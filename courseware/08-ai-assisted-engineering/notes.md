# Notes 08. 讲师备注

## 讲授重点

本讲不是宣传 AI，而是复盘工程方法。

核心观点：

```text
AI 缩短探索路径，人类控制工程边界。
```

## 推荐讲法

用本项目真实演进讲：

1. 从 QEMU virtual time 问题开始
2. 到 FreeRTOS 双核 firmware
3. 到 interactive/e2e 稳定性
4. 到 SV timer prototype
5. 到 README 明确 scope
6. 到 courseware 沉淀

让学员看到 AI 并不是一次生成最终系统，而是持续小步推进。

## 必须强调的边界

AI 容易把 demo 讲得过满。讲师要明确：

- 这个平台不是 RTL signoff
- 不是 cycle-accurate full-chip simulator
- 不是 UVM replacement
- 是 firmware-driven functional validation platform

这个边界判断来自人类架构审查。

## 课堂互动

让每组选择一个外设，例如 GPIO/SPI/I2C/ADC，写一个 AI 协作任务拆解。

要求：

- 至少 6 个小任务
- 每个任务有验证方式
- 明确 non-goals
- 写一段适合 AI 的 prompt

## 结尾建议

把 AI 定位成工程放大器：

- 能帮助 senior engineer 快速探索
- 能帮助团队沉淀文档
- 能帮助新人理解系统
- 不能替代工程责任

这比单纯讨论“AI 能不能写代码”更有建设性。
