# 06. 自动化 e2e、Trace 和软件回归测试

## 本讲目标

- 理解如何把 demo 变成 regression
- 理解 `scripts/e2e_test.sh` 的自动化流程
- 理解日志、trace、report 在定位问题中的作用
- 理解 smoke/nightly/long-run 测试分层

---

## Demo 与 Regression 的区别

Demo：

- 人手启动
- 人眼观察
- 偶尔运行
- 失败原因不稳定

Regression：

- 脚本启动
- 自动判断 PASS/FAIL
- 可重复运行
- 输出日志和 artifacts
- 可接入 CI

本项目的 e2e 是 regression 雏形。

---

## e2e_test.sh 流程

```text
1. 检查 QEMU/firmware/SV host shell 是否存在
2. 清理端口
3. 启动 Python device server
4. 启动 UART capture client
5. 启动 SV host shell
6. 启动 QEMU
7. 等待 firmware menu
8. 注入命令 a
9. 检查 expected strings
10. 输出 logs/trace/report
```

---

## 为什么通过 UART 注入命令

firmware menu 是软件可见入口。

自动注入：

```bash
printf 'a\n' | nc -q1 127.0.0.1 "$UART_TERM_PORT"
```

价值：

- 与 interactive 操作一致
- 不需要改 firmware test hook
- 可复用 UART RX/IRQ path
- 更接近真实用户/host 输入

---

## Expected Strings 的优缺点

优点：

- 简单直接
- 易于添加
- 适合 smoke test
- 对教学友好

缺点：

- 容易受日志文字影响
- 不能表达复杂断言
- 对覆盖率统计帮助有限

下一步可演进：

- structured result protocol
- JUnit XML
- JSON summary
- firmware-side test result register

---

## 日志体系

主要日志：

```text
build/e2e_server.log
build/e2e_qemu.log
build/e2e_uart.log
build/e2e_sv_host_shell.log
build/device_trace.jsonl
build/trace_report.html
```

定位建议：

- firmware 没输出：看 UART/server/QEMU
- QEMU 不启动：看 e2e_qemu.log
- Python model 异常：看 e2e_server.log
- SV IRQ 异常：看 e2e_sv_host_shell.log
- 事件顺序异常：看 trace_report.html

---

## Trace 的价值

Trace 不只是日志。

它应该帮助回答：

- 哪个设备在什么时候发生事件？
- DMA transfer deadline 是否正确？
- IRQ 是否在预期事件后触发？
- WDT reset 前后状态如何变化？
- 多设备之间的事件顺序是否合理？

---

## 测试分层

Smoke test：

- 每次提交跑
- 覆盖核心启动和关键路径
- 时间短

Nightly regression：

- 更多 case
- 更长 timeout
- 更多 negative/boundary test

Long-run test：

- 长时间稳定性
- 多次 reset
- stress DMA/IRQ/UART

---

## 从 e2e 到 CI

CI 最小流程：

```bash
make gen
make sv
make fw
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

Artifacts：

- firmware image
- all logs
- trace JSONL
- trace HTML
- summary report

---

## 本讲总结

- e2e 是平台工程化的关键
- 自动注入 UART 命令让 demo 可回归
- 日志和 trace 是定位问题的基础
- 下一步是 structured report、coverage 和 CI gate
