# 04. FreeRTOS、双核启动和 Firmware Demo 闭环

## 本讲目标

- 理解 firmware 如何在 QEMU KX6625 上启动
- 理解 vector table、reset handler、linker script 的职责
- 理解 FreeRTOS Cortex-M4F port 与 SysTick
- 理解双核 CPU0/CPU1 分工和 IPC demo

---

## Firmware 关键文件

```text
firmware/start.S
firmware/linker.ld
firmware/main.c
firmware/cpu1_main.c
firmware/FreeRTOSConfig.h
firmware/Makefile
```

构建输出：

```text
build/firmware.elf
build/firmware.bin
```

---

## Cortex-M 启动流程

Cortex-M reset 后硬件读取：

```text
0x00000000: initial MSP
0x00000004: reset handler PC
```

所以 vector table 必须位于 image 开头。

`start.S` 提供：

- vector table
- reset handler
- HardFault/default handler
- CPU0 C runtime init
- CPU1 stack switch and branch

---

## CPU0/CPU1 分流

reset handler 第一件事：

```text
read SYSCTRL.CPUID
if cpu_index == 1 -> cpu1_entry
else -> CPU0 init
```

CPU0：

- copy `.data`
- zero `.bss`
- call `main()`

CPU1：

- switch to `_cpu1_stack_top`
- call `cpu1_main()`

---

## FreeRTOS Port

使用官方 GCC Cortex-M4F port：

```text
freertos/FreeRTOS-Kernel/portable/GCC/ARM_CM4F/port.c
```

核心 exception：

```text
SVCall  -> vPortSVCHandler
PendSV  -> xPortPendSVHandler
SysTick -> xPortSysTickHandler
```

这些 handler 必须在 vector table 中正确连接。

---

## SysTick 与 Timer0 的区别

SysTick：

- Cortex-M core peripheral
- FreeRTOS scheduler tick
- exception index 15

Timer0：

- KX6625 外部 MMIO device
- NVIC external IRQ2
- 可被 firmware/demo 使用

不要把两者混淆。

---

## Firmware Demo Menu

firmware 通过 UART 提供菜单：

```text
1) UART IRQ demo
2) DMA M2M copy
3) DMA client
4) CRC-32
5) WDT reset
6) Dual-CPU IPC
7) SV APB timer
a) All tests
```

自动化 e2e 注入 `a\n` 跑完整流程。

---

## IRQ Handler 路径

以 SV timer 为例：

```text
SV RTL irq_o
-> sv_timer_bridge IRQ message
-> QEMU mmio-sockdev IRQ line
-> ARMv7-M NVIC IRQ5
-> vector table sv_timer_irq_handler
-> firmware clears IRQ
```

同样模式适用于 UART/DMA/WDT 等。

---

## 双核 IPC Demo

CPU0：

- 写 `IPC_ARG0`
- 写 `IPC_REQ`
- set `IPC_STATUS=PENDING`
- 等待 `DONE`

CPU1：

- polling IPC status
- 执行 XOR
- 写 response
- set `DONE`

目的：验证双核启动、共享 SRAM、基本同步。

---

## WDT Warm Boot Demo

WDT timeout 后：

- Python WDT model 设置 retention register
- 触发 QEMU system reset
- firmware 从 reset vector 重启
- WDT reset reason 保留
- app_task 识别 warm boot

验证点：

- reset path
- retention state
- firmware warm boot handling

---

## 本讲总结

- firmware 是平台验证闭环的中心
- startup/vector/linker/FreeRTOS port 是嵌入式基础
- demo menu 是 e2e 自动化入口
- 双核 IPC 和 WDT reset 让平台更接近真实 SoC bring-up
