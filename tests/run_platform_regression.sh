#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-fast}"

run_fast() {
    python3 -m compileall device_model tests scripts/*.py
    python3 -m pytest tests/python tests/qemu tests/sv tests/trace
}

run_artifact_checks() {
    python3 -m pytest tests/e2e tests/trace
    if [[ -f build/device_trace.jsonl ]]; then
        python3 tests/trace/check_trace_requirements.py build/device_trace.jsonl --profile platform-smoke
    else
        echo "build/device_trace.jsonl not found; skipping trace profile check" >&2
    fi
}

case "${MODE}" in
    fast)
        run_fast
        ;;
    artifact)
        run_artifact_checks
        ;;
    full)
        make gen
        make sv
        make -C firmware clean
        make fw
        ICOUNT_SHIFT="${ICOUNT_SHIFT:-5}" bash scripts/e2e_test.sh
        run_artifact_checks
        ;;
    *)
        echo "usage: $0 [fast|artifact|full]" >&2
        exit 2
        ;;
esac