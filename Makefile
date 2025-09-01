# Makefile for QEMU MMIO Socket Device Project

.PHONY: all qemu fw run clean help

# Default target
all: help

# Build QEMU with custom mmio-sockdev
qemu:
	@echo "Building QEMU with custom mmio-sockdev..."
	./scripts/build_qemu.sh

# Build firmware
fw:
	@echo "Building firmware..."
	$(MAKE) -C firmware

# Run the complete demo
run:
	@echo "=========================================="
	@echo "QEMU MMIO Socket Device Demo"
	@echo "=========================================="
	@echo ""
	@echo "To run the demo, you need TWO terminals:"
	@echo ""
	@echo "Terminal 1 (Python server):"
	@echo "  python3 tools/mmio_device_server.py --port 7890"
	@echo ""
	@echo "Terminal 2 (QEMU):"
	@echo "  ./scripts/run_demo.sh"
	@echo ""
	@echo "Expected output in Terminal 1:"
	@echo "  Hello from MMIO sockdev"
	@echo ""
	@echo "Press Ctrl+C to stop QEMU"
	@echo "=========================================="

# Start Python server in background and run QEMU
run-auto:
	@echo "Starting Python server in background..."
	python3 tools/mmio_device_server.py --port 7890 &
	@echo "Waiting for server to start..."
	sleep 2
	@echo "Starting QEMU..."
	./scripts/run_demo.sh
	@echo "Stopping Python server..."
	pkill -f "mmio_device_server.py" || true

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	$(MAKE) -C firmware clean
	rm -rf qemu-fork/build/

# Help
help:
	@echo "QEMU MMIO Socket Device Project"
	@echo "================================"
	@echo ""
	@echo "Available targets:"
	@echo "  qemu      - Build QEMU with custom mmio-sockdev"
	@echo "  fw        - Build bare metal firmware"
	@echo "  run       - Show instructions for running demo"
	@echo "  run-auto  - Run demo automatically (experimental)"
	@echo "  clean     - Clean all build artifacts"
	@echo "  help      - Show this help"
	@echo ""
	@echo "Quick start:"
	@echo "  make fw        # Build firmware"
	@echo "  make qemu      # Build QEMU (takes time)"
	@echo "  make run       # Show run instructions"