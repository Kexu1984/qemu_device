# 07. 面向软件 CI/CD 与 Coverage 的平台演进

## 本讲目标

- 明确下一阶段平台建设方向
- 理解软件 CI/CD 与 RTL 验证平台的边界
- 梳理 firmware/driver coverage 的可行路径
- 设计一个最小可落地的 CI pipeline

---

## 为什么下一步聚焦软件 CI/CD

本平台最自然的工业落地点：

- 不依赖开发板
- 可自动化
- 可重复
- 运行速度远快于 RTL full simulation
- 可覆盖软件启动、驱动、RTOS、应用逻辑
- 可作为 SDK release gate

RTL signoff 走另一条路径，不在本原型平台上承接。

---

## 软件 CI/CD 平台目标

目标：

```text
每次软件提交后，自动构建 firmware，
在 QEMU 平台运行测试，收集日志、trace、coverage，
形成 pass/fail gate。
```

服务对象：

- BSP
- driver
- SDK
- RTOS integration
- application smoke test

---

## 最小 CI Pipeline

```text
checkout
-> install/cache dependencies
-> make gen
-> make sv
-> make fw
-> ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
-> collect artifacts
-> publish summary
```

Artifacts：

- `build/firmware.elf`
- `build/e2e_*.log`
- `build/device_trace.jsonl`
- `build/trace_report.html`
- coverage summary

---

## Coverage 的几个层次

Test coverage：

- 哪些 test case 跑过
- 哪些 driver API 被调用
- 哪些 feature 被覆盖

Code coverage：

- function coverage
- line coverage
- branch coverage

Scenario coverage：

- reset path
- error path
- timeout path
- IRQ storm
- DMA boundary

---

## Bare-metal/RTOS Coverage 难点

常规 gcov/lcov 在裸机上不一定直接可用：

- 没有文件系统
- 需要 coverage runtime
- 需要把 counter dump 出来
- freestanding build 环境限制较多

可选路径：

- firmware 自定义 counter
- driver API coverage table
- test result register/log
- QEMU PC trace / sampling
- gcov runtime 移植

---

## 建议第一阶段 Coverage

不要一开始追求完整 line coverage。

先做：

```text
test matrix coverage
+ driver API coverage
+ key branch/assert coverage
```

示例：

| Module | Case | Result |
|--------|------|--------|
| UART | RX IRQ | PASS |
| DMA | M2M 32B | PASS |
| CRC | direct vector | PASS |
| WDT | reset retention | PASS |
| SV Timer | IRQ clear | PASS |

---

## CI Gate 设计

基础 gate：

- build must pass
- e2e must pass
- no timeout
- no QEMU fatal error
- no missing expected test result

进阶 gate：

- minimum API coverage
- no new warning
- trace sanity check
- flaky test detection
- performance/runtime threshold

---

## 报告格式

建议输出：

```text
summary.json
junit.xml
trace_report.html
coverage.html
logs.zip
```

这样可以接入：

- GitHub Actions
- GitLab CI
- Jenkins
- 内部 dashboard

---

## 与 RTL 验证的边界

本平台软件 coverage 不是 RTL coverage。

它回答：

```text
软件是否执行了这些 driver/API/scenario？
软件是否在虚拟 SoC 上通过了预期功能？
```

不回答：

```text
RTL branch/condition/toggle coverage 是否达标？
CDC/timing 是否正确？
```

---

## 本讲总结

- 软件 CI/CD 是本平台最务实的下一阶段
- coverage 应从 test/API/scenario 开始，再逐步探索 code coverage
- CI artifacts 和报告体系比单次 demo 更重要
- RTL 验证应保持独立路径，避免 scope 失控
