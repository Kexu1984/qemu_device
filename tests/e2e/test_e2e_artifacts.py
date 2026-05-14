from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_ROOT / 'build'
SERVER_LOG = BUILD_DIR / 'e2e_server.log'
UART_LOG = BUILD_DIR / 'e2e_uart.log'
SV_LOG = BUILD_DIR / 'e2e_sv_host_shell.log'
TRACE_JSONL = BUILD_DIR / 'device_trace.jsonl'
TRACE_HTML = BUILD_DIR / 'trace_report.html'
SV_WAVE = BUILD_DIR / 'e2e_sv_host_shell.vcd'

REQUIREMENTS = (
    'PLAT-GEN-002',
    'PLAT-GEN-005',
    'FAB-012',
    'FAB-013',
    'TIME-002',
    'TIME-009',
    'IRQ-003',
    'IRQ-006',
    'RST-001',
    'RST-002',
    'OBS-002',
    'VER-005',
)

SERVER_REQUIRED = (
    'MMIO SockDev Interrupt Demo',
    'UART interrupt handled successfully',
    'DMA] Verification PASSED',
    'DMA-CRC] Result 0xCBF43926 PASSED',
    'Dual-CPU IPC PASS',
    'Dual-master MMIO PASS',
    'Python master SV register access PASSED',
    'SV timer fired',
    'SV DMA M2M copy PASSED',
    'SV GPIO ID GPIO PASSED',
    'HSM AES-CMAC PASSED',
    'OTP] HSM OTP KEY_ID0 AES-CBC PASSED',
    'SYSCTRL] SECURE_BOOT CMAC PASSED',
    'SYSCTRL] DEVCTL UART STATUS read PASSED',
    'WDT] TIMEOUT',
    'Warm boot detected: RESET_REASON=WDT',
    'WDT demo complete',
)

UART_REQUIRED = (
    'MMIO SockDev Interrupt Demo',
    'KX6625 Test Menu',
    'UART interrupt handled successfully',
    'All tests done',
    'Dual-master MMIO PASS',
    'SV DMA M2M copy PASSED',
    'HSM AES-CMAC PASSED',
    'Warm boot detected: RESET_REASON=WDT',
)

SV_REQUIRED = (
    'RW channel connected',
    'IRQ channel connected',
    'fabric channel connected',
    'IRQ assert',
    'IRQ deassert',
    'FABRIC READ',
    'FABRIC WRITE',
    'OK',
)


def read_required(path: Path) -> str:
    if not path.exists():
        pytest.skip(f'{path} is not available; run ICOUNT_SHIFT=5 bash scripts/e2e_test.sh first')
    return path.read_text(encoding='utf-8', errors='replace')


def assert_contains_all(text: str, required: tuple[str, ...]) -> None:
    missing = [needle for needle in required if needle not in text]
    assert not missing, f'missing expected strings: {missing}'


def test_e2e_server_log_covers_core_platform_use_cases() -> None:
    assert_contains_all(read_required(SERVER_LOG), SERVER_REQUIRED)


def test_e2e_uart_log_captures_firmware_visible_results() -> None:
    assert_contains_all(read_required(UART_LOG), UART_REQUIRED)


def test_e2e_sv_host_shell_log_covers_sv_irq_and_fabric_paths() -> None:
    assert_contains_all(read_required(SV_LOG), SV_REQUIRED)


def test_e2e_artifacts_include_trace_report_trace_jsonl_and_sv_wave() -> None:
    for artifact in (TRACE_JSONL, TRACE_HTML, SV_WAVE):
        if not artifact.exists():
            pytest.skip(f'{artifact} is not available; run ICOUNT_SHIFT=5 bash scripts/e2e_test.sh first')
        assert artifact.stat().st_size > 0