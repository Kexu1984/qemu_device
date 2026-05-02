# Lab 04. 阅读 Firmware 启动与 Demo 菜单

## 目标

理解 firmware 如何启动、如何进入 FreeRTOS task、如何通过菜单驱动外设测试。

## 实验 1：查看 vector table

```bash
sed -n '1,120p' firmware/start.S
```

关注：

- initial MSP
- reset handler
- SVCall/PendSV/SysTick
- IRQ0-IRQ5 handler

## 实验 2：查看 reset handler

```bash
sed -n '120,220p' firmware/start.S
```

讨论：

- 为什么一开始就读 CPUID？
- CPU1 为什么要切换 stack？
- CPU0 为什么要初始化 `.data` 和 `.bss`？

## 实验 3：查看 FreeRTOS app task

```bash
grep -n "static void app_task" -A120 firmware/main.c
```

关注：

- UART enable
- NVIC init
- global IRQ enable
- CPU1 release
- WDT warm boot fast path
- menu loop

## 实验 4：运行 interactive

推荐使用 inline：

```bash
RUN_INLINE=1 ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

在菜单中输入：

```text
6
7
```

观察 Dual-CPU IPC 和 SV APB timer 输出。

## 思考题

1. FreeRTOS tick 使用的是哪个 exception？
2. 为什么 CPU1 不运行 FreeRTOS？
3. WDT reset 后为什么 Python retention register 还在？
4. 如果要新增 IRQ6，需要修改哪些文件？
