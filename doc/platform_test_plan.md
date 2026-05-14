# Simulation Platform Core Test Plan

This document proposes requirement-based test coverage for the simulation
platform core described in `doc/platform_requirements.md`.

The purpose is to raise confidence in fabric, timing/event, IRQ, reset,
transport, and trace behavior across QEMU C, Python, and SystemVerilog code.
It is intentionally separate from firmware/MCAL coverage.

The requirement-to-test mapping is maintained in
`doc/platform_requirement_test_matrix.md`.

## 1. Functional Coverage Strategy

The current end-to-end smoke test is valuable, but it is broad. It proves that
many flows work together, while leaving gaps in negative cases, protocol edge
cases, and per-module requirement coverage.

The priority is functional coverage: every platform-core requirement should
eventually have executable evidence that the required behavior occurs. Evidence
can be a focused unit test, a transport harness test, an integrated e2e result,
or a trace event/sequence assertion. C/SV line and branch coverage are useful
diagnostics, but they are not the completion criterion for this platform stage.

Recommended functional evidence layers:

| Layer | Scope | Example tools | Purpose |
|-------|-------|---------------|---------|
| L0 Static checks | Python, shell, docs, generated constants | `python -m compileall`, shellcheck, markdown review | Catch syntax and simple integration errors early |
| L1 Python unit tests | `device_model/mmio_base.py`, `mmio_device_server.py`, tracer helpers | `pytest` | Exercise fabric clients, bus decode, tick dispatch, protocol parsing without QEMU |
| L2 Transport harness tests | TCP R/W, IRQ, tick, fabric, reset protocol servers | Python socket test harness | Exercise short frames, disconnects, malformed opcodes, DES response, large transfers |
| L3 QEMU functional evidence | `mmio_fabric.c`, `mmio_sockdev.c`, SYSCTRL/CRU paths | source contract tests, focused e2e, trace sequences, qtest only where practical | Prove C-side transaction, requester ID, reset, IRQ, and tick plumbing behavior |
| L4 SV functional evidence | APB ingress, APB decoder, SV master router, fabric egress, IRQ forwarding | source contract tests, existing `sv_host_shell`, waveform/artifact checks, Verilator only where practical | Prove RTL bridge behavior without making branch coverage a gate |
| L5 End-to-end regression | Full QEMU + Python + SV + firmware | `ICOUNT_SHIFT=5 bash scripts/e2e_test.sh`, `python3 -m pytest tests/e2e` | Prove integrated behavior and requirement-level observable evidence |
| L6 Trace assertions | `build/device_trace.jsonl` | `tests/trace/check_trace_requirements.py`, `python3 -m pytest tests/trace` | Verify required platform events and ordering, not only log strings |

Requirement coverage is the primary metric. For each core requirement, the
matrix should identify one or more evidence types: `Unit`, `Transport`,
`Contract`, `E2E Artifact`, or `Trace Sequence`. Line and branch coverage can
help find untested code, especially in Python infrastructure, but they do not
replace functional evidence.

Regression scope depends on the touched module. Fabric core changes are broad
platform changes and should run QEMU C, Python, SV, e2e, and trace assertion
coverage. Firmware-only or device-only changes may run the targeted tests that
map to the affected requirements.

Implementation should be staged. The first phase builds the test-use-case
framework and implements L1/L2 tests because they are fast, local, and good at
shaping the harness. Later phases add L3/L4 functional evidence, L5 e2e artifact
checks, and L6 trace event/sequence assertions as stable QEMU/SV/trace
infrastructure becomes available.

## 2. Current Coverage Assessment

| Area | Current evidence | Main gap |
|------|------------------|----------|
| CPU to Python MMIO | e2e firmware demos and Python server logs | Limited protocol negative tests |
| Python bus-master to memory | DMA/HSM/flash style e2e flows | Limited unit tests for large transfers, disconnects, response errors |
| Python master to SV register | e2e string `Python master SV register access PASSED` | Needs trace/assertion and negative cases |
| SV master to memory | e2e string `SV DMA M2M copy PASSED` | Needs SV-level router/fabric egress tests |
| Timing/DES | DMA/timer/WDT e2e behavior | Needs direct tests for DES values, periodic tick dispatch, no host-time dependency |
| IRQ | UART, timer, SV timer, GPIO, WDT style e2e behavior | Needs assert/deassert/clear tests and disconnected-channel behavior |
| Reset | WDT warm boot e2e, reset architecture doc | Needs Level-2 CRU device reset tests and trace checks |
| Trace | HTML report generation | Needs automated trace event assertions |
| QEMU C helpers | Source contract tests and full e2e path | Needs only focused dynamic functional cases where source contracts plus trace evidence are insufficient |

## 3. Test Case Status

Status values used below:

| Status | Meaning |
|--------|---------|
| Existing partial | Covered indirectly by current e2e logs or demos, but not requirement-specific enough. |
| Proposed | New test recommended. |
| Future | Depends on target behavior or design decision not fully implemented yet. |

## 4. Fabric Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-FAB-001 | FAB-001, FAB-002, TR-004 | Proposed | L1/L2 | Unit-test fabric read/write frame construction with master ID, absolute address, length, and payload. | pytest result and coverage report |
| TC-FAB-002 | FAB-003, PLAT-GEN-004 | Proposed | L0/L1 | Verify generated master ID constants exist and are imported by Python fabric users without hard-coded fallback in normal generated builds. | pytest or generation check |
| TC-FAB-003 | FAB-004, FAB-007 | Proposed | L1 | Use a fake bus and fake fabric channel to prove `BusMasterAddressSpace` routes MMIO ranges in-process and memory ranges through fabric while preserving order. | pytest result |
| TC-FAB-004 | FAB-010, TR-005 | Proposed | L1 | Request a transfer larger than `_max_transfer` and assert chunk addresses, lengths, ordering, and failure propagation. | pytest result |
| TC-FAB-005 | FAB-005 | Proposed | L3 | Exercise QEMU-native fabric helper read/write with a requester ID and verify target sees the expected master. | qtest/host test or focused e2e trace |
| TC-FAB-006 | FAB-006, FAB-013 | Existing partial | L4/L5/L6 | Run SV DMA M2M copy and assert SV master transaction evidence in logs and trace, not only firmware success string. | e2e plus trace checker |
| TC-FAB-007 | FAB-008, FAB-009 | Future | L2/L5 | Access unmapped fabric address and assert current OK/ERROR behavior plus trace/log evidence; richer decode-error status is roadmap. | protocol test and trace checker |
| TC-FAB-008 | FAB-012 | Existing partial | L5 | Python master reads/writes an SV register through the fabric path and verifies data. | e2e plus trace checker |
| TC-FAB-009 | FAB-011 | Future | L0 | Validate generated decode/access-policy metadata from `spec/` once decode metadata is generated. | generation test |
| TC-FAB-010 | FAB-014, VER-008 | Proposed | L5/L6 | For any fabric core change, run the cross-domain functional regression set: Python master path, SV master path, e2e artifacts, and trace sequence assertions. | regression runner |
| TC-FAB-011 | FAB-015 | Future | L3/L5 | When system MPU exists, assert access-denial behavior through MPU policy rather than ad hoc per-device checks. | MPU policy test |

## 5. Timing And Event Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-TIME-001 | TIME-001, TIME-002 | Existing partial | L5 | Run deterministic e2e with `ICOUNT_SHIFT=5` and assert timing-sensitive demos pass. | e2e log |
| TC-TIME-002 | TIME-003, TIME-004 | Proposed | L1 | Call `PeripheralBus.tick_all(vtime_ns)` with fake devices and assert all devices/observers receive the same absolute timestamp. | pytest result |
| TC-TIME-003 | TIME-005, TR-002 | Proposed | L2 | Send a write frame to an RWServer-backed fake device returning `next_event_ns` and assert the 8-byte response. | socket harness test |
| TC-TIME-004 | TIME-006 | Proposed | L1 | For timer/DMA model unit tests, assert write arms pending state and completion only occurs after `on_tick()` reaches the scheduled virtual timestamp. | pytest result |
| TC-TIME-005 | TIME-007 | Proposed | L1 | Audit timed Python devices with a static/unit check that modeled time comes from `vtime_ns` inputs rather than host `time.time()` for chip behavior. | static check or pytest |
| TC-TIME-006 | TIME-008 | Existing partial | L4/L5 | Exercise SV timer and assert it advances by SV-local behavior while docs/tests avoid CPU-cycle accuracy claims. | SV test or e2e plus waveform |
| TC-TIME-007 | TIME-009 | Existing partial | L5 | Firmware waits for DMA/timer/WDT event and wakes through virtual-time event or IRQ. | e2e log and trace |
| TC-TIME-008 | TIME-010, OBS-003 | Proposed | L6 | Assert trace contains timer/DMA/WDT timing events with QEMU virtual timestamps, monotonic sequence numbers, and representative ordered event sequences. | trace checker |
| TC-TIME-009 | TIME-011, OBS-006 | Proposed | L4/L6 | Assert SV-local tests or waveforms report SV cycle/tick evidence without requiring correlation to QEMU virtual time. | SV test or waveform check |

## 6. IRQ Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-IRQ-001 | IRQ-001, IRQ-002 | Proposed | L1/L2 | Use a socketpair or fake socket to assert `IRQController.set_irq()` sends `I, irq_idx, level` for assert and deassert. | pytest result |
| TC-IRQ-002 | IRQ-005 | Proposed | L1 | Call `set_irq()` before connection and assert it returns false without throwing. | pytest result |
| TC-IRQ-003 | IRQ-003, IRQ-007 | Existing partial | L5 | Validate UART/timer/GPIO IRQ handled by firmware and cleared by device-specific status/clear path. | e2e log plus trace |
| TC-IRQ-004 | IRQ-006, IRQ-007 | Existing partial | L4/L5 | Validate SV timer or GPIO IRQ forwards through SV host shell to QEMU NVIC and firmware observes it. | e2e log, SV log, trace |
| TC-IRQ-005 | IRQ-004 | Proposed | L5/L6 | Secure boot/SYSCTRL pre-CPU flow completes through status bits and does not require a CPU IRQ. | e2e trace/status assertion |
| TC-IRQ-006 | IRQ-008 | Proposed | L6 | Trace checker validates source device, IRQ number, timestamp, and ordered surrounding events for representative Python and SV IRQ events. | trace checker |
| TC-IRQ-007 | IRQ-009 | Proposed | L1/L5 | Test pulse IRQ as `level=1` followed by `level=0`; prove firmware or a harness can observe the pulse reliably. | pytest/e2e result |
| TC-IRQ-008 | IRQ-010 | Proposed | L1/L5 | Test level-sensitive IRQ remains asserted until firmware or harness clears the source register, then deasserts. | pytest/e2e result |

## 7. Reset Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-RST-001 | RST-001, RST-002, RST-003, RST-004 | Existing partial | L5 | WDT triggers system reset; firmware observes warm boot retention state. | e2e log |
| TC-RST-002 | RST-004 | Proposed | L1/L5 | Unit or e2e test proves volatile registers reset while documented retention registers survive system reset. | pytest/e2e trace |
| TC-RST-003 | RST-005, RST-006 | Future | L2/L5 | Assert CRU Level-2 device reset blocks access while asserted and returns reset values on release. | focused e2e and trace |
| TC-RST-004 | RST-007 | Future | L2/L4 | Send CRU device-reset notifications to Python and SV backends without firmware and assert backend state transitions. | socket/SV harness |
| TC-RST-005 | RST-008 | Proposed | L6 | Trace checker validates reset source, ordered WDT timeout-to-reset sequence, and reset reason. | trace checker |
| TC-RST-006 | RST-009 | Proposed | L4/L5 | Keep an SV device in software-controlled reset until firmware writes the release register sequence; assert normal register/IRQ behavior is blocked before release and works after release. | SV/e2e result |

## 8. Transport Protocol Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-TR-001 | TR-001 | Proposed | L2 | Send a valid read frame to RWServer and assert base+offset address, master ID propagation, and response bytes. | socket harness test |
| TC-TR-002 | TR-001, TR-002 | Proposed | L2 | Send a valid write frame and assert payload, master ID, absolute address, and DES response. | socket harness test |
| TC-TR-003 | TR-003, TR-006 | Proposed | L2 | Send unknown opcode, short header, and disconnect mid-frame; assert server exits client cleanly and remains available. | socket harness test |
| TC-TR-004 | TR-004, TR-005, TR-006 | Proposed | L2 | Send concurrent fabric read/write requests through serialized API and assert no interleaved responses. | pytest/socket test |
| TC-TR-005 | PLAT-GEN-002 | Existing partial | L5 | Full e2e validates R/W, IRQ, tick, fabric, reset, terminal, and SV bridge channels in one run. | e2e log |

## 9. Observability Test Cases

| Test ID | Requirements | Status | Level | Test idea | Evidence |
|---------|--------------|--------|-------|-----------|----------|
| TC-OBS-001 | OBS-001 | Proposed | L1 | Unit-test tracer with multiple event producers and assert JSONL records are valid and non-blocking behavior is preserved. | pytest result |
| TC-OBS-002 | OBS-002 | Existing partial | L5 | e2e generates `build/trace_report.html` from `build/device_trace.jsonl`. | e2e log |
| TC-OBS-003 | OBS-003, OBS-005 | Proposed | L6 | Add a trace assertion script that fails if required event names or required event sequences are missing. | trace checker |
| TC-OBS-004 | OBS-004 | Proposed | L6 | Assert representative fabric/IRQ/reset/timing trace events include required fields and success values, including QEMU virtual time when available and host wall time when useful. | trace checker |
| TC-OBS-005 | OBS-006 | Proposed | L4/L6 | Assert SV-local waveform or trace evidence includes SV cycle/tick information for SV-local behavior. | SV test or waveform check |

## 10. Suggested Test Artifacts

The following files or directories are proposed. Names can change during
implementation review.

| Artifact | Purpose |
|----------|---------|
| `tests/python/test_peripheral_bus.py` | Unit tests for address decode, tick dispatch, and unmapped behavior. |
| `tests/python/test_fabric_channel.py` | Unit/socket tests for fabric frame construction, chunking, status handling, disconnects. |
| `tests/python/test_rw_server_protocol.py` | Socket harness tests for R/W protocol, DES response, malformed frames. |
| `tests/python/test_irq_controller.py` | IRQ assert/deassert and not-connected behavior. |
| `tests/python/test_tracer.py` | Trace JSONL validity and required field behavior. |
| `tests/e2e/test_e2e_artifacts.py` | Offline checks for e2e logs, trace report, and SV wave artifacts. |
| `tests/trace/check_trace_requirements.py` | Requirement-level assertions over `build/device_trace.jsonl`. |
| `tests/sv/` | SV bridge contract tests and optional dynamic APB/router/fabric tests where they add functional evidence. |
| `tests/qemu/` or qtest integration | Focused QEMU-native helper and `mmio-sockdev` behavior tests only where e2e/trace evidence leaves a functional gap. |
| `tests/run_platform_regression.sh` | Unified fast, artifact, and full functional regression entry point. |

## 11. Proposed Commands

Fast local platform checks:

```bash
bash tests/run_platform_regression.sh fast
```

Artifact-only e2e evidence check after an existing e2e run:

```bash
bash tests/run_platform_regression.sh artifact
```

Integrated deterministic functional regression:

```bash
bash tests/run_platform_regression.sh full
```

Optional coverage-oriented Python diagnostic run:

```bash
python3 -m coverage run -m pytest tests/python
python3 -m coverage report --show-missing
```

QEMU C and SV branch/line coverage are intentionally not gates for this stage.
If later needed, practical options include qtest for QEMU-native paths,
gcov/lcov for selected C helper builds, and Verilator coverage for SV bridge
tests. These should still map back to functional requirements before numeric
coverage is used as acceptance evidence.

## 12. Implementation Plan

The review decisions for the first testing roadmap are:

1. Build tests by phase. Start with L1 Python unit tests and L2 transport
   harness tests. Add L3 QEMU-native tests, L4 SV/Verilator tests, L5 e2e
   checks, and L6 trace assertions progressively.
2. Increase requirement coverage gradually. The first goal is a usable test-use-
   case framework with representative cases, then a steady expansion of covered
   requirements and corner cases.
3. Use trace/event assertions as pass criteria once stable event names and
   required fields exist. This is more reliable than depending only on firmware
   log strings.
4. Set an achievable first functional-coverage target. Start by ensuring every
   core happy path has unit, e2e artifact, or trace-sequence evidence. Add
   error-path and boundary scenarios before chasing line/branch coverage.
5. Use QEMU/SV branch or line coverage only as a diagnostic follow-up. The next
   investment should be trace sequence assertions and e2e regeneration, because
   they directly prove platform behavior across domains.

## 13. Remaining Review Questions

1. Which remaining requirements should be promoted from artifact evidence to
   trace-sequence evidence first?
2. Which error paths should enter the first functional coverage gate: fabric
   failure, disconnect, IRQ edge cases, reset retention, or timing determinism?
3. Which tests should run in CI by default: `fast`, `artifact`, or full e2e on
   selected branches only?