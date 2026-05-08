"""
fabric — Functional platform fabric for modeled bus-master access.

This module is the Python runtime side of the cross-language fabric direction.
It gives Python master devices one stable absolute-address read/write surface
while the fabric owns decode to local Python MMIO or QEMU system fabric.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from device_model.mmio_base import FabricChannel
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class FabricStatus(IntEnum):
    OK = 0
    DECODE_ERROR = 1
    TRANSPORT_ERROR = 2
    SLAVE_ERROR = 3


@dataclass(frozen=True)
class FabricResponse:
    status: FabricStatus = FabricStatus.OK
    target: str = 'unknown'

    @property
    def ok(self) -> bool:
        return self.status == FabricStatus.OK


@dataclass(frozen=True)
class FabricRegion:
    name: str
    base: int
    size: int
    target: str

    def contains(self, addr: int, length: int = 1) -> bool:
        return self.base <= addr and addr + max(length, 1) <= self.base + self.size


class PlatformFabric:
    """Absolute-address fabric for Python-domain bus masters.

    The first implementation routes local APB/peripheral windows to the
    in-process ``PeripheralBus`` and routes non-MMIO addresses to QEMU through
    ``FabricChannel`` frames. The public interface is intentionally the
    same shape needed by later QEMU and SV fabric clients.
    """

    def __init__(
        self,
        *,
        fabric_channel: FabricChannel,
        local_bus: object,
        local_regions: list[FabricRegion],
        memory_regions: list[FabricRegion],
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._fabric_channel = fabric_channel
        self._bus = local_bus
        self._local_regions = local_regions
        self._memory_regions = memory_regions
        self._tr: DeviceTracer = tracer.context('fabric') if tracer else NULL_DEVICE_TRACER

    def client(self, master_id: int, name: str) -> 'FabricMasterClient':
        return FabricMasterClient(self, master_id, name)

    def read(self, master_id: int, addr: int, size: int) -> tuple[bytes, FabricResponse]:
        local = self._find(self._local_regions, addr, size)
        if local is not None:
            data = self._bus.read(addr, size, master_id)
            self._trace('READ', master_id, addr, size, local.name, FabricStatus.OK)
            return data, FabricResponse(FabricStatus.OK, local.name)

        memory = self._find(self._memory_regions, addr, size)
        if memory is not None:
            data = self._fabric_channel.fabric_read(master_id, addr, size)
            status = FabricStatus.OK if data is not None else FabricStatus.TRANSPORT_ERROR
            self._trace('READ', master_id, addr, size, memory.name, status)
            return (data or (b'\x00' * size)), FabricResponse(status, memory.name)

        self._trace('READ', master_id, addr, size, 'unmapped', FabricStatus.DECODE_ERROR)
        return b'\x00' * size, FabricResponse(FabricStatus.DECODE_ERROR, 'unmapped')

    def write(self, master_id: int, addr: int, data: bytes) -> FabricResponse:
        size = len(data)
        local = self._find(self._local_regions, addr, size)
        if local is not None:
            self._bus.write(addr, size, data, master_id)
            self._trace('WRITE', master_id, addr, size, local.name, FabricStatus.OK)
            return FabricResponse(FabricStatus.OK, local.name)

        memory = self._find(self._memory_regions, addr, size)
        if memory is not None:
            ok = self._fabric_channel.fabric_write(master_id, addr, data)
            status = FabricStatus.OK if ok else FabricStatus.TRANSPORT_ERROR
            self._trace('WRITE', master_id, addr, size, memory.name, status)
            return FabricResponse(status, memory.name)

        self._trace('WRITE', master_id, addr, size, 'unmapped', FabricStatus.DECODE_ERROR)
        return FabricResponse(FabricStatus.DECODE_ERROR, 'unmapped')

    def on_tick(self, vtime_ns: int) -> int:
        self._tr.tick(vtime_ns)
        return 0

    @staticmethod
    def _find(regions: list[FabricRegion], addr: int, size: int) -> Optional[FabricRegion]:
        for region in regions:
            if region.contains(addr, size):
                return region
        return None

    def _trace(
        self,
        op: str,
        master_id: int,
        addr: int,
        size: int,
        target: str,
        status: FabricStatus,
    ) -> None:
        self._tr.emit(
            op,
            master_id=hex(master_id),
            addr=hex(addr),
            size=size,
            target=target,
            status=status.name,
        )


class FabricMasterClient:
    """Small per-master facade passed into Python master devices."""

    def __init__(self, fabric: PlatformFabric, master_id: int, name: str) -> None:
        self._fabric = fabric
        self.master_id = master_id
        self.name = name

    def read(self, addr: int, size: int) -> tuple[bytes, FabricResponse]:
        return self._fabric.read(self.master_id, addr, size)

    def read32(self, addr: int) -> tuple[int, FabricResponse]:
        data, response = self.read(addr, 4)
        return int.from_bytes(data[:4].ljust(4, b'\x00'), 'little'), response

    def write(self, addr: int, data: bytes) -> FabricResponse:
        return self._fabric.write(self.master_id, addr, data)

    def write32(self, addr: int, value: int) -> FabricResponse:
        return self.write(addr, int(value & 0xFFFF_FFFF).to_bytes(4, 'little'))
