#!/bin/bash
set -e

# Run script for the complete MMIO socket device demo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
QEMU_BIN="$PROJECT_ROOT/qemu-fork/build/qemu-system-arm"
FIRMWARE_BIN="$PROJECT_ROOT/build/firmware.bin"

echo "Starting MMIO Socket Device Demo..."

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
echo "Using QEMU: $QEMU_BIN"
echo ""
echo "NOTE: Make sure Python device server is running first:"
echo "  python3 tools/mmio_device_server.py --port 7890"
echo ""
echo "Starting QEMU in 3 seconds..."
sleep 3

# Run QEMU with our custom device
exec "$QEMU_BIN" \
    -M virt \
    -cpu cortex-a15 \
    -nographic \
    -monitor none \
    -no-reboot \
    -chardev socket,id=mmiosock,host=127.0.0.1,port=7890,server=off,wait=on \
    -device mmio-sockdev,chardev=mmiosock,addr=0x10020000 \
    -device loader,file="$FIRMWARE_BIN",addr=0x40200000,entry=0x40200000