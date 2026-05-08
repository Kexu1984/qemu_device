# 03. mmio-sockdev 与 Python 外设模型

## 本讲目标

- 理解 `mmio-sockdev` 的设计目的
- 理解 QEMU 与外部 Python device model 的协议
- 理解 Python device server 的 transport/dispatch/model 分层
- 理解 spec-driven generation 的价值

---

## 为什么需要 mmio-sockdev

QEMU 内部写 device model 的成本较高：

- C/QOM/SysBus 代码复杂
- rebuild QEMU 成本高
- 调试外设逻辑不如 Python 灵活
- 快速试验寄存器行为不方便

`mmio-sockdev` 的思路：

```text
QEMU 只做通用 MMIO proxy
外设行为放到外部进程中实现
```

---

## mmio-sockdev 支持的通道

| 通道 | 方向 | 用途 |
|------|------|------|
| chardev | QEMU <-> model | MMIO read/write |
| irq-chardev | model -> QEMU | IRQ assert/deassert |
| tick-chardev | QEMU -> model | virtual-time tick |
| fabric-chardev | model -> QEMU | fabric bus-master access |
| rst-chardev | model -> QEMU | system reset request |

一个外设可以只用 R/W，也可以组合使用 IRQ/tick/mem/rst。

---

## R/W 协议

Read:

```text
'R' | master_id | offset[31:0] | size
-> data[size]
```

Write:

```text
'W' | master_id | offset[31:0] | size | data[size]
-> next_event_ns[63:0]
```

`master_id`：发起访问的 CPU index。

`next_event_ns`：用于 DES 调度下一次 device event。

---

## IRQ 协议

```text
'I' | irq_idx | level
```

示例：

```text
I 0 1 -> assert IRQ line 0
I 0 0 -> deassert IRQ line 0
```

QEMU 将 `mmio-sockdev` 的 IRQ output 接到 ARMv7-M NVIC input。

---

## Python Device Server 分层

核心文件：

```text
device_model/mmio_device_server.py
device_model/mmio_base.py
```

分层：

```text
RWServer / IRQServer / TickServer / MemServer / RstServer
    -> MMIOBus
        -> MMIODevice subclass
```

优点：

- transport 与 device behaviour 解耦
- 新设备只需要实现 read/write/on_tick
- 统一 IRQ、DMA、reset 工具类

---

## MMIODevice 抽象

每个外设实现：

```python
class MyDevice(MMIODevice):
    def read(self, offset, size, master_id=0) -> bytes:
        ...

    def write(self, offset, size, data, master_id=0) -> int:
        ...

    def on_tick(self, vtime_ns) -> int:
        ...
```

返回值：

- `0`: 无需调度下一事件
- `N > 0`: 请求 QEMU 在 `now + N ns` 发 tick

---

## 典型 Python 设备

UART：

- TXDATA 输出字符
- RX FIFO 接收 UART terminal 输入
- IRQ demo

DMA：

- bus-master memory read/write
- M2M/M2P/P2M
- latency + IRQ completion

WDT：

- virtual-time countdown
- pre-reset IRQ
- rst-chardev 触发 QEMU reset
- retention register

---

## spec-driven generation

设备配置源头：

```text
spec/devices.yaml
spec/*.yaml
spec/soc.yaml
```

生成：

```text
build/generated/mmio_devices.h
设备 C macro for firmware

device_model/generated/device_consts.py
Python constants

scripts/qemu-fork/hw/arm/kx6625_soc.h
QEMU SoC config
```

价值：避免地址、IRQ、端口、寄存器偏移手写不一致。

---

## Python Model 的工程价值

适合作为：

- 快速 functional device model
- 软件 bring-up 环境
- reference model
- checker/scoreboard 雏形
- trace/log collector
- fault injection 入口

不适合作为：

- RTL 精确时序替代品
- signoff model
- 高性能大规模仿真唯一方案

---

## 本讲总结

- `mmio-sockdev` 把 QEMU 与外设行为解耦
- Python device model 让外设功能快速可迭代
- spec-driven generation 是平台可维护性的基础
- Python 和 SV 后续可以形成 reference vs RTL 的相互验证关系
