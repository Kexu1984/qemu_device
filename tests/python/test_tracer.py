from __future__ import annotations

import json

from device_model.tracer import Tracer


REQUIREMENTS = (
    'OBS-001',
    'TIME-010',
)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_tracer_writes_header_and_device_events_with_required_fields(tmp_path) -> None:
    trace_path = tmp_path / 'device_trace.jsonl'
    tracer = Tracer(str(trace_path), flush_every=1)
    device_trace = tracer.context('timer0')

    device_trace.tick(123_000)
    device_trace.emit('EXPIRE', irq_idx=2)
    tracer.close()

    records = read_jsonl(trace_path)
    assert records[0]['dev'] == '__tracer__'
    assert records[0]['event'] == 'HEADER'
    assert records[1]['dev'] == 'timer0'
    assert records[1]['event'] == 'EXPIRE'
    assert records[1]['t_virt_ns'] == 123_000
    assert records[1]['irq_idx'] == 2

    for record in records:
        assert {'seq', 't_wall_ns', 't_virt_ns', 'dev', 'event'} <= set(record)


def test_tracer_explicit_virtual_time_override(tmp_path) -> None:
    trace_path = tmp_path / 'device_trace.jsonl'
    tracer = Tracer(str(trace_path), flush_every=1)
    device_trace = tracer.context('dma')

    device_trace.tick(100)
    device_trace.emit('COMPLETE', t_virt_ns_override=512)
    tracer.close()

    records = read_jsonl(trace_path)
    assert records[1]['event'] == 'COMPLETE'
    assert records[1]['t_virt_ns'] == 512