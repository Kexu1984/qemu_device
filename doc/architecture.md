# Architecture

This document records the architectural rules for the KX6625 QEMU prototype. It is intentionally high level. Device register details stay in `spec/`, and command usage stays in `doc/tools.md`.

The goal is to keep the project moving toward a realistic SoC validation environment without turning every implementation note into a permanent document that must be synchronized forever.

## Scope

This repository models a chip-level prototyping platform, not a cycle-accurate full-chip simulator.

The platform is expected to support:

- Firmware and RTOS bring-up on a custom QEMU SoC.
- Register-level validation of Python functional device models.
- Register-level validation of selected SystemVerilog devices through a transaction bridge.
- Early boot, reset, clock, security, and lifecycle flows that happen before or around CPU execution.
- Deterministic end-to-end tests using QEMU virtual time where possible.

The platform is not expected to model every bus wait state, clock-domain crossing, analog behavior, or full gate-level timing detail.

## Documentation Boundaries

Keep documentation split by ownership level:

- `README.md`: project overview, quick start, and current capability summary.
- `doc/architecture.md`: SoC-level architecture, ownership boundaries, modeling rules, and design principles.
- `doc/timing.md`: QEMU virtual time, Python device timing, SV local-clock timing, and their boundaries.
- `doc/tools.md`: development, build, generation, run, debug, and validation tools.
- `spec/`: device-level design details, memory maps, register maps, reset values, access policies, and generated-code inputs.
- `courseware/`: teaching material and labs; it should not be the source of truth for platform architecture.

When architecture and implementation diverge, update this document first only if the rule or boundary changed. If only a register field changed, update the relevant `spec/*.yaml` and generated artifacts.

## SoC Model Layers

The platform is organized into several modeling layers.

| Layer | Main files | Responsibility |
|-------|------------|----------------|
| QEMU machine | `scripts/qemu-fork/hw/arm/kx6625.c` | CPU containers, memory map, native SYSCTRL, flash preload, reset and boot gates |
| QEMU socket proxy | `scripts/qemu-fork/hw/misc/mmio_sockdev.c` | Generic MMIO, IRQ, tick, DMA memory, and reset transport between QEMU and external models |
| Python models | `device_model/` | Fast functional peripheral models, register behavior, DMA clients, reference crypto/OTP behavior |
| SystemVerilog models | `sv_device/` | RTL-style peripheral blocks with local clocks, accessed through transaction boundaries |
| Firmware | `firmware/` | FreeRTOS CPU0 workload, CPU1 bare-metal loop, driver-level validation |
| Specs and generated code | `spec/`, `device_model/generated/`, `build/generated/` | Machine-readable device description and generated constants/headers |
| Scripts and tests | `scripts/`, `Makefile` | Build, run, signing, code generation, e2e validation, trace visualization |

## Modeling Principles

Use hardware ownership as the first design question.

For every new feature, decide:

- Which block owns the state machine?
- Which block is the bus master?
- Which block is the slave register target?
- Is the CPU already running when this flow happens?
- Does completion need a CPU interrupt, a status bit, a sideband signal, or a local hardware handshake?
- Does the behavior survive reset, depend on clock state, or cross a security/lifecycle boundary?

Prefer hardware-like interactions over software-service APIs. A QEMU-native block should not call into a Python model as a library service when the chip behavior is naturally a bus transaction. It should access the target register interface through the modeled bus path.

## Bus Masters and Access Paths

The current platform has these modeled bus masters:

| Master | Master ID | Typical access path | Notes |
|--------|-----------|---------------------|-------|
| CPU0 | `0x00` | Firmware MMIO through QEMU CPU access | Main FreeRTOS core |
| CPU1 | `0x01` | Firmware MMIO through QEMU CPU access | Bare-metal secondary core |
| SYSCTRL | `0xF0` | Native QEMU address-space accesses into device registers | Used for pre-CPU and privileged SoC control flows |
| DMA/HSM internal DMA | transport-specific | `mem-chardev` physical memory channel | Reads/writes QEMU physical memory as a modeled bus master |

The SYSCTRL master ID exists because some flows happen before CPU0 is released. Device models can use this ID to distinguish CPU-visible accesses from privileged SoC-control accesses.

## SYSCTRL Ownership

SYSCTRL is the chip-level system controller. It owns chip-lifecycle and early-boot state machines unless a future architecture explicitly assigns ownership elsewhere.

SYSCTRL responsibilities include:

- CPU identity and CPU release policy.
- Reset policy and reset reason/status reporting.
- Boot status, boot gating, and secure boot orchestration.
- Coarse peripheral clock/reset policy.
- Privileged indirect access to device registers for chip-control flows.

SYSCTRL should model hardware control paths, not firmware convenience services. If SYSCTRL needs to use another block, it should normally access that block's registers as a bus master.

## Secure Boot V1

Secure boot is owned by SYSCTRL.

The current secure boot flow is:

1. QEMU preloads the Intel HEX firmware image into the modeled flash image.
2. `scripts/secure_boot_otp.py` installs OTP key0, secure-boot metadata, and the expected AES-CMAC into `build/otp.hex`.
3. SYSCTRL holds CPU0 before boot.
4. SYSCTRL waits until real OTP and HSM socket-backed devices are visible.
5. SYSCTRL reads OTP shadow metadata and expected CMAC.
6. SYSCTRL programs HSM registers as master `0xF0`.
7. HSM computes AES-CMAC over the fixed 512 KB flash image.
8. SYSCTRL compares the HSM result with OTP expected CMAC.
9. SYSCTRL releases CPU0 only if verification passes.

HSM is a crypto engine, not the secure-boot state machine owner. OTP stores key material and non-secret boot metadata. CPU interrupts are not part of the pre-CPU secure boot path; completion is represented as SYSCTRL boot status.

## Interrupts, Status Bits, and Sideband Signals

Do not automatically turn every hardware completion into a CPU interrupt.

Use this rule of thumb:

- CPU-visible asynchronous events should use NVIC IRQs when firmware is expected to handle them.
- Pre-CPU or SYSCTRL-owned flows should use local status bits, sideband signals, or direct polling by the owning state machine.
- A one-bit block-level done/fail/ready signal should not be expanded into a full CPU interrupt path unless the architecture requires firmware participation.
- Device-level IRQ details belong in `spec/*.yaml` and `spec/README.md`.

## Clock and Time Model

QEMU CPU execution and Python timed devices use chip virtual time.

See `doc/timing.md` for the detailed timing model across QEMU, Python devices, and SystemVerilog devices.

Recommended deterministic runs use:

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

With `-icount shift=5`, `QEMU_CLOCK_VIRTUAL` advances as instruction count times 32 ns. Python timed devices can receive QEMU virtual-time ticks or one-shot DES events through `mmio-sockdev`.

SystemVerilog devices keep their own local clock. An MMIO access to an SV device is a synchronous transaction boundary. The SV host shell can spend local pclk cycles to complete a register operation, but those cycles are not automatically back-annotated into QEMU CPU execution time.

## Reset Model

Reset is modeled at several levels:

- QEMU machine reset resets CPU state and native SoC state.
- Python device reset is coordinated by the device server and reset manager.
- WDT can request a QEMU system reset through the reset channel.
- Some device registers are retention state and intentionally survive warm reset.
- CPU1 can be held or released independently through SYSCTRL policy.

When adding reset-sensitive behavior, specify which reset domain owns it: POR, warm reset, CPU-local reset, peripheral reset, or retention state.

## Python Device Model Rules

Python models should behave like hardware peripherals:

- Expose behavior through registers and modeled channels.
- Keep register reset values and access policy aligned with `spec/*.yaml`.
- Use `RegisterBank` and shared helpers where possible.
- Use QEMU virtual time or DES events for deterministic timing.
- Use `MemChannel` for modeled bus-master memory access.
- Avoid hidden direct coupling unless it represents an internal hardware connection, such as HSM reading OTP key slots through a private key-provider path.

## SystemVerilog Device Model Rules

SystemVerilog devices are used for RTL-style peripheral validation.

Rules:

- SV blocks keep local clocks and local state machines.
- QEMU accesses SV blocks through transaction boundaries, usually APB-style register operations.
- SV IRQs return to QEMU through the normal IRQ transport.
- Python reference models can be used for comparison, but should not hide the SV block's own register behavior.
- Do not claim cycle-accurate CPU-to-SV alignment unless the bridge explicitly models that timing.

## Spec Directory Contract

`spec/` is the source of truth for device-level details.

It should contain:

- Device memory maps.
- Register offsets, names, reset values, access types, and bit definitions.
- IRQ assignments and transport port assignments.
- Access policy metadata such as allowed masters.
- SoC-level generated constants needed by firmware, Python, and QEMU glue.

It should not become a long architecture narrative. If a rule applies across multiple devices or explains SoC-level ownership, place it in this document instead.

## Feature Development Flow

For large features, use this review loop:

1. Define the hardware ownership: state machine, masters, slaves, reset/clock/security domains.
2. Update or add `spec/*.yaml` for register-visible behavior.
3. Generate constants with `make gen`.
4. Implement the model in the right layer: QEMU machine, Python, SV, firmware, or script.
5. Add firmware or e2e coverage that proves the hardware-visible flow.
6. Run deterministic validation.
7. Update only the docs whose ownership boundary changed.

This loop is meant to preserve flexibility. Low-level custom chip design often has several valid implementation shapes, so architectural review should happen before code becomes the constraint.
