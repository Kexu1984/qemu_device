# Lab 03. 阅读 mmio-sockdev 与 Python Device Server

## 目标

理解一次 firmware MMIO 访问如何进入 Python device model。

## 实验 1：查看 QEMU 侧 mmio-sockdev

```bash
sed -n '130,260p' scripts/qemu-fork/hw/misc/mmio_sockdev.c
```

关注：

- `mmio_sockdev_read`
- `mmio_sockdev_write`
- request packet 格式
- write 后读取 `next_event_ns`

继续查看 IRQ：

```bash
sed -n '460,510p' scripts/qemu-fork/hw/misc/mmio_sockdev.c
```

## 实验 2：查看 Python transport

```bash
sed -n '140,210p' device_model/mmio_device_server.py
```

关注：

- `RWServer._handle_client`
- read/write packet 解析
- `bus.read()` / `bus.write()`
- write response `struct.pack('<Q', next_event_ns)`

## 实验 3：查看一个具体设备

```bash
sed -n '1,180p' device_model/uart_model.py
```

观察：

- TXDATA 如何输出
- RX FIFO 如何接入 `UartChannel`
- IRQ 如何触发

## 实验 4：观察生成常量

```bash
make gen
sed -n '1,160p' build/generated/mmio_devices.h
sed -n '1,160p' device_model/generated/device_consts.py
```

讨论：

- C 和 Python 是否使用同一份设备配置？
- 如果手写地址，可能出现什么问题？

## 思考题

1. 为什么 write 需要返回 `next_event_ns`，read 不需要？
2. 为什么不要直接探测 IRQ port？
3. Python model 和 SV model 在平台中的关系是什么？
4. 如果要加一个新外设，最少需要改哪些文件？
