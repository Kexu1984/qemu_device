"""
fabric_master_demo — Tick-driven Python fabric master smoke device.

The device has no MMIO slave window. It is a modeled bus master that receives
Python-domain ticks and proves that a Python master can access another device's
registers through the fabric interface.
"""

from __future__ import annotations

from typing import Optional

from device_model.fabric import FabricMasterClient
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer

try:
    from device_model.generated.device_consts import (
        CRC_CTRL_REG,
        CRC_DATA_REG,
        CRC_RESULT_REG,
        SV_TIMER_DMA_ID_REG,
    )
except ModuleNotFoundError:
    CRC_DATA_REG = 0x40008000
    CRC_RESULT_REG = 0x40008004
    CRC_CTRL_REG = 0x40008008
    SV_TIMER_DMA_ID_REG = 0x4000B100


class PythonFabricMasterDemo:
    _EXPECTED_CRC32 = 0xCBF43926
    _EXPECTED_SV_DMA_ID = 0x414D4453
    _SV_NOT_READY_VALUE = 0xDEAD0000
    _SV_RETRY_INTERVAL_NS = 1_000_000
    _MAX_SV_PROBE_ATTEMPTS = 5000
    _PAYLOAD = b'123456789'

    def __init__(
        self,
        *,
        fabric: FabricMasterClient,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._fabric = fabric
        self._crc_done = False
        self._sv_done = False
        self._sv_attempts = 0
        self._next_sv_probe_ns = 0
        self._tr: DeviceTracer = tracer.context('py_fabric_master') if tracer else NULL_DEVICE_TRACER

    def on_tick(self, vtime_ns: int) -> int:
        self._tr.tick(vtime_ns)
        if self._crc_done and self._sv_done:
            return 0
        if not self._crc_done:
            self._crc_done = self._run_crc_probe(vtime_ns)
        if self._crc_done and not self._sv_done and vtime_ns >= self._next_sv_probe_ns:
            self._sv_done = self._run_sv_probe(vtime_ns)
        return 0

    def _run_crc_probe(self, vtime_ns: int) -> bool:
        reset_rsp = self._fabric.write32(CRC_CTRL_REG, 0x1)
        if not reset_rsp.ok:
            self._fail('CRC_RESET_FAIL', vtime_ns, reset_rsp.status.name)
            return False

        for byte in self._PAYLOAD:
            write_rsp = self._fabric.write(CRC_DATA_REG, bytes([byte]))
            if not write_rsp.ok:
                self._fail('CRC_DATA_FAIL', vtime_ns, write_rsp.status.name)
                return False

        result, read_rsp = self._fabric.read32(CRC_RESULT_REG)
        if read_rsp.ok and result == self._EXPECTED_CRC32:
            print('[FABRIC] Python master CRC register access PASSED')
            self._tr.emit(
                'CRC_PROBE_PASS',
                t_virt_ns_override=vtime_ns,
                result=hex(result),
                master_id=hex(self._fabric.master_id),
            )
            return True

        self._fail('CRC_PROBE_FAIL', vtime_ns, read_rsp.status.name, result)
        return False

    def _run_sv_probe(self, vtime_ns: int) -> bool:
        self._sv_attempts += 1
        result, read_rsp = self._fabric.read32(SV_TIMER_DMA_ID_REG)
        if read_rsp.ok and result == self._EXPECTED_SV_DMA_ID:
            print('[FABRIC] Python master SV register access PASSED')
            self._tr.emit(
                'SV_PROBE_PASS',
                t_virt_ns_override=vtime_ns,
                result=hex(result),
                master_id=hex(self._fabric.master_id),
            )
            return True

        can_retry = self._sv_attempts < self._MAX_SV_PROBE_ATTEMPTS
        not_ready = read_rsp.ok and result == self._SV_NOT_READY_VALUE
        if can_retry and (not_ready or not read_rsp.ok):
            self._next_sv_probe_ns = vtime_ns + self._SV_RETRY_INTERVAL_NS
            return False

        self._fail('SV_PROBE_FAIL', vtime_ns, read_rsp.status.name, result)
        return True

    def _fail(self, event: str, vtime_ns: int, status: str, result: Optional[int] = None) -> None:
        print(f'[FABRIC] Python master register access FAILED event={event} status={status}')
        data = {
            'status': status,
            'master_id': hex(self._fabric.master_id),
        }
        if result is not None:
            data['result'] = hex(result)
        self._tr.emit(event, t_virt_ns_override=vtime_ns, **data)
