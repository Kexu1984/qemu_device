#!/usr/bin/env python3
"""
uart_console.py — Firmware UART terminal client.

Connects to the Python device server's UART terminal channel and prints
firmware character output to the local terminal.  Firmware writes to the
UART TXDATA register → Python device model → UartChannel → this script.

This gives a clean view of firmware output separated from Python device
model debug logs (DMA, IRQ, tick messages etc.).

Usage
-----
    python3 scripts/uart_console.py [host [port]]

    Default: host=127.0.0.1  port=7904

    Or equivalently with netcat:
        nc 127.0.0.1 7904

Start the Python device server first, then QEMU, then this script
(or in any order — the server accepts connections at any time).

ANSI escape codes from the server (e.g. UART RESET marker) are passed
through unchanged so a colour-capable terminal renders them correctly.
Use ``--no-colour`` or pipe to a file to suppress them.
"""

from __future__ import annotations

import argparse
import select
import socket
import sys


def run(host: str, port: int) -> None:
    """Connect and stream bytes until the server closes or Ctrl-C."""
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

    sock.settimeout(None)   # blocking from here on
    print(f'[uart_console] Connected to UART terminal at {host}:{port}',
          file=sys.stderr)
    print('[uart_console] Firmware output follows (Ctrl-C to quit)',
          file=sys.stderr)
    print('─' * 60, file=sys.stderr)

    out = sys.stdout.buffer   # write raw bytes; terminal handles encoding

    try:
        while True:
            # Use select so KeyboardInterrupt is delivered promptly even on
            # blocking sockets (avoids the SIGINT-inside-recv gotcha on Linux).
            ready, _, _ = select.select([sock], [], [], 0.2)
            if not ready:
                continue
            data = sock.recv(4096)
            if not data:
                print('\n[uart_console] Server closed the connection.',
                      file=sys.stderr)
                break
            out.write(data)
            out.flush()
    except KeyboardInterrupt:
        print('\n[uart_console] Disconnected.', file=sys.stderr)
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description='UART terminal — streams firmware UART output from the device server.',
    )
    parser.add_argument('host', nargs='?', default='127.0.0.1',
                        help='Device server host (default: 127.0.0.1)')
    parser.add_argument('port', nargs='?', type=int, default=7904,
                        help='UART terminal port (default: 7904)')
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == '__main__':
    main()
