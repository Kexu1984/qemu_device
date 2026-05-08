# 05. SystemVerilog RTL Device 接入路径

## 本讲目标

- 理解为什么要把 SV RTL device 接入 QEMU firmware 环境
- 理解 SV host shell 的基本结构
- 理解 APB transaction 与 MMIO transaction 的关系
- 明确 SV 独立 clock domain 与 QEMU 行为级模型的边界

---

## 为什么接入 SV RTL

Python model 很快，但它不是 RTL。

SV RTL 接入的价值：

- 用真实 driver 访问真实 register RTL
- 验证 RTL 状态机的软件可见行为
- 验证 IRQ assert/clear path
- 在 FPGA/样片之前做早期 firmware-driven 验证
- 与 Python reference model 形成对照

---

## 当前 SV Timer 原型

文件：

```text
sv_device/sv_timer_apb.sv
sv_device/sv_host_shell.cpp
sv_device/Makefile
spec/sv_timer.yaml
```

地址与端口：

```text
MMIO base: 0x4000B000
IRQ:       5
RW port:   7906
IRQ port:  7907
```

---

## SV Timer Register

| Offset | Name | Access | Description |
|--------|------|--------|-------------|
| 0x00 | CTRL | R/W | bit0=ENABLE, bit1=IRQ_EN |
| 0x04 | LOAD | R/W | countdown load cycles |
| 0x08 | VALUE | R | current countdown |
| 0x0C | STATUS | R | bit0=IRQ_PENDING |
| 0x10 | IRQ_CLEAR | W | write bit0=1 clear IRQ |

---

## QEMU 到 SV 的访问路径

```text
firmware mmio_write32(SV_TIMER_CTRL_REG, ...)
-> QEMU mmio-sockdev write callback
-> TCP port 7906
-> sv_host_shell.cpp
-> APB setup/access cycles
-> sv_timer_apb.sv state update
```

IRQ 返回：

```text
sv_timer_apb.irq_o
-> bridge sends 'I' message to port 7907
-> QEMU NVIC IRQ5
-> firmware sv_timer_irq_handler
```

---

## APB Transaction

APB 两阶段：

```text
setup:  PSEL=1, PENABLE=0
access: PSEL=1, PENABLE=1
```

bridge 负责：

- 设置 PADDR/PWRITE/PWDATA
- 推进 RTL clock
- 读取 PRDATA
- 等待 PREADY

当前 timer 中 `PREADY=1`，但接口形式保留了 APB 语义。

---

## 独立 Clock Domain

需要明确：

```text
QEMU CPU clock: behavioural / virtual time
SV pclk: bridge-maintained local RTL clock
```

不做的事情：

- 不强制 QEMU 48 MHz 与 SV 16 MHz cycle 对齐
- 不把 SV pclk cycles 自动反算成 QEMU CPU cycles
- 不把 MMIO host blocking time 当芯片时间

---

## 当前原型的 Timing 语义

当前原型验证的是：

- QEMU 能访问 SV register
- bridge 能驱动 APB transaction
- SV RTL 能产生 IRQ
- firmware 能处理并清除 IRQ

不验证：

- CPU bus wait-state
- clock-domain crossing 细节
- full-chip timing
- RTL coverage closure

---

## 为什么这仍然有价值

因为很多问题是软件可见的功能问题：

- register bit 是否正确
- start/clear/status 语义是否正确
- IRQ 是否按预期触发
- firmware handler 是否能清中断
- driver sequence 是否符合 RTL 设计

这些问题越早发现越便宜。

---

## 下一步可扩展方向

- 通用 APB bridge wrapper
- `--pclk-hz` 和 SV cycle counter
- waveform dump 开关
- transaction timeout
- Python reference model compare
- 更复杂 SV peripheral：UART/SPI/I2C/DMA client/crypto

---

## 本讲总结

- SV host shell 证明了 QEMU firmware 到 RTL device 的路径可行
- MMIO 是同步 transaction boundary
- SV device 保持本地 clock，不与 QEMU CPU 做 cycle 对齐
- 该路径适合 RTL device 功能验证，不适合作为 RTL timing signoff
