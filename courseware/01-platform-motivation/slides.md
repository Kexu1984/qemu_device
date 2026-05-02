# 01. 为什么需要 Firmware-Driven Validation Platform

## 本讲目标

- 理解软件开发、芯片验证、RTL 开发之间的协作断点
- 明确本平台要解决的问题和不解决的问题
- 理解平台对客户 app 开发和交付支持的价值
- 建立 firmware-driven validation 的基本方法论
- 理解为什么 QEMU、Python model、SystemVerilog RTL 可以组合成一个务实平台

---

## 传统流程中的典型断点

软件团队常见问题：

- 等 RTL 仿真环境、FPGA、样片或开发板
- 驱动开发依赖硬件进度
- IRQ、DMA、reset、clock 等问题暴露较晚
- 软件回归测试难以自动化

验证团队常见问题：

- UVM testbench 与真实 firmware 使用方式脱节
- 寄存器行为和软件驱动期望不一致
- 外设功能 OK，但软件集成后仍有大量 bring-up 问题
- 很难快速回答“这个 RTL 用真实驱动跑起来怎样”

---

## Firmware-Driven Validation 是什么

Firmware-driven validation 指的是：

- 用真实或接近真实的 firmware 驱动 SoC/外设模型
- 通过 MMIO、IRQ、DMA、reset 等真实软件可见接口进行验证
- 关注软件可观察行为，而不是每一个门级或总线周期

核心问题：

```text
真实软件如何看见这个设备？
真实驱动如何配置、等待、处理中断、检查结果？
```

---

## 本项目的定位

本项目是一个芯片功能验证和软件原型开发平台原型：

```text
QEMU CPU/SoC behavioural model
+ Python fast device models
+ SystemVerilog/Verilator RTL device bridge
+ FreeRTOS firmware
+ automated e2e regression
+ trace/report
```

它强调：

- 快速搭建软件可运行环境
- 快速验证外设软件可见行为
- 快速形成自动化回归
- 清楚区分功能验证和时序 signoff

---

## 两个主要用途

用途 1：软件原型开发

- BSP/SDK/driver early bring-up
- FreeRTOS 集成验证
- 应用软件开发和调试
- CI 中的 smoke/regression test

用途 2：RTL device 功能验证

- 将局部 RTL 外设接入 QEMU firmware 环境
- 用真实驱动访问 RTL register
- 验证 IRQ、状态机、寄存器行为
- 与 Python reference model 对照

---

## 对客户的价值

虚拟平台不只服务芯片公司内部研发，也可以作为客户软件开发工具交付。

客户可以在没有开发板或样片时：

- 运行 BSP/SDK binary image
- 调试自己的 application
- 验证 RTOS task、driver API、middleware 集成
- 复现客户现场问题
- 在 CI 中跑客户 application smoke test

这时平台可以被定位为：

```text
Binary-compatible software simulator for KX6625 firmware/application bring-up
```

---

## 客户交付场景

典型交付方式：

- QEMU binary + machine/device package
- BSP/SDK firmware image
- Python/SV device model package
- run script and documentation
- sample app and regression script

客户使用路径：

```text
customer app
-> link with BSP/SDK
-> run on simulator
-> debug UART/log/trace
-> reproduce and report issue
```

这种方式可以降低客户等待硬件的成本，也能让供应商更早收集软件兼容性问题。

---

## 不适合承担的任务

本平台不应该被包装成：

- RTL signoff 平台
- CDC signoff 工具
- STA/timing closure 工具
- full-chip cycle-accurate simulator
- UVM coverage closure 替代品
- emulation/FPGA prototyping 替代品

更准确的说法：

```text
Firmware-driven functional validation platform
```

---

## 为什么选择 QEMU

QEMU 的价值：

- 已有成熟 CPU 执行引擎
- 可运行真实 firmware/RTOS
- 支持自定义 machine 和 device
- 可自动化、可脚本化、适合 CI
- 比 RTL 全系统仿真快很多

QEMU 的边界：

- CPU 行为级，不是 cycle-accurate CPU
- 普通 MMIO callback 是同步完成
- 不自动建模外设 APB wait-state 对 CPU cycle 的影响

---

## 为什么需要 Python Device Model

Python 的价值：

- 快速实现外设功能模型
- 快速修改寄存器行为
- 适合作为 reference model
- 适合做日志、trace、checker
- 开发成本低，适合早期探索

典型设备：

- UART
- DMA
- Timer
- CRC
- WDT

---

## 为什么接入 SystemVerilog

SV/RTL 的价值：

- 真实 RTL 状态机
- 本地 clock 行为
- 接近最终设计实现
- 可与 firmware driver 直接联调

但需要明确：

```text
SV device 有独立本地 clock。
QEMU 通过 MMIO/IRQ 事务边界观察它。
不声称 QEMU 48 MHz 与 SV pclk cycle 精确对齐。
```

---

## 平台能力边界

| 域 | 角色 | 时间模型 |
|----|------|----------|
| QEMU | CPU/SoC/firmware 行为级模型 | QEMU virtual time / icount |
| Python device | 快速功能模型和参考模型 | 可使用 QEMU virtual-time tick |
| SV device | RTL device 本地行为 | 独立本地 clock，由 bridge 维护 |

边界事件：

- MMIO read/write
- IRQ assert/deassert
- DMA request/complete
- reset

---

## 本项目当前闭环

当前已经跑通：

- dual Cortex-M4 KX6625 machine
- FreeRTOS CPU0 + bare-metal CPU1 IPC
- UART/DMA/CRC/WDT Python models
- SV APB timer prototype
- e2e 自动化测试
- trace report

验证链路：

```text
firmware -> QEMU MMIO -> external device model -> IRQ -> firmware
```

---

## 课程后续安排

后续 7 讲将分别展开：

- QEMU CPU/SoC 行为级模型
- mmio-sockdev 与 Python 外设
- FreeRTOS 和双核 firmware
- SV RTL device bridge
- e2e regression 和 trace
- 软件 CI/CD 与 coverage
- AI-assisted engineering 方法论

---

## 本讲总结

- 本平台解决的是早期软件开发和 firmware-driven 功能验证问题
- QEMU、Python、SV 的组合有实际工程意义，但必须明确能力边界
- 该平台适合作为中小团队的软件 CI/CD 和外设功能验证基础设施原型
- 后续重点应从 demo 走向 regression、coverage 和团队方法论
