# QEMU Custom MMIO Socket Device

A framework for implementing custom ARM hardware devices in QEMU, with register logic and interrupt firing modelled in Python. A single generic QEMU SysBus device (`mmio-sockdev`) proxies MMIO reads/writes, IRQ lines, virtual-clock ticks, and bus-master DMA to/from external Python device models over TCP. A shared virtual-clock tick mechanism lets any device implement timing-dependent behaviour (countdown timers, DMA latency, etc.) that tracks QEMU's simulated time exactly.

## Overview

This project implements:
- **Custom QEMU Device** (`mmio-sockdev`): Generic SysBus proxy — 4 KB MMIO, IRQ line, optional virtual-clock tick channel, optional bus-master DMA memory channel, optional system-reset channel (`rst-chardev`). One instance per device on the QEMU command line.
- **Python Device Server** (`device_model/mmio_device_server.py`): Transport + address dispatcher (`MMIOBus`). Each peripheral is a `MMIODevice` subclass with `read()`, `write()`, and an optional `on_tick()` override.
- **Six modelled peripherals**: Console UART, multi-channel DMA controller, countdown timer, DMA client demo peripheral, CRC-32 hardware accelerator, Watchdog Timer (WDT).
- **KX6625 Custom SoC** (`scripts/qemu-fork/hw/arm/kx6625.c`): Cortex-M3 @ 48 MHz, 512 KB FLASH @ `0x00000000`, 128 KB SRAM @ `0x20000000`, NVIC with 16 external IRQs.
- **Bare-Metal Cortex-M3 Firmware**: NVIC init, IRQ handlers, UART demo, DMA M2M copy demo, DMA peripheral DREQ/DACK demo, CRC-32 test, WDT countdown-reset demo with warm-boot detection.
- **End-to-End Smoke Test** (`scripts/e2e_test.sh`): Starts Python server, boots QEMU, exercises all six devices including a WDT-triggered system reset and warm-boot detection, asserts firmware output.

## Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  QEMU  (KX6625 custom SoC — Cortex-M3 @ 48 MHz, NVIC, 16 external IRQs)                   │
│                                                                                            │
│  ┌──────────────┐    MMIO                ┌──────────────────────────────────────────────┐ │
│  │  Firmware    │ ─── read/write ──────► │  mmio-sockdev (×6 instances)                 │ │
│  │  (Cortex-M3) │                        │                                              │ │
│  │              │ ◄── IRQ (NVIC) ──────── │   chardev      ↔ R/W TCP channel             │ │
│  └──────┬───────┘                        │   irq-chardev  ← IRQ TCP channel             │ │
│         │                                │   tick-chardev → virtual-clock tick TCP      │ │
│         │ read/write                     │   mem-chardev  ← DMA bus-master TCP (opt.)   │ │
│         ▼                                │   rst-chardev  ← system-reset TCP (opt.)     │ │
│  ┌────────────────────┐                  └───────────┬──────────────────────────────────┘ │
│  │  FLASH  512 KB     │                              │ TCP channels                       │
│  │  0x00000000        │ ◄── cpu_physical_memory_write (mem-chardev → QEMU phys mem)       │
│  ├────────────────────┤                              │                                    │
│  │  SRAM   128 KB     │   QEMU_CLOCK_VIRTUAL fires QEMUTimer every tick-period-ms         │
│  │  0x20000000        │   Any byte on rst-chardev → qemu_system_reset_request()           │
│  └────────────────────┘                                                                   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                              │ TCP (per-channel connections)
                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  Python Device Server  (device_model/mmio_device_server.py)                                │
│                                                                                            │
│  RWServer               IRQServer              TickServer          MemServer  RstServer    │
│  :7890/:7892/:7894/:…   :7891/:7893/:7895/:…   :7896              :7897      :7903         │
│  QEMU ↔ Python          Python → QEMU          QEMU → Python      Py→QEMU    Py→QEMU      │
│  (MMIO R/W ops)         (IRQ injection)        (virtual clock)    (DMA)      (sys reset)  │
│        │                      │                     │                │            │        │
│        └──────────────┬───────┘          bus.tick_all(vtime_ns)  MemChannel  RstController│
│                       │                                                                    │
│                   MMIOBus                    SystemResetManager                            │
│       ┌───────────────┼──────────┬────────────────┬──────┬──────┐   on WDT timeout:       │
│       ▼               ▼          ▼                ▼      ▼      ▼   1. device.on_reset()  │
│  ConsoleUart    DmaController TimerDevice DmaClientDemo CRC-32  WDT  (all devices)        │
│  0x40004000     0x40005000    0x40006000  0x40007000   0x40008000 0x40009000               │
│  IRQ 0          IRQ 1         on_tick()   IRQ 3         —       IRQ 4  2. RstCtrl.send()  │
│                 on_tick()     IRQ 2       DREQ/DACK    data feed on_tick()   → TCP :7903  │
│                 dma_read/write                                   timeout     → QEMU reset  │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Virtual-Clock Tick Broadcast

The `tick-chardev` property on `mmio-sockdev` connects to a `QEMUTimer` on `QEMU_CLOCK_VIRTUAL`. Every `tick-period-ms` of **simulated** time QEMU sends:

```
'T'(1B) | vtime_ns(8B LE)
```

`TickServer` receives this and calls `bus.tick_all(vtime_ns)` — dispatching to **every** registered device. Devices that need timing override `on_tick()`; the rest inherit a no-op. This architecture means:

- Adding a new timed device requires no changes to the transport layer.
- Ticks stop when QEMU is paused (gdb, single-step) — no spurious IRQs.
- The same tick stream drives both the timer countdown and DMA latency.

```
QEMU_CLOCK_VIRTUAL
    │  'T'|vtime_ns  (TCP :7896)
    ▼
TickServer  ──► bus.tick_all(vtime_ns)
                   ├── ConsoleUartDevice.on_tick()   →  no-op (inherited)
                   ├── DmaController.on_tick()       →  advance every BUSY channel; DMA copy + IRQ on 0
                   ├── TimerDevice.on_tick()         →  check elapsed_ns ≥ load_ns; IRQ on expiry
                   ├── DmaClientDemoDevice.on_tick() →  no-op (inherited)
                   ├── CrcDevice.on_tick()           →  no-op (inherited)
                   └── WdtDevice.on_tick()           →  check elapsed_ms ≥ load_ms; trigger reset on expiry
```

### IRQ Flow

```
MMIODevice.irq_controller.set_irq(idx, level)
    │  'I'(1B) | idx(1B) | level(1B)  (TCP irq-port)
    ▼
mmio-sockdev (QEMU)  ──►  NVIC (IRQ line)  ──►  Cortex-M3
```

NVIC pulse pattern: assert then immediately deassert so the NVIC edge-trigger does not re-fire.

### Bus-Master DMA Flow

The DMA controller model acts as a bus master: it directly reads/writes QEMU physical memory without involving the firmware CPU. This is modelled via a dedicated `mem-chardev` TCP channel:

```
DmaController._tick_channel() calls:
    MemChannel.dma_read(src_addr, length)
        │  'M'(1B)|'R'(1B)|phys_addr(8B LE)|length(4B LE)  → QEMU
        │  QEMU executes cpu_physical_memory_read() and responds data(lengthB)
        ▼
    MemChannel.dma_write(dst_addr, data)
        │  'M'(1B)|'W'(1B)|phys_addr(8B LE)|length(4B LE)|data(lengthB)  → QEMU
        ▼
        QEMU executes cpu_physical_memory_write() into SRAM
```

### DMA Controller Architecture

`DmaController` (`dma_controller.py`) is the single MMIO-mapped DMA IP. It supports two independent channels:

| Channel | Mode | How triggered | Completion |
|---------|------|--------------|------------|
| CH0 | Memory-to-memory (M2M) | Firmware writes `CH0_CTRL.START` | Pulses DMA IRQ (NVIC) |
| CH1 | Peripheral DREQ/DACK (P2M/M2P) | `DmaClientHandle.transfer()` call | Calls peripheral's `on_complete` callback |

Each channel has its own 0x20-byte register slot. Transfers are tick-driven: a countdown (`transfer_ticks=10`) advances on every virtual-clock tick, so latency is tied to QEMU's virtual clock and stops during debug pauses.

```
Firmware path (CH0):
  write CH0_CTRL.START  →  _firmware_start()  →  _arm_channel()
  → _tick_channel() after N ticks → MemChannel copy → pulse IRQ 1

Peripheral path (CH1 / DmaClientDemoDevice):
  DmaClientHandle.transfer()  →  _peripheral_request()  →  _arm_channel()
  → _tick_channel() after N ticks → MemChannel copy → on_complete() callback
  → DmaClientDemoDevice sets STATUS.DONE → pulses IRQ 3
```

## Device Model Layer

`device_model/mmio_base.py` provides the shared building blocks used by every Python device model. These helpers eliminate per-device boilerplate and encode common hardware access patterns as reusable, testable units.

### `RegisterBank` — Thread-Safe Register Storage

Replaces the raw `bytearray + threading.Lock + manual bounds-check` pattern that every device would otherwise repeat.

```python
self._regs = RegisterBank(
    size,
    initial=bytes(init_values),          # optional reset snapshot
    policies={                            # optional per-register access policies
        _STATUS:  RegAccess.READ_ONLY,
        _VALUE:   RegAccess.READ_ONLY,
        _INTCLR:  RegAccess.WRITE_ONLY,
    },
)
```

**Key methods:**

| Method | Description |
|--------|-------------|
| `read(offset, size) → bytes` | CPU-side read; applies access policy |
| `write(offset, size, data)` | CPU-side write; applies access policy |
| `get32(offset) → int` | 32-bit LE read, **bypasses policy** (device-internal) |
| `set32(offset, value)` | 32-bit LE write, bypasses policy |
| `set_bits(offset, mask)` | Atomic OR, bypasses policy |
| `clear_bits(offset, mask)` | Atomic AND-NOT, bypasses policy |
| `reset(initial=None)` | Restore to construction-time snapshot |
| `with self._regs:` | Acquire internal lock for atomic multi-register operations |
| `get32_nolock / set32_nolock` | No-lock variants for use inside the context manager |
| `self._regs[byte_offset]` | Direct byte access inside context manager |

### `RegAccess` — Per-Register Access Policies

`RegAccess` is an `enum.Flag` whose members describe how a register behaves when the CPU reads or writes it. Policies apply **only to the external CPU path** (`read()`/`write()`). Internal device helpers (`get32`, `set_bits`, `__setitem__`, etc.) always bypass policies so the device hardware can freely update its own state.

| Flag | CPU Read | CPU Write | Typical Use |
|------|----------|-----------|-------------|
| *(none)* | returns stored value | stores value | normal R/W register |
| `WRITE_ONLY` | returns **0** | stores normally | pulse/strobe registers (`INTCLR`, `KICK`, `SWRESET`) |
| `READ_ONLY` | returns stored value | **dropped silently** | `STATUS`, `VALUE`, hardware-computed registers |
| `READ_CLEAR` | returns value then **clears to 0** | stores normally | latching event / error registers |
| `W1C` | returns stored value | **bits written 1 → cleared** | IRQ status (ARM convention): firmware acks by writing bit mask |
| `W1S` | returns stored value | **bits written 1 → set** | set-only enable registers |

Flags can be combined with `|`.

```python
# Example: standard ARM interrupt status register
policies={
    _STATUS: RegAccess.W1C,        # firmware clears individual IRQ bits
    _INTCLR: RegAccess.WRITE_ONLY, # reads return 0
    _VALUE:  RegAccess.READ_ONLY,  # hardware-computed; CPU writes dropped
}

# Example: self-clearing event latch
policies={
    _EVENTS: RegAccess.READ_CLEAR, # read returns accumulated flags and zeroes the register
}
```

### `IrqLine` — Single Interrupt Line

Encapsulates an `IRQController` + line index and provides named operations matching Cortex-M NVIC semantics.

```python
self._irq = IrqLine(irq_controller, idx=0)

self._irq.assert_()    # level = 1  (stays high; use for level-triggered, e.g. timer)
self._irq.deassert()   # level = 0
self._irq.pulse()      # assert then immediately deassert (edge-trigger; NVIC won't re-fire)
self._irq.wait_connected(timeout)  # block until QEMU IRQ channel connects
self._irq.idx          # read-only: line index
```

`pulse()` is the correct primitive for most peripherals — the NVIC latches the rising edge as *pending*; the level must return low before the handler returns to prevent the NVIC re-pending the interrupt on exception return.

If `irq_controller` is `None` all methods are silent no-ops, so devices remain constructible without an IRQ channel.

### `VirtualClock` — Countdown Tracker

Encapsulates the `_start_vtime_ns / _last_vtime_ns` countdown pattern shared by the Timer and WDT.

```python
self._clock = VirtualClock()

# In on_tick():
self._clock.update(vtime_ns)                # record latest timestamp
if self._clock.is_expired(load_ms):
    self._clock.disarm()                    # one-shot
    # or:
    self._clock.rearm_periodic(load_ms * 1_000_000)  # periodic — advances start by one period (no drift)

# Arm (e.g. when CTRL.ENABLE written):
self._clock.arm()                # from most-recent tick
self._clock.arm(vtime_ns)        # from explicit timestamp

# Read remaining time:
remaining = self._clock.remaining_ms(load_ms)
```

The clock is correct across QEMU debug pauses: virtual time stops, `update()` stops being called, `is_expired()` stays False.

### `DmaRequestInterface` — Abstract DREQ/DACK Protocol

Abstract base class for the peripheral-to-DMA-controller handshake. Device models that need DMA accept this interface type instead of the concrete `DmaClientHandle`, decoupling them from the DMA controller implementation.

```python
class MyDevice(MMIODevice):
    def __init__(self, dma: DmaRequestInterface, ...):
        self._dma = dma

    def _start_transfer(self):
        ok = self._dma.transfer(
            src, dst, length, callback=self._on_done,
        )
        # True = DACK (accepted), False = NACK (channel busy)

    def _on_done(self, success: bool): ...
```

Abstract members: `transfer(src, dst, length, callback, *, src_fixed, dst_fixed) → bool`, `busy → bool`, `channel_id → int`.

`src_fixed=True` / `dst_fixed=True` model peripheral register addresses that do not auto-increment (e.g. reading a FIFO or writing to the CRC DATA register).

`DmaClientHandle` in `dma_controller.py` is the concrete implementation.

## Devices

### Memory Map

| Region           | Base Address  | Size   | NVIC IRQ | R/W Port | IRQ Port | Tick Port | Mem Port | RST Port |
|------------------|---------------|--------|----------|----------|----------|-----------|----------|----------|
| Console UART     | `0x40004000`  | 4 KB   | 0        | 7890     | 7891     | —         | —        | —        |
| DMA Controller   | `0x40005000`  | 4 KB   | 1        | 7892     | 7893     | —         | 7897     | —        |
| Timer 0          | `0x40006000`  | 4 KB   | 2        | 7894     | 7895     | 7896      | —        | —        |
| DMA Client Demo  | `0x40007000`  | 4 KB   | 3        | 7898     | 7899     | —         | —        | —        |
| CRC-32 Engine    | `0x40008000`  | 4 KB   | —        | 7900     | —        | —         | —        | —        |
| Watchdog Timer   | `0x40009000`  | 4 KB   | 4        | 7901     | 7902     | —         | —        | 7903     |
| **FLASH**        | `0x00000000`  | 512 KB | —        | —        | —        | —         | —        | —        |
| **SRAM**         | `0x20000000`  | 128 KB | —        | —        | —        | —         | —        | —        |

The tick channel (`:7896`) is shared — a single `TickServer` broadcasts virtual-clock ticks from the timer's `mmio-sockdev` instance to **all** bus devices via `MMIOBus.tick_all()`.

### Console UART (`uart_model.py`)

| Offset | Name    | Access | Description                         |
|--------|---------|--------|-------------------------------------|
| 0x00   | TXDATA  | W      | Write byte to stdout (low 8 bits)   |
| 0x04   | STATUS  | R      | bit0 = TXREADY (always 1)           |
| 0x08   | CTRL    | R/W    | bit0 = ENABLE                       |

Fires a one-shot demo IRQ ~2 s after the IRQ channel connects. Does not use `on_tick()`. Characters are line-buffered in Python (flushed on `\n`) to prevent interleaving with other device thread output.

### DMA Controller (`dma_controller.py`)

A multi-channel DMA controller that acts as both the firmware-visible MMIO device and the engine for peripheral DREQ/DACK transfers. Two channels, each occupying a 0x20-byte register slot:

**Per-channel register layout (stride = 0x20)**

| Offset within slot | Name       | Access | Description                              |
|--------------------|------------|--------|------------------------------------------|
| +0x00              | CH_SRC_ADDR | R/W   | Transfer source physical address         |
| +0x04              | CH_DST_ADDR | R/W   | Transfer destination physical address    |
| +0x08              | CH_LENGTH   | R/W   | Transfer length in bytes                 |
| +0x0C              | CH_CTRL     | R/W   | bit0 = START, bit1 = ENABLE              |
| +0x10              | CH_STATUS   | R     | bit0 = BUSY, bit1 = DONE                 |

CH0 starts at offset `0x00`; CH1 starts at offset `0x20`.

Writing `CH_CTRL.START` sets `STATUS.BUSY` and starts a virtual-clock countdown (`transfer_ticks = 10`). After 10 ticks the DMA controller:
1. Reads `length` bytes from `src_addr` via `MemChannel.dma_read()`.
2. Writes them to `dst_addr` via `MemChannel.dma_write()`.
3. Sets `STATUS.DONE`, clears `STATUS.BUSY`.
4. **M2M (CH0 firmware path)**: pulses DMA IRQ 1.  **P2M/M2P (CH1 peripheral path)**: calls the peripheral's `on_complete(success)` callback.

Peripheral devices obtain a `DmaClientHandle` via `DmaController.get_handle(channel_id)` and call `handle.transfer(src, dst, length, callback)` — analogous to asserting a hardware DREQ line. The controller returns `True` (DACK) or `False` (NACK if channel busy).

### DMA Client Demo (`dma_client_demo.py`)

A demo peripheral that uses the DMA controller's DREQ/DACK interface to perform transfers without firmware involvement.

| Offset | Name     | Access | Description                          |
|--------|----------|--------|--------------------------------------|
| 0x00   | SRC_ADDR | R/W    | Transfer source physical address     |
| 0x04   | DST_ADDR | R/W    | Transfer destination physical address|
| 0x08   | LENGTH   | R/W    | Transfer length in bytes             |
| 0x0C   | CTRL     | R/W    | bit0 = START                         |
| 0x10   | STATUS   | R      | bit0 = BUSY, bit1 = DONE             |

Firmware writes `CTRL.START`; the demo device calls `dma_handle.transfer()` (DREQ). On completion, `STATUS.DONE` is set and IRQ 3 is pulsed.

### CRC-32 Engine (`crc_device.py`)

Hardware CRC-32/ISO-HDLC accelerator (IEEE 802.3 polynomial, used in Ethernet / ZIP / PNG).

| Offset | Name   | Access | Description                                                         |
|--------|--------|--------|---------------------------------------------------------------------|
| 0x00   | DATA   | R/W    | Write: feed bytes into accumulator. Read: raw accumulator value     |
| 0x04   | RESULT | R      | Final CRC-32 result (`accumulator ^ 0xFFFFFFFF`)                    |
| 0x08   | CTRL   | R/W    | bit0 = RESET — write 1 to reset accumulator to `0xFFFFFFFF`        |

Test vector: `CRC-32("123456789") = 0xCBF43926`. Supports byte and word writes; word writes feed four bytes in little-endian order. Compatible with firmware-driven direct writes and bus-master DMA M2P transfers (the DMA controller can feed data directly to offset `0x00`).

### Watchdog Timer (`wdt_model.py`)

A hardware watchdog that triggers a system reset if firmware stalls.

| Offset | Name         | Access | Description                                                              |
|--------|--------------|--------|--------------------------------------------------------------------------|
| 0x00   | LOAD         | R/W    | Timeout value in milliseconds (0 = disabled)                             |
| 0x04   | VALUE        | R      | Remaining time in ms (virtual-clock based)                               |
| 0x08   | CTRL         | R/W    | bit0 = ENABLE, bit1 = INT_ENABLE (fire IRQ 4 before reset)               |
| 0x0C   | KICK         | W      | Write any value to reload countdown; clears `STATUS.TIMEOUT`             |
| 0x10   | STATUS       | R      | bit0 = TIMEOUT (set when countdown expires)                              |
| 0x14   | RESET_REASON | R      | **Retention**: 0 = POR (power-on reset), 1 = WDT reset                  |
| 0x18   | TIMEOUT_CNT  | R      | **Retention**: number of WDT timeouts since power-on                     |

**Retention registers**: `RESET_REASON` and `TIMEOUT_CNT` survive a watchdog reset because they live in the Python device model instance, which persists across QEMU system resets. Only a full Python server restart (equivalent to power-on reset) clears them to 0.

**Reset flow**: When the countdown reaches zero, `WdtDevice.on_tick()` sets `RESET_REASON = 1`, increments `TIMEOUT_CNT`, optionally pulses IRQ 4 (pre-reset warning), then calls `SystemResetManager.wdt_reset()`. The manager calls `on_reset()` on every bus device (clearing volatile state while preserving retention registers) and then sends one byte over the `rst-chardev` TCP channel to QEMU. QEMU receives the byte and calls `qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)`, rebooting the firmware without exiting QEMU or closing TCP sockets.

Firmware detects a warm boot by reading `RESET_REASON` at startup:

```c
uint32_t reason = *(volatile uint32_t *)WDT_RESET_REASON_REG;
if (reason == WDT_REASON_POR) {
    /* First boot: start watchdog */
} else {
    /* Warm boot after WDT reset */
    uint32_t cnt = *(volatile uint32_t *)WDT_TIMEOUT_CNT_REG;
}
```

## Communication Protocols

All protocols are binary, little-endian.

### R/W Channel (QEMU → Python)

Binary, little-endian, sent by `mmio-sockdev` on each guest MMIO access:

```
Read:   'R'(1B) | offset(4B LE) | size(1B)             QEMU → Python
        data(sizeB LE)                                  Python → QEMU

Write:  'W'(1B) | offset(4B LE) | size(1B) | data(sizeB LE)   QEMU → Python
```

`offset` is relative to the device base address (`addr=` property).

### IRQ Channel (Python → QEMU)

```
'I'(1B) | irq_idx(1B) | level(1B)
```

`irq_idx` is 0-based index of the IRQ output on the `mmio-sockdev` instance.  `level` = 1 assert, 0 deassert.

### Tick Channel (QEMU → Python, optional)

```
'T'(1B) | vtime_ns(8B LE)
```

Sent every `tick-period-ms` of QEMU virtual time. Python dispatches to all devices via `MMIOBus.tick_all()`.

### MEM Channel — Bus-Master DMA (Python → QEMU, optional)

Allows a Python device model to directly read/write QEMU physical memory, modelling a bus-master DMA engine. Maximum single transfer: 64 KB.

```
DMA write:  'M'(1B) | 'W'(1B) | phys_addr(8B LE) | length(4B LE) | data(lengthB)
            QEMU executes cpu_physical_memory_write(phys_addr, data, length)

DMA read:   'M'(1B) | 'R'(1B) | phys_addr(8B LE) | length(4B LE)
            QEMU executes cpu_physical_memory_read(phys_addr, buf, length)
            QEMU responds: data(lengthB)
```

### RST Channel — System Reset (Python → QEMU, optional)

Allows a Python device model to trigger a subsystem-level QEMU system reset without exiting the emulator. Used by the WDT to reboot the firmware while keeping all TCP connections open.

```
Python → QEMU:  any single byte (e.g. 'R')
QEMU action:    qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)
                — CPU resets, vector table re-fetched, firmware restarts.
                — All chardev TCP sockets remain connected.
                — Python device model instance continues running;
                  volatile registers cleared by on_reset(), retention registers preserved.
```

The `rst-chardev` property is optional. If omitted, the device operates normally without reset capability.

## QEMU Command Line

The Python device server binds all TCP ports first; QEMU connects to them as a client. Each device needs one `mmio-sockdev` instance. The timer instance also carries the shared tick channel:

```bash
# Console UART
-chardev socket,id=uart_rw,host=127.0.0.1,port=7890
-chardev socket,id=uart_irq,host=127.0.0.1,port=7891
-device  mmio-sockdev,chardev=uart_rw,irq-chardev=uart_irq,addr=0x40004000,irq-num=0

# DMA controller (includes bus-master memory channel)
-chardev socket,id=dma_rw,host=127.0.0.1,port=7892
-chardev socket,id=dma_irq,host=127.0.0.1,port=7893
-chardev socket,id=dma_mem,host=127.0.0.1,port=7897
-device  mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,mem-chardev=dma_mem,addr=0x40005000,irq-num=1

# Timer 0 (also carries the shared tick broadcast)
-chardev socket,id=timer_rw,host=127.0.0.1,port=7894
-chardev socket,id=timer_irq,host=127.0.0.1,port=7895
-chardev socket,id=timer_tick,host=127.0.0.1,port=7896
-device  mmio-sockdev,chardev=timer_rw,irq-chardev=timer_irq,tick-chardev=timer_tick,tick-period-ms=1,addr=0x40006000,irq-num=2

# DMA Client Demo peripheral
-chardev socket,id=demo_rw,host=127.0.0.1,port=7898
-chardev socket,id=demo_irq,host=127.0.0.1,port=7899
-device  mmio-sockdev,chardev=demo_rw,irq-chardev=demo_irq,addr=0x40007000,irq-num=3

# CRC-32 engine (no IRQ, no tick)
-chardev socket,id=crc_rw,host=127.0.0.1,port=7900
-device  mmio-sockdev,chardev=crc_rw,addr=0x40008000

# Watchdog Timer (IRQ 4 pre-reset warning + rst-chardev for system reset)
-chardev socket,id=wdt_rw,host=127.0.0.1,port=7901
-chardev socket,id=wdt_irq,host=127.0.0.1,port=7902
-chardev socket,id=wdt_rst,host=127.0.0.1,port=7903
-device  mmio-sockdev,chardev=wdt_rw,irq-chardev=wdt_irq,rst-chardev=wdt_rst,addr=0x40009000,irq-num=4
```

## Quick Start

### Prerequisites

- Ubuntu/Debian (or compatible Linux)
- ARM cross-compiler: `sudo apt install gcc-arm-none-eabi`
- Python 3 (standard library only)
- Build tools: `sudo apt install build-essential ninja-build pkg-config libglib2.0-dev libpixman-1-dev`

### 1. Build firmware

```bash
make fw
```

Output: `build/firmware.elf` and `build/firmware.bin`. This also runs `make gen` to regenerate `build/generated/mmio_devices.h` from `spec/devices.yaml`.

### 2. Build QEMU (first time only — ~10-15 minutes)

```bash
make qemu
```

Output: `scripts/qemu-fork/build/qemu-system-arm`

### 3. Run end-to-end smoke test

```bash
bash scripts/e2e_test.sh
```

This single command:
1. Starts the Python device server (all six devices)
2. Waits for the UART port to be ready
3. Starts QEMU (`-M kx6625`) with six `mmio-sockdev` instances and the firmware
4. Polls firmware output in the server log for up to 120 s
5. Asserts all expected log lines are present and prints PASS or FAIL

Logs are written to `build/e2e_server.log` and `build/e2e_qemu.log` for post-mortem inspection.

**Expected output:**

```
[PASS] Found: "MMIO SockDev Interrupt Demo"
[PASS] Found: "NVIC initialised"
[PASS] Found: "IRQs enabled"
[PASS] Found: "UART interrupt handled"
[PASS] Found: "DMA demo"
[PASS] Found: "DMA started"
[PASS] Found: "Verification PASSED"
[PASS] Found: "Demo complete"
[PASS] Found: "DMA client test"
[PASS] Found: "DMA client transfer started"
[PASS] Found: "Transfer verified PASSED"
[PASS] Found: "All demos complete"
[PASS] Found: "CRC test"
[PASS] Found: "0xCBF43926 PASSED"
[PASS] Found: "DMA-CRC test"
[PASS] Found: "DMA-CRC] Result 0xCBF43926 PASSED"
[PASS] Found: "All tests done"
[PASS] Found: "Power-on reset (RESET_REASON=POR)"
[PASS] Found: "Kick 1"
[PASS] Found: "Kick 2"
[PASS] Found: "Waiting for WDT timeout"
[PASS] Found: "WDT] TIMEOUT"
[PASS] Found: "Warm boot detected: RESET_REASON=WDT"
[PASS] Found: "WDT demo complete"

[PASS] End-to-end IRQ test PASSED
```

**Troubleshooting:**

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Required file not found: …/qemu-system-arm` | QEMU not built yet | `make qemu` |
| `Required file not found: …/firmware.bin` | Firmware not built | `make fw` |
| Port already in use | Leftover process | `fuser -k 7890/tcp 7891/tcp` |
| Timeout / FAIL | IRQ not firing | Check `build/e2e_server.log` and `build/e2e_qemu.log` |

### 4. Run the full server interactively

**Terminal 1** — Python device server (all four devices):
```bash
python3 device_model/mmio_device_server.py
```

**Terminal 2** — QEMU:
```bash
bash scripts/run_demo.sh
```

Firmware character output (via TXDATA writes) appears in Terminal 1.

## Firmware Demo Sequence

The firmware (`firmware/main.c`) executes five demos back-to-back:

### Phase 1 — UART IRQ

1. Initialises NVIC (16 external IRQs armed, IRQs 0–4 enabled).
2. Enables IRQs and waits (`WFI`) for IRQ 0.
3. Python server fires the UART IRQ ~2 s after connecting; firmware acknowledges and prints `[FW] UART interrupt handled successfully!`.

### Phase 2 — DMA Memory-to-Memory Copy (CH0)

1. Fills SRAM source buffer `0x20000000` with bytes `0x01..0x20` (32 bytes).
2. Programs DMA CH0 registers: `CH0_SRC_ADDR=0x20000000`, `CH0_DST_ADDR=0x20000200`, `CH0_LENGTH=32`, `CH0_CTRL=START`.
3. DMA controller (Python) reads the source via `dma_read()`, writes the destination via `dma_write()`, then pulses IRQ 1 after 10 virtual ticks.
4. Firmware handles IRQ 1, then verifies the destination buffer matches the source.
5. Prints `[DMA] Verification PASSED!` and `[FW] Demo complete.`

### Phase 3 — DMA Client Demo (CH1, DREQ/DACK)

1. Firmware programs `DMA_CLIENT_DEMO` registers (`SRC_ADDR`, `DST_ADDR`, `LENGTH`) and writes `CTRL.START`.
2. `DmaClientDemoDevice` calls `dma_handle.transfer()` — DREQ to CH1.
3. DMA controller accepts (DACK), performs the copy, then calls the demo device's `on_complete` callback.
4. Demo device sets `STATUS.DONE` and pulses IRQ 3.
5. Firmware handles IRQ 3, verifies buffer, prints `[DMA] Transfer verified PASSED!` and `[FW] All demos complete.`

### Phase 4 — CRC-32 Verification

1. **Direct test**: firmware writes `CRC_CTRL=RESET`, then feeds the 9 bytes of `"123456789"` directly to `CRC_DATA`, reads `CRC_RESULT`. Asserts result equals `0xCBF43926`.
2. **DMA-fed test**: firmware sets up a DMA M2P transfer from SRAM (containing `"123456789"`) to `CRC_DATA` offset `0x40008000`, starts the transfer, waits for IRQ 1, reads `CRC_RESULT`. Asserts result equals `0xCBF43926`.
3. Prints `[CRC] Result 0xCBF43926 PASSED!`, `[DMA-CRC] Result 0xCBF43926 PASSED!`, and `[FW] All tests done.`

### Phase 5 — Watchdog Timer Reset Demo

1. **POR boot**: firmware reads `WDT_RESET_REASON_REG`; value = 0 (`REASON_POR`) → first boot path.
2. Sets `WDT_LOAD = 200 ms`, prints `"Kick 1"` and `"Kick 2"` (two `KICK` register writes).
3. Stops kicking, prints `"Waiting for WDT timeout"`. Python `WdtDevice.on_tick()` fires after 200 ms virtual time.
4. Python calls `SystemResetManager.wdt_reset()`: all bus devices `on_reset()` called (volatile state cleared, retention registers preserved), then `RstController.send_reset()` sends one byte to QEMU over TCP `:7903`.
5. QEMU receives the byte → `qemu_system_reset_request(SHUTDOWN_CAUSE_SUBSYSTEM_RESET)` — CPU reboots, TCP sockets stay open.
6. **Warm boot**: firmware reads `WDT_RESET_REASON_REG` = 1 (`REASON_WDT`) → warm boot path.
7. Reads `WDT_TIMEOUT_CNT_REG` (= 1), prints `"Warm boot detected: RESET_REASON=WDT"`, `"WDT demo complete"`, disables WDT.

## Project Structure

```
qemu_device/
├── Makefile                          # Top-level build system
├── README.md                         # This file
├── spec/                             # Device specs (single source of truth)
│   ├── devices.yaml                  # Platform memory map + IRQ + TCP port topology
│   ├── uart.yaml                     # Console UART register map
│   ├── dma.yaml                      # DMA controller CH0/CH1 register map
│   ├── dma_client_demo.yaml          # DMA client demo register map
│   ├── timer.yaml                    # Timer 0 register map
│   ├── crc.yaml                      # CRC-32 engine register map
│   └── wdt.yaml                      # Watchdog Timer register map
├── firmware/                         # Bare-metal Cortex-M3 firmware
│   ├── start.S                       # Vector table, Reset_Handler, IRQ dispatch (IRQ0–IRQ4)
│   ├── main.c                        # NVIC init + 5-phase demo (UART/DMA/CRC/WDT)
│   ├── linker.ld                     # Memory layout (FLASH @ 0x00000000, SRAM @ 0x20000000)
│   └── Makefile                      # Runs gen_device_code.py then compiles
├── device_model/                     # Python device emulation layer
│   ├── mmio_base.py                  # MMIODevice ABC; IRQController; MemChannel; RstController
│   │                                 #   RegisterBank (+ RegAccess policies); IrqLine;
│   │                                 #   VirtualClock; DmaRequestInterface
│   ├── mmio_device_server.py         # MMIOBus + RWServer + IRQServer + TickServer + MemServer
│   │                                 #   + RstServer + SystemResetManager + main()
│   ├── uart_model.py                 # Console UART (character output + demo IRQ)
│   ├── dma_controller.py             # DMA controller (multi-channel M2M + DREQ/DACK)
│   ├── dma_client_demo.py            # DMA client demo peripheral (DREQ/DACK to DMA CH1)
│   ├── timer_model.py                # Countdown timer (virtual-clock, one-shot + periodic)
│   ├── crc_device.py                 # CRC-32/ISO-HDLC hardware accelerator
│   ├── wdt_model.py                  # Watchdog Timer (countdown reset + retention registers)
│   └── generated/                    # Auto-generated constants (make gen / make fw)
│       └── device_consts.py          # Python constants mirroring mmio_devices.h
├── scripts/
│   ├── build_qemu.sh                 # QEMU configure + ninja build
│   ├── gen_device_code.py            # Code generator: spec/ → C header + Python consts
│   ├── run_demo.sh                   # Interactive demo launcher
│   ├── e2e_test.sh                   # Automated end-to-end smoke test
│   └── qemu-fork/                    # Modified QEMU 8.1.0 source tree (build target)
│       └── hw/
│           ├── misc/mmio_sockdev.c   # Generic SysBus mmio-sockdev (chardev/irq/tick/mem/rst)
│           └── arm/kx6625.c          # KX6625 custom SoC definition
└── build/                            # Build artifacts (gitignored)
    ├── firmware.elf / firmware.bin
    └── generated/
        └── mmio_devices.h            # Auto-generated C header (make gen / make fw)
```

## Makefile Targets

| Target       | Description                                                  |
|--------------|--------------------------------------------------------------|
| `make gen`   | Generate C header + Python consts from `spec/`               |
| `make fw`    | Generate constants, then build firmware (`build/firmware.elf`) |
| `make qemu`  | Copy `mmio_sockdev.c` to qemu-fork, then build QEMU          |
| `make run`   | Print interactive run instructions                           |
| `make clean` | Remove all build artifacts                                   |

## NVIC / IRQ Configuration

| Parameter             | Value                             |
|-----------------------|-----------------------------------|
| Machine               | `kx6625` (Cortex-M3 @ 48 MHz)    |
| NVIC external IRQs    | 16                                |
| UART IRQ              | 0 (`irq-num=0`)                   |
| DMA IRQ               | 1 (`irq-num=1`)                   |
| Timer 0 IRQ           | 2 (`irq-num=2`)                   |
| DMA Client Demo IRQ   | 3 (`irq-num=3`)                   |
| WDT pre-reset IRQ     | 4 (`irq-num=4`)                   |

IRQ pulse pattern: assert then immediately deassert to edge-trigger the NVIC without re-firing.

## Extending: Adding a New Device

1. **Define the spec**: add an entry in `spec/devices.yaml` and create `spec/<name>.yaml` with the register map.
2. **Write the model**: create `device_model/<name>_model.py` subclassing `MMIODevice`. Override `read()`, `write()`, and optionally `on_tick()` for timing behaviour. Use `RegisterBank` (with `RegAccess` policies) for register storage, `IrqLine` for interrupt injection, `VirtualClock` for countdown timing, and `DmaRequestInterface` for bus-master DMA requests. For watchdog-style resets, instantiate a `RstController` and pass a `SystemResetManager.wdt_reset` callback.
3. **Register on the bus**: add `bus.register(BASE, SIZE, YourDevice(...))` in `mmio_device_server.py`'s `main()`.
4. **Add transport servers**: create `RWServer` and `IRQServer` instances as needed. Devices that need timing use the existing `TickServer` automatically. Devices that need bus-master DMA get a dedicated `MemServer` instance. Devices that trigger system resets get an `RstServer` instance wired to a `RstController`.
5. **Extend the QEMU command line**: add a `mmio-sockdev` instance with `chardev`, `irq-chardev`, `addr`, `irq-num`. Add `mem-chardev` for DMA; `tick-chardev` for timer-style ticks; `rst-chardev` for system-reset capability.
6. Regenerate constants with `make gen`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `"chardev not connected"` | Start Python server before QEMU |
| `"Connection refused"` on port | Check server is running: `lsof -i :7890` |
| Firmware never prints | Verify `build/firmware.elf` exists (`make fw`) |
| IRQ never fires | Check `build/e2e_server.log`; confirm IRQ port not blocked |
| DMA never completes | Check `build/e2e_server.log` for `[MEM]` and `[TICK]` connection lines |
| WDT timeout never fires | Confirm WDT CTRL.ENABLE is set; check `[TICK]` connection in server log |
| QEMU never resets after WDT | Verify QEMU was rebuilt (`make qemu`) with `rst-chardev` support |
| Warm boot not detected | Python server was restarted (clears retention registers); re-run the full test |
| `"Property 'mmio-sockdev.rst-chardev' not found"` | QEMU binary is stale; run `make qemu` |
| QEMU build fails | Install missing libs: `sudo apt install libglib2.0-dev libpixman-1-dev` |
| ARM toolchain missing | `sudo apt install gcc-arm-none-eabi` |
| `"Parameter 'driver' expects a pluggable device type"` | QEMU binary is stale; run `make qemu` |
| Firmware stuck at "Waiting for UART interrupt" | Check NVIC configuration in `nvic_init()`; ensure IRQ 0 is enabled |

Stop QEMU: `Ctrl+C` (script) or `Ctrl+A X` (nographic monitor).

## License

This project is provided as educational material for understanding QEMU device development and ARM system emulation.
