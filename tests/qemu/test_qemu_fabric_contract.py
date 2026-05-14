from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MMIO_FABRIC_C = REPO_ROOT / 'scripts/qemu-fork/hw/misc/mmio_fabric.c'
MMIO_FABRIC_H = REPO_ROOT / 'scripts/qemu-fork/include/hw/misc/mmio_fabric.h'
MMIO_SOCKDEV_C = REPO_ROOT / 'scripts/qemu-fork/hw/misc/mmio_sockdev.c'

REQUIREMENTS = (
    'FAB-001',
    'FAB-005',
    'FAB-008',
    'TIME-001',
    'TIME-005',
    'IRQ-001',
    'IRQ-002',
    'RST-002',
    'TR-001',
    'TR-002',
    'TR-004',
)


def read_source(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def function_body(source: str, name: str) -> str:
    match = re.search(rf'\b{name}\s*\([^)]*\)\s*\{{', source)
    assert match, f'{name} function not found'
    start = match.end()
    depth = 1
    pos = start
    while pos < len(source) and depth:
        if source[pos] == '{':
            depth += 1
        elif source[pos] == '}':
            depth -= 1
        pos += 1
    assert depth == 0, f'{name} function body is not balanced'
    return source[start:pos - 1]


def test_requirement_ids_are_declared() -> None:
    assert all(requirement and '-' in requirement for requirement in REQUIREMENTS)


def test_qemu_fabric_api_exposes_absolute_address_master_id_contract() -> None:
    header = read_source(MMIO_FABRIC_H)

    assert 'MemTxAttrs mmio_fabric_attrs(uint8_t master_id)' in header
    assert 'MmioFabricResponse mmio_fabric_read(uint8_t master_id, hwaddr addr' in header
    assert 'MmioFabricStatus mmio_fabric_write(uint8_t master_id, hwaddr addr' in header
    assert 'MmioFabricStatus mmio_fabric_read_buf(uint8_t master_id, hwaddr addr' in header
    assert 'MmioFabricStatus mmio_fabric_write_buf(uint8_t master_id, hwaddr addr' in header


def test_qemu_fabric_preserves_requester_id_in_memtx_attrs() -> None:
    source = read_source(MMIO_FABRIC_C)
    body = function_body(source, 'mmio_fabric_attrs')

    assert '.requester_id = master_id' in body


def test_qemu_fabric_status_mapping_keeps_current_ok_error_contract() -> None:
    header = read_source(MMIO_FABRIC_H)
    source = read_source(MMIO_FABRIC_C)

    for status_name in (
        'MMIO_FABRIC_OK = 0',
        'MMIO_FABRIC_DECODE_ERROR = 1',
        'MMIO_FABRIC_ACCESS_ERROR = 2',
        'MMIO_FABRIC_SLAVE_ERROR = 3',
        'MMIO_FABRIC_TRANSPORT_ERROR = 4',
    ):
        assert status_name in header

    body = function_body(source, 'mmio_fabric_status_from_memtx')
    assert 'MEMTX_OK' in body
    assert 'MEMTX_DECODE_ERROR' in body
    assert 'MEMTX_ACCESS_ERROR' in body
    assert 'MEMTX_ERROR' in body

    ok_body = function_body(source, 'mmio_fabric_ok')
    assert 'status == MMIO_FABRIC_OK' in ok_body


def test_mmio_sockdev_rw_protocol_carries_master_id_offset_size_and_des_response() -> None:
    source = read_source(MMIO_SOCKDEV_C)
    read_body = function_body(source, 'mmio_sockdev_read')
    write_body = function_body(source, 'mmio_sockdev_write')

    assert "req[0] = 'R'" in read_body
    assert 'current_cpu->cpu_index' in read_body
    assert 'MASTER_ID_SYSCTRL' in read_body
    assert 'stl_le_p(req + 2, (uint32_t)offset)' in read_body
    assert 'req[6] = (uint8_t)size' in read_body

    assert "req[0] = 'W'" in write_body
    assert 'current_cpu->cpu_index' in write_body
    assert 'stl_le_p(req + 2, (uint32_t)offset)' in write_body
    assert 'qemu_chr_fe_read_all(&s->chr, resp, sizeof(resp))' in write_body
    assert 'ldq_le_p(resp)' in write_body


def test_mmio_sockdev_des_uses_qemu_virtual_time_and_one_shot_tick() -> None:
    source = read_source(MMIO_SOCKDEV_C)
    write_body = function_body(source, 'mmio_sockdev_write')
    tick_body = function_body(source, 'mmio_sockdev_tick_fire')
    event_body = function_body(source, 'mmio_sockdev_tick_chr_event')

    assert 'qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)' in write_body
    assert 'timer_mod(s->tick_timer, fire_ns)' in write_body
    assert "buf[0] = 'T'" in tick_body
    assert 'stq_le_p(buf + 1, vtime_ns)' in tick_body
    assert 'if (s->tick_period_ms > 0)' in tick_body
    assert 'tick_period_ms == 0' in event_body


def test_mmio_sockdev_fabric_protocol_parses_master_addr_len_and_returns_status() -> None:
    source = read_source(MMIO_SOCKDEV_C)
    parse_body = function_body(source, 'mmio_sockdev_parse_fabric_header')
    read_body = function_body(source, 'mmio_sockdev_fabric_read')
    write_body = function_body(source, 'mmio_sockdev_fabric_write')

    assert "rx->hdr[0] != 'F'" in parse_body
    assert "rx->op != 'R' && rx->op != 'W'" in parse_body
    assert 'rx->master_id = rx->hdr[2]' in parse_body
    assert 'rx->addr = ldq_le_p(rx->hdr + 4)' in parse_body
    assert 'rx->data_len = ldl_le_p(rx->hdr + 12)' in parse_body
    assert 'FABRIC_MAX_LEN' in parse_body

    assert 'mmio_fabric_read_buf(rx->master_id, rx->addr, resp' in read_body
    assert 'qemu_chr_fe_write_all(&s->fabric_chr, &ack, sizeof(ack))' in read_body
    assert 'mmio_fabric_write_buf(rx->master_id, rx->addr, rx->data_buf' in write_body
    assert 'mmio_fabric_ok(status) ? 0 : (uint8_t)status' in write_body


def test_mmio_sockdev_irq_and_reset_transport_contracts() -> None:
    source = read_source(MMIO_SOCKDEV_C)
    irq_body = function_body(source, 'mmio_sockdev_irq_receive')
    reset_body = function_body(source, 'mmio_sockdev_rst_receive')

    assert "s->irq_rxbuf[0] != 'I'" in irq_body
    assert 'uint8_t irq_idx = s->irq_rxbuf[1]' in irq_body
    assert 'uint8_t level   = s->irq_rxbuf[2]' in irq_body
    assert 'qemu_set_irq(s->irq[irq_idx], level ? 1 : 0)' in irq_body

    assert 'qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)' in reset_body