# Reset Architecture

This document describes the reset model for the KX6625 prototype environment,
covering the reset hierarchy, retention register policy, the CRU peripheral
design, and the notification mechanism between the native QEMU CRU and the
external device models (Python and SystemVerilog).

Read this document before implementing the native CRU block or modifying
`SystemResetManager`.

---

## 1. Reset Philosophy

Hardware reset has two very different jobs:

1. **Bring a block back to a known register state** so it behaves predictably
   after the reset event.
2. **Communicate why the reset happened** so that firmware can decide whether
   to re-initialize fully or resume from a saved context.

In this simulation environment the split is cleanly modeled:

- The **QEMU CPU** is reset by sending a byte over the `rst-chardev` TCP
  channel to `mmio-sockdev`, which calls `qemu_system_reset_request()`.  The
  CPU vector-fetches from address `0x00000000` just as it would on real
  silicon after a chip reset.
- The **Python device models** are reset by calling `on_reset()` on each
  device instance.  The Python *process itself* continues running across a
  system-level reset, which is what makes retention registers possible: they
  are Python instance variables that `on_reset()` deliberately leaves
  untouched.
- The **CRU** is a **native QEMU block** (like SYSCTRL), not a Python socket
  device.  Its registers are implemented in C.  This is the only design that
  can intercept accesses to *all* device types — Python-backed and
  SystemVerilog-backed — before they are forwarded over TCP, because both
  device types are accessed through `mmio-sockdev` in QEMU.  A Python-side
  guard would never see accesses destined for the SV host shell.
- When CRU RST_N bits change, native CRU sends explicit reset-notification
  messages over dedicated TCP channels to the Python device server and the SV
  bridge respectively.  Neither backend needs to track CRU register state
  internally.

---

## 2. Reset Tree

```
                    ┌──────────────────────────────────────┐
                    │         RESET HIERARCHY               │
                    └──────────────────────────────────────┘

  Level 0 ─ Global / Power-On Reset (POR)
  ────────────────────────────────────────────────────────────────
  Trigger  : QEMU + Python process restart (e.g. fresh `make qemu`)
  Scope    : Everything, including retention registers
  QEMU     : Fresh QEMU process; CPU starts at reset vector
  Python   : Fresh process; all device __init__ values active
  Retention: Cleared (process does not persist across POR)
  RESET_REASON → 0x00 (POR)

  Level 1 ─ System Reset  (CPU + all peripherals)
  ────────────────────────────────────────────────────────────────
  Python server stays running; QEMU CPU is reset via rst-chardev.
  All volatile device registers are cleared; retention registers survive.

  Scope of volatile state cleared by Level-1:
    • All socket-backed devices: registers → hardware reset values, in_reset/clk_en state → 0
    • CRU volatile registers (CLK_EN0/1, RST_CTRL0/1, PLL_CTRL, CLK_DIV0) → cleared to 0
      CRU.RESET_REASON is NOT cleared (it is a retention register, Level-0 only)
    • SYSCTRL volatile registers (RESET_CTRL, CPU_CTRL, CPU_STATUS, BOOT_MODE) → cleared
      SYSCTRL.RESET_STATUS bit0 (POR_SEEN) survives as it reflects a Level-0 event

  AND relationship: Level-1 reset is a strict subset of Level-0 POR in terms of scope.
  POR clears everything Level-1 clears, plus all retention registers.
  Level-1 does NOT clear: WDT.RESET_REASON, WDT.TIMEOUT_CNT, CRU.RESET_REASON.

    Sub-type 1a: WDT Reset
    Trigger  : WDT countdown reaches zero
    Owner    : WdtDevice.on_tick() → SystemResetManager.wdt_reset()
    WDT-specific: RESET_REASON ← 0x01 (WDT), TIMEOUT_CNT += 1
    RESET_REASON → 0x01 (WDT_RESET)

    Sub-type 1b: Software System Reset
    Trigger  : Firmware writes CRU.SOFT_SYSRST_REQ (preferred) or SYSCTRL.RESET_CTRL.SYS_RESET_REQ
               Both delegate to SystemResetManager.software_system_reset() — identical code path.
    Owner    : CruDevice.write() or SYSCTRL native handler → SystemResetManager.software_system_reset()
    WDT retention: unchanged (TIMEOUT_CNT not incremented, RESET_REASON not touched by WDT)
    RESET_REASON → 0x02 (SW_SYSTEM_RESET) — written by the reset initiator before calling manager

  Level 2 ─ Device Reset  (single peripheral, CPU continues)
  ────────────────────────────────────────────────────────────────
  Trigger  : CRU.RST_CTRL_x.DEV_RST_N transitions 1→0 (assert) or 0→1 (release)
  Scope    : Only the named device; all others keep running
  QEMU     : Native CRU C code updates its in-memory CLK_EN/RST_CTRL tables.
             The mmio-sockdev guard (kx6625_cru_check_access) immediately begins
             blocking or passing accesses to that address range.
             CRU then sends a 'D' reset-notification message over the dedicated
             CRU-notify TCP channel to the appropriate backend:
               • Python device  → CruNotifyServer port (Python server)
               • SV device      → CruNotifyServer port (SV host shell)
  Python   : CruNotifyServer dispatches:
             On assert  : device._cru_in_reset = True  (device holds its state)
             On release : device.on_device_reset() called; registers → reset values
  SV host shell: SV host shell receives the same 'D' message; performs its own reset
             action on the local RTL state (drain pipeline, clear register file).
  Retention: Device-level retention is not defined; all registers return to
             reset values on release.
```

---

## 3. Retention Registers

A retention register is a register whose value survives a Level-1 system
reset but is cleared by a Level-0 POR.

**Implementation rule**: retention registers are Python instance variables
that `on_reset()` simply does not assign.  The variable persists because the
Python process persists across a Level-1 reset.  A Level-0 POR starts a fresh
Python process, so all instance variables start from `__init__` defaults.

| Register       | Device | Retention level | Purpose                                      |
|----------------|--------|-----------------|----------------------------------------------|
| RESET_REASON   | WDT    | Level-1 (system)| Tells firmware why the last reset occurred   |
| TIMEOUT_CNT    | WDT    | Level-1 (system)| Cumulative WDT fire count since power-on     |
| CRU.RESET_REASON | CRU  | Level-1 (system)| Mirrors WDT RESET_REASON at the SoC level    |

The CRU `RESET_REASON` register at the SoC level is the canonical place for
firmware to read reset cause.  It is set by `SystemResetManager` before
calling `on_reset()` on any device, and is preserved through all Level-1
resets.

---

## 4. Level-0: Global / Power-On Reset

```
  User runs: make qemu   (or kills and restarts QEMU + Python server)

  Python process starts fresh
      └── SoCTop.__init__()
          └── every device.__init__() ── all registers at reset values
                                     ── retention registers at 0 (no prior value)

  QEMU process starts fresh
      └── CPU0 fetches reset vector from 0x00000000
      └── All mmio-sockdev instances connect to Python server
```

No special code path needed.  This is just process restart.

---

## 5. Level-1: System Reset

### 5a. WDT Reset

```
  WdtDevice.on_tick(vtime_ns):
      elapsed ≥ load_ms
          1. self._reset_reason = 1         # WDT_RESET
          2. self._timeout_cnt += 1         # retention update BEFORE on_reset
          3. self._reset_callback()         # → SystemResetManager.wdt_reset()

  SystemResetManager.wdt_reset():
      1. self._rst_reason_store = RESET_REASON_WDT   # SoC-level retention
      2. for device in bus.all_devices():
             device.on_reset()             # clears volatile state, preserves own retention
      3. self._rst_ctrl.send_reset()       # byte → rst-chardev TCP → QEMU

  QEMU mmio-sockdev (rst_chardev_read):
      qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)
          └── CPU fetches reset vector; mmio-sockdev re-connects to Python server
```

### 5b. Software System Reset

Software system reset is triggered by firmware writing a register — either
`CRU.SOFT_SYSRST_REQ` (the new CRU register, preferred) or the existing
`SYSCTRL.RESET_CTRL.SYS_RESET_REQ`.

```
  Firmware writes CRU.SOFT_SYSRST_REQ = 1:

  CruDevice.write(SOFT_SYSRST_REQ):
      1. Records RESET_REASON = SW_SYSTEM_RESET in its own retention register
      2. Calls SystemResetManager.software_system_reset()

  SystemResetManager.software_system_reset():
      1. self._rst_reason_store = RESET_REASON_SW_SYSTEM_RESET
      2. for device in bus.all_devices():
             device.on_reset()             # same volatile-clear, same retention-preserve
      3. self._rst_ctrl.send_reset()       # same rst-chardev path as WDT reset

  QEMU side: identical to WDT reset — CPU fetches reset vector
```

The distinction from WDT reset:
- TIMEOUT_CNT is not incremented.
- WDT volatile registers are cleared (CTRL, LOAD, STATUS) but TIMEOUT_CNT
  and RESET_REASON inside WdtDevice are preserved unchanged.
- RESET_REASON reads back 0x02 (SW_SYSTEM_RESET) instead of 0x01 (WDT_RESET).

---

## 6. Level-2: Device Reset (CRU-controlled)

Each peripheral has a reset-release bit in `CRU.RST_CTRL_x`.  The bit is
active-low (reset asserted when bit = 0, released when bit = 1) matching
typical SoC convention.

### Assert reset  (bit 0 → 0)

```
  Firmware writes CRU.RST_CTRL0 and clears DMA_RST_N:

  CruDevice.write(RST_CTRL0, data):
      detects DMA_RST_N 1→0 transition
      self._dev_reset_mgr.assert_reset('dma')

  DeviceResetManager.assert_reset('dma'):
      self._in_reset['dma'] = True
      # Does NOT call on_reset() — volatile state preserved while in reset
      # (matches hardware: the block is frozen, not reinitialized)

  Subsequent DMA MMIO accesses:
      MMIOBus.read/write  →  CRU access guard callback (see Section 8)
                          →  checks: DMA_RST_N == 0  OR  DMA_CLK_EN == 0
                          →  if violation: ABORT
                              - read  returns 0xDEAD0000 (distinctive error marker)
                              - write is discarded
                              - error event emitted to tracer
                              - [CRU] ABORT log line printed
```

Keeping volatile state frozen rather than clearing it on assert-reset is the
deliberate choice here: it matches how most real hardware behaves (the reset
signal gates clocks; the registers are neither accessible nor initialized
until release).

The abort response (0xDEAD0000) is intentionally distinctive so that firmware
reading a stuck-at-zero register and firmware incorrectly reading before reset
release produce different signatures.  A future extension can inject a QEMU
bus fault (HardFault on Cortex-M) once the mmio-sockdev protocol gains an
error-response code.

### Release reset  (bit 0 → 1)

```
  Firmware writes CRU.RST_CTRL0 and sets DMA_RST_N:

  CruDevice.write(RST_CTRL0, data):
      detects DMA_RST_N 0→1 transition
      self._dev_reset_mgr.release_reset('dma')

  DeviceResetManager.release_reset('dma'):
      device = self._device_map['dma']
      device.on_device_reset()            # clears all registers to reset values
      self._in_reset['dma'] = False       # now accessible
```

`on_device_reset()` is a new `MMIODevice` method — by default it calls
`on_reset()`.  Devices that need to distinguish a Level-2 device reset from a
Level-1 system reset can override `on_device_reset()`.

---

## 7. CRU Register Map

CRU is a **native QEMU MMIO block** (`native: true` in `spec/devices.yaml`),
implemented in C alongside SYSCTRL in `scripts/qemu-fork/hw/arm/kx6625.c`
(or a dedicated `kx6625_cru.c`).  There is no `mmio-sockdev` instance and
no TCP connection for CRU register access.

Base address: `0x4000F000`  (next available slot after FLASH_CTRL at `0x4000E000`)

```
Offset  Name                Access  Reset    Description
──────────────────────────────────────────────────────────────────────────────
0x00    CLK_EN0             RW      0x0000   Per-device clock enable gates.
                                             Bit 0 = UART_CLK_EN
                                             Bit 1 = DMA_CLK_EN
                                             Bit 2 = TIMER0_CLK_EN
                                             Bit 3 = DMA_CLIENT_CLK_EN
                                             Bit 4 = CRC_CLK_EN
                                             Bit 5 = WDT_CLK_EN
                                             Bit 6 = HSM_CLK_EN
                                             Bit 7 = OTP_CLK_EN
                                             Bit 8 = FLASH_CTRL_CLK_EN
                                             (Remaining bits reserved)

0x04    CLK_EN1             RW      0x0000   Extended clock enables (future SV devices, etc.)

0x10    RST_CTRL0           RW      0x0000   Per-device reset control, active-low.
                                             Bit 0 = UART_RST_N       (0=in reset, 1=released)
                                             Bit 1 = DMA_RST_N
                                             Bit 2 = TIMER0_RST_N
                                             Bit 3 = DMA_CLIENT_RST_N
                                             Bit 4 = CRC_RST_N
                                             Bit 5 = WDT_RST_N
                                             Bit 6 = HSM_RST_N
                                             Bit 7 = OTP_RST_N
                                             Bit 8 = FLASH_CTRL_RST_N
                                             (Remaining bits reserved)

0x14    RST_CTRL1           RW      0x0000   Extended reset controls (future devices)

0x20    SOFT_SYSRST_REQ     W       0x0000   Write 0xDEAD_BEEF to trigger a software
                                             system reset (Level-1b).  Self-clears.
                                             Any other value is ignored.

0x24    RESET_REASON        R       0x0000   SoC-level reset cause (retention register):
                                             0x00 = POR / global reset
                                             0x01 = WDT reset
                                             0x02 = Software system reset
                                             (Updated by SystemResetManager before
                                             on_reset() is dispatched)

0x28    PLL0_CTRL           RW      0x0001   PLL0 control stub.
                                             Bit 0 = PLL0_EN (functional no-op; tracked only)
                                             Bit 8 = PLL0_LOCK (R, reads 1 always in simulation)

0x2C    PLL1_CTRL           RW      0x0001   PLL1 control stub (same layout as PLL0_CTRL)

0x30    CLK_DIV0            RW      0x0000   Clock divider stubs — tracked, not functionally
                                             applied.  Bits [7:0] = PCLK_DIV (default 4).

0x34    ID                  R       0x43525531  ASCII 'CRU1' little-endian device identifier
```

### Notes on the clock registers

Clock enables and dividers are **tracked but not functionally applied** in
this simulation environment.  There is no real clock.  The purpose of
modeling them is:

1. Firmware can follow the exact same initialization sequence it would on
   silicon (enable clock → release reset → configure device).
2. If a device is accessed while its clock enable bit is 0, the access is
   **aborted** by the CRU access guard — the same abort path as reset-asserted
   access.  This catches firmware that skips clock initialization.
3. Test automation can assert that firmware enables clocks in the correct order
   by checking the tracer event stream for `[CRU] ABORT` events.

The CRU access guard checks **both** conditions with a single C function:

```
  kx6625_cru_check_access(addr) → false  if  CLK_EN[dev] == 0  OR  RST_N[dev] == 0
                                   true   otherwise
```

Both violations use the same abort behavior (`0xDEAD0000` on reads / discard
on writes + `[CRU] ABORT` log in QEMU).  The guard runs entirely in QEMU C
code (`mmio-sockdev` calls `kx6625_cru_check_access()` before any TCP
forwarding) and is transparent to both Python and SV backends.

### CRU's own reset domain

CRU is itself subject to Level-1a/1b reset.  On any system reset:

- `CLK_EN0`, `CLK_EN1`, `RST_CTRL0`, `RST_CTRL1`, `PLL0_CTRL`, `PLL1_CTRL`,
  `CLK_DIV0` → cleared to hardware reset values (all zeros → all devices in
  reset with clocks off).
- `RESET_REASON` → **not cleared** (retention register; only Level-0 POR clears it).

This means firmware must explicitly re-enable clocks and release device resets
after any Level-1 system reset, just as it does after power-on.  The access
guard enforces this: any device accessed before its CRU bits are programmed
will abort.

The CRU device itself is never gated by its own guard — CRU registers are
always accessible (gating CRU behind its own bits would be a deadlock).

---

## 8. Implementation Design

### 8.1 Native QEMU CRU (C layer)

CRU is implemented as a native QEMU SysBus device in
`scripts/qemu-fork/hw/arm/kx6625_cru.c` (or inlined into `kx6625.c`),
registered as `"kx6625-cru"`.  It is instantiated by `kx6625_soc_init()` the
same way SYSCTRL is.

```c
typedef struct KX6625CruState {
    SysBusDevice  parent_obj;
    MemoryRegion  mmio;            /* 0x4000F000, 4KB */

    /* CLK_EN and RST_CTRL shadow — authoritative state for the guard */
    uint32_t      clk_en0;         /* CLK_EN0 register */
    uint32_t      clk_en1;         /* CLK_EN1 register */
    uint32_t      rst_ctrl0;       /* RST_CTRL0 register */
    uint32_t      rst_ctrl1;       /* RST_CTRL1 register */
    uint32_t      reset_reason;    /* retention: survives Level-1 */

    /* Per-device address table for the guard */
    KX6625CruEntry entries[KX6625_CRU_MAX_DEVICES];
    int            n_entries;

    /* Notify channels — TCP connections to Python server and SV host shell */
    CharBackend    py_notify_chr;  /* → Python CruNotifyServer  */
    CharBackend    sv_notify_chr;  /* → SV host shell notify port   */
} KX6625CruState;

/* Called from kx6625_soc_init() for every socket-backed device */
void kx6625_cru_register_device(
    KX6625CruState *cru,
    const char     *dev_id,
    uint64_t        base,
    uint64_t        size,
    int             clk_bit,   /* bit position in CLK_EN0 */
    int             rst_bit    /* bit position in RST_CTRL0 */
);

/*
 * Called from mmio-sockdev before forwarding any read or write to TCP.
 * Returns true → access permitted.
 * Returns false → caller must abort (return 0xDEAD0000 / discard write).
 */
bool kx6625_cru_check_access(KX6625CruState *cru, uint64_t phys_addr);
```

CRU registers themselves are always accessible — `kx6625_cru_check_access`
returns `true` unconditionally for addresses in `[0x4000F000, 0x4001_0000)`.

On a QEMU system reset (`device_reset` hook on the CRU object):
- `clk_en0`, `clk_en1`, `rst_ctrl0`, `rst_ctrl1` → 0 (all devices in reset)
- `reset_reason` is **not** cleared (it is a retention register)

This reset hook runs automatically when `qemu_system_reset_request()` fires
(both WDT and software system resets), matching the Level-1 scope defined in
Section 2.

### 8.2 Access guard in `mmio-sockdev.c`

Each `mmio-sockdev` instance gains an optional property `cru` pointing to the
native CRU object.  During `kx6625_soc_init()`, this property is set for every
peripheral mmio-sockdev instance.

```c
/* In mmio_sockdev_mem_read() and mmio_sockdev_mem_write(), before TCP forward: */
if (s->cru && !kx6625_cru_check_access(s->cru, s->base_addr + offset)) {
    /* read: return 0xDEAD0000; write: discard */
    qemu_log_mask(LOG_GUEST_ERROR,
        "[CRU] ABORT addr=0x%09" PRIx64 " dev=%s\n",
        s->base_addr + offset, s->name);
    if (is_read) {
        memset(buf, 0, size);
        stl_le_p(buf, 0xDEAD0000);
    }
    return;
}
```

This single check point covers **all** device backends uniformly:
- Python devices — QEMU ↔ Python server over TCP
- SV devices — QEMU ↔ SV host shell over TCP  
- Any future backend

No Python code participates in the guard.  Python and SV servers never need
to shadow or track CRU state for access control purposes.

### 8.3 Device reset notification protocol (QEMU CRU → backends)

When firmware writes `RST_CTRL0` and a bit transitions, the native CRU must
notify the backend that owns the affected device.  This uses a dedicated TCP
notify channel (separate from the MMIO R/W chardev).

**Protocol message** (CRU → backend, 3 bytes):

```
'D'(1B) | dev_idx(1B) | action(1B)

  dev_idx : index matching the registration order in kx6625_cru_register_device()
            (same mapping as CLK_EN / RST_CTRL bit positions)
  action  : 0x00 = assert reset   (RST_N bit went 1→0)
            0x01 = release reset  (RST_N bit went 0→1)
```

The CRU sends the message synchronously in its `mmio_write` handler, before
returning to the firmware.  Firmware naturally cannot access the device until
it writes RST_N=1 and the backend acknowledges (implicit: the notify is
fire-and-forget; the guard enforces access ordering).

**Python backend — `CruNotifyServer`**:

A new server in `device_model/mmio_device_server.py` accepts the QEMU CRU
TCP connection on a dedicated port (proposed: `7917`).

```python
class CruNotifyServer:
    """
    Receives device-level clock/reset notifications from QEMU native CRU.

    On 'D' | dev_idx | 0x00 (assert reset):
        device._cru_in_reset = True
        # device state is frozen; QEMU guard already blocks MMIO access

    On 'D' | dev_idx | 0x01 (release reset):
        device.on_device_reset()   # registers → reset values
        device._cru_in_reset = False
    """

    def __init__(self, port: int, device_map: dict[int, MMIODevice]) -> None:
        # device_map: dev_idx → MMIODevice instance
        ...
```

Python devices no longer need any clock/reset awareness in their own
`read()`/`write()` methods.  The QEMU guard enforces access ordering;
`CruNotifyServer` keeps device state correct on reset transitions.

**SV host shell — notify port**:

The SV host shell (`sv_device/sv_host_shell.cpp`) opens a listening port for
CRU reset notifications (proposed: `7918`).  On receiving a `'D'` message:
- assert reset: drain any in-progress APB transactions; mark device as reset
- release reset: call the Verilator model's reset deassert sequence

### 8.4 `SystemResetManager` — unchanged Level-1 path

The Level-1 reset path (WDT and software system reset) is unchanged on the
Python side.  `SystemResetManager.wdt_reset()` and `software_system_reset()`
continue to call `on_reset()` on all bus devices and send the rst-chardev
byte to QEMU.  The native QEMU CRU's `device_reset` hook clears CLK_EN/RST_CTRL
automatically as part of the same QEMU reset cycle.

### 8.5 New method on `MMIODevice`: `on_device_reset()`

```python
class MMIODevice:
    def on_device_reset(self) -> None:
        """
        Called by CruNotifyServer when this device's RST_N bit is released
        (CRU RST_CTRL bit goes 0→1).  Default implementation calls on_reset()
        so existing devices work without change.  Override to distinguish
        a Level-2 device reset from a Level-1 system reset if needed.
        """
        self.on_reset()
```

### 8.6 Wiring in `SoCTop` and `kx6625_soc_init()`

Python side (`SoCTop`):

```python
# Sketch — not final API
dev_idx_map = {
    0: uart_device,
    1: dma_device,
    2: timer_device,
    3: dma_client_device,
    4: crc_device,
    5: wdt_device,
    6: hsm_device,
    7: otp_device,
    8: flash_ctrl_device,
}
cru_notify = CruNotifyServer(port=7917, device_map=dev_idx_map)
self._add_server(cru_notify)
```

QEMU C side (`kx6625_soc_init()`):

```c
KX6625CruState *cru = KX6625_CRU(dev);
/* Register each peripheral with its CLK_EN / RST_CTRL bit */
kx6625_cru_register_device(cru, "uart",       0x40004000, 0x1000, 0, 0);
kx6625_cru_register_device(cru, "dma",        0x40005000, 0x1000, 1, 1);
kx6625_cru_register_device(cru, "timer0",     0x40006000, 0x1000, 2, 2);
kx6625_cru_register_device(cru, "dma_client", 0x40007000, 0x1000, 3, 3);
kx6625_cru_register_device(cru, "crc",        0x40008000, 0x1000, 4, 4);
kx6625_cru_register_device(cru, "wdt",        0x40009000, 0x1000, 5, 5);
kx6625_cru_register_device(cru, "hsm",        0x4000C000, 0x1000, 6, 6);
kx6625_cru_register_device(cru, "otp",        0x4000D000, 0x1000, 7, 7);
kx6625_cru_register_device(cru, "flash_ctrl", 0x4000E000, 0x1000, 8, 8);

/* Wire each mmio-sockdev to the CRU guard */
object_property_set_link(OBJECT(uart_sockdev),  "cru", OBJECT(cru), &err);
object_property_set_link(OBJECT(dma_sockdev),   "cru", OBJECT(cru), &err);
/* ... etc for all socket-backed devices ... */
/* SV device mmio-sockdev also wired to cru — guard applies uniformly */
object_property_set_link(OBJECT(sv_sockdev),    "cru", OBJECT(cru), &err);
```

---

## 9. Sequence Diagrams

### 9.1 WDT Reset (Level-1a)

```
Firmware       WdtDevice        SystemResetManager    RstController    QEMU
   │               │                    │                   │             │
   │  (WFI)        │                    │                   │             │
   │               │ on_tick()          │                   │             │
   │               │  elapsed≥load      │                   │             │
   │               │  RESET_REASON←1   │                   │             │
   │               │  TIMEOUT_CNT+=1   │                   │             │
   │               │──wdt_reset()──────►│                   │             │
   │               │                   │ on_reset() → all  │             │
   │               │                   │ devices (volatile │             │
   │               │                   │ cleared)          │             │
   │               │                   │──send_reset()────►│             │
   │               │                   │                   │──byte──────►│
   │               │                   │                   │             │ reset_request()
   │◄──────────────────────────────────────────────────────────────────── CPU reset vector
```

### 9.2 Software System Reset (Level-1b)

```
Firmware      QEMU native CRU    SystemResetManager    RstController    QEMU CPU
   │                │                    │                   │             │
   │ write          │                    │                   │             │
   │ SOFT_SYSRST ──►│                   │                   │             │
   │                │ value==0xDEADBEEF  │                   │             │
   │                │ RESET_REASON←0x02  │                   │             │
   │                │──sw_sys_reset()───►│                   │             │
   │                │                   │ on_reset() → all  │             │
   │                │                   │ Python devices    │             │
   │                │                   │──send_reset()────►│             │
   │                │                   │                   │──byte──────►│
   │                │                   │                   │             │ reset_request()
   │                │                   │                   │             │ → device_reset hook:
   │                │                   │                   │             │   clk_en0/1 ← 0
   │                │                   │                   │             │   rst_ctrl0/1 ← 0
   │◄──────────────────────────────────────────────────────────────────────── CPU reset vector
```

Note: QEMU's built-in `device_reset` mechanism fires on every SysBus device
when `qemu_system_reset_request()` is processed.  The native CRU's reset hook
clears `clk_en0/1` and `rst_ctrl0/1` automatically at this point, without
needing an explicit call from `SystemResetManager`.

### 9.3 Device Reset — Assert then Release (Level-2)

```
Firmware      QEMU native CRU    mmio-sockdev     CruNotifyServer   DmaController
   │                │                 │                 │                │
   │ write          │                 │                 │                │
   │ RST_CTRL0      │                 │                 │                │
   │ DMA_RST_N←0 ──►│                 │                 │                │
   │                │ rst_ctrl0[1]←0  │                 │                │
   │                │──'D'|1|0x00────────────────────────►│               │
   │                │                 │                 │ _cru_in_reset←True
   │                │                 │                 │                │
   │ (DMA MMIO)     │                 │                 │                │
   │ load r0,[DMA]──►                 │                 │                │
   │                │ kx6625_cru_     │                 │                │
   │                │ check_access()  │                 │                │
   │                │ → false ────────►ABORT            │                │
   │◄── 0xDEAD0000 ──────────────────│                 │                │
   │                │  [CRU] ABORT   │                 │                │
   │                │                 │                 │                │
   │ write          │                 │                 │                │
   │ RST_CTRL0      │                 │                 │                │
   │ DMA_RST_N←1 ──►│                 │                 │                │
   │                │ rst_ctrl0[1]←1  │                 │                │
   │                │──'D'|1|0x01────────────────────────►│               │
   │                │                 │                 │──on_device_reset()►│
   │                │                 │                 │                │ registers←reset
   │                │                 │                 │ _cru_in_reset←False
   │                │                 │                 │                │
   │ (DMA MMIO)     │                 │                 │                │
   │ load r0,[DMA]──►                 │                 │                │
   │                │ check_access()  │                 │                │
   │                │ → true ─────────►─────────────────────────────────►│ normal dispatch
```

### 9.4 SV Device Access Guard (same QEMU guard, different backend)

```
Firmware      QEMU native CRU    mmio-sockdev     SV host shell
   │                │            (sv_sockdev)          │
   │ (SV_RST_N=0)   │                 │                │
   │                │ rst_ctrl1[0]←0  │                │
   │                │──'D'|16|0x00────────────────────►│ (SV notify port)
   │                │                 │                │ reset SV local state
   │                │                 │                │
   │ (SV MMIO)      │                 │                │
   │ load r0,[SV] ──►                 │                │
   │                │ check_access()  │                │
   │                │ → false ─────────►ABORT          │
   │◄── 0xDEAD0000 ──────────────────│                │
```

The SV `mmio-sockdev` instance is wired to the same native CRU guard as
Python device instances.  The guard is backend-agnostic.

### 9.5 Clock-Disabled Access (same QEMU abort path)

```
Firmware      QEMU native CRU    mmio-sockdev
   │                │                 │
   │ (skipped       │                 │
   │  CLK_EN step)  │ clk_en0[1]=0    │
   │                │                 │
   │ (DMA MMIO)     │                 │
   │ load r0,[DMA]──►                 │
   │                │ check_access()  │
   │                │ clk_dis→false ──►ABORT
   │◄── 0xDEAD0000 ──────────────────│
   │                │  [CRU] ABORT   │
```

---

## 10. Boot Sequence Implication

On any Level-1 reset (WDT or SW), CRU's own volatile registers are cleared
(CLK_EN0/1 → 0, RST_CTRL0/1 → 0) as part of `CruDevice.on_reset()`.  This
means all peripheral clock enables are off and all peripheral resets are
asserted.  Firmware must re-run the full clock-enable and reset-release
sequence for any device it intends to use after a system reset.

The required firmware initialization order for each device:

```
  1. Write CRU.CLK_EN0  — set the device's CLK_EN bit
  2. Write CRU.RST_CTRL0 — set the device's RST_N bit (release reset)
  3. Configure device registers
```

If step 3 is attempted before steps 1 and 2, the CRU access guard aborts the
access with 0xDEAD0000 and logs `[CRU] ABORT`.  This is the intended behavior:
it catches firmware porting bugs early rather than letting incorrect values
silently propagate.

This is intentional: it enforces that firmware initializes peripherals
explicitly, which is the normal real-chip requirement and makes the test
environment a better proxy for real bring-up.

CRU registers are always accessible regardless of guard state (CRU is never
gated by its own bits; that would create a deadlock where reset cannot be
released).

SYSCTRL volatile registers (RESET_CTRL, CPU_CTRL, CPU_STATUS, BOOT_MODE) are
also cleared by Level-1 resets.  Firmware that needs to release CPU1 after a
system reset must re-write SYSCTRL.CPU_CTRL.CPU1_RELEASE, exactly as it does
after power-on.

---

## 11. Design Decisions

1. **Access guard location — QEMU native C (`kx6625_cru_check_access`)**.
   The guard lives entirely in QEMU C code inside `mmio-sockdev`.  This is
   the only location that can intercept accesses to *all* device types —
   Python-backed and SV-backed — uniformly before any TCP forwarding occurs.
   A Python-side guard (e.g. in `MMIOBus`) would be bypassed entirely for SV
   device accesses, which go through QEMU directly to the SV host shell without
   entering the Python server.  Python and SV backends have zero clock/reset
   boilerplate; they only receive explicit `'D'` reset-notification messages.

2. **Clock enable enforcement — abort on violation (same as reset-asserted)**.
   Accessing a device with CLK_EN=0 is aborted identically to accessing a
   device with RST_N=0.  Both return 0xDEAD0000 (reads) / discard (writes)
   and emit a `[CRU] ABORT` log + tracer event.  Warning-only was rejected:
   silent undefined-behavior is worse than a loud abort for catching firmware
   initialization bugs.

3. **CRU base address — `0x4000F000` confirmed**.
   This is the next natural slot after FLASH_CTRL at `0x4000E000`.  Reserved
   for CRU exclusively.

4. **SOFT_SYSRST_REQ magic value — `0xDEADBEEF` confirmed**.
   Any write of a value other than `0xDEADBEEF` is silently ignored.  This
   avoids accidental resets from stray zero-writes or partial initialization.
   The single-magic-value approach is sufficient for this simulation context;
   a two-write unlock sequence is not required.

5. **CRU RST_CTRL initial state — all-zero (all devices in reset)**.
   `RST_CTRL0` and `CLK_EN0` reset to `0x0000` after any Level-1 reset
   (because CRU's own volatile registers are cleared by Level-1).  This is a
   deliberate breaking change: existing firmware that accesses devices without
   CRU initialization will be caught by the abort guard.  Migration path:
   add a CRU init helper to the firmware startup sequence before any device
   driver initialization.

6. **SYSCTRL.RESET_CTRL.SYS_RESET_REQ — delegates to the same manager**.
   Both `CRU.SOFT_SYSRST_REQ` and `SYSCTRL.RESET_CTRL.SYS_RESET_REQ` call
   `SystemResetManager.software_system_reset()`.  This guarantees identical
   reset scope and retention behavior regardless of which register firmware
   uses.  SYSCTRL volatile registers (RESET_CTRL, CPU_CTRL, CPU_STATUS,
   BOOT_MODE) are cleared by Level-1 just like all other volatile state;
   SYSCTRL does not have its own retention registers.
