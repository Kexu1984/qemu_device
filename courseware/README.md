# QEMU-Based Firmware Validation Platform Courseware

本目录用于沉淀面向软件开发工程师和芯片验证工程师的内部教学课件。

课程目标不是把这个项目包装成完整的工业 signoff 平台，而是帮助团队理解一种务实的验证方法：用 QEMU 承担 CPU/SoC/firmware 行为级执行环境，用 Python 快速构建外设功能模型，用 SystemVerilog/Verilator 接入局部 RTL device，并在此基础上建设软件 CI/CD、回归测试和 coverage 平台。

## 面向对象

- 嵌入式软件、BSP、SDK、驱动和 RTOS 工程师
- 芯片验证、RTL 外设、SoC 集成和软硬件联调工程师
- 希望理解 AI-assisted engineering 如何落地到复杂工程原型的技术负责人

## 课程主线

本课程建议分为 8 讲，每讲 60-90 分钟。前 5 讲建立平台方法论和实现认知，第 6-7 讲面向软件 CI/CD 与验证实践，第 8 讲讨论 AI 驱动工程和团队落地。

| 讲次 | 主题 | 主要受众 | 核心问题 |
|------|------|----------|----------|
| 01 | 为什么需要 firmware-driven validation platform | 软件 + 验证 | 这个平台解决什么问题，不解决什么问题 |
| 02 | QEMU 作为 CPU/SoC 行为级模型 | 软件为主 | Cortex-M、NVIC、SysTick、MMIO、icount 的边界 |
| 03 | mmio-sockdev 与 Python 外设模型 | 软件 + 验证 | 如何快速搭建 UART/DMA/Timer/WDT 等功能模型 |
| 04 | FreeRTOS、双核启动和 firmware demo 闭环 | 软件为主 | startup、vector table、linker、FreeRTOS port、CPU1 IPC |
| 05 | SystemVerilog RTL device 接入路径 | 验证为主 | Verilator bridge、APB transaction、IRQ、独立 clock domain |
| 06 | 自动化 e2e、trace 和软件回归测试 | 软件 + 验证 | 如何把 demo 变成可重复的 regression |
| 07 | 面向软件 CI/CD 与 coverage 的平台演进 | 软件 + 管理 | 如何建设 driver/API/application coverage 和质量门禁 |
| 08 | AI 驱动复杂工程原型的方法论 | 技术负责人 | 如何让 AI 参与架构探索、编码、调试、文档和复盘 |

## 建议课件结构

每一讲建议包含以下材料：

- `slides.md`: 可转换为 PPT/Marp 的主课件
- `lab.md`: 上机实验步骤
- `notes.md`: 讲师备注、常见问题和讨论点
- `assets/`: 截图、图示、trace 报告片段、波形示例

后续可以按如下结构展开：

```text
courseware/
├── README.md
├── 01-platform-motivation/
│   ├── slides.md
│   ├── lab.md
│   └── notes.md
├── 02-qemu-cpu-model/
├── 03-mmio-sockdev-python-devices/
├── 04-freertos-dual-core-firmware/
├── 05-systemverilog-device-bridge/
├── 06-e2e-trace-regression/
├── 07-software-cicd-coverage/
└── 08-ai-assisted-engineering/
```

## 课程定位

### 平台能力边界

这个平台适合讲清楚并实践以下内容：

- 早期软件 bring-up 和 driver 原型开发
- firmware-driven 外设功能验证
- Python reference model 和 RTL device 的对照思路
- QEMU virtual time、device-local clock 与 wall-clock 的区别
- 软件 CI/CD、自动回归、日志和 trace 报告
- AI-assisted engineering 在复杂系统原型中的用法

这个平台不应被描述为：

- RTL signoff 平台
- CDC/signoff/timing closure 工具
- full-chip cycle-accurate simulator
- UVM coverage closure 的替代品

### 教学重点

课程中需要反复强调三个边界：

1. QEMU 是 CPU/firmware 行为级执行环境，不是全芯片 cycle-accurate 仿真器。
2. Python device 是快速功能模型和参考模型，适合软件开发和早期验证。
3. SystemVerilog device 保持独立本地 clock，通过 MMIO/IRQ 等事务边界接入 QEMU。

## 各讲主题概要

### 01. 为什么需要 firmware-driven validation platform

目标：建立问题意识和平台定位。

内容：

- 软件团队、RTL 团队、验证团队在传统流程中的断点
- 为什么板子/FPGA/RTL 仿真都不足以覆盖早期软件开发需求
- firmware-driven validation 的价值和局限
- 本项目的两大用途：软件原型开发、RTL device 功能验证
- 与 UVM、FPGA prototyping、emulation、post-silicon validation 的边界

实验建议：

- 浏览 README 的系统架构图
- 运行一次 `ICOUNT_SHIFT=5 bash scripts/e2e_test.sh`
- 查看 `build/trace_report.html`

### 02. QEMU 作为 CPU/SoC 行为级模型

目标：理解 QEMU 在平台中的角色。

内容：

- KX6625 machine、dual Cortex-M4、FLASH/SRAM/NVIC
- Cortex-M SysTick 与外部 timer0 的区别
- `icount`、QEMU virtual time 与 wall-clock 的区别
- MMIO R/W 在 QEMU 中的同步行为
- 为什么不把 QEMU 用作跨 clock domain cycle-accurate 模型

实验建议：

- 查看 `scripts/qemu-fork/hw/arm/kx6625.c`
- 对比 `ICOUNT_SHIFT=5` 与不使用 icount 的运行行为

### 03. mmio-sockdev 与 Python 外设模型

目标：理解可扩展外设模型框架。

内容：

- `mmio-sockdev` R/W、IRQ、tick、mem、rst channel
- `device_model/mmio_device_server.py` 的 transport + dispatch 分层
- `MMIODevice`、`IRQController`、`MemChannel`、`RstController`
- UART、DMA、CRC、WDT 模型的设计方式
- `spec/devices.yaml` 到 C/Python 常量的生成链路

实验建议：

- 增加一个只读 ID register 的 Python device mock
- 修改 spec 后运行 `make gen`，观察生成文件变化

### 04. FreeRTOS、双核启动和 firmware demo 闭环

目标：理解真实 firmware 如何驱动平台。

内容：

- `start.S` vector table、reset handler、CPU0/CPU1 分流
- linker script 与 C runtime 初始化
- FreeRTOS CM4F port、SysTick、SVC、PendSV
- UART menu、DMA、CRC、WDT、dual-core IPC demo
- firmware 输出如何成为 e2e 判断依据

实验建议：

- 增加一个 firmware menu command
- 观察 IRQ handler 和 NVIC enable 的对应关系

### 05. SystemVerilog RTL device 接入路径

目标：理解 QEMU 与 RTL device 的事务边界。

内容：

- `sv_device/sv_timer_apb.sv` 的 APB register timer
- `sv_timer_bridge.cpp` 如何把 socket MMIO 转成 APB cycle
- Verilator build flow
- IRQ5 从 RTL `irq_o` 到 firmware ISR 的路径
- SV 独立 pclk 与 QEMU CPU clock 不做 cycle 对齐的原因

实验建议：

- 修改 SV timer LOAD 值和 firmware test
- 在 bridge log 中观察 IRQ assert/deassert

### 06. 自动化 e2e、trace 和软件回归测试

目标：把 demo 变成 regression。

内容：

- `scripts/e2e_test.sh` 的流程：启动 server、SV bridge、QEMU、UART capture、注入命令、检查日志
- expected strings 的优点和局限
- JSONL trace 与 HTML report
- 如何定位失败：QEMU log、server log、SV log、UART log
- smoke test、nightly test、long-run test 的分层

实验建议：

- 故意改错一个 expected string，观察失败报告
- 增加 SV timer 的 UART expected check

### 07. 面向软件 CI/CD 与 coverage 的平台演进

目标：规划下一阶段工程化方向。

内容：

- CI pipeline：`make gen`、`make sv`、`make fw`、`e2e_test.sh`
- artifacts：logs、trace report、firmware image、coverage report
- 软件 coverage 的可选路径：test matrix、API coverage、branch/assert counter、PC trace、gcov/lcov 可行性分析
- driver/API/application coverage 与 RTL coverage 的区别
- release quality gate 与 regression dashboard

实验建议：

- 设计一个 `ci/run_all.sh` 草案
- 将 e2e 输出整理成 JUnit-like summary 的设想

### 08. AI 驱动复杂工程原型的方法论

目标：复盘 AI-assisted engineering 如何带来生产率提升。

内容：

- 人类负责的问题定义、边界判断、架构 review 和验收
- AI 适合承担的代码生成、搜索、脚本修改、文档初稿、错误定位
- 如何把大任务拆成可验证的小闭环
- 如何避免 AI 带来的过度自信和模型边界误判
- 5 天原型 vs 传统人力 2 个月以上的生产率复盘

实验建议：

- 给定一个新外设需求，设计 AI 协作任务拆分
- 编写一份 review checklist，约束 AI 生成代码的验收标准

## 后续落地建议

第一阶段先完成 01-03 讲的 slides/lab，让团队理解平台定位和基本使用；第二阶段完成 04-06 讲，让软件和验证工程师能读懂实现并添加测试；第三阶段完成 07-08 讲，进入 CI/CD、coverage 和 AI-assisted engineering 方法论。
