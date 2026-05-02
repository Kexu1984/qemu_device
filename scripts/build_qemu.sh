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

# Copy an out-of-tree mmio-sockdev implementation when present.  Current
# checkouts keep the maintained source directly in scripts/qemu-fork.
if [ -f "$SCRIPT_DIR/../device_model/mmio_sockdev.c" ]; then
    echo "Installing custom mmio_sockdev.c from device_model/ ..."
    cp "$SCRIPT_DIR/../device_model/mmio_sockdev.c" hw/misc/mmio_sockdev.c
elif [ -f "hw/misc/mmio_sockdev.c" ]; then
    echo "Using mmio_sockdev.c already present in qemu-fork."
else
    echo "ERROR: hw/misc/mmio_sockdev.c not found."
    exit 1
fi

# Install build dependencies (Ubuntu/Debian) only before first configure.
# Existing build trees can do a normal incremental ninja build without sudo.
# Set SKIP_APT=1 to force a non-interactive build-only path.
if [ "${SKIP_APT:-0}" != "1" ] && [ ! -f "build/build.ninja" ] && command -v apt-get >/dev/null 2>&1; then
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
if [ ! -f "build/build.ninja" ]; then
    echo "Configuring QEMU..."
    ./configure --target-list=arm-softmmu --enable-slirp
fi

echo "Building QEMU..."
cd build
ninja

echo "QEMU build complete: $QEMU_DIR/build/qemu-system-arm"