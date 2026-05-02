"""
otp_model - one-time-programmable storage controller model.

The OTP controller persists rows in a host-side HEX text file.  Each row is a
32-bit data word plus an 8-bit deterministic SECDED-style ECC byte.  Firmware
can program rows through MMIO, but only 1->0 bit transitions are allowed and a
program unlock sequence is required.  HSM key rows are CPU read-protected and
are exposed to the HSM only through the direct read_key() provider API.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from device_model.mmio_base import IRQController, IrqLine, MMIODevice, RegAccess, RegisterBank
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class OtpControllerDevice(MMIODevice):
    _ID = 0x00
    _VERSION = 0x04
    _CTRL = 0x08
    _STATUS = 0x0C
    _INT_STATUS = 0x10
    _INT_ENABLE = 0x14
    _ERROR = 0x18
    _STATUS_CLEAR = 0x1C
    _ADDR = 0x20
    _WDATA = 0x24
    _RDATA = 0x28
    _ECC_RDATA = 0x2C
    _UNLOCK0 = 0x30
    _UNLOCK1 = 0x34
    _LOCK_CTRL = 0x38
    _LOCK_STATUS = 0x3C
    _ROW_COUNT = 0x40
    _ROW_BITS = 0x44
    _ECC_STATUS = 0x48
    _FILE_STATUS = 0x4C
    _LIFECYCLE_WORD0 = 0x100
    _CUSTOMER_WORD0 = 0x120
    _REGSIZE = 0x130

    _CTRL_START = 0x01
    _CTRL_READ = 0x02
    _CTRL_PROGRAM = 0x04
    _CTRL_RELOAD = 0x08
    _CTRL_SAVE = 0x10
    _CTRL_IRQ_ENABLE = 0x20

    _STATUS_BUSY = 0x0001
    _STATUS_DONE = 0x0002
    _STATUS_ERROR = 0x0004
    _STATUS_IRQ_PENDING = 0x0008
    _STATUS_UNLOCKED = 0x0010
    _STATUS_FILE_LOADED = 0x0020
    _STATUS_FILE_DIRTY = 0x0040
    _STATUS_ECC_CORRECTED = 0x0080
    _STATUS_ECC_UNCORRECTABLE = 0x0100
    _STATUS_LOCKED_REGION = 0x0200
    _STATUS_SHADOW_VALID = 0x0400
    _STATUS_READ_PROTECTED = 0x0800

    _INT_DONE = 0x01
    _INT_ERROR = 0x02
    _INT_ECC_CORRECTED = 0x04
    _INT_ECC_UNCORRECTABLE = 0x08

    _FILE_EXISTS = 0x01
    _FILE_LOADED = 0x02
    _FILE_DIRTY = 0x04
    _FILE_STRICT = 0x08
    _FILE_FORMAT_ERROR = 0x10

    _ERR_NONE = 0
    _ERR_BAD_COMMAND = 1
    _ERR_ADDR_RANGE = 2
    _ERR_ZERO_TO_ONE = 3
    _ERR_LOCKED = 4
    _ERR_UNLOCK_REQUIRED = 5
    _ERR_FILE_IO = 6
    _ERR_FILE_FORMAT = 7
    _ERR_ECC_CORRECTED = 8
    _ERR_ECC_UNCORRECTABLE = 9
    _ERR_BUSY = 10
    _ERR_READ_PROTECTED = 11

    _UNLOCK0_VALUE = 0x4F545031
    _UNLOCK1_VALUE = 0x50524F47

    _LOCK_HSM_KEYS = 0x1
    _LOCK_LIFECYCLE = 0x2
    _LOCK_CUSTOMER = 0x4
    _LOCK_GP = 0x8

    _KEY_BASE_ROW = 0x0000
    _KEY_SLOTS = 15
    _KEY_ROWS_PER_SLOT = 4
    _KEY_LAST_ROW = _KEY_BASE_ROW + _KEY_SLOTS * _KEY_ROWS_PER_SLOT - 1
    _LIFECYCLE_BASE_ROW = 0x0040
    _CUSTOMER_BASE_ROW = 0x0050
    _GP_BASE_ROW = 0x0060

    def __init__(
        self,
        storage_file: str = 'build/otp.hex',
        row_count: int = 256,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        strict_file: bool = False,
        auto_save_after_program: bool = True,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._storage_file = Path(storage_file)
        self._row_count = row_count
        self._strict_file = strict_file
        self._auto_save = auto_save_after_program
        self._rows = [0xFFFFFFFF for _ in range(row_count)]
        self._ecc = [self._compute_ecc(0xFFFFFFFF) for _ in range(row_count)]
        self._lock_status = 0
        self._corrected_count = 0
        self._uncorrectable_count = 0
        self._last_ecc_row = 0
        self._lock = threading.Lock()
        self._irq = IrqLine(irq_controller, irq_idx)
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER

        init = bytearray(self._REGSIZE)
        self._put32(init, self._ID, 0x3150544F)
        self._put32(init, self._VERSION, 0x00010000)
        self._put32(init, self._WDATA, 0xFFFFFFFF)
        self._put32(init, self._RDATA, 0xFFFFFFFF)
        self._put32(init, self._ROW_COUNT, row_count)
        self._put32(init, self._ROW_BITS, 32)
        self._regs = RegisterBank(
            self._REGSIZE,
            bytes(init),
            policies={
                self._ID: RegAccess.READ_ONLY,
                self._VERSION: RegAccess.READ_ONLY,
                self._STATUS: RegAccess.READ_ONLY,
                self._INT_STATUS: RegAccess.W1C,
                self._ERROR: RegAccess.READ_ONLY,
                self._STATUS_CLEAR: RegAccess.WRITE_ONLY,
                self._RDATA: RegAccess.READ_ONLY,
                self._ECC_RDATA: RegAccess.READ_ONLY,
                self._UNLOCK0: RegAccess.WRITE_ONLY,
                self._UNLOCK1: RegAccess.WRITE_ONLY,
                self._LOCK_STATUS: RegAccess.READ_ONLY,
                self._ROW_COUNT: RegAccess.READ_ONLY,
                self._ROW_BITS: RegAccess.READ_ONLY,
                self._ECC_STATUS: RegAccess.READ_ONLY,
                self._FILE_STATUS: RegAccess.READ_ONLY,
                self._LIFECYCLE_WORD0 + 0x00: RegAccess.READ_ONLY,
                self._LIFECYCLE_WORD0 + 0x04: RegAccess.READ_ONLY,
                self._LIFECYCLE_WORD0 + 0x08: RegAccess.READ_ONLY,
                self._LIFECYCLE_WORD0 + 0x0C: RegAccess.READ_ONLY,
                self._CUSTOMER_WORD0 + 0x00: RegAccess.READ_ONLY,
                self._CUSTOMER_WORD0 + 0x04: RegAccess.READ_ONLY,
                self._CUSTOMER_WORD0 + 0x08: RegAccess.READ_ONLY,
                self._CUSTOMER_WORD0 + 0x0C: RegAccess.READ_ONLY,
            },
        )
        self._load_from_file()
        self._refresh_shadow()
        self._update_file_status()

    @property
    def name(self) -> str:
        return 'OTP'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        self._regs.write(offset, size, data)

        if offset <= self._STATUS_CLEAR < offset + size:
            clear = int.from_bytes(data[:size], 'little')
            self._regs.clear_bits(
                self._STATUS,
                clear & (self._STATUS_ECC_CORRECTED |
                         self._STATUS_ECC_UNCORRECTABLE |
                         self._STATUS_READ_PROTECTED),
            )

        if offset <= self._UNLOCK0 < offset + size:
            if self._regs.get32(self._UNLOCK0) == self._UNLOCK0_VALUE:
                self._refresh_unlocked_status()
        if offset <= self._UNLOCK1 < offset + size:
            if self._regs.get32(self._UNLOCK1) == self._UNLOCK1_VALUE:
                self._refresh_unlocked_status()

        if offset <= self._LOCK_CTRL < offset + size:
            requested = self._regs.get32(self._LOCK_CTRL) & 0xF
            if requested:
                with self._lock:
                    self._lock_status |= requested
                self._regs.set32(self._LOCK_STATUS, self._lock_status)
                self._save_to_file()

        if offset <= self._CTRL < offset + size:
            ctrl = self._regs.get32(self._CTRL)
            if ctrl & self._CTRL_START:
                self._regs.clear_bits(self._CTRL, self._CTRL_START)
                self._execute(ctrl)
        return 0

    def on_reset(self) -> None:
        self._regs.clear_bits(self._STATUS, self._STATUS_BUSY | self._STATUS_IRQ_PENDING)
        self._regs.clear_bits(self._CTRL, self._CTRL_START)
        self._update_file_status()

    def read_key(self, slot_id: int, key_size_bits: int = 128) -> Optional[bytes]:
        if key_size_bits != 128 or slot_id < 0 or slot_id >= self._KEY_SLOTS:
            return None
        base = self._KEY_BASE_ROW + slot_id * self._KEY_ROWS_PER_SLOT
        words = []
        with self._lock:
            for row in range(base, base + self._KEY_ROWS_PER_SLOT):
                value, ok = self._read_row_checked(row, update_status=True)
                if not ok:
                    self._tr.emit('KEY_READ_FAIL', slot=slot_id, row=row)
                    return None
                words.append(value)
        if all(word == 0xFFFFFFFF for word in words):
            self._set_error(self._ERR_ADDR_RANGE)
            self._tr.emit('KEY_READ_EMPTY', slot=slot_id)
            return None
        self._tr.emit('KEY_READ', slot=slot_id)
        return b''.join(word.to_bytes(4, 'little') for word in words)

    @staticmethod
    def _put32(buf: bytearray, offset: int, value: int) -> None:
        buf[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, 'little')

    def _execute(self, ctrl: int) -> None:
        command_bits = ctrl & (self._CTRL_READ | self._CTRL_PROGRAM | self._CTRL_RELOAD | self._CTRL_SAVE)
        self._clear_for_command()
        if command_bits == 0 or command_bits & (command_bits - 1):
            self._set_error(self._ERR_BAD_COMMAND)
            self._finish_command(False)
            return

        self._regs.set_bits(self._STATUS, self._STATUS_BUSY)
        success = False
        try:
            if command_bits == self._CTRL_READ:
                success = self._cmd_read()
            elif command_bits == self._CTRL_PROGRAM:
                success = self._cmd_program()
            elif command_bits == self._CTRL_RELOAD:
                success = self._load_from_file()
                self._refresh_shadow()
            elif command_bits == self._CTRL_SAVE:
                success = self._save_to_file()
            else:
                self._set_error(self._ERR_BAD_COMMAND)
        finally:
            self._regs.clear_bits(self._STATUS, self._STATUS_BUSY)
            self._finish_command(success)

    def _clear_for_command(self) -> None:
        self._regs.clear_bits(self._STATUS, self._STATUS_DONE | self._STATUS_ERROR | self._STATUS_IRQ_PENDING)
        self._regs.clear_bits(self._INT_STATUS, self._INT_DONE | self._INT_ERROR)
        self._regs.set32(self._ERROR, self._ERR_NONE)

    def _finish_command(self, success: bool) -> None:
        self._regs.set_bits(self._STATUS, self._STATUS_DONE)
        self._regs.set_bits(self._INT_STATUS, self._INT_DONE)
        if not success:
            self._regs.set_bits(self._STATUS, self._STATUS_ERROR)
            self._regs.set_bits(self._INT_STATUS, self._INT_ERROR)
        self._update_file_status()
        self._maybe_irq()

    def _cmd_read(self) -> bool:
        row = self._regs.get32(self._ADDR)
        if not self._row_in_range(row):
            self._set_error(self._ERR_ADDR_RANGE)
            return False
        if self._is_read_protected(row):
            self._regs.set_bits(self._STATUS, self._STATUS_READ_PROTECTED)
            self._set_error(self._ERR_READ_PROTECTED)
            self._tr.emit('READ_PROTECTED', row=row)
            return False
        with self._lock:
            value, ok = self._read_row_checked(row, update_status=True)
            ecc = self._ecc[row]
        self._regs.set32(self._RDATA, value)
        self._regs.set32(self._ECC_RDATA, ecc)
        self._tr.emit('READ', row=row, value=value, ok=ok)
        return ok

    def _cmd_program(self) -> bool:
        row = self._regs.get32(self._ADDR)
        new_value = self._regs.get32(self._WDATA)
        if not self._row_in_range(row):
            self._set_error(self._ERR_ADDR_RANGE)
            return False
        if not self._is_unlocked():
            self._set_error(self._ERR_UNLOCK_REQUIRED)
            return False
        if self._row_locked(row):
            self._regs.set_bits(self._STATUS, self._STATUS_LOCKED_REGION)
            self._set_error(self._ERR_LOCKED)
            return False
        with self._lock:
            old_value = self._rows[row]
            if new_value & ~old_value:
                self._set_error(self._ERR_ZERO_TO_ONE)
                self._tr.emit('PROGRAM_FAIL_ZERO_TO_ONE', row=row, old=old_value, new=new_value)
                return False
            programmed = old_value & new_value
            self._rows[row] = programmed
            self._ecc[row] = self._compute_ecc(programmed)
        self._regs.set32(self._RDATA, programmed)
        self._regs.set32(self._ECC_RDATA, self._compute_ecc(programmed))
        self._regs.set_bits(self._STATUS, self._STATUS_FILE_DIRTY)
        self._refresh_shadow()
        if self._auto_save and not self._save_to_file():
            return False
        self._tr.emit('PROGRAM', row=row, old=old_value, new=programmed)
        return True

    def _load_from_file(self) -> bool:
        with self._lock:
            self._rows = [0xFFFFFFFF for _ in range(self._row_count)]
            self._ecc = [self._compute_ecc(0xFFFFFFFF) for _ in range(self._row_count)]
            self._lock_status = 0
            exists = self._storage_file.exists()
            if not exists:
                if self._strict_file:
                    self._set_error(self._ERR_FILE_IO)
                    return False
                self._regs.set_bits(self._STATUS, self._STATUS_FILE_LOADED)
                return True
            try:
                for line_no, raw_line in enumerate(self._storage_file.read_text(encoding='utf-8').splitlines(), 1):
                    line = raw_line.strip()
                    if not line or line.startswith('#'):
                        if line.startswith('# LOCK_STATUS'):
                            parts = line.split()
                            if len(parts) >= 3:
                                self._lock_status = int(parts[2], 16) & 0xF
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        raise ValueError(f'line {line_no}: expected 3 fields')
                    row = int(parts[0], 16)
                    value = int(parts[1], 16) & 0xFFFFFFFF
                    ecc = int(parts[2], 16) & 0xFF
                    if not self._row_in_range(row):
                        raise ValueError(f'line {line_no}: row out of range')
                    self._rows[row] = value
                    self._ecc[row] = ecc
            except (OSError, ValueError) as exc:
                print(f'[OTP] file load error: {exc}', flush=True)
                self._regs.set_bits(self._FILE_STATUS, self._FILE_FORMAT_ERROR)
                self._set_error(self._ERR_FILE_FORMAT)
                return False
        self._regs.set_bits(self._STATUS, self._STATUS_FILE_LOADED)
        self._regs.set32(self._LOCK_STATUS, self._lock_status)
        self._tr.emit('LOAD', path=str(self._storage_file))
        return True

    def _save_to_file(self) -> bool:
        try:
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                lines = [
                    '# KX6625 OTP v1: row_index data_hex ecc_hex',
                    f'# LOCK_STATUS {self._lock_status:08X}',
                ]
                for row, value in enumerate(self._rows):
                    ecc = self._ecc[row]
                    if value != 0xFFFFFFFF or ecc != self._compute_ecc(0xFFFFFFFF):
                        lines.append(f'{row:04X} {value:08X} {ecc:02X}')
            self._storage_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        except OSError as exc:
            print(f'[OTP] file save error: {exc}', flush=True)
            self._set_error(self._ERR_FILE_IO)
            return False
        self._regs.clear_bits(self._STATUS, self._STATUS_FILE_DIRTY)
        self._tr.emit('SAVE', path=str(self._storage_file))
        return True

    def _refresh_shadow(self) -> None:
        with self._lock:
            for idx in range(4):
                row = self._LIFECYCLE_BASE_ROW + idx
                self._regs.set32(self._LIFECYCLE_WORD0 + idx * 4, self._rows[row])
            for idx in range(4):
                row = self._CUSTOMER_BASE_ROW + idx
                self._regs.set32(self._CUSTOMER_WORD0 + idx * 4, self._rows[row])
        self._regs.set_bits(self._STATUS, self._STATUS_SHADOW_VALID)

    def _read_row_checked(self, row: int, update_status: bool) -> tuple[int, bool]:
        value = self._rows[row]
        stored_ecc = self._ecc[row]
        corrected, ok, event = self._check_and_correct(value, stored_ecc)
        if event == 'corrected':
            if update_status:
                self._latch_ecc_corrected(row)
            value = corrected
        elif event == 'uncorrectable':
            if update_status:
                self._latch_ecc_uncorrectable(row)
            return value, False
        return value, ok

    def _latch_ecc_corrected(self, row: int) -> None:
        self._corrected_count = (self._corrected_count + 1) & 0xFF
        self._last_ecc_row = row & 0xFFFF
        self._regs.set_bits(self._STATUS, self._STATUS_ECC_CORRECTED)
        self._regs.set_bits(self._INT_STATUS, self._INT_ECC_CORRECTED)
        self._update_ecc_status()

    def _latch_ecc_uncorrectable(self, row: int) -> None:
        self._uncorrectable_count = (self._uncorrectable_count + 1) & 0xFF
        self._last_ecc_row = row & 0xFFFF
        self._regs.set_bits(self._STATUS, self._STATUS_ECC_UNCORRECTABLE)
        self._regs.set_bits(self._INT_STATUS, self._INT_ECC_UNCORRECTABLE)
        self._set_error(self._ERR_ECC_UNCORRECTABLE)
        self._update_ecc_status()

    def _update_ecc_status(self) -> None:
        value = self._corrected_count | (self._uncorrectable_count << 8) | (self._last_ecc_row << 16)
        self._regs.set32(self._ECC_STATUS, value)

    def _update_file_status(self) -> None:
        value = 0
        if self._storage_file.exists():
            value |= self._FILE_EXISTS
        if self._regs.get32(self._STATUS) & self._STATUS_FILE_LOADED:
            value |= self._FILE_LOADED
        if self._regs.get32(self._STATUS) & self._STATUS_FILE_DIRTY:
            value |= self._FILE_DIRTY
        if self._strict_file:
            value |= self._FILE_STRICT
        if self._regs.get32(self._FILE_STATUS) & self._FILE_FORMAT_ERROR:
            value |= self._FILE_FORMAT_ERROR
        self._regs.set32(self._FILE_STATUS, value)

    def _refresh_unlocked_status(self) -> None:
        if self._is_unlocked():
            self._regs.set_bits(self._STATUS, self._STATUS_UNLOCKED)

    def _is_unlocked(self) -> bool:
        return (self._regs.get32(self._UNLOCK0) == self._UNLOCK0_VALUE and
                self._regs.get32(self._UNLOCK1) == self._UNLOCK1_VALUE)

    def _row_in_range(self, row: int) -> bool:
        return 0 <= row < self._row_count

    def _is_read_protected(self, row: int) -> bool:
        return self._KEY_BASE_ROW <= row <= self._KEY_LAST_ROW

    def _row_locked(self, row: int) -> bool:
        if self._KEY_BASE_ROW <= row <= self._KEY_LAST_ROW:
            return bool(self._lock_status & self._LOCK_HSM_KEYS)
        if self._LIFECYCLE_BASE_ROW <= row <= self._LIFECYCLE_BASE_ROW + 3:
            return bool(self._lock_status & self._LOCK_LIFECYCLE)
        if self._CUSTOMER_BASE_ROW <= row <= 0x005F:
            return bool(self._lock_status & self._LOCK_CUSTOMER)
        if row >= self._GP_BASE_ROW:
            return bool(self._lock_status & self._LOCK_GP)
        return False

    def _set_error(self, code: int) -> None:
        self._regs.set32(self._ERROR, code)
        self._regs.set_bits(self._STATUS, self._STATUS_ERROR)

    def _maybe_irq(self) -> None:
        ctrl = self._regs.get32(self._CTRL)
        pending = self._regs.get32(self._INT_STATUS) & self._regs.get32(self._INT_ENABLE)
        if (ctrl & self._CTRL_IRQ_ENABLE) and pending:
            self._regs.set_bits(self._STATUS, self._STATUS_IRQ_PENDING)
            self._irq.pulse()
            self._tr.emit('IRQ_PULSE', irq_idx=self._irq.idx, pending=pending)

    @classmethod
    def _compute_ecc(cls, value: int) -> int:
        parity = 0
        for data_bit in range(32):
            if (value >> data_bit) & 1:
                pos = cls._data_bit_to_hamming_pos(data_bit)
                parity ^= pos
        parity &= 0x3F
        overall = (cls._popcount(value) + cls._popcount(parity)) & 1
        return parity | (overall << 7)

    @staticmethod
    def _popcount(value: int) -> int:
        return bin(value & 0xFFFFFFFF).count('1')

    @classmethod
    def _check_and_correct(cls, value: int, stored_ecc: int) -> tuple[int, bool, str]:
        calc_ecc = cls._compute_ecc(value)
        syndrome = (calc_ecc ^ stored_ecc) & 0x3F
        overall_diff = ((calc_ecc ^ stored_ecc) >> 7) & 1
        if syndrome == 0 and overall_diff == 0:
            return value, True, 'ok'
        if overall_diff == 1:
            data_bit = cls._hamming_pos_to_data_bit(syndrome)
            if data_bit is not None:
                return value ^ (1 << data_bit), True, 'corrected'
            return value, True, 'corrected'
        return value, False, 'uncorrectable'

    @staticmethod
    def _data_bit_to_hamming_pos(data_bit: int) -> int:
        count = -1
        pos = 1
        while True:
            if pos & (pos - 1):
                count += 1
                if count == data_bit:
                    return pos
            pos += 1

    @staticmethod
    def _hamming_pos_to_data_bit(pos: int) -> Optional[int]:
        if pos <= 0 or not (pos & (pos - 1)):
            return None
        data_bit = -1
        for candidate in range(1, pos + 1):
            if candidate & (candidate - 1):
                data_bit += 1
        return data_bit if 0 <= data_bit < 32 else None
