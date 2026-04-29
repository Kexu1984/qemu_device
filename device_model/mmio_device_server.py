#!/usr/bin/env python3
"""
MMIO Device Server — transport + dispatch layer.
=================================================

Architecture
------------

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  RWServer (:7890/:7892/:7894)     IRQServer (:7891/:7895)                  │ Transport
  │  TCP + binary MMIO protocol      TCP + IRQ injection channel               │
  └──────────────────┬────────────────────────────┬───────────────────────────┘
                     │ abs_addr = base + offset    │ per-device IRQController
  ┌──────────────────▼────────────────────────────▼───────────────────────────┐
  │                               MMIOBus                                     │ Dispatch
  │           abs_addr → find registered device → compute offset              │
  └───────────┬────────────────────────┬───────────────────────┬──────────────┘
  ┌───────────▼───────────┐  ┌─────────▼──────────┐  ┌─────────▼──────────┐
  │  ConsoleUartDevice    │  │     DmaDevice       │  │    TimerDevice     │ Models
  │  @ 0x10020000         │  │     @ 0x10030000    │  │    @ 0x10040000    │
  │  (uart_model.py)      │  │     (dma_model.py)  │  │    (timer_model.py)│
  └───────────────────────┘  └────────────────────┘  └────────────────────┘

Adding a new device
-------------------
1. Create ``device_model/<name>_model.py`` subclassing ``MMIODevice``.
2. Import it here and register it on the bus in ``main()``.
3. Add a matching ``-chardev``/``-device`` pair to the QEMU command line.

R/W Protocol  (QEMU → Python, per mmio-sockdev instance)
  Read:   'R'(1B) | offset(4B LE) | size(1B)  →  data(sizeB LE)
  Write:  'W'(1B) | offset(4B LE) | size(1B) | data(sizeB LE)

IRQ Protocol  (Python → QEMU, shared irq-chardev)
  'I'(1B) | irq_idx(1B) | level(1B)
  irq_idx: index of the IRQ output line on the mmio-sockdev (0-based)
  level:   1 = assert, 0 = deassert
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

from device_model.mmio_base         import AddressSpace, IRQController, MemChannel, MMIODevice, RstController, recv_exact  # noqa: E402
from device_model.uart_model        import ConsoleUartDevice                      # noqa: E402
from device_model.timer_model       import TimerDevice                            # noqa: E402
from device_model.dma_controller    import DmaController                          # noqa: E402
from device_model.dma_client_demo   import DmaClientDemoDevice                    # noqa: E402
from device_model.crc_device        import CrcDevice                              # noqa: E402
from device_model.wdt_model         import WdtDevice                              # noqa: E402


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

    def add_tick_observer(self, observer: object) -> None:
        """Register an object that should receive on_tick() calls.

        Use this for non-MMIO objects (e.g. a shared DmaController) that
        need virtual-clock ticks but are not mapped into the address space.
        The observer must implement ``on_tick(vtime_ns: int)``.
        """
        self._tick_observers.append(observer)

    def tick_all(self, vtime_ns: int) -> None:
        """Broadcast a virtual-clock tick to every registered device and
        every tick observer registered via add_tick_observer().

        Each device's ``on_tick()`` is called in registration order.
        Devices with no timing needs use the default no-op from MMIODevice.
        """
        for _base, _size, device in self._entries:
            device.on_tick(vtime_ns)
        for observer in self._tick_observers:
            observer.on_tick(vtime_ns)


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

# Device defaults — mirror spec/devices.yaml.
# These are the canonical runtime values; override per device via CLI args.
_UART_BASE      = 0x10020000
_UART_SIZE      = 0x1000
_UART_RW_PORT   = 7890
_UART_IRQ_PORT  = 7891
_UART_IRQ_DELAY = 2.0

_DMA_BASE       = 0x10030000
_DMA_SIZE       = 0x1000
_DMA_RW_PORT    = 7892
_DMA_IRQ_PORT   = 7893
_DMA_MEM_PORT   = 7897   # Python → QEMU physical memory (DMA bus-master channel)

_TIMER_BASE     = 0x10040000
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


# ---------------------------------------------------------------------------
# Transport: virtual-clock tick channel  (QEMU → Python)
# ---------------------------------------------------------------------------

class TickServer:
    """
    Accepts QEMU's tick-chardev TCP connection and broadcasts virtual-clock
    ticks to every device registered on the bus.

    QEMU sends  'T'(1B) | vtime_ns(8B LE)  every ``tick-period-ms`` of
    virtual time.  On each message this server calls ``bus.tick_all(vtime_ns)``
    which dispatches to every registered ``MMIODevice.on_tick()`` in order.

    This keeps the tick mechanism fully generic — any device (timer, DMA,
    future peripherals) simply overrides ``on_tick()`` to react to virtual
    time.  Devices with no timing needs use the inherited no-op.

    Usage::

        tick_srv = TickServer(port=7896, bus=bus)
        threading.Thread(target=tick_srv.start, daemon=True).start()
    """

    _TICK_MSG_SIZE = 9   # 'T'(1B) + vtime_ns(8B LE)

    def __init__(self, port: int, bus: MMIOBus) -> None:
        self.port     = port
        self._bus     = bus
        self._sock: Optional[socket.socket] = None
        self._running = False

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
                self._bus.tick_all(vtime_ns)
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


# ---------------------------------------------------------------------------
# System reset coordinator
# ---------------------------------------------------------------------------

class SystemResetManager:
    """
    Coordinates a watchdog reset across all Python device models.

    On WDT timeout:
      1. Calls ``on_reset()`` on every MMIODevice registered on the bus,
         clearing volatile state while preserving retention registers.
      2. Sends a byte via ``RstController`` → rst-chardev TCP channel →
         QEMU ``qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)``.

    The TCP connections (RW / IRQ / MEM / RST) remain alive across the QEMU
    system reset.  Firmware restarts from the reset vector and sees fresh
    Python-side device state; WDT retention registers reflect the timeout.
    """

    def __init__(self, bus: 'MMIOBus', rst_ctrl) -> None:
        self._bus      = bus
        self._rst_ctrl = rst_ctrl

    def wdt_reset(self) -> None:
        """Called by WdtDevice when the watchdog countdown expires."""
        print('[SYS] WDT reset: resetting all device volatile state...')
        for _base, _size, device in self._bus._entries:
            device.on_reset()
        print('[SYS] Sending system-reset request to QEMU...')
        if not self._rst_ctrl.send_reset():
            print('[SYS] WARNING: rst-chardev not connected — '
                  'QEMU reset not sent.',
                  file=sys.stderr)


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

    # ── 1. Per-device IRQ controllers ────────────────────────────────────
    uart_irq_ctrl  = IRQController()
    dma_irq_ctrl   = IRQController()
    timer_irq_ctrl = IRQController()
    demo_irq_ctrl  = IRQController()
    wdt_irq_ctrl   = IRQController()

    # ── 1b. System-reset controller (WDT → QEMU) ─────────────────────────
    wdt_rst_ctrl = RstController()

    # ── 2. DMA bus-master memory channel ─────────────────────────────────
    mem_channel = MemChannel()

    # ── 3. DMA controller — the MMIO-mapped engine ───────────────────────
    #
    # DmaController is the single DMA IP on the SoC.  It is registered on
    # the bus at _DMA_BASE so firmware can read/write its channel registers
    # directly (M2M transfers).  Peripherals that need DMA obtain a
    # DmaClientHandle via get_handle() for the DREQ/DACK interface (P2M/M2P).
    #
    # AddressSpace routes DMA reads/writes by address:
    #   - MMIO region [0x40000000, 0x50000000): dispatched directly to the
    #     Python MMIOBus in-process — no TCP round-trip, no ordering race.
    #   - All other addresses (SRAM, flash): forwarded to QEMU physical memory
    #     via MemChannel (cpu_physical_memory_read/write over TCP).
    #
    # The bus reference in AddressSpace is live — devices can be registered
    # on the bus after addr_space is created; transfers happen at runtime when
    # the bus is already fully populated.
    #
    #   CH0 @ _DMA_BASE+0x000 — firmware-programmed (IRQ=dma_irq_ctrl)
    #   CH1 @ _DMA_BASE+0x020 — DmaClientDemoDevice via DmaClientHandle
    bus = MMIOBus()

    addr_space = AddressSpace(
        mem_channel  = mem_channel,
        mmio_bus     = bus,
        mmio_regions = [
            (_UART_BASE,  _UART_SIZE),
            (_DMA_BASE,   _DMA_SIZE),
            (_TIMER_BASE, _TIMER_SIZE),
            (_DEMO_BASE,  _DEMO_SIZE),
            (_CRC_BASE,   _CRC_SIZE),
            (_WDT_BASE,   _WDT_SIZE),
        ],
    )

    dma_ctrl = DmaController(
        num_channels  = 2,
        address_space = addr_space,
        irq_controller= dma_irq_ctrl,
        irq_idx       = 0,
        transfer_ticks= 10,
    )

    # ── 4. Address bus + device registration ─────────────────────────────

    bus.register(
        _UART_BASE, _UART_SIZE,
        ConsoleUartDevice(
            irq_controller=uart_irq_ctrl,
            irq_idx=0,
            irq_delay=uart_irq_delay,
        ),
    )
    # DmaController IS the DMA MMIO device — no separate DmaDevice needed.
    bus.register(_DMA_BASE, _DMA_SIZE, dma_ctrl)
    bus.register(
        _TIMER_BASE, _TIMER_SIZE,
        TimerDevice(irq_controller=timer_irq_ctrl, irq_idx=0),
    )
    # DmaClientDemoDevice uses DMA CH1 via DmaClientHandle (DREQ/DACK).
    bus.register(
        _DEMO_BASE, _DEMO_SIZE,
        DmaClientDemoDevice(
            dma_handle=dma_ctrl.get_handle(1),
            irq_controller=demo_irq_ctrl,
            irq_idx=0,
        ),
    )
    # CRC-32 hardware accelerator — polled only, no IRQ.
    bus.register(
        _CRC_BASE, _CRC_SIZE,
        CrcDevice(),
    )

    # WDT — watchdog timer with retention registers + system-reset capability.
    # SystemResetManager is constructed after the bus is fully populated so that
    # wdt_reset() can iterate bus._entries.
    sys_reset_mgr = SystemResetManager(bus=bus, rst_ctrl=wdt_rst_ctrl)
    bus.register(
        _WDT_BASE, _WDT_SIZE,
        WdtDevice(
            irq_controller=wdt_irq_ctrl,
            irq_idx=0,
            reset_callback=sys_reset_mgr.wdt_reset,
        ),
    )

    # ── 5. Transport servers ──────────────────────────────────────────────
    uart_irq_server = IRQServer(port=uart_irq_port, irq_controller=uart_irq_ctrl)
    threading.Thread(target=uart_irq_server.start, daemon=True).start()

    dma_irq_server = IRQServer(port=_DMA_IRQ_PORT, irq_controller=dma_irq_ctrl)
    threading.Thread(target=dma_irq_server.start, daemon=True).start()

    # DMA bus-master memory channel: Python → QEMU physical memory
    mem_server = MemServer(port=_DMA_MEM_PORT, mem_channel=mem_channel)
    threading.Thread(target=mem_server.start, daemon=True).start()

    dma_rw_server = RWServer(port=_DMA_RW_PORT, bus=bus, base_addr=_DMA_BASE)
    threading.Thread(target=dma_rw_server.start, daemon=True).start()

    # Virtual-clock tick server: broadcasts to ALL registered bus devices.
    tick_server = TickServer(port=_TIMER_TICK_PORT, bus=bus)
    threading.Thread(target=tick_server.start, daemon=True).start()

    timer_irq_server = IRQServer(port=_TIMER_IRQ_PORT, irq_controller=timer_irq_ctrl)
    threading.Thread(target=timer_irq_server.start, daemon=True).start()

    timer_rw_server = RWServer(port=_TIMER_RW_PORT, bus=bus, base_addr=_TIMER_BASE)
    threading.Thread(target=timer_rw_server.start, daemon=True).start()

    # DmaClientDemoDevice transport servers
    demo_irq_server = IRQServer(port=_DEMO_IRQ_PORT, irq_controller=demo_irq_ctrl)
    threading.Thread(target=demo_irq_server.start, daemon=True).start()

    demo_rw_server = RWServer(port=_DEMO_RW_PORT, bus=bus, base_addr=_DEMO_BASE)
    threading.Thread(target=demo_rw_server.start, daemon=True).start()

    crc_rw_server = RWServer(port=_CRC_RW_PORT, bus=bus, base_addr=_CRC_BASE)
    threading.Thread(target=crc_rw_server.start, daemon=True).start()

    # WDT transport servers: R/W, IRQ, and system-reset channels
    wdt_irq_server = IRQServer(port=_WDT_IRQ_PORT, irq_controller=wdt_irq_ctrl)
    threading.Thread(target=wdt_irq_server.start, daemon=True).start()

    rst_server = RstServer(port=_WDT_RST_PORT, rst_controller=wdt_rst_ctrl)
    threading.Thread(target=rst_server.start, daemon=True).start()

    wdt_rw_server = RWServer(port=_WDT_RW_PORT, bus=bus, base_addr=_WDT_BASE)
    threading.Thread(target=wdt_rw_server.start, daemon=True).start()

    uart_rw_server = RWServer(port=uart_rw_port, bus=bus, base_addr=_UART_BASE)
    try:
        uart_rw_server.start()
    except KeyboardInterrupt:
        print('\n[main] Shutting down...')
    finally:
        uart_rw_server.stop()
        dma_rw_server.stop()
        uart_irq_server.stop()
        dma_irq_server.stop()
        mem_server.stop()
        timer_rw_server.stop()
        timer_irq_server.stop()
        tick_server.stop()
        demo_rw_server.stop()
        demo_irq_server.stop()
        crc_rw_server.stop()
        wdt_rw_server.stop()
        wdt_irq_server.stop()
        rst_server.stop()


if __name__ == '__main__':
    main()
