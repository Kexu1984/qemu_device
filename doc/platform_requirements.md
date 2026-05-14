# Simulation Platform Core Requirements

This document is a requirements-level description of the simulation platform
core. It complements `doc/architecture.md`, `doc/fabric.md`, and
`doc/timing.md` by turning the platform design intent into testable
requirements.

Device register maps remain in `spec/`. Firmware and MCAL requirements remain
outside this document unless they are needed to validate the platform core.

## 1. Purpose

The simulation platform shall provide a deterministic chip-function validation
environment that connects QEMU-native code, Python functional models, and
SystemVerilog/Verilator RTL models through explicit transaction, timing, IRQ,
reset, and trace boundaries.

The platform is not required to provide full-chip cycle accuracy, exact CPU bus
wait states, analog behavior, or gate-level timing unless a future requirement
explicitly adds those capabilities.

## 2. Scope

The core platform modules covered here are:

- Fabric and bus-master transactions.
- Timing and event delivery.
- Interrupt delivery.
- Reset delivery and reset-domain behavior.
- Transport protocol handling between QEMU, Python, and SV.
- Observability and trace evidence.

The main implementation domains are:

| Domain | Representative files | Role |
|--------|----------------------|------|
| QEMU C | `scripts/qemu-fork/hw/arm/kx6625.c`, `scripts/qemu-fork/hw/misc/mmio_sockdev.c`, `scripts/qemu-fork/hw/misc/mmio_fabric.c` | CPU/SoC integration, native blocks, socket proxy, fabric helpers, reset/tick/IRQ plumbing |
| Python | `device_model/mmio_base.py`, `device_model/mmio_device_server.py`, `device_model/soc_top.py`, `device_model/tracer.py` | Functional device domain, peripheral bus, transport servers, fabric clients, tick/reset dispatch, trace |
| SystemVerilog/C++ | `sv_device/*.sv`, `sv_device/sv_host_shell.cpp` | RTL-style APB island, SV-local timing, SV master routing, DPI fabric egress, IRQ forwarding |
| Generated specs | `spec/*.yaml`, `device_model/generated/`, `build/generated/` | Addresses, ports, IRQs, master IDs, generated constants |

## 3. Requirement Status

Status values used in this document:

| Status | Meaning |
|--------|---------|
| Current | Intended to describe current behavior and should be testable now. |
| Target | Desired platform behavior that may require implementation work. |
| Open | Requires architecture decision before implementation or test closure. |

## 4. General Platform Requirements

| ID | Status | Requirement |
|----|--------|-------------|
| PLAT-GEN-001 | Current | The platform shall model chip-functional behavior, not claim full-chip cycle accuracy by default. |
| PLAT-GEN-002 | Current | QEMU, Python, and SV domains shall communicate through explicit transactions, events, IRQs, reset notifications, or documented sideband paths. |
| PLAT-GEN-003 | Current | Device-specific register facts shall be sourced from `spec/`; cross-device platform rules shall be documented under `doc/`. |
| PLAT-GEN-004 | Current | Generated constants shall be used for shared architectural values such as base addresses, IRQs, ports, and master IDs whenever practical. |
| PLAT-GEN-005 | Current | Platform changes that affect ordering, timing, reset, fabric, or IRQ behavior shall provide deterministic validation evidence when practical. |

## 4.1 Reviewed Design Decisions

These decisions capture the current project direction and should be reflected
in implementation and tests.

| Topic | Decision |
|-------|----------|
| Fabric response status | Keep the current OK/ERROR response model for now. Richer statuses such as decode error, access-policy error, timeout, and slave error remain a roadmap improvement. |
| Fabric coverage scope | Fabric requirements and tests cover all participating domains: QEMU-native C, Python, and SystemVerilog/C++ bridge code. |
| Access denial | Keep the current access-denial behavior for now. A future system MPU may define stronger policy behavior such as bus faults or richer denial reporting. |
| SV reset model | SV blocks are treated as devices. SV device reset should be software controlled through registers; software must explicitly release reset before the SV device is considered active. |
| IRQ model | The platform needs both level-sensitive IRQ semantics and pulse IRQ semantics. Pulse behavior must be defined as a short assert/deassert event, not as a separate transport type unless a future protocol revision requires it. |
| Timestamp model | QEMU virtual time is the primary platform timestamp for deterministic behavior. Host wall time may be recorded for ordering/debug visibility. SV-local timing is represented by SV clock ticks/cycles and is not correlated to QEMU virtual time by default. |
| Coverage priority | Functional requirement evidence comes first. Line and branch coverage are optional diagnostics, not QEMU/SV acceptance gates. |
| Test location | New platform tests should live under the repository-level `tests/` directory. |
| Regression selection | Fabric core changes require broad platform regression across QEMU C, Python, SV, e2e, and trace assertions. Firmware-only or device-only changes may run the corresponding targeted tests. |
| Target requirements | `Target` requirements are accepted as roadmap items unless later review reclassifies or removes them. |

## 5. Fabric Requirements

The fabric is the functional transaction surface for modeled bus-master access
across QEMU-native, Python, SV, and memory targets.

| ID | Status | Requirement |
|----|--------|-------------|
| FAB-001 | Current | A fabric transaction shall carry an explicit `master_id`, absolute SoC physical `address`, access `size`, and write `data` when applicable. |
| FAB-002 | Current | Master-facing APIs shall use absolute SoC physical addresses; endpoint-local offsets shall be computed only after decode. |
| FAB-003 | Current | Master IDs shall be allocated in `spec/soc.yaml` and propagated through generated constants. |
| FAB-004 | Current | Python bus-master devices shall use a fabric client or bus-master address-space object instead of target-specific direct calls for memory/system access. |
| FAB-005 | Current | QEMU-native masters shall use fabric helper APIs for modeled bus transactions when accessing another device as a bus master. |
| FAB-006 | Current | SV bus masters shall use the SV request/response path through `sv_master_router.sv` and `sv_fabric_egress_dpi.sv` for external fabric access. |
| FAB-007 | Current | The fabric shall preserve transaction ordering for a single serialized fabric channel. |
| FAB-008 | Target | Fabric decode should eventually distinguish OK, decode error, access-policy error, timeout/disconnected target, and slave error in the response model. The current required behavior remains OK/ERROR. |
| FAB-009 | Current | Unmapped or failed fabric accesses shall be observable through logs or trace evidence. |
| FAB-010 | Current | Fabric buffer accesses shall support transfers larger than a single transport chunk by splitting and preserving address order. |
| FAB-011 | Target | Fabric decode and access-policy metadata should be generated from `spec/` where possible. |
| FAB-012 | Target | A Python master should be able to reach Python, SV, QEMU-native, and memory targets through the same logical transaction contract. |
| FAB-013 | Target | An SV master should be able to reach Python, SV, QEMU-native, and memory targets through the same logical transaction contract. |
| FAB-014 | Current | Fabric tests shall include QEMU-native C, Python, and SystemVerilog/C++ bridge behavior when the fabric core is modified. |
| FAB-015 | Target | A future system MPU may own detailed access-denial policy and may refine whether denial is reported as an error response, trace-only denial, or guest-visible fault. |

## 6. Timing And Event Requirements

The timing model contains multiple time domains. These domains are connected by
transactions and explicit events, not by a single global cycle-accurate clock.

| ID | Status | Requirement |
|----|--------|-------------|
| TIME-001 | Current | QEMU CPU execution and QEMU timers shall use QEMU virtual time. |
| TIME-002 | Current | Deterministic regression runs shall use `ICOUNT_SHIFT=5` unless a test explicitly needs realtime behavior. |
| TIME-003 | Current | Python timed devices shall use QEMU virtual-time timestamps supplied by tick or DES messages, not host wall-clock time. |
| TIME-004 | Current | A periodic tick message shall contain an absolute `vtime_ns` timestamp and shall be dispatched to all registered tick-capable devices or observers. |
| TIME-005 | Current | A DES-capable write shall return `next_event_ns`; QEMU shall schedule a virtual-time tick at `now + next_event_ns` when the value is non-zero. |
| TIME-006 | Current | Devices shall treat MMIO writes as configuration transactions and explicitly schedule later hardware effects when behavior is not immediate. |
| TIME-007 | Current | TCP round-trip latency shall not be interpreted as chip bus latency. |
| TIME-008 | Current | SV devices shall keep SV-local time in Verilator cycles and shall not imply cycle-accurate alignment with QEMU virtual time. |
| TIME-009 | Current | `WFI` wakeup from a virtual-time event or IRQ shall be validated as functional behavior under deterministic runs. |
| TIME-010 | Target | Timing-related trace events should include QEMU virtual time when available and may include host wall time for debug ordering. |
| TIME-011 | Current | SV-local timing evidence shall use SV clock ticks or cycles and shall not be correlated to QEMU virtual time unless a future bridge explicitly models that relation. |

## 7. IRQ Requirements

The IRQ path is the functional connection from Python/SV device events to QEMU
NVIC-visible interrupts.

| ID | Status | Requirement |
|----|--------|-------------|
| IRQ-001 | Current | A device IRQ path shall use an `irq-chardev` channel carrying IRQ index and level. |
| IRQ-002 | Current | IRQ-producing devices shall be able to assert and deassert an IRQ level. |
| IRQ-003 | Current | Firmware-visible asynchronous events shall use NVIC IRQs when firmware is expected to handle them. |
| IRQ-004 | Current | Pre-CPU or SYSCTRL-owned flows shall prefer status bits, sideband signals, or local polling instead of CPU IRQs unless firmware participation is required. |
| IRQ-005 | Current | The platform shall tolerate IRQ channel not-yet-connected conditions without crashing the Python device process. |
| IRQ-006 | Current | SV IRQ outputs shall be observed by the SV host shell and forwarded to QEMU through the same functional IRQ transport model. |
| IRQ-007 | Target | IRQ tests shall cover assert, observe, clear, and deassert behavior for both Python and SV IRQ sources. |
| IRQ-008 | Target | IRQ trace evidence should identify source device, IRQ number, asserted/deasserted level, and relevant virtual or local timing context. |
| IRQ-009 | Target | The IRQ model shall support pulse IRQ semantics as an assert followed by a deassert after the receiving side has had an opportunity to observe the interrupt. |
| IRQ-010 | Target | The IRQ model shall support level-sensitive semantics where the device keeps the IRQ asserted until firmware clears the device-specific interrupt source. |

### Pulse And Level-Sensitive IRQ Semantics

Level-sensitive IRQ behavior means the device asserts the IRQ line and keeps it
asserted while the interrupt source remains pending. Firmware clears a
device-specific status or interrupt-clear register, and the device then
deasserts the IRQ line. This is appropriate for status-backed interrupts such
as timer pending bits, GPIO change status, or DMA done status.

Pulse IRQ behavior means the device emits a short interrupt event: assert the
IRQ line, then deassert it after a defined observation window. In this platform
the transport can still use the same `I, irq_idx, level` messages: one message
with `level=1`, followed by one message with `level=0`. The requirement is not
a new socket protocol by itself; it is a device/bridge behavior requirement.
Tests must prove that QEMU/NVIC and firmware can observe the pulse reliably.
If a future device needs a pulse narrower than the QEMU interrupt observation
window, that device should either stretch the pulse in the model or expose a
status bit so the event cannot be lost.

## 8. Reset Requirements

Reset is a platform core function because it crosses QEMU CPU state, Python
device state, SV device state, and retention behavior.

| ID | Status | Requirement |
|----|--------|-------------|
| RST-001 | Current | The platform shall distinguish POR, system reset, and device reset scopes. |
| RST-002 | Current | A system reset initiated by a Python device shall request a QEMU system reset through the reset channel. |
| RST-003 | Current | Python volatile device state shall be reset through device `on_reset()` during system reset. |
| RST-004 | Current | Retention state shall survive system reset only when explicitly documented. |
| RST-005 | Target | Device reset assertion shall block or reject accesses to the affected device while preserving frozen state until reset release. |
| RST-006 | Target | Device reset release shall return the affected device registers to documented reset values. |
| RST-007 | Target | Reset notifications to Python and SV backends shall be testable independently from firmware demos. |
| RST-008 | Target | Reset trace evidence should identify reset source, reset scope, affected device, and retention outcome. |
| RST-009 | Target | SV reset shall be modeled as device-level software-controlled reset. Software shall write the relevant register sequence to release an SV device from reset before normal operation. |

## 9. Transport Protocol Requirements

Transport code is the boundary that keeps device semantics out of sockets and
keeps socket details out of device models.

| ID | Status | Requirement |
|----|--------|-------------|
| TR-001 | Current | The R/W transport shall parse read and write frames, preserve master ID, compute absolute address from base plus offset, and delegate to the bus. |
| TR-002 | Current | A write response shall always return an 8-byte little-endian DES value to QEMU. |
| TR-003 | Current | Unknown or malformed transport opcodes shall terminate or reject the client connection without corrupting device state. |
| TR-004 | Current | Fabric transport frames shall carry operation, master ID, flags, absolute address, length, and payload for writes. |
| TR-005 | Current | Fabric channel I/O shall be serialized per channel to avoid interleaved responses. |
| TR-006 | Target | Transport protocol tests shall exercise short reads, disconnects, malformed opcodes, and large transfers. |

## 10. Observability Requirements

Trace and logs are required evidence for platform behavior, not only debugging
convenience.

| ID | Status | Requirement |
|----|--------|-------------|
| OBS-001 | Current | The platform shall emit non-blocking JSONL trace events for meaningful device and platform activity. |
| OBS-002 | Current | Trace visualization shall produce a human-readable HTML report from `build/device_trace.jsonl`. |
| OBS-003 | Target | Fabric, timing, IRQ, and reset events should have stable event names that can be asserted by automated tests. |
| OBS-004 | Target | Trace events for cross-domain transactions should include source domain, target domain, master ID, address, response status, QEMU virtual time when available, and host wall time when useful for debug ordering. |
| OBS-005 | Target | CI or local regression should be able to fail on missing required trace events, not only on missing firmware log strings. |
| OBS-006 | Target | SV trace or waveform evidence should include SV-local cycle/tick information for SV-local behavior. |

## 11. Verification Requirements

| ID | Status | Requirement |
|----|--------|-------------|
| VER-001 | Target | Functional requirement evidence is the primary verification metric: each platform requirement in this document shall map to at least one test case, e2e artifact, trace sequence, or accepted rationale for no test. |
| VER-002 | Target | Python platform infrastructure should have executable unit and transport tests; numeric line/branch coverage is an optional diagnostic. |
| VER-003 | Target | QEMU C platform helpers should have source contracts, e2e artifact evidence, trace sequence evidence, or focused qtest/host-level tests for critical functional paths. |
| VER-004 | Target | SV platform bridge modules should have source contracts, SV host shell/e2e evidence, trace/waveform evidence, or focused Verilator tests for APB ingress, master routing, fabric egress, and IRQ forwarding. |
| VER-005 | Target | End-to-end tests should validate behavior through observable requirements, not only broad demo success strings. |
| VER-006 | Target | Coverage reporting should distinguish firmware coverage from platform coverage. |
| VER-007 | Target | Platform tests shall be organized under a repository-level `tests/` directory unless a tool requires local placement. |
| VER-008 | Target | Fabric core changes shall run broad platform regression across QEMU C, Python, SV, e2e, and trace assertions; narrower firmware-only or device-only changes may run targeted tests mapped to the affected requirements. |

## 12. Remaining Review Questions

The first review pass resolved the original open questions. These follow-up
questions remain useful before implementation-heavy test work begins.

1. What exact observation window should pulse IRQ tests require: one QEMU main-loop iteration, a fixed virtual-time duration, one firmware polling interval, or device-specific pulse stretching?
2. Which trace event names should become stable contract names for fabric, timing, IRQ, and reset assertions?
3. What first-pass requirement coverage threshold is acceptable for platform CI: all Current requirements only, or both Current and selected Target requirements?
4. Which QEMU C test approach should be preferred first: qtest integration, focused e2e trace assertions, or host-buildable helper tests?