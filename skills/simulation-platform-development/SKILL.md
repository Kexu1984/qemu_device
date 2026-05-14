---
name: simulation-platform-development
description: "Use when: designing, refactoring, reviewing, or validating the QEMU/Python/SystemVerilog simulation platform itself; changing fabric, timing, event scheduling, reset, IRQ, trace, mmio-sockdev, Python device-domain infrastructure, SV bridge infrastructure, or platform architecture documentation under doc/."
argument-hint: "<platform feature, e.g. fabric master decode or DES timing>"
---

# Simulation Platform Development

## Goal

Use this workflow when the task is about the simulation and validation platform itself, rather than about a specific chip peripheral or firmware driver. The expected output is a platform-level change or review that preserves the architecture boundaries documented in `doc/` and keeps the QEMU, Python, and SystemVerilog domains connected through explicit transactions and events.

This repository is a chip-function validation environment. It is not a full cross-domain cycle-accurate simulator unless a task explicitly adds such a feature and documents the new timing contract.

## When To Use

Use this skill for tasks such as:

- Change the platform fabric, master IDs, decode behavior, access policy, or cross-domain bus-master routing.
- Change `mmio-sockdev`, socket protocols, transport servers, tick channels, DES events, IRQ delivery, or reset channels.
- Add or refactor Python device-domain infrastructure such as `PeripheralBus`, `BusMasterAddressSpace`, tracing, reset management, or generated platform constants.
- Add or refactor SystemVerilog bridge infrastructure such as APB ingress, SV master router, DPI fabric egress, host-shell request/response handling, or SV IRQ forwarding.
- Update platform architecture documents in `doc/`, especially fabric, timing, reset, tools, and architecture boundaries.
- Review whether a proposed implementation belongs in QEMU-native code, Python infrastructure, SystemVerilog infrastructure, generated specs, or firmware.

Do not use this skill for ordinary MCAL or firmware-driver implementation. Use the MCAL development workflow for `firmware/MCAL/` and driver-facing AUTOSAR-style work.

## Required Inputs

Before implementing, collect these inputs or explicitly mark them as unavailable:

1. Platform ownership statement.
   Example: the state machine is owned by SYSCTRL, a Python device, an SV RTL block, or a QEMU-native helper.
2. Affected platform domains.
   Example: QEMU machine, `mmio-sockdev`, Python device server, SV host shell, SV RTL bridge, generated constants, scripts, or docs.
3. Transaction and timing expectations.
   Example: synchronous MMIO, DES one-shot event, periodic virtual-time tick, SV local clock behavior, IRQ, status bit, reset request, or trace event.
4. Existing source-of-truth documents.
   Example: `doc/architecture.md`, `doc/fabric.md`, `doc/timing.md`, `doc/reset.md`, `doc/tools.md`, and relevant `spec/*.yaml` files.
5. Validation target.
   Example: `make gen`, QEMU fork build, SV build, firmware build, deterministic e2e, trace report inspection, or focused unit/demo script.

## Platform Boundaries

Keep work split by ownership level:

- `doc/`: platform architecture, modeling rules, timing contracts, fabric rules, reset model, and tool usage.
- `spec/`: device-level memory maps, register maps, IRQ assignments, port assignments, reset values, access policy, and generated-code inputs.
- `device_model/`: Python functional device domain, transport servers, fabric clients, reset/tick managers, traces, and Python-owned device models.
- `sv_device/`: SystemVerilog device island, APB ingress/decoder, SV slaves, SV masters, router, DPI fabric egress, and host shell.
- `scripts/qemu-fork/`: QEMU machine, native SoC blocks, `mmio-sockdev`, QEMU fabric/reset/tick plumbing.
- `firmware/`: software workloads and drivers used to validate the modeled chip; avoid using firmware as the owner of platform behavior.

If a rule applies across multiple devices or explains platform-level ownership, put it in `doc/`. If a detail is a device register, reset value, IRQ, or address assignment, put it in `spec/`.

## Development Flow

### 1. Classify The Platform Change

Identify the primary platform mechanism before editing code:

- Fabric and bus-master access: master ID, absolute address decode, response policy, target ownership, bridge path, trace visibility.
- Timing and events: QEMU virtual time, Python DES, periodic tick, SV local cycles, WFI wakeup, or host wall-clock behavior.
- Reset and boot: POR, warm reset, CPU-local reset, peripheral reset, retention state, secure boot, CPU release policy.
- IRQ and status signaling: CPU-visible NVIC IRQ, local status bit, pre-CPU sideband, or internal handshake.
- Transport and bridge behavior: socket frame format, synchronous MMIO response, fabric channel, reset channel, terminal channel, SV DPI boundary.
- Observability: JSONL trace fields, trace visualization, logs, debug hooks, or waveform output.

### 2. Decide The Hardware Ownership

For every platform feature, answer these questions:

- Which block owns the state machine?
- Which block is the bus master?
- Which block is the slave register target?
- Is the CPU already running when this flow happens?
- Does completion need a CPU interrupt, status bit, sideband signal, reset request, or local handshake?
- Does the behavior cross reset, clock, security, lifecycle, Python/SV/QEMU, or generated-code boundaries?

Prefer hardware-like transactions over direct software-service calls. A QEMU-native block should not call Python or SV implementation details directly when the modeled chip behavior is naturally a bus transaction.

### 3. Preserve The Transaction Contract

Platform fabric work should converge on the logical contract described in `doc/fabric.md`:

```text
read(master_id, address, size) -> data, response
write(master_id, address, size, data) -> response
```

Use absolute SoC physical addresses at the master-facing boundary. The fabric or bridge should decode addresses and pass endpoint-local offsets only to slave implementations.

New master IDs should be allocated in `spec/soc.yaml` and propagated through generated constants rather than hard-coded in model code.

### 4. Preserve The Timing Contract

Timing work must name its clock or event owner:

- QEMU virtual time for CPU execution and QEMU timers.
- Python virtual-time timestamps for deterministic functional peripheral events.
- Python DES one-shot events for precise scheduled completions.
- Python periodic ticks for simple countdown/background checks.
- SV local cycles for RTL-local state machines and APB protocol behavior.
- Host wall-clock only for process runtime or debug convenience, not chip time.

Do not treat TCP latency, host scheduling, or SV host-shell polling as chip bus latency unless the feature explicitly models that behavior and updates `doc/timing.md`.

### 5. Implement In Small Vertical Slices

For each slice:

1. Update the platform design note in `doc/` if the boundary or rule changes.
2. Update `spec/*.yaml` only when generated constants, maps, IDs, or policy metadata change.
3. Run `make gen` after changing specs.
4. Implement the platform change in the owning domain: QEMU, Python, SV, scripts, or generated glue.
5. Add or update a narrow validation path that exercises the platform-visible behavior.
6. Inspect trace output when ordering, IRQ, reset, fabric, or timing behavior is part of the feature.

Avoid broad cleanup while changing platform primitives. Small, reviewable slices make cross-domain regressions easier to isolate.

## Validation Commands

Use the repo's existing commands unless the task says otherwise:

```bash
make gen
make sv
make -C firmware clean && make fw
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
python3 scripts/visualize_trace.py build/device_trace.jsonl build/trace_report.html
```

Choose the subset that matches the change:

- Spec or generated constant changes: run `make gen`.
- QEMU fork changes: build the QEMU fork with `SKIP_APT=1 bash scripts/build_qemu.sh` when practical.
- SV bridge or RTL changes: run `make sv` and an SV-relevant e2e path.
- Python infrastructure changes: run targeted scripts if available and deterministic e2e for cross-domain behavior.
- Timing, reset, IRQ, fabric, or transport changes: prefer full deterministic e2e with `ICOUNT_SHIFT=5`.

If a command is unavailable or too expensive for the current task, report that clearly and describe the residual risk.

## Completion Checklist

Before finishing, verify:

- The owning platform domain is clear.
- The transaction path is explicit and does not depend on private implementation shortcuts.
- Master IDs, addresses, IRQs, ports, and generated constants remain aligned with `spec/`.
- Timing behavior names its time domain and does not imply unsupported cycle accuracy.
- Reset behavior names its reset domain and retention expectations.
- Trace/debug observability is adequate for the changed behavior.
- Relevant `doc/` files were updated when architecture rules changed.
- Relevant validation commands were run or intentionally skipped with rationale.

## Output Format For Agent Responses

When reporting results, include:

- What platform mechanism was touched.
- Which domain owns the behavior: QEMU, Python, SV, generated specs, scripts, or docs.
- The transaction, timing, reset, or IRQ contract that changed or was preserved.
- What validation was run.
- Known platform limitations or follow-up risks.

Keep the final summary concise, but do not omit timing, reset, or cross-domain caveats when they matter.