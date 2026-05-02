# Lab 05. 构建并观察 SV APB Timer Bridge

## 目标

理解 SystemVerilog timer 如何通过 Verilator bridge 接入 QEMU。

## 实验 1：构建 SV bridge

```bash
make sv
```

确认输出：

```bash
test -x sv_device/build/sv_timer_bridge && echo OK
```

## 实验 2：查看 SV RTL

```bash
sed -n '1,140p' sv_device/sv_timer_apb.sv
```

关注：

- register offsets
- `ctrl_q/load_q/value_q/status_q`
- countdown logic
- `irq_o`
- `IRQ_CLEAR`

## 实验 3：查看 bridge

```bash
sed -n '1,220p' sv_device/sv_timer_bridge.cpp
```

关注：

- socket listen/accept
- `SvTimerBridge`
- `apb_read`
- `apb_write`
- `run_cycles`
- `send_irq`

## 实验 4：运行单项 firmware 测试

```bash
RUN_INLINE=1 ICOUNT_SHIFT=5 bash scripts/run_interactive.sh
```

在菜单输入：

```text
7
```

观察输出：

```text
[SVTIMER] Starting SystemVerilog APB timer test.
[IRQ] SV timer fired! INTID=5
[SVTIMER] IRQ observed and cleared PASSED!
```

## 实验 5：查看 bridge log

```bash
less build/interactive_sv_timer.log
```

关注：

```text
RW channel connected
IRQ channel connected
IRQ assert
IRQ deassert
```

## 思考题

1. 为什么 SV bridge 需要同时监听 R/W 和 IRQ 两个端口？
2. APB transaction 和 QEMU MMIO transaction 是什么关系？
3. 为什么不把 SV pclk cycles 自动反算到 QEMU CPU cycles？
4. 如果 RTL 卡住不返回 PREADY，bridge 应该如何处理？
