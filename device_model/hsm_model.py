"""
hsm_model — AES-128 / CMAC hardware security module model.

The HSM is exposed as a CPU-visible MMIO register block, but the data path is
DMA-style: firmware programs SRC_ADDR/DST_ADDR/LENGTH/MODE/KEY_ID and writes
CTRL.START.  The model then reads the source buffer from the QEMU physical
address space, performs AES/CMAC internally, writes the result to DST_ADDR, and
pulses its IRQ when complete.

Register access is restricted to CPU0 (master_id == 0).  Other masters read
zero, writes are ignored, and STATUS.ACCESS_ERR is sticky until module reset.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

from device_model.mmio_base import AddressSpace, IRQController, IrqLine, MMIODevice, RegAccess, RegisterBank
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


class HsmDevice(MMIODevice):
    # Register offsets
    _ID         = 0x00
    _VERSION    = 0x04
    _CTRL       = 0x08
    _STATUS     = 0x0C
    _INT_STATUS = 0x10
    _INT_ENABLE = 0x14
    _ERROR      = 0x18
    _MODE       = 0x1C
    _SRC_ADDR   = 0x20
    _DST_ADDR   = 0x24
    _LENGTH     = 0x28
    _DMA_STATUS = 0x2C
    _KEY_ID     = 0x30
    _KEY_STATUS = 0x34
    _KEY_WORD0  = 0x38
    _KEY_WORD1  = 0x3C
    _KEY_WORD2  = 0x40
    _KEY_WORD3  = 0x44
    _IV_WORD0   = 0x50
    _IV_WORD1   = 0x54
    _IV_WORD2   = 0x58
    _IV_WORD3   = 0x5C
    _TAG_WORD0  = 0x60
    _TAG_WORD1  = 0x64
    _TAG_WORD2  = 0x68
    _TAG_WORD3  = 0x6C
    _REGSIZE    = 0x70

    # CTRL bits
    _CTRL_START  = 0x01
    _CTRL_IRQ_EN = 0x02

    # STATUS bits
    _STATUS_BUSY           = 0x01
    _STATUS_DONE           = 0x02
    _STATUS_ERROR          = 0x04
    _STATUS_IRQ_PENDING    = 0x08
    _STATUS_KEY_VALID      = 0x10
    _STATUS_OTP_KEY_LOADED = 0x20
    _STATUS_ACCESS_ERR     = 0x40

    # INT bits
    _INT_DONE       = 0x01
    _INT_ERROR      = 0x02
    _INT_ACCESS_ERR = 0x04

    # DMA_STATUS bits
    _DMA_READ_BUSY  = 0x01
    _DMA_READ_DONE  = 0x02
    _DMA_WRITE_BUSY = 0x04
    _DMA_WRITE_DONE = 0x08
    _DMA_ERROR      = 0x10

    # KEY_STATUS bits
    _KEY_REG_WRITTEN    = 0x01
    _KEY_OTP_AVAILABLE  = 0x02
    _KEY_ACTIVE_VALID   = 0x04

    # MODE values and flags
    _MODE_ECB = 0
    _MODE_CBC = 1
    _MODE_CFB = 2
    _MODE_CTR = 3
    _MODE_CMAC = 4
    _MODE_DECRYPT = 0x100

    # ERROR codes
    _ERR_NONE = 0
    _ERR_ACCESS_DENIED = 1
    _ERR_INVALID_MODE = 2
    _ERR_INVALID_LENGTH = 3
    _ERR_KEY_NOT_VALID = 4
    _ERR_OTP_FILE = 5
    _ERR_OTP_SLOT = 6
    _ERR_DMA_READ = 7
    _ERR_DMA_WRITE = 8
    _ERR_DST_BUS = 9

    _KEY_ID_REGISTER = 15
    _ALLOWED_MASTER = 0

    _FLASH_BASE = 0x00000000
    _FLASH_SIZE = 0x00080000

    def __init__(
        self,
        address_space: AddressSpace,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        otp_file: str = 'build/hsm_otp.json',
        tracer: Optional[Tracer] = None,
    ) -> None:
        init = bytearray(self._REGSIZE)
        init[self._ID:self._ID + 4] = (0x314D5348).to_bytes(4, 'little')
        init[self._VERSION:self._VERSION + 4] = (0x00010000).to_bytes(4, 'little')
        self._regs = RegisterBank(
            self._REGSIZE,
            bytes(init),
            policies={
                self._ID: RegAccess.READ_ONLY,
                self._VERSION: RegAccess.READ_ONLY,
                self._STATUS: RegAccess.READ_ONLY,
                self._ERROR: RegAccess.READ_ONLY,
                self._DMA_STATUS: RegAccess.READ_ONLY,
                self._KEY_STATUS: RegAccess.READ_ONLY,
                self._KEY_WORD0: RegAccess.WRITE_ONLY,
                self._KEY_WORD1: RegAccess.WRITE_ONLY,
                self._KEY_WORD2: RegAccess.WRITE_ONLY,
                self._KEY_WORD3: RegAccess.WRITE_ONLY,
                self._TAG_WORD0: RegAccess.READ_ONLY,
                self._TAG_WORD1: RegAccess.READ_ONLY,
                self._TAG_WORD2: RegAccess.READ_ONLY,
                self._TAG_WORD3: RegAccess.READ_ONLY,
                self._INT_STATUS: RegAccess.W1C,
            },
        )
        self._addrspace = address_space
        self._irq = IrqLine(irq_controller, irq_idx)
        self._otp_file = Path(otp_file)
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
        self._op_lock = threading.Lock()
        self._active_key: Optional[bytes] = None
        self._register_key_words_written = 0

    @property
    def name(self) -> str:
        return 'HSM'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        if not self._master_allowed(master_id):
            self._latch_access_error(master_id)
            return b'\x00' * size
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        if not self._master_allowed(master_id):
            self._latch_access_error(master_id)
            return 0

        self._regs.write(offset, size, data)

        if offset <= self._INT_STATUS < offset + size:
            if self._regs.get32(self._INT_STATUS) == 0:
                self._regs.clear_bits(self._STATUS, self._STATUS_IRQ_PENDING)

        for key_off in (self._KEY_WORD0, self._KEY_WORD1, self._KEY_WORD2, self._KEY_WORD3):
            if offset <= key_off < offset + size:
                self._register_key_words_written |= 1 << ((key_off - self._KEY_WORD0) // 4)
                self._refresh_key_status()

        if offset <= self._CTRL < offset + size:
            ctrl = self._regs.get32(self._CTRL)
            if ctrl & self._CTRL_START:
                self._regs.clear_bits(self._CTRL, self._CTRL_START)
                self._start_operation()
        return 0

    def on_reset(self) -> None:
        self._regs.reset()
        self._active_key = None
        self._register_key_words_written = 0
        self._tr.emit('RESET')

    def _master_allowed(self, master_id: int) -> bool:
        return master_id == self._ALLOWED_MASTER

    def _latch_access_error(self, master_id: int) -> None:
        self._set_error(self._ERR_ACCESS_DENIED)
        self._regs.set_bits(self._STATUS, self._STATUS_ACCESS_ERR)
        self._regs.set_bits(self._INT_STATUS, self._INT_ACCESS_ERR)
        self._maybe_irq()
        print(f'[HSM] access denied for master_id={master_id}', flush=True)
        self._tr.emit('ACCESS_DENIED', master_id=master_id)

    def _start_operation(self) -> None:
        if not self._op_lock.acquire(blocking=False):
            self._set_error(self._ERR_DMA_WRITE)
            return
        self._clear_for_start()
        thread = threading.Thread(target=self._run_operation, daemon=True, name='hsm-op')
        thread.start()

    def _clear_for_start(self) -> None:
        self._regs.clear_bits(
            self._STATUS,
            self._STATUS_DONE | self._STATUS_ERROR | self._STATUS_IRQ_PENDING,
        )
        self._regs.set32(self._ERROR, self._ERR_NONE)
        self._regs.set32(self._DMA_STATUS, 0)
        self._regs.clear_bits(self._INT_STATUS, self._INT_DONE | self._INT_ERROR)
        self._regs.set_bits(self._STATUS, self._STATUS_BUSY)

    def _run_operation(self) -> None:
        success = False
        try:
            src = self._regs.get32(self._SRC_ADDR)
            dst = self._regs.get32(self._DST_ADDR)
            length = self._regs.get32(self._LENGTH)
            mode_reg = self._regs.get32(self._MODE)
            mode = mode_reg & 0xF
            decrypt = bool(mode_reg & self._MODE_DECRYPT)

            self._tr.emit('START', src=src, dst=dst, length=length, mode=mode, decrypt=decrypt)
            print(
                f'[HSM] START mode={mode} decrypt={int(decrypt)} '
                f'src=0x{src:08x} dst=0x{dst:08x} len={length}',
                flush=True,
            )

            key = self._resolve_key()
            if key is None:
                return
            if not self._validate_length(mode, length):
                self._set_error(self._ERR_INVALID_LENGTH)
                return
            if self._dst_is_flash(dst):
                self._set_error(self._ERR_DST_BUS)
                return

            self._regs.set_bits(self._DMA_STATUS, self._DMA_READ_BUSY)
            data = self._addrspace.read(src, length)
            self._regs.clear_bits(self._DMA_STATUS, self._DMA_READ_BUSY)
            if data is None or len(data) != length:
                self._regs.set_bits(self._DMA_STATUS, self._DMA_ERROR)
                self._set_error(self._ERR_DMA_READ)
                return
            self._regs.set_bits(self._DMA_STATUS, self._DMA_READ_DONE)

            output = self._crypt(mode, decrypt, key, data)
            if output is None:
                return

            self._regs.set_bits(self._DMA_STATUS, self._DMA_WRITE_BUSY)
            ok = self._addrspace.write(dst, output)
            self._regs.clear_bits(self._DMA_STATUS, self._DMA_WRITE_BUSY)
            if not ok:
                self._regs.set_bits(self._DMA_STATUS, self._DMA_ERROR)
                self._set_error(self._ERR_DMA_WRITE)
                return
            self._regs.set_bits(self._DMA_STATUS, self._DMA_WRITE_DONE)

            if mode == self._MODE_CMAC:
                self._write_tag_words(output)

            success = True
            self._regs.set_bits(self._STATUS, self._STATUS_DONE)
            self._regs.set_bits(self._INT_STATUS, self._INT_DONE)
            self._tr.emit('DONE', ok=True, out_len=len(output))
            print(f'[HSM] DONE out_len={len(output)}', flush=True)
        finally:
            self._regs.clear_bits(self._STATUS, self._STATUS_BUSY)
            if not success:
                self._regs.set_bits(self._STATUS, self._STATUS_ERROR)
                self._regs.set_bits(self._INT_STATUS, self._INT_ERROR)
                self._tr.emit('DONE', ok=False, error=self._regs.get32(self._ERROR))
                print(f'[HSM] ERROR code={self._regs.get32(self._ERROR)}', flush=True)
            self._maybe_irq()
            self._op_lock.release()

    def _resolve_key(self) -> Optional[bytes]:
        key_id = self._regs.get32(self._KEY_ID) & 0xFF
        self._regs.clear_bits(self._STATUS, self._STATUS_KEY_VALID | self._STATUS_OTP_KEY_LOADED)
        if key_id == self._KEY_ID_REGISTER:
            if self._register_key_words_written != 0xF:
                self._set_error(self._ERR_KEY_NOT_VALID)
                return None
            key = self._read_words(self._KEY_WORD0, 4)
            self._active_key = key
            self._regs.set_bits(self._STATUS, self._STATUS_KEY_VALID)
            self._refresh_key_status(active_key_valid=True)
            return key
        if 0 <= key_id <= 14:
            key = self._load_otp_key(key_id)
            if key is None:
                return None
            self._active_key = key
            self._regs.set_bits(self._STATUS, self._STATUS_KEY_VALID | self._STATUS_OTP_KEY_LOADED)
            self._refresh_key_status(active_key_valid=True, otp_available=True)
            return key
        self._set_error(self._ERR_OTP_SLOT)
        return None

    def _load_otp_key(self, key_id: int) -> Optional[bytes]:
        try:
            doc = json.loads(self._otp_file.read_text(encoding='utf-8'))
            value = doc['slots'][str(key_id)]['aes128']
            key = bytes.fromhex(value)
        except FileNotFoundError:
            self._set_error(self._ERR_OTP_FILE)
            return None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._set_error(self._ERR_OTP_SLOT)
            return None
        if len(key) != 16:
            self._set_error(self._ERR_OTP_SLOT)
            return None
        return key

    def _validate_length(self, mode: int, length: int) -> bool:
        if length == 0:
            return False
        if mode in (self._MODE_ECB, self._MODE_CBC):
            return (length % 16) == 0
        if mode in (self._MODE_CFB, self._MODE_CTR, self._MODE_CMAC):
            return True
        self._set_error(self._ERR_INVALID_MODE)
        return False

    def _crypt(self, mode: int, decrypt: bool, key: bytes, data: bytes) -> Optional[bytes]:
        iv = self._read_words(self._IV_WORD0, 4)
        try:
            if mode == self._MODE_ECB:
                cipher = AES.new(key, AES.MODE_ECB)
                return cipher.decrypt(data) if decrypt else cipher.encrypt(data)
            if mode == self._MODE_CBC:
                cipher = AES.new(key, AES.MODE_CBC, iv=iv)
                return cipher.decrypt(data) if decrypt else cipher.encrypt(data)
            if mode == self._MODE_CFB:
                cipher = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
                return cipher.decrypt(data) if decrypt else cipher.encrypt(data)
            if mode == self._MODE_CTR:
                cipher = AES.new(key, AES.MODE_CTR, nonce=b'', initial_value=int.from_bytes(iv, 'big'))
                return cipher.encrypt(data)
            if mode == self._MODE_CMAC:
                cmac = CMAC.new(key, ciphermod=AES)
                cmac.update(data)
                return cmac.digest()
        except ValueError as exc:
            print(f'[HSM] crypto error: {exc}', file=sys.stderr, flush=True)
            self._set_error(self._ERR_INVALID_MODE)
            return None
        self._set_error(self._ERR_INVALID_MODE)
        return None

    def _read_words(self, start: int, count: int) -> bytes:
        out = bytearray()
        for idx in range(count):
            out.extend(self._regs.get32(start + idx * 4).to_bytes(4, 'little'))
        return bytes(out)

    def _write_tag_words(self, tag: bytes) -> None:
        for idx in range(4):
            word = int.from_bytes(tag[idx * 4:idx * 4 + 4], 'little')
            self._regs.set32(self._TAG_WORD0 + idx * 4, word)

    def _refresh_key_status(self, active_key_valid: bool = False, otp_available: bool = False) -> None:
        key_id = self._regs.get32(self._KEY_ID) & 0xFF
        status = (key_id & 0xFF) << 8
        if self._register_key_words_written == 0xF:
            status |= self._KEY_REG_WRITTEN
        if otp_available:
            status |= self._KEY_OTP_AVAILABLE
        if active_key_valid:
            status |= self._KEY_ACTIVE_VALID
        self._regs.set32(self._KEY_STATUS, status)

    def _set_error(self, code: int) -> None:
        self._regs.set32(self._ERROR, code)
        self._regs.set_bits(self._STATUS, self._STATUS_ERROR)

    def _maybe_irq(self) -> None:
        ctrl = self._regs.get32(self._CTRL)
        pending = self._regs.get32(self._INT_STATUS) & self._regs.get32(self._INT_ENABLE)
        if (ctrl & self._CTRL_IRQ_EN) and pending:
            self._regs.set_bits(self._STATUS, self._STATUS_IRQ_PENDING)
            self._irq.pulse()
            self._tr.emit('IRQ_PULSE', irq_idx=self._irq.idx, pending=pending)

    def _dst_is_flash(self, dst: int) -> bool:
        return self._FLASH_BASE <= dst < self._FLASH_BASE + self._FLASH_SIZE
