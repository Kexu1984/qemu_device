#!/bin/bash
set -e

# Run script for the complete MMIO socket device demo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
QEMU_BIN="$PROJECT_ROOT/scripts/qemu-fork/build/qemu-system-arm"
FIRMWARE_BIN="$PROJECT_ROOT/build/firmware.bin"

echo "Starting MMIO Socket Device Demo (with IRQ support)..."

# Check if firmware exists
if [ ! -f "$FIRMWARE_BIN" ]; then
    echo "Error: Firmware not found at $FIRMWARE_BIN"
    echo "Please run 'make fw' first"
    exit 1
fi

# Check if QEMU exists
if [ ! -f "$QEMU_BIN" ]; then
    echo "Error: QEMU not found at $QEMU_BIN"
    echo "Please run 'make qemu' first"
    exit 1
fi

echo "Using firmware: $FIRMWARE_BIN"
echo "Using QEMU:     $QEMU_BIN"
echo ""
echo "NOTE: Make sure Python device server is running first:"
echo "  python3 -m device_model.mmio_device_server"
echo ""
echo "Starting QEMU in 3 seconds..."
sleep 3

# Run QEMU with three mmio-sockdev instances:
#
#  KX6625 SoC peripheral map:
#  1. console_uart (addr=0x40004000, IRQ0)  — UART + one-shot IRQ demo
#  2. dma          (addr=0x40005000, IRQ1)  — DMA with bus-master mem channel
#  3. timer0       (addr=0x40006000, IRQ2)  — virtual-clock tick timer
#
# Each device has:
#   chardev     (rw)   — MMIO register read/write channel (QEMU <-> Python)
#   irq-chardev        — IRQ injection channel           (Python -> QEMU)
# Optional per device:
#   mem-chardev        — DMA bus-master channel          (Python -> QEMU phys mem)
#   tick-chardev       — Virtual-clock tick channel      (QEMU -> Python)
exec "$QEMU_BIN" \
    -M kx6625 \
    -nographic \
    -monitor none \
    -no-reboot \
    \
    -chardev socket,id=uart_rw,host=127.0.0.1,port=7890 \
    -chardev socket,id=uart_irq,host=127.0.0.1,port=7891 \
    -device mmio-sockdev,chardev=uart_rw,irq-chardev=uart_irq,addr=0x40004000,irq-num=0 \
    \
    -chardev socket,id=dma_rw,host=127.0.0.1,port=7892 \
    -chardev socket,id=dma_irq,host=127.0.0.1,port=7893 \
    -chardev socket,id=dma_mem,host=127.0.0.1,port=7897 \
    -device mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,mem-chardev=dma_mem,addr=0x40005000,irq-num=1 \
    \
    -chardev socket,id=timer_rw,host=127.0.0.1,port=7894 \
    -chardev socket,id=timer_irq,host=127.0.0.1,port=7895 \
    -chardev socket,id=timer_tick,host=127.0.0.1,port=7896 \
    -device mmio-sockdev,chardev=timer_rw,irq-chardev=timer_irq,tick-chardev=timer_tick,tick-period-ms=1,addr=0x40006000,irq-num=2 \
    \
    -kernel "${FIRMWARE_BIN%.bin}.elf"