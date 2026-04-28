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

from device_model.mmio_base import IRQController, MMIODevice  # noqa: E402


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
    ) -> None:
        self._regs = bytearray(self._REGSIZE)
        self._regs[self._CTRL] = 0x01          # ENABLE=1 by default

        self._irq_ctrl  = irq_controller
        self._irq_idx   = irq_idx
        self._irq_delay = irq_delay
        self._irq_fired = False
        self._irq_lock  = threading.Lock()
        self._line_buf  = ''

        if irq_controller is not None:
            threading.Thread(target=self._irq_task, daemon=True).start()

    @property
    def name(self) -> str:
        return 'ConsoleUart'

    # -- MMIODevice interface ---------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._STATUS:
            return (1).to_bytes(size, 'little')    # TXREADY always set
        end = offset + size
        if end <= self._REGSIZE:
            return bytes(self._regs[offset:end])
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        if offset == self._TXDATA:
            ch = data[0] & 0xFF
            if 32 <= ch <= 126:
                self._line_buf += chr(ch)
            elif ch == 0x0A:  # newline — flush accumulated line atomically
                print(self._line_buf, flush=True)
                self._line_buf = ''
            else:
                self._line_buf += f'[{ch:#04x}]'
            return
        end = offset + size
        if end <= self._REGSIZE:
            self._regs[offset:end] = data[:size]

    def on_reset(self) -> None:
        self._regs[:] = bytearray(self._REGSIZE)
        self._regs[self._CTRL] = 0x01
        with self._irq_lock:
            self._irq_fired = False
        if self._line_buf:
            print(self._line_buf, flush=True)
            self._line_buf = ''

    # -- IRQ injection (daemon thread) ------------------------------------

    def _irq_task(self) -> None:
        """One-shot IRQ: fires *irq_delay* seconds after the channel connects."""
        ctrl = self._irq_ctrl
        assert ctrl is not None

        ctrl.wait_connected()
        time.sleep(self._irq_delay)

        with self._irq_lock:
            if self._irq_fired:
                return
            self._irq_fired = True

        ctrl.set_irq(self._irq_idx, 1)
        print(
            f'[IRQ] IRQ {self._irq_idx} asserted  (level=1)'
            ' \u2192 QEMU will raise NVIC IRQ'
        )
        # Deassert immediately: NVIC latches the rising edge as pending; the
        # level must be low by the time the handler returns so the NVIC does
        # not re-fire (Cortex-M re-pends while level is still high).
        ctrl.set_irq(self._irq_idx, 0)
        print(f'[IRQ] IRQ {self._irq_idx} deasserted (level=0)')
