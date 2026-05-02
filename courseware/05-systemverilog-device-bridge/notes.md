# Notes 05. 讲师备注

## 讲授重点

本讲容易引发对 timing 的讨论。要明确平台定位：

```text
SV RTL has local pclk.
QEMU sees synchronous MMIO transaction completion.
No cross-domain cycle-accurate alignment is claimed.
```

## 推荐讲法

先讲为什么需要 SV：Python model 很快，但不能替代 RTL 状态机。

然后讲路径：

```text
firmware -> QEMU -> socket -> C++ bridge -> Verilated RTL -> IRQ -> firmware
```

最后讲边界：这个路径验证功能，不验证全芯片 timing。

## 关键讨论点

### MMIO blocking

QEMU 发 MMIO 时会阻塞等待 bridge 返回。这是 host 线程阻塞，不等于 guest CPU 自动消耗对应 cycle。

### 16 MHz vs 48 MHz

如果 SV 被定义为 16 MHz，QEMU CPU 被定义为 48 MHz，当前平台不维护严格 3:1 cycle 关系。SV pclk 是本地仿真概念。

### 后续可改进

- 显式 `--pclk-hz`
- SV cycle counter
- waveform dump
- transaction timeout
- APB bus functional model 抽象

## 课堂提醒

不要把本讲讲成 Verilator 教程。Verilator 是工具，核心是 co-sim boundary 和 firmware-driven RTL device validation。
