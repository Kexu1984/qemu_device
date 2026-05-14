#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {'seq', 't_wall_ns', 't_virt_ns', 'dev', 'event'}

PROFILE_REQUIRED_EVENTS = {
    'platform-smoke': [
        ('__tracer__', 'HEADER'),
        ('fabric', 'READ'),
        ('fabric', 'WRITE'),
        ('py_fabric_master', 'SV_PROBE_PASS'),
        ('py_fabric_master', 'CRC_PROBE_PASS'),
        ('uart0', 'IRQ_FIRE'),
        ('DmaController(2ch)', 'CH_START'),
        ('DmaController(2ch)', 'CH_DONE'),
        ('DmaController(2ch)', 'IRQ_PULSE'),
        ('DmaClientDemo(ch1)', 'IRQ_PULSE'),
        ('CRC-32', 'RESULT'),
        ('HSM', 'START'),
        ('HSM', 'DONE'),
        ('HSM', 'IRQ_PULSE'),
        ('OTP', 'PROGRAM'),
        ('OTP', 'READ_PROTECTED'),
        ('wdt', 'TIMEOUT'),
        ('wdt', 'RESET'),
    ],
}

PROFILE_REQUIRED_SEQUENCES = {
    'platform-smoke': [
        [
            ('DmaController(2ch)', 'CH_START'),
            ('DmaController(2ch)', 'CH_DONE'),
            ('DmaController(2ch)', 'IRQ_PULSE'),
        ],
        [
            ('HSM', 'START'),
            ('HSM', 'DONE'),
            ('HSM', 'IRQ_PULSE'),
        ],
        [
            ('wdt', 'LOAD'),
            ('wdt', 'ARM'),
            ('wdt', 'KICK'),
            ('wdt', 'TIMEOUT'),
            ('wdt', 'RESET'),
        ],
    ],
}

EVENT_REQUIRED_FIELDS = {
    ('fabric', 'READ'): {'master_id', 'addr', 'size', 'status', 'target'},
    ('fabric', 'WRITE'): {'master_id', 'addr', 'size', 'status', 'target'},
    ('py_fabric_master', 'SV_PROBE_PASS'): {'master_id', 'result'},
    ('py_fabric_master', 'CRC_PROBE_PASS'): {'master_id', 'result'},
    ('uart0', 'IRQ_FIRE'): {'irq_idx'},
    ('DmaController(2ch)', 'CH_START'): {'ch', 'src', 'dst', 'length', 'latency_ns'},
    ('DmaController(2ch)', 'CH_DONE'): {'ch', 'ok', 'path'},
    ('DmaController(2ch)', 'IRQ_PULSE'): {'ch', 'irq_idx'},
    ('DmaClientDemo(ch1)', 'IRQ_PULSE'): {'irq_idx'},
    ('CRC-32', 'RESULT'): {'crc32'},
    ('HSM', 'START'): {'src', 'dst', 'length', 'mode'},
    ('HSM', 'DONE'): {'ok', 'out_len'},
    ('HSM', 'IRQ_PULSE'): {'irq_idx', 'pending'},
    ('OTP', 'PROGRAM'): {'row', 'old', 'new'},
    ('OTP', 'READ_PROTECTED'): {'row'},
    ('wdt', 'TIMEOUT'): {'timeout_cnt'},
    ('wdt', 'RESET'): {'reset_reason', 'timeout_cnt'},
}


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open('r', encoding='utf-8') as trace_file:
        for line_number, line in enumerate(trace_file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{line_number}: invalid JSON: {exc}') from exc
            missing = REQUIRED_FIELDS - set(record)
            if missing:
                raise ValueError(f'{path}:{line_number}: missing required fields: {sorted(missing)}')
            records.append(record)
    return records


def validate_common_contract(records: list[dict], trace_name: str) -> list[str]:
    errors: list[str] = []
    if not records:
        return [f'{trace_name}: no trace records found']
    if records[0].get('dev') != '__tracer__' or records[0].get('event') != 'HEADER':
        errors.append(f'{trace_name}: first record is not the tracer HEADER')

    previous_seq = None
    previous_wall = None
    for index, record in enumerate(records):
        seq = record.get('seq')
        wall = record.get('t_wall_ns')
        virt = record.get('t_virt_ns')
        if not isinstance(seq, int):
            errors.append(f'{trace_name}: record {index}: seq is not an int')
        elif previous_seq is not None and seq <= previous_seq:
            errors.append(f'{trace_name}: record {index}: seq is not strictly increasing')
        previous_seq = seq if isinstance(seq, int) else previous_seq

        if not isinstance(wall, int):
            errors.append(f'{trace_name}: record {index}: t_wall_ns is not an int')
        elif previous_wall is not None and wall < previous_wall:
            errors.append(f'{trace_name}: record {index}: t_wall_ns moved backwards')
        previous_wall = wall if isinstance(wall, int) else previous_wall

        if not isinstance(virt, int):
            errors.append(f'{trace_name}: record {index}: t_virt_ns is not an int')
    return errors


def validate_required_events(records: list[dict], required_events: list[tuple[str, str]], trace_name: str) -> list[str]:
    available = {(str(record['dev']), str(record['event'])) for record in records}
    missing_events = [required for required in required_events if required not in available]
    if not missing_events:
        return []
    formatted = ', '.join(f'{device}:{event}' for device, event in missing_events)
    return [f'{trace_name}: missing required events: {formatted}']


def validate_event_fields(records: list[dict], trace_name: str) -> list[str]:
    errors: list[str] = []
    for (device, event), required_fields in EVENT_REQUIRED_FIELDS.items():
        matching = [record for record in records if record.get('dev') == device and record.get('event') == event]
        if not matching:
            continue
        if not any(required_fields <= set(record) for record in matching):
            errors.append(
                f'{trace_name}: {device}:{event} is missing required fields '
                f'{sorted(required_fields)}'
            )
    return errors


def validate_event_sequences(records: list[dict], sequences: list[list[tuple[str, str]]], trace_name: str) -> list[str]:
    errors: list[str] = []
    event_stream = [(str(record.get('dev')), str(record.get('event'))) for record in records]
    for sequence in sequences:
        cursor = 0
        for event in event_stream:
            if cursor < len(sequence) and event == sequence[cursor]:
                cursor += 1
            if cursor == len(sequence):
                break
        if cursor != len(sequence):
            formatted = ' -> '.join(f'{device}:{event}' for device, event in sequence)
            errors.append(f'{trace_name}: missing ordered event sequence: {formatted}')
    return errors


def validate_functional_invariants(records: list[dict], trace_name: str) -> list[str]:
    errors: list[str] = []
    fabric_failures = [
        record for record in records
        if record.get('dev') == 'fabric'
        and record.get('event') in {'READ', 'WRITE'}
        and record.get('status') not in {0, 'OK'}
    ]
    if fabric_failures:
        errors.append(f'{trace_name}: fabric READ/WRITE contains non-OK status')

    dma_failures = [
        record for record in records
        if record.get('dev') == 'DmaController(2ch)'
        and record.get('event') == 'CH_DONE'
        and record.get('ok') is not True
    ]
    if dma_failures:
        errors.append(f'{trace_name}: DMA completion contains ok != true')

    hsm_failures = [
        record for record in records
        if record.get('dev') == 'HSM'
        and record.get('event') == 'DONE'
        and record.get('ok') is not True
    ]
    if hsm_failures:
        errors.append(f'{trace_name}: HSM completion contains ok != true')

    probe_failures = [
        record for record in records
        if record.get('dev') == 'py_fabric_master'
        and record.get('event') in {'SV_PROBE_PASS', 'CRC_PROBE_PASS'}
        and record.get('result') in {None, False, 'FAIL', 'ERROR'}
    ]
    if probe_failures:
        errors.append(f'{trace_name}: Python fabric master probe result is not PASS')

    wdt_resets = [record for record in records if record.get('dev') == 'wdt' and record.get('event') == 'RESET']
    if wdt_resets and not any(record.get('reset_reason') == 1 for record in wdt_resets):
        errors.append(f'{trace_name}: WDT reset does not carry reset_reason == 1')
    return errors


def parse_required_event(value: str) -> tuple[str, str]:
    if ':' not in value:
        raise argparse.ArgumentTypeError('required event must use DEV:EVENT format')
    device, event = value.split(':', 1)
    if not device or not event:
        raise argparse.ArgumentTypeError('required event must use DEV:EVENT format')
    return device, event


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Check platform trace records against the initial trace contract.',
    )
    parser.add_argument('trace', type=Path, help='Path to device_trace.jsonl')
    parser.add_argument(
        '--require-event',
        action='append',
        default=[],
        type=parse_required_event,
        help='Require at least one event in DEV:EVENT format. May be repeated.',
    )
    parser.add_argument(
        '--profile',
        choices=sorted(PROFILE_REQUIRED_EVENTS),
        help='Apply a named built-in required-event profile.',
    )
    args = parser.parse_args()

    records = load_records(args.trace)
    required_events = list(args.require_event)
    required_sequences = []
    if args.profile:
        required_events.extend(PROFILE_REQUIRED_EVENTS[args.profile])
        required_sequences.extend(PROFILE_REQUIRED_SEQUENCES[args.profile])

    errors = []
    errors.extend(validate_common_contract(records, str(args.trace)))
    errors.extend(validate_required_events(records, required_events, str(args.trace)))
    errors.extend(validate_event_fields(records, str(args.trace)))
    errors.extend(validate_event_sequences(records, required_sequences, str(args.trace)))
    if args.profile:
        errors.extend(validate_functional_invariants(records, str(args.trace)))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f'{args.trace}: {len(records)} records OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())