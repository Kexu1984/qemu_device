"""
tracer.py — Lightweight event tracer for the Python device model layer.

Architecture
------------

    Device thread             Background writer thread
    ─────────────             ────────────────────────
    DeviceTracer.emit()   →   queue.Queue   →   file I/O (JSONL)

Device threads never block on file I/O.  The writer thread drains the
queue continuously and flushes every ``flush_every`` records (default 32)
so the file is usable with ``tail -f`` during a live run.

Usage — server side (``mmio_device_server.py``)
------------------------------------------------
::

    tracer = Tracer("build/device_trace.jsonl")
    uart_dev = ConsoleUartDevice(..., tracer=tracer)
    timer_dev = TimerDevice(...,      tracer=tracer)
    ...
    tracer.close()          # flush + join writer thread

Usage — device model
--------------------
::

    from device_model.tracer import Tracer, DeviceTracer, NULL_DEVICE_TRACER

    class MyDevice(MMIODevice):
        def __init__(self, ..., tracer: Optional[Tracer] = None) -> None:
            self._tr: DeviceTracer = (
                tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
            )

        def on_tick(self, vtime_ns: int) -> None:
            self._tr.tick(vtime_ns)   # update virtual-time context
            if self._clock.is_expired(self._load_ms):
                self._tr.emit("EXPIRE", load_ms=self._load_ms)

        def write(self, offset, size, data):
            ...
            self._tr.emit("TX", ch=ch, ascii=chr(ch) if 0x20 <= ch < 0x7F else None)

Record format (JSONL)
---------------------
One JSON object per line.  All fields are at the top level (flat, no nested
``data`` sub-dict) to make ``jq`` / ``pandas`` queries as simple as possible.

Required fields on every record:

    seq        int   — global monotonically increasing sequence number
    t_wall_ns  int   — wall-clock time in ns (time.monotonic_ns())
    t_virt_ns  int   — last known QEMU virtual-clock time in ns
                       (0 before first tick, or for devices without on_tick)
    dev        str   — device name (from MMIODevice.name)
    event      str   — event type, UPPER_SNAKE_CASE

Additional fields are appended from the kwargs passed to ``emit()``.

First record in every file is a header::

    {"seq":0,"t_wall_ns":…,"t_virt_ns":0,"dev":"__tracer__","event":"HEADER",
     "version":"1","pid":12345,"path":"build/device_trace.jsonl"}

Example records::

    {"seq":1,"t_wall_ns":1714399200123456789,"t_virt_ns":0,"dev":"uart","event":"TX","ch":65,"ascii":"A"}
    {"seq":2,"t_wall_ns":1714399202000000000,"t_virt_ns":2000000000,"dev":"timer0","event":"EXPIRE","load_ms":100}
    {"seq":3,"t_wall_ns":1714399202001000000,"t_virt_ns":2000000000,"dev":"timer0","event":"IRQ_PULSE","irq_idx":2}

Offline analysis
----------------
Filter by device::

    jq 'select(.dev=="timer0")' build/device_trace.jsonl

All TICK events in virtual-time order::

    jq -s 'sort_by(.t_virt_ns) | .[] | select(.event=="EXPIRE")' build/device_trace.jsonl

Print a summary table::

    python3 -c "
    import json, sys, collections
    counts = collections.Counter()
    for line in open('build/device_trace.jsonl'):
        r = json.loads(line)
        counts[(r['dev'], r['event'])] += 1
    for (dev, ev), n in sorted(counts.items()):
        print(f'{dev:20s}  {ev:20s}  {n}')
    "
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Optional


# ---------------------------------------------------------------------------
# DeviceTracer — per-device handle
# ---------------------------------------------------------------------------

class DeviceTracer:
    """
    Per-device trace handle.  Obtained from ``Tracer.context(dev_name)``.

    Maintains its own ``_vtime_ns`` field so emit() calls always carry the
    virtual-time context set by the most recent ``tick()`` call — even when
    the event occurs inside ``read()`` / ``write()`` (which have no vtime
    parameter).

    All methods on the ``NULL_DEVICE_TRACER`` singleton are no-ops.
    """

    __slots__ = ('_tracer', '_dev', '_vtime_ns')

    def __init__(self, tracer: Optional['Tracer'], dev: str) -> None:
        self._tracer   = tracer
        self._dev      = dev
        self._vtime_ns = 0

    def tick(self, vtime_ns: int) -> None:
        """
        Update the virtual-time context for this device.

        Call once at the very start of ``on_tick(vtime_ns)`` before any
        ``emit()`` calls inside that tick handler.  All subsequent emits
        (including those triggered from within ``on_tick``) will carry this
        vtime automatically.
        """
        self._vtime_ns = vtime_ns

    def emit(self, event: str, **data) -> None:
        """
        Record a trace event.

        *event* should be UPPER_SNAKE_CASE (e.g. ``"TX"``, ``"EXPIRE"``,
        ``"IRQ_PULSE"``).  Additional keyword arguments are merged into the
        top-level record alongside the standard fields.

        This call is non-blocking: the record is placed on an internal queue
        and written by a background thread.
        """
        if self._tracer is not None:
            self._tracer._put(self._dev, event, self._vtime_ns, data)


class _NullDeviceTracer(DeviceTracer):
    """Singleton no-op tracer for devices constructed without a Tracer."""

    __slots__ = ()

    def __init__(self) -> None:
        # Don't call super().__init__ — _tracer stays None
        super().__init__(None, '')

    def tick(self, vtime_ns: int) -> None:   # type: ignore[override]
        pass

    def emit(self, event: str, **data) -> None:   # type: ignore[override]
        pass


# Module-level singleton — used when no Tracer is provided.
NULL_DEVICE_TRACER: DeviceTracer = _NullDeviceTracer()


# ---------------------------------------------------------------------------
# Tracer — manages the background writer and vends DeviceTracer contexts
# ---------------------------------------------------------------------------

class Tracer:
    """
    Central trace coordinator.

    Create one instance per simulation run; pass it to every device that
    should emit traces.  Call ``close()`` at shutdown to flush all pending
    records and join the writer thread.

    Parameters
    ----------
    path : str
        Output file path.  Parent directories are created if absent.
        An existing file at *path* is overwritten.
    flush_every : int
        Flush the output file after every *flush_every* records (default 32).
        Lower values give more real-time visibility; higher values improve
        throughput.
    """

    def __init__(self, path: str, *, flush_every: int = 32) -> None:
        self._path        = path
        self._flush_every = flush_every
        self._queue: queue.Queue = queue.Queue()
        self._seq         = 0
        self._lock        = threading.Lock()   # guards _seq counter

        # Create parent directories.
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        self._thread = threading.Thread(
            target=self._writer_loop,
            name='tracer-writer',
            daemon=True,
        )
        self._thread.start()

        # Emit the header record synchronously to guarantee it is first.
        self._put('__tracer__', 'HEADER', 0, {
            'version': '1',
            'pid':     os.getpid(),
            'path':    str(os.path.abspath(path)),
        })

    # ── Public API ────────────────────────────────────────────────────────

    def context(self, dev: str) -> DeviceTracer:
        """
        Return a ``DeviceTracer`` bound to *dev*.

        Typically called once in each device's ``__init__``::

            self._tr = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
        """
        return DeviceTracer(self, dev)

    def close(self) -> None:
        """
        Flush all pending records, close the output file, and join the
        writer thread.  Should be called in the server's ``finally`` block.
        """
        self._queue.put(None)           # sentinel — tells writer to stop
        self._thread.join(timeout=10)

    # ── Internal ──────────────────────────────────────────────────────────

    def _put(self, dev: str, event: str, vtime_ns: int, data: dict) -> None:
        """Assemble a record and enqueue it.  Thread-safe; non-blocking."""
        with self._lock:
            seq = self._seq
            self._seq += 1
        record = {
            'seq':       seq,
            't_wall_ns': time.monotonic_ns(),
            't_virt_ns': vtime_ns,
            'dev':       dev,
            'event':     event,
        }
        record.update(data)
        self._queue.put(record)

    def _writer_loop(self) -> None:
        """Background writer thread: drain queue → JSONL file."""
        pending = 0
        try:
            with open(self._path, 'w', encoding='utf-8') as fh:
                while True:
                    try:
                        item = self._queue.get(timeout=0.5)
                    except queue.Empty:
                        if pending:
                            fh.flush()
                            pending = 0
                        continue

                    if item is None:
                        break   # sentinel — flush and exit

                    fh.write(json.dumps(item, separators=(',', ':')) + '\n')
                    pending += 1
                    if pending >= self._flush_every:
                        fh.flush()
                        pending = 0

                # Drain any remaining items after sentinel.
                while True:
                    try:
                        item = self._queue.get_nowait()
                        if item is not None:
                            fh.write(json.dumps(item, separators=(',', ':')) + '\n')
                    except queue.Empty:
                        break
                fh.flush()
        except Exception as exc:
            import sys
            print(f'[Tracer] writer error: {exc}', file=sys.stderr)
