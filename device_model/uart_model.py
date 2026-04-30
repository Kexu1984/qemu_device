"""
uart_model — Console UART device model.

Register map (offsets from device base address, see spec/uart.yaml):
  0x00  TXDATA  W    Transmit data byte (bits [7:0] → stdout)
  0x04  STATUS  R    bit0 = TXREADY (always 1), bit1 = RXREADY (RX FIFO non-empty)
  0x08  CTRL    R/W  bit0 = ENABLE (default 1), bit1 = RX_IRQ_EN
  0x0C  RXDATA  R    Receive data byte (pops one byte from RX FIFO; 0x00 if empty)

RX behaviour:
  Bytes arriving from any connected terminal client are pushed into a thread-safe
  deque (RX FIFO).  When CTRL.RX_IRQ_EN is set, an IRQ is pulsed immediately to
  wake the firmware from WFI.  Firmware can then poll STATUS.RXREADY and read
  RXDATA until the FIFO is empty.

TX IRQ behaviour: one-shot assert irq_delay seconds after the IRQ channel
connects, then deasserted immediately (edge-trigger).  Simulates a TX-empty IRQ.
"""

from __future__ import annotations

import collections
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
    UART console device with TX output and RX input support.

    Offset  Name    Access  Description
    ------  ------  ------  -------------------------------------------
    0x00    TXDATA  W       Write byte to stdout / terminal (bits [7:0])
    0x04    STATUS  R       bit0 = TXREADY (always 1), bit1 = RXREADY
    0x08    CTRL    R/W     bit0 = ENABLE, bit1 = RX_IRQ_EN
    0x0C    RXDATA  R       Pop one byte from RX FIFO (0x00 if empty)
    """

    _TXDATA  = 0x00
    _STATUS  = 0x04
    _CTRL    = 0x08
    _RXDATA  = 0x0C
    _REGSIZE = 0x10

    _CTRL_ENABLE     = 0x1
    _CTRL_RX_IRQ_EN  = 0x2

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

        # RX FIFO — filled by UartChannel when terminal clients send data
        self._rx_fifo: collections.deque[int] = collections.deque()
        self._rx_lock = threading.Lock()

        # Wire UartChannel RX callback to our FIFO
        if uart_channel is not None:
            uart_channel._rx_callback = self._on_rx_data

        if irq_controller is not None:
            threading.Thread(target=self._irq_task, daemon=True).start()

    @property
    def name(self) -> str:
        return 'ConsoleUart'

    # -- RX data path ------------------------------------------------------

    def _on_rx_data(self, data: bytes) -> None:
        """Called from UartChannel._watch_client thread when terminal sends bytes."""
        with self._rx_lock:
            for b in data:
                # CR → LF normalisation for terminal compatibility
                self._rx_fifo.append(0x0A if b == 0x0D else b)
            fifo_len = len(self._rx_fifo)
        self._tr.emit('RX', length=len(data), fifo_depth=fifo_len)
        # If RX_IRQ_EN: pulse IRQ to wake firmware from WFI
        ctrl = self._regs.get32(self._CTRL)
        if ctrl & self._CTRL_RX_IRQ_EN:
            self._irq.pulse()

    # -- MMIODevice interface ----------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        if offset == self._STATUS:
            with self._rx_lock:
                rx_ready = 1 if self._rx_fifo else 0
            status = 0x1 | (rx_ready << 1)   # bit0=TXREADY, bit1=RXREADY
            return status.to_bytes(size, 'little')
        if offset == self._RXDATA:
            with self._rx_lock:
                byte = self._rx_fifo.popleft() if self._rx_fifo else 0
            return byte.to_bytes(size, 'little')
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes) -> int:
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
            return 0
        self._regs.write(offset, size, data)
        return 0

    def on_reset(self) -> None:
        self._regs.reset()
        with self._irq_lock:
            self._irq_fired = False
        with self._rx_lock:
            self._rx_fifo.clear()
        if self._line_buf:
            print(self._line_buf, flush=True)
            self._line_buf = ''
        if self._uart_channel is not None:
            self._uart_channel.send(b'\r\n\x1b[33m--- [UART RESET] ---\x1b[0m\r\n')
        self._tr.emit('RESET')

    # -- TX IRQ injection (daemon thread) ---------------------------------

    def _irq_task(self) -> None:
        """One-shot TX IRQ: fires *irq_delay* seconds after the channel connects."""
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
