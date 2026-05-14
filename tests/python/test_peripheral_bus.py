from __future__ import annotations

import pytest

from device_model.mmio_device_server import PeripheralBus

from platform_test_utils import FakeDevice, TickObserver, assert_requirements


REQUIREMENTS = (
    'FAB-002',
    'TIME-004',
    'TR-001',
)


def test_requirement_ids_are_declared() -> None:
    assert_requirements(REQUIREMENTS)


def test_peripheral_bus_decodes_absolute_address_to_device_offset() -> None:
    bus = PeripheralBus()
    device = FakeDevice(read_data=b'ABCD', next_event_ns=1234)

    bus.register(0x4000_0000, 0x1000, device)

    assert bus.read(0x4000_0010, 2, master_id=0x10) == b'AB'
    assert bus.write(0x4000_0020, 4, b'WXYZ', master_id=0x11) == 1234

    assert device.reads == [(0x10, 2, 0x10)]
    assert device.writes == [(0x20, 4, b'WXYZ', 0x11)]


def test_peripheral_bus_rejects_overlapping_ranges() -> None:
    bus = PeripheralBus()
    bus.register(0x4000_0000, 0x1000, FakeDevice(name='first'))

    with pytest.raises(ValueError, match='overlaps'):
        bus.register(0x4000_0800, 0x1000, FakeDevice(name='second'))


def test_unmapped_read_returns_zero_bytes_and_write_has_no_event() -> None:
    bus = PeripheralBus()

    assert bus.read(0x5000_0000, 4, master_id=0x22) == b'\x00\x00\x00\x00'
    assert bus.write(0x5000_0000, 4, b'abcd', master_id=0x22) == 0


def test_tick_all_dispatches_same_virtual_timestamp_to_devices_and_observers() -> None:
    bus = PeripheralBus()
    first = FakeDevice(name='first')
    second = FakeDevice(name='second')
    observer = TickObserver()

    bus.register(0x4000_0000, 0x1000, first)
    bus.register(0x4000_1000, 0x1000, second)
    bus.add_tick_observer(observer)

    assert bus.tick_all(987_654_321) == 0
    assert first.ticks == [987_654_321]
    assert second.ticks == [987_654_321]
    assert observer.ticks == [987_654_321]