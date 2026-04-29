"""
uart_model — Console UART device model.

Register map (offsets from device base address, see spec/uart.yaml):
  0x00  TXDATA  W    Transmit data byte (bits [7:0] → stdout)
  0x04  STATUS  R    bit0 = TXREADY (always 1)
  0x08  CTRL    R/W  bit0 = ENABLE (default 1)

IRQ behaviour: one-shot assert irq_delay seconds after the IRQ channel
connects, then deasserted 2 s later.  Simulates a TX-empty interrupt.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure the project root is on sys.path so sibling package imports work
# whether this module is imported as a package or run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, RegisterBank, UartChannel  # noqa: E402
from device_model.tracer    import NULL_DEVICE_TRACER, DeviceTracer, Tracer                       # noqa: E402


class ConsoleUartDevice(MMIODevice):
    """
    Simple UART-like console device.

    Offset  Name    Access  Description
    ------  ------  ------  -------------------------------------------
    0x00    TXDATA  W       Write byte to stdout (bits [7:0])
    0x04    STATUS  R       bit0 = TXREADY (always 1)
    0x08    CTRL    R/W     bit0 = ENABLE (default 1)
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
        uart_channel: Optional[UartChannel] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        _init = bytearray(self._REGSIZE)
        _init[self._CTRL] = 0x01           # ENABLE=1 by default
        self._regs         = RegisterBank(self._REGSIZE, bytes(_init))
        self._irq          = IrqLine(irq_controller, irq_idx)
        self._irq_delay    = irq_delay
        self._irq_fired    = False
        self._irq_lock     = threading.Lock()
        self._line_buf     = ''
        self._uart_channel = uart_channel
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

        if irq_controller is not None:
            threading.Thread(target=self._irq_task, daemon=True).start()

    @property
    def name(self) -> str:
        return 'ConsoleUart'

    # -- MMIODevice interface ---------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._STATUS:
            return (1).to_bytes(size, 'little')    # TXREADY always set
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes) -> None:
        if offset == self._TXDATA:
            ch = data[0] & 0xFF
            # ── Terminal channel: forward raw bytes, LF → CRLF ───────────
            if self._uart_channel is not None:
                self._uart_channel.send(b'\r\n' if ch == 0x0A else bytes([ch]))
            # ── Trace ─────────────────────────────────────────────────────
            self._tr.emit('TX', ch=ch,
                          ascii=chr(ch) if 0x20 <= ch < 0x7F else None)
            # ── Stdout: line-buffer for e2e test compatibility ────────────
            if 32 <= ch <= 126:
                self._line_buf += chr(ch)
            elif ch == 0x0A:  # newline — flush accumulated line atomically
                print(self._line_buf, flush=True)
                self._line_buf = ''
            else:
                self._line_buf += f'[{ch:#04x}]'
            return
        self._regs.write(offset, size, data)

    def on_reset(self) -> None:
        self._regs.reset()
        with self._irq_lock:
            self._irq_fired = False
        if self._line_buf:
            print(self._line_buf, flush=True)
            self._line_buf = ''
        if self._uart_channel is not None:
            self._uart_channel.send(b'\r\n\x1b[33m--- [UART RESET] ---\x1b[0m\r\n')
        self._tr.emit('RESET')

    # -- IRQ injection (daemon thread) ------------------------------------

    def _irq_task(self) -> None:
        """One-shot IRQ: fires *irq_delay* seconds after the channel connects."""
        self._irq.wait_connected()
        time.sleep(self._irq_delay)

        with self._irq_lock:
            if self._irq_fired:
                return
            self._irq_fired = True

        self._irq.assert_()
        print(
            f'[IRQ] IRQ {self._irq.idx} asserted  (level=1)'
            ' \u2192 QEMU will raise NVIC IRQ'
        )
        # Deassert immediately: NVIC latches the rising edge as pending; the
        # level must be low by the time the handler returns so the NVIC does
        # not re-fire (Cortex-M re-pends while level is still high).
        self._irq.deassert()
        print(f'[IRQ] IRQ {self._irq.idx} deasserted (level=0)')
        self._tr.emit('IRQ_FIRE', irq_idx=self._irq.idx)
