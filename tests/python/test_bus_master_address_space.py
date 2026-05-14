from __future__ import annotations

from device_model.mmio_base import BusMasterAddressSpace


REQUIREMENTS = (
    'FAB-002',
    'FAB-004',
    'FAB-007',
)


class RecordingFabric:
    def __init__(self, master_id: int = 0x44) -> None:
        self.master_id = master_id
        self.reads: list[tuple[int, int, int]] = []
        self.writes: list[tuple[int, int, bytes]] = []

    def fabric_read(self, master_id: int, addr: int, length: int) -> bytes:
        self.reads.append((master_id, addr, length))
        return bytes([0xA5]) * length

    def fabric_write(self, master_id: int, addr: int, data: bytes) -> bool:
        self.writes.append((master_id, addr, data))
        return True


class RecordingBus:
    def __init__(self) -> None:
        self.reads: list[tuple[int, int]] = []
        self.writes: list[tuple[int, int, bytes]] = []

    def read(self, addr: int, size: int) -> bytes:
        self.reads.append((addr, size))
        return b'B' * size

    def write(self, addr: int, size: int, data: bytes) -> int:
        self.writes.append((addr, size, data))
        return 0


def test_mmio_region_routes_to_python_bus_and_memory_routes_to_fabric() -> None:
    fabric = RecordingFabric(master_id=0x44)
    bus = RecordingBus()
    address_space = BusMasterAddressSpace(
        fabric_channel=fabric,  # type: ignore[arg-type]
        mmio_bus=bus,
        mmio_regions=[(0x4000_0000, 0x0010_0000)],
    )

    assert address_space.read(0x4000_1000, 4) == b'BBBB'
    assert address_space.write(0x4000_2000, b'abcd') is True
    assert address_space.read(0x2000_0000, 3) == b'\xA5\xA5\xA5'
    assert address_space.write(0x2000_0010, b'xyz') is True

    assert bus.reads == [(0x4000_1000, 4)]
    assert bus.writes == [(0x4000_2000, 4, b'abcd')]
    assert fabric.reads == [(0x44, 0x2000_0000, 3)]
    assert fabric.writes == [(0x44, 0x2000_0010, b'xyz')]


def test_explicit_master_id_overrides_fabric_default() -> None:
    fabric = RecordingFabric(master_id=0x44)
    address_space = BusMasterAddressSpace(
        fabric_channel=fabric,  # type: ignore[arg-type]
        mmio_bus=RecordingBus(),
        mmio_regions=[],
        master_id=0x55,
    )

    assert address_space.read(0x2000_0000, 1) == b'\xA5'
    assert address_space.write(0x2000_0004, b'k') is True
    assert fabric.reads == [(0x55, 0x2000_0000, 1)]
    assert fabric.writes == [(0x55, 0x2000_0004, b'k')]