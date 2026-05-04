# Timing Model

This document explains the timing model used by the KX6625 QEMU prototype. It focuses on the boundary between QEMU timing, Python device timing, and SystemVerilog device timing.

The most important rule is simple: this project has multiple time domains. They are connected through transactions and events, not through one global cycle-accurate clock.

## Time Domains

| Domain | Unit | Driver | Determinism | Main use |
|--------|------|--------|-------------|----------|
| Host wall-clock | host time | Linux scheduler, TCP, process execution | Not deterministic | Process runtime and socket latency |
| QEMU virtual time | nanoseconds | QEMU `QEMU_CLOCK_VIRTUAL`; deterministic with `-icount` | Deterministic when `ICOUNT_SHIFT=5` is used | CPU execution, QEMU timers, Python timed events |
| Python device time | QEMU virtual-time timestamps | Tick/DES messages from `mmio-sockdev` | Deterministic when driven by QEMU virtual time | Timer, WDT, DMA latency, modeled device events |
| SV local time | Verilator cycles | SV bridge `eval_cycle()` loop | Local to the bridge, not tied to QEMU virtual time | RTL pclk/APB/register state machines |

The platform intentionally does not force these into a single cycle-accurate full-chip clock. QEMU provides a CPU/software behavioral model; Python devices provide deterministic functional device timing; SV devices keep a local RTL-style clock and communicate through MMIO/IRQ transaction boundaries.

## QEMU Timing

QEMU owns CPU execution time and virtual timers.

The recommended deterministic mode is:

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

This maps guest instruction execution to virtual time with:

```text
QEMU_CLOCK_VIRTUAL = executed_instruction_count * 32 ns
```

This is selected to approximate KX6625 CPU execution at 48 MHz with a functional CPI assumption. It is not a promise of exact CPU pipeline timing.

### QEMU Virtual Timers

`mmio-sockdev` creates `QEMUTimer` objects on `QEMU_CLOCK_VIRTUAL` for tick-capable devices. When the timer fires, QEMU sends the current virtual timestamp to the external model:

```text
'T' | vtime_ns
```

Because this uses `QEMU_CLOCK_VIRTUAL`, timers freeze when QEMU virtual execution freezes. Under `icount`, `WFI` can advance virtual time directly to the next timer deadline instead of waiting for host wall-clock time.

### MMIO Access Timing

Guest MMIO reads/writes are synchronous from the CPU point of view.

For a socket-backed device:

1. Firmware executes an MMIO read or write.
2. QEMU enters the `mmio-sockdev` callback.
3. QEMU sends a TCP request to the Python or SV model.
4. QEMU waits for the response.
5. The guest instruction completes.

The host TCP round trip consumes wall-clock time, but it does not automatically add guest virtual time. From the chip-functional model point of view, the register access is an instantaneous transaction unless the device explicitly schedules a later event.

### Cortex-M SysTick

The Cortex-M SysTick used by FreeRTOS is part of QEMU's ARMv7-M CPU container. It is separate from the KX6625 external `timer0` Python device.

- SysTick drives FreeRTOS scheduling on CPU0.
- `timer0` is a modeled external peripheral that can raise an NVIC external IRQ.
- Both are ultimately observed through QEMU CPU execution, but they are not the same block.

### Running Without Icount

Without `ICOUNT_SHIFT`, QEMU still has virtual timers, but the run is not deterministic in the same way. Timer delivery and CPU progress can depend on host scheduling, execution speed, socket latency, and process timing.

Use non-icount runs only for convenience or manual exploration. Use `ICOUNT_SHIFT=5` for regression and timing-sensitive validation.

## Python Device Timing

Python devices do not own a clock by themselves. They receive timing from QEMU through `mmio-sockdev`.

There are two timing mechanisms.

## Periodic Tick

A `mmio-sockdev` instance with `tick-chardev` and `tick-period-ms > 0` sends periodic virtual-time messages:

```text
QEMU QEMUTimer fires on QEMU_CLOCK_VIRTUAL
    -> mmio-sockdev sends 'T' | vtime_ns
    -> Python TickServer receives the timestamp
    -> TickServer calls bus.tick_all(vtime_ns)
    -> each device may run on_tick(vtime_ns)
```

This is used for coarse shared time progression, such as timer/WDT style countdown logic. Devices that do not need timing inherit a no-op `on_tick()`.

The timestamp is absolute QEMU virtual time in nanoseconds. Device code should compute elapsed time from timestamps instead of counting host callbacks.

## DES One-Shot Tick

The DES path is used when a device can predict the exact time of its next event.

On every write, the Python device returns an 8-byte little-endian value:

```text
next_event_ns = 0      no event scheduled
next_event_ns > 0      ask QEMU to fire a tick after this many virtual ns
```

QEMU handles `next_event_ns > 0` with:

```text
fire_time = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + next_event_ns
timer_mod(tick_timer, fire_time)
```

Then QEMU later sends:

```text
'T' | fire_time
```

The Python device receives this through `on_tick(fire_time)` and completes the event, such as DMA completion or timer expiry.

This is better than waiting for the next periodic tick when the event deadline is known precisely.

## Python Timing Rules

Use these rules for Python device models:

- Model time from QEMU virtual timestamps, not host `time.time()`.
- Use DES one-shot scheduling for precise completion events.
- Use periodic ticks for simple countdown or background checks.
- Treat MMIO register writes as configuration transactions; schedule the later hardware effect explicitly if it is not instantaneous.
- Do not assume TCP latency corresponds to bus latency.
- Do not busy-wait in Python to model device time.

## Current Python Examples

| Device | Timing style | Notes |
|--------|--------------|-------|
| Timer | DES/virtual-time expiry | Register write can schedule the exact expiry deadline |
| DMA | DES one-shot | Transfer latency is computed and completion happens on the scheduled tick |
| WDT | Virtual-time countdown | Timeout is based on simulated chip time, not host time |
| HSM | Functional operation with DMA memory access | Current crypto operation is functional; add scheduled latency if a future model needs cycle-level crypto duration |
| UART/CRC/OTP | Mostly untimed functional MMIO | Register effects are immediate unless explicitly modeled otherwise |

## SystemVerilog Device Timing

SystemVerilog devices use a separate local clock inside the Verilator bridge. This clock is not `QEMU_CLOCK_VIRTUAL`.

The current bridge advances SV time in two ways:

- APB reads/writes explicitly call `eval_cycle()` to execute setup/access/cleanup cycles.
- When no MMIO request is pending, the bridge poll loop times out and calls `run_cycles(kIdleCyclesPerPoll)`, currently 16 cycles per idle poll.

This means SV devices continue to have a local notion of pclk cycles even when QEMU is not issuing MMIO requests. That local progression is driven by the bridge process and host scheduling, not by QEMU `icount`.

## SV Transaction Boundary

From QEMU's point of view, an SV device is still accessed through a synchronous `mmio-sockdev` transaction:

```text
Firmware MMIO access
    -> QEMU mmio-sockdev
    -> TCP request to SV bridge
    -> bridge performs APB cycles on Verilated RTL
    -> bridge returns register data or write response
    -> QEMU resumes guest CPU
```

The APB operation can consume several SV local cycles. Those cycles do not automatically advance QEMU virtual time. They only advance the Verilated device state.

## SV IRQ Timing

An SV block can raise an IRQ after local RTL cycles. The bridge observes the RTL IRQ output and sends an IRQ message to QEMU. QEMU then injects the corresponding NVIC interrupt into the guest-visible CPU model.

This is a functional interrupt connection, not a cycle-accurate cross-domain timing model. The exact relationship between an SV pclk edge and a QEMU CPU instruction boundary is not modeled.

## Comparing Python and SV Timing

Python and SV timing have different purposes.

| Aspect | Python model | SV model |
|--------|--------------|----------|
| Clock source | QEMU virtual time | Bridge-local Verilator cycles |
| Best for | Functional device behavior, deterministic event latency, fast reference models | RTL register behavior, local state machines, APB protocol validation |
| Regression determinism | Strong with `ICOUNT_SHIFT=5` | Functional, but local-cycle progress can depend on bridge scheduling |
| CPU cycle alignment | Not cycle accurate | Not cycle accurate across QEMU CPU and SV pclk |
| Transaction behavior | Synchronous MMIO plus scheduled events | Synchronous MMIO converted into APB cycles |

A Python device is the better place for deterministic chip-virtual-time behavior. An SV device is the better place for RTL block behavior. Neither currently models a full bus fabric with wait states and exact CPU/APB clock crossing.

## What Is Modeled

The platform models:

- CPU-visible functional ordering of MMIO accesses.
- NVIC interrupt delivery at the behavioral level.
- Deterministic QEMU/Python virtual-time events under `icount`.
- Local RTL cycles inside the SV bridge.
- DMA-style memory access through the QEMU physical memory channel.
- WFI wakeup from virtual timer or interrupt events.

## What Is Not Modeled

The platform does not currently model:

- Exact CPU pipeline timing.
- Exact AHB/APB wait states for every access.
- Cycle-accurate QEMU CPU to SV pclk alignment.
- Full clock-domain crossing synchronizers.
- Analog PLL/oscillator behavior.
- Host TCP latency as chip bus latency.
- A global event scheduler shared by QEMU, Python, and SV.

These can be added selectively later, but they should be explicit feature decisions rather than accidental assumptions.

## Design Guidance

When adding a timed feature, choose the timing owner deliberately:

- Use QEMU native timers for CPU/container-local behavior or native SoC controller behavior.
- Use Python DES for deterministic peripheral completion latency.
- Use Python periodic tick for simple virtual-time countdowns.
- Use SV local cycles for RTL state machines and APB-visible hardware behavior.
- Use status bits or sideband signals for pre-CPU hardware handshakes.
- Use NVIC IRQs only when firmware should observe and handle the event.

If a feature needs cross-domain accuracy, document the intended relationship first. The default platform assumption is functional ordering plus explicit timing events, not full-chip cycle accuracy.

## Debugging Checklist

When timing behavior looks wrong, check:

- Was the run started with `ICOUNT_SHIFT=5`?
- Is the device using `on_tick(vtime_ns)` rather than host time?
- Did the Python write handler return the intended `next_event_ns`?
- Does the corresponding `mmio-sockdev` instance have a `tick-chardev`?
- Is `tick-period-ms` periodic or zero for DES-only mode?
- Is the firmware waiting with `WFI`, polling, or relying on an IRQ?
- Is the event in a Python virtual-time model or an SV local-cycle model?
- For SV behavior, did the bridge have a chance to run local cycles?
- Is the expected behavior a CPU interrupt, a register status bit, or a local hardware signal?
