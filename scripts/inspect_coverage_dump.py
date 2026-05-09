#!/usr/bin/env python3
"""Inspect a KXCV coverage dump emitted by the MMIO coverage device."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path


def count_nonzero_u64(payload: bytes) -> int:
    count = 0
    for idx in range(0, len(payload) - (len(payload) % 8), 8):
        if int.from_bytes(payload[idx:idx + 8], 'little') != 0:
            count += 1
    return count


def parse_kxcv(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b'KXCV':
        raise ValueError(f'{path} is not a KXCV coverage dump')

    version, region_count = struct.unpack_from('<II', data, 4)
    offset = 12
    regions = {}
    for _ in range(region_count):
        if offset + 12 > len(data):
            raise ValueError('truncated region header')
        region_id, name_len, payload_len = struct.unpack_from('<III', data, offset)
        offset += 12
        if offset + name_len + payload_len > len(data):
            raise ValueError('truncated region payload')
        name = data[offset:offset + name_len].decode('ascii')
        offset += name_len
        payload = data[offset:offset + payload_len]
        offset += payload_len
        regions[name] = {
            'id': region_id,
            'captured_bytes': payload_len,
            'crc32': f'0x{zlib.crc32(payload) & 0xFFFFFFFF:08X}',
            'nonzero_u64': count_nonzero_u64(payload),
        }

    return {
        'format': 'KXCV',
        'version': version,
        'file': str(path),
        'file_bytes': len(data),
        'payload_bytes': sum(item['captured_bytes'] for item in regions.values()),
        'regions': regions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump', nargs='?', default='build/coverage/firmware.kxcv')
    parser.add_argument('--json', dest='json_out', help='Optional path for JSON summary output')
    parser.add_argument('--require-nonzero-counters', action='store_true')
    args = parser.parse_args()

    try:
        summary = parse_kxcv(Path(args.dump))
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(summary, indent=2))

    if args.require_nonzero_counters:
        counters = summary['regions'].get('prf_cnts', {})
        if counters.get('nonzero_u64', 0) == 0:
            print('ERROR: prf_cnts has no non-zero 64-bit counters', file=sys.stderr)
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())