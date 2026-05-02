# 02. QEMU 作为 CPU/SoC 行为级模型

## 本讲目标

- 理解 QEMU 在平台中的角色
- 理解 KX6625 machine 的基本组成
- 区分 CPU 行为级模型、virtual time、wall-clock 和 cycle accuracy
- 理解 MMIO 在 QEMU 中的同步访问语义

---

## QEMU 在本平台中的职责

QEMU 负责：

- 模拟 Cortex-M CPU 执行 firmware
- 提供 SoC memory map
- 提供 FLASH/SRAM/NVIC/SysTick 等基础环境
- 加载 firmware ELF/bin
- 将 MMIO 访问转发给 `mmio-sockdev`
- 接收外部 device model 的 IRQ/reset 请求

QEMU 不负责：

- RTL 内部状态机逐拍验证
- 外设 APB/AHB 精确 wait-state
- 跨 clock domain cycle 对齐

---

## KX6625 Machine 结构

核心文件：

```text
scripts/qemu-fork/hw/arm/kx6625.c
scripts/qemu-fork/hw/arm/kx6625_soc.h
```

主要组成：

- dual Cortex-M4
- FLASH at `0x00000000`
- SRAM at `0x20000000`
- peripheral stub region
- SYSCTRL native MMIO
- dynamic sysbus device support for `mmio-sockdev`

---

## Dual Cortex-M4 模型

CPU0：

- primary core
- reset 后执行 vector table
- 初始化 C runtime
- 启动 FreeRTOS

CPU1：

- starts powered off
- CPU0 通过 SYSCTRL 释放
- 重新 reset 后读取正确 vector table
- 进入 `cpu1_main()` 执行 bare-metal IPC loop

---

## Cortex-M 基础组件

QEMU ARMv7-M container 提供：

- Cortex-M core
- NVIC
- SysTick
- exception entry/return
- vector table fetch

注意：

```text
SysTick 是 Cortex-M architecture core peripheral，
不是 KX6625 外部 timer0。
```

---

## MMIO 在 QEMU 中的语义

对于普通 QEMU MMIO callback：

```text
firmware load/store
-> QEMU memory region callback
-> callback 返回数据或完成写入
-> guest 继续执行
```

在 `mmio-sockdev` 中：

```text
callback 内部通过 TCP 请求外部 device model
QEMU vCPU host thread 阻塞等待返回
返回后 guest 继续执行
```

关键点：

- host 阻塞时间不等于 guest cycle 时间
- SV/APB 消耗多少 pclk 不会自动推进 QEMU CPU cycle

---

## QEMU Virtual Time 与 icount

推荐运行方式：

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

含义：

```text
QEMU_CLOCK_VIRTUAL = executed_instruction_count * 32 ns
```

优点：

- 确定性更好
- WFI 可以跳到 timer deadline
- Python timed devices 可以基于 virtual time 运行

限制：

- 不是真实 CPU cycle accurate 模型
- 不自动表达外部 SV pclk 与 CPU clock 的关系

---

## WFI 与虚拟时间

firmware 中常见模式：

```c
while (!irq_done) {
    __asm__ volatile ("wfi");
}
```

在 icount 下：

- CPU halt
- QEMU 可推进 virtual time 到下一个 timer deadline
- IRQ 到来后 CPU wakeup

这让 WDT、DMA、timer 等事件可以快速且确定地完成。

---

## CPU 行为级模型的价值

对软件开发足够有用：

- 启动流程
- vector table
- IRQ handler
- RTOS scheduler
- MMIO driver
- DMA buffer 操作
- reset flow

但要避免误用：

- 不用它评估精确性能
- 不用它做总线时序 signoff
- 不把 host execution time 当芯片时间

---

## 本讲总结

- QEMU 是 CPU/SoC/firmware 行为级执行环境
- `icount` 提供确定性 virtual time，但不是跨域 cycle accuracy
- MMIO callback 是同步事务边界
- 外设行为可以通过 Python/SV 补充，但 CPU 侧 timing 不能自动反算
