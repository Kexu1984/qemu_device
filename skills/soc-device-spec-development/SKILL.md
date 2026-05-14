---
name: soc-device-spec-development
description: "Use when: defining, extending, reviewing, or validating a chip instance built on the simulation platform; adding peripherals, editing spec/*.yaml, memory maps, register maps, IRQs, TCP ports, access policies, generated constants, Python/SV device models, or low-level firmware drivers that prove the device contract."
argument-hint: "<device or SoC feature, e.g. GPIO peripheral spec or SYSCTRL access policy>"
---

# SoC Device Specification Development

## Goal

Use this workflow when the task is about defining a modeled chip instance on top of the simulation platform. The expected output is a traceable device-level contract: YAML specification, generated constants, device model behavior, integration path, and enough firmware or e2e validation to prove the register-visible behavior.

This skill owns the boundary between platform architecture and firmware software development. It defines what the chip exposes. MCAL and application software should consume that exposed contract rather than inventing hardware behavior in firmware.

## When To Use

Use this skill for tasks such as:

- Add a new peripheral to the KX6625 SoC model.
- Update `spec/*.yaml` register maps, memory maps, IRQ assignments, TCP ports, reset values, access types, bitfields, or allowed-master policy.
- Decide whether a peripheral should be Python-modeled, SystemVerilog-modeled, QEMU-native, or split across domains.
- Connect a device to the platform through MMIO socket, native QEMU MMIO, SV APB bridge, fabric master, IRQ, tick/DES, reset, or trace paths.
- Generate and consume constants in firmware, Python models, QEMU glue, or SV tests.
- Add low-level `firmware/drivers/` code that validates a device contract before MCAL wraps it.
- Review whether a device spec is complete enough for driver and MCAL development.

Do not use this skill for platform-wide fabric/timing architecture changes unless the device feature requires them. Use the simulation platform workflow for platform mechanisms and the MCAL workflow for AUTOSAR-style driver abstraction work.

## Required Inputs

Before implementing, collect these inputs or explicitly mark them as unavailable:

1. Device purpose and class.
   Example: interface peripheral, control peripheral, bus-master peripheral, security/lifecycle peripheral, memory controller, or SV prototype.
2. Register-visible contract.
   Example: base address, size, offsets, fields, access type, reset value, W1C/W1S behavior, side effects, reserved bits, alignment, and error behavior.
3. Integration path.
   Example: Python `MMIODevice`, QEMU-native block, SV APB slave, bus master, tick/DES event source, IRQ source, reset requester, or trace producer.
4. Access and ownership policy.
   Example: CPU0-only, CPU1 allowed, SYSCTRL privileged access, DMA/HSM/SV master access, secure/non-secure future metadata, or retention state.
5. Verification target.
   Example: generated headers, Python unit/demo path, firmware driver demo, deterministic e2e, SV host shell e2e, trace report, or coverage evidence.

## Device-Level Source Of Truth

The `spec/` directory is the source of truth for chip and device facts:

- Memory maps and peripheral windows.
- Register offsets, names, access types, reset values, and bit definitions.
- IRQ assignments and socket port assignments.
- Tick, fabric, reset, and terminal channel assignments.
- Master IDs and access-policy metadata.
- SoC-level generated constants needed by firmware, Python, QEMU, and SV glue.

Keep long architecture narratives out of `spec/`. If a rule applies across multiple devices, put it in `doc/architecture.md`, `doc/fabric.md`, `doc/timing.md`, or `doc/reset.md`.

## Device Classification

Classify the requested device before writing YAML:

- Interface peripheral: UART, SPI, I2C, GPIO, CAN, PWM, ADC, or similar external-facing IP.
- Control peripheral: SYSCTRL, CRU, reset controller, clock controller, pin controller, interrupt aggregation, or lifecycle control.
- Bus-master peripheral: DMA, HSM, flash controller, SV DMA, or any block that reads/writes memory or other devices.
- Security and lifecycle peripheral: OTP, HSM, secure boot helper, key ladder, access controller, or debug lock.
- Memory or storage controller: flash, data flash, SRAM windows, boot memory, or memory-mapped data windows.
- SV prototype peripheral: APB slave or master implemented in `sv_device/` and connected through the SV host shell.

The classification affects reset, timing, IRQ, access-policy, and validation expectations.

## Development Flow

### 1. Define The Hardware Contract First

Start with the register-visible behavior:

- Base address, aperture size, and owner domain.
- Register offsets, access width, access type, reset value, and reserved bits.
- Field definitions, W1C/W1S semantics, write masks, read side effects, and clear-on-read behavior.
- Reset domains: POR, warm reset, CPU-local reset, peripheral reset, or retention state.
- IRQ behavior: source, enable bit, status bit, clear mechanism, pulse/level behavior, and NVIC number.
- Timing behavior: immediate, QEMU virtual-time DES, periodic tick, SV local cycles, or untimed functional operation.
- Bus-master behavior: master ID, source/destination address rules, response/error handling, and allowed target ranges.

Avoid starting from firmware API shape. Firmware and MCAL should follow the hardware contract.

### 2. Update Specs And Generated Constants

For spec changes:

1. Update the relevant `spec/*.yaml` file or add a new one.
2. Update `spec/devices.yaml` for memory map, IRQ, port, tick, reset, fabric, or terminal channel entries.
3. Update `spec/soc.yaml` for SoC-level constants such as clocks, reset policy, CPU configuration, master IDs, or global generated values.
4. Update `spec/README.md` when human-readable device tables should change.
5. Run `make gen`.
6. Use generated names from `build/generated/mmio_devices.h` and `device_model/generated/device_consts.py`; do not duplicate numeric constants by hand.

If generated outputs are tracked source-of-truth in the repo, keep them aligned. If they are build artifacts, do not commit accidental generated churn unless the project expects it.

### 3. Choose The Implementation Domain

Use the device's role to choose where behavior belongs:

- Python model: fast functional peripheral behavior, deterministic virtual-time events, reference/checker behavior, crypto/OTP/flash functional logic, or bus-master demos.
- SystemVerilog model: RTL-style APB register behavior, local pclk state machines, SV bus-master prototypes, or block-level RTL validation.
- QEMU-native block: CPU/container integration, native system-control behavior, boot/reset policy, or flows that must exist before external device servers participate.
- Firmware driver: low-level software that exercises and validates the device contract; it should not own hardware behavior.

When in doubt, preserve hardware-like boundaries. A control block should reach another block through registers or modeled sideband signals, not by calling private implementation functions unless it represents an internal hardware connection.

### 4. Implement The Device Slice

For a Python-owned peripheral:

1. Add or update the `MMIODevice` implementation under `device_model/`.
2. Register it in the SoC/device-domain construction path.
3. Use generated constants for offsets, reset values, IRQs, ports, and master IDs.
4. Add `on_tick()` or DES scheduling only if the hardware contract needs time.
5. Emit trace events for meaningful state transitions, errors, IRQs, resets, and bus-master operations.

For an SV-owned peripheral:

1. Add or update APB slave logic under `sv_device/`.
2. Register the window in the SV APB decoder and top-level wiring.
3. Keep APB sequencing inside SV bridge modules rather than host-shell ad hoc register behavior.
4. Connect IRQ and optional master request/response paths through existing SV interfaces.
5. Use waveform/e2e evidence when validating local RTL behavior.

For a QEMU-native peripheral:

1. Add or update QEMU `MemoryRegionOps` and machine wiring.
2. Use generated constants where available.
3. Keep native blocks hardware-like, especially for SYSCTRL/reset/boot flows.
4. Route device-register access through modeled bus paths when the architecture calls for a master transaction.

### 5. Add Firmware Or E2E Proof

Add only the firmware needed to prove the device contract:

- Low-level drivers belong under `firmware/drivers/` and public driver headers under `firmware/drivers/includes/`.
- Demo or e2e dispatch may live in `firmware/main.c` when needed for validation.
- MCAL-facing AUTOSAR-style abstractions belong under `firmware/MCAL/` and should use the MCAL development workflow.

Positive tests should prove reset values, read/write behavior, side effects, IRQs, timing completion, and bus-master access. Negative tests should cover invalid offsets, unsupported sizes, access-policy denial, protected registers, bad address alignment, or illegal state transitions when relevant.

## Validation Commands

Use the repo's existing validation commands unless the task says otherwise:

```bash
make gen
make sv
make -C firmware clean && make fw
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
python3 scripts/visualize_trace.py build/device_trace.jsonl build/trace_report.html
```

Choose the subset that matches the device change:

- YAML/spec-only changes: run `make gen` and inspect generated constants.
- Python device behavior: run targeted Python checks if available and deterministic e2e for integrated behavior.
- SV peripheral behavior: run `make sv` and an SV-relevant e2e path.
- Firmware driver changes: run firmware build and the smallest e2e/demo that exercises the register contract.
- IRQ, timing, reset, access policy, or bus-master behavior: prefer full deterministic e2e with `ICOUNT_SHIFT=5`.

If a command cannot be run, report why and name the unverified risk.

## Completion Checklist

Before finishing, verify:

- The device class and implementation domain are clear.
- `spec/*.yaml`, `spec/devices.yaml`, and `spec/soc.yaml` are aligned with the feature.
- Generated constants were refreshed when specs changed.
- Register reset values, access types, field semantics, and reserved bits are documented.
- IRQ, timing, reset, tick/DES, fabric, and access-policy behavior are specified when applicable.
- Python, SV, QEMU-native, and firmware code use generated constants instead of duplicated magic numbers where practical.
- Low-level firmware validation is separate from MCAL abstraction work.
- `spec/README.md` or docs were updated when human-readable device behavior changed.
- Relevant validation commands were run or intentionally skipped with rationale.

## Output Format For Agent Responses

When reporting results, include:

- Which device or SoC feature was touched.
- Which implementation domain owns it: Python, SV, QEMU-native, generated specs, firmware driver, or docs.
- What spec/register/IRQ/timing/reset/access-policy contract changed.
- What generated outputs or drivers were updated.
- What validation was run.
- Known gaps before MCAL or application software can rely on the device.

Keep the final summary concise, but do not omit hardware-contract gaps.