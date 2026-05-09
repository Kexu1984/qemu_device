"""
coverage_device — MMIO sink for firmware coverage data.

The firmware streams LLVM coverage/profile sections into this device through
ordinary mmio-sockdev writes. The Python model writes a small KXCV container
and a JSON summary that CI can inspect before a full LLVM .profraw packer
exists.
"""

from __future__ import annotations

import json
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Optional

from device_model.mmio_base import MMIODevice
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class CoverageDevice(MMIODevice):
    _ID_VALUE = 0x31564F43  # 'COV1'
    _VERSION = 0x00010000

    _REG_ID = 0x00
    _REG_VERSION = 0x04
    _REG_CTRL = 0x08
    _REG_STATUS = 0x0C
    _REG_ERROR = 0x10
    _REG_REGION = 0x14
    _REG_SIZE = 0x18
    _REG_WRITTEN = 0x1C
    _REG_DATA = 0x20
    _REG_TOTAL_BYTES = 0x24
    _REG_CHUNKS = 0x28
    _REG_NONZERO_WORDS = 0x2C
    _REG_REGION_COUNT = 0x30
    _REG_CRC32 = 0x34

    _CTRL_RESET = 0x01
    _CTRL_FLUSH = 0x02

    _STATUS_ACTIVE = 0x01
    _STATUS_COMPLETE = 0x02
    _STATUS_ERROR = 0x04

    _ERR_NONE = 0
    _ERR_BAD_REGION = 1
    _ERR_OVERFLOW = 2
    _ERR_IO = 3

    _REGION_NAMES = {
        1: 'prf_data',
        2: 'prf_cnts',
        3: 'prf_names',
        4: 'covmap',
    }

    def __init__(
        self,
        output_file: str = 'build/coverage/firmware.kxcv',
        summary_file: str = 'build/coverage/firmware_coverage_summary.json',
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._output_file = Path(output_file)
        self._summary_file = Path(summary_file)
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
        self._reset_capture()

    @property
    def name(self) -> str:
        return 'coverage'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        with self._lock:
            value = 0
            if offset == self._REG_ID:
                value = self._ID_VALUE
            elif offset == self._REG_VERSION:
                value = self._VERSION
            elif offset == self._REG_STATUS:
                value = self._status
            elif offset == self._REG_ERROR:
                value = self._error
            elif offset == self._REG_REGION:
                value = self._active_region
            elif offset == self._REG_SIZE:
                value = self._expected_size
            elif offset == self._REG_WRITTEN:
                value = self._active_written
            elif offset == self._REG_TOTAL_BYTES:
                value = self._total_bytes
            elif offset == self._REG_CHUNKS:
                value = self._chunks
            elif offset == self._REG_NONZERO_WORDS:
                value = self._count_nonzero_u64(bytes(self._regions[2]))
            elif offset == self._REG_REGION_COUNT:
                value = sum(1 for chunk in self._regions.values() if chunk)
            elif offset == self._REG_CRC32:
                value = self._crc32
            return struct.pack('<I', value & 0xFFFFFFFF)[:size]

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        value = int.from_bytes(data[:4].ljust(4, b'\x00'), 'little')
        with self._lock:
            if offset == self._REG_CTRL:
                if value & self._CTRL_RESET:
                    self._reset_capture()
                    self._tr.emit('RESET_CAPTURE')
                if value & self._CTRL_FLUSH:
                    self._flush_locked()
                return 0

            if offset == self._REG_REGION:
                self._select_region_locked(value)
                return 0

            if offset == self._REG_SIZE:
                self._begin_region_locked(value)
                return 0

            if offset == self._REG_DATA:
                self._append_data_locked(data[:size])
                return 0
        return 0

    def on_reset(self) -> None:
        with self._lock:
            self._reset_capture()
        self._tr.emit('RESET')

    def _reset_capture(self) -> None:
        self._status = 0
        self._error = self._ERR_NONE
        self._active_region = 0
        self._expected_size = 0
        self._active_written = 0
        self._regions: dict[int, bytearray] = {
            region_id: bytearray() for region_id in self._REGION_NAMES
        }
        self._region_expected: dict[int, int] = {
            region_id: 0 for region_id in self._REGION_NAMES
        }
        self._total_bytes = 0
        self._chunks = 0
        self._crc32 = 0

    def _set_error_locked(self, error: int) -> None:
        self._error = error
        self._status |= self._STATUS_ERROR

    def _select_region_locked(self, region_id: int) -> None:
        if region_id not in self._REGION_NAMES:
            self._active_region = 0
            self._set_error_locked(self._ERR_BAD_REGION)
            return
        self._active_region = region_id
        self._expected_size = self._region_expected[region_id]
        self._active_written = len(self._regions[region_id])
        self._status = (self._status | self._STATUS_ACTIVE) & ~self._STATUS_COMPLETE

    def _begin_region_locked(self, expected_size: int) -> None:
        if self._active_region not in self._REGION_NAMES:
            self._set_error_locked(self._ERR_BAD_REGION)
            return
        self._expected_size = expected_size
        self._active_written = 0
        self._regions[self._active_region] = bytearray()
        self._region_expected[self._active_region] = expected_size
        self._status = (self._status | self._STATUS_ACTIVE) & ~self._STATUS_COMPLETE
        self._tr.emit('BEGIN_REGION', region=self._REGION_NAMES[self._active_region], size=expected_size)

    def _append_data_locked(self, payload: bytes) -> None:
        if self._active_region not in self._REGION_NAMES:
            self._set_error_locked(self._ERR_BAD_REGION)
            return
        region = self._regions[self._active_region]
        expected = self._region_expected[self._active_region]
        if expected and len(region) + len(payload) > expected:
            self._set_error_locked(self._ERR_OVERFLOW)
            payload = payload[:max(0, expected - len(region))]
        if not payload:
            return
        region.extend(payload)
        self._active_written = len(region)
        self._total_bytes += len(payload)
        self._chunks += 1
        self._crc32 = zlib.crc32(payload, self._crc32) & 0xFFFFFFFF
        if expected and len(region) == expected:
            self._status &= ~self._STATUS_ACTIVE
        self._tr.emit('DATA', region=self._REGION_NAMES[self._active_region], size=len(payload))

    @staticmethod
    def _count_nonzero_u64(payload: bytes) -> int:
        count = 0
        for idx in range(0, len(payload) - (len(payload) % 8), 8):
            if int.from_bytes(payload[idx:idx + 8], 'little') != 0:
                count += 1
        return count

    def _flush_locked(self) -> None:
        try:
            self._output_file.parent.mkdir(parents=True, exist_ok=True)
            self._summary_file.parent.mkdir(parents=True, exist_ok=True)
            with self._output_file.open('wb') as fh:
                fh.write(b'KXCV')
                fh.write(struct.pack('<II', 1, len(self._REGION_NAMES)))
                for region_id, name in self._REGION_NAMES.items():
                    payload = bytes(self._regions[region_id])
                    name_bytes = name.encode('ascii')
                    fh.write(struct.pack('<III', region_id, len(name_bytes), len(payload)))
                    fh.write(name_bytes)
                    fh.write(payload)

            self._status = (self._status | self._STATUS_COMPLETE) & ~self._STATUS_ACTIVE
            summary = self._make_summary_locked()
            self._summary_file.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
            print(f'[COV] wrote {self._output_file} ({self._total_bytes} bytes), summary {self._summary_file}')
            self._tr.emit('FLUSH', total_bytes=self._total_bytes, output=str(self._output_file))
        except OSError as exc:
            print(f'[COV] flush error: {exc}')
            self._set_error_locked(self._ERR_IO)

    def _make_summary_locked(self) -> dict:
        regions = {}
        for region_id, name in self._REGION_NAMES.items():
            payload = bytes(self._regions[region_id])
            expected = self._region_expected[region_id]
            regions[name] = {
                'id': region_id,
                'expected_bytes': expected,
                'captured_bytes': len(payload),
                'complete': expected == len(payload),
                'crc32': f'0x{zlib.crc32(payload) & 0xFFFFFFFF:08X}',
                'nonzero_u64': self._count_nonzero_u64(payload),
            }
        return {
            'format': 'KXCV',
            'version': 1,
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'output_file': str(self._output_file),
            'total_bytes': self._total_bytes,
            'chunks': self._chunks,
            'nonzero_counter_words': self._count_nonzero_u64(bytes(self._regions[2])),
            'crc32': f'0x{self._crc32:08X}',
            'status': self._status,
            'error': self._error,
            'regions': regions,
        }