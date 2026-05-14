# Platform Test Framework

This directory contains requirement-based tests for the simulation platform
core. It is organized by test layer from `doc/platform_test_plan.md`.

## Layout

| Directory | Layer | Purpose |
|-----------|-------|---------|
| `python/` | L1/L2 | Fast Python unit tests and socket protocol harness tests. |
| `qemu/` | L3 | QEMU-native source/contract tests and future qtest or host-helper tests. |
| `sv/` | L4 | SV/Verilator bridge source/contract tests and future simulation tests. |
| `e2e/` | L5 | Offline assertions over full e2e artifacts produced by `scripts/e2e_test.sh`. |
| `trace/` | L6 | Offline trace requirement assertions over `build/device_trace.jsonl`. |

## First-Phase Commands

```bash
python3 -m pytest tests/python
python3 -m pytest tests/qemu tests/sv
python3 -m pytest tests/e2e tests/trace
python3 tests/trace/check_trace_requirements.py build/device_trace.jsonl --profile platform-smoke
```

Unified functional regression entry points:

```bash
bash tests/run_platform_regression.sh fast
bash tests/run_platform_regression.sh artifact
bash tests/run_platform_regression.sh full
```

`fast` runs local L1-L4/L6 checks. `artifact` validates the latest e2e output
under `build/`. `full` rebuilds the platform, runs `scripts/e2e_test.sh`, then
validates e2e artifacts and trace sequences.

For coverage-oriented Python runs:

```bash
python3 -m coverage run -m pytest tests/python
python3 -m coverage report --show-missing
```

Numeric line/branch coverage is a supporting diagnostic. The acceptance target
for platform core work is functional requirement evidence: unit behavior,
transport behavior, integrated e2e results, and trace event/sequence checks.

Each test module should list the requirement IDs it covers in a module-level
`REQUIREMENTS` tuple. Keep `doc/platform_requirement_test_matrix.md` aligned
when adding, renaming, or retiring tests.