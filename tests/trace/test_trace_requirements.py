from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from check_trace_requirements import (
    PROFILE_REQUIRED_EVENTS,
    PROFILE_REQUIRED_SEQUENCES,
    validate_common_contract,
    validate_event_fields,
    validate_event_sequences,
    validate_functional_invariants,
    validate_required_events,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / 'tests/trace/check_trace_requirements.py'
BUILD_TRACE = REPO_ROOT / 'build/device_trace.jsonl'

REQUIREMENTS = (
    'OBS-003',
    'OBS-004',
    'OBS-005',
    'TIME-010',
    'FAB-012',
    'FAB-013',
    'IRQ-008',
    'RST-008',
)


def write_trace(path: Path, records: list[dict]) -> None:
    path.write_text('\n'.join(json.dumps(record) for record in records) + '\n', encoding='utf-8')


def minimal_record(seq: int, dev: str, event: str, **extra) -> dict:
    record = {
        'seq': seq,
        't_wall_ns': seq * 10,
        't_virt_ns': seq * 100,
        'dev': dev,
        'event': event,
    }
    record.update(extra)
    return record


def test_common_trace_contract_accepts_monotonic_records() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'fabric', 'READ', master_id=0x13, addr=0x4000, size=4, status=0, target='sv'),
    ]

    assert validate_common_contract(records, 'unit') == []


def test_common_trace_contract_rejects_missing_header_and_nonmonotonic_seq() -> None:
    records = [
        minimal_record(1, 'fabric', 'READ'),
        minimal_record(1, 'fabric', 'WRITE'),
    ]

    errors = validate_common_contract(records, 'unit')
    assert any('first record is not the tracer HEADER' in error for error in errors)
    assert any('seq is not strictly increasing' in error for error in errors)


def test_required_event_validation_reports_missing_events() -> None:
    records = [minimal_record(0, '__tracer__', 'HEADER')]

    errors = validate_required_events(records, [('fabric', 'READ')], 'unit')
    assert errors == ['unit: missing required events: fabric:READ']


def test_event_field_validation_checks_stable_event_contract() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'fabric', 'READ', master_id=0x13),
    ]

    errors = validate_event_fields(records, 'unit')
    assert any('fabric:READ is missing required fields' in error for error in errors)


def test_platform_smoke_profile_is_not_empty() -> None:
    assert PROFILE_REQUIRED_EVENTS['platform-smoke']
    assert PROFILE_REQUIRED_SEQUENCES['platform-smoke']
    assert ('fabric', 'READ') in PROFILE_REQUIRED_EVENTS['platform-smoke']
    assert ('wdt', 'TIMEOUT') in PROFILE_REQUIRED_EVENTS['platform-smoke']


def test_event_sequence_validation_accepts_ordered_subsequence() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'noise', 'A'),
        minimal_record(2, 'DmaController(2ch)', 'CH_START'),
        minimal_record(3, 'noise', 'B'),
        minimal_record(4, 'DmaController(2ch)', 'CH_DONE'),
        minimal_record(5, 'DmaController(2ch)', 'IRQ_PULSE'),
    ]

    assert validate_event_sequences(
        records,
        [[('DmaController(2ch)', 'CH_START'), ('DmaController(2ch)', 'CH_DONE'), ('DmaController(2ch)', 'IRQ_PULSE')]],
        'unit',
    ) == []


def test_event_sequence_validation_rejects_missing_ordered_step() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'DmaController(2ch)', 'CH_START'),
        minimal_record(2, 'DmaController(2ch)', 'IRQ_PULSE'),
    ]

    errors = validate_event_sequences(
        records,
        [[('DmaController(2ch)', 'CH_START'), ('DmaController(2ch)', 'CH_DONE'), ('DmaController(2ch)', 'IRQ_PULSE')]],
        'unit',
    )
    assert any('missing ordered event sequence' in error for error in errors)


def test_functional_invariants_accept_platform_success_records() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'fabric', 'READ', status='OK'),
        minimal_record(2, 'fabric', 'WRITE', status='OK'),
        minimal_record(3, 'DmaController(2ch)', 'CH_DONE', ok=True),
        minimal_record(4, 'HSM', 'DONE', ok=True),
        minimal_record(5, 'py_fabric_master', 'SV_PROBE_PASS', result='0x414d4453'),
        minimal_record(6, 'wdt', 'RESET', reset_reason=1),
    ]

    assert validate_functional_invariants(records, 'unit') == []


def test_functional_invariants_reject_failed_platform_results() -> None:
    records = [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'fabric', 'READ', status=1),
        minimal_record(2, 'DmaController(2ch)', 'CH_DONE', ok=False),
        minimal_record(3, 'HSM', 'DONE', ok=False),
        minimal_record(4, 'py_fabric_master', 'SV_PROBE_PASS', result='FAIL'),
        minimal_record(5, 'wdt', 'RESET', reset_reason=0),
    ]

    errors = validate_functional_invariants(records, 'unit')
    assert any('fabric READ/WRITE contains non-OK status' in error for error in errors)
    assert any('DMA completion contains ok != true' in error for error in errors)
    assert any('HSM completion contains ok != true' in error for error in errors)
    assert any('Python fabric master probe result is not PASS' in error for error in errors)
    assert any('WDT reset does not carry reset_reason == 1' in error for error in errors)


def test_trace_checker_cli_accepts_required_event(tmp_path) -> None:
    trace_path = tmp_path / 'trace.jsonl'
    write_trace(trace_path, [
        minimal_record(0, '__tracer__', 'HEADER'),
        minimal_record(1, 'fabric', 'READ', master_id=0x13, addr=0x4000, size=4, status=0, target='sv'),
    ])

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(trace_path), '--require-event', 'fabric:READ'],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert 'records OK' in result.stdout


def test_existing_build_trace_satisfies_platform_smoke_profile_when_available() -> None:
    if not BUILD_TRACE.exists():
        pytest.skip('build/device_trace.jsonl is not available; run scripts/e2e_test.sh first')

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(BUILD_TRACE), '--profile', 'platform-smoke'],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr