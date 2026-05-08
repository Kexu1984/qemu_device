# Lab 01. 运行并观察平台闭环

## 目标

通过一次完整运行，理解本平台的基本闭环：

```text
firmware -> QEMU -> mmio-sockdev -> Python/SV device -> IRQ/log/trace -> firmware
```

## 前置条件

在仓库根目录执行：

```bash
make gen
make sv
make fw
```

QEMU 如果尚未构建：

```bash
make qemu
```

## 实验 1：运行自动化 e2e

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

观察输出中的关键行：

```text
[PASS] End-to-end IRQ test PASSED
[PASS] Trace report: build/trace_report.html
```

## 实验 2：查看日志

查看 Python server 输出：

```bash
less build/e2e_server.log
```

建议搜索：

```text
KX6625 Test Menu
DMA started
SV timer fired
WDT demo complete
```

查看 QEMU 输出：

```bash
less build/e2e_qemu.log
```

建议观察：

```text
mmio-sockdev: IRQ[0] connected to ARMv7M/NVIC input 5
```

查看 SV host shell 输出：

```bash
less build/e2e_sv_host_shell.log
```

建议观察：

```text
SV-TIMER
IRQ assert
IRQ deassert
```

## 实验 3：查看 trace report

如果桌面环境可用：

```bash
xdg-open build/trace_report.html
```

或者直接在浏览器中打开该文件。

关注：

- DMA transfer timing
- IRQ events
- WDT reset sequence
- device event ordering

## 实验 4：从客户视角观察平台

把本次运行当成一个客户 app 调试会话，而不只是内部 firmware demo。

观察并记录：

- 客户能否通过 UART/log 判断 app 是否运行到预期路径？
- 客户能否在没有板子的情况下复现 driver/API 使用问题？
- trace report 是否能帮助供应商定位客户反馈？
- 当前平台还缺少哪些客户可用性能力？

可讨论的改进：

- 更稳定的 run script
- 更清晰的 binary image 加载方式
- 更友好的 trace/report 输出
- 客户 app smoke test 模板
- 常见问题复现包

## 讨论问题

1. 哪些输出来自 firmware？哪些来自 Python device server？哪些来自 QEMU？
2. e2e 测试为什么通过 UART 注入命令 `a`？
3. 为什么这个平台适合软件回归，而不是 RTL signoff？
4. 如果某个 IRQ 没有触发，应优先看哪些日志？
5. 如果把平台交付给客户作为 binary simulator，需要额外补齐哪些文档和工具？

## 预期结论

完成本实验后，学员应能说明：

- 平台中的主要进程：QEMU、Python device server、SV host shell
- firmware 如何通过 UART menu 驱动测试
- e2e 如何判断 PASS/FAIL
- trace report 在调试中的价值
- 平台如何支持客户在没有硬件时调试 application
