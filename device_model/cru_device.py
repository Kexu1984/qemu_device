"""
cru_device — CRU (Clock and Reset Unit) Python-side support.

The CRU is implemented as a native QEMU MMIO block in kx6625.c (0x4000F000).
This module provides the Python-side counterparts that integrate with the
device-server infrastructure:

  RstController
    Owns the rst-chardev TCP channel (Python → QEMU).  When the WDT expires,
    WdtDevice calls SystemResetManager.wdt_reset(), which calls
    RstController.send_reset() to write one byte; QEMU receives it and calls
    qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET), rebooting the
    firmware without exiting QEMU.

  CruNotifyServer
    Listens for 'D' | dev_idx | action messages from the QEMU CRU block
    (cru-notify-chardev, port 7917, optional).  Dispatches to
    MMIODevice.on_device_reset() when the CRU holds a device in reset.

  SystemResetManager
    Coordinates a system reset across all Python device models:
    - wdt_reset()           : WDT-timeout path — resets all devices then
                              triggers the QEMU reset via RstController.
    - software_system_reset(): CRU SOFT_SYSRST_REQ path — resets all Python
                              device state; QEMU drives the actual CPU reset.

Usage (wired in soc_top.py):

    rst_ctrl    = RstController()
    sys_reset   = SystemResetManager(bus=bus, rst_ctrl=rst_ctrl)
    wdt_dev     = WdtDevice(..., reset_callback=sys_reset.wdt_reset)
    rst_server  = RstServer(port=7903, rst_controller=rst_ctrl)

    # Optional — only if CRU notify chardev is configured in QEMU:
    cru_notify  = CruNotifyServer(port=7917, device_map={0: uart_dev, ...})
"""
from __future__ import annotations

import socket
import sys
import threading
from typing import Optional

from device_model.mmio_base import recv_exact


# ---------------------------------------------------------------------------
# RstController — Python → QEMU system reset via rst-chardev
# ---------------------------------------------------------------------------

class RstController:
    """
    Triggers a QEMU system reset over the rst-chardev TCP channel.

    Python sends a single byte; QEMU's mmio_sockdev calls
    ``qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)``, which
    reboots the firmware without exiting QEMU (even with ``-no-reboot``).

    QEMU connects as client; Python holds the server-side socket (via
    ``RstServer``) and writes to it to trigger the reset.  Same
    connect/disconnect lifecycle as ``IRQController``.
    """

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._lock      = threading.Lock()
        self._connected = threading.Event()

    # -- called by RstServer ----------------------------------------------

    def _on_connect(self, sock: socket.socket) -> None:
        with self._lock:
            self._sock = sock
        self._connected.set()
        print('[RST] rst-chardev connected')

    def _on_disconnect(self) -> None:
        with self._lock:
            self._sock = None
        self._connected.clear()
        print('[RST] rst-chardev disconnected')

    # -- public API -------------------------------------------------------

    def wait_connected(self, timeout: Optional[float] = None) -> bool:
        """Block until QEMU connects the rst channel (or ``timeout`` expires)."""
        return self._connected.wait(timeout)

    def send_reset(self) -> bool:
        """Send a single byte to trigger a QEMU system reset.

        Returns ``True`` on success, ``False`` if the channel is not open.
        """
        with self._lock:
            if self._sock is None:
                print('[RST] send_reset: no connection — reset not sent',
                      file=sys.stderr)
                return False
            try:
                self._sock.sendall(b'\x52')   # 'R' — any byte triggers reset
                return True
            except OSError as exc:
                print(f'[RST] send_reset error: {exc}', file=sys.stderr)
                return False


# ---------------------------------------------------------------------------
# CruNotifyServer — QEMU CRU → Python device-reset notifications (optional)
# ---------------------------------------------------------------------------

class CruNotifyServer:
    """
    Accepts QEMU's cru-notify-chardev TCP connection (port 7917, optional).

    Receives ``'D'(1B) | dev_idx(1B) | action(1B)`` messages from the QEMU
    CRU block whenever a device's reset state changes (RST_CTRL0 bit written).

    action values:
      0x01 (ACTION_ASSERT)   — device held in reset (RST_CTRL bit cleared by FW)
      0x02 (ACTION_DEASSERT) — device released from reset (RST_CTRL bit set by FW)

    ``ACTION_ASSERT`` dispatches to ``MMIODevice.on_device_reset()``; the
    default implementation delegates to ``on_reset()``, clearing volatile state.

    The chardev is not yet wired in ``e2e_test.sh`` / ``run_interactive.sh``
    (``-chardev socket,id=cru_notify`` not present); this server is ready for
    future use when per-device reset notifications are needed.

    ``device_map`` maps CRU device-index (int) to ``MMIODevice`` instance,
    matching the ``kx6625_cru_devices[]`` table in ``kx6625.c``:
      0=uart  1=dma  2=timer0  3=dma_demo  4=crc  5=wdt  6=sv_timer  7=hsm  8=otp
    """

    _MSG_SIZE       = 3     # 'D'(1B) + dev_idx(1B) + action(1B)
    ACTION_ASSERT   = 0x01  # device held in reset
    ACTION_DEASSERT = 0x02  # device released from reset

    def __init__(self, port: int, device_map: dict) -> None:
        self.port     = port
        self._dev_map = device_map
        self._sock: Optional[socket.socket] = None
        self._running = False

    def _handle_client(self, conn: socket.socket, addr) -> None:
        print(f'[CRU-NOTIFY] QEMU connected from {addr}')
        try:
            while self._running:
                hdr = conn.recv(self._MSG_SIZE)
                if not hdr:
                    break
                if len(hdr) < self._MSG_SIZE:
                    try:
                        hdr += recv_exact(conn, self._MSG_SIZE - len(hdr))
                    except ConnectionError:
                        break
                if hdr[0] != ord('D'):
                    print(f'[CRU-NOTIFY] unexpected byte 0x{hdr[0]:02x}',
                          file=sys.stderr)
                    continue
                dev_idx = hdr[1]
                action  = hdr[2]
                device  = self._dev_map.get(dev_idx)
                if device is None:
                    print(f'[CRU-NOTIFY] unknown dev_idx={dev_idx}', file=sys.stderr)
                    continue
                if action == self.ACTION_ASSERT:
                    print(f'[CRU-NOTIFY] dev[{dev_idx}] {device.name}: held in reset')
                    device.on_device_reset()
                elif action == self.ACTION_DEASSERT:
                    print(f'[CRU-NOTIFY] dev[{dev_idx}] {device.name}: released from reset')
                else:
                    print(f'[CRU-NOTIFY] dev[{dev_idx}] unknown action=0x{action:02x}',
                          file=sys.stderr)
        except (ConnectionError, OSError) as exc:
            if self._running:
                print(f'[CRU-NOTIFY] {addr}: {exc}', file=sys.stderr)
        finally:
            conn.close()
            print(f'[CRU-NOTIFY] QEMU disconnected from {addr}')

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', self.port))
        self._sock.listen(1)
        self._running = True
        print(f'[CRU-NOTIFY] Listening on port {self.port}')
        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True,
                    ).start()
                except OSError:
                    if self._running:
                        print('[CRU-NOTIFY] accept error', file=sys.stderr)
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None


# ---------------------------------------------------------------------------
# SystemResetManager — coordinates reset across all Python device models
# ---------------------------------------------------------------------------

class SystemResetManager:
    """
    Coordinates a system reset across all Python-side device models.

    Two reset paths:

    wdt_reset()
        Called by ``WdtDevice`` on watchdog timeout.
        1. Calls ``on_reset()`` on every ``MMIODevice`` on the bus (clears
           volatile state; retention registers are preserved by each device).
        2. Sends a byte via ``RstController`` → rst-chardev → QEMU
           ``qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)``.
        TCP connections (RW / IRQ / MEM / RST) remain alive across the reset.

    software_system_reset()
        Called when the QEMU CRU processes a ``SOFT_SYSRST_REQ`` write.
        Resets all Python device volatile state; QEMU drives the CPU reset
        itself (no rst-chardev byte needed — QEMU is the initiator).
    """

    def __init__(self, bus: object, rst_ctrl: RstController) -> None:
        self._bus      = bus
        self._rst_ctrl = rst_ctrl

    def wdt_reset(self) -> None:
        """Called by WdtDevice when the watchdog countdown expires."""
        print('[SYS] WDT reset: resetting all device volatile state...')
        for _base, _size, device in self._bus._entries:
            device.on_reset()
        print('[SYS] Sending system-reset request to QEMU...')
        if not self._rst_ctrl.send_reset():
            print('[SYS] WARNING: rst-chardev not connected — '
                  'QEMU reset not sent.',
                  file=sys.stderr)

    def software_system_reset(self) -> None:
        """Called when QEMU's CRU processes a SOFT_SYSRST_REQ write.

        Resets all Python device volatile state; QEMU drives the actual
        CPU reset via the existing rst-chardev channel.
        """
        print('[SYS] Software system reset: resetting all device volatile state...')
        for _base, _size, device in self._bus._entries:
            device.on_reset()
