# Makefile for QEMU MMIO Socket Device Project

.PHONY: all qemu fw sv gen run clean test help

# Default target
all: help

# Generate C header and Python device map from spec/devices.yaml
gen:
	@echo "Generating device code from spec/devices.yaml..."
	python3 scripts/gen_device_code.py

# Build QEMU with custom mmio-sockdev
qemu:
	@echo "Building QEMU with custom mmio-sockdev..."
	./scripts/build_qemu.sh

# Build firmware (runs gen automatically)
fw:
	@echo "Building firmware..."
	$(MAKE) -C firmware

# Build SystemVerilog/Verilator device prototypes
sv:
	@echo "Building SystemVerilog device prototypes..."
	$(MAKE) -C sv_device

# Run the complete demo
run:
	@echo "=========================================="
	@echo "QEMU MMIO Socket Device Demo"
	@echo "=========================================="
	@echo ""
	@echo "To run the demo, you need TWO terminals:"
	@echo ""
	@echo "Terminal 1 (Python server):"
	@echo "  python3 device_model/mmio_device_server.py --port 7890"
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
	python3 device_model/mmio_device_server.py --port 7890 &
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
	$(MAKE) -C sv_device clean
	rm -rf device_model/generated/

# Help
help:
	@echo "QEMU MMIO Socket Device Project"
	@echo "================================"
	@echo ""
	@echo "Available targets:"
	@echo "  gen       - Generate C header + Python map from config/devices.yaml"
	@echo "  qemu      - Build QEMU with custom mmio-sockdev"
	@echo "  fw        - Build bare metal firmware (runs gen automatically)"
	@echo "  sv        - Build SystemVerilog/Verilator device prototypes"
	@echo "  run       - Show instructions for running demo"
	@echo "  run-auto  - Run demo automatically (experimental)"
	@echo "  test      - Test protocol implementation"
	@echo "  clean     - Clean all build artifacts"
	@echo "  help      - Show this help"
	@echo ""
	@echo "Quick start:"
	@echo "  make gen       # Generate device headers from config/devices.yaml"
	@echo "  make fw        # Build firmware"
	@echo "  make test      # Test protocol"
	@echo "  make qemu      # Build QEMU (takes time)"
	@echo "  make run       # Show run instructions"