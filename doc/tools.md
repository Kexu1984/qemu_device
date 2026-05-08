# Tools

This document is the entry point for development tools used by the KX6625 QEMU prototype. It explains what each tool is for and when to run it. Device register details belong in `spec/`; SoC-level design rules belong in `doc/architecture.md`; QEMU/Python/SV timing boundaries belong in `doc/timing.md`.

## Common Commands

| Task | Command |
|------|---------|
| Generate constants from specs | `make gen` |
| Build firmware | `make fw` |
| Build QEMU fork | `SKIP_APT=1 bash scripts/build_qemu.sh` |
| Run deterministic e2e test | `ICOUNT_SHIFT=5 bash scripts/e2e_test.sh` |
| Run interactive system | `ICOUNT_SHIFT=5 bash scripts/run_interactive.sh` |
| Visualize trace | `python3 scripts/visualize_trace.py build/device_trace.jsonl build/trace_report.html` |

Use `ICOUNT_SHIFT=5` for deterministic chip-virtual-time runs unless a test explicitly needs realtime behavior.

## Code Generation

### `scripts/gen_device_code.py`

Reads the YAML specs in `spec/` and generates shared constants for firmware and Python.

Typical use:

```bash
make gen
```

Generated outputs include:

- `device_model/generated/device_consts.py`
- `build/generated/mmio_devices.h`

Run this after changing device specs, memory maps, IRQ assignments, register offsets, or generated SoC constants.

## Firmware Build

### `firmware/Makefile`

Builds the Cortex-M firmware image used by QEMU.

Typical use:

```bash
make fw
```

Important outputs:

- `build/firmware.elf`
- `build/firmware.hex`

The HEX file is the input for flash preload and secure-boot OTP signing.

## QEMU Build

### `scripts/build_qemu.sh`

Configures and builds the local QEMU fork under `scripts/qemu-fork/`.

Typical use in an already prepared environment:

```bash
SKIP_APT=1 bash scripts/build_qemu.sh
```

Important output:

- `scripts/qemu-fork/build/qemu-system-arm`

Use this after changing QEMU machine code, `mmio-sockdev`, or other files under the fork.

Note: `scripts/qemu-fork/` is ignored by default. Intentional source changes inside the fork must be force-added with git, for example:

```bash
git add -f scripts/qemu-fork/hw/arm/kx6625.c scripts/qemu-fork/hw/misc/mmio_sockdev.c
```

## Secure Boot OTP Preparation

### `scripts/secure_boot_otp.py`

Computes the secure-boot AES-CMAC for the firmware HEX image and installs OTP rows needed by SYSCTRL secure boot.

Typical use:

```bash
python3 scripts/secure_boot_otp.py --firmware-hex build/firmware.hex --otp build/otp.hex --fresh
```

The tool currently:

- Builds a fixed 512 KB flash image initialized to `0xFF`.
- Applies the Intel HEX contents to that image.
- Computes AES-CMAC using secure boot key0.
- Programs OTP key rows, boot metadata rows, and expected CMAC rows.
- Preserves OTP 1-to-0 programming semantics.

`e2e_test.sh` and `run_interactive.sh` call this tool before launching QEMU.

## Python Device Server

### `device_model/mmio_device_server.py`

Starts the socket-backed Python SoC model. It exposes MMIO, IRQ, tick, fabric bus-master, reset, and terminal channels consumed by QEMU `mmio-sockdev` instances.

Most users should start it through:

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

Direct invocation is useful while debugging Python devices, transport behavior, or trace output.

## SystemVerilog Host Shell

The SystemVerilog prototype is built and run through the scripts used by e2e and interactive flows. It provides RTL-style APB devices behind a QEMU `mmio-sockdev` instance.

Use this path when validating:

- APB register semantics.
- SV-local state machines and clocks.
- SV-generated IRQs into QEMU/NVIC.
- Comparison against Python functional behavior.

The SV host shell is intentionally a transaction boundary. It does not make the full platform cycle accurate.

## Run Scripts

### `scripts/e2e_test.sh`

Full deterministic smoke test. It builds or prepares the needed runtime pieces, starts Python devices, starts SV devices, launches QEMU with the firmware HEX image, checks firmware output, and generates a trace report.

Typical use:

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

Use this before pushing larger platform changes.

### `scripts/run_interactive.sh`

Starts the same platform in an interactive mode for manual inspection.

Typical use:

```bash
ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

Use this while iterating on firmware output, device behavior, or manual debug.

### `scripts/uart_console.py`

Connects to the UART terminal channel exposed by the Python UART model. This is useful when a run script leaves the platform up for interactive observation.

## Trace and Visualization

### `device_model/tracer.py`

Records device events into JSONL without blocking device execution.

Typical trace output:

- `build/device_trace.jsonl`

### `scripts/visualize_trace.py`

Converts the JSONL trace into a self-contained HTML report.

Typical use:

```bash
python3 scripts/visualize_trace.py build/device_trace.jsonl build/trace_report.html
```

Typical output:

- `build/trace_report.html`

Use this to inspect device ordering, virtual timestamps, IRQs, DMA operations, WDT reset behavior, HSM/OTP behavior, and cross-model interactions.

## QEMU Runtime Knobs

Important environment variables:

| Variable | Purpose |
|----------|---------|
| `ICOUNT_SHIFT` | Enables QEMU `-icount`; `5` is the recommended deterministic mode |
| `SKIP_APT` | Skips package installation in QEMU build script when dependencies are already installed |

Recommended default:

```bash
ICOUNT_SHIFT=5
```

## Validation Expectations

For changes that affect specs, firmware, QEMU, Python models, SV host shell, boot, reset, security, or timing, run the narrowest useful validation and then the e2e test when practical.

Typical full validation sequence:

```bash
make gen
make fw
SKIP_APT=1 bash scripts/build_qemu.sh
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

For documentation-only changes, at minimum inspect the changed Markdown and keep links relative.
