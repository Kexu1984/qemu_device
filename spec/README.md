# Device Specifications

This directory contains the machine-readable YAML specifications for every peripheral in the KX6625 SoC model. The YAML files are processed by `scripts/gen_device_code.py` to auto-generate firmware C headers and Python constants.

```
spec/
├── devices.yaml          # Platform memory map, IRQ topology, TCP port assignments
├── uart.yaml             # Console UART register map
├── dma.yaml              # DMA controller register map (CH0 / CH1)
├── dma_client_demo.yaml  # DMA client demo peripheral register map
├── timer.yaml            # Countdown timer register map
├── crc.yaml              # CRC-32 engine register map
├── sv_timer.yaml         # SystemVerilog APB timer prototype register map
├── soc.yaml              # SoC-level configuration (clock, reset)
└── wdt.yaml              # Watchdog timer register map
```

---

## Memory Map

| Region           | Base Address  | Size   | NVIC IRQ | R/W Port | IRQ Port | Tick Port | Mem Port | RST Port | Term Port |
|------------------|---------------|--------|----------|----------|----------|-----------|----------|----------|-----------|
| Console UART     | `0x40004000`  | 4 KB   | 0        | 7890     | 7891     | —         | —        | —        | **7904**  |
| DMA Controller   | `0x40005000`  | 4 KB   | 1        | 7892     | 7893     | **7905**  | 7897     | —        | —         |
| Timer 0          | `0x40006000`  | 4 KB   | 2        | 7894     | 7895     | 7896      | —        | —        | —         |
| DMA Client Demo  | `0x40007000`  | 4 KB   | 3        | 7898     | 7899     | —         | —        | —        | —         |
| CRC-32 Engine    | `0x40008000`  | 4 KB   | —        | 7900     | —        | —         | —        | —        | —         |
| Watchdog Timer   | `0x40009000`  | 4 KB   | 4        | 7901     | 7902     | —         | —        | 7903     | —         |
| SV APB Timer     | `0x4000B000`  | 4 KB   | 5        | 7906     | 7907     | —         | —        | —        | —         |
| **FLASH**        | `0x00000000`  | 512 KB | —        | —        | —        | —         | —        | —        | —         |
| **SRAM**         | `0x20000000`  | 128 KB | —        | —        | —        | —         | —        | —        | —         |

> **Tick ports**: Port 7896 is the shared 1 ms periodic tick (Timer → all devices via `MMIOBus.tick_all()`). Port 7905 is the DMA DES one-shot tick — QEMU fires it at exactly `arm_vtime + transfer_ns` in virtual time.

---

## Console UART (`uart_model.py`)

| Offset | Name   | Access | Reset | Description                        |
|--------|--------|--------|-------|------------------------------------|
| 0x00   | TXDATA | W      | 0x00  | Write byte to stdout (low 8 bits)  |
| 0x04   | STATUS | R      | 0x01  | bit0 = TXREADY (always 1)          |
| 0x08   | CTRL   | R/W    | 0x01  | bit0 = ENABLE                      |

Fires a one-shot demo IRQ ~2 s after the IRQ channel connects. Every byte written to TXDATA is also forwarded to the `UartChannel` TCP server on port **7904** for live terminal viewing.

---

## DMA Controller (`dma_controller.py`)

Two independent channels. Each occupies a 0x20-byte register slot.

**Per-channel layout (stride = 0x20; CH0 @ +0x00, CH1 @ +0x20):**

| Offset within slot | Name        | Access | Reset | Description                           |
|--------------------|-------------|--------|-------|---------------------------------------|
| +0x00              | CH_SRC_ADDR | R/W    | 0     | Transfer source physical address      |
| +0x04              | CH_DST_ADDR | R/W    | 0     | Transfer destination physical address |
| +0x08              | CH_LENGTH   | R/W    | 0     | Transfer length in bytes              |
| +0x0C              | CH_CTRL     | R/W    | 0     | bit0 = START, bit1 = ENABLE           |
| +0x10              | CH_STATUS   | R      | 0     | bit0 = BUSY, bit1 = DONE              |
| +0x14              | CH_SRC_MODE | R/W    | 0     | bit0 = FIXED (no auto-increment)      |
| +0x18              | CH_DST_MODE | R/W    | 0     | bit0 = FIXED (no auto-increment)      |

**Transfer latency model (virtual time):**

| Transfer type | Formula | Example (32B M2M) |
|---------------|---------|-------------------|
| M2M | `(1 + N_AHB) × 20ns + N_FSM × 83ns` | `(1+8)×20 + 4×83 = 512 ns` |
| M2P | `(1 + N_AHB) × 20ns + N_FSM × 83ns` | `(1+3)×20 + 4×83 = 412 ns` |

Where `NS_PER_HCLK = 20 ns` (48 MHz), `NS_PER_PCLK = 83 ns` (12 MHz). Writing `CH_CTRL.START` returns `transfer_ns` to QEMU (DES protocol), which schedules a virtual-time tick at exactly `now_vtime + transfer_ns`.

---

## DMA Client Demo (`dma_client_demo.py`)

Demo peripheral that uses the DMA controller's DREQ/DACK interface.

| Offset | Name     | Access | Reset | Description                           |
|--------|----------|--------|-------|---------------------------------------|
| 0x00   | SRC_ADDR | R/W    | 0     | Transfer source physical address      |
| 0x04   | DST_ADDR | R/W    | 0     | Transfer destination physical address |
| 0x08   | LENGTH   | R/W    | 0     | Transfer length in bytes              |
| 0x0C   | CTRL     | R/W    | 0     | bit0 = START                          |
| 0x10   | STATUS   | R      | 0     | bit0 = BUSY, bit1 = DONE              |

Firmware writes `CTRL.START`; the device asserts DREQ to DMA CH1. On completion, `STATUS.DONE` is set and IRQ 3 is pulsed.

---

## Timer 0 (`timer_model.py`)

| Offset | Name    | Access | Reset | Description                                             |
|--------|---------|--------|-------|---------------------------------------------------------|
| 0x00   | LOAD    | R/W    | 0     | Countdown value in milliseconds (0 = disabled)          |
| 0x04   | VALUE   | R      | 0     | Remaining time in ms (virtual-clock based)              |
| 0x08   | CTRL    | R/W    | 0     | bit0 = ENABLE, bit1 = INT_ENABLE, bit2 = PERIODIC       |
| 0x0C   | INTCLR  | W      | —     | Write any value to clear pending interrupt              |
| 0x10   | STATUS  | R      | 0     | bit0 = INT_PENDING                                      |

Writing `CTRL.ENABLE` returns `load_ms × 1_000_000` ns to QEMU (DES protocol) — QEMU schedules the expiry tick in virtual time. Periodic mode re-arms each expiry from the previous deadline (no drift accumulation).

---

## CRC-32 Engine (`crc_device.py`)

CRC-32/ISO-HDLC (IEEE 802.3 / Ethernet / ZIP / PNG polynomial `0x04C11DB7`).

| Offset | Name   | Access | Reset        | Description                                                  |
|--------|--------|--------|--------------|--------------------------------------------------------------|
| 0x00   | DATA   | R/W    | —            | Write: feed bytes into accumulator. Read: raw accumulator    |
| 0x04   | RESULT | R      | —            | Final result (`accumulator ^ 0xFFFFFFFF`)                    |
| 0x08   | CTRL   | R/W    | 0            | bit0 = RESET — write 1 to reset accumulator to `0xFFFFFFFF` |

Test vector: `CRC-32("123456789") = 0xCBF43926`. Supports byte and word writes; word writes feed four bytes in little-endian order. Compatible with firmware direct writes and DMA M2P bus-master transfers.

---

## Watchdog Timer (`wdt_model.py`)

| Offset | Name         | Access | Reset | Description                                                        |
|--------|--------------|--------|-------|--------------------------------------------------------------------|
| 0x00   | LOAD         | R/W    | 0     | Timeout value in milliseconds (0 = disabled)                       |
| 0x04   | VALUE        | R      | 0     | Remaining time in ms (virtual-clock based)                         |
| 0x08   | CTRL         | R/W    | 0     | bit0 = ENABLE, bit1 = INT_ENABLE (fire IRQ 4 before reset)         |
| 0x0C   | KICK         | W      | —     | Write any value to reload countdown and clear STATUS.TIMEOUT        |
| 0x10   | STATUS       | R      | 0     | bit0 = TIMEOUT                                                     |
| 0x14   | RESET_REASON | R      | 0     | **Retention**: 0 = POR, 1 = WDT reset                              |
| 0x18   | TIMEOUT_CNT  | R      | 0     | **Retention**: number of WDT timeouts since power-on               |

**Retention registers** (`RESET_REASON`, `TIMEOUT_CNT`) survive a watchdog reset: they live in the Python device model instance, which persists across QEMU system resets. Only a full Python server restart (power-on reset) clears them to 0.

**Reset flow**: On timeout, `WdtDevice.on_tick()` sets `RESET_REASON=1`, increments `TIMEOUT_CNT`, optionally pulses IRQ 4 (pre-reset warning), then calls `SystemResetManager.wdt_reset()` → `qemu_system_reset_request()` on the QEMU side. TCP sockets remain connected.

---

## SV APB Timer (`sv_device/sv_timer_apb.sv`)

| Offset | Name      | Access | Reset | Description                                  |
|--------|-----------|--------|-------|----------------------------------------------|
| 0x00   | CTRL      | R/W    | 0     | bit0 = ENABLE, bit1 = IRQ_EN                 |
| 0x04   | LOAD      | R/W    | 0     | Countdown load value in SV clock cycles      |
| 0x08   | VALUE     | R      | 0     | Current countdown value                      |
| 0x0C   | STATUS    | R      | 0     | bit0 = IRQ_PENDING                           |
| 0x10   | IRQ_CLEAR | W      | —     | Write bit0 = 1 to clear IRQ_PENDING and IRQ5 |

The Verilator bridge listens on R/W port 7906 and IRQ port 7907. QEMU still sees this as a normal `mmio-sockdev` region at `0x4000B000`; the bridge converts each MMIO access into APB setup/access cycles on the SV RTL.

---

## Code Generation

```bash
make gen
# or directly:
python3 scripts/gen_device_code.py
```

Outputs:
- `build/generated/mmio_devices.h` — C `#define` constants for firmware
- `device_model/generated/device_consts.py` — Python constants for device models and tests
