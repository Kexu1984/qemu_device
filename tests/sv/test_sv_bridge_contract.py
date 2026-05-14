from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SV_DIR = REPO_ROOT / 'sv_device'

SV_APB_INGRESS = SV_DIR / 'sv_apb_ingress.sv'
SV_MASTER_ROUTER = SV_DIR / 'sv_master_router.sv'
SV_FABRIC_EGRESS = SV_DIR / 'sv_fabric_egress_dpi.sv'
SV_DEVICE_TOP = SV_DIR / 'sv_device_top.sv'
SV_HOST_SHELL = SV_DIR / 'sv_host_shell.cpp'
SV_MAKEFILE = SV_DIR / 'Makefile'

REQUIREMENTS = (
    'FAB-001',
    'FAB-006',
    'FAB-013',
    'TIME-008',
    'TIME-011',
    'IRQ-006',
    'RST-009',
)


def read_source(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def module_body(source: str, name: str) -> str:
    match = re.search(rf'\bmodule\s+{name}\b', source)
    assert match, f'{name} module not found'
    end = source.find('endmodule', match.end())
    assert end != -1, f'{name} endmodule not found'
    return source[match.start():end]


def test_requirement_ids_are_declared() -> None:
    assert all(requirement and '-' in requirement for requirement in REQUIREMENTS)


def test_sv_apb_ingress_owns_host_to_apb_setup_access_fsm() -> None:
    body = module_body(read_source(SV_APB_INGRESS), 'sv_apb_ingress')

    for state in ('ST_IDLE', 'ST_SETUP', 'ST_ACCESS'):
        assert state in body
    assert 'assign host_req_ready_o = (state_q == ST_IDLE)' in body
    assert 'assign psel_o = (state_q == ST_SETUP) || (state_q == ST_ACCESS)' in body
    assert 'assign penable_o = (state_q == ST_ACCESS)' in body
    assert 'host_rsp_error_o <= pslverr_i || (size_q != 3\'b010)' in body


def test_sv_master_router_routes_local_sv_window_and_external_fabric() -> None:
    body = module_body(read_source(SV_MASTER_ROUTER), 'sv_master_router')

    assert "SV_ISLAND_BASE = 32'h4000_B000" in body
    assert "SV_ISLAND_MASK = 32'hFFFF_F000" in body
    assert 'local_sel' in body
    assert 'local_psel_o' in body
    assert 'assign ext_req_valid_o = req_valid_i && !local_sel' in body


def test_sv_fabric_egress_dpi_enforces_32bit_request_response_contract() -> None:
    source = read_source(SV_FABRIC_EGRESS)
    body = module_body(source, 'sv_fabric_egress_dpi')

    assert 'import "DPI-C" function longint unsigned sv_fabric_read32' in source
    assert 'import "DPI-C" function int sv_fabric_write32' in source
    assert "localparam logic [2:0] SIZE_32 = 3'b010" in body
    assert 'req_ready_o = (state_q == ST_IDLE)' in body
    assert 'req_size_i != SIZE_32' in body
    assert 'sv_fabric_write32(req_addr_i, req_wdata_i)' in body
    assert 'sv_fabric_read32(req_addr_i)' in body
    assert 'rsp_error_q <= |read_result[63:32]' in body


def test_sv_device_top_wires_ingress_decoder_slaves_router_egress_and_irq() -> None:
    body = module_body(read_source(SV_DEVICE_TOP), 'sv_device_top')

    for instance in (
        'sv_apb_ingress u_apb_ingress',
        'sv_apb_decoder u_apb_decoder',
        'sv_timer_apb u_timer',
        'sv_dma_apb u_dma',
        'sv_gpio_apb u_gpio',
        'sv_spi_tx_apb u_spi_tx',
        'sv_master_router u_master_router',
        'sv_fabric_egress_dpi u_fabric_egress',
    ):
        assert instance in body
    assert 'assign irq_o = timer_irq | dma_irq | gpio_irq | spi_irq' in body
    assert 'spi_dma_req' in body
    assert '.spi_req_i     (spi_dma_req)' in body
    assert '.dma_req_o (spi_dma_req)' in body
    assert '.local_psel_o    (fabric_psel)' in body


def test_sv_host_shell_fabric_frames_use_sv_dma_master_id_and_le32_accesses() -> None:
    source = read_source(SV_HOST_SHELL)

    assert 'constexpr uint8_t kSvDmaMasterId = 0x20' in source
    assert "hdr[0] = 'F'" in source
    assert "hdr[1] = 'R'" in source
    assert 'hdr[2] = kSvDmaMasterId' in source
    assert 'store_le32(hdr + 12, 4)' in source
    assert "pkt[0] = 'F'" in source
    assert "pkt[1] = 'W'" in source
    assert 'pkt[2] = kSvDmaMasterId' in source
    assert 'store_le32(pkt + 16, value)' in source
    assert 'return ok ? 1 : 0' in source


def test_sv_host_shell_local_time_irq_and_reset_behavior_are_explicit() -> None:
    source = read_source(SV_HOST_SHELL)

    assert 'constexpr uint32_t kIdleCyclesPerPoll = 16' in source
    assert 'bridge.run_cycles(kIdleCyclesPerPoll)' in source
    assert 'dut_->rst_n = 0' in source
    assert 'dut_->rst_n = 1' in source
    assert "uint8_t msg[3] = {'I', 0, static_cast<uint8_t>(level ? 1 : 0)}" in source
    assert 'if (irq_now != last_irq)' in source


def test_sv_makefile_builds_expected_bridge_top_with_trace_enabled() -> None:
    source = read_source(SV_MAKEFILE)

    assert '--top-module sv_device_top' in source
    assert '--trace' in source
    assert 'sv_fabric_egress_dpi.sv' in source
    assert 'sv_spi_tx_apb.sv' in source
    assert 'sv_dma_core.sv' in source
    assert 'sv_dma_m2p_core.sv' not in source
    assert 'sv_master_router.sv' in source
    assert 'sv_apb_ingress.sv' in source
    assert 'sv_host_shell.cpp' in source