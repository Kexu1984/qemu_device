# Lab 02. 观察 QEMU Machine 与 Virtual Time

## 目标

- 找到 KX6625 machine 的关键代码
- 理解 firmware 如何被加载
- 对比 icount 与非 icount 的运行方式

## 实验 1：查看 KX6625 machine

```bash
sed -n '1,260p' scripts/qemu-fork/hw/arm/kx6625.c
```

重点观察：

- `ARMv7MState armv7m`
- `ARMv7MState armv7m1`
- `memory_region_init_rom`
- `memory_region_init_ram`
- `SYSCTRL_OFF_CPU1RST`
- `armv7m_load_kernel`
- `machine_class_allow_dynamic_sysbus_dev`

## 实验 2：查看生成的 SoC 配置

```bash
sed -n '1,180p' scripts/qemu-fork/hw/arm/kx6625_soc.h
```

关注：

- CPU type
- IRQ 数量
- clock frequency
- FLASH/SRAM region
- IRQ table

## 实验 3：对比 icount 与非 icount

运行自动化测试：

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

再运行：

```bash
bash scripts/e2e_test.sh
```

讨论：

- 两次是否都能通过？
- 运行时间是否稳定？
- WDT、DMA、timer 事件在日志中如何表现？

## 实验 4：观察 QEMU log

```bash
less build/e2e_qemu.log
```

搜索：

```text
mmio-sockdev
SYSCTRL
CPU1 released
```

## 思考题

1. 为什么 CPU1 需要在 firmware load 后重新 reset？
2. `current_cpu->cpu_index` 为什么可以用于 SYSCTRL CPUID？
3. 如果 MMIO socket 往返耗时 100 us，guest 是否认为经过了 100 us？为什么？
4. `icount` 解决了什么问题？没有解决什么问题？
