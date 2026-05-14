from __future__ import annotations

from device_model.mmio_base import FabricChannel, recv_exact

from platform_test_utils import make_socketpair, recv_fabric_read, recv_fabric_write, run_peer


REQUIREMENTS = (
    'FAB-001',
    'FAB-007',
    'FAB-010',
    'TR-004',
    'TR-005',
)


def test_fabric_write_chunks_large_payloads_in_address_order() -> None:
    channel_sock, peer_sock = make_socketpair()
    channel = FabricChannel(master_id=0x99)
    channel._max_transfer = 3
    channel._on_connect(channel_sock)
    frames: list[tuple[int, int, int, bytes]] = []

    def peer(sock):
        for _frame_index in range(3):
            frames.append(recv_fabric_write(sock))
            sock.sendall(b'\x00')

    thread = run_peer(peer, peer_sock)

    assert channel.fabric_write(0x12, 0x2000_0000, b'ABCDEFG') is True
    thread.join(timeout=2.0)

    assert frames == [
        (0x12, 0x2000_0000, 3, b'ABC'),
        (0x12, 0x2000_0003, 3, b'DEF'),
        (0x12, 0x2000_0006, 1, b'G'),
    ]

    channel.stop()
    peer_sock.close()


def test_fabric_read_chunks_large_reads_and_concatenates_responses() -> None:
    channel_sock, peer_sock = make_socketpair()
    channel = FabricChannel(master_id=0x99)
    channel._max_transfer = 2
    channel._on_connect(channel_sock)
    requests: list[tuple[int, int, int]] = []

    def peer(sock):
        for payload in (b'AB', b'CD', b'E'):
            requests.append(recv_fabric_read(sock))
            sock.sendall(b'\x00' + payload)

    thread = run_peer(peer, peer_sock)

    assert channel.fabric_read(0x20, 0x1000_0000, 5) == b'ABCDE'
    thread.join(timeout=2.0)

    assert requests == [
        (0x20, 0x1000_0000, 2),
        (0x20, 0x1000_0002, 2),
        (0x20, 0x1000_0004, 1),
    ]

    channel.stop()
    peer_sock.close()


def test_fabric_write_error_status_stops_transfer() -> None:
    channel_sock, peer_sock = make_socketpair()
    channel = FabricChannel(master_id=0x99)
    channel._max_transfer = 2
    channel._on_connect(channel_sock)

    def peer(sock):
        recv_fabric_write(sock)
        sock.sendall(b'\x01')
        try:
            assert recv_exact(sock, 1) == b''
        except Exception:
            pass

    thread = run_peer(peer, peer_sock)

    assert channel.fabric_write(0x21, 0x3000_0000, b'abcd') is False
    thread.join(timeout=2.0)

    channel.stop()
    peer_sock.close()