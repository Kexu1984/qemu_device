# Platform Requirement To Test Matrix

This matrix maps the requirements in `doc/platform_requirements.md` to the
first-phase test cases and future planned tests. Keep this file aligned with
`doc/platform_test_plan.md` and the test modules under `tests/`.

The acceptance focus is functional coverage. C/SV source contracts and optional
line/branch coverage can support review, but a requirement is considered strong
only when it has behavior-level evidence such as unit execution, transport
harness execution, e2e artifact checks, or trace event/sequence assertions.

## Status

| Status | Meaning |
|--------|---------|
| Implemented | Test exists in the repository and can be run now. |
| Partial | Some executable coverage exists, but additional cases are needed to close the requirement. |
| Planned | Test is defined in the test plan but not implemented yet. |
| Future | Depends on roadmap behavior or later infrastructure. |
| Evidence | Covered indirectly by existing e2e/demo evidence; should later become explicit. |

## Evidence Types

| Type | Meaning |
|------|---------|
| Unit | Focused executable unit behavior. |
| Transport | Socket/protocol harness behavior. |
| Contract | Source-level interface or integration contract. |
| E2E Artifact | Logs, VCD, reports, or firmware-visible integrated result. |
| Trace Sequence | Required events, fields, ordering, and success values in JSONL trace. |

## Matrix

| Requirement | Test Case | Status | Test Location | Notes |
|-------------|-----------|--------|---------------|-------|
| PLAT-GEN-001 | TC-TR-005 | Evidence | `scripts/e2e_test.sh` | e2e validates chip-functional behavior; not a cycle-accuracy proof. |
| PLAT-GEN-002 | TC-TR-005 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | Integrated transport coverage across QEMU, Python, SV, and firmware. |
| PLAT-GEN-003 | TC-FAB-002 | Planned | `tests/python/` | Generated/spec constant check still to be implemented. |
| PLAT-GEN-004 | TC-FAB-002 | Planned | `tests/python/` | Generated/spec constant check still to be implemented. |
| PLAT-GEN-005 | TC-FAB-010 | Implemented | `tests/run_platform_regression.sh`, `tests/e2e/test_e2e_artifacts.py`, `tests/trace/check_trace_requirements.py` | Fast, artifact, and full functional regression entry points exist. |
| FAB-001 | TC-FAB-001 | Implemented | `tests/python/test_fabric_channel.py` | Fabric frames carry op, master ID, absolute address, length, and data. |
| FAB-002 | TC-FAB-001, TC-FAB-003 | Implemented | `tests/python/test_peripheral_bus.py`, `tests/python/test_bus_master_address_space.py` | Absolute address at master/bus boundary; local offset after decode. |
| FAB-003 | TC-FAB-002 | Planned | `tests/python/` | Generated master ID validation. |
| FAB-004 | TC-FAB-003 | Implemented | `tests/python/test_bus_master_address_space.py` | Python bus-master routing through MMIO bus or fabric client. |
| FAB-005 | TC-FAB-005 | Implemented | `tests/qemu/test_qemu_fabric_contract.py` | QEMU-native helper contract coverage. |
| FAB-006 | TC-FAB-006 | Implemented | `tests/sv/test_sv_bridge_contract.py`, `scripts/e2e_test.sh` | SV master bridge contract plus existing e2e evidence. |
| FAB-007 | TC-FAB-003, TC-FAB-004 | Implemented | `tests/python/test_bus_master_address_space.py`, `tests/python/test_fabric_channel.py` | Single-channel ordering and chunk order. |
| FAB-008 | TC-FAB-007 | Future | `tests/trace/`, `tests/python/` | Current OK/ERROR only; richer statuses are roadmap. |
| FAB-009 | TC-FAB-007 | Future | `tests/trace/`, `tests/python/` | Unmapped/failure trace assertion. |
| FAB-010 | TC-FAB-004 | Implemented | `tests/python/test_fabric_channel.py` | Chunked transfer coverage. |
| FAB-011 | TC-FAB-009 | Future | generation test | Depends on generated decode/access-policy metadata. |
| FAB-012 | TC-FAB-008 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `tests/trace/check_trace_requirements.py`, `scripts/e2e_test.sh` | Python master to SV register e2e and trace profile with success-value checks. |
| FAB-013 | TC-FAB-006 | Implemented | `tests/sv/test_sv_bridge_contract.py`, `tests/e2e/test_e2e_artifacts.py`, `tests/trace/check_trace_requirements.py`, `scripts/e2e_test.sh` | SV master to memory bridge contract plus e2e artifact and trace-sequence evidence. |
| FAB-014 | TC-FAB-010 | Implemented | `tests/run_platform_regression.sh` | Broad functional regression rule has fast/artifact/full runner modes. |
| FAB-015 | TC-FAB-011 | Future | MPU tests | Depends on future system MPU. |
| TIME-001 | TC-TIME-001 | Implemented | `tests/qemu/test_qemu_fabric_contract.py`, `scripts/e2e_test.sh` | QEMU virtual-time calls protected by source contract; deterministic e2e uses `ICOUNT_SHIFT=5`. |
| TIME-002 | TC-TIME-001 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | Deterministic e2e artifact checks after `ICOUNT_SHIFT=5` run. |
| TIME-003 | TC-TIME-002 | Implemented | `tests/python/test_peripheral_bus.py` | Tick dispatch uses supplied `vtime_ns`. |
| TIME-004 | TC-TIME-002 | Implemented | `tests/python/test_peripheral_bus.py` | Periodic tick broadcast to devices and observers. |
| TIME-005 | TC-TIME-003 | Implemented | `tests/python/test_rw_server_protocol.py`, `tests/qemu/test_qemu_fabric_contract.py` | R/W write response returns DES `next_event_ns`; QEMU schedules on virtual time. |
| TIME-006 | TC-TIME-004 | Planned | `tests/python/` | Device-specific timer/DMA scheduled completion tests. |
| TIME-007 | TC-TIME-005 | Planned | static or pytest audit | Audit host-time use in timed chip behavior. |
| TIME-008 | TC-TIME-006 | Implemented | `tests/sv/test_sv_bridge_contract.py`, `scripts/e2e_test.sh`, SV wave | SV-local timing contract and e2e/wave evidence. |
| TIME-009 | TC-TIME-007 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `tests/trace/check_trace_requirements.py`, `scripts/e2e_test.sh` | Firmware wakeup through IRQ/timing events plus ordered DMA/WDT trace sequences. |
| TIME-010 | TC-TIME-008 | Implemented | `tests/python/test_tracer.py`, `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | Trace required fields, monotonic contract, ordered event sequences, and virtual timestamp handling. |
| TIME-011 | TC-TIME-009 | Implemented | `tests/sv/test_sv_bridge_contract.py` | SV-local cycle/tick source contract. |
| IRQ-001 | TC-IRQ-001 | Implemented | `tests/python/test_irq_controller.py` | IRQ frame format. |
| IRQ-002 | TC-IRQ-001 | Implemented | `tests/python/test_irq_controller.py` | Assert/deassert support. |
| IRQ-003 | TC-IRQ-003 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | Firmware-visible IRQ handling. |
| IRQ-004 | TC-IRQ-005 | Planned | `tests/trace/` | Secure boot/SYSCTRL no-CPU-IRQ assertion. |
| IRQ-005 | TC-IRQ-002 | Implemented | `tests/python/test_irq_controller.py` | Not-connected behavior. |
| IRQ-006 | TC-IRQ-004 | Implemented | `tests/sv/test_sv_bridge_contract.py`, `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | SV IRQ forwarding source contract plus e2e evidence. |
| IRQ-007 | TC-IRQ-003, TC-IRQ-004 | Evidence | `scripts/e2e_test.sh` | Needs explicit clear/deassert assertions. |
| IRQ-008 | TC-IRQ-006 | Implemented | `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | IRQ trace events and surrounding functional sequences covered in platform-smoke profile. |
| IRQ-009 | TC-IRQ-007 | Implemented | `tests/python/test_irq_controller.py` | Pulse as assert then deassert. |
| IRQ-010 | TC-IRQ-008 | Implemented | `tests/python/test_irq_controller.py` | Level-sensitive frame behavior covered at transport level; source-clear behavior remains device/e2e work. |
| RST-001 | TC-RST-001 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | WDT warm boot evidence. |
| RST-002 | TC-RST-001 | Implemented | `tests/qemu/test_qemu_fabric_contract.py`, `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | QEMU reset request contract plus e2e evidence. |
| RST-003 | TC-RST-001 | Evidence | `scripts/e2e_test.sh` | Needs focused unit coverage. |
| RST-004 | TC-RST-002 | Planned | `tests/python/`, e2e trace | Retention-focused tests. |
| RST-005 | TC-RST-003 | Future | `tests/python/`, e2e trace | Level-2 device reset access gating. |
| RST-006 | TC-RST-003 | Future | `tests/python/`, e2e trace | Device reset release values. |
| RST-007 | TC-RST-004 | Future | `tests/python/`, `tests/sv/` | Reset notification harness. |
| RST-008 | TC-RST-005 | Implemented | `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | WDT LOAD/ARM/KICK/TIMEOUT/RESET sequence and reset reason covered in platform-smoke profile. |
| RST-009 | TC-RST-006 | Partial | `tests/sv/test_sv_bridge_contract.py`, e2e | SV reset source contract exists; software-controlled device reset behavior still needs simulation/e2e case. |
| TR-001 | TC-TR-001, TC-TR-002 | Implemented | `tests/python/test_rw_server_protocol.py`, `tests/qemu/test_qemu_fabric_contract.py` | R/W read/write frame parsing and absolute address computation. |
| TR-002 | TC-TR-002 | Implemented | `tests/python/test_rw_server_protocol.py`, `tests/qemu/test_qemu_fabric_contract.py` | 8-byte DES response. |
| TR-003 | TC-TR-003 | Implemented | `tests/python/test_rw_server_protocol.py` | Unknown opcode closes client without bus access. |
| TR-004 | TC-FAB-001 | Implemented | `tests/python/test_fabric_channel.py`, `tests/qemu/test_qemu_fabric_contract.py`, `tests/sv/test_sv_bridge_contract.py` | Fabric frame fields across Python, QEMU, and SV host shell. |
| TR-005 | TC-FAB-004, TC-TR-004 | Implemented | `tests/python/test_fabric_channel.py` | Serialized chunk order; concurrent stress still planned. |
| TR-006 | TC-TR-003, TC-TR-004 | Partial | `tests/python/test_rw_server_protocol.py`, `tests/python/test_fabric_channel.py` | Malformed/short/disconnect cases need expansion. |
| OBS-001 | TC-OBS-001 | Implemented | `tests/python/test_tracer.py` | JSONL event output. |
| OBS-002 | TC-OBS-002 | Implemented | `tests/e2e/test_e2e_artifacts.py`, `scripts/e2e_test.sh` | HTML report generation artifact. |
| OBS-003 | TC-OBS-003 | Implemented | `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | Initial stable platform-smoke event and sequence profile. |
| OBS-004 | TC-OBS-004 | Implemented | `tests/python/test_tracer.py`, `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | Required fields, timestamps, event ordering, and success values. |
| OBS-005 | TC-OBS-003 | Implemented | `tests/trace/test_trace_requirements.py`, `tests/trace/check_trace_requirements.py` | Checker fails on missing required events. |
| OBS-006 | TC-OBS-005 | Partial | `tests/sv/test_sv_bridge_contract.py` | SV-local source contract exists; waveform/trace assertion still planned. |
| VER-001 | matrix maintenance | Implemented | `doc/platform_requirement_test_matrix.md` | Requirement-to-test mapping exists. |
| VER-002 | functional coverage first | Implemented | `doc/platform_test_plan.md`, `doc/platform_requirement_test_matrix.md` | Numeric Python coverage is optional diagnostic; functional evidence is the gate. |
| VER-003 | QEMU functional evidence | Partial | `tests/qemu/test_qemu_fabric_contract.py`, `tests/e2e/`, `tests/trace/` | Source contract plus e2e/trace evidence; qtest/C coverage optional if a gap remains. |
| VER-004 | SV functional evidence | Partial | `tests/sv/test_sv_bridge_contract.py`, `tests/e2e/`, `tests/trace/` | Source contract plus e2e/trace evidence; Verilator coverage optional if a gap remains. |
| VER-005 | trace/e2e assertions | Implemented | `tests/e2e/test_e2e_artifacts.py`, `tests/trace/check_trace_requirements.py` | e2e artifact and trace assertion framework. |
| VER-006 | coverage separation | Planned | reports | Separate firmware/platform coverage reporting. |
| VER-007 | test directory layout | Implemented | `tests/` | Repository-level test directory exists. |
| VER-008 | fabric regression runner | Implemented | `tests/run_platform_regression.sh` | Functional regression entry point exists with `fast`, `artifact`, and `full` modes. |

## First Phase Implemented Cases

The first committed framework covers representative L1/L2 behavior:

- `TC-FAB-001`: fabric frame construction.
- `TC-FAB-003`: Python bus-master routing.
- `TC-FAB-004`: fabric chunking and order.
- `TC-TIME-002`: virtual-time tick dispatch.
- `TC-TIME-003`: DES write response.
- `TC-IRQ-001`, `TC-IRQ-002`, `TC-IRQ-007`, `TC-IRQ-008`: IRQ transport frames and basic semantics.
- `TC-TR-001`, `TC-TR-002`, `TC-TR-003`: R/W protocol behavior.
- `TC-OBS-001`, `TC-OBS-003`, `TC-OBS-004`: trace output and trace checker framework.

## Second Phase Implemented Cases

The second framework expansion adds executable L3/L4 source contract coverage:

- `TC-FAB-005`: QEMU-native fabric helper API and requester ID contract.
- `TC-FAB-006`: SV master router and fabric egress contract.
- `TC-TIME-003`: QEMU DES scheduling contract.
- `TC-TIME-006`, `TC-TIME-009`: SV-local timing source contract.
- `TC-IRQ-004`: SV IRQ forwarding contract.
- `TC-RST-001`, `TC-RST-006`: QEMU reset request and SV reset source contract.
- `TC-TR-001`, `TC-TR-002`, `TC-FAB-001`: QEMU/SV transport frame contracts.

Next expansion should add generated-constant checks, timed device unit tests,
short-frame/disconnect protocol tests, qtest or host-buildable QEMU helper tests,
and Verilator simulation tests for SV APB/router/fabric behavior.

## Third Phase Implemented Cases

The third framework expansion adds offline L5/L6 artifact and trace assertion
coverage:

- `TC-TR-005`: e2e artifact checks for integrated QEMU/Python/SV/firmware behavior.
- `TC-TIME-007`: firmware-visible wakeup and timing/IRQ results in e2e logs.
- `TC-IRQ-003`, `TC-IRQ-004`: Python and SV IRQ evidence in e2e logs.
- `TC-RST-001`, `TC-RST-005`: WDT warm reset and ordered reset trace evidence.
- `TC-OBS-002`, `TC-OBS-003`, `TC-OBS-004`: trace report artifact, stable event profile, required trace fields, event sequences, and success values.

## Functional Coverage Direction

The current completion target is requirement-level functional evidence, not
numeric QEMU/SV branch coverage. The highest-value next cases are:

- Fabric error path: non-OK status, bad target, disconnect, and recovery.
- Timing determinism: repeated e2e trace sequence stability under `ICOUNT_SHIFT=5`.
- IRQ edge cases: pulse ordering and level-sensitive source-clear behavior.
- Reset edge cases: reset retention and CRU Level-2 device reset release behavior.
- E2E regeneration: CI or manual full runner proving artifacts came from the
	current source tree.

Next expansion should add the highest-value error-path scenarios and promote
more artifact-only evidence to trace-sequence evidence where stable event names
exist.