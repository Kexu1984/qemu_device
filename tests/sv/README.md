# SV Platform Tests

L4 SystemVerilog/Verilator platform tests.

First targets:

- APB ingress request/response sequencing.
- SV APB decoder behavior.
- `sv_master_router.sv` request routing.
- `sv_fabric_egress_dpi.sv` fabric handoff behavior.
- SV IRQ forwarding and software-controlled reset behavior.

SV-local timing evidence should use SV cycles/ticks and should not imply
cycle-accurate alignment with QEMU virtual time.

The first executable tests are source-level bridge contract tests. They are not
a replacement for Verilator testbenches, but they protect the current APB,
router, DPI fabric, IRQ, and local reset integration contract.

Run:

```bash
python3 -m pytest tests/sv
```