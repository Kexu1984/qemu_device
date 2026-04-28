#!/usr/bin/env python3
"""
MMIO Device Server — Layered QEMU Peripheral Emulation
=======================================================

Architecture
------------

  ┌──────────────────────────────────────────────────────────────┐
  │  RWServer (port 7890)         IRQServer (port 7891)          │  Transport
  │  TCP + binary MMIO protocol   TCP + IRQ injection channel    │
  └───────────────┬───────────────────────────┬──────────────────┘
                  │ abs_addr = base + offset   │ IRQController
  ┌───────────────▼───────────────────────────▼──────────────────┐
  │                          MMIOBus                             │  Dispatch
  │        abs_addr → find registered device → compute offset   │
  └──────────┬─────────────────────────┬────────────────────────┘
  ┌──────────▼──────────┐   ┌──────────▼──────────┐
  │  ConsoleUartDevice  │   │   <YourDevice>      │  Devices
  │  @ 0x10020000       │   │   @ 0x10030000      │
  └─────────────────────┘   └─────────────────────┘

Adding a new device
-------------------
1. Subclass ``MMIODevice``, implement ``read(offset, size)`` and
   ``write(offset, size, data)``.
2. In ``main()``, call ``bus.register(base_addr, size, MyDevice(...))``.
3. Add a matching ``-chardev``/``-device`` pair to the QEMU command line
   (new mmio-sockdev at the new base address on a new port), or place the
   new device inside the existing 4 KB region using sub-offsets.

R/W Protocol  (QEMU → Python, per mmio-sockdev instance)
  Read:   'R'(1B) | offset(4B LE) | size(1B)  →  data(sizeB LE)
  Write:  'W'(1B) | offset(4B LE) | size(1B) | data(sizeB LE)

IRQ Protocol  (Python → QEMU, shared irq-chardev)
  'I'(1B) | irq_idx(1B) | level(1B)
  irq_idx: index of the IRQ output line on the mmio-sockdev (0-based)
  level:   1 = assert, 0 = deassert
"""

from __future__ import annotations

import socket
import struct
import sys
import argparse
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional


# ---------------------------------------------------------------------------
# Helper
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
        self._entries: list = []  # list[tuple[int, int, MMIODevice]]

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

    def read(self, addr: int, size: int) -> bytes:
        device, offset = self._find(addr)
        if device is None:
            print(f'[BUS] unmapped read  0x{addr:08x} size={size}', file=sys.stderr)
            return b'\x00' * size
        return device.read(offset, size)

    def write(self, addr: int, size: int, data: bytes) -> None:
        device, offset = self._find(addr)
        if device is None:
            print(f'[BUS] unmapped write 0x{addr:08x} size={size}', file=sys.stderr)
            return
        device.write(offset, size, data)


# ---------------------------------------------------------------------------
# Built-in device: Console UART
# ---------------------------------------------------------------------------

class ConsoleUartDevice(MMIODevice):
    """
    Simple UART-like console device.

    Offset  Name    Access  Description
    ------  ------  ------  ----------------------------------------
    0x00    TXDATA  W       Write byte to stdout (bits [7:0])
    0x04    STATUS  R       bit0 = TXREADY (always 1)
    0x08    CTRL    R/W     bit0 = ENABLE (default 1)

    Interrupt support
    -----------------
    Optionally fires a **one-shot IRQ** *irq_delay* seconds after the IRQ
    channel connects.  This simulates a device-complete notification, the
    same pattern real hardware uses when a TX buffer drains and raises a
    TX-empty interrupt.

    Parameters
    ----------
    irq_controller:
        Shared ``IRQController`` instance.  Pass ``None`` to disable IRQs.
    irq_idx:
        Index of the IRQ output line on the mmio-sockdev (matches the
        ``irq_idx`` byte in the 'I' protocol message).
    irq_delay:
        Seconds to wait (after the IRQ channel connects) before firing.
    """

    _TXDATA  = 0x00
    _STATUS  = 0x04
    _CTRL    = 0x08
    _REGSIZE = 0x10

    def __init__(
        self,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        irq_delay: float = 2.0,
    ) -> None:
        self._regs = bytearray(self._REGSIZE)
        self._regs[self._CTRL] = 0x01         # ENABLE=1 by default

        self._irq_ctrl  = irq_controller
        self._irq_idx   = irq_idx
        self._irq_delay = irq_delay
        self._irq_fired = False
        self._irq_lock  = threading.Lock()

        if irq_controller is not None:
            threading.Thread(target=self._irq_task, daemon=True).start()

    @property
    def name(self) -> str:
        return 'ConsoleUart'

    # -- MMIODevice interface ---------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._STATUS:
            return (1).to_bytes(size, 'little')   # TXREADY always set
        end = offset + size
        if end <= self._REGSIZE:
            return bytes(self._regs[offset:end])
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        if offset == self._TXDATA:
            ch = data[0] & 0xFF
            # Printable ASCII + newline → print directly; others as hex
            print(
                chr(ch) if (32 <= ch <= 126 or ch == 0x0A) else f'[{ch:#04x}]',
                end='', flush=True,
            )
            return
        end = offset + size
        if end <= self._REGSIZE:
            self._regs[offset:end] = data[:size]

    def on_reset(self) -> None:
        self._regs[:] = bytearray(self._REGSIZE)
        self._regs[self._CTRL] = 0x01
        with self._irq_lock:
            self._irq_fired = False

    # -- IRQ injection (runs in a daemon thread) --------------------------

    def _irq_task(self) -> None:
        """One-shot IRQ: fires *irq_delay* seconds after the channel connects."""
        ctrl = self._irq_ctrl
        assert ctrl is not None

        ctrl.wait_connected()           # block until QEMU opens irq-chardev
        time.sleep(self._irq_delay)

        with self._irq_lock:
            if self._irq_fired:
                return                  # another reconnect already fired
            self._irq_fired = True

        ctrl.set_irq(self._irq_idx, 1)
        print(
            f'[IRQ] IRQ {self._irq_idx} asserted  (level=1)'
            ' \u2192 QEMU will raise GIC SPI 0'
        )
        time.sleep(2.0)
        ctrl.set_irq(self._irq_idx, 0)
        print(f'[IRQ] IRQ {self._irq_idx} deasserted (level=0)')


# ---------------------------------------------------------------------------
# Example skeleton — copy/paste to add a new device
# ---------------------------------------------------------------------------
#
# class MyNewDevice(MMIODevice):
#     """DMA controller, timer, etc."""
#
#     @property
#     def name(self) -> str:
#         return 'MyNewDevice'
#
#     def read(self, offset: int, size: int) -> bytes:
#         # ... return register bytes ...
#         return b'\x00' * size
#
#     def write(self, offset: int, size: int, data: bytes) -> None:
#         # ... handle register write ...
#         # To fire an IRQ:
#         #   self._irq_ctrl.set_irq(self._irq_idx, 1)
#         pass


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
                    hdr    = recv_exact(conn, 5)       # offset(4B LE) + size(1B)
                    offset = struct.unpack('<I', hdr[:4])[0]
                    size   = hdr[4]
                    data   = self.bus.read(self.base_addr + offset, size)
                    conn.sendall(data)

                elif op == ord('W'):
                    hdr     = recv_exact(conn, 5)      # offset(4B LE) + size(1B)
                    offset  = struct.unpack('<I', hdr[:4])[0]
                    size    = hdr[4]
                    payload = recv_exact(conn, size)
                    self.bus.write(self.base_addr + offset, size, payload)

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

# Try to import the generated device map.  It is created by running
#   python3 scripts/gen_device_code.py   (or: make gen)
# If it doesn't exist yet, fall back to hardcoded defaults with a warning.
try:
    import sys as _sys
    _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    from tools.generated.device_map import DEVICE_MAP as _DEVICE_MAP   # type: ignore
    _uart = _DEVICE_MAP['console_uart']
    _DEFAULT_RW_PORT   = _uart.rw_port
    _DEFAULT_IRQ_PORT  = _uart.irq_port
    _DEFAULT_IRQ_DELAY = _uart.irq_delay
    _DEFAULT_BASE_ADDR = _uart.base_addr
    _DEFAULT_SIZE      = _uart.size
except Exception as _exc:
    print(
        f'[main] WARNING: generated device map not found ({_exc}).\n'
        '       Run "make gen" (or python3 scripts/gen_device_code.py) first.\n'
        '       Falling back to hardcoded defaults.',
        file=sys.stderr,
    )
    _DEFAULT_RW_PORT   = 7890
    _DEFAULT_IRQ_PORT  = 7891
    _DEFAULT_IRQ_DELAY = 2.0
    _DEFAULT_BASE_ADDR = 0x10020000
    _DEFAULT_SIZE      = 0x1000


def main() -> None:
    parser = argparse.ArgumentParser(
        description='MMIO Device Server — layered QEMU peripheral emulation',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--port',      type=int,              default=_DEFAULT_RW_PORT,
                        help='R/W channel TCP port')
    parser.add_argument('--irq-port',  type=int,              default=_DEFAULT_IRQ_PORT,
                        help='IRQ channel TCP port')
    parser.add_argument('--irq-delay', type=float,            default=_DEFAULT_IRQ_DELAY,
                        help='Seconds before the demo IRQ fires')
    parser.add_argument('--base-addr', type=lambda x: int(x, 0),
                        default=_DEFAULT_BASE_ADDR,
                        help='MMIO base address (must match QEMU addr= property)')
    args = parser.parse_args()

    # ── 1. Shared IRQ controller ──────────────────────────────────────────
    irq_ctrl = IRQController()

    # ── 2. Address bus + device registration ─────────────────────────────
    bus = MMIOBus()
    bus.register(
        args.base_addr,
        _DEFAULT_SIZE,
        ConsoleUartDevice(
            irq_controller=irq_ctrl,
            irq_idx=0,               # IRQ line index in the 'I' protocol message
            irq_delay=args.irq_delay,
        ),
    )

    # To add a second device from config:
    #
    #   dma = DEVICE_MAP['dma']
    #   bus.register(dma.base_addr, dma.size,
    #                DmaDevice(irq_ctrl, irq_idx=0, irq_delay=dma.irq_delay))
    #   RWServer(port=dma.rw_port, bus=bus, base_addr=dma.base_addr)  → start in thread
    #
    # And in QEMU command line:
    #   -chardev socket,id=dmasock,host=127.0.0.1,port=<dma.rw_port>
    #   -device  mmio-sockdev,chardev=dmasock,addr=<dma.base_addr>,irq-num=<dma.irq_num>

    # ── 3. Transport servers ──────────────────────────────────────────────
    irq_server = IRQServer(port=args.irq_port, irq_controller=irq_ctrl)
    threading.Thread(target=irq_server.start, daemon=True).start()

    rw_server = RWServer(port=args.port, bus=bus, base_addr=args.base_addr)
    try:
        rw_server.start()
    except KeyboardInterrupt:
        print('\n[main] Shutting down...')
    finally:
        rw_server.stop()
        irq_server.stop()


if __name__ == '__main__':
    main()

