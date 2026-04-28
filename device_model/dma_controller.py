"""
dma_controller — Multi-channel DMA controller (MMIODevice).

This module implements the complete DMA controller IP as it would appear in a
real SoC: a single MMIO-mapped device that firmware programs directly, with N
independent channels each having its own register set.  The same controller
also serves as the DMA engine for other peripherals that use the
DREQ/DACK handshake interface (DmaClientHandle).

Architecture
------------

  DmaController(MMIODevice)
  │
  ├─ MMIO register space  (firmware r/w via QEMU chardev)
  │   CH0: offset 0x000  SRC_ADDR / DST_ADDR / LENGTH / CTRL / STATUS
  │   CH1: offset 0x020  SRC_ADDR / DST_ADDR / LENGTH / CTRL / STATUS
  │   …
  │
  ├─ MemChannel            physical memory bus-master (shared by all channels)
  ├─ on_tick(vtime_ns)     advances every BUSY channel (tick observer)
  │
  └─ get_handle(ch) → DmaClientHandle
       Peripheral devices obtain a handle once at init time and call
       handle.transfer(src, dst, length, callback) to request a DMA
       operation — analogous to asserting a hardware DREQ line.
       The controller responds with DACK (True) or NACK (False).

Channel register layout (stride = 0x20 per channel)
----------------------------------------------------
  offset +0x00  CH_SRC_ADDR  RW  Source address
  offset +0x04  CH_DST_ADDR  RW  Destination address
  offset +0x08  CH_LENGTH    RW  Transfer length in bytes
  offset +0x0C  CH_CTRL      RW  bit0=START (firmware-triggered), bit1=ENABLE
  offset +0x10  CH_STATUS    R   bit0=BUSY, bit1=DONE

Transfer modes
--------------
  Memory-to-memory (M2M):
    Firmware writes SRC/DST/LENGTH/CTRL registers → controller copies.

  Peripheral-to-memory / memory-to-peripheral (P2M / M2P):
    A peripheral holds a DmaClientHandle and calls handle.transfer().
    The controller allocates the bound channel and performs the copy.
    On completion the controller calls the peripheral's callback (TC signal).
    The STATUS register of that channel also reflects DONE.

Both modes share the same tick-driven latency and MemChannel transport.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

from device_model.mmio_base import IRQController, MemChannel, MMIODevice


# ---------------------------------------------------------------------------
# Channel register offsets (within one channel's 0x20-byte slot)
# ---------------------------------------------------------------------------

_CH_SRC_ADDR = 0x00
_CH_DST_ADDR = 0x04
_CH_LENGTH   = 0x08
_CH_CTRL     = 0x0C
_CH_STATUS   = 0x10
_CH_MODE     = 0x14   # bit0=DEST_FIXED: 1=M2P (fixed dest), 0=M2M (incr dest)
_CH_STRIDE   = 0x20   # bytes per channel register block

# CTRL bits
_CTRL_START  = 0x01
_CTRL_ENABLE = 0x02

# MODE bits
_MODE_DEST_FIXED = 0x01   # destination address is fixed (M2P / memory-to-peripheral)

# STATUS bits
_STATUS_BUSY = 0x01
_STATUS_DONE = 0x02


# ---------------------------------------------------------------------------
# Internal per-channel state
# ---------------------------------------------------------------------------

class _DmaChannel:
    """Runtime state for one DMA channel."""

    IDLE = 'IDLE'
    BUSY = 'BUSY'

    def __init__(self, idx: int) -> None:
        self.idx              = idx
        self.state            = self.IDLE
        self.src              = 0
        self.dst              = 0
        self.length           = 0
        self.dest_fixed       = False   # True = M2P mode (fixed destination)
        self.ticks_remaining  = 0
        self.on_complete: Optional[Callable[[bool], None]] = None


# ---------------------------------------------------------------------------
# DMA controller — the actual MMIO device
# ---------------------------------------------------------------------------

class DmaController(MMIODevice):
    """
    Multi-channel DMA controller.

    Implements ``MMIODevice`` so it can be registered on the ``MMIOBus``
    and receive reads/writes from firmware via QEMU's chardev protocol.

    Each channel occupies a 0x20-byte register slot:
        CH0 @ base+0x000 … base+0x01F
        CH1 @ base+0x020 … base+0x03F
        …

    The controller is also a tick observer: call
    ``bus.add_tick_observer(dma_ctrl)`` so ``on_tick()`` is invoked once
    per virtual-clock tick.

    Peripheral devices obtain a ``DmaClientHandle`` via ``get_handle(ch)``
    and call ``handle.transfer(src, dst, length, callback)`` to trigger
    a transfer without touching the MMIO register space.
    """

    def __init__(
        self,
        num_channels: int,
        mem_channel: Optional[MemChannel] = None,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        transfer_ticks: int = 10,
    ) -> None:
        n = num_channels
        self._num_channels   = n
        self._regsize        = n * _CH_STRIDE
        self._regs           = bytearray(self._regsize)
        self._channels       = [_DmaChannel(i) for i in range(n)]
        self._locks          = [threading.Lock() for _ in range(n)]
        self._mem            = mem_channel
        self._irq_ctrl       = irq_controller
        self._irq_idx        = irq_idx
        self._transfer_ticks = transfer_ticks

    @property
    def name(self) -> str:
        return f'DmaController({self._num_channels}ch)'

    # -- MMIODevice interface (firmware register access) ------------------

    def read(self, offset: int, size: int) -> bytes:
        end = offset + size
        if end <= self._regsize:
            ch_idx = offset // _CH_STRIDE
            with self._locks[ch_idx]:
                return bytes(self._regs[offset:end])
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        end = offset + size
        if end > self._regsize:
            return
        ch_idx    = offset // _CH_STRIDE
        ch_base   = ch_idx * _CH_STRIDE
        ctrl_abs  = ch_base + _CH_CTRL

        with self._locks[ch_idx]:
            self._regs[offset:end] = data[:size]

        # Detect firmware CTRL.START write
        if offset <= ctrl_abs < end:
            if self._regs[ctrl_abs] & _CTRL_START:
                with self._locks[ch_idx]:
                    self._regs[ctrl_abs] &= ~_CTRL_START   # clear START (write-once)
                self._firmware_start(ch_idx)

    def on_reset(self) -> None:
        for lock in self._locks:
            with lock:
                pass   # no-op, just drain any pending
        self._regs[:] = bytearray(self._regsize)
        for ch in self._channels:
            ch.state = _DmaChannel.IDLE

    # -- Tick observer interface ------------------------------------------

    def on_tick(self, vtime_ns: int) -> None:
        """Advance all BUSY channels by one tick."""
        for ch in self._channels:
            self._tick_channel(ch, vtime_ns)

    # -- Peripheral DREQ/DACK interface -----------------------------------

    def get_handle(self, channel_id: int) -> 'DmaClientHandle':
        """Return a DmaClientHandle bound to *channel_id*.

        The peripheral calls ``handle.transfer()`` to assert DREQ.
        Raises ValueError if *channel_id* is out of range.
        """
        if channel_id >= self._num_channels:
            raise ValueError(
                f'DmaController: channel {channel_id} out of range '
                f'(num_channels={self._num_channels})'
            )
        return DmaClientHandle(self, channel_id)

    def _peripheral_request(
        self,
        channel_id: int,
        src: int,
        dst: int,
        length: int,
        on_complete: Callable[[bool], None],
    ) -> bool:
        """Internal: accept a DREQ from a peripheral (via DmaClientHandle).

        Returns True (DACK) if the channel was idle, False (NACK) if busy.
        """
        ch   = self._channels[channel_id]
        lock = self._locks[channel_id]

        with lock:
            if ch.state == _DmaChannel.BUSY:
                return False
            self._arm_channel(ch, src, dst, length, on_complete)

        print(
            f'[DMA] CH{channel_id}: DACK — peripheral request accepted '
            f'src=0x{src:08x} dst=0x{dst:08x} len={length} '
            f'({self._transfer_ticks} ticks)',
            flush=True,
        )
        return True

    def channel_busy(self, channel_id: int) -> bool:
        with self._locks[channel_id]:
            return self._channels[channel_id].state == _DmaChannel.BUSY

    # -- Internal helpers -------------------------------------------------

    def _firmware_start(self, ch_idx: int) -> None:
        """Firmware wrote CTRL.START — read registers and arm channel."""
        ch      = self._channels[ch_idx]
        base    = ch_idx * _CH_STRIDE
        lock    = self._locks[ch_idx]

        with lock:
            src    = int.from_bytes(self._regs[base + _CH_SRC_ADDR : base + _CH_SRC_ADDR + 4], 'little')
            dst    = int.from_bytes(self._regs[base + _CH_DST_ADDR : base + _CH_DST_ADDR + 4], 'little')
            length = int.from_bytes(self._regs[base + _CH_LENGTH   : base + _CH_LENGTH   + 4], 'little')
            mode   = int.from_bytes(self._regs[base + _CH_MODE     : base + _CH_MODE     + 4], 'little')
            dest_fixed = bool(mode & _MODE_DEST_FIXED)
            if ch.state == _DmaChannel.BUSY:
                print(f'[DMA] CH{ch_idx}: START ignored — channel already BUSY', flush=True)
                return
            self._arm_channel(ch, src, dst, length, on_complete=None,
                              dest_fixed=dest_fixed)

        mode_str = 'M2P(fixed-dst)' if dest_fixed else 'M2M'
        print(
            f'[DMA] CH{ch_idx}: firmware START [{mode_str}] — '
            f'src=0x{src:08x} dst=0x{dst:08x} len={length} '
            f'({self._transfer_ticks} ticks)',
            flush=True,
        )

    def _arm_channel(
        self,
        ch: _DmaChannel,
        src: int,
        dst: int,
        length: int,
        on_complete: Optional[Callable[[bool], None]],
        dest_fixed: bool = False,
    ) -> None:
        """Arm *ch* for transfer. Caller must hold self._locks[ch.idx]."""
        base = ch.idx * _CH_STRIDE
        ch.state           = _DmaChannel.BUSY
        ch.src             = src
        ch.dst             = dst
        ch.length          = length
        ch.dest_fixed      = dest_fixed
        ch.ticks_remaining = self._transfer_ticks
        ch.on_complete     = on_complete
        self._regs[base + _CH_STATUS] = _STATUS_BUSY

    def _tick_channel(self, ch: _DmaChannel, vtime_ns: int) -> None:
        lock = self._locks[ch.idx]
        base = ch.idx * _CH_STRIDE

        with lock:
            if ch.state != _DmaChannel.BUSY:
                return
            ch.ticks_remaining -= 1
            if ch.ticks_remaining > 0:
                return

            # Snapshot and mark idle before blocking TCP I/O.
            src      = ch.src
            dst      = ch.dst
            length   = ch.length
            callback = ch.on_complete
            ch.state = _DmaChannel.IDLE

        # Bus-master copy outside the per-channel lock.
        success = False
        if self._mem and length > 0:
            data = self._mem.dma_read(src, length)
            if data:
                if ch.dest_fixed:
                    # M2P mode: write each byte individually to the fixed dest
                    # (e.g. a peripheral MMIO register like CRC_DATA_REG).
                    # QEMU dispatches each cpu_physical_memory_write(dst, 1B)
                    # through the destination device's MemoryRegion write callback.
                    for b in data:
                        self._mem.dma_write(dst, bytes([b]))
                    # Synchronisation fence: dma_write is fire-and-forget; the
                    # IRQ travels over a DIFFERENT socket than the mem writes, so
                    # QEMU's event-loop could process the IRQ before all N writes.
                    # A synchronous dma_read on the SAME mem socket forces QEMU to
                    # drain all preceding writes first (TCP FIFO within one conn).
                    # After this returns, all bytes are guaranteed to have been
                    # forwarded to the CRC device before the IRQ fires.
                    self._mem.dma_read(src, 1)   # flush fence; result discarded
                    print(
                        f'[DMA] CH{ch.idx}: M2P {length}B '
                        f'src=0x{src:08x} → dst=0x{dst:08x} (fixed) @{vtime_ns}ns',
                        flush=True,
                    )
                else:
                    # M2M mode: single bulk write to incrementing destination
                    self._mem.dma_write(dst, data)
                    print(
                        f'[DMA] CH{ch.idx}: copied {length}B '
                        f'0x{src:08x} → 0x{dst:08x} @{vtime_ns}ns',
                        flush=True,
                    )
                success = True
            else:
                print(
                    f'[DMA] CH{ch.idx}: dma_read 0x{src:08x} failed',
                    file=sys.stderr, flush=True,
                )
        elif length == 0:
            success = True

        # Update STATUS register.
        with lock:
            self._regs[base + _CH_STATUS] = (
                (self._regs[base + _CH_STATUS] & ~_STATUS_BUSY) | _STATUS_DONE
            )

        # Notify peripheral callback (P2M/M2P path).
        if callback:
            callback(success)
        else:
            # Firmware-triggered path: pulse the shared DMA IRQ.
            if self._irq_ctrl is not None:
                self._irq_ctrl.set_irq(self._irq_idx, 1)
                print(f'[DMA] CH{ch.idx}: transfer complete @{vtime_ns}ns — IRQ asserted', flush=True)
                self._irq_ctrl.set_irq(self._irq_idx, 0)
                print(f'[DMA] CH{ch.idx}: IRQ deasserted', flush=True)
            else:
                print(f'[DMA] CH{ch.idx}: transfer complete (no IRQ wired)', flush=True)


# ---------------------------------------------------------------------------
# Per-peripheral handle  (hardware DREQ/DACK interface)
# ---------------------------------------------------------------------------

class DmaClientHandle:
    """
    Peripheral-side interface to one DMA channel inside DmaController.

    Each peripheral model holds one DmaClientHandle, obtained from
    ``DmaController.get_handle(channel_id)``.

    Hardware analogy
    ----------------
    ``transfer()``      ↔  peripheral asserts DREQ
    returns True        ↔  DMA controller asserts DACK (channel accepted)
    returns False       ↔  channel busy — NACK
    ``on_complete(ok)`` ↔  DMA controller asserts TC (transfer complete)

    Usage
    -----
    ::

        class MyPeripheral(MMIODevice):
            def __init__(self, dma_ctrl: DmaController, ch: int, ...):
                self._dma = dma_ctrl.get_handle(ch)

            def _on_rx_fifo_full(self):
                ok = self._dma.transfer(fifo_addr, buf_addr, n, self._on_done)

            def _on_done(self, success: bool) -> None:
                # called from DmaController tick thread
                self._set_status_done()
                self._pulse_irq()
    """

    def __init__(self, controller: DmaController, channel_id: int) -> None:
        self._ctrl       = controller
        self._channel_id = channel_id

    def transfer(
        self,
        src: int,
        dst: int,
        length: int,
        on_complete: Callable[[bool], None],
    ) -> bool:
        """Assert DREQ — request a DMA transfer.

        Returns True (DACK) if accepted, False (NACK) if channel busy.
        *on_complete(success)* is called from the DmaController tick thread.
        """
        return self._ctrl._peripheral_request(
            self._channel_id, src, dst, length, on_complete
        )

    @property
    def busy(self) -> bool:
        return self._ctrl.channel_busy(self._channel_id)

    @property
    def channel_id(self) -> int:
        return self._channel_id


