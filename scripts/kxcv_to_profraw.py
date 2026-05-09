#!/usr/bin/env python3
"""Convert a KXCV MMIO coverage dump into an LLVM raw profile (.profraw)."""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path


LLVM_RAW_MAGIC_32 = (
    (255 << 56)
    | (ord('l') << 48)
    | (ord('p') << 40)
    | (ord('r') << 32)
    | (ord('o') << 24)
    | (ord('f') << 16)
    | (ord('R') << 8)
    | 129
)
LLVM_RAW_VERSION = 5
LLVM_VALUE_KIND_LAST = 1
PROFILE_DATA_32_SIZE = 40


def align8_padding(size: int) -> int:
    return (8 - (size % 8)) % 8


def parse_kxcv(path: Path) -> dict[str, bytes]:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b'KXCV':
        raise ValueError(f'{path} is not a KXCV coverage dump')
    version, region_count = struct.unpack_from('<II', data, 4)
    if version != 1:
        raise ValueError(f'unsupported KXCV version {version}')

    offset = 12
    regions: dict[str, bytes] = {}
    for _ in range(region_count):
        if offset + 12 > len(data):
            raise ValueError('truncated KXCV region header')
        _region_id, name_len, payload_len = struct.unpack_from('<III', data, offset)
        offset += 12
        if offset + name_len + payload_len > len(data):
            raise ValueError('truncated KXCV region payload')
        name = data[offset:offset + name_len].decode('ascii')
        offset += name_len
        regions[name] = data[offset:offset + payload_len]
        offset += payload_len
    return regions


def load_symbols(elf: Path, nm: str = 'arm-none-eabi-nm') -> dict[str, int]:
    try:
        output = subprocess.check_output([nm, '-n', str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f'failed to run {nm} on {elf}: {exc}') from exc

    symbols: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                symbols[parts[2]] = int(parts[0], 16)
            except ValueError:
                pass
    return symbols


def require_symbols(symbols: dict[str, int], names: list[str]) -> dict[str, int]:
    missing = [name for name in names if name not in symbols]
    if missing:
        raise ValueError('missing ELF symbols: ' + ', '.join(missing))
    return {name: symbols[name] for name in names}


def build_profraw(regions: dict[str, bytes], counters_start: int, names_start: int) -> bytes:
    required = ['prf_data', 'prf_cnts', 'prf_names']
    missing = [name for name in required if name not in regions]
    if missing:
        raise ValueError('KXCV missing regions: ' + ', '.join(missing))

    data = regions['prf_data']
    counters = regions['prf_cnts']
    names = regions['prf_names']

    if len(data) % PROFILE_DATA_32_SIZE != 0:
        raise ValueError(f'prf_data size {len(data)} is not a multiple of {PROFILE_DATA_32_SIZE}')
    if len(counters) % 8 != 0:
        raise ValueError(f'prf_cnts size {len(counters)} is not 8-byte aligned')

    padding_before_counters = align8_padding(len(data))
    padding_after_counters = align8_padding(len(counters))
    header = struct.pack(
        '<10Q',
        LLVM_RAW_MAGIC_32,
        LLVM_RAW_VERSION,
        len(data) // PROFILE_DATA_32_SIZE,
        padding_before_counters,
        len(counters) // 8,
        padding_after_counters,
        len(names),
        counters_start,
        names_start,
        LLVM_VALUE_KIND_LAST,
    )
    return b''.join([
        header,
        data,
        b'\x00' * padding_before_counters,
        counters,
        b'\x00' * padding_after_counters,
        names,
        b'\x00' * 8,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump', nargs='?', default='build/coverage/firmware.kxcv')
    parser.add_argument('-o', '--output', default='build/coverage/firmware.profraw')
    parser.add_argument('--elf', default='build/firmware.elf')
    parser.add_argument('--nm', default='arm-none-eabi-nm')
    args = parser.parse_args()

    try:
        regions = parse_kxcv(Path(args.dump))
        symbols = require_symbols(load_symbols(Path(args.elf), args.nm), [
            '__llvm_prf_cnts_start',
            '__llvm_prf_names_start',
        ])
        profraw = build_profraw(
            regions,
            counters_start=symbols['__llvm_prf_cnts_start'],
            names_start=symbols['__llvm_prf_names_start'],
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(profraw)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    print(f'wrote {args.output} ({len(profraw)} bytes)')
    print(f'  data_records={len(regions["prf_data"]) // PROFILE_DATA_32_SIZE}')
    print(f'  counters={len(regions["prf_cnts"]) // 8}')
    print(f'  names_bytes={len(regions["prf_names"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())