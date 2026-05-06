"""
uart_model — UART device model: channel server and register model.

Provides
--------
UartChannel
    TCP server that broadcasts the firmware UART character stream to external
    terminal clients (nc / uart_console.py) and delivers their keystrokes back
    to the firmware RX FIFO.  Owned by ``ConsoleUartDevice``.

ConsoleUartDevice
    MMIO register model for the KX6625 console UART.  Translates register
    reads/writes into terminal I/O through ``UartChannel`` and asserts a
    TX-ready IRQ a configurable number of seconds after the firmware enters
    the UART IRQ demo wait.

Register map (offsets from device base, see spec/uart.yaml):
  0x00  TXDATA  W    Transmit data byte (bits [7:0] → stdout)
  0x04  STATUS  R    bit0 = TXREADY (always 1), bit1 = RXREADY (RX FIFO non-empty)
  0x08  CTRL    R/W  bit0 = ENABLE (default 1), bit1 = RX_IRQ_EN
  0x0C  RXDATA  R    Receive data byte (pops one byte from RX FIFO; 0x00 if empty)

RX behaviour:
  Bytes arriving from any connected terminal client are pushed into a thread-safe
  deque (RX FIFO).  When CTRL.RX_IRQ_EN is set, an IRQ is pulsed immediately to
  wake the firmware from WFI.  Firmware can then poll STATUS.RXREADY and read
  RXDATA until the FIFO is empty.

TX IRQ behaviour: assert irq_delay seconds after firmware prints the UART IRQ
wait banner, then deasserted immediately (edge-trigger).  Simulates a TX-empty IRQ.
"""

from __future__ import annotations

import collections
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# Ensure the project root is on sys.path so sibling package imports work
# whether this module is imported as a package or run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, RegisterBank  # noqa: E402
from device_model.tracer    import NULL_DEVICE_TRACER, DeviceTracer, Tracer           # noqa: E402


# ---------------------------------------------------------------------------
# UartChannel — TCP server that exposes the UART byte stream to a terminal
# ---------------------------------------------------------------------------

class UartChannel:
    """
    TCP server that broadcasts the firmware UART character stream to any
    number of external terminal clients (e.g. ``nc`` / ``uart_console.py``)
    and delivers their keystrokes back into the firmware RX FIFO.

    Architecture
    ------------
    ::

        ConsoleUartDevice.write(TXDATA)
             │ raw byte (LF → CRLF for terminal)
             ▼
        UartChannel.send(data)          — in device-model thread
             │  (iterates client list under lock; removes dead sockets)
             ├─► client socket 1  (e.g. nc 127.0.0.1 7904)
             ├─► client socket 2  (e.g. uart_console.py)
             └─► ...

        UartChannel._accept_loop()      — daemon thread
             │  accept new TCP connections on self._port
             └─► spawns _watch_client(conn) daemon thread per client
                  (detects clean close / RST; delivers RX bytes)

    Usage (server side)::

        uart_ch  = UartChannel(port=7904)
        uart_ch.start()          # spawns accept thread; non-blocking
        uart_dev = ConsoleUartDevice(..., uart_channel=uart_ch)

    Client side::

        nc 127.0.0.1 7904
        # or:
        python3 scripts/uart_console.py
    """

    def __init__(self, port: int, host: str = '127.0.0.1',
                 rx_callback: Optional[Callable[[bytes], None]] = None) -> None:
        self._host    = host
        self._port    = port
        self._clients: list[socket.socket] = []
        self._lock    = threading.Lock()
        self._server: Optional[socket.socket] = None
        self._running = False
        self._rx_callback = rx_callback

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Bind and listen; spawn the accept loop in a daemon thread."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.listen(4)
        self._running = True
        print(
            f'[UART] Terminal server on port {self._port}'
            f' — connect: nc {self._host} {self._port}'
        )
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self) -> None:
        """Stop accepting new connections and close the server socket."""
        self._running = False
        if self._server:
            self._server.close()
            self._server = None

    # ── Accept loop ───────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._server.accept()
            except OSError:
                break
            with self._lock:
                self._clients.append(conn)
            print(f'[UART] Terminal client connected from {addr}')
            threading.Thread(
                target=self._watch_client,
                args=(conn, addr),
                daemon=True,
            ).start()

    def _watch_client(self, conn: socket.socket, addr) -> None:
        """Deliver RX bytes and detect client disconnection."""
        try:
            while True:
                data = conn.recv(256)
                if not data:
                    break
                if self._rx_callback is not None:
                    self._rx_callback(data)
        except OSError:
            pass
        finally:
            with self._lock:
                try:
                    self._clients.remove(conn)
                except ValueError:
                    pass
            try:
                conn.close()
            except OSError:
                pass
            print(f'[UART] Terminal client disconnected from {addr}')

    # ── Device-model API ─────────────────────────────────────────────

    def send(self, data: bytes) -> None:
        """Forward *data* to all connected terminal clients.

        Called from the device-model write thread; must be fast.
        Clients that have gone away are pruned from the list silently.
        """
        if not data:
            return
        with self._lock:
            dead: list[socket.socket] = []
            for client in self._clients:
                try:
                    client.sendall(data)
                except OSError:
                    dead.append(client)
            for c in dead:
                try:
                    self._clients.remove(c)
                except ValueError:
                    pass

    @property
    def connected(self) -> bool:
        """True if at least one terminal client is currently connected."""
        with self._lock:
            return bool(self._clients)


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
        name: str = 'uart0',
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        irq_delay: float = 2.0,
        uart_channel: Optional[UartChannel] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._name         = name
        _init = bytearray(self._REGSIZE)
        _init[self._CTRL] = 0x01           # ENABLE=1 by default
        self._regs         = RegisterBank(self._REGSIZE, bytes(_init))
        self._irq          = IrqLine(irq_controller, irq_idx)
        self._irq_delay    = irq_delay
        self._line_buf     = ''
        self._uart_channel = uart_channel
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

        # RX FIFO — filled by UartChannel when terminal clients send data
        self._rx_fifo: collections.deque[int] = collections.deque()
        self._rx_lock = threading.Lock()

        # Wire UartChannel RX callback to our FIFO
        if uart_channel is not None:
            uart_channel._rx_callback = self._on_rx_data

    @property
    def name(self) -> str:
        return self._name

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

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
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

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
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
                line = self._line_buf
                print(line, flush=True)
                if 'Waiting for UART interrupt' in line:
                    self._schedule_tx_ready_irq()
                self._line_buf = ''
            else:
                self._line_buf += f'[{ch:#04x}]'
            return 0
        self._regs.write(offset, size, data)
        return 0

    def on_reset(self) -> None:
        self._regs.reset()
        with self._rx_lock:
            self._rx_fifo.clear()
        if self._line_buf:
            print(self._line_buf, flush=True)
            self._line_buf = ''
        if self._uart_channel is not None:
            self._uart_channel.send(b'\r\n\x1b[33m--- [UART RESET] ---\x1b[0m\r\n')
        self._tr.emit('RESET')

    # -- TX IRQ injection (daemon thread) ---------------------------------

    def _schedule_tx_ready_irq(self) -> None:
        """Schedule a fresh TX-ready IRQ for the current UART demo wait."""
        threading.Thread(target=self._delayed_tx_ready_irq, daemon=True).start()

    def _delayed_tx_ready_irq(self) -> None:
        """Pulse TX-ready IRQ irq_delay seconds after the firmware asks for it."""
        self._irq.wait_connected()
        time.sleep(self._irq_delay)
        self._irq.assert_()
        print(
            f'[IRQ] IRQ {self._irq.idx} asserted  (level=1)'
            ' \u2192 QEMU will raise NVIC IRQ'
        )
        # Deassert immediately: NVIC latches the rising edge as pending.
        self._irq.deassert()
        print(f'[IRQ] IRQ {self._irq.idx} deasserted (level=0)')
        self._tr.emit('IRQ_FIRE', irq_idx=self._irq.idx)
