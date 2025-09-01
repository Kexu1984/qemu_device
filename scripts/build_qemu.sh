#!/bin/bash
set -e

# Build script for QEMU with custom mmio-sockdev

QEMU_VERSION="v8.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QEMU_DIR="$SCRIPT_DIR/qemu-fork"

echo "Building QEMU with custom mmio-sockdev..."

# Clone QEMU if not exists
if [ ! -d "$QEMU_DIR/.git" ]; then
    echo "Cloning QEMU..."
    git clone --depth 1 --branch $QEMU_VERSION https://github.com/qemu/qemu.git "$QEMU_DIR"
fi

cd "$QEMU_DIR"

# Install build dependencies (Ubuntu/Debian)
if command -v apt-get >/dev/null 2>&1; then
    echo "Installing build dependencies..."
    sudo apt-get update
    sudo apt-get install -y \
        build-essential \
        ninja-build \
        pkg-config \
        libglib2.0-dev \
        libpixman-1-dev \
        libfdt-dev \
        zlib1g-dev \
        libslirp-dev \
        git \
        python3 \
        python3-venv
fi

# Add our custom device to meson.build if not already added
if ! grep -q "mmio_sockdev.c" hw/misc/meson.build; then
    echo "Adding mmio_sockdev to meson.build..."
    sed -i "/^misc_ss.add/a misc_ss.add(files('mmio_sockdev.c'))" hw/misc/meson.build
fi

# Configure and build
if [ ! -f "build/config.h" ]; then
    echo "Configuring QEMU..."
    ./configure --target-list=arm-softmmu --enable-slirp
fi

echo "Building QEMU..."
cd build
ninja

echo "QEMU build complete: $QEMU_DIR/build/qemu-system-arm"