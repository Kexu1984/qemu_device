"""FLASH controller model with socket-backed DFLASH memory window.

The controller owns a host-side DFLASH backend stored as 64-bit data wordlines
plus 8-bit ECC. The APB register window exposes program/erase/read/verify
commands. A second MMIO registration exposes the DFLASH memory window so CPU and
bus-master reads go through this model instead of a native QEMU byte array.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, RegAccess, RegisterBank
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class DataFlashWindowDevice(MMIODevice):
    def __init__(self, controller: 'FlashControllerDevice') -> None:
        self._controller = controller

    @property
    def name(self) -> str:
        return 'DFLASH_WINDOW'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        return self._controller.read_data_window(offset, size, master_id)

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        self._controller.reject_data_window_write(offset, size, master_id)
        return 0


class FlashControllerDevice(MMIODevice):
    _ID = 0x00
    _VERSION = 0x04
    _CTRL = 0x08
    _STATUS = 0x0C
    _INT_STATUS = 0x10
    _INT_ENABLE = 0x14
    _ERROR = 0x18
    _CMD = 0x1C
    _ADDR = 0x20
    _SRC_ADDR = 0x24
    _DST_ADDR = 0x28
    _LENGTH = 0x2C
    _WORDLINE_SIZE = 0x30
    _FLASH_BASE = 0x34
    _FLASH_SIZE = 0x38
    _ERASED_VALUE = 0x3C
    _UNLOCK0 = 0x40
    _UNLOCK1 = 0x44
    _LOCK = 0x48
    _STATUS_CLEAR = 0x4C
    _TIMING_READ = 0x50
    _TIMING_PROGRAM = 0x54
    _TIMING_ERASE_WORDLINE = 0x58
    _TIMING_ERASE_CHIP = 0x5C
    _LAST_OP_ADDR = 0x60
    _LAST_OP_LENGTH = 0x64
    _LAST_OP_CRC32 = 0x68
    _ECC_STATUS = 0x6C
    _ECC_ADDR = 0x70
    _ECC_SYNDROME = 0x74
    _ECC_CORRECTED_COUNT = 0x78
    _ECC_UNCORRECTABLE_COUNT = 0x7C
    _INJECT_ADDR = 0x80
    _INJECT_MASK_LO = 0x84
    _INJECT_MASK_HI = 0x88
    _INJECT_ECC_MASK = 0x8C
    _INJECT_CTRL = 0x90
    _REGSIZE = 0x94

    _CTRL_START = 0x01
    _CTRL_IRQ_ENABLE = 0x02

    _STATUS_BUSY = 0x0001
    _STATUS_DONE = 0x0002
    _STATUS_ERROR = 0x0004
    _STATUS_IRQ_PENDING = 0x0008
    _STATUS_LOCKED = 0x0010
    _STATUS_PROGRAM_ALLOWED = 0x0020
    _STATUS_ERASE_ALLOWED = 0x0040
    _STATUS_ECC_CORRECTED = 0x0080
    _STATUS_ECC_UNCORRECTABLE = 0x0100
    _STATUS_FILE_LOADED = 0x0200
    _STATUS_FILE_DIRTY = 0x0400

    _INT_DONE = 0x01
    _INT_ERROR = 0x02
    _INT_ECC_CORRECTED = 0x04
    _INT_ECC_UNCORRECTABLE = 0x08

    _ECC_CHECKED = 0x01
    _ECC_CORRECTED = 0x02
    _ECC_UNCORRECTABLE = 0x04

    _ERR_NONE = 0
    _ERR_BUSY = 1
    _ERR_INVALID_CMD = 2
    _ERR_ADDR_RANGE = 3
    _ERR_LENGTH_RANGE = 4
    _ERR_ADDR_ALIGN = 5
    _ERR_LENGTH_ALIGN = 6
    _ERR_LOCKED = 7
    _ERR_UNLOCK_REQUIRED = 8
    _ERR_PROGRAM_ZERO_TO_ONE = 9
    _ERR_MEM_READ = 10
    _ERR_MEM_WRITE = 11
    _ERR_VERIFY = 12
    _ERR_ECC_CORRECTED = 13
    _ERR_ECC_UNCORRECTABLE = 14
    _ERR_FILE_IO = 15
    _ERR_FILE_FORMAT = 16

    _CMD_NONE = 0
    _CMD_READ = 1
    _CMD_PROGRAM = 2
    _CMD_ERASE_WORDLINE = 3
    _CMD_ERASE_CHIP = 4
    _CMD_VERIFY = 5

    _UNLOCK0_VALUE = 0x464C5331
    _UNLOCK_PROGRAM = 0x50524F47
    _UNLOCK_ERASE = 0x45524153

    _DATA_BASE = 0x10000000
    _DATA_SIZE = 0x00080000
    _WORDLINE_BYTES = 8
    _ERASED_ROW = 0xFFFFFFFFFFFFFFFF

    def __init__(
        self,
        address_space: Optional[object],
        storage_file: str = 'build/dflash.hex',
        data_base: int = _DATA_BASE,
        data_size: int = _DATA_SIZE,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._address_space = address_space
        self._storage_file = Path(storage_file)
        self._data_base = data_base
        self._data_size = data_size
        self._row_count = data_size // self._WORDLINE_BYTES
        self._rows = [self._ERASED_ROW for _ in range(self._row_count)]
        self._ecc = [self._compute_ecc(self._ERASED_ROW) for _ in range(self._row_count)]
        self._flags = [0 for _ in range(self._row_count)]
        self._program_allowed = False
        self._erase_allowed = False
        self._file_dirty = False
        self._corrected_count = 0
        self._uncorrectable_count = 0
        self._lock = threading.Lock()
        self._irq = IrqLine(irq_controller, irq_idx)
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
        self.window = DataFlashWindowDevice(self)

        init = bytearray(self._REGSIZE)
        self._put32(init, self._ID, 0x48534C46)
        self._put32(init, self._VERSION, 0x00010000)
        self._put32(init, self._STATUS, self._STATUS_LOCKED)
        self._put32(init, self._WORDLINE_SIZE, self._WORDLINE_BYTES)
        self._put32(init, self._FLASH_BASE, data_base)
        self._put32(init, self._FLASH_SIZE, data_size)
        self._put32(init, self._ERASED_VALUE, 0xFF)
        self._put32(init, self._TIMING_READ, 0x001400C8)
        self._put32(init, self._TIMING_PROGRAM, 0x03E8C350)
        self._put32(init, self._TIMING_ERASE_WORDLINE, 0x001E8480)
        self._put32(init, self._TIMING_ERASE_CHIP, 0x01312D00)
        self._regs = RegisterBank(
            self._REGSIZE,
            bytes(init),
            policies={
                self._ID: RegAccess.READ_ONLY,
                self._VERSION: RegAccess.READ_ONLY,
                self._STATUS: RegAccess.READ_ONLY,
                self._INT_STATUS: RegAccess.W1C,
                self._ERROR: RegAccess.READ_ONLY,
                self._WORDLINE_SIZE: RegAccess.READ_ONLY,
                self._FLASH_BASE: RegAccess.READ_ONLY,
                self._FLASH_SIZE: RegAccess.READ_ONLY,
                self._ERASED_VALUE: RegAccess.READ_ONLY,
                self._UNLOCK0: RegAccess.WRITE_ONLY,
                self._UNLOCK1: RegAccess.WRITE_ONLY,
                self._LOCK: RegAccess.WRITE_ONLY,
                self._STATUS_CLEAR: RegAccess.WRITE_ONLY,
                self._TIMING_READ: RegAccess.READ_ONLY,
                self._TIMING_PROGRAM: RegAccess.READ_ONLY,
                self._TIMING_ERASE_WORDLINE: RegAccess.READ_ONLY,
                self._TIMING_ERASE_CHIP: RegAccess.READ_ONLY,
                self._LAST_OP_ADDR: RegAccess.READ_ONLY,
                self._LAST_OP_LENGTH: RegAccess.READ_ONLY,
                self._LAST_OP_CRC32: RegAccess.READ_ONLY,
                self._ECC_STATUS: RegAccess.READ_ONLY,
                self._ECC_ADDR: RegAccess.READ_ONLY,
                self._ECC_SYNDROME: RegAccess.READ_ONLY,
                self._ECC_CORRECTED_COUNT: RegAccess.READ_ONLY,
                self._ECC_UNCORRECTABLE_COUNT: RegAccess.READ_ONLY,
                self._INJECT_CTRL: RegAccess.WRITE_ONLY,
            },
        )
        self._load_from_file()
        self._refresh_status()

    @property
    def name(self) -> str:
        return 'FLASH_CTRL'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        self._regs.write(offset, size, data)

        if offset <= self._STATUS_CLEAR < offset + size:
            clear = int.from_bytes(data[:size], 'little')
            self._clear_status(clear)

        if offset <= self._UNLOCK0 < offset + size or offset <= self._UNLOCK1 < offset + size:
            self._update_unlock_state()

        if offset <= self._LOCK < offset + size:
            self._program_allowed = False
            self._erase_allowed = False
            self._refresh_status()

        if offset <= self._INJECT_CTRL < offset + size:
            self._apply_injection()

        if offset <= self._CTRL < offset + size:
            ctrl = self._regs.get32(self._CTRL)
            if ctrl & self._CTRL_START:
                self._regs.clear_bits(self._CTRL, self._CTRL_START)
                self._start_execute(ctrl)
        return 0

    def on_reset(self) -> None:
        self._regs.clear_bits(self._STATUS, self._STATUS_BUSY | self._STATUS_IRQ_PENDING)
        self._regs.clear_bits(self._CTRL, self._CTRL_START)
        self._refresh_status()

    def read_data_window(self, offset: int, size: int, master_id: int = 0) -> bytes:
        if offset < 0 or offset + size > self._data_size:
            self._set_error(self._ERR_ADDR_RANGE)
            return b'\x00' * size
        data = bytearray()
        pos = offset
        remaining = size
        with self._lock:
            while remaining > 0:
                row = pos // self._WORDLINE_BYTES
                row_off = pos % self._WORDLINE_BYTES
                take = min(remaining, self._WORDLINE_BYTES - row_off)
                value, ok = self._read_row_checked(row, update_status=True)
                if not ok:
                    value = self._rows[row]
                data.extend(value.to_bytes(8, 'little')[row_off:row_off + take])
                pos += take
                remaining -= take
        return bytes(data)

    def reject_data_window_write(self, offset: int, size: int, master_id: int = 0) -> None:
        self._set_error(self._ERR_LOCKED)
        self._tr.emit('DFLASH_WRITE_REJECT', offset=offset, size=size, master_id=master_id)

    def _start_execute(self, ctrl: int) -> None:
        if self._regs.get32(self._STATUS) & self._STATUS_BUSY:
            self._finish_error(self._ERR_BUSY, ctrl)
            return

        self._regs.set_bits(self._STATUS, self._STATUS_BUSY)
        self._regs.clear_bits(self._STATUS, self._STATUS_DONE | self._STATUS_ERROR)
        self._regs.set32(self._ERROR, self._ERR_NONE)
        worker = threading.Thread(target=self._execute, args=(ctrl,), daemon=True)
        worker.start()

    def _execute(self, ctrl: int) -> None:
        cmd = self._regs.get32(self._CMD)
        addr = self._regs.get32(self._ADDR)
        length = self._regs.get32(self._LENGTH)
        ok = False
        err = self._ERR_NONE

        try:
            if cmd == self._CMD_READ:
                ok, err = self._cmd_read(addr, length)
            elif cmd == self._CMD_PROGRAM:
                ok, err = self._cmd_program(addr, length)
            elif cmd == self._CMD_ERASE_WORDLINE:
                ok, err = self._cmd_erase_wordline(addr)
            elif cmd == self._CMD_ERASE_CHIP:
                ok, err = self._cmd_erase_chip()
            elif cmd == self._CMD_VERIFY:
                ok, err = self._cmd_verify(addr, length)
            else:
                err = self._ERR_INVALID_CMD
        except OSError:
            ok = False
            err = self._ERR_FILE_IO
        except Exception as exc:
            print(f'[FLASH] command error: {exc}', file=sys.stderr)
            ok = False
            err = self._ERR_FILE_IO

        self._regs.clear_bits(self._STATUS, self._STATUS_BUSY)
        if ok:
            self._regs.set_bits(self._STATUS, self._STATUS_DONE)
            self._regs.set32(self._ERROR, self._ERR_NONE)
            self._raise_int(self._INT_DONE, ctrl)
        else:
            self._regs.set_bits(self._STATUS, self._STATUS_DONE | self._STATUS_ERROR)
            self._regs.set32(self._ERROR, err)
            self._raise_int(self._INT_ERROR, ctrl)
        self._refresh_status()

    def _cmd_read(self, addr: int, length: int) -> tuple[bool, int]:
        if self._address_space is None:
            return False, self._ERR_MEM_WRITE
        if length == 0:
            return False, self._ERR_LENGTH_RANGE
        if not self._range_ok(addr, length):
            return False, self._ERR_ADDR_RANGE
        dst = self._regs.get32(self._DST_ADDR)
        data = self.read_data_window(addr, length)
        if not self._address_space.write(dst, data):
            return False, self._ERR_MEM_WRITE
        self._record_op(addr, length)
        return True, self._ERR_NONE

    def _cmd_program(self, addr: int, length: int) -> tuple[bool, int]:
        if not self._program_allowed:
            return False, self._ERR_UNLOCK_REQUIRED
        self._program_allowed = False
        if self._address_space is None:
            return False, self._ERR_MEM_READ
        if length == 0:
            return False, self._ERR_LENGTH_RANGE
        if addr % self._WORDLINE_BYTES != 0:
            return False, self._ERR_ADDR_ALIGN
        if length % self._WORDLINE_BYTES != 0:
            return False, self._ERR_LENGTH_ALIGN
        if not self._range_ok(addr, length):
            return False, self._ERR_ADDR_RANGE
        src = self._regs.get32(self._SRC_ADDR)
        payload = self._address_space.read(src, length)
        if payload is None or len(payload) != length:
            return False, self._ERR_MEM_READ

        with self._lock:
            for index in range(0, length, self._WORDLINE_BYTES):
                row = (addr + index) // self._WORDLINE_BYTES
                new_value = int.from_bytes(payload[index:index + 8], 'little')
                old_value = self._rows[row]
                if (old_value & new_value) != new_value:
                    return False, self._ERR_PROGRAM_ZERO_TO_ONE
            for index in range(0, length, self._WORDLINE_BYTES):
                row = (addr + index) // self._WORDLINE_BYTES
                new_value = int.from_bytes(payload[index:index + 8], 'little')
                self._rows[row] = new_value
                self._ecc[row] = self._compute_ecc(new_value)
                self._flags[row] = 0
        self._file_dirty = True
        self._save_to_file()
        self._record_op(addr, length)
        self._tr.emit('PROGRAM', addr=addr, length=length)
        return True, self._ERR_NONE

    def _cmd_erase_wordline(self, addr: int) -> tuple[bool, int]:
        if not self._erase_allowed:
            return False, self._ERR_UNLOCK_REQUIRED
        self._erase_allowed = False
        if not self._range_ok(addr, 1):
            return False, self._ERR_ADDR_RANGE
        row = addr // self._WORDLINE_BYTES
        with self._lock:
            self._rows[row] = self._ERASED_ROW
            self._ecc[row] = self._compute_ecc(self._ERASED_ROW)
            self._flags[row] = 0
        self._file_dirty = True
        self._save_to_file()
        self._record_op(row * self._WORDLINE_BYTES, self._WORDLINE_BYTES)
        self._tr.emit('ERASE_WORDLINE', row=row)
        return True, self._ERR_NONE

    def _cmd_erase_chip(self) -> tuple[bool, int]:
        if not self._erase_allowed:
            return False, self._ERR_UNLOCK_REQUIRED
        self._erase_allowed = False
        erased_ecc = self._compute_ecc(self._ERASED_ROW)
        with self._lock:
            self._rows = [self._ERASED_ROW for _ in range(self._row_count)]
            self._ecc = [erased_ecc for _ in range(self._row_count)]
            self._flags = [0 for _ in range(self._row_count)]
        self._file_dirty = True
        self._save_to_file()
        self._record_op(0, self._data_size)
        self._tr.emit('ERASE_CHIP')
        return True, self._ERR_NONE

    def _cmd_verify(self, addr: int, length: int) -> tuple[bool, int]:
        if length == 0:
            return False, self._ERR_LENGTH_RANGE
        if not self._range_ok(addr, length):
            return False, self._ERR_ADDR_RANGE
        first = addr // self._WORDLINE_BYTES
        last = (addr + length - 1) // self._WORDLINE_BYTES
        ok = True
        with self._lock:
            for row in range(first, last + 1):
                _value, row_ok = self._read_row_checked(row, update_status=True)
                ok = ok and row_ok
        self._record_op(addr, length)
        return (ok, self._ERR_NONE if ok else self._ERR_VERIFY)

    def _range_ok(self, addr: int, length: int) -> bool:
        return addr < self._data_size and length <= self._data_size and addr + length <= self._data_size

    def _record_op(self, addr: int, length: int) -> None:
        self._regs.set32(self._LAST_OP_ADDR, addr)
        self._regs.set32(self._LAST_OP_LENGTH, length)

    def _update_unlock_state(self) -> None:
        unlock0 = self._regs.get32(self._UNLOCK0)
        unlock1 = self._regs.get32(self._UNLOCK1)
        if unlock0 == self._UNLOCK0_VALUE and unlock1 == self._UNLOCK_PROGRAM:
            self._program_allowed = True
            self._erase_allowed = False
        elif unlock0 == self._UNLOCK0_VALUE and unlock1 == self._UNLOCK_ERASE:
            self._erase_allowed = True
            self._program_allowed = False
        self._refresh_status()

    def _clear_status(self, clear: int) -> None:
        self._regs.clear_bits(
            self._STATUS,
            clear & (self._STATUS_DONE | self._STATUS_ERROR | self._STATUS_IRQ_PENDING |
                     self._STATUS_ECC_CORRECTED | self._STATUS_ECC_UNCORRECTABLE),
        )
        self._regs.write(self._INT_STATUS, 4, (clear & 0x0F).to_bytes(4, 'little'))
        if clear & self._STATUS_ERROR:
            self._regs.set32(self._ERROR, self._ERR_NONE)

    def _refresh_status(self) -> None:
        status = self._regs.get32(self._STATUS)
        status &= ~(self._STATUS_LOCKED | self._STATUS_PROGRAM_ALLOWED |
                    self._STATUS_ERASE_ALLOWED | self._STATUS_FILE_LOADED |
                    self._STATUS_FILE_DIRTY)
        if self._program_allowed:
            status |= self._STATUS_PROGRAM_ALLOWED
        if self._erase_allowed:
            status |= self._STATUS_ERASE_ALLOWED
        if not self._program_allowed and not self._erase_allowed:
            status |= self._STATUS_LOCKED
        if self._storage_file.exists():
            status |= self._STATUS_FILE_LOADED
        if self._file_dirty:
            status |= self._STATUS_FILE_DIRTY
        self._regs.set32(self._STATUS, status)

    def _set_error(self, err: int) -> None:
        self._regs.set_bits(self._STATUS, self._STATUS_ERROR)
        self._regs.set32(self._ERROR, err)
        self._refresh_status()

    def _finish_error(self, err: int, ctrl: int) -> None:
        self._regs.clear_bits(self._STATUS, self._STATUS_BUSY)
        self._regs.set_bits(self._STATUS, self._STATUS_DONE | self._STATUS_ERROR)
        self._regs.set32(self._ERROR, err)
        self._raise_int(self._INT_ERROR, ctrl)
        self._refresh_status()

    def _raise_int(self, bits: int, ctrl: int = 0) -> None:
        self._regs.set_bits(self._INT_STATUS, bits)
        enabled = self._regs.get32(self._INT_ENABLE)
        if (ctrl & self._CTRL_IRQ_ENABLE) or (enabled & bits):
            self._regs.set_bits(self._STATUS, self._STATUS_IRQ_PENDING)
            self._irq.pulse()

    def _read_row_checked(self, row: int, update_status: bool) -> tuple[int, bool]:
        value = self._rows[row]
        stored_ecc = self._ecc[row]
        expected = self._compute_ecc(value)
        syndrome = (stored_ecc ^ expected) & 0x7F
        overall = (self._popcount(value) + self._popcount(stored_ecc & 0x7F) +
               ((stored_ecc >> 7) & 0x1)) & 0x1
        corrected = False
        uncorrectable = False
        corrected_value = value

        if syndrome == 0 and overall == 0:
            pass
        elif syndrome != 0 and overall == 1 and syndrome <= 64:
            corrected_value = value ^ (1 << (syndrome - 1))
            corrected = True
        elif syndrome == 0 and overall == 1:
            corrected = True
        else:
            uncorrectable = True

        if update_status:
            ecc_status = self._ECC_CHECKED | ((syndrome & 0xFF) << 8)
            if corrected:
                ecc_status |= self._ECC_CORRECTED
                self._corrected_count += 1
                self._regs.set_bits(self._STATUS, self._STATUS_ECC_CORRECTED)
                self._regs.set_bits(self._INT_STATUS, self._INT_ECC_CORRECTED)
                self._raise_int(self._INT_ECC_CORRECTED)
            if uncorrectable:
                ecc_status |= self._ECC_UNCORRECTABLE
                self._uncorrectable_count += 1
                self._regs.set_bits(self._STATUS, self._STATUS_ECC_UNCORRECTABLE | self._STATUS_ERROR)
                self._regs.set32(self._ERROR, self._ERR_ECC_UNCORRECTABLE)
                self._regs.set_bits(self._INT_STATUS, self._INT_ECC_UNCORRECTABLE)
                self._raise_int(self._INT_ECC_UNCORRECTABLE)
            self._regs.set32(self._ECC_STATUS, ecc_status)
            self._regs.set32(self._ECC_ADDR, row * self._WORDLINE_BYTES)
            self._regs.set32(self._ECC_SYNDROME, syndrome)
            self._regs.set32(self._ECC_CORRECTED_COUNT, self._corrected_count)
            self._regs.set32(self._ECC_UNCORRECTABLE_COUNT, self._uncorrectable_count)
            self._refresh_status()

        return corrected_value, not uncorrectable

    def _apply_injection(self) -> None:
        ctrl = self._regs.get32(self._INJECT_CTRL)
        if not (ctrl & 0x1):
            return
        addr = self._regs.get32(self._INJECT_ADDR)
        if not self._range_ok(addr, 1):
            self._set_error(self._ERR_ADDR_RANGE)
            return
        row = addr // self._WORDLINE_BYTES
        mask = self._regs.get32(self._INJECT_MASK_LO) | (self._regs.get32(self._INJECT_MASK_HI) << 32)
        ecc_mask = self._regs.get32(self._INJECT_ECC_MASK) & 0xFF
        with self._lock:
            self._rows[row] ^= mask
            self._ecc[row] ^= ecc_mask
        if ctrl & 0x2:
            self._regs.set32(self._INJECT_MASK_LO, 0)
            self._regs.set32(self._INJECT_MASK_HI, 0)
            self._regs.set32(self._INJECT_ECC_MASK, 0)
        self._file_dirty = True
        self._save_to_file()
        self._tr.emit('INJECT', row=row, data_mask=mask, ecc_mask=ecc_mask)

    @classmethod
    def _compute_ecc(cls, value: int) -> int:
        ecc = 0
        for bit_index, parity_pos in enumerate((1, 2, 4, 8, 16, 32, 64)):
            parity = 0
            for data_pos in range(1, 65):
                if data_pos & parity_pos:
                    parity ^= (value >> (data_pos - 1)) & 1
            ecc |= (parity & 1) << bit_index
        overall = (cls._popcount(value) + cls._popcount(ecc & 0x7F)) & 1
        ecc |= overall << 7
        return ecc & 0xFF

    @staticmethod
    def _popcount(value: int) -> int:
        return bin(value & 0xFFFFFFFFFFFFFFFF).count('1')

    @staticmethod
    def _put32(buf: bytearray, off: int, val: int) -> None:
        buf[off:off + 4] = (val & 0xFFFFFFFF).to_bytes(4, 'little')

    def _load_from_file(self) -> None:
        if not self._storage_file.exists():
            return
        try:
            with self._storage_file.open('r', encoding='utf-8') as fh:
                for line_no, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue
                    parts = stripped.split()
                    if len(parts) < 3:
                        raise ValueError(f'line {line_no}: expected row data ecc [flags]')
                    row = int(parts[0], 16)
                    if row < 0 or row >= self._row_count:
                        raise ValueError(f'line {line_no}: row out of range')
                    self._rows[row] = int(parts[1], 16) & 0xFFFFFFFFFFFFFFFF
                    self._ecc[row] = int(parts[2], 16) & 0xFF
                    self._flags[row] = int(parts[3], 16) if len(parts) > 3 else 0
            self._file_dirty = False
            self._tr.emit('LOAD', file=str(self._storage_file))
        except (OSError, ValueError) as exc:
            print(f'[FLASH] load error: {exc}')
            self._set_error(self._ERR_FILE_FORMAT)

    def _save_to_file(self) -> None:
        try:
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            with self._storage_file.open('w', encoding='utf-8') as fh:
                fh.write('# KX6625 DFLASH v1: row_index data64_hex ecc_hex flags_hex\n')
                for row, value in enumerate(self._rows):
                    fh.write(f'{row:08X} {value:016X} {self._ecc[row]:02X} {self._flags[row]:08X}\n')
            self._file_dirty = False
            self._refresh_status()
        except OSError as exc:
            print(f'[FLASH] save error: {exc}')
            self._set_error(self._ERR_FILE_IO)
