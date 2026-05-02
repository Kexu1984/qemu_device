# Notes 06. 讲师备注

## 讲授重点

本讲从“能跑”转向“可回归”。重点不是脚本技巧，而是测试工程思维：

- 自动启动
- 自动输入
- 自动判断
- 自动收集 artifacts
- 可重复定位

## 推荐演示

现场运行一次 e2e，然后打开：

- `build/e2e_server.log`
- `build/e2e_qemu.log`
- `build/e2e_sv_timer.log`
- `build/trace_report.html`

让学员看到同一事件在不同日志中的位置。

## 讨论点

### 为什么不是只看 QEMU log？

因为 firmware UART 输出通过 Python server/UartChannel 承载，QEMU log 主要是 QEMU 自己的 device connection 和错误。

### 为什么 trace report 重要？

文本日志适合看局部，trace 适合看事件顺序和时间关系。

### expected strings 的下一步

后续 CI 平台建议增加 structured result：

```text
TESTCASE name=DMA_M2M status=PASS
TESTCASE name=SV_TIMER status=PASS
```

或让 firmware 写 test result register，由 host 读取。

## 课后任务

设计一个测试分层表：

- 每次提交必须跑什么
- nightly 跑什么
- release 前跑什么
