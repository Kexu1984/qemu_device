# QEMU Custom MMIO Socket Device

A framework for implementing custom ARM hardware devices in QEMU, with register logic and interrupt firing modelled in Python. A single generic QEMU SysBus device (`mmio-sockdev`) proxies MMIO reads/writes, IRQ lines, virtual-clock ticks, and bus-master DMA to/from external Python device models over TCP. A shared virtual-clock tick mechanism lets any device implement timing-dependent behaviour (countdown timers, DMA latency, etc.) that tracks QEMU's simulated time exactly.

## Overview

This project implements:
- **Custom QEMU Device** (`mmio-sockdev`): Generic SysBus proxy — 4 KB MMIO, IRQ line, optional virtual-clock tick channel, optional bus-master DMA memory channel. One instance per device on the QEMU command line.
- **Python Device Server** (`device_model/mmio_device_server.py`): Transport + address dispatcher (`MMIOBus`). Each peripheral is a `MMIODevice` subclass with `read()`, `write()`, and an optional `on_tick()` override.
- **Three modelled peripherals**: Console UART, DMA controller, countdown timer.
- **Bare-Metal ARM Firmware**: ARMv7-A / GICv2 init, IRQ handler, UART demo, DMA memory-copy demo.
- **SRAM region**: 64 KB at `0x20000000` added to the QEMU `virt` machine — accessible by both the CPU and the DMA device model via the bus-master memory channel.
- **End-to-End Smoke Test** (`scripts/e2e_test.sh`): Starts Python server, boots QEMU, fires UART IRQ and DMA transfer, asserts firmware output.

## Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  QEMU  (ARM virt, Cortex-A15, GICv2)                                                       │
│                                                                                            │
│  ┌──────────────┐    MMIO                ┌──────────────────────────────────────────────┐ │
│  │  Firmware    │ ─── read/write ──────► │  mmio-sockdev (×3 instances)                 │ │
│  │  (ARMv7-A)   │                        │                                              │ │
│  │              │ ◄── IRQ (GICv2 SPI) ── │   chardev      ↔ R/W TCP channel             │ │
│  └──────┬───────┘                        │   irq-chardev  ← IRQ TCP channel             │ │
│         │                                │   tick-chardev → virtual-clock tick TCP      │ │
│         │ read/write                     │   mem-chardev  ← DMA bus-master TCP (opt.)   │ │
│         ▼                                └───────────┬──────────────────────────────────┘ │
│  ┌──────────────┐                                    │ TCP channels                       │
│  │  SRAM 64 KB  │ ◄── cpu_physical_memory_write ─────┘ (mem-chardev → QEMU phys mem)     │
│  │  0x20000000  │                                                                         │
│  └──────────────┘   QEMU_CLOCK_VIRTUAL fires QEMUTimer every tick-period-ms              │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                              │ TCP (per-channel connections)
                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│  Python Device Server  (device_model/mmio_device_server.py)                                │
│                                                                                            │
│  RWServer               IRQServer              TickServer          MemServer               │
│  :7890/:7892/:7894      :7891/:7893/:7895      :7896               :7897                   │
│  QEMU ↔ Python          Python → QEMU          QEMU → Python       Python → QEMU           │
│  (MMIO R/W ops)         (IRQ injection)        (virtual clock)     (bus-master DMA)        │
│        │                      │                     │                   │                  │
│        └──────────────┬───────┘          bus.tick_all(vtime_ns)   MemChannel               │
│                       │                                            dma_read/dma_write()    │
│                   MMIOBus                                               │                  │
│          ┌────────────┼────────────┐                                   │                  │
│          ▼            ▼            ▼                                   │                  │
│  ConsoleUartDevice  DmaDevice  TimerDevice                             │                  │
│  0x10020000         0x10030000  0x10040000                             │                  │
│       │             on_tick():  on_tick():                             │                  │
│       │             countdown;  elapsed check                          │                  │
│       │             dma_read() ─────────────────────────────────────── ┘ → SRAM read      │
│       │             dma_write()─────────────────────────── QEMU phys mem write (SRAM)     │
│       │             fire IRQ 33                                                            │
│       └─ fire IRQ 32                                                                       │
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
                   ├── ConsoleUartDevice.on_tick()  →  no-op (inherited)
                   ├── DmaDevice.on_tick()          →  decrement _ticks_remaining; DMA copy + IRQ on 0
                   └── TimerDevice.on_tick()        →  check elapsed_ns ≥ load_ns; IRQ on expiry
```

### IRQ Flow

```
MMIODevice.irq_controller.set_irq(idx, level)
    │  'I'(1B) | idx(1B) | level(1B)  (TCP irq-port)
    ▼
mmio-sockdev (QEMU)  ──►  GICv2 SPI (INTID = irq-num)  ──►  Cortex-A15 IRQ line
```

### Bus-Master DMA Flow

The DMA device model acts as a bus master: it directly reads/writes QEMU physical memory without involving the firmware CPU. This is modelled via a dedicated `mem-chardev` TCP channel:

```
DmaDevice.on_tick() calls:
    MemChannel.dma_read(src_addr, length)
        │  'M'(1B)|'R'(1B)|phys_addr(8B LE)|length(4B LE)  → QEMU
        │  QEMU executes cpu_physical_memory_read() and responds data(lengthB)
        ▼
    MemChannel.dma_write(dst_addr, data)
        │  'M'(1B)|'W'(1B)|phys_addr(8B LE)|length(4B LE)|data(lengthB)  → QEMU
        ▼
        QEMU executes cpu_physical_memory_write() into the SRAM region
```

## Devices

### Memory Map

| Region        | Base Address  | Size   | GIC INTID  | R/W Port | IRQ Port | Tick Port | Mem Port |
|---------------|---------------|--------|------------|----------|----------|-----------|----------|
| Console UART  | `0x10020000`  | 4 KB   | 32 (SPI 0) | 7890     | 7891     | —         | —        |
| DMA           | `0x10030000`  | 4 KB   | 33 (SPI 1) | 7892     | 7893     | —         | 7897     |
| Timer 0       | `0x10040000`  | 4 KB   | 34 (SPI 2) | 7894     | 7895     | 7896      | —        |
| **SRAM**      | `0x20000000`  | 64 KB  | —          | —        | —        | —         | —        |

The tick channel (`:7896`) is shared — a single `TickServer` broadcasts ticks from the timer's `mmio-sockdev` instance to **all** bus devices via `MMIOBus.tick_all()`.

### Console UART (`uart_model.py`)

| Offset | Name    | Access | Description                         |
|--------|---------|--------|-------------------------------------|
| 0x00   | TXDATA  | W      | Write byte to stdout (low 8 bits)   |
| 0x04   | STATUS  | R      | bit0 = TXREADY (always 1)           |
| 0x08   | CTRL    | R/W    | bit0 = ENABLE                       |

Fires a one-shot demo IRQ ~2 s after the IRQ channel connects. Does not use `on_tick()`. Characters are line-buffered in Python (flushed on `\n`) to prevent interleaving with other device thread output.

### DMA Controller (`dma_model.py`)

| Offset | Name     | Access | Description                          |
|--------|----------|--------|--------------------------------------|
| 0x00   | SRC_ADDR | R/W    | Transfer source physical address     |
| 0x04   | DST_ADDR | R/W    | Transfer destination physical address|
| 0x08   | LENGTH   | R/W    | Transfer length in bytes             |
| 0x0C   | CTRL     | R/W    | bit0 = START, bit1 = ENABLE          |
| 0x10   | STATUS   | R      | bit0 = BUSY, bit1 = DONE             |

Writing `CTRL.START` sets `STATUS.BUSY` and starts a virtual-clock countdown (`transfer_ticks = 10` by default). After 10 ticks the DMA model:
1. Reads `length` bytes from `src_addr` in QEMU physical memory via `MemChannel.dma_read()`.
2. Writes them to `dst_addr` via `MemChannel.dma_write()`.
3. Sets `STATUS.DONE`, clears `STATUS.BUSY`, and fires IRQ 33.

### Timer 0 (`timer_model.py`)

| Offset | Name   | Access | Description                              |
|--------|--------|--------|------------------------------------------|
| 0x00   | LOAD   | R/W    | Countdown value in milliseconds          |
| 0x04   | VALUE  | R      | Remaining time in ms (virtual-clock)     |
| 0x08   | CTRL   | R/W    | bit0 = ENABLE, bit1 = PERIODIC, bit2 = INT_ENABLE |
| 0x0C   | STATUS | R      | bit0 = INT_PENDING                       |
| 0x10   | INTCLR | W      | Write any value to clear INT_PENDING     |

Writing `CTRL.ENABLE` records `vtime_ns` from the next tick. `on_tick()` computes `elapsed_ns = vtime_ns − start_vtime_ns`; fires IRQ when `elapsed_ns ≥ LOAD × 1 000 000`. Re-arms automatically in periodic mode.

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

## QEMU Command Line

The Python device server binds all TCP ports first; QEMU connects to them as a client. Each device needs one `mmio-sockdev` instance. The timer instance also carries the shared tick channel:

```bash
# Console UART
-chardev socket,id=uart_rw,host=127.0.0.1,port=7890
-chardev socket,id=uart_irq,host=127.0.0.1,port=7891
-device  mmio-sockdev,chardev=uart_rw,irq-chardev=uart_irq,addr=0x10020000,irq-num=32

# DMA (includes bus-master memory channel)
-chardev socket,id=dma_rw,host=127.0.0.1,port=7892
-chardev socket,id=dma_irq,host=127.0.0.1,port=7893
-chardev socket,id=dma_mem,host=127.0.0.1,port=7897
-device  mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,mem-chardev=dma_mem,addr=0x10030000,irq-num=33

# Timer 0  (also carries the shared tick broadcast)
-chardev socket,id=timer_rw,host=127.0.0.1,port=7894
-chardev socket,id=timer_irq,host=127.0.0.1,port=7895
-chardev socket,id=timer_tick,host=127.0.0.1,port=7896
-device  mmio-sockdev,chardev=timer_rw,irq-chardev=timer_irq,tick-chardev=timer_tick,tick-period-ms=1,addr=0x10040000,irq-num=34
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
1. Starts the Python device server (all three devices)
2. Waits for the UART port to be ready
3. Starts QEMU with three `mmio-sockdev` instances and the firmware
4. Polls firmware output in the server log for up to 80 s
5. Asserts all expected log lines are present and prints PASS or FAIL

Logs are written to `build/e2e_server.log` and `build/e2e_qemu.log` for post-mortem inspection.

**Expected output:**

```
[PASS] Found: "MMIO SockDev Interrupt Demo"
[PASS] Found: "GIC initialised"
[PASS] Found: "IRQs enabled"
[PASS] Found: "UART interrupt handled"
[PASS] Found: "DMA demo"
[PASS] Found: "DMA started"
[PASS] Found: "Verification PASSED"
[PASS] Found: "Demo complete"

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

**Terminal 1** — Python device server (all three devices):
```bash
python3 device_model/mmio_device_server.py
```

**Terminal 2** — QEMU:
```bash
bash scripts/run_demo.sh
```

Firmware character output (via TXDATA writes) appears in Terminal 1.

## Firmware Demo Sequence

The firmware (`firmware/main.c`) executes two demos back-to-back:

### Phase 1 — UART IRQ

1. Initialises GICv2 (Group0, INTID 32 + 33 armed, routed to CPU 0).
2. Enables IRQs and polls `GICC_IAR` / `wfi` for INTID 32.
3. Python server fires the UART IRQ ~2 s after connecting; firmware acknowledges and prints `[FW] UART interrupt handled successfully!`.

### Phase 2 — DMA Memory Copy

1. Fills SRAM source buffer `0x20000000+0x000` with bytes `0x01..0x20` (32 bytes).
2. Programs DMA registers: `SRC=0x20000000`, `DST=0x20000200`, `LEN=32`, `CTRL=START|ENABLE`.
3. DMA device model (Python) reads the source via `dma_read()`, writes the destination via `dma_write()`, then fires IRQ 33 after 10 virtual ticks.
4. Firmware polls for INTID 33, then verifies the destination buffer matches the source.
5. Prints `[DMA] Verification PASSED!` and `[FW] Demo complete.`

## Project Structure

```
qemu_device/
├── Makefile                          # Top-level build system
├── README.md                         # This file
├── spec/                             # Device specs (single source of truth)
│   ├── devices.yaml                  # Platform memory map + IRQ + TCP port topology
│   ├── uart.yaml                     # Console UART register map
│   ├── dma.yaml                      # DMA controller register map
│   └── timer.yaml                    # Timer 0 register map
├── firmware/                         # Bare-metal ARM firmware
│   ├── start.S                       # Vector table, mode stacks, VBAR setup
│   ├── main.c                        # GICv2 init + UART IRQ demo + DMA demo
│   ├── linker.ld                     # Memory layout (text at 0x40200000)
│   └── Makefile                      # Runs gen_device_code.py then compiles
├── device_model/                     # Python device emulation layer
│   ├── mmio_base.py                  # MMIODevice ABC, IRQController, MemChannel, recv_exact()
│   ├── mmio_device_server.py         # MMIOBus + RWServer + IRQServer + TickServer + MemServer + main()
│   ├── uart_model.py                 # Console UART (character output + demo IRQ)
│   ├── dma_model.py                  # DMA controller (tick-based latency + bus-master copy)
│   ├── timer_model.py                # Countdown timer (virtual-clock, one-shot + periodic)
│   ├── mmio_sockdev.c                # QEMU C device model (canonical source — copied to qemu-fork on build)
│   └── generated/                    # Auto-generated constants (make gen / make fw)
│       └── device_consts.py          # Python constants mirroring mmio_devices.h
├── scripts/
│   ├── build_qemu.sh                 # QEMU configure + ninja build
│   ├── gen_device_code.py            # Code generator: spec/ → C header + Python consts
│   ├── run_demo.sh                   # Interactive demo launcher
│   ├── e2e_test.sh                   # Automated end-to-end smoke test
│   └── qemu-fork/                    # Modified QEMU 8.1.0 source tree
│       ├── hw/misc/mmio_sockdev.c    # Custom SysBus device (built copy)
│       └── hw/arm/virt.c             # virt machine: SRAM region + mmio-sockdev whitelist
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

## GIC / IRQ Configuration

| Parameter     | Value                                   |
|---------------|-----------------------------------------|
| Machine       | `virt` (Cortex-A15)                     |
| GIC version   | GICv2                                   |
| GICD base     | `0x08000000`                            |
| GICC base     | `0x08010000`                            |
| UART IRQ      | INTID 32 = SPI 0 (`irq-num=32`)         |
| DMA IRQ       | INTID 33 = SPI 1 (`irq-num=33`)         |
| Timer 0 IRQ   | INTID 34 = SPI 2 (`irq-num=34`)         |

**Note — Group0 requirement for Secure SVC mode**: The ARM Cortex-A15 resets into Secure SVC mode. When SPIs are configured as **Group1** (`GICD_IGROUPR1 ≠ 0`), `GICC_IAR` returns INTID **1022** instead of the actual interrupt ID (with `AckCtl=0`). The firmware therefore keeps all used SPIs in **Group0** (`GICD_IGROUPR1 = 0`) and enables only Group0 at the CPU Interface (`GICC_CTLR = 1`). This causes `GICC_IAR` to return the real INTID directly in Secure state.

## Extending: Adding a New Device

1. **Define the spec**: add an entry in `spec/devices.yaml` and create `spec/<name>.yaml` with the register map.
2. **Write the model**: create `device_model/<name>_model.py` subclassing `MMIODevice`. Override `read()`, `write()`, and optionally `on_tick()` for timing behaviour or `MemChannel.dma_read/write()` for bus-master DMA.
3. **Register on the bus**: add `bus.register(BASE, SIZE, YourDevice(...))` in `mmio_device_server.py`'s `main()`.
4. **Add transport servers**: create `RWServer` and `IRQServer` instances as needed. If the device needs timing, it uses the existing `TickServer` automatically (no changes required). If it needs bus-master DMA, add a `MemServer` instance.
5. **Extend the QEMU command line**: add a `mmio-sockdev` instance with the appropriate `chardev`/`irq-chardev`/`addr`/`irq-num` properties. Add `mem-chardev` for DMA.
6. Regenerate constants with `make gen`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `"chardev not connected"` | Start Python server before QEMU |
| `"Connection refused"` on port | Check server is running: `lsof -i :7890` |
| Firmware never prints | Verify `build/firmware.elf` exists (`make fw`) |
| IRQ never fires | Check `build/e2e_server.log`; confirm IRQ port not blocked |
| DMA never completes | Check `build/e2e_server.log` for `[MEM]` and `[TICK]` connection lines |
| QEMU build fails | Install missing libs: `sudo apt install libglib2.0-dev libpixman-1-dev` |
| ARM toolchain missing | `sudo apt install gcc-arm-none-eabi` |
| `"Parameter 'driver' expects a pluggable device type"` | QEMU binary is stale; run `make qemu` |
| Firmware stuck at "Waiting for UART interrupt" | GIC misconfiguration; ensure `GICD_IGROUPR1=0` (Group0) in `gic_init()` |

Stop QEMU: `Ctrl+C` (script) or `Ctrl+A X` (nographic monitor).

## License

This project is provided as educational material for understanding QEMU device development and ARM system emulation.
