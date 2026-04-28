"""
dma_model — Simple DMA controller device model.

Register map (offsets from device base address, see spec/dma.yaml):
  0x00  SRC_ADDR  RW  DMA source address
  0x04  DST_ADDR  RW  DMA destination address
  0x08  LENGTH    RW  Transfer length in bytes
  0x0C  CTRL      RW  bit0=START, bit1=ENABLE
  0x10  STATUS    R   bit0=BUSY, bit1=DONE

Tick-based transfer latency
---------------------------
When firmware writes CTRL.START, the DMA does not complete immediately.
Instead it sets STATUS.BUSY and counts virtual-clock ticks delivered via
``on_tick()`` (from the shared ``TickServer``).  After ``transfer_ticks``
ticks have elapsed, the transfer is marked DONE, STATUS.BUSY is cleared,
and an IRQ is asserted if a controller is wired.

This mirrors how real DMA controllers take a non-zero number of bus cycles
to complete a transfer, and ties the latency to QEMU's virtual clock so it
is correct under pause/step/debug.

The default ``transfer_ticks=10`` is a configurable stub value; set it to
reflect realistic bus bandwidth in your simulation.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_model.mmio_base import IRQController, MemChannel, MMIODevice  # noqa: E402


class DmaDevice(MMIODevice):
    """
    DMA controller with tick-based transfer latency.

    Offset  Name      Access  Description
    ------  --------  ------  -------------------------------------------
    0x00    SRC_ADDR  RW      DMA source address
    0x04    DST_ADDR  RW      DMA destination address
    0x08    LENGTH    RW      Transfer length in bytes
    0x0C    CTRL      RW      bit0=START, bit1=ENABLE
    0x10    STATUS    R       bit0=BUSY, bit1=DONE
    """

    # Register offsets
    _SRC_ADDR = 0x00
    _DST_ADDR = 0x04
    _LENGTH   = 0x08
    _CTRL     = 0x0C
    _STATUS   = 0x10
    _REGSIZE  = 0x14

    # CTRL bits
    _CTRL_START  = 0x01
    _CTRL_ENABLE = 0x02

    # STATUS bits
    _STATUS_BUSY = 0x01
    _STATUS_DONE = 0x02

    def __init__(
        self,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        transfer_ticks: int = 10,
        mem_channel: Optional[MemChannel] = None,
    ) -> None:
        self._regs          = bytearray(self._REGSIZE)
        self._irq_ctrl      = irq_controller
        self._irq_idx       = irq_idx
        self._transfer_ticks = transfer_ticks   # virtual ticks to complete a transfer
        self._ticks_remaining: Optional[int] = None   # None = idle
        self._mem_channel   = mem_channel
        self._lock          = threading.Lock()

    @property
    def name(self) -> str:
        return 'DMA'

    # -- MMIODevice interface ---------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        end = offset + size
        if end <= self._REGSIZE:
            with self._lock:
                return bytes(self._regs[offset:end])
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        end = offset + size
        if end > self._REGSIZE:
            return
        with self._lock:
            self._regs[offset:end] = data[:size]
        # Trigger on CTRL.START
        if offset <= self._CTRL < end:
            if self._regs[self._CTRL] & self._CTRL_START:
                # Clear START bit immediately (write-once semantics)
                with self._lock:
                    self._regs[self._CTRL] &= ~self._CTRL_START
                self._start_transfer()

    def on_reset(self) -> None:
        with self._lock:
            self._regs[:] = bytearray(self._REGSIZE)
            self._ticks_remaining = None

    # -- Virtual-clock tick handler ---------------------------------------

    def on_tick(self, vtime_ns: int) -> None:
        """Count down ticks after a transfer starts; complete on zero."""
        with self._lock:
            if self._ticks_remaining is None:
                return
            self._ticks_remaining -= 1
            if self._ticks_remaining > 0:
                return
            # Snapshot transfer parameters before releasing the lock
            self._ticks_remaining = None
            src_addr = int.from_bytes(self._regs[self._SRC_ADDR:self._SRC_ADDR + 4], 'little')
            dst_addr = int.from_bytes(self._regs[self._DST_ADDR:self._DST_ADDR + 4], 'little')
            length   = int.from_bytes(self._regs[self._LENGTH:self._LENGTH + 4], 'little')

        # Perform DMA bus-master copy outside the lock (may block on TCP)
        if self._mem_channel and length > 0:
            data = self._mem_channel.dma_read(src_addr, length)
            if data:
                self._mem_channel.dma_write(dst_addr, data)
                print(
                    f'[DMA]  copied {length}B: 0x{src_addr:08x} → 0x{dst_addr:08x}',
                    flush=True,
                )
            else:
                print(
                    f'[DMA]  dma_read from 0x{src_addr:08x} failed',
                    file=sys.stderr, flush=True,
                )

        with self._lock:
            self._regs[self._STATUS] = (self._regs[self._STATUS] & ~self._STATUS_BUSY) | self._STATUS_DONE

        # Fire IRQ outside the lock — assert then immediately deassert (pulse).
        # The NVIC latches the rising edge as a pending bit; deassert before
        # the handler returns so the NVIC does not re-fire on exception return.
        if self._irq_ctrl is not None:
            self._irq_ctrl.set_irq(self._irq_idx, 1)
            print(f'[DMA]  transfer complete at vtime={vtime_ns} ns — IRQ asserted',
                  flush=True)
            self._irq_ctrl.set_irq(self._irq_idx, 0)
            print(f'[DMA]  IRQ deasserted', flush=True)
        else:
            print('[DMA]  transfer complete (no IRQ controller wired)', flush=True)

    # -- Transfer logic ---------------------------------------------------

    def _start_transfer(self) -> None:
        """
        Called when firmware sets CTRL.START.

        Sets STATUS.BUSY and arms the tick countdown.  After
        ``transfer_ticks`` virtual ticks the transfer completes via
        ``on_tick()``.
        """
        with self._lock:
            src    = int.from_bytes(self._regs[self._SRC_ADDR:self._SRC_ADDR + 4], 'little')
            dst    = int.from_bytes(self._regs[self._DST_ADDR:self._DST_ADDR + 4], 'little')
            length = int.from_bytes(self._regs[self._LENGTH:self._LENGTH + 4], 'little')
            self._regs[self._STATUS] = self._STATUS_BUSY
            self._ticks_remaining    = self._transfer_ticks

        print(
            f'[DMA] transfer started: src=0x{src:08x} dst=0x{dst:08x}'
            f' len={length} — will complete in {self._transfer_ticks} ticks',
            flush=True,
        )
