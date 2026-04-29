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

Timing model
------------
QEMU sends virtual-time ticks via tick-chardev every ``tick-period-ms=1`` of
virtual time.  The RW channel (firmware register writes) carries NO vtime_ns,
so Python only learns the current virtual time at tick boundaries.

  tick_period = 1 ms = 1,000,000 ns
  DMA transfer = 512 ns (32 B M2M at HCLK=48MHz)

Because tick_period >> transfer_ns for all practical transfers, waiting for
the *next* tick to fire the completion would add ~1 ms of artificial latency
(≈2000× the modelled 512 ns).  To avoid this, transfers are executed
immediately in a background thread when armed.  The on_tick() path remains
as a safety-net for any transfer that somehow did not complete before the
next tick (e.g. if the background thread was slow).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

from device_model.mmio_base import (
    AddressSpace, DmaRequestInterface, IRQController, IrqLine, MMIODevice,
    HCLK_HZ, NS_PER_HCLK, NS_PER_PCLK,
)


# ---------------------------------------------------------------------------
# Channel register offsets (within one channel's 0x20-byte slot)
# ---------------------------------------------------------------------------

_CH_SRC_ADDR = 0x00
_CH_DST_ADDR = 0x04
_CH_LENGTH   = 0x08
_CH_CTRL     = 0x0C
_CH_STATUS   = 0x10
_CH_SRC_MODE = 0x14   # bit0=FIXED: source address holds (P2x) vs increments
_CH_DST_MODE = 0x18   # bit0=FIXED: destination address holds (xP) vs increments
_CH_STRIDE   = 0x20   # bytes per channel register block

# CTRL bits
_CTRL_START  = 0x01
_CTRL_ENABLE = 0x02

# Address-mode bit (shared by SRC_MODE and DST_MODE)
_MODE_FIXED  = 0x01   # 0 = address increments after each byte, 1 = address fixed

# ---------------------------------------------------------------------------
# AHB/PCLK timing model
# ---------------------------------------------------------------------------
#
# KX6625 DMA engine: state machine runs on PCLK (12 MHz, APB domain);
# actual burst transfer is on AHB bus (HCLK = 48 MHz).
#
# Latency breakdown for a transfer of `length` bytes:
#
#   AHB address phase  :  1 HCLK cycle
#   AHB data beats     :  ceil(length / 4) HCLK cycles  (32-bit bus)
#   DMA FSM overhead   :  4 PCLK cycles  (fetch desc + DONE handshake)
#
# Example: 32 bytes
#   AHB: (1 + 8) × 20 ns  = 180 ns
#   FSM: 4 × 83 ns         = 332 ns
#   Total                  ≈ 512 ns  (vs 10 ms with tick-based model)

_DMA_FSM_PCLK_CYCLES = 4   # APB-domain state-machine overhead per transfer

# STATUS bits
_STATUS_BUSY = 0x01
_STATUS_DONE = 0x02


def _compute_transfer_ns(length: int) -> int:
    """Compute AHB-burst + PCLK-FSM latency in nanoseconds.

    AHB transfer (HCLK domain, 32-bit bus):
      - 1 address-phase cycle
      - ceil(length / 4) data-beat cycles
    DMA state-machine overhead (PCLK domain):
      - _DMA_FSM_PCLK_CYCLES cycles

    Minimum returned value is 1 PCLK cycle (avoids zero-latency instant done).
    """
    if length == 0:
        return NS_PER_PCLK   # zero-length: FSM overhead only
    ahb_beats  = (length + 3) // 4          # ceil(length / 4) 32-bit beats
    ahb_ns     = (1 + ahb_beats) * NS_PER_HCLK
    fsm_ns     = _DMA_FSM_PCLK_CYCLES * NS_PER_PCLK
    return ahb_ns + fsm_ns


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
        self.src_fixed        = False   # True = source address is held (P2x transfer)
        self.dst_fixed        = False   # True = dest address is held (xP transfer)
        self.transfer_ns      = 0       # latency in ns (computed from AHB + PCLK cycles)
        self.arm_vtime_ns     = -1      # vtime_ns when channel was armed (-1 = unset)
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
        address_space: Optional[AddressSpace] = None,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        tracer: Optional[Tracer] = None,
    ) -> None:
        n = num_channels
        self._num_channels   = n
        self._regsize        = n * _CH_STRIDE
        self._regs           = bytearray(self._regsize)
        self._channels       = [_DmaChannel(i) for i in range(n)]
        self._locks          = [threading.Lock() for _ in range(n)]
        self._addrspace      = address_space
        self._irq           = IrqLine(irq_controller, irq_idx)
        self._vtime_ns: int  = 0          # latest tick timestamp (ns)
        self._vtime_lock     = threading.Lock()
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

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
        self._tr.emit('RESET')

    # -- Tick observer interface ------------------------------------------

    def on_tick(self, vtime_ns: int) -> None:
        """Update virtual clock; execute any transfers that are still pending.

        For normal operation, transfers already completed synchronously when
        armed (see _arm_and_execute).  This path is a safety-net for any
        channel still BUSY at tick time (e.g. transfer thread delayed).
        """
        with self._vtime_lock:
            self._vtime_ns = vtime_ns
        self._tr.tick(vtime_ns)
        for ch in self._channels:
            with self._locks[ch.idx]:
                if ch.state == _DmaChannel.BUSY:
                    # Transfer thread is still running — let it finish.
                    pass

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
        src_fixed: bool = False,
        dst_fixed: bool = False,
    ) -> bool:
        """Internal: accept a DREQ from a peripheral (via DmaClientHandle).

        Returns True (DACK) if the channel was idle, False (NACK) if busy.
        """
        ch   = self._channels[channel_id]
        lock = self._locks[channel_id]

        with lock:
            if ch.state == _DmaChannel.BUSY:
                return False
            with self._vtime_lock:
                now_ns = self._vtime_ns
            self._arm_channel(ch, src, dst, length, on_complete,
                              src_fixed=src_fixed, dst_fixed=dst_fixed,
                              vtime_ns=now_ns)

        _MODE_NAMES = {(False,False):'M2M',(False,True):'M2P',(True,False):'P2M',(True,True):'P2P'}
        mode_str = _MODE_NAMES[(src_fixed, dst_fixed)]
        latency_ns = _compute_transfer_ns(length)
        print(
            f'[DMA] CH{channel_id}: DACK — peripheral request accepted [{mode_str}] '
            f'src=0x{src:08x} dst=0x{dst:08x} len={length} '
            f'(latency ~{latency_ns} ns)',
            flush=True,
        )
        self._tr.emit('CH_DREQ', ch=channel_id, src=src, dst=dst,
                      length=length, mode=mode_str, latency_ns=latency_ns)
        # Execute immediately: transfer_ns (sub-µs) << tick_period (1 ms)
        threading.Thread(
            target=self._execute_transfer, args=(ch, now_ns),
            daemon=True, name=f'dma-ch{channel_id}',
        ).start()
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
            src_mode   = int.from_bytes(self._regs[base + _CH_SRC_MODE : base + _CH_SRC_MODE + 4], 'little')
            dst_mode   = int.from_bytes(self._regs[base + _CH_DST_MODE : base + _CH_DST_MODE + 4], 'little')
            src_fixed  = bool(src_mode & _MODE_FIXED)
            dst_fixed  = bool(dst_mode & _MODE_FIXED)
            if ch.state == _DmaChannel.BUSY:
                print(f'[DMA] CH{ch_idx}: START ignored — channel already BUSY', flush=True)
                return
            with self._vtime_lock:
                now_ns = self._vtime_ns
            self._arm_channel(ch, src, dst, length, on_complete=None,
                              src_fixed=src_fixed, dst_fixed=dst_fixed,
                              vtime_ns=now_ns)

        _MODE_NAMES = {(False,False):'M2M',(False,True):'M2P',(True,False):'P2M',(True,True):'P2P'}
        mode_str = _MODE_NAMES[(src_fixed, dst_fixed)]
        latency_ns = _compute_transfer_ns(length)
        print(
            f'[DMA] CH{ch_idx}: firmware START [{mode_str}] — '
            f'src=0x{src:08x} dst=0x{dst:08x} len={length} '
            f'(latency ~{latency_ns} ns)',
            flush=True,
        )
        self._tr.emit('CH_START', ch=ch_idx, src=src, dst=dst,
                      length=length, mode=mode_str, latency_ns=latency_ns)
        # Execute immediately: transfer_ns (sub-µs) << tick_period (1 ms)
        threading.Thread(
            target=self._execute_transfer, args=(ch, now_ns),
            daemon=True, name=f'dma-ch{ch_idx}',
        ).start()

    def _arm_channel(
        self,
        ch: _DmaChannel,
        src: int,
        dst: int,
        length: int,
        on_complete: Optional[Callable[[bool], None]],
        src_fixed: bool = False,
        dst_fixed: bool = False,
        vtime_ns: int = 0,
    ) -> None:
        """Arm *ch* for transfer. Caller must hold self._locks[ch.idx]."""
        base = ch.idx * _CH_STRIDE
        ch.state          = _DmaChannel.BUSY
        ch.src            = src
        ch.dst            = dst
        ch.length         = length
        ch.src_fixed      = src_fixed
        ch.dst_fixed      = dst_fixed
        ch.transfer_ns    = _compute_transfer_ns(length)
        ch.arm_vtime_ns   = vtime_ns     # -1 if unknown; resolved on first tick
        ch.on_complete    = on_complete
        self._regs[base + _CH_STATUS] = _STATUS_BUSY

    def _execute_transfer(self, ch: _DmaChannel, arm_vtime_ns: int) -> None:
        """Perform the actual bus-master copy and fire completion signals.

        Called immediately after arming (in a background thread) so that
        sub-microsecond transfers are not artificially delayed to the next
        1 ms tick boundary.  The per-channel lock is NOT held on entry.

        The virtual time reported for DONE is the arm time plus the modelled
        AHB+PCLK latency — giving firmware a correct picture of when the
        transfer ended in the virtual-clock domain.
        """
        lock = self._locks[ch.idx]
        base = ch.idx * _CH_STRIDE
        _MODE_NAMES = {(False,False):'M2M',(False,True):'M2P',(True,False):'P2M',(True,True):'P2P'}

        with lock:
            if ch.state != _DmaChannel.BUSY:
                return   # already cancelled (e.g. reset while thread was starting)
            src      = ch.src
            dst      = ch.dst
            length   = ch.length
            xfer_ns  = ch.transfer_ns
            callback = ch.on_complete
            ch.state = _DmaChannel.IDLE

        # Virtual completion time = arm time + modelled AHB+PCLK latency
        done_vtime_ns = arm_vtime_ns + xfer_ns

        # Bus-master copy (outside per-channel lock — may block on TCP I/O)
        success = False
        if self._addrspace and length > 0:
            # --- Read source data -----------------------------------------
            if ch.src_fixed:
                # P2x: read repeatedly from the same source address
                # (e.g. a UART RX FIFO register or peripheral status reg).
                data: Optional[bytes] = b''
                for _ in range(length):
                    chunk = self._addrspace.read(src, 1)
                    if chunk is None:
                        data = None
                        break
                    data += chunk  # type: ignore[operator]
            else:
                # M2x: bulk read from incrementing source address (SRAM/flash).
                data = self._addrspace.read(src, length)

            if data:
                # --- Write destination data --------------------------------
                if ch.dst_fixed:
                    # xP: write each byte individually to the fixed destination
                    # (e.g. a CRC DATA register or TX FIFO).
                    for b in data:
                        self._addrspace.write(dst, bytes([b]))
                else:
                    # xM: bulk write to incrementing destination (SRAM).
                    self._addrspace.write(dst, data)

                mode_str = _MODE_NAMES[(ch.src_fixed, ch.dst_fixed)]
                print(
                    f'[DMA] CH{ch.idx}: {mode_str} {length}B '
                    f'src=0x{src:08x} → dst=0x{dst:08x} '
                    f'vtime={done_vtime_ns}ns (+{xfer_ns}ns)',
                    flush=True,
                )
                success = True
            else:
                print(
                    f'[DMA] CH{ch.idx}: read failed src=0x{src:08x}',
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
            self._tr.emit('CH_DONE', ch=ch.idx, ok=success, path='peripheral',
                          t_virt_ns_override=done_vtime_ns)
            callback(success)
        else:
            # Firmware-triggered path: pulse the shared DMA IRQ.
            if self._irq is not None:
                print(
                    f'[DMA] CH{ch.idx}: transfer complete '
                    f'vtime={done_vtime_ns}ns — IRQ asserted',
                    flush=True,
                )
                self._irq.pulse()
                self._tr.emit('CH_DONE', ch=ch.idx, ok=success,
                              t_virt_ns_override=done_vtime_ns)
                self._tr.emit('IRQ_PULSE', ch=ch.idx, irq_idx=self._irq.idx,
                              t_virt_ns_override=done_vtime_ns)
                print(f'[DMA] CH{ch.idx}: IRQ deasserted', flush=True)
            else:
                print(f'[DMA] CH{ch.idx}: transfer complete (no IRQ wired)', flush=True)
                self._tr.emit('CH_DONE', ch=ch.idx, ok=success,
                              t_virt_ns_override=done_vtime_ns)


# ---------------------------------------------------------------------------
# Per-peripheral handle  (hardware DREQ/DACK interface)
# ---------------------------------------------------------------------------

class DmaClientHandle(DmaRequestInterface):
    """
    Peripheral-side interface to one DMA channel inside DmaController.

    Each peripheral model holds one DmaClientHandle, obtained from
    ``DmaController.get_handle(channel_id)``.  Implements
    ``DmaRequestInterface`` so that device models can type-hint their DMA
    dependency as the abstract interface rather than a concrete class.

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
        src_fixed: bool = False,
        dst_fixed: bool = False,
    ) -> bool:
        """Assert DREQ — request a DMA transfer.

        Returns True (DACK) if accepted, False (NACK) if channel busy.
        *on_complete(success)* is called from the DmaController tick thread.

        ``src_fixed=True`` keeps the source address fixed after each byte
        (P2x transfer, e.g. reading a peripheral RX FIFO register).
        ``dst_fixed=True`` keeps the destination address fixed (xP transfer,
        e.g. writing a peripheral TX FIFO or CRC data register).
        """
        return self._ctrl._peripheral_request(
            self._channel_id, src, dst, length, on_complete,
            src_fixed=src_fixed, dst_fixed=dst_fixed,
        )

    @property
    def busy(self) -> bool:
        return self._ctrl.channel_busy(self._channel_id)

    @property
    def channel_id(self) -> int:
        return self._channel_id


