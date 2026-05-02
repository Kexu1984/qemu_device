# Notes 02. 讲师备注

## 讲授重点

本讲重点是让学员不要把 QEMU 误解成 RTL simulator。

必须强调：

- QEMU 的强项是执行真实 firmware
- `icount` 是 virtual-time deterministic execution，不是 CPU 精确时序模型
- 普通 MMIO callback 是同步完成
- host 阻塞时间不会自动变成 guest cycle 时间

## 推荐板书

```text
firmware STR/LDR
  -> QEMU MemoryRegionOps
  -> mmio_sockdev_read/write
  -> TCP external model
  -> response
  -> guest continues
```

然后标注：

```text
host wait != guest virtual cycle elapsed
```

## 容易被问到的问题

### Q: 如果外设很慢，QEMU 怎么体现 wait-state？

当前平台不体现 CPU bus wait-state。慢外设建议通过 STATUS polling、IRQ completion、DMA completion 等软件可见协议表达。

### Q: `icount` 是否能让 QEMU 与 SV pclk 对齐？

不能自动对齐。SV pclk 是 SV bridge 的本地模型。两者通过 transaction/IRQ 边界交互。

### Q: 为什么还要用 icount？

对 Python timed devices 很有价值：WDT、DMA deadline、timer tick 可以基于 QEMU virtual time 确定运行。

## 建议延伸

可以简单介绍 QEMU 中两类时间：

- wall-clock/realtime
- virtual clock

但不建议展开 QEMU 内部 timer 框架太深，否则会偏离课程主线。
