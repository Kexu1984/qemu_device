"""
mmio_base — System-level base classes and transport primitives for MMIO device models.

Provides
--------
Helpers:
  recv_exact(sock, n) → bytes   — reliable socket receive helper

SoC clock constants (KX6625):
  HCLK_HZ = 48_000_000          — Cortex-M4 / AHB bus clock
  PCLK_HZ = 12_000_000          — APB peripheral clock (HCLK ÷ 4)
  NS_PER_HCLK, NS_PER_PCLK      — nanoseconds per clock cycle

Device base class:
  MMIODevice                    — abstract base class for all peripheral models.
                                  Subclasses implement read() / write() and
                                  optionally on_reset() / on_device_reset() /
                                  on_tick().  on_device_reset() is invoked by
                                  CruNotifyServer when the CRU holds a device in
                                  reset; by default it delegates to on_reset().

Transport channel primitives (Python ↔ QEMU TCP):
  IRQController                 — thread-safe IRQ injection into QEMU (irq-chardev)
    FabricChannel                 — fabric read/write into QEMU system address
                                                                    space (fabric-chardev)

Address routing:
- BusMasterAddressSpace: unified accessor for bus-master devices; routes
    accesses by physical address: MMIO ranges → in-process PeripheralBus,
    all other addresses -> FabricChannel (QEMU fabric via TCP)

Device-specific transports live in their own modules:
  UartChannel   → device_model/uart_model.py
  RstController → device_model/cru_device.py  (also CruNotifyServer, SystemResetManager)

This module has no device-specific logic; it is imported by every device
model (uart_model.py, dma_controller.py, …) and by mmio_device_server.py.
"""

from __future__ import annotations

import enum
import socket
import struct
import sys
import threading
from abc import ABC, abstractmethod
from typing import Dict, Optional

try:
    from device_model.generated.device_consts import MASTER_ID_UNKNOWN
except ModuleNotFoundError:
    MASTER_ID_UNKNOWN = 0xFF


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
# SoC clock constants  (KX6625 — matches kx6625.c)
# ---------------------------------------------------------------------------

#: Cortex-M3 core / AHB bus clock  (48 MHz)
HCLK_HZ: int = 48_000_000

#: APB peripheral clock (PCLK = HCLK ÷ 4 = 12 MHz)
#: Used by UART, Timer, WDT, CRC, DMA state-machine.
PCLK_HZ: int = 12_000_000

#: Nanoseconds per HCLK cycle  (≈ 20.83 ns)
NS_PER_HCLK: int = 1_000_000_000 // HCLK_HZ   # = 20

#: Nanoseconds per PCLK cycle  (≈ 83.33 ns)
NS_PER_PCLK: int = 1_000_000_000 // PCLK_HZ   # = 83


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
    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        """Return ``size`` bytes of register data at ``offset``."""

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        """
        Write ``data`` to the register at ``offset``.

        Returns the nanoseconds until the next device event (DES protocol).
        Return 0 for ordinary config writes with no scheduled event.
        Return N > 0 to ask QEMU to deliver a virtual-time tick exactly
        N ns in the future (e.g. DMA transfer completion, timer expiry).

        QEMU reads this 8-byte little-endian value after every write and,
        if > 0, calls ``timer_mod(tick_timer, now + N)`` so the device's
        ``on_tick()`` fires at the precise virtual time.
        """
        return 0

    def on_reset(self) -> None:
        """Optional: called when the system is reset."""

    def on_device_reset(self) -> None:
        """Optional: called by CRU when this device is held in reset via RST_CTRL.
        Default delegates to on_reset() so devices only need to override one method."""
        self.on_reset()

    def on_tick(self, vtime_ns: int) -> int:
        """
        Optional: called on every virtual-clock tick from QEMU.

        ``vtime_ns`` is the current QEMU_CLOCK_VIRTUAL value in nanoseconds.
        Devices that need timing (timers, DMA latency, etc.) override this
        method to advance their internal state.  The default is a no-op so
        that devices without timing requirements need not implement it.

        Returns 0 (no further scheduled events).  Future DES extensions may
        use a non-zero return to request the next tick interval.
        """
        return 0


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
# Fabric / bus-master channel
# ---------------------------------------------------------------------------

class FabricChannel:
    """
    Bus-master fabric channel: Python device model -> QEMU system fabric.

    A Python device that acts as a bus master uses this class to read from and
    write to QEMU's system address space. Requests use the fabric wire protocol
    and carry an explicit master ID per transaction.

    Protocol (Python -> QEMU, over fabric-chardev TCP channel):
      Write: 'F' | 'W' | master_id(1B) | flags(1B) | addr(8B LE) | len(4B LE)
          | data(lengthB), QEMU responds: status(1B)
      Read:  'F' | 'R' | master_id(1B) | flags(1B) | addr(8B LE) | len(4B LE),
          QEMU responds: status(1B) | data(lengthB)

        Thread safety:
            ``fabric_write()`` and ``fabric_read()`` are serialised by an internal lock.
      Only one DMA operation may be in flight at a time (which matches how
      the TickServer drives DMA completion — single-threaded).

    Typical lifecycle::

        # In mmio_device_server.py:
        fabric_channel = FabricChannel()
        fabric_server  = FabricServer(port=7897, fabric_channel=fabric_channel)
        threading.Thread(target=fabric_server.start, daemon=True).start()

        # In DmaDevice.on_tick() — called from TickServer thread:
        data = fabric_channel.fabric_read(master_id, src_addr, length)
        if data:
            fabric_channel.fabric_write(master_id, dst_addr, data)
    """

    def __init__(self, master_id: int = MASTER_ID_UNKNOWN) -> None:
        self._master_id = master_id & 0xFF
        self._sock: Optional[socket.socket] = None
        self._lock      = threading.Lock()    # serialises all socket I/O
        self._connected = threading.Event()
        self._close_evt = threading.Event()   # set on I/O error or stop()
        self._max_transfer = 65536

    @property
    def master_id(self) -> int:
        return self._master_id

    # -- called by FabricServer -------------------------------------------

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
        """Mark the channel as closed; unblocks FabricServer._handle_client."""
        self._connected.clear()
        self._close_evt.set()

    def wait_for_close(self) -> None:
        """Block until the channel closes or ``stop()`` is called."""
        self._close_evt.wait()

    def stop(self) -> None:
        """Force-close the channel (called by FabricServer.stop())."""
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
        """Return True when QEMU connects the fabric channel."""
        return self._connected.wait(timeout)

    def fabric_write(self, master_id: int, addr: int, data: bytes) -> bool:
        """
        Write *data* to QEMU fabric address *addr* as *master_id*.

        Returns ``True`` on success, ``False`` if the fabric reports an error
        or the channel is disconnected.
        """
        with self._lock:
            if self._sock is None:
                return False
            try:
                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + self._max_transfer]
                    hdr = b'F' + b'W' + bytes([master_id & 0xFF, 0])
                    hdr += struct.pack('<QI', addr + offset, len(chunk))
                    self._sock.sendall(hdr + chunk)
                    ack = recv_exact(self._sock, 1)
                    if ack != b'\x00':
                        return False
                    offset += len(chunk)
                return True
            except (OSError, ConnectionError) as exc:
                print(f'[FABRIC]  write error: {exc}', file=sys.stderr)
                self._signal_close()
                return False

    def fabric_read(self, master_id: int, addr: int, length: int) -> Optional[bytes]:
        """
        Read *length* bytes from QEMU fabric address *addr* as *master_id*.

        Returns the data on success, ``None`` on fabric or transport error.
        """
        with self._lock:
            if self._sock is None:
                return None
            try:
                out = bytearray()
                offset = 0
                while offset < length:
                    chunk_len = min(self._max_transfer, length - offset)
                    hdr = b'F' + b'R' + bytes([master_id & 0xFF, 0])
                    hdr += struct.pack('<QI', addr + offset, chunk_len)
                    self._sock.sendall(hdr)
                    status = recv_exact(self._sock, 1)
                    data = recv_exact(self._sock, chunk_len)
                    if status != b'\x00':
                        return None
                    out.extend(data)
                    offset += chunk_len
                return bytes(out)
            except (OSError, ConnectionError) as exc:
                print(f'[FABRIC]  read error: {exc}', file=sys.stderr)
                self._signal_close()
                return None

# ---------------------------------------------------------------------------
# Address space — routes DMA reads/writes by physical address
# ---------------------------------------------------------------------------

class BusMasterAddressSpace:
    """
    Python-domain memory transaction bus for bus-master devices.

    Unified address-space accessor for bus-master devices (e.g. DMA engine,
    HSM crypto engine, flash controller). This is the Python-side memory path
    shown in the architecture diagram.

    Routes reads/writes by physical address:

    - Addresses within any registered MMIO region:
        Dispatched directly to the Python PeripheralBus in-process.
        No TCP round-trip — the device model's ``read()``/``write()`` is called
        synchronously, making M2P and P2M transfers race-free.

    - All other addresses (SRAM, flash, ...):
        Dispatched to QEMU through ``FabricChannel`` fabric frames.

    The ``mmio_bus`` parameter is duck-typed: any object implementing
    ``read(addr, size) -> bytes`` and ``write(addr, size, data)`` is accepted.
    This avoids a circular import with ``mmio_device_server.PeripheralBus``.

    Usage::

        addr_space = BusMasterAddressSpace(
            fabric_channel = fabric_ch,
            mmio_bus     = bus,
            mmio_regions = [(0x40000000, 0x100000)],  # peripheral address space
        )
        dma_ctrl = DmaController(address_space=addr_space, ...)
    """

    def __init__(
        self,
        fabric_channel: 'FabricChannel',
        mmio_bus:     object,           # duck-typed: read()/write() methods
        mmio_regions: list,             # list[tuple[int, int]]  [(base, size), …]
        master_id:    Optional[int] = None,
    ) -> None:
        self._fabric  = fabric_channel
        self._bus     = mmio_bus
        self._regions = mmio_regions    # [(base: int, size: int), …]
        self._master_id = master_id

    def _is_mmio(self, addr: int) -> bool:
        return any(base <= addr < base + size for base, size in self._regions)

    def read(self, addr: int, length: int) -> Optional[bytes]:
        """
        Read ``length`` bytes from ``addr``.

        Returns bytes on success; ``None`` if a QEMU transport error occurs
        (MMIO reads always succeed, returning zero bytes for unmapped ranges).
        """
        if self._is_mmio(addr):
            return self._bus.read(addr, length)   # PeripheralBus always returns bytes
        master_id = self._master_id if self._master_id is not None else self._fabric.master_id
        return self._fabric.fabric_read(master_id, addr, length)

    def write(self, addr: int, data: bytes) -> bool:
        """
        Write ``data`` to ``addr``.

        Returns ``True`` on success, ``False`` on QEMU transport error
        (MMIO writes always succeed).
        """
        if self._is_mmio(addr):
            self._bus.write(addr, len(data), data)
            return True
        master_id = self._master_id if self._master_id is not None else self._fabric.master_id
        return self._fabric.fabric_write(master_id, addr, data)

# Backward-compatible public name used by existing device models.
AddressSpace = BusMasterAddressSpace


# ---------------------------------------------------------------------------
# RegAccess — per-register access-policy flags
# ---------------------------------------------------------------------------

class RegAccess(enum.Flag):
    """
    Access-policy flags for individual registers inside a ``RegisterBank``.

    Combine multiple policies with ``|``; the default (no flags) means
    standard read/write with no side effects.

    Policies only apply to *external* CPU-side access (the ``read()`` and
    ``write()`` methods).  Internal device helpers — ``get32()``,
    ``set32()``, ``set_bits()``, ``clear_bits()``, ``get32_nolock()``,
    ``set32_nolock()``, ``__getitem__``, ``__setitem__`` — always bypass
    policies so the device hardware can freely update its own registers.

    Members
    -------
    READ_CLEAR
        Reading atomically returns the current value then clears the register
        to zero.  Used for self-clearing status/error latches where a read
        acts as an implicit acknowledge.  Example: a one-shot event register
        that accumulates flags until the CPU reads it.

    WRITE_ONLY
        CPU reads always return 0 regardless of stored content.  Writes work
        normally (the value is stored and can be read back internally via
        device helpers).  Typical use: pulse/strobe registers like INTCLR or
        KICK where the *act* of writing matters, not the value.

    READ_ONLY
        CPU writes are silently discarded; the stored value is not modified.
        Reads return the current stored value as normal.  Typical use: STATUS,
        VALUE, and any register that is written only by device hardware.

    W1C  (Write-1-to-Clear)
        Bits where the CPU writes **1** are cleared in the register; bits
        where the CPU writes **0** are left unchanged.  The most common
        convention for interrupt status registers in ARM SoCs.  Internal
        ``set_bits()`` still sets bits normally (device raises the flag).

    W1S  (Write-1-to-Set)
        Bits where the CPU writes **1** are set in the register; bits where
        the CPU writes **0** are left unchanged.  Used for set-only control
        registers where individual feature bits are armed independently.

    Usage examples
    --------------
    Interrupt status register (device sets, firmware clears individual bits)::

        # Construction
        self._regs = RegisterBank(
            size,
            policies={
                _STATUS: RegAccess.W1C,        # firmware: write 1 to clear bit
                _INTCLR: RegAccess.WRITE_ONLY, # pulse register, reads as 0
                _VALUE:  RegAccess.READ_ONLY,  # hardware-computed, no CPU write
            },
        )

        # In on_tick / interrupt logic — internal; bypasses policies:
        self._regs.set_bits(_STATUS, INT_PENDING)   # hardware raises flag

        # Firmware writes STATUS with W1C — only the written 1-bits are cleared:
        #   old STATUS = 0x03 (two bits set)
        #   CPU writes 0x01  → new STATUS = 0x02  (bit 0 cleared, bit 1 kept)

    Self-clearing event latch (read acknowledges and clears)::

        self._regs = RegisterBank(
            size,
            policies={_EVENTS: RegAccess.READ_CLEAR},
        )
        # Device sets bits internally via set_bits()
        # CPU reads EVENTS: gets current value, register atomically zeroed
    """
    READ_CLEAR = enum.auto()   # read → return value, then clear to 0
    WRITE_ONLY = enum.auto()   # read → 0;  write → stored normally
    READ_ONLY  = enum.auto()   # read → stored value;  write → ignored
    W1C        = enum.auto()   # write 1 clears bit;  write 0 no-op
    W1S        = enum.auto()   # write 1 sets bit;    write 0 no-op


# ---------------------------------------------------------------------------
# RegisterBank — uniform, thread-safe register storage
# ---------------------------------------------------------------------------

class RegisterBank:
    """
    Thread-safe, bounds-checked register storage for MMIO device models.

    Replaces the common pattern of a bare ``bytearray`` + ``threading.Lock``
    + manual bounds checking that every device repeats.  Provides both
    individual-register helpers (``get32``, ``set32``, ``set_bits``,
    ``clear_bits``) and a context-manager interface for atomic multi-register
    operations.

    Usage — simple device::

        class MyDevice(MMIODevice):
            _CTRL   = 0x00
            _STATUS = 0x04
            _SIZE   = 0x08

            def __init__(self):
                init = bytearray(self._SIZE)
                init[self._CTRL] = 0x01          # CTRL defaults to ENABLE=1
                self._regs = RegisterBank(self._SIZE, bytes(init))

            def read(self, offset, size):
                return self._regs.read(offset, size)

            def write(self, offset, size, data):
                self._regs.write(offset, size, data)

            def on_reset(self):
                self._regs.reset()          # back to construction-time initial

    Usage — atomic multi-register operation::

        with self._regs:                          # acquires internal lock
            src = self._regs.get32_nolock(SRC)
            dst = self._regs.get32_nolock(DST)
            self._regs[STATUS] = BUSY             # byte write, no lock needed
    """

    def __init__(
        self,
        size: int,
        initial: Optional[bytes] = None,
        policies: Optional[Dict[int, RegAccess]] = None,
    ) -> None:
        self._size     = size
        _init          = bytes(initial) if initial else bytes(size)
        # Pad or truncate to exactly *size* bytes.
        self._init     = (_init + bytes(size))[:size]
        self._data     = bytearray(self._init)
        self._lock     = threading.Lock()
        # Per-register access policies.  Keys are the register byte offset
        # (same value used when calling read/write).  Missing → no policy.
        self._policies: Dict[int, RegAccess] = policies or {}

    # ── Slice-level access (policy-aware; internal lock acquired automatically)
    #
    # Only read() and write() enforce policies.  All other methods (get32,
    # set32, set_bits, clear_bits, nolock variants, __getitem__, __setitem__)
    # bypass policies — they represent the device hardware acting on its own
    # registers, just as hardware state-machines update registers directly.

    def read(self, offset: int, size: int) -> bytes:
        """
        Return *size* bytes starting at *offset* (CPU-side read).

        Applies per-register access policies:
        - ``WRITE_ONLY``: returns ``size`` zero bytes without touching storage.
        - ``READ_CLEAR``: atomically returns stored value then zeroes it.
        - All other policies: returns stored value unchanged.

        Out-of-bounds reads return zero bytes.
        """
        end = offset + size
        if offset < 0 or end > self._size:
            return b'\x00' * size
        policy = self._policies.get(offset, RegAccess(0))
        if bool(policy & RegAccess.WRITE_ONLY):
            return b'\x00' * size
        with self._lock:
            val = bytes(self._data[offset:end])
            if bool(policy & RegAccess.READ_CLEAR):
                self._data[offset:end] = b'\x00' * size
        return val

    def write(self, offset: int, size: int, data: bytes) -> None:
        """
        Write *data* at *offset* (CPU-side write).

        Applies per-register access policies:
        - ``READ_ONLY``:  silently discards the write.
        - ``W1C``:        bits written as 1 clear the stored bit;
                          bits written as 0 leave the stored bit unchanged.
        - ``W1S``:        bits written as 1 set the stored bit;
                          bits written as 0 leave the stored bit unchanged.
        - All other policies (including ``WRITE_ONLY``): stores value normally.

        Out-of-bounds writes are silently ignored.
        """
        end = offset + size
        if offset < 0 or end > self._size:
            return
        policy = self._policies.get(offset, RegAccess(0))
        if bool(policy & RegAccess.READ_ONLY):
            return
        bit_mask = (1 << (size * 8)) - 1
        with self._lock:
            if bool(policy & RegAccess.W1C):
                old  = int.from_bytes(self._data[offset:end], 'little')
                mask = int.from_bytes(data[:size], 'little') & bit_mask
                self._data[offset:end] = ((old & ~mask) & bit_mask).to_bytes(size, 'little')
            elif bool(policy & RegAccess.W1S):
                old  = int.from_bytes(self._data[offset:end], 'little')
                mask = int.from_bytes(data[:size], 'little') & bit_mask
                self._data[offset:end] = ((old | mask) & bit_mask).to_bytes(size, 'little')
            else:
                self._data[offset:end] = data[:size]

    # ── 32-bit helpers (internal lock acquired automatically) ─────────────

    def get32(self, offset: int) -> int:
        """Read a 32-bit little-endian value at *offset*."""
        with self._lock:
            return int.from_bytes(self._data[offset:offset + 4], 'little')

    def set32(self, offset: int, value: int) -> None:
        """Write a 32-bit little-endian value at *offset*."""
        with self._lock:
            self._data[offset:offset + 4] = (value & 0xFFFF_FFFF).to_bytes(4, 'little')

    def set_bits(self, offset: int, mask: int) -> None:
        """Atomically OR *mask* into the 32-bit word at *offset*."""
        with self._lock:
            cur = int.from_bytes(self._data[offset:offset + 4], 'little')
            self._data[offset:offset + 4] = (
                (cur | mask) & 0xFFFF_FFFF
            ).to_bytes(4, 'little')

    def clear_bits(self, offset: int, mask: int) -> None:
        """Atomically AND-NOT *mask* into the 32-bit word at *offset*."""
        with self._lock:
            cur = int.from_bytes(self._data[offset:offset + 4], 'little')
            self._data[offset:offset + 4] = (
                (cur & ~mask) & 0xFFFF_FFFF
            ).to_bytes(4, 'little')

    def reset(self, initial: Optional[bytes] = None) -> None:
        """Reset contents to *initial* (or the value provided at construction)."""
        src = (bytes(initial or self._init) + bytes(self._size))[:self._size]
        with self._lock:
            self._data[:] = src

    # ── Context manager — for atomic multi-register operations ───────────
    #
    # Inside ``with self._regs:``, use get32_nolock() / set32_nolock() or
    # direct byte access via __getitem__ / __setitem__ without acquiring
    # the lock again (it is already held).

    def __enter__(self) -> 'RegisterBank':
        self._lock.acquire()
        return self

    def __exit__(self, *_) -> None:
        self._lock.release()

    # ── No-lock variants (only valid inside context manager) ─────────────

    def get32_nolock(self, offset: int) -> int:
        """Read 32-bit LE without acquiring the lock — use inside context manager."""
        return int.from_bytes(self._data[offset:offset + 4], 'little')

    def set32_nolock(self, offset: int, value: int) -> None:
        """Write 32-bit LE without acquiring the lock — use inside context manager."""
        self._data[offset:offset + 4] = (value & 0xFFFF_FFFF).to_bytes(4, 'little')

    # ── Byte-level direct access (only valid inside context manager) ──────

    def __getitem__(self, key: int) -> int:
        """Direct byte read — caller must hold the lock via context manager."""
        return self._data[key]

    def __setitem__(self, key: int, value: int) -> None:
        """Direct byte write — caller must hold the lock via context manager."""
        self._data[key] = value & 0xFF


# ---------------------------------------------------------------------------
# IrqLine — single interrupt line with pulse / assert / deassert helpers
# ---------------------------------------------------------------------------

class IrqLine:
    """
    A single interrupt line backed by an ``IRQController`` TCP channel.

    Encapsulates the common pattern of holding a reference to an
    ``IRQController`` plus a line index, and calling
    ``set_irq(idx, 1); set_irq(idx, 0)`` for Cortex-M NVIC edge-triggered
    interrupts.

    If *irq_controller* is ``None``, all methods are silent no-ops, so
    devices can be constructed without an IRQ channel for unit testing or
    polled-only operation.

    Usage::

        irq = IrqLine(irq_controller=ctrl, idx=0)
        irq.pulse()    # edge-trigger: assert then immediately deassert
        irq.assert_()  # level = 1 (stays asserted until deassert() is called)
        irq.deassert() # level = 0
        irq.wait_connected()
    """

    def __init__(
        self,
        irq_controller: Optional[IRQController],
        idx: int = 0,
    ) -> None:
        self._ctrl = irq_controller
        self._idx  = idx

    @property
    def idx(self) -> int:
        """The IRQ line index (0-based)."""
        return self._idx

    def assert_(self) -> None:
        """Assert the interrupt line (level = 1)."""
        if self._ctrl is not None:
            self._ctrl.set_irq(self._idx, 1)

    def deassert(self) -> None:
        """Deassert the interrupt line (level = 0)."""
        if self._ctrl is not None:
            self._ctrl.set_irq(self._idx, 0)

    def pulse(self) -> None:
        """
        Edge-trigger the interrupt: assert then immediately deassert.

        The Cortex-M NVIC latches the rising edge as *pending*; the level
        must return low before the handler exits so the NVIC does not
        re-pend (re-fire) on exception return.
        """
        if self._ctrl is not None:
            self._ctrl.set_irq(self._idx, 1)
            self._ctrl.set_irq(self._idx, 0)

    def wait_connected(self, timeout: Optional[float] = None) -> bool:
        """Block until the QEMU IRQ channel connects (or *timeout* expires)."""
        if self._ctrl is None:
            return False
        return self._ctrl.wait_connected(timeout)


# ---------------------------------------------------------------------------
# VirtualClock — virtual-clock elapsed/remaining tracker
# ---------------------------------------------------------------------------

class VirtualClock:
    """
    Virtual-clock elapsed/remaining time tracker for countdown peripherals.

    Encapsulates the ``_start_vtime_ns`` / ``_last_vtime_ns`` pattern that
    timer and watchdog devices share.  The countdown is driven by
    ``update()`` calls (one per virtual-clock tick from QEMU); expiry is
    tested with ``is_expired(load_ms)``.

    Thread safety: all state is protected by an internal lock.  Methods
    may be called from any thread.

    Usage::

        clock = VirtualClock()

        # In on_tick():
        clock.update(vtime_ns)
        if clock.is_expired(load_ms):
            clock.disarm()
            # ... handle expiry ...

        # To start the countdown (e.g. when CTRL.ENABLE is written):
        clock.arm()          # arms from the most recent tick time

        # To reload (e.g. watchdog kick):
        clock.arm()          # re-arms from the most recent tick time

        # Periodic re-arm (avoids drift by advancing start by one period):
        clock.rearm_periodic(load_ms * 1_000_000)
    """

    def __init__(self) -> None:
        self._lock:       threading.Lock = threading.Lock()
        self._start_ns:   Optional[int]  = None   # countdown start (None = disarmed)
        self._current_ns: Optional[int]  = None   # most recent tick timestamp

    def update(self, vtime_ns: int) -> None:
        """Record the latest virtual-clock timestamp.  Called on every tick."""
        with self._lock:
            self._current_ns = vtime_ns

    def arm(self, vtime_ns: Optional[int] = None) -> None:
        """
        Start (or restart) the countdown.

        If *vtime_ns* is given it becomes the start time; otherwise the
        most recently received tick time is used.  Call ``arm()`` without
        arguments to implement a watchdog kick (reload from *now*).
        """
        with self._lock:
            self._start_ns = vtime_ns if vtime_ns is not None else self._current_ns

    def disarm(self) -> None:
        """Stop the countdown.  ``is_expired()`` returns False until re-armed."""
        with self._lock:
            self._start_ns = None

    def rearm_periodic(self, period_ns: int) -> None:
        """
        Advance the countdown start by *period_ns* nanoseconds.

        Used for periodic timers: instead of re-arming from *now* (which
        accumulates drift if ticks are delivered late), this advances the
        start timestamp by exactly one period so expiry stays on a fixed grid.
        """
        with self._lock:
            if self._start_ns is not None:
                self._start_ns += period_ns

    @property
    def armed(self) -> bool:
        """True if a countdown is in progress."""
        with self._lock:
            return self._start_ns is not None

    @property
    def current_ns(self) -> Optional[int]:
        """Most recently received virtual-clock timestamp (nanoseconds)."""
        with self._lock:
            return self._current_ns

    def elapsed_ms(self) -> int:
        """
        Milliseconds elapsed since the countdown was armed.
        Returns 0 if disarmed or no tick has been received yet.
        """
        with self._lock:
            if self._start_ns is None or self._current_ns is None:
                return 0
            return (self._current_ns - self._start_ns) // 1_000_000

    def remaining_ms(self, load_ms: int) -> int:
        """
        Milliseconds remaining before *load_ms* is reached.
        Returns *load_ms* if disarmed; never negative.
        """
        return max(0, load_ms - self.elapsed_ms())

    def is_expired(self, load_ms: int) -> bool:
        """
        Return True if the countdown has reached zero (elapsed ≥ load_ms)
        and the clock is currently armed.
        """
        if load_ms == 0:
            return False
        with self._lock:
            if self._start_ns is None or self._current_ns is None:
                return False
            return (self._current_ns - self._start_ns) // 1_000_000 >= load_ms

    def is_expired_ns(self, duration_ns: int) -> bool:
        """
        Return True if *duration_ns* nanoseconds have elapsed since arm().

        More precise than :meth:`is_expired` (millisecond granularity):
        use this when the timeout is derived from hardware clock cycles,
        e.g.::

            # AHB burst: (1 + beats) HCLK cycles
            duration_ns = (1 + beats) * NS_PER_HCLK
            if clock.is_expired_ns(duration_ns): ...
        """
        if duration_ns <= 0:
            return True
        with self._lock:
            if self._start_ns is None or self._current_ns is None:
                return False
            return (self._current_ns - self._start_ns) >= duration_ns


# ---------------------------------------------------------------------------
# DmaRequestInterface — abstract DREQ/DACK peripheral DMA protocol
# ---------------------------------------------------------------------------

class DmaRequestInterface(ABC):
    """
    Abstract interface for a peripheral to request DMA transfers.

    Models the hardware DREQ/DACK handshake: a peripheral asserts a DMA
    request (DREQ) by calling ``transfer()``; the DMA controller either
    accepts (DACK, returns True) or declines (NACK, returns False).  On
    completion the controller calls the provided ``callback``.

    Implemented by ``DmaClientHandle`` in ``dma_controller.py``.  Device
    models that need DMA capability accept this interface type in their
    constructor, decoupling them from the concrete DMA controller and making
    them independently testable.

    Usage::

        class MyDevice(MMIODevice):
            def __init__(self, dma: DmaRequestInterface, ...):
                self._dma = dma

            def _start_transfer(self, src, dst, length):
                accepted = self._dma.transfer(
                    src=src, dst=dst, length=length,
                    callback=self._on_dma_done,
                )
                if not accepted:
                    print('DMA NACK — channel busy')

            def _on_dma_done(self, success: bool) -> None:
                ...
    """

    @abstractmethod
    def transfer(
        self,
        src: int,
        dst: int,
        length: int,
        callback: 'Callable[[bool], None]',
        *,
        src_fixed: bool = False,
        dst_fixed: bool = False,
    ) -> bool:
        """
        Request a DMA transfer (assert DREQ).

        Returns True (DACK) if the channel accepted the request, False
        (NACK) if the channel is busy.  *callback(success: bool)* is invoked
        from the DMA controller's tick thread when the transfer completes.

        ``src_fixed=True``: source address does not increment (P2x, e.g.
        reading a peripheral FIFO register).
        ``dst_fixed=True``: destination address does not increment (xP, e.g.
        writing to a CRC data register or TX FIFO).
        """

    @property
    @abstractmethod
    def busy(self) -> bool:
        """True if a transfer is already in progress on this channel."""

    @property
    @abstractmethod
    def channel_id(self) -> int:
        """The DMA channel index this handle is bound to."""
