---
name: mcal-development
description: "Use when: developing, refactoring, reviewing, or validating AUTOSAR-style MCAL modules; creating Dio/Port/Uart/Mcu/Gpt/Wdg/Spi/Adc drivers; building MCAL requirement matrices; comparing AUTOSAR SWS requirements with SDK driver code; planning MCAL interface verification, MISRA/static analysis, and e2e validation."
argument-hint: "<module or feature, e.g. Dio GPIO over sv_device GPIO>"
---

# MCAL Development And Validation

## Goal

Use this workflow to develop and validate AUTOSAR-style MCAL code in this repository. The expected output is not only source code, but also a traceable development record: specification inputs, driver dependency analysis, MCAL interface design, requirements matrix, tests, static-analysis notes, and verification evidence.

This skill treats the existing low-level `firmware/drivers/` code as hardware access drivers and the `firmware/MCAL/` tree as the standardized MCAL-facing layer. MCAL may call into drivers, but application/demo code should call MCAL APIs only when the intent is to validate the MCAL abstraction.

## When To Use

Use this skill for tasks such as:

- Add or redesign an MCAL module such as Dio, Port, Uart, Mcu, Gpt, Wdg, Spi, Adc, Pwm, Icu, or Can.
- Convert an existing firmware driver into an AUTOSAR-style MCAL interface.
- Validate whether a module is aligned with AUTOSAR SWS expectations.
- Create a requirement checklist for MCAL APIs and behavior.
- Add MCAL interface tests, negative tests, and e2e tests.
- Decide what static analysis, MISRA checks, and coverage evidence are needed.

## Required Inputs

Before implementing, collect these inputs or explicitly mark them as unavailable:

1. AUTOSAR SWS/SRS references for the target MCAL module.
   Example: SWS_Dio for digital IO, SWS_Port for pin direction/mode configuration.
2. Hardware model or SDK driver reference.
   Example: `sv_device/sv_gpio_apb.sv`, generated `mmio_devices.h`, or vendor-style low-level driver code.
3. Existing repo conventions.
   Example: `firmware/drivers/includes/*.h`, `firmware/MCAL/includes/*.h`, `spec/*.yaml`, `scripts/e2e_test.sh`.
4. Verification target.
   Example: compile only, firmware unit test, QEMU e2e, SV host shell e2e, coverage report, static scan.

If AUTOSAR documents are not available in the workspace, do not invent exact requirement IDs. Use placeholder IDs such as `DIO-SWS-TODO-001` and label the source as `pending official SWS lookup`.

## Development Flow

### 1. Classify The Module

Map the requested feature to AUTOSAR concepts before coding.

For GPIO-like work:

- `Port` owns pin mode, direction capability, pull config, alternate function, and initialization.
- `Dio` owns digital read/write of channels, ports, and channel groups.
- A low-level hardware driver may expose register operations, but MCAL should expose AUTOSAR-shaped APIs.

For UART-like work:

- AUTOSAR Classic has communication stack layering; decide whether this repo needs a strict AUTOSAR module name or a pragmatic `Mcal_Uart` abstraction for training/demo purposes.
- Document the decision in the requirement matrix.

### 2. Build The Requirement Matrix First

Create or update a matrix before implementation. Use [the template](./requirements-matrix-template.md).

Minimum columns:

- Requirement ID
- Source
- Requirement summary
- MCAL API or config item
- Driver dependency
- Implementation file
- Test evidence
- Status

Every public MCAL API should map to at least one requirement row. Every negative behavior should also get a row, such as invalid channel, null config, uninitialized access, invalid direction, or unsupported feature.

### 3. Analyze The Hardware Driver Layer

Read the relevant driver and hardware files before editing MCAL:

- Register spec under `spec/`.
- Generated register names in `build/generated/mmio_devices.h` after `make gen`.
- Hardware implementation under `device_model/` or `sv_device/`.
- Existing low-level firmware driver under `firmware/drivers/<module>/`.

Document the driver capabilities and limitations. For example:

- GPIO supports 32 channels.
- Direction is a bitmask.
- Output pins loop back into DATA_IN.
- Input pins can use INPUT_SIM in the SV model.
- GPIO IRQ is data-change based and shares SV IRQ5.

### 4. Design The MCAL Boundary

Keep the layering clear:

- `firmware/drivers/<module>/`: raw hardware-oriented API, register semantics, IRQ helpers, local self-test.
- `firmware/drivers/includes/<module>.h`: driver interface used by MCAL and tests.
- `firmware/MCAL/<module>/`: AUTOSAR-style API, parameter validation, config handling, standardized behavior.
- `firmware/MCAL/includes/`: public MCAL interfaces and common MCAL types.
- `firmware/main.c`: demo menu and e2e dispatch only.

Do not expose generated register names directly from MCAL headers unless there is a clear reason. Prefer a driver wrapper.

### 5. Implement In Small Vertical Slices

For each slice:

1. Update spec/register map if hardware changes are needed.
2. Regenerate code with `make gen`.
3. Implement or update low-level driver functions.
4. Implement or update MCAL API functions.
5. Add menu or e2e test path only when useful for validation.
6. Build firmware.
7. Run targeted e2e if behavior touches QEMU/SV/device model.

### 6. Interface Verification

For each MCAL API, include positive and negative checks.

Positive checks:

- Init succeeds with valid config.
- Read/write/toggle or equivalent nominal API works.
- MCAL output matches driver/hardware observable state.

Negative checks:

- Invalid channel returns the expected error.
- Null pointer behavior is specified and tested.
- Unsupported direction/mode returns an error or is explicitly documented.
- APIs used before initialization either work by design or report a development error.

For AUTOSAR-style validation, decide whether the module reports errors through `Det` or a repo-local return-code policy. If `Det` is not implemented yet, record it as a gap.

### 7. Static Analysis And Coding Rules

Recommended commercial tools for serious MCAL compliance work:

- Polyspace Bug Finder + Code Prover.
- Perforce Helix QAC / PRQA QA-C.
- LDRA Testbed.
- PC-lint Plus.

Recommended low-cost repo baseline:

- `cppcheck` for C static checks.
- `clang-tidy` or `CodeChecker` where cross-compile compilation database support is available.
- Compiler warnings: `-Wall -Wextra` plus targeted additions such as `-Wconversion` after the codebase is ready.

When running static analysis, record:

- Tool name and version.
- Command line or CI job.
- Rule set, such as MISRA C:2012 profile if available.
- Deviations and justifications.
- Open findings and owner.

### 8. Validation Commands

Use the repo's existing validation commands unless the task says otherwise:

```bash
make gen
make sv
make -C firmware clean && make fw
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

For firmware-only MCAL changes that do not touch SV/QEMU/device behavior, `make -C firmware clean && make fw` may be sufficient, but document that e2e was not run and why.

### 9. Completion Checklist

Before finishing, verify:

- Requirement matrix updated or created.
- MCAL public header added under `firmware/MCAL/includes/`.
- MCAL implementation added under `firmware/MCAL/<module>/`.
- Driver dependency is clear and isolated under `firmware/drivers/`.
- Build system includes new sources.
- Positive and negative behavior is tested or listed as TODO with rationale.
- Static-analysis recommendation or result is documented.
- `make gen`, relevant build commands, and relevant e2e commands have been run.
- No generated or build artifacts are accidentally staged unless they are tracked source-of-truth files.

## Output Format For Agent Responses

When reporting results, include:

- What MCAL module was touched.
- What AUTOSAR concept it maps to.
- What driver or hardware layer it uses.
- What requirement rows were added or updated.
- What tests/static checks were run.
- Known compliance gaps.

Keep the final summary concise, but do not omit compliance gaps.
