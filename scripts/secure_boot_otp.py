#!/usr/bin/env python3
"""Install KX6625 secure-boot OTP metadata for a firmware Intel HEX image."""

from __future__ import annotations

import argparse
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

FLASH_BASE = 0x00000000
FLASH_SIZE = 0x00080000
BOOT_MAGIC = 0x31564253
BOOT_ALG_AES_CMAC = 1
BOOT_KEY_ID = 0
DEFAULT_KEY_HEX = '2b7e151628aed2a6abf7158809cf4f3c'
ERASED_WORD = 0xFFFFFFFF

KEY_BASE_ROW = 0x0000
KEY_ROWS_PER_SLOT = 4
BOOT_MAGIC_ROW = 0x0040
BOOT_IMAGE_BASE_ROW = 0x0041
BOOT_IMAGE_SIZE_ROW = 0x0042
BOOT_CONFIG_ROW = 0x0043
BOOT_CMAC_BASE_ROW = 0x0050
BOOT_CMAC_ROWS = 4


def compute_ecc(value: int) -> int:
    parity = 0
    for data_bit in range(32):
        if (value >> data_bit) & 1:
            pos = data_bit_to_hamming_pos(data_bit)
            parity ^= pos
    parity &= 0x3F
    overall = (popcount(value) + popcount(parity)) & 1
    return parity | (overall << 7)


def popcount(value: int) -> int:
    return bin(value & 0xFFFFFFFF).count('1')


def data_bit_to_hamming_pos(data_bit: int) -> int:
    count = -1
    pos = 1
    while True:
        if pos & (pos - 1):
            count += 1
            if count == data_bit:
                return pos
        pos += 1


def parse_intel_hex(path: Path, flash_base: int, flash_size: int) -> bytearray:
    image = bytearray([0xFF] * flash_size)
    upper = 0
    for line_no, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(':'):
            raise ValueError(f'{path}:{line_no}: expected Intel HEX record')
        data = bytes.fromhex(line[1:])
        count = data[0]
        addr = int.from_bytes(data[1:3], 'big')
        rectype = data[3]
        payload = data[4:4 + count]
        checksum = sum(data) & 0xFF
        if checksum != 0:
            raise ValueError(f'{path}:{line_no}: bad checksum')
        if rectype == 0x00:
            absolute = upper + addr
            start = absolute - flash_base
            end = start + count
            if start < 0 or end > flash_size:
                raise ValueError(f'{path}:{line_no}: data outside flash range 0x{flash_base:08x}..0x{flash_base + flash_size:08x}')
            image[start:end] = payload
        elif rectype == 0x01:
            break
        elif rectype == 0x02:
            upper = int.from_bytes(payload, 'big') << 4
        elif rectype == 0x04:
            upper = int.from_bytes(payload, 'big') << 16
        elif rectype in (0x03, 0x05):
            continue
        else:
            raise ValueError(f'{path}:{line_no}: unsupported record type {rectype}')
    return image


def load_otp(path: Path, fresh: bool) -> tuple[list[int], int]:
    rows = [ERASED_WORD] * 256
    lock_status = 0
    if fresh or not path.exists():
        return rows, lock_status
    for line_no, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == 'LOCK_STATUS':
                lock_status = int(parts[2], 16) & 0xF
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f'{path}:{line_no}: expected row data ecc')
        row = int(parts[0], 16)
        if not 0 <= row < len(rows):
            raise ValueError(f'{path}:{line_no}: row out of range')
        rows[row] = int(parts[1], 16) & 0xFFFFFFFF
    return rows, lock_status


def program_word(rows: list[int], row: int, value: int) -> None:
    old = rows[row]
    value &= 0xFFFFFFFF
    if value & ~old:
        raise ValueError(f'OTP row 0x{row:04x} would require 0->1 programming: old=0x{old:08x} new=0x{value:08x}')
    rows[row] = old & value


def write_otp(path: Path, rows: list[int], lock_status: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '# KX6625 OTP v1: row_index data_hex ecc_hex',
        f'# LOCK_STATUS {lock_status:08X}',
    ]
    erased_ecc = compute_ecc(ERASED_WORD)
    for row, value in enumerate(rows):
        ecc = compute_ecc(value)
        if value != ERASED_WORD or ecc != erased_ecc:
            lines.append(f'{row:04X} {value:08X} {ecc:02X}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def install_secure_boot(args: argparse.Namespace) -> None:
    key = bytes.fromhex(args.key_hex)
    if len(key) != 16:
        raise ValueError('secure boot key must be 16 bytes / 32 hex characters')
    if args.image_size <= 0 or args.image_size > FLASH_SIZE:
        raise ValueError(f'image size must be in range 1..0x{FLASH_SIZE:x}')

    image = parse_intel_hex(Path(args.firmware_hex), args.flash_base, FLASH_SIZE)
    cmac = CMAC.new(key, ciphermod=AES)
    cmac.update(bytes(image[:args.image_size]))
    tag = cmac.digest()

    otp_path = Path(args.otp)
    rows, lock_status = load_otp(otp_path, args.fresh)

    for idx in range(4):
        word = int.from_bytes(key[idx * 4:idx * 4 + 4], 'little')
        program_word(rows, KEY_BASE_ROW + BOOT_KEY_ID * KEY_ROWS_PER_SLOT + idx, word)

    program_word(rows, BOOT_MAGIC_ROW, BOOT_MAGIC)
    program_word(rows, BOOT_IMAGE_BASE_ROW, args.flash_base)
    program_word(rows, BOOT_IMAGE_SIZE_ROW, args.image_size)
    program_word(rows, BOOT_CONFIG_ROW, (BOOT_ALG_AES_CMAC << 8) | BOOT_KEY_ID)

    for idx in range(BOOT_CMAC_ROWS):
        word = int.from_bytes(tag[idx * 4:idx * 4 + 4], 'little')
        program_word(rows, BOOT_CMAC_BASE_ROW + idx, word)

    write_otp(otp_path, rows, lock_status)
    print(f'[SECBOOT] firmware={args.firmware_hex}')
    print(f'[SECBOOT] otp={otp_path}')
    print(f'[SECBOOT] image_base=0x{args.flash_base:08x} image_size=0x{args.image_size:08x}')
    print(f'[SECBOOT] key_id={BOOT_KEY_ID} cmac={tag.hex()}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-hex', default='build/firmware.hex')
    parser.add_argument('--otp', default='build/otp.hex')
    parser.add_argument('--key-hex', default=DEFAULT_KEY_HEX)
    parser.add_argument('--flash-base', type=lambda s: int(s, 0), default=FLASH_BASE)
    parser.add_argument('--image-size', type=lambda s: int(s, 0), default=FLASH_SIZE)
    parser.add_argument('--fresh', action='store_true', help='create OTP content from erased state instead of preserving existing rows')
    args = parser.parse_args()
    install_secure_boot(args)


if __name__ == '__main__':
    main()
