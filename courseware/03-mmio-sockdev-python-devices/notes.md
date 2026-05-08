# Notes 03. 讲师备注

## 讲授重点

本讲重点讲“分层”和“解耦”：

```text
QEMU generic proxy
-> TCP protocol
-> Python transport
-> MMIOBus dispatch
-> device model
```

不要把所有代码逐行讲完，重点讲每层职责。

## 建议演示

可以打开两个文件并排讲：

- `scripts/qemu-fork/hw/misc/mmio_sockdev.c`
- `device_model/mmio_device_server.py`

用一条 write 流程串起来。

## 关键概念

### next_event_ns

这是平台中非常重要的 DES 钩子。它允许 device 在一次 MMIO write 后告诉 QEMU：下一次事件在多少 ns 后发生。

适用场景：

- DMA transfer complete
- timer expiry
- delayed IRQ

### FabricChannel

DMA 不是 Python 直接访问 host memory，而是通过 QEMU fabric-chardev 请求 platform address read/write。

这能更接近真实 bus-master device 的软件可见行为。

## 常见误区

- 以为 Python model 越真实越好：其实 Python model 重点是快、可观测、可对照。
- 以为所有 device 都需要 tick：很多纯寄存器设备不需要。
- 以为端口号可以随便写：端口、IRQ、地址应该由 spec 统一管理。

## 课后任务

让学员画出 UART TXDATA write 的完整路径：

```text
firmware send_char
-> QEMU mmio-sockdev
-> RWServer
-> ConsoleUartDevice.write
-> stdout/UartChannel
```
