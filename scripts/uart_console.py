#!/usr/bin/env python3
"""
uart_console.py — Firmware UART terminal client (bidirectional).

Connects to the Python device server's UART terminal channel (port 7904).

* **TX output** (firmware → terminal): bytes written to UART TXDATA register
  flow through the Python device model → UartChannel → this script → stdout.

* **RX input** (terminal → firmware): keystrokes are forwarded immediately to
  the UartChannel, which pushes them into the firmware's RX FIFO and pulses
  the UART RX IRQ.  The firmware's recv_line() echoes each character back.

The local terminal is put into **raw mode** while connected so that individual
keystrokes are sent without waiting for Enter, and without local echo (the
firmware handles echo itself via send_char()).  The original terminal settings
are restored on exit.

Usage
-----
    python3 scripts/uart_console.py [host [port]]

    Default: host=127.0.0.1  port=7904

Start the Python device server first, then QEMU, then this script
(or in any order — the server accepts connections at any time).
"""

from __future__ import annotations

import argparse
import select
import socket
import sys
import termios
import tty


def run(host: str, port: int) -> None:
    """Connect and run a bidirectional raw-mode terminal session."""
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except ConnectionRefusedError:
        print(
            f'[uart_console] Connection refused: {host}:{port}\n'
            'Is the device server running?',
            file=sys.stderr,
        )
        sys.exit(1)
    except TimeoutError:
        print(f'[uart_console] Timed out connecting to {host}:{port}',
              file=sys.stderr)
        sys.exit(1)

    sock.settimeout(None)
    print(f'[uart_console] Connected to UART terminal at {host}:{port}',
          file=sys.stderr)
    print('[uart_console] Firmware output follows — type commands at the # prompt',
          file=sys.stderr)
    print('[uart_console] Press Ctrl-C or Ctrl-] to disconnect',
          file=sys.stderr)
    print('─' * 60, file=sys.stderr)

    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)

    out = sys.stdout.buffer

    try:
        # Raw mode: no echo, no line buffering — every keystroke sent immediately.
        tty.setraw(stdin_fd)

        while True:
            r, _, _ = select.select([sock, sys.stdin.buffer], [], [], 0.2)

            # ── Firmware TX: socket → stdout ──────────────────────────────
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    # Server closed the connection
                    break
                out.write(data)
                out.flush()

            # ── User RX: stdin → socket ───────────────────────────────────
            if sys.stdin.buffer in r:
                ch = sys.stdin.buffer.read(1)
                if not ch:
                    break
                # Ctrl-C (0x03) or Ctrl-] (0x1D) → exit
                if ch in (b'\x03', b'\x1d'):
                    break
                sock.sendall(ch)

    except KeyboardInterrupt:
        pass
    finally:
        # Always restore terminal settings before printing anything
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        sock.close()
        print('\r\n[uart_console] Disconnected.', file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='UART bidirectional terminal — connects to the firmware UART channel.',
    )
    parser.add_argument('host', nargs='?', default='127.0.0.1',
                        help='Device server host (default: 127.0.0.1)')
    parser.add_argument('port', nargs='?', type=int, default=7904,
                        help='UART terminal port (default: 7904)')
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == '__main__':
    main()
