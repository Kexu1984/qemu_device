# Lab 08. 设计一个 AI 协作工程任务

## 目标

练习如何把一个复杂平台需求拆成 AI 可以协作完成的小闭环。

## 任务背景

假设要新增一个 APB GPIO device，要求：

- firmware 可以配置 direction
- firmware 可以 write output
- firmware 可以 read input/status
- device 可以产生 IRQ
- 未来可以有 Python model 和 SV RTL model 两种实现

## 实验 1：拆解任务

请将需求拆成 6-10 个小任务。

参考格式：

```text
1. 增加 spec/gpio.yaml
2. 生成 C/Python constants
3. 实现 Python GPIO model
4. 增加 QEMU command line device
5. 增加 firmware menu test
6. 增加 e2e expected strings
7. 更新 README/spec README
8. 后续增加 SV GPIO bridge
```

## 实验 2：写 AI Prompt

为其中一个任务写 prompt。要求包含：

- 目标
- 需要读取的文件
- 修改范围
- 验证命令
- 不要做的事情

示例：

```text
请在现有 spec-driven 设备体系下新增 GPIO 设备规格，
只修改 spec/devices.yaml 和新增 spec/gpio.yaml，
保持端口不冲突，寄存器包含 DATA/DIR/STATUS/IRQ_CLEAR。
修改后运行 make gen 验证。
不要改 firmware 或 QEMU runner。
```

## 实验 3：设计验收清单

为 AI 生成结果设计 review checklist：

- 是否读过现有设备模式？
- 是否端口/IRQ/base address 不冲突？
- 是否更新生成文件？
- 是否有 firmware test？
- 是否 e2e 通过？
- 是否文档说明能力边界？

## 实验 4：识别风险

列出 AI 可能犯的错误：

- 自创不兼容协议
- 忘记 write response `next_event_ns`
- 忘记 IRQ clear
- 忘记 runner 中挂 QEMU device
- 把 SV timing 能力说过头

## 思考题

1. 哪些任务适合交给 AI？哪些必须由人类判断？
2. 如何判断 AI 产出是否只是“看起来对”？
3. 为什么复杂项目要小步闭环？
4. AI-assisted engineering 对团队流程会产生什么影响？
