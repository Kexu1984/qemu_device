#!/usr/bin/env python3
"""
MMIO Device Server — transport + dispatch layer for KX6625 peripheral models.
=============================================================================

Architecture
------------

  QEMU kx6625 machine (scripts/qemu-fork/hw/arm/kx6625.c)
    │  one TCP chardev pair per mmio-sockdev instance
    ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  Transport servers (this file)                                           │
  │  RWServer        — MMIO R/W channel (one per device, QEMU → Python)     │
  │  IRQServer       — IRQ injection channel (Python → QEMU, per device)    │
  │  TickServer      — virtual-clock tick channel (QEMU → Python)           │
  │  MemServer       — bus-master DMA memory channel (Python ↔ QEMU RAM)    │
  │  RstServer       — WDT system-reset channel (Python → QEMU)            │
  │  CruNotifyServer — CRU device-reset notifications (QEMU → Python, opt) │
  └──────────────────────────────┬───────────────────────────────────────────┘
                                 │ absolute-address dispatch
  ┌──────────────────────────────▼───────────────────────────────────────────┐
  │  MMIOBus  (address-range router → MMIODevice instances)                  │
  └─┬──────┬──────┬─────────┬─────┬─────┬─────┬─────┬──────────────────────┘
    │      │      │         │     │     │     │     │
  UART   DMA  Timer  DmaDemo CRC  WDT  HSM  OTP  FlashCtrl
 40004  40005  40006   40007 40008 40009 4000C 4000D  4000E   (base ×0x1000)

  Native QEMU devices (no Python model, implemented in kx6625.c):
    SYSCTRL @ 0x4000A000,  CRU @ 0x4000F000

  SystemVerilog bridge (separate sv_timer_bridge process, ports 7906/7907/7912):
    sv_timer @ 0x4000B000

Port assignments (all 127.0.0.1):
  UART      RW=7890  IRQ=7891  TERM=7904
  DMA       RW=7892  IRQ=7893  MEM=7897  TICK=7905
  Timer     RW=7894  IRQ=7895  TICK=7896
  DmaDemo   RW=7898  IRQ=7899
  CRC       RW=7900
  WDT       RW=7901  IRQ=7902  RST=7903
  sv_timer  RW=7906  IRQ=7907  MEM=7912  (sv_timer_bridge, not this server)
  HSM       RW=7908  IRQ=7909
  OTP       RW=7910  IRQ=7911
  FlashCtrl RW=7913  IRQ=7914  MEM=7915
  DFlash    RW=7916
  CRU-NOTIFY=7917  (optional; not yet wired in e2e_test.sh / run_interactive.sh)

Adding a new device
-------------------
1. Create ``device_model/<name>_model.py`` subclassing ``MMIODevice``.
2. Register it in ``device_model/soc_top.py`` (``kx6625_default()``).
3. Add matching ``-chardev``/``-device`` pairs to the QEMU command lines in
   ``scripts/e2e_test.sh`` and ``scripts/run_interactive.sh``.

Wire protocols
--------------
R/W  (QEMU → Python, per mmio-sockdev chardev)
  Read:  'R'(1B) | master_id(1B) | offset(4B LE) | size(1B)
         ← data(sizeB LE)
  Write: 'W'(1B) | master_id(1B) | offset(4B LE) | size(1B) | data(sizeB LE)
         ← next_event_ns(8B LE)  — 0: no event; >0: DES tick at that virtual time
IRQ  (Python → QEMU, irq-chardev)
  'I'(1B) | irq_idx(1B) | level(1B)   — level: 1=assert, 0=deassert
Tick  (QEMU → Python, tick-chardev)
  'T'(1B) | vtime_ns(8B LE)
MEM  (Python ↔ QEMU, mem-chardev — bus-master DMA)
  Write: 'M'(1B) | 'W'(1B) | phys_addr(8B LE) | length(4B LE) | data(lengthB)
  Read:  'M'(1B) | 'R'(1B) | phys_addr(8B LE) | length(4B LE)  ← data(lengthB)
RST  (Python → QEMU, rst-chardev)
  any byte → QEMU calls qemu_system_reset_request()
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path for sibling package imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_model.mmio_base         import AddressSpace, IRQController, MemChannel, MMIODevice, recv_exact  # noqa: E402
from device_model.uart_model        import ConsoleUartDevice                      # noqa: E402
from device_model.timer_model       import TimerDevice                            # noqa: E402
from device_model.dma_controller    import DmaController                          # noqa: E402
from device_model.dma_client_demo   import DmaClientDemoDevice                    # noqa: E402
from device_model.crc_device        import CrcDevice                              # noqa: E402
from device_model.wdt_model         import WdtDevice                              # noqa: E402
from device_model.tracer            import Tracer                                  # noqa: E402


# ---------------------------------------------------------------------------
# Address-range dispatcher
# ---------------------------------------------------------------------------

class MMIOBus:
    """
    Maps absolute address ranges to ``MMIODevice`` instances and dispatches
    read/write operations.

    The ``RWServer`` adds the mmio-sockdev base address to the QEMU-supplied
    offset before calling ``read()``/``write()``, so all addresses here are
    absolute.

    Example
    -------
    ::

        bus = MMIOBus()
        bus.register(0x10020000, 0x1000, ConsoleUartDevice(...))
        bus.register(0x10030000, 0x1000, DmaDevice(...))
    """

    def __init__(self) -> None:
        self._entries: list = []         # list[tuple[int, int, MMIODevice]]
        self._tick_observers: list = []  # objects that only need on_tick()

    def register(self, base: int, size: int, device: MMIODevice) -> None:
        """Register *device* at the address range [base, base+size)."""
        for b, s, d in self._entries:
            if base < b + s and base + size > b:
                raise ValueError(
                    f'{device.name}: [0x{base:x}, 0x{base+size:x}) overlaps '
                    f'{d.name} at [0x{b:x}, 0x{b+s:x})'
                )
        self._entries.append((base, size, device))
        print(f'[BUS] {device.name:20s}  base=0x{base:08x}  size=0x{size:x}')

    def _find(self, addr: int) -> tuple[Optional[MMIODevice], int]:
        for base, size, device in self._entries:
            if base <= addr < base + size:
                return device, addr - base
        return None, 0

    def read(self, addr: int, size: int, master_id: int = 0) -> bytes:
        device, offset = self._find(addr)
        if device is None:
            print(f'[BUS] unmapped read  0x{addr:08x} size={size}', file=sys.stderr)
            return b'\x00' * size
        return device.read(offset, size, master_id)

    def write(self, addr: int, size: int, data: bytes, master_id: int = 0) -> int:
        device, offset = self._find(addr)
        if device is None:
            print(f'[BUS] unmapped write 0x{addr:08x} size={size}', file=sys.stderr)
            return 0
        result = device.write(offset, size, data, master_id)
        # Device may return int (DES next_event_ns) or None (legacy devices).
        return result if isinstance(result, int) else 0

    def add_tick_observer(self, observer: object) -> None:
        """Register an object that should receive on_tick() calls.

        Use this for non-MMIO objects (e.g. a shared DmaController) that
        need virtual-clock ticks but are not mapped into the address space.
        The observer must implement ``on_tick(vtime_ns: int)``.
        """
        self._tick_observers.append(observer)

    def tick_all(self, vtime_ns: int) -> int:
        """Broadcast a virtual-clock tick to every registered device and
        every tick observer registered via add_tick_observer().

        Each device's ``on_tick()`` is called in registration order.
        Devices with no timing needs use the default no-op from MMIODevice.
        Returns 0 (tick responses are not used for the shared tick channel).
        """
        for _base, _size, device in self._entries:
            device.on_tick(vtime_ns)
        for observer in self._tick_observers:
            observer.on_tick(vtime_ns)
        return 0


# ---------------------------------------------------------------------------
# Transport: R/W channel
# ---------------------------------------------------------------------------

class RWServer:
    """
    Accepts QEMU's main chardev TCP connection.

    Parses the binary MMIO protocol, computes the absolute address
    (``base_addr + offset``), and delegates R/W operations to the bus.
    Pure transport: no device semantics here.
    """

    def __init__(self, port: int, bus: MMIOBus, base_addr: int) -> None:
        self.port      = port
        self.bus       = bus
        self.base_addr = base_addr
        self._sock: Optional[socket.socket] = None
        self._running  = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[RW]  QEMU connected from {addr}')
        try:
            while self._running:
                op_byte = conn.recv(1)
                if not op_byte:
                    break
                op = op_byte[0]

                if op == ord('R'):
                    hdr       = recv_exact(conn, 6)    # master_id(1B) + offset(4B LE) + size(1B)
                    master_id = hdr[0]
                    offset    = struct.unpack('<I', hdr[1:5])[0]
                    size      = hdr[5]
                    data      = self.bus.read(self.base_addr + offset, size, master_id)
                    conn.sendall(data)

                elif op == ord('W'):
                    hdr           = recv_exact(conn, 6)    # master_id(1B) + offset(4B LE) + size(1B)
                    master_id     = hdr[0]
                    offset        = struct.unpack('<I', hdr[1:5])[0]
                    size          = hdr[5]
                    payload       = recv_exact(conn, size)
                    next_event_ns = self.bus.write(self.base_addr + offset, size, payload, master_id)
                    # DES protocol: always send 8-byte little-endian response.
                    # QEMU reads this and schedules a precise tick if > 0.
                    conn.sendall(struct.pack('<Q', next_event_ns))

                else:
                    print(f'[RW]  unknown opcode 0x{op:02x}', file=sys.stderr)
                    break

        except (ConnectionError, OSError) as exc:
            if self._running:
                print(f'[RW]  {addr}: {exc}', file=sys.stderr)
        finally:
            conn.close()
            print(f'[RW]  QEMU disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(4)
        self._running = True
        print(f'[RW]  Listening on port {self.port}  base=0x{self.base_addr:08x}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[RW]  accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None


# ---------------------------------------------------------------------------
# Transport: IRQ channel
# ---------------------------------------------------------------------------

class IRQServer:
    """
    Accepts QEMU's irq-chardev TCP connection and hands the socket to the
    shared ``IRQController``.

    Pure transport: all IRQ timing and logic lives in individual devices.
    This class just plumbs the TCP socket through to the controller.
    """

    def __init__(self, port: int, irq_controller: IRQController) -> None:
        self.port = port
        self.ctrl = irq_controller
        self._sock: Optional[socket.socket] = None
        self._running = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[IRQ] QEMU irq-chardev connected from {addr}')
        self.ctrl._on_connect(conn)
        try:
            conn.settimeout(1.0)
            while self._running:
                try:
                    data = conn.recv(64)
                    if not data:
                        break
                    # QEMU should never send data on the IRQ channel; log it.
                    print(f'[IRQ] unexpected data from QEMU: {data!r}',
                          file=sys.stderr)
                except socket.timeout:
                    continue
        except OSError:
            pass
        finally:
            self.ctrl._on_disconnect()
            conn.close()
            print(f'[IRQ] QEMU irq-chardev disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(1)
        self._running = True
        print(f'[IRQ] Listening on port {self.port}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[IRQ] accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# Device defaults — mirror spec/devices.yaml.
# These are the canonical runtime values; override per device via CLI args.
_UART_BASE      = 0x40004000
_UART_SIZE      = 0x1000
_UART_RW_PORT   = 7890
_UART_IRQ_PORT  = 7891
_UART_IRQ_DELAY = 2.0

_DMA_BASE       = 0x40005000
_DMA_SIZE       = 0x1000
_DMA_RW_PORT    = 7892
_DMA_IRQ_PORT   = 7893
_DMA_MEM_PORT   = 7897   # Python → QEMU physical memory (DMA bus-master channel)

_TIMER_BASE     = 0x40006000
_TIMER_SIZE     = 0x1000
_TIMER_RW_PORT   = 7894
_TIMER_IRQ_PORT  = 7895
_TIMER_TICK_PORT = 7896   # QEMU → Python virtual-clock tick channel

_DEMO_BASE       = 0x40007000
_DEMO_SIZE       = 0x1000
_DEMO_RW_PORT    = 7898
_DEMO_IRQ_PORT   = 7899

_CRC_BASE        = 0x40008000
_CRC_SIZE        = 0x1000
_CRC_RW_PORT     = 7900

_WDT_BASE        = 0x40009000
_WDT_SIZE        = 0x1000
_WDT_RW_PORT     = 7901
_WDT_IRQ_PORT    = 7902
_WDT_RST_PORT    = 7903   # Python → QEMU system-reset channel

_DMA_TICK_PORT   = 7905   # QEMU → Python DES tick channel for DMA (tick-period-ms=0)

_UART_TERM_PORT  = 7904   # Python → external terminal (firmware UART output)


# ---------------------------------------------------------------------------
# Transport: virtual-clock tick channel  (QEMU → Python)
# ---------------------------------------------------------------------------

class TickServer:
    """
    Accepts QEMU's tick-chardev TCP connection and dispatches virtual-clock
    ticks to a device or the whole bus.

    QEMU sends  'T'(1B) | vtime_ns(8B LE)  on every tick.  This server
    calls ``tick_fn(vtime_ns)`` synchronously for each message.  The tick is
    fire-and-forget on the QEMU side (no response expected), so on_tick()
    may do blocking I/O (e.g. DMA memory transfers) without deadlocking.

    Usage::

        # Shared 1 ms periodic tick for all bus devices:
        tick_server = TickServer(port=7896, tick_fn=bus.tick_all)

        # Dedicated DES tick for DMA (tick_period_ms=0, one-shot):
        dma_tick = TickServer(port=7905, tick_fn=dma_ctrl.on_tick)
    """

    _TICK_MSG_SIZE = 9   # 'T'(1B) + vtime_ns(8B LE)

    def __init__(self, port: int, tick_fn) -> None:
        self.port      = port
        self._tick_fn  = tick_fn
        self._sock: Optional[socket.socket] = None
        self._running  = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[TICK] QEMU tick-chardev connected from {addr}')
        try:
            while self._running:
                hdr = recv_exact(conn, self._TICK_MSG_SIZE)
                if hdr[0] != ord('T'):
                    print(f'[TICK] unexpected byte 0x{hdr[0]:02x}, skipping',
                          file=sys.stderr)
                    continue
                vtime_ns = int.from_bytes(hdr[1:9], 'little')
                self._tick_fn(vtime_ns)
        except (ConnectionError, OSError) as exc:
            if self._running:
                print(f'[TICK] {addr}: {exc}', file=sys.stderr)
        finally:
            conn.close()
            print(f'[TICK] QEMU tick-chardev disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(1)
        self._running = True
        print(f'[TICK] Listening on port {self.port}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[TICK] accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None


# ---------------------------------------------------------------------------
# Transport: DMA memory channel  (Python → QEMU physical memory)
# ---------------------------------------------------------------------------

class MemServer:
    """
    Accepts QEMU's mem-chardev TCP connection and registers it with
    the shared ``MemChannel``.

    Once connected, all I/O is owned by ``MemChannel.dma_write()`` /
    ``dma_read()`` (called from the DMA device's ``on_tick()`` handler).
    This thread simply waits for the channel to close, then accepts the
    next connection.

    Usage::

        mem_ch  = MemChannel()
        mem_srv = MemServer(port=7897, mem_channel=mem_ch)
        threading.Thread(target=mem_srv.start, daemon=True).start()
    """

    def __init__(self, port: int, mem_channel: MemChannel) -> None:
        self.port  = port
        self._chan  = mem_channel
        self._sock: Optional[socket.socket] = None
        self._running = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[MEM]  QEMU mem-chardev connected from {addr}')
        self._chan._on_connect(conn)
        # All socket I/O is performed exclusively by MemChannel.dma_write/read.
        # Block here until MemChannel signals close (I/O error or stop()).
        self._chan.wait_for_close()
        self._chan._on_disconnect()
        try:
            conn.close()
        except OSError:
            pass
        print(f'[MEM]  QEMU mem-chardev disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(1)
        self._running = True
        print(f'[MEM]  Listening on port {self.port}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[MEM]  accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self._chan.stop()   # unblocks any waiting _handle_client
        if self._sock:
            self._sock.close()
            self._sock = None


# ---------------------------------------------------------------------------
# Transport: system-reset channel  (Python → QEMU via rst-chardev)
# ---------------------------------------------------------------------------

class RstServer:
    """
    Accepts QEMU's rst-chardev TCP connection and hands the socket to the
    shared ``RstController``.

    When WdtDevice times out it calls SystemResetManager.wdt_reset(), which
    calls RstController.send_reset(), which writes a byte here.  QEMU receives
    the byte and calls qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET).
    """

    def __init__(self, port: int, rst_controller) -> None:
        self.port  = port
        self.ctrl  = rst_controller
        self._sock: Optional[socket.socket] = None
        self._running = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[RST] QEMU rst-chardev connected from {addr}')
        self.ctrl._on_connect(conn)
        try:
            conn.settimeout(1.0)
            while self._running:
                try:
                    data = conn.recv(64)
                    if not data:
                        break
                    print(f'[RST] unexpected data from QEMU: {data!r}',
                          file=sys.stderr)
                except socket.timeout:
                    continue
        except OSError:
            pass
        finally:
            self.ctrl._on_disconnect()
            conn.close()
            print(f'[RST] QEMU rst-chardev disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(1)
        self._running = True
        print(f'[RST] Listening on port {self.port}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[RST] accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None



def main() -> None:
    parser = argparse.ArgumentParser(
        description='MMIO Device Server — transport + dispatch for all peripherals',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # UART options (used for the e2e test)
    parser.add_argument('--uart-rw-port',  type=int,   default=_UART_RW_PORT,
                        help='UART R/W channel TCP port')
    parser.add_argument('--uart-irq-port', type=int,   default=_UART_IRQ_PORT,
                        help='UART IRQ channel TCP port')
    parser.add_argument('--uart-irq-delay', type=float, default=_UART_IRQ_DELAY,
                        help='Seconds before UART demo IRQ fires')
    parser.add_argument('--uart-term-port', type=int,   default=_UART_TERM_PORT,
                        help='UART terminal output TCP port (connect: nc 127.0.0.1 <port>)')
    parser.add_argument('--trace-file', default='build/device_trace.jsonl',
                        help='Path for device event trace output (JSONL format)')
    parser.add_argument('--no-trace', action='store_true',
                        help='Disable event tracing')
    # Legacy short aliases kept for backward compatibility with e2e_test.sh
    parser.add_argument('--port',      type=int,   default=None,
                        help='Alias for --uart-rw-port')
    parser.add_argument('--irq-port',  type=int,   default=None,
                        help='Alias for --uart-irq-port')
    parser.add_argument('--irq-delay', type=float, default=None,
                        help='Alias for --uart-irq-delay')
    args = parser.parse_args()

    # Apply legacy aliases
    uart_rw_port   = args.port      if args.port      is not None else args.uart_rw_port
    uart_irq_port  = args.irq_port  if args.irq_port  is not None else args.uart_irq_port
    uart_irq_delay = args.irq_delay if args.irq_delay is not None else args.uart_irq_delay

    # ── Event tracer ─────────────────────────────────────────────────────
    tracer: Tracer | None = None
    if not args.no_trace:
        tracer = Tracer(args.trace_file)
        print(f'[tracer] recording to {args.trace_file}')

    # ── SoCTop: KX6625 default topology ──────────────────────────────────
    # Function-level import avoids the circular-import that would arise from
    # a top-level import: soc_top imports transport classes from this module,
    # so this module must not import soc_top at the top level.
    from device_model.soc_top import kx6625_default  # noqa: PLC0415

    soc = kx6625_default(
        uart_rw_port   = uart_rw_port,
        uart_irq_port  = uart_irq_port,
        uart_irq_delay = uart_irq_delay,
        uart_term_port = args.uart_term_port,
        tracer         = tracer,
    )
    soc.start()

if __name__ == '__main__':
    main()
