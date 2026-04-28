"""
mmio_base — Shared base classes for MMIO device models.

Provides:
  recv_exact(sock, n) → bytes   — reliable socket receive helper
  MMIODevice                    — abstract base class for all device models
  IRQController                 — thread-safe IRQ injection into QEMU
  MemChannel                    — bus-master DMA channel into QEMU physical memory

This module has no device-specific logic; it is imported by every device
model (uart_model.py, dma_model.py, …) and by mmio_device_server.py.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
from abc import ABC, abstractmethod
from typing import Optional


# ---------------------------------------------------------------------------
# Socket helper
# ---------------------------------------------------------------------------

def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly *n* bytes; raise ConnectionError on EOF."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('connection closed')
        buf += chunk
    return buf


# ---------------------------------------------------------------------------
# Device base class
# ---------------------------------------------------------------------------

class MMIODevice(ABC):
    """
    Abstract base for all peripheral device implementations.

    All addresses passed to ``read()`` / ``write()`` are *offsets* from the
    base address registered on the bus, so devices always start at offset 0.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable device name (used in log messages)."""

    @abstractmethod
    def read(self, offset: int, size: int) -> bytes:
        """Return ``size`` bytes of register data at ``offset``."""

    @abstractmethod
    def write(self, offset: int, size: int, data: bytes) -> None:
        """Write ``data`` to the register at ``offset``."""

    def on_reset(self) -> None:
        """Optional: called when the system is reset."""

    def on_tick(self, vtime_ns: int) -> None:
        """
        Optional: called on every virtual-clock tick from QEMU.

        ``vtime_ns`` is the current QEMU_CLOCK_VIRTUAL value in nanoseconds.
        Devices that need timing (timers, DMA latency, etc.) override this
        method to advance their internal state.  The default is a no-op so
        that devices without timing requirements need not implement it.
        """


# ---------------------------------------------------------------------------
# IRQ controller  (one instance shared by all devices)
# ---------------------------------------------------------------------------

class IRQController:
    """
    Injects level-triggered interrupts into QEMU over the irq-chardev
    TCP channel.  Thread-safe: any device thread may call ``set_irq()``
    at any time.

    If the IRQ channel has not yet connected, ``set_irq()`` returns False.
    Use ``wait_connected()`` to block until the channel is ready.
    """

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._connected = threading.Event()

    # -- called by IRQServer ----------------------------------------------

    def _on_connect(self, sock: socket.socket) -> None:
        with self._lock:
            self._sock = sock
        self._connected.set()

    def _on_disconnect(self) -> None:
        with self._lock:
            self._sock = None
        self._connected.clear()

    # -- public API for devices -------------------------------------------

    def wait_connected(self, timeout: Optional[float] = None) -> bool:
        """Block until QEMU connects the IRQ channel (or ``timeout`` expires)."""
        return self._connected.wait(timeout)

    def set_irq(self, irq_idx: int, level: int) -> bool:
        """
        Assert (``level=1``) or deassert (``level=0``) IRQ line *irq_idx*.

        Returns ``True`` on success, ``False`` if the channel is not open.
        """
        with self._lock:
            if self._sock is None:
                return False
            try:
                self._sock.sendall(
                    bytes([ord('I'), irq_idx & 0xFF, 1 if level else 0])
                )
                return True
            except OSError as exc:
                print(f'[IRQ] send error: {exc}', file=sys.stderr)
                return False


# ---------------------------------------------------------------------------
# DMA / bus-master memory channel
# ---------------------------------------------------------------------------

class MemChannel:
    """
    Bus-master DMA channel: Python device model → QEMU physical memory.

    A Python device that acts as a DMA master (e.g., a DMA controller,
    network card, or NPU) uses this class to read from and write to QEMU's
    physical address space, modelling how real devices perform bus-master DMA.

    Protocol (Python → QEMU, over mem-chardev TCP channel):
      DMA write: 'M'(1B) | 'W'(1B) | phys_addr(8B LE) | length(4B LE) | data(lengthB)
      DMA read:  'M'(1B) | 'R'(1B) | phys_addr(8B LE) | length(4B LE)
                 QEMU responds: data(lengthB)

    Thread safety:
      ``dma_write()`` and ``dma_read()`` are serialised by an internal lock.
      Only one DMA operation may be in flight at a time (which matches how
      the TickServer drives DMA completion — single-threaded).

    Typical lifecycle::

        # In mmio_device_server.py:
        mem_channel = MemChannel()
        mem_server  = MemServer(port=7897, mem_channel=mem_channel)
        threading.Thread(target=mem_server.start, daemon=True).start()

        # In DmaDevice.on_tick() — called from TickServer thread:
        data = mem_channel.dma_read(src_addr, length)
        if data:
            mem_channel.dma_write(dst_addr, data)
    """

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._lock      = threading.Lock()    # serialises all socket I/O
        self._connected = threading.Event()
        self._close_evt = threading.Event()   # set on I/O error or stop()

    # -- called by MemServer ----------------------------------------------

    def _on_connect(self, sock: socket.socket) -> None:
        self._close_evt.clear()
        with self._lock:
            self._sock = sock
        self._connected.set()

    def _on_disconnect(self) -> None:
        with self._lock:
            self._sock = None
        self._connected.clear()

    def _signal_close(self) -> None:
        """Mark the channel as closed; unblocks MemServer._handle_client."""
        self._connected.clear()
        self._close_evt.set()

    def wait_for_close(self) -> None:
        """Block until the channel closes or ``stop()`` is called."""
        self._close_evt.wait()

    def stop(self) -> None:
        """Force-close the channel (called by MemServer.stop())."""
        self._signal_close()
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    # -- public API for device models -------------------------------------

    def wait_connected(self, timeout: Optional[float] = None) -> bool:
        """Return True when QEMU connects the mem-chardev."""
        return self._connected.wait(timeout)

    def dma_write(self, phys_addr: int, data: bytes) -> bool:
        """
        Write *data* to QEMU physical address *phys_addr*.

        Models a DMA engine writing a result buffer (e.g., completed DMA
        transfer, device output) into system RAM.  Returns ``True`` on
        success, ``False`` if the channel is disconnected or an I/O error
        occurs.
        """
        with self._lock:
            if self._sock is None:
                return False
            try:
                hdr = b'M' + b'W' + struct.pack('<QI', phys_addr, len(data))
                self._sock.sendall(hdr + data)
                return True
            except OSError as exc:
                print(f'[MEM]  dma_write error: {exc}', file=sys.stderr)
                self._signal_close()
                return False

    def dma_read(self, phys_addr: int, length: int) -> Optional[bytes]:
        """
        Read *length* bytes from QEMU physical address *phys_addr*.

        Models a DMA engine reading a source buffer from system RAM (e.g.,
        memory-to-memory copy, device descriptor fetch).  Returns the data
        on success, ``None`` on error.

        This call blocks until QEMU sends the response.  Since DMA
        completions are driven single-threaded via ``on_tick()``, there is
        at most one outstanding read at any time.
        """
        with self._lock:
            if self._sock is None:
                return None
            try:
                hdr = b'M' + b'R' + struct.pack('<QI', phys_addr, length)
                self._sock.sendall(hdr)
                return recv_exact(self._sock, length)
            except (OSError, ConnectionError) as exc:
                print(f'[MEM]  dma_read error: {exc}', file=sys.stderr)
                self._signal_close()
                return None
