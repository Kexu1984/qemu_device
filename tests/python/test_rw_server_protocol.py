from __future__ import annotations

import struct
import threading

import pytest

from device_model.mmio_base import recv_exact
from device_model.mmio_device_server import RWServer

from platform_test_utils import FakeBus, make_socketpair


REQUIREMENTS = (
    'TR-001',
    'TR-002',
    'TR-003',
    'TIME-005',
)


def run_rw_server_with_socket(server: RWServer, server_sock) -> threading.Thread:
    server._running = True
    thread = threading.Thread(
        target=server._handle_client,
        args=(server_sock, ('unit-test', 0)),
        daemon=True,
    )
    thread.start()
    return thread


def test_rw_server_read_frame_preserves_master_id_and_computes_absolute_address() -> None:
    client_sock, server_sock = make_socketpair()
    bus = FakeBus(read_data=b'RSP!')
    server = RWServer(port=0, bus=bus, base_addr=0x4000_0000)  # type: ignore[arg-type]
    thread = run_rw_server_with_socket(server, server_sock)

    client_sock.sendall(b'R' + bytes([0x10]) + struct.pack('<I', 0x20) + bytes([3]))

    assert recv_exact(client_sock, 3) == b'RSP'
    assert bus.reads == [(0x4000_0020, 3, 0x10)]

    server._running = False
    client_sock.close()
    thread.join(timeout=2.0)


def test_rw_server_write_frame_returns_des_next_event_value() -> None:
    client_sock, server_sock = make_socketpair()
    bus = FakeBus(next_event_ns=9876)
    server = RWServer(port=0, bus=bus, base_addr=0x4000_0000)  # type: ignore[arg-type]
    thread = run_rw_server_with_socket(server, server_sock)

    client_sock.sendall(
        b'W'
        + bytes([0x11])
        + struct.pack('<I', 0x24)
        + bytes([4])
        + b'abcd'
    )

    assert struct.unpack('<Q', recv_exact(client_sock, 8))[0] == 9876
    assert bus.writes == [(0x4000_0024, 4, b'abcd', 0x11)]

    server._running = False
    client_sock.close()
    thread.join(timeout=2.0)


def test_rw_server_closes_client_on_unknown_opcode_without_bus_access() -> None:
    client_sock, server_sock = make_socketpair()
    bus = FakeBus()
    server = RWServer(port=0, bus=bus, base_addr=0x4000_0000)  # type: ignore[arg-type]
    thread = run_rw_server_with_socket(server, server_sock)

    client_sock.sendall(b'X')
    with pytest.raises(ConnectionError, match='connection closed'):
        recv_exact(client_sock, 1)
    thread.join(timeout=2.0)

    assert bus.reads == []
    assert bus.writes == []

    server._running = False
    client_sock.close()