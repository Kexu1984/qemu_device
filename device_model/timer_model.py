"""
timer_model — countdown timer device model (virtual-clock, Python-side)

Register map (offsets from device base, see spec/timer.yaml):
  0x00  LOAD    RW  Countdown load value in milliseconds
  0x04  VALUE   R   Remaining time in ms (based on QEMU virtual clock)
  0x08  CTRL    RW  bit0=ENABLE, bit1=PERIODIC, bit2=INT_ENABLE
  0x0C  STATUS  R   bit0=INT_PENDING (set on expiry, cleared by INTCLR write)
  0x10  INTCLR  W   Write any value to clear INT_PENDING and deassert IRQ

Virtual-clock architecture
--------------------------
Timer ticks are driven by QEMU's QEMU_CLOCK_VIRTUAL via the tick-chardev
channel added to mmio_sockdev.c.  Every tick-period-ms of simulated time
QEMU sends:

    'T'(1B) | vtime_ns(8B LE)

Python records the virtual nanosecond timestamp when CTRL.ENABLE is written
(_start_vtime_ns) and checks on every received tick whether the countdown
has expired:

    expired = (vtime_ns - _start_vtime_ns) >= load_ms * 1_000_000

This means the timer is correct even if QEMU is paused (gdb breakpoint,
single-step, etc.) — the virtual clock stops, Python gets no ticks, and no
spurious IRQs fire.

The TickServer in mmio_device_server.py accepts the TCP connection from QEMU,
reads tick messages, and calls TimerDevice.on_tick(vtime_ns) for each one.
"""
from __future__ import annotations

import threading
from typing import Optional

from device_model.mmio_base import IRQController, MMIODevice


class TimerDevice(MMIODevice):
    """Countdown timer with one-shot and periodic modes."""

    @property
    def name(self) -> str:
        return 'timer0'

    # Register offsets
    _LOAD   = 0x00
    _VALUE  = 0x04
    _CTRL   = 0x08
    _STATUS = 0x0C
    _INTCLR = 0x10
    _REGSIZE = 0x14   # contiguous register block size

    # CTRL bit masks
    _CTRL_ENABLE     = 0x01
    _CTRL_PERIODIC   = 0x02
    _CTRL_INT_ENABLE = 0x04

    # STATUS bit masks
    _STATUS_INT_PENDING = 0x01

    def __init__(
        self,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
    ) -> None:
        self._regs = bytearray(self._REGSIZE)
        self._irq_ctrl   = irq_controller
        self._irq_idx    = irq_idx
        self._lock       = threading.Lock()
        # Virtual nanosecond timestamp when the current countdown started.
        # Set to None when the timer is disabled or has not started.
        self._start_vtime_ns: Optional[int] = None
        # Last virtual nanosecond received from QEMU (for VALUE reads).
        self._last_vtime_ns:  Optional[int] = None

    # ------------------------------------------------------------------ #
    # MMIODevice interface                                                 #
    # ------------------------------------------------------------------ #

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._VALUE:
            return self._read_value(size)
        if offset == self._INTCLR:
            # Write-only register — reads as zero
            return b'\x00' * size
        end = offset + size
        if end <= self._REGSIZE:
            with self._lock:
                return bytes(self._regs[offset:end])
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        end = offset + size
        if end > self._REGSIZE:
            return

        # STATUS is read-only; VALUE is read-only — ignore writes to them.
        if offset not in (self._VALUE, self._STATUS):
            with self._lock:
                self._regs[offset:end] = data[:size]

        # React to CTRL write
        if offset <= self._CTRL < end:
            ctrl = self._regs[self._CTRL]   # already updated above
            if ctrl & self._CTRL_ENABLE:
                self._arm_timer()
            else:
                self._disarm_timer()

        # React to INTCLR write (write-any-value to clear)
        if offset <= self._INTCLR < end:
            with self._lock:
                self._regs[self._STATUS] &= ~self._STATUS_INT_PENDING
            if self._irq_ctrl is not None:
                self._irq_ctrl.set_irq(self._irq_idx, 0)
                print(f'[TMR] IRQ {self._irq_idx} deasserted (INTCLR)')

    # ------------------------------------------------------------------ #
    # Virtual-clock tick entry point                                       #
    # Called by TickServer on every 'T' message received from QEMU.       #
    # ------------------------------------------------------------------ #

    def on_tick(self, vtime_ns: int) -> None:
        """Advance the virtual clock.  Check for timer expiry."""
        with self._lock:
            self._last_vtime_ns = vtime_ns

            if self._start_vtime_ns is None:
                return  # timer not armed

            load_ms = int.from_bytes(
                self._regs[self._LOAD:self._LOAD + 4], 'little'
            )
            if load_ms == 0:
                return

            elapsed_ns = vtime_ns - self._start_vtime_ns
            load_ns    = load_ms * 1_000_000

            if elapsed_ns < load_ns:
                return  # not expired yet

            # ---- Expired ----
            self._regs[self._STATUS] |= self._STATUS_INT_PENDING
            ctrl = self._regs[self._CTRL]

            if ctrl & self._CTRL_PERIODIC:
                # Re-arm: advance start by exactly one period so drift
                # doesn't accumulate across multiple periods.
                self._start_vtime_ns += load_ns
            else:
                self._start_vtime_ns = None   # one-shot: disarm

        # Fire IRQ outside the lock
        if (ctrl & self._CTRL_INT_ENABLE) and self._irq_ctrl is not None:
            self._irq_ctrl.set_irq(self._irq_idx, 1)
            print(f'[TMR] Timer expired at vtime={vtime_ns} ns '
                  f'— IRQ {self._irq_idx} asserted')

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _read_value(self, size: int) -> bytes:
        """Return remaining time in ms based on last received virtual tick."""
        with self._lock:
            ctrl     = self._regs[self._CTRL]
            load_ms  = int.from_bytes(
                self._regs[self._LOAD:self._LOAD + 4], 'little'
            )
            start    = self._start_vtime_ns
            last     = self._last_vtime_ns

        if start is not None and (ctrl & self._CTRL_ENABLE) and last is not None:
            elapsed_ms = (last - start) // 1_000_000
            remaining  = max(0, load_ms - elapsed_ms)
        else:
            remaining = 0
        return (remaining & 0xFFFF_FFFF).to_bytes(4, 'little')[:size]

    def _arm_timer(self) -> None:
        """Record the virtual start time for the current countdown."""
        with self._lock:
            # Use the last known virtual time as the start reference.
            # If no tick has arrived yet, start_vtime_ns stays None until
            # the first tick comes in — at that point on_tick() will arm it.
            # We store a sentinel -1 to indicate "arm on next tick".
            self._start_vtime_ns = self._last_vtime_ns
        print('[TMR] Timer armed (waiting for tick to confirm start)')

    def _disarm_timer(self) -> None:
        """Stop the countdown."""
        with self._lock:
            self._start_vtime_ns = None
        print('[TMR] Timer disarmed')
