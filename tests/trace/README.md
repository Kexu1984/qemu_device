# Trace Requirement Checks

This directory contains L6 offline trace checks for platform requirement
coverage.

The initial checker validates the common trace contract:

```bash
python3 tests/trace/check_trace_requirements.py build/device_trace.jsonl
python3 tests/trace/check_trace_requirements.py build/device_trace.jsonl --profile platform-smoke
```

Once stable event names are agreed, require specific events with repeated
`--require-event DEV:EVENT` arguments.

The `platform-smoke` profile checks more than event presence: it also validates
representative DMA, HSM, and WDT event ordering and key success values such as
fabric status, DMA/HSM completion, Python fabric probe result, and WDT reset
reason.