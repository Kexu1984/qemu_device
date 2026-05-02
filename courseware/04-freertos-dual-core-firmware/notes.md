# Notes 04. 讲师备注

## 讲授重点

本讲是软件工程师最容易产生共鸣的一讲。重点强调：

- 这不是孤立外设 demo，而是真实 firmware 驱动平台
- Cortex-M startup 和 FreeRTOS port 是关键基础
- e2e 自动测试最终依赖 firmware 输出

## 推荐讲法

按照启动时间线讲：

```text
QEMU load firmware
-> Cortex-M reset vector
-> start.S
-> main()
-> xTaskCreate(app_task)
-> vTaskStartScheduler
-> app_task
-> menu/e2e
```

然后再讲 CPU1 release 和 IPC。

## 容易被问到的问题

### Q: 为什么 CPU1 不跑 FreeRTOS？

当前平台是 asymmetric model。CPU0 跑 FreeRTOS，CPU1 跑 bare-metal IPC loop。这样更简单，也足够验证双核启动和共享内存。

### Q: 为什么 vector table 要直接放 FreeRTOS handler？

Cortex-M exception 入口由硬件根据 vector table 直接跳转。FreeRTOS port 依赖 SVC、PendSV、SysTick handler。

### Q: 为什么 WDT reset 后 retention register 没丢？

因为 QEMU reset 不会重启 Python server。WDT model instance 仍在，只有 volatile state 被 on_reset 清除。

## 实验提示

Interactive 模式建议使用：

```bash
RUN_INLINE=1 ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

避免 xterm 在远程/VS Code 环境里不明显。
