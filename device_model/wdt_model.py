"""
wdt_model — Watchdog Timer device model (Python-side)

Register map (offsets from device base, see spec/wdt.yaml):
  0x00  LOAD         RW  Timeout value in milliseconds (write before ENABLE)
  0x04  VALUE        R   Remaining time in ms (virtual-clock based)
  0x08  CTRL         RW  bit0=ENABLE, bit1=INT_ENABLE (warn IRQ before reset)
  0x0C  KICK         W   Write any value to reload countdown + clear TIMEOUT
  0x10  STATUS       R   bit0=TIMEOUT  (set when countdown reaches zero)
  0x14  RESET_REASON R   Retention: 0=POR  1=WDT_RESET
  0x18  TIMEOUT_CNT  R   Retention: cumulative WDT timeout count since power-on

Two-level reset architecture
-----------------------------
*Watchdog reset* (WDT timeout):
  1. Python WDT on_tick() detects expiry.
  2. Calls SystemResetManager.wdt_reset() (registered as reset_callback).
  3. SystemResetManager calls on_reset() on all bus devices (including WDT).
  4. WDT on_reset() clears volatile state (LOAD, CTRL, STATUS, countdown)
     but preserves retention registers (RESET_REASON=1, TIMEOUT_CNT+=1
     already set before on_reset() is called).
  5. SystemResetManager sends a byte via RstController → rst-chardev TCP.
  6. QEMU receives the byte and calls
     qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET).
  7. CPU resets, firmware restarts from the reset vector.
  8. Firmware reads RESET_REASON=1 and knows it was a WDT reset.

*Global reset* (power-on / Python server restart):
  All state including retention registers is cleared because the Python
  process starts fresh with default __init__ values.

Virtual-clock timing
---------------------
The countdown is driven by the shared virtual-clock tick broadcast from
TickServer (same stream used by TimerDevice).  WdtDevice.on_tick() is
called on every tick; it checks the elapsed virtual nanoseconds against
the loaded timeout.  Timing is therefore correct even during QEMU debug
pauses (the virtual clock stops, ticks stop, no spurious resets).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, VirtualClock
from device_model.tracer    import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class WdtDevice(MMIODevice):
    """Watchdog timer with virtual-clock countdown and retention registers."""

    @property
    def name(self) -> str:
        return 'wdt'

    # ── Register offsets ──────────────────────────────────────────────────
    _LOAD         = 0x00
    _VALUE        = 0x04
    _CTRL         = 0x08
    _KICK         = 0x0C
    _STATUS       = 0x10
    _RESET_REASON = 0x14
    _TIMEOUT_CNT  = 0x18

    # ── Bit masks ─────────────────────────────────────────────────────────
    _CTRL_ENABLE     = 0x01
    _CTRL_INT_ENABLE = 0x02
    _STATUS_TIMEOUT  = 0x01

    # ── RESET_REASON values ───────────────────────────────────────────────
    REASON_POR = 0x00   # power-on reset / global reset
    REASON_WDT = 0x01   # watchdog timeout reset

    def __init__(
        self,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        reset_callback: Optional[Callable[[], None]] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._irq            = IrqLine(irq_controller, irq_idx)
        self._reset_callback = reset_callback   # SystemResetManager.wdt_reset
        self._clock          = VirtualClock()
        self._lock           = threading.Lock()
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

        # ── Volatile registers (cleared by on_reset / watchdog reset) ────
        self._load_ms: int = 0
        self._ctrl:    int = 0
        self._status:  int = 0

        # ── Retention registers (survive watchdog reset) ──────────────────
        # These are set *before* on_reset() is called, then preserved.
        self._reset_reason: int = self.REASON_POR
        self._timeout_cnt:  int = 0

    # ── MMIODevice interface ──────────────────────────────────────────────

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        with self._lock:
            val = self._read_locked(offset, size)
        return val.to_bytes(size, 'little')

    def _read_locked(self, offset: int, size: int) -> int:
        if offset == self._LOAD:
            return self._load_ms
        if offset == self._VALUE:
            return self._clock.remaining_ms(self._load_ms)
        if offset == self._CTRL:
            return self._ctrl
        if offset == self._STATUS:
            return self._status
        if offset == self._RESET_REASON:
            return self._reset_reason
        if offset == self._TIMEOUT_CNT:
            return self._timeout_cnt
        return 0

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> None:
        value = int.from_bytes(data[:size], 'little')
        with self._lock:
            if offset == self._LOAD:
                self._load_ms = value
                print(f'[WDT] LOAD = {value} ms')
                self._tr.emit('LOAD', load_ms=value)

            elif offset == self._CTRL:
                prev_enable = self._ctrl & self._CTRL_ENABLE
                self._ctrl  = value
                if (value & self._CTRL_ENABLE) and not prev_enable:
                    # Arm from the most recent tick (or None if no tick yet;
                    # on_tick() will arm from the first tick in that case).
                    self._clock.arm()
                    self._status &= ~self._STATUS_TIMEOUT
                    print(f'[WDT] enabled, timeout = {self._load_ms} ms')
                    self._tr.emit('ARM', load_ms=self._load_ms)
                elif not (value & self._CTRL_ENABLE) and prev_enable:
                    self._clock.disarm()
                    print('[WDT] disabled')
                    self._tr.emit('DISARM')

            elif offset == self._KICK:
                # Reload countdown regardless of content written
                if self._ctrl & self._CTRL_ENABLE:
                    self._clock.arm()
                    self._status &= ~self._STATUS_TIMEOUT
                    print('[WDT] kicked — countdown reloaded')
                    self._tr.emit('KICK')

    # ── Reset handling ────────────────────────────────────────────────────

    def on_reset(self) -> None:
        """
        Called by SystemResetManager on watchdog reset.
        Clears volatile state; retention registers are preserved.
        """
        self._clock.disarm()
        with self._lock:
            self._load_ms = 0
            self._ctrl    = 0
            self._status  = 0
            # _reset_reason and _timeout_cnt are intentionally NOT cleared here.
            print(
                f'[WDT] on_reset(): volatile state cleared  '
                f'RESET_REASON={self._reset_reason}  '
                f'TIMEOUT_CNT={self._timeout_cnt}'
            )
        self._tr.emit('RESET', reset_reason=self._reset_reason,
                      timeout_cnt=self._timeout_cnt)

    # ── Virtual-clock tick ────────────────────────────────────────────────

    def on_tick(self, vtime_ns: int) -> None:
        """
        Advance the watchdog countdown using the virtual clock.

        Called by MMIOBus.tick_all() on every tick from TickServer.
        Fires the optional warning IRQ and schedules a system reset when
        the countdown reaches zero.
        """
        self._tr.tick(vtime_ns)
        self._clock.update(vtime_ns)

        fire_reset  = False
        fire_irq    = False

        with self._lock:
            if not (self._ctrl & self._CTRL_ENABLE):
                return

            # Arm on the first tick if CTRL.ENABLE was set before any tick
            # arrived (VirtualClock.arm() with no current_ns leaves start=None).
            if not self._clock.armed:
                self._clock.arm(vtime_ns)
                return

            if not self._clock.is_expired(self._load_ms):
                return

            # ── Timeout ─────────────────────────────────────────────────
            self._status   |= self._STATUS_TIMEOUT
            self._ctrl     &= ~self._CTRL_ENABLE   # disarm to prevent re-fire
            self._clock.disarm()

            # Update retention registers BEFORE on_reset() is called
            self._reset_reason  = self.REASON_WDT
            self._timeout_cnt  += 1
            cnt = self._timeout_cnt
            print(f'[WDT] TIMEOUT — reset_reason=WDT  timeout_cnt={cnt}')
            fire_irq   = bool(self._ctrl & self._CTRL_INT_ENABLE)
            fire_reset = True

        if fire_irq:
            # Pulse the pre-reset warning IRQ (edge-trigger)
            print(f'[WDT] IRQ {self._irq.idx} pulse (pre-reset warning)')
            self._irq.pulse()
            self._tr.emit('IRQ_PULSE', irq_idx=self._irq.idx)

        if fire_reset and self._reset_callback is not None:
            self._tr.emit('TIMEOUT', timeout_cnt=cnt)
            self._reset_callback()

