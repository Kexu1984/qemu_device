"""
crc_device — CRC-32 hardware accelerator model.

Implements the standard CRC-32/ISO-HDLC algorithm, identical to the one
used in Ethernet frames, ZIP archives, and PNG images:

  Polynomial:       0x04C11DB7 (normal), 0xEDB88320 (reflected)
  Initial value:    0xFFFFFFFF
  Input reflected:  yes  (LSb first)
  Output reflected: yes
  Final XOR value:  0xFFFFFFFF

  Test vector: CRC-32("123456789") = 0xCBF43926

Register map  (offsets from device base address, see spec/crc.yaml)
------------------------------------------------------------------------
  0x00  DATA    W   Feed data bytes into the CRC accumulator.
                    Byte write (size=1): feeds 1 byte.
                    Word write (size=4): feeds 4 bytes (little-endian order).
                R   Returns the raw accumulator value (before final XOR).
  0x04  RESULT  R   Final CRC-32 = accumulator ^ 0xFFFFFFFF.
  0x08  CTRL    W   bit0=RESET — write 1 to reinitialise accumulator to
                    0xFFFFFFFF (start a new CRC computation).
                    bit1..31 reserved, write 0.

Typical firmware usage:
  1. mmio_write32(CRC_CTRL_REG, 0x1)           // reset
  2. for each byte: mmio_write8(CRC_DATA_REG, b)  // feed data
  3. result = mmio_read32(CRC_RESULT_REG)       // read CRC
"""

from __future__ import annotations

import struct
import threading
from typing import Optional

from device_model.mmio_base import MMIODevice
from device_model.tracer    import NULL_DEVICE_TRACER, DeviceTracer, Tracer


# ---------------------------------------------------------------------------
# CRC-32/ISO-HDLC lookup table  (built at class definition time)
# ---------------------------------------------------------------------------
def _make_crc32_table() -> list[int]:
    table: list[int] = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
        table.append(crc)
    return table


class CrcDevice(MMIODevice):
    """
    CRC-32 hardware accelerator.

    Thread-safe: any QEMU thread may call read()/write() concurrently;
    all state is protected by a reentrant lock.
    """

    # CRC-32 lookup table (shared across all instances)
    _TABLE: list[int] = _make_crc32_table()

    # CRC initial / reset value
    _INIT: int = 0xFFFFFFFF

    # Register offsets
    _REG_DATA   = 0x00
    _REG_RESULT = 0x04
    _REG_CTRL   = 0x08

    # CTRL bits
    _CTRL_RESET = 0x01

    def __init__(self, tracer: Optional[Tracer] = None) -> None:
        self._lock      = threading.Lock()
        self._acc: int  = self._INIT       # running CRC accumulator
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

    # -- MMIODevice interface -------------------------------------------------

    @property
    def name(self) -> str:
        return "CRC-32"

    def read(self, offset: int, size: int) -> bytes:
        with self._lock:
            if offset == self._REG_DATA:
                # Raw accumulator (before final XOR)
                return struct.pack('<I', self._acc & 0xFFFFFFFF)[:size]
            if offset == self._REG_RESULT:
                # Finalised CRC: accumulator ^ 0xFFFFFFFF
                result = (self._acc ^ 0xFFFFFFFF) & 0xFFFFFFFF
                self._tr.emit('RESULT', crc32=hex(result))
                return struct.pack('<I', result)[:size]
            if offset == self._REG_CTRL:
                return b'\x00' * size
        return b'\x00' * size

    def write(self, offset: int, size: int, data: bytes) -> None:
        with self._lock:
            if offset == self._REG_DATA:
                # Feed every byte in the payload through the CRC engine.
                # Works for both byte writes (size=1) and word writes (size=4).
                for byte in data:
                    self._acc = (
                        (self._acc >> 8)
                        ^ self._TABLE[(self._acc ^ byte) & 0xFF]
                    )
                self._tr.emit('DATA_WRITE', length=size)
                return

            if offset == self._REG_CTRL:
                # Parse control word (little-endian, up to 4 bytes)
                val = int.from_bytes(data[:4].ljust(4, b'\x00'), 'little')
                if val & self._CTRL_RESET:
                    self._acc = self._INIT
                    print('[CRC] accumulator reset to 0xFFFFFFFF')
                    self._tr.emit('RESET')
                return

    def on_reset(self) -> None:
        with self._lock:
            self._acc = self._INIT
        self._tr.emit('RESET')

    # -- Diagnostic helpers ---------------------------------------------------

    @property
    def current_result(self) -> int:
        """Return the current finalised CRC-32 (for test/debug use only)."""
        with self._lock:
            return (self._acc ^ 0xFFFFFFFF) & 0xFFFFFFFF
