# Bus Fabric Design

This document describes the bus-fabric direction for the KX6625 QEMU prototype.
It focuses on cross-domain register and memory access between QEMU-native,
Python, and SystemVerilog devices. Device register maps remain in `spec/`;
timing-domain details remain in `doc/timing.md`.

The design goal is to make bus-master behavior explicit and stable. A device
model should be able to become a master without learning whether the target is
implemented in Python, SystemVerilog, or native QEMU code.

## Current Structure

The platform currently has three related but not fully unified access paths.

| Path | Current owner | Main files | Behavior |
|------|---------------|------------|----------|
| CPU to external register | QEMU `mmio-sockdev` | `scripts/qemu-fork/hw/misc/mmio_sockdev.c`, `device_model/mmio_device_server.py`, `sv_device/sv_timer_bridge.cpp` | CPU MMIO is translated into synchronous socket R/W transactions toward a Python or SV endpoint. |
| Python bus-master access | Python device domain | `device_model/mmio_base.py` | `BusMasterAddressSpace` routes Python master accesses to in-process Python MMIO or to QEMU through `FabricChannel` fabric frames. |
| SV bus-master access | SV bridge | `sv_device/sv_device_top.sv`, `sv_device/sv_master_router.sv`, `sv_device/sv_timer_bridge.cpp` | SV master requests leave through an AHB-like adapter and are serviced by the bridge as `fabric-chardev` fabric frames. |

This is good enough for local device validation, but it leaves a gap for
cross-domain SoC behavior:

- A Python device cannot cleanly access an SV register through the modeled bus.
- An SV device cannot cleanly access a Python register through the modeled bus.
- Native QEMU master devices need a stable path that does not depend on private
  Python or SV implementation details.
- Memory and peripheral access are represented by different transports instead
  of one decoded platform transaction path.

## Target Model

The target architecture is a functional platform fabric with explicit masters,
slaves, decode, and bridges.

```text
                 CPU MMIO
                    |
QEMU native master --+        +-----------------------+
Python APB master ---+------->| Platform APB Fabric   |
SV APB master -------+        | decode + policy + log |
                             +-----------+-----------+
                                         |
       +---------------------------------+-------------------------------+
       |                                 |                               |
Python APB slave windows       SV APB slave windows          APB-to-AHB bridge
       |                                 |                               |
Python MMIODevice models       Verilated RTL APB blocks      QEMU RAM / flash /
                                                               modeled AHB slaves
```

The APB fabric is the stable peripheral transaction surface. The AHB side is
the stable memory/system-bus surface. An APB master may reach memory through an
APB-to-AHB bridge, but this remains a functional model, not a cycle-accurate
claim about a real APB memory datapath.

## Transaction Contract

All masters should use the same logical transaction shape, independent of the
implementation language.

```text
read(master_id, address, size) -> data, response
write(master_id, address, size, data) -> response
```

Required fields:

| Field | Purpose |
|-------|---------|
| `master_id` | Identifies CPU0, CPU1, SYSCTRL, Python device masters, SV device masters, and future QEMU-native masters. |
| `address` | Absolute SoC physical address. Masters do not pass endpoint-local offsets. |
| `size` | Access width in bytes. Initial support should preserve the current 1/2/4-byte MMIO behavior and 32-bit SV register access. |
| `data` | Write payload in little-endian byte order. |
| `response` | Current implementation uses OK/ERROR. The encoding should reserve values for decode error, access-policy error, timeout, disconnected target, and slave error. |
| `sideband` | Reserved 32-bit metadata field for simulated bus attributes such as secure/non-secure, privilege, QoS, cacheability, protection, or debug access. It is defined for forward compatibility and is not interpreted by the current prototype. |

The contract intentionally uses absolute addresses. That keeps master-device
code stable when a target moves between Python, SV, or QEMU-native ownership.

## Master IDs

Master IDs are part of the architectural interface. They should be allocated in
one place and propagated through traces, access policy checks, and socket
protocols.

Current IDs:

| Master | ID | Notes |
|--------|----|-------|
| CPU0 | `0x00` | Main FreeRTOS core. |
| CPU1 | `0x01` | Secondary core. |
| DMA | `0x10` | Python DMA controller. |
| HSM | `0x11` | Python HSM internal DMA master. |
| FLASH_CTRL | `0x12` | Python flash-controller bus master. |
| PY_FABRIC_DEMO | `0x13` | Python fabric demo master. |
| SV_DMA | `0x20` | SystemVerilog DMA prototype master. |
| SYSCTRL | `0xF0` | QEMU-native system controller and pre-CPU flows. |
| QEMU_INTERNAL | `0xFE` | Generic QEMU internal access with no explicit SoC master. |
| UNKNOWN | `0xFF` | Fallback for unattributed access. |

Recommended ranges:

| Range | Intended use |
|-------|--------------|
| `0x00`-`0x0F` | CPU and architectural core masters. |
| `0x10`-`0x1F` | Python-modeled bus masters. |
| `0x20`-`0x5F` | SystemVerilog-modeled bus masters. |
| `0x60`-`0xDF` | QEMU-native non-CPU masters and future modeled infrastructure masters. |
| `0xE0`-`0xFF` | Privileged, debug, test, and fallback/system-control masters. |

New master devices must request a named ID in `spec/soc.yaml`. The generator
then emits matching Python constants and QEMU C macros, including QEMU-native
IDs such as `KX6625_MASTER_ID_SYSCTRL`. Model code should include/import those
generated definitions rather than hard-coding numeric values.

## Decode Rules

The fabric should decode by absolute address, not by source domain.

| Address class | Target path |
|---------------|-------------|
| Python-owned APB peripheral window | Dispatch to `PeripheralBus` / `MMIODevice`. |
| SV-owned APB peripheral window | Dispatch to the SV bridge and RTL APB decoder. |
| QEMU-native peripheral window | Dispatch through QEMU's address space as a native MMIO access. |
| SRAM, flash, instruction memory, data memory, and other AHB memory windows | Dispatch through the APB-to-AHB bridge to QEMU physical memory or a modeled AHB slave. APB masters are allowed to reach the full modeled AHB memory map unless a generated policy entry explicitly denies the access. |
| Unmapped window | Return a decode error and trace the failed access. |

The decode table should be generated from `spec/` where possible. Each entry
should describe base address, size, owner domain, access width limits, and any
allowed-master policy.

## Stable Interface for New Masters

Adding a new master should be mechanical and should not require changes in
target devices.

### Python Master Device

A Python device should receive a fabric client object during construction:

```python
class ExampleDevice(MMIODevice):
    def __init__(self, fabric, master_id: int, ...):
        self._fabric = fabric
        self._master_id = master_id

    def start_transfer(self) -> None:
        data, rsp = self._fabric.read(self._master_id, addr, size)
        rsp = self._fabric.write(self._master_id, addr, size, payload)
```

The existing `BusMasterAddressSpace` can evolve into this fabric client. Its
public behavior should remain simple: absolute-address read/write with no
target-domain knowledge in the device model.

### SystemVerilog Master Device

An SV master should use a small stable request/response interface inside the
RTL domain:

```text
req_valid
req_ready
req_write
req_addr
req_size
req_wdata
rsp_valid
rsp_rdata
rsp_error
```

This is close to the current `sv_dma_core` to `sv_master_router` interface.
The router should remain the stable local integration point. It can later grow
decode for local SV APB windows and forward all other requests to the bridge.
SV device logic should not know whether a target is Python, QEMU-native, or
memory behind APB-to-AHB.

### QEMU-Native Master Device

A QEMU-native block should use a helper API that mirrors the same contract:

```c
uint64_t fabric_read(void *fabric, uint8_t master_id, uint64_t addr,
                     unsigned size, int *response);
int fabric_write(void *fabric, uint8_t master_id, uint64_t addr,
                 uint64_t data, unsigned size);
```

This keeps QEMU-native SYSCTRL-style flows hardware-like. A native block should
not call Python or SV implementation functions directly when the behavior is a
bus transaction.

## Stable Interface for New Slaves

Adding a new slave should only require a spec entry, an implementation endpoint,
and registration with the fabric.

| Slave owner | Required surface |
|-------------|------------------|
| Python | `MMIODevice.read(offset, size, master_id)` and `write(offset, size, data, master_id)`. |
| SV | APB slave signals behind the SV APB decoder. |
| QEMU-native | QEMU `MemoryRegionOps` plus fabric registration metadata. |
| AHB memory/slave | QEMU physical memory or a modeled AHB target behind the APB-to-AHB bridge. |

Slave implementations receive endpoint-local offsets. The fabric performs the
absolute-address decode and subtracts the selected base address.

## Transport Direction

The external bus-master channel is a fabric transaction channel. Python and SV
masters use the explicit fabric frame; the older `M` packet shape has been
removed from QEMU and is no longer part of the project ABI.

Current fabric frame:

```text
Write request:
'F' | 'W' | master_id(1) | flags(1) | address(64 LE) | length(32 LE) | data

Write response:
status(1)

Read request:
'F' | 'R' | master_id(1) | flags(1) | address(64 LE) | length(32 LE)

Read response:
status(1) | data(length)
```

Status values match the QEMU-side `MmioFabricStatus` values. On read error,
QEMU returns a non-zero status and zero-filled data so the stream remains
self-synchronising. `flags` is reserved and currently must be zero.

The logical protocol also reserves a 32-bit `sideband` field for future
simulation of bus attributes such as secure/non-secure, privilege, QoS,
cacheability, and debug access. The current runnable frame keeps the existing
8-bit reserved `flags` byte for compatibility with the prototype; the next wire
revision should replace or extend it with `sideband(32 LE)` while leaving the
current value zero until a device or policy model consumes it.

The important semantic change is that the receiver decodes the address across
the whole platform, not only QEMU RAM. MMIO is therefore a slave class under the
fabric rather than the fabric itself: CPU MMIO, Python `MMIODevice`, SV APB
slaves, QEMU-native `MemoryRegionOps`, and AHB memory windows are all targets
behind the same address-based transaction model.

## Deadlock and Reentrancy Rules

Cross-domain bus access must avoid synchronous cycles that wait on themselves.

Rules:

- Same-domain accesses should use direct dispatch when possible. Python master
  to Python slave can call `PeripheralBus` in-process instead of routing through
  QEMU and back to Python.
- SV local APB windows should be decoded in the SV router when the requesting
  master and target are inside the same Verilated design.
- Cross-domain accesses should have one outstanding transaction per bridge
  channel unless the protocol explicitly adds tags.
- A bridge must return a timeout or bus error rather than block forever when a
  target endpoint is disconnected.
- Trace every cross-domain request with source master, address, target domain,
  operation, response, and latency in host/virtual terms where available.

## Timing Model

Fabric transactions are functional transaction boundaries.

- CPU MMIO remains synchronous from the guest instruction point of view.
- Python devices continue to use QEMU virtual time and DES ticks for modeled
  hardware completion.
- SV devices continue to keep local Verilator cycles.
- A fabric transaction may spend host wall-clock time crossing a socket, but
  that does not automatically advance guest virtual time.
- Any modeled bus latency should be explicit metadata or a scheduled device
  event, not an accidental side effect of TCP latency.

## Initial Implementation Plan

The fabric can be introduced without rewriting every device at once.

1. Define generated fabric metadata from `spec/`: address ranges, owner domain,
   slave type, allowed masters, and access width constraints.
2. Rename or wrap `BusMasterAddressSpace` as the Python fabric client while
   preserving existing DMA/HSM/flash users.
3. Add a QEMU-side fabric helper for native masters such as SYSCTRL.
4. Extend the SV bridge with a bus transaction channel or extend the current
   memory channel into address-decoded fabric access.
5. Teach `sv_master_router.sv` to decode local SV windows first and forward
   external windows to the bridge.
6. Add a focused Python-to-SV proving regression first: a Python APB master
  should read the SV DMA ID register at `SV_TIMER_DMA_ID_REG` and observe
  `0x414D4453` (`"SDMA"`). Follow-on regressions should cover one SV master
  accessing a Python register and both domains accessing SRAM through the
  APB-to-AHB path.

## Prototype Status

The first runnable prototype keeps the existing CPU-to-device transports intact
and adds both Python-side and QEMU-side fabric runtime pieces:

- `device_model/fabric.py` defines `PlatformFabric`, `FabricRegion`, response
  status, and per-master clients.
- `device_model/fabric_master_demo.py` defines a tick-driven Python master with
  master ID `MASTER_ID_PY_FABRIC_DEMO`.
- `device_model/soc_top.py` wires the fabric into the default Python device
  domain and registers the Python master as a shared tick observer.
- `scripts/qemu-fork/include/hw/misc/mmio_fabric.h` and
  `scripts/qemu-fork/hw/misc/mmio_fabric.c` define the QEMU-native fabric
  helper used by KX6625 native masters and external bus-master transports.
- `scripts/qemu-fork/hw/misc/mmio_sockdev.c` accepts `fabric-chardev` traffic
  using the `F` frame above and routes it through `mmio_fabric`. The legacy
  `mem-chardev` property and `M` packet parser have been removed.
- `device_model/mmio_base.py` exposes `FabricChannel`, which emits fabric frames
  with per-request master IDs.
- `sv_device/sv_timer_bridge.cpp` emits fabric frames with `MASTER_ID_SV_DMA`
  for SV AHB master accesses.
- `scripts/qemu-fork/hw/arm/kx6625.c` routes SYSCTRL DEVCTL and secure-boot
  device-register transactions through `mmio_fabric` with
  `KX6625_MASTER_ID_SYSCTRL`.
- `sv_device/sv_fabric_router.sv` records the SV request/response port contract
  but is not yet used by `sv_device_top.sv`.

The demo master currently proves Python-master-to-Python-slave register access
by driving the CRC peripheral through the fabric on the first Python tick. It
also performs the first Python-to-SV proof by reading `SV_TIMER_DMA_ID_REG`
through QEMU fabric decode and expecting `0x414D4453` (`"SDMA"`). QEMU e2e also
proves that SYSCTRL native accesses and Python/SV external master accesses
continue to work through the QEMU fabric helper. The next integration step is
the opposite cross-domain direction: an SV master reaching a Python register
through QEMU fabric decode.

## Review Questions

The following decisions close the current review questions:

- APB masters may access the full modeled AHB memory map, including instruction
  memory, data memory, SRAM, and flash windows. Restrictions should be expressed
  as generated fabric policy, not as an implicit bridge aperture.
- Master IDs are defined in `spec/soc.yaml` and generated for all languages.
  QEMU-native IDs also come from the generated QEMU header, so native devices use
  macros such as `KX6625_MASTER_ID_SYSCTRL` instead of local numeric constants.
- The first status model remains OK/ERROR. The protocol reserves additional
  status values for decode error, slave error, permission denied, timeout, and
  disconnected target.
- Python-to-SV is the first cross-domain target-routing proof. Use a Python APB
  master to read a stable SV register such as `SV_TIMER_DMA_ID_REG` before
  expanding to SV-to-Python access.
- Reserve 32 bits of protocol sideband metadata for future simulated bus signals
  such as secure/non-secure, privilege, QoS, cacheability, protection, and debug
  attributes. Keep the field zero and uninterpreted until a policy or target
  model needs it.
