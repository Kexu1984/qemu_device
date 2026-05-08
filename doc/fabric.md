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
| CPU to external register | QEMU `mmio-sockdev` | `scripts/qemu-fork/hw/misc/mmio_sockdev.c`, `device_model/mmio_device_server.py`, `sv_device/sv_host_shell.cpp`, `sv_device/sv_apb_ingress.sv` | CPU MMIO is translated into synchronous socket R/W transactions. For SV endpoints, the C++ host shell submits a host request and the APB setup/access sequencing is performed in SV. |
| Python bus-master access | Python device domain | `device_model/mmio_base.py` | `BusMasterAddressSpace` routes Python master accesses to in-process Python MMIO or to QEMU through `FabricChannel` fabric frames. |
| SV bus-master access | SV RTL domain | `sv_device/sv_device_top.sv`, `sv_device/sv_master_router.sv`, `sv_device/sv_fabric_egress_dpi.sv`, `sv_device/sv_host_shell.cpp` | SV master request/response sequencing stays in SV. SV calls timing-independent DPI functions implemented by the C++ host shell to emit `fabric-chardev` frames. |

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
| SV-owned APB peripheral window | Dispatch to the SV host shell and RTL APB decoder. |
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

## SystemVerilog Fabric Hierarchy

The SV side is best viewed as one Verilated device island. The C++ file is not
part of the bus hierarchy; it is the host shell that owns sockets, wave dump,
IRQ forwarding, and DPI functions.

```text
sv_host_shell.cpp
  host shell: sockets + Verilator clock + IRQ + DPI fabric functions
    |
    | host_req / host_rsp
    v
sv_device_top.sv
  SV device island top
    |
    +-- inbound slave path: CPU/QEMU -> SV registers
    |     sv_apb_ingress.sv
    |       host request to APB setup/access FSM
    |            |
    |            v
    |     sv_apb_decoder.sv
    |            |
    |            +-- sv_timer_apb.sv      APB slave registers
    |            +-- sv_dma_apb.sv        APB slave registers + DMA master control
    |
    +-- outbound master path: SV DMA -> platform fabric
      sv_dma_apb.sv / sv_dma_core.sv
        |
        v
      sv_master_router.sv
        |
        v
      sv_fabric_egress_dpi.sv
        SV request/response FSM, calls DPI read/write helpers
        |
        v
      sv_host_shell.cpp -> fabric-chardev -> QEMU fabric
```

In this hierarchy, `sv_device_top.sv` is the SV device-domain top. Its inbound
register window behaves as APB slaves behind `sv_apb_decoder.sv`; it is not
meant to make the C++ host shell manually drive APB pins. `sv_apb_ingress.sv`
is the SV-side ingress bridge that turns a host request from C++ into real APB
setup/access phases.

For outbound access, `sv_dma_core.sv` is the SV bus master. It sends generic
request/response transactions through `sv_master_router.sv`. The current
external target endpoint is `sv_fabric_egress_dpi.sv`, which keeps the
request/response sequencing in SV and calls timing-independent C++ DPI helpers
only when a transaction reaches the external fabric. Later, `sv_master_router.sv`
can grow local decode so an SV master can reach local SV APB windows before
falling through to the external fabric endpoint.

## Fabric Interface Reference

This section is the implementation-facing contract for adding new fabric users.
The same logical transaction shape exists in all domains, but each domain has a
different integration surface.

### QEMU-Native Interfaces

QEMU-native masters should include `hw/misc/mmio_fabric.h` and use the helper
API in `scripts/qemu-fork/hw/misc/mmio_fabric.c`. These helpers route through
QEMU's system address space with `MemTxAttrs.requester_id` set from the fabric
master ID, so native devices do not need to know whether the target is RAM,
Python MMIO, SV APB, or another QEMU-native region.

| Interface | Use |
|-----------|-----|
| `mmio_fabric_read(master_id, addr, size)` | Read 1, 2, 4, or 8 bytes and return `MmioFabricResponse { status, rdata }`. |
| `mmio_fabric_write(master_id, addr, size, data)` | Write 1, 2, 4, or 8 bytes and return `MmioFabricStatus`. |
| `mmio_fabric_read_buf(master_id, addr, buf, len)` | Read an arbitrary byte buffer; used by external fabric transports. |
| `mmio_fabric_write_buf(master_id, addr, buf, len)` | Write an arbitrary byte buffer; used by external fabric transports. |
| `mmio_fabric_ok(status)` | Test whether a status is `MMIO_FABRIC_OK`. |
| `mmio_fabric_attrs(master_id)` | Build `MemTxAttrs` with the requester ID set; use only when a caller must perform lower-level QEMU memory access directly. |

Typical native master flow:

```c
#include "hw/misc/mmio_fabric.h"
#include "hw/arm/kx6625_gen.h"

static uint32_t sysctrl_read_device(uint64_t addr)
{
    MmioFabricResponse rsp;

    rsp = mmio_fabric_read(KX6625_MASTER_ID_SYSCTRL, addr, sizeof(uint32_t));
    if (!mmio_fabric_ok(rsp.status)) {
        /* Convert fabric status to the device's own error/status register. */
        return 0;
    }
    return (uint32_t)rsp.rdata;
}

static bool sysctrl_write_device(uint64_t addr, uint32_t value)
{
    MmioFabricStatus status;

    status = mmio_fabric_write(KX6625_MASTER_ID_SYSCTRL, addr,
                               sizeof(uint32_t), value);
    return mmio_fabric_ok(status);
}
```

Guidelines for QEMU-native users:

- Use generated master ID macros from `spec/soc.yaml`, for example
  `KX6625_MASTER_ID_SYSCTRL`; do not hard-code numeric IDs.
- Use `mmio_fabric_read()` / `mmio_fabric_write()` for register-sized access
  and the `_buf()` variants for DMA-style buffers.
- Convert `MmioFabricStatus` into the native device's visible status/error
  registers instead of silently ignoring failed transactions.
- Native master devices should not call Python or SV implementation functions
  directly for modeled bus transactions.

### Python Interfaces

Python has two layers. New bus-master devices should prefer the high-level
`PlatformFabric` / `FabricMasterClient` surface. Existing DMA-style devices may
continue using `BusMasterAddressSpace`, which is the backward-compatible address
space wrapper around the same fabric channel.

| Interface | Use |
|-----------|-----|
| `FabricChannel` | Low-level TCP fabric transport to QEMU over `fabric-chardev`. It emits `F` frames and serializes socket I/O. |
| `FabricServer` | Accepts QEMU's `fabric-chardev` connection and attaches it to a `FabricChannel`. |
| `PlatformFabric` | Absolute-address fabric dispatcher for Python masters. It routes local Python MMIO in-process and external windows through `FabricChannel`. |
| `PlatformFabric.client(master_id, name)` | Create a per-master `FabricMasterClient` facade with a fixed master ID. |
| `FabricMasterClient.read(addr, size)` / `write(addr, data)` | Byte-oriented absolute-address read/write returning `FabricResponse`. |
| `FabricMasterClient.read32(addr)` / `write32(addr, value)` | Convenience helpers for 32-bit register access. |
| `BusMasterAddressSpace.read(addr, length)` / `write(addr, data)` | Legacy-compatible bus-master address-space API used by DMA/HSM/flash models. |
| `MMIODevice.read(offset, size, master_id)` / `write(offset, size, data, master_id)` | Python slave endpoint API. The bus passes endpoint-local offsets plus the requesting master ID. |

Typical high-level Python master:

```python
from device_model.fabric import FabricMasterClient


class ExamplePythonMaster:
    def __init__(self, fabric: FabricMasterClient) -> None:
        self._fabric = fabric

    def probe(self, addr: int) -> bool:
        value, read_rsp = self._fabric.read32(addr)
        if not read_rsp.ok:
            return False

        write_rsp = self._fabric.write32(addr + 4, value ^ 0xFFFF_FFFF)
        return write_rsp.ok
```

Typical Python-domain wiring:

```python
fabric_channel = FabricChannel(master_id=MASTER_ID_DMA)
fabric_server = FabricServer(port=7897, fabric_channel=fabric_channel)

fabric = PlatformFabric(
    fabric_channel=fabric_channel,
    local_bus=bus,
    local_regions=[FabricRegion('python_mmio', 0x40004000, 0x6000, 'python')],
    memory_regions=[FabricRegion('sram', 0x20000000, 0x20000, 'qemu_memory')],
    tracer=tracer,
)

master = ExamplePythonMaster(
    fabric.client(MASTER_ID_PY_FABRIC_DEMO, 'py_fabric_demo')
)
```

Typical legacy-compatible DMA-style wiring:

```python
addr_space = BusMasterAddressSpace(
    fabric_channel=fabric_channel,
    mmio_bus=bus,
    mmio_regions=[(0x40000000, 0x00100000)],
    master_id=MASTER_ID_DMA,
)

data = addr_space.read(src_addr, length)
if data is not None:
    ok = addr_space.write(dst_addr, data)
```

Guidelines for Python users:

- Use `FabricMasterClient` for new fabric-aware masters; use
  `BusMasterAddressSpace` when integrating with an existing DMA-like model that
  already expects an address-space object.
- Use generated constants from `device_model/generated/device_consts.py` for
  master IDs and addresses.
- Check `FabricResponse.ok` or the boolean/`None` result from lower-level
  address-space helpers; do not assume cross-domain transport is always present.
- Same-domain Python MMIO should stay in-process through `PlatformFabric` or
  `BusMasterAddressSpace`, which avoids socket reentrancy and unnecessary QEMU
  round trips.

### SystemVerilog Interfaces

The SV side has separate ingress and egress interfaces. Ingress is for
CPU/QEMU-originated register access into SV APB slaves. Egress is for SV bus
masters, such as DMA, that initiate transactions to the platform fabric.

#### Host-to-SV APB Ingress

`sv_host_shell.cpp` accepts QEMU's MMIO R/W socket requests and drives the
`host_req` / `host_rsp` pins on `sv_device_top.sv`. SV APB timing is owned by
`sv_apb_ingress.sv`.

```text
host_req_valid
host_req_ready
host_req_write
host_req_addr[11:0]
host_req_size[2:0]
host_req_wdata[31:0]
host_rsp_valid
host_rsp_rdata[31:0]
host_rsp_error
```

Usage rules:

- `sv_host_shell.cpp` asserts `host_req_valid` when `host_req_ready` is high.
- `sv_apb_ingress.sv` latches the request, performs APB setup/access phases,
  and pulses `host_rsp_valid` when `pready` is observed.
- Current SV APB register access is 32-bit; `sv_apb_ingress.sv` reports an
  error when `host_req_size` is not `3'b010`.
- New SV APB slaves should connect behind `sv_apb_decoder.sv`, not directly to
  C++.

#### SV Master Request/Response Port

SV bus masters should use the generic request/response interface already used
between `sv_dma_core.sv`, `sv_master_router.sv`, and
`sv_fabric_egress_dpi.sv`:

```text
req_valid
req_ready
req_write
req_addr[31:0]
req_wdata[31:0]
req_size[2:0]
rsp_valid
rsp_rdata[31:0]
rsp_error
```

Typical SV master behavior:

```systemverilog
// Request phase
if (start && req_ready_i) begin
    req_valid_o <= 1'b1;
    req_write_o <= 1'b0;
    req_addr_o  <= source_addr;
    req_size_o  <= 3'b010; // 32-bit
end

// Response phase
if (rsp_valid_i) begin
    if (rsp_error_i) begin
        error_q <= 1'b1;
    end else begin
        read_data_q <= rsp_rdata_i;
    end
end
```

Usage rules:

- `sv_master_router.sv` is the stable integration point for SV masters. New SV
  masters should connect to the router or to an arbitration layer in front of
  it, not to DPI functions directly.
- `sv_fabric_egress_dpi.sv` is the current external endpoint. It accepts one
  request, calls `sv_fabric_read32()` or `sv_fabric_write32()`, and returns a
  response one SV cycle later so requester FSMs observe a clean response phase.
- Current DPI egress supports 32-bit accesses only. Wider or byte-lane aware
  transactions should extend the SV request port and the DPI helper contract
  together.
- SV RTL should treat `rsp_error` as a bus error and reflect it into its own
  status/error registers.

#### C++ DPI Boundary

The only SV-to-host fabric calls are the timing-independent DPI helpers
implemented in `sv_host_shell.cpp`:

```systemverilog
import "DPI-C" function longint unsigned sv_fabric_read32(input int unsigned addr);
import "DPI-C" function int sv_fabric_write32(input int unsigned addr,
                                              input int unsigned data);
```

`sv_fabric_read32()` returns `{status_or_error_bits, data[31:0]}` in a 64-bit
value: upper bits zero means success, non-zero means error. `sv_fabric_write32()`
returns `1` on success and `0` on error. These functions are an implementation
boundary for `sv_fabric_egress_dpi.sv`; ordinary SV device logic should use the
request/response port instead of importing DPI directly.

Guidelines for SV users:

- Add APB slave registers under `sv_apb_decoder.sv` for CPU-visible SV devices.
- Add bus-master logic with the generic request/response port and route through
  `sv_master_router.sv`.
- Keep local SV-to-SV decode in SV when possible; use `sv_fabric_egress_dpi.sv`
  only when the target is outside the Verilated device island.
- Keep C++ host-shell code limited to sockets, Verilator clocking, IRQ/waveform
  plumbing, and timing-independent DPI fabric helpers.

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

## Current Integration State

The fabric is now the shared bus-master transport for QEMU-native, Python, and
SystemVerilog master flows. The old memory-only `M` packet and `mem-chardev`
property have been removed from the runtime ABI.

Completed integration points:

1. Generated master IDs are defined from `spec/soc.yaml` and emitted for
  firmware/Python/QEMU use.
2. QEMU-native masters use `mmio_fabric_read()` / `mmio_fabric_write()` with
  generated master IDs, for example SYSCTRL using `KX6625_MASTER_ID_SYSCTRL`.
3. External Python/SV master traffic reaches QEMU through `fabric-chardev` and
  the `F` frame.
4. Python masters use `PlatformFabric`, `FabricMasterClient`, or the existing
  `BusMasterAddressSpace` wrapper, all carrying explicit master IDs.
5. SV ingress and egress transaction sequencing live in SV: `sv_apb_ingress.sv`
  owns host-to-APB timing, and `sv_fabric_egress_dpi.sv` owns SV-master
  response timing before crossing the C++ DPI boundary.
6. Regression coverage proves Python-to-Python fabric access, Python-to-SV
  register access, QEMU-native SYSCTRL fabric access, and SV DMA access to
  QEMU fabric memory windows.

Known remaining polish:

- `sv_master_router.sv` is still a pass-through point for external fabric
  access. It is intentionally the place to add local SV target decode or
  arbitration when multiple SV masters/targets appear.
- The runnable wire frame still uses an 8-bit reserved `flags` byte. The
  logical 32-bit sideband field should be introduced in a future protocol
  revision when access policy or debug/protection attributes need it.
- A dedicated SV-master-to-Python-register regression would further prove the
  opposite cross-domain MMIO direction. Current e2e coverage proves SV master
  fabric access through SRAM and Python master access into SV registers.

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
- `sv_device/sv_apb_ingress.sv` performs APB setup/access sequencing for
  host-originated CPU MMIO requests into the SV device window.
- `sv_device/sv_fabric_egress_dpi.sv` performs SV bus-master request/response
  sequencing and calls timing-independent DPI helpers for external fabric
  read/write operations.
- `sv_device/sv_host_shell.cpp` is now primarily a socket, Verilator clock,
  IRQ, waveform, and DPI host-function shim. It no longer owns APB or AHB
  transaction state machines; it only sends fabric frames with
  `MASTER_ID_SV_DMA` when called by SV DPI.
- `scripts/qemu-fork/hw/arm/kx6625.c` routes SYSCTRL DEVCTL and secure-boot
  device-register transactions through `mmio_fabric` with
  `KX6625_MASTER_ID_SYSCTRL`.
- `sv_device/sv_fabric_router.sv` records the SV request/response port contract
  as a reusable reference for future router/decode expansion.

The demo master currently proves Python-master-to-Python-slave register access
by driving the CRC peripheral through the fabric on the first Python tick. It
also performs the first Python-to-SV proof by reading `SV_TIMER_DMA_ID_REG`
through QEMU fabric decode and expecting `0x414D4453` (`"SDMA"`). QEMU e2e also
proves that SYSCTRL native accesses and Python/SV external master accesses
continue to work through the QEMU fabric helper.

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
