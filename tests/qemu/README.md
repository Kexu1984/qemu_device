# QEMU Platform Tests

L3 QEMU-native platform tests.

First targets:

- `mmio_fabric.c` requester ID propagation and OK/ERROR response behavior.
- `mmio_sockdev.c` R/W, IRQ, tick, reset, and fabric plumbing.
- SYSCTRL/CRU native master paths that should use modeled fabric access.

The first executable tests are source-level contract tests. They are not a
replacement for qtest or C coverage, but they are fast checks that protect the
fabric, timing, IRQ, reset, and transport contracts while QEMU coverage
infrastructure is being selected.

Run:

```bash
python3 -m pytest tests/qemu
```