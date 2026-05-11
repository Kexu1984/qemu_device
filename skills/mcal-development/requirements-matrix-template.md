# MCAL Requirement Matrix Template

Use this template when developing or reviewing an AUTOSAR-style MCAL module.

| Requirement ID | Source | Requirement Summary | MCAL API / Config | Driver Dependency | Implementation | Test Evidence | Static Analysis | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|
| DIO-SWS-TODO-001 | pending official SWS lookup | Read one digital channel returns STD_HIGH/STD_LOW equivalent | `Dio_ReadChannel` or repo-local equivalent | `firmware/drivers/gpio` | `firmware/MCAL/dio/...` | unit/e2e test name | tool/report | TODO | Replace placeholder ID after SWS review |
| PORT-SWS-TODO-001 | pending official SWS lookup | Initialize pin direction from configuration | `Port_Init` | `firmware/drivers/gpio` | `firmware/MCAL/port/...` | unit/e2e test name | tool/report | TODO | Split from Dio when moving from `Mcal_Gpio` |

## Status Values

- `TODO`: requirement identified but not implemented.
- `IMPLEMENTED`: code exists, but tests are not complete.
- `TESTED`: positive tests pass.
- `NEGATIVE_TESTED`: positive and negative behavior tested.
- `DEVIATION`: intentionally different from AUTOSAR; justification required.
- `BLOCKED`: waiting for spec, SDK, model, or tool support.

## Evidence Examples

- Build: `make -C firmware clean && make fw`
- SV build: `make sv`
- E2E: `ICOUNT_SHIFT=5 bash scripts/e2e_test.sh`
- Static scan: `cppcheck --enable=all ...`
- Commercial scan: Polyspace / Helix QAC / LDRA report path

## Notes For This Repository

Current GPIO implementation is a training-friendly MCAL-style abstraction, not a certified AUTOSAR MCAL module. For closer AUTOSAR alignment, split GPIO into:

- `Port`: pin direction/mode/configuration.
- `Dio`: digital channel/port read/write APIs.

Record all gaps explicitly instead of claiming full AUTOSAR compliance.
