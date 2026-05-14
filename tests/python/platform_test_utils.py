from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

from device_model.mmio_base import MMIODevice, recv_exact


class FakeDevice(MMIODevice):
    def __init__(self, name: str = 'fake', read_data: bytes = b'\x00' * 4, next_event_ns: int = 0) -> None:
        self._name = name
        self._read_data = read_data
        self._next_event_ns = next_event_ns
        self.reads: list[tuple[int, int, int]] = []
        self.writes: list[tuple[int, int, bytes, int]] = []
        self.ticks: list[int] = []
        self.reset_count = 0

    @property
    def name(self) -> str:
        return self._name

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        self.reads.append((offset, size, master_id))
        return self._read_data[:size].ljust(size, b'\x00')

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        self.writes.append((offset, size, data, master_id))
        return self._next_event_ns

    def on_tick(self, vtime_ns: int) -> int:
        self.ticks.append(vtime_ns)
        return 0

    def on_reset(self) -> None:
        self.reset_count += 1


class TickObserver:
    def __init__(self) -> None:
        self.ticks: list[int] = []

    def on_tick(self, vtime_ns: int) -> int:
        self.ticks.append(vtime_ns)
        return 0


@dataclass
class FakeBus:
    read_data: bytes = b'\x00' * 4
    next_event_ns: int = 0
    reads: list[tuple[int, int, int]] = field(default_factory=list)
    writes: list[tuple[int, int, bytes, int]] = field(default_factory=list)

    def read(self, addr: int, size: int, master_id: int = 0) -> bytes:
        self.reads.append((addr, size, master_id))
        return self.read_data[:size].ljust(size, b'\x00')

    def write(self, addr: int, size: int, data: bytes, master_id: int = 0) -> int:
        self.writes.append((addr, size, data, master_id))
        return self.next_event_ns


def make_socketpair() -> tuple[socket.socket, socket.socket]:
    left_sock, right_sock = socket.socketpair()
    left_sock.settimeout(2.0)
    right_sock.settimeout(2.0)
    return left_sock, right_sock


def run_peer(handler: Callable[[socket.socket], None], peer_sock: socket.socket) -> threading.Thread:
    thread = threading.Thread(target=handler, args=(peer_sock,), daemon=True)
    thread.start()
    return thread


def recv_fabric_write(sock: socket.socket) -> tuple[int, int, int, bytes]:
    header = recv_exact(sock, 16)
    assert header[0:2] == b'FW'
    master_id = header[2]
    addr, length = struct.unpack('<QI', header[4:16])
    payload = recv_exact(sock, length)
    return master_id, addr, length, payload


def recv_fabric_read(sock: socket.socket) -> tuple[int, int, int]:
    header = recv_exact(sock, 16)
    assert header[0:2] == b'FR'
    master_id = header[2]
    addr, length = struct.unpack('<QI', header[4:16])
    return master_id, addr, length


def assert_requirements(requirements: Iterable[str]) -> None:
    assert all(requirement and '-' in requirement for requirement in requirements)