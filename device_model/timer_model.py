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

``VirtualClock.update(vtime_ns)`` records the timestamp each tick.
``VirtualClock.arm()`` captures the start time when CTRL.ENABLE is written.
``VirtualClock.is_expired(load_ms)`` returns True once the elapsed virtual
time reaches or exceeds load_ms × 1 000 000 ns.

This means the timer is correct even if QEMU is paused (gdb breakpoint,
single-step, etc.) — the virtual clock stops, Python gets no ticks, and no
spurious IRQs fire.
"""
from __future__ import annotations

from typing import Optional

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, RegAccess, RegisterBank, VirtualClock
from device_model.tracer    import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class TimerDevice(MMIODevice):
    """Countdown timer with one-shot and periodic modes."""

    @property
    def name(self) -> str:
        return self._name

    # Register offsets
    _LOAD   = 0x00
    _VALUE  = 0x04
    _CTRL   = 0x08
    _STATUS = 0x0C
    _INTCLR = 0x10
    _REGSIZE = 0x14

    # CTRL bit masks
    _CTRL_ENABLE     = 0x01
    _CTRL_PERIODIC   = 0x02
    _CTRL_INT_ENABLE = 0x04

    # STATUS bit masks
    _STATUS_INT_PENDING = 0x01

    def __init__(
        self,
        name: str = 'timer0',
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._name  = name
        self._regs  = RegisterBank(
            self._REGSIZE,
            policies={
                # STATUS: written by hardware (set_bits); CPU reads only.
                self._STATUS: RegAccess.READ_ONLY,
                # VALUE:  computed on-the-fly in read(); CPU reads only.
                self._VALUE:  RegAccess.READ_ONLY,
                # INTCLR: pulse register — reads always return 0.
                self._INTCLR: RegAccess.WRITE_ONLY,
            },
        )
        self._irq   = IrqLine(irq_controller, irq_idx)
        self._clock = VirtualClock()
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

    # ------------------------------------------------------------------ #
    # MMIODevice interface                                                 #
    # ------------------------------------------------------------------ #

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._VALUE:
            # VALUE is computed from the virtual clock, not from stored bytes.
            load_ms = self._regs.get32(self._LOAD)
            remaining = self._clock.remaining_ms(load_ms)
            return (remaining & 0xFFFF_FFFF).to_bytes(4, 'little')[:size]
        # INTCLR → WRITE_ONLY policy returns 0; STATUS → READ_ONLY returns stored.
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes) -> int:
        # STATUS (READ_ONLY) and VALUE (READ_ONLY): policy silently drops writes.
        # INTCLR (WRITE_ONLY): policy stores the value, but we intercept below
        # to trigger the side effect (clear STATUS.INT_PENDING, deassert IRQ).
        self._regs.write(offset, size, data)

        next_event_ns = 0
        if offset <= self._CTRL < offset + size:
            ctrl = self._regs.get32(self._CTRL)
            if ctrl & self._CTRL_ENABLE:
                self._clock.arm()
                load_ms = self._regs.get32(self._LOAD)
                expire_ns = load_ms * 1_000_000
                print(f'[TMR] Timer armed — load={load_ms}ms expire_ns={expire_ns}')
                self._tr.emit('ARM', load_ms=load_ms)
                # DES: return expire_ns so QEMU schedules a precise tick
                next_event_ns = expire_ns
            else:
                self._clock.disarm()
                print('[TMR] Timer disarmed')
                self._tr.emit('DISARM')

        if offset <= self._INTCLR < offset + size:
            self._regs.clear_bits(self._STATUS, self._STATUS_INT_PENDING)
            self._irq.deassert()
            print(f'[TMR] IRQ {self._irq.idx} deasserted (INTCLR)')
            self._tr.emit('INTCLR', irq_idx=self._irq.idx)

        return next_event_ns

    def on_reset(self) -> None:
        self._regs.reset()
        self._clock.disarm()
        print('[TMR] Reset')
        self._tr.emit('RESET')

    # ------------------------------------------------------------------ #
    # Virtual-clock tick entry point                                       #
    # Called by TickServer on every 'T' message received from QEMU.       #
    # ------------------------------------------------------------------ #

    def on_tick(self, vtime_ns: int) -> int:
        """Advance the virtual clock and check for timer expiry."""
        self._tr.tick(vtime_ns)
        self._clock.update(vtime_ns)

        load_ms = self._regs.get32(self._LOAD)
        if not self._clock.is_expired(load_ms):
            return 0

        # ---- Expired ----
        self._regs.set_bits(self._STATUS, self._STATUS_INT_PENDING)
        ctrl = self._regs.get32(self._CTRL)

        if ctrl & self._CTRL_PERIODIC:
            self._clock.rearm_periodic(load_ms * 1_000_000)
        else:
            self._clock.disarm()

        if ctrl & self._CTRL_INT_ENABLE:
            self._irq.assert_()
            print(f'[TMR] Timer expired at vtime={vtime_ns} ns '
                  f'— IRQ {self._irq.idx} asserted')
            self._tr.emit('EXPIRE', load_ms=load_ms)
            self._tr.emit('IRQ_ASSERT', irq_idx=self._irq.idx)
        return 0
