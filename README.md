# QEMU Custom MMIO Socket Device

A QEMU custom SysBus MMIO device that proxies register access to an external Python process via TCP socket. This demonstrates how to create custom hardware devices in QEMU and implement their logic externally.

## Overview

This project implements:
- **Custom QEMU Device**: `mmio-sockdev` - a SysBus device that maps 4KB MMIO region
- **Python Device Server**: Implements register semantics and device behavior
- **Bare Metal Firmware**: ARMv7-A firmware that demonstrates device usage
- **Build System**: Scripts and Makefiles for easy compilation and testing

### Architecture

```
┌─────────────────┐    TCP Socket    ┌─────────────────┐
│   QEMU Guest    │ ◄────────────────► │ Python Server   │
│                 │   Binary Protocol │                 │
│ ┌─────────────┐ │                   │ ┌─────────────┐ │
│ │ Bare Metal  │ │                   │ │ Register    │ │
│ │ Firmware    │ │                   │ │ Emulation   │ │
│ │             │ │                   │ │             │ │
│ │ MMIO Write  │ │                   │ │ Print Chars │ │
│ │ 0x10020000  │ │                   │ │ to stdout   │ │
│ └─────────────┘ │                   │ └─────────────┘ │
│                 │                   │                 │
│ mmio-sockdev    │                   │ Device Logic    │
└─────────────────┘                   └─────────────────┘
```

## Register Map

The device implements a simple UART-like interface:

| Offset | Name    | Access | Description                           |
|--------|---------|--------|---------------------------------------|
| 0x00   | TXDATA  | W      | Write character to output (low 8 bits)|
| 0x04   | STATUS  | R      | bit0=TXREADY (always 1)              |
| 0x08   | CTRL    | R/W    | bit0=ENABLE (default 1)              |

## Communication Protocol

Binary protocol over TCP socket (little-endian):

### Read Operation
```
Host → Python: 'R' (1B) | addr(4B) | size(1B)
Python → Host: data(sizeB)
```

### Write Operation  
```
Host → Python: 'W' (1B) | addr(4B) | size(1B) | data(sizeB)
```

## Quick Start

### Prerequisites

- Ubuntu/Debian system (or compatible)
- ARM cross-compilation toolchain: `sudo apt install gcc-arm-none-eabi`
- Python 3
- Build tools: `sudo apt install build-essential ninja-build pkg-config`

### Build and Run

1. **Build the firmware:**
   ```bash
   make fw
   ```

2. **Build QEMU with custom device (takes 10-15 minutes):**
   ```bash
   make qemu
   ```

3. **Run the demo:**
   
   **Terminal 1** (Python device server):
   ```bash
   python3 tools/mmio_device_server.py --port 7890
   ```
   
   **Terminal 2** (QEMU):
   ```bash
   ./scripts/run_demo.sh
   ```

### Expected Output

In Terminal 1 (Python server), you should see:
```
MMIO Device Server listening on port 7890
Register map:
  0x00 TXDATA (W): Print character
  0x04 STATUS (R): TXREADY=1
  0x08 CTRL (R/W): ENABLE bit
Waiting for QEMU connection...
Client connected from ('127.0.0.1', 12345)
Hello from MMIO sockdev
```

## Project Structure

```
qemu_device/
├── Makefile                    # Main build system
├── README.md                   # This file
├── .gitignore                  # Git ignore rules
├── qemu-fork/                  # QEMU source with custom device
│   └── hw/misc/mmio_sockdev.c  # Custom MMIO device implementation
├── tools/
│   └── mmio_device_server.py   # Python device server
├── firmware/                   # Bare metal firmware
│   ├── start.S                 # ARM startup code
│   ├── main.c                  # Main firmware logic
│   ├── linker.ld              # Linker script
│   └── Makefile               # Firmware build system
├── scripts/
│   ├── build_qemu.sh          # QEMU build script
│   └── run_demo.sh            # Demo run script
└── build/                     # Build artifacts (gitignored)
    └── firmware.bin           # Compiled firmware
```

## Makefile Targets

- `make fw` - Build bare metal firmware
- `make qemu` - Build QEMU with custom device
- `make run` - Show demo run instructions  
- `make clean` - Clean all build artifacts
- `make help` - Show available targets

## Development Notes

### QEMU Device Implementation

The custom device (`mmio_sockdev.c`) implements:
- SysBus device inheriting from `SysBusDevice`
- 4KB MMIO region with read/write callbacks
- TCP socket communication via QEMU's CharBackend
- Thread-safe access with mutex locking

### Python Server Features

The device server (`mmio_device_server.py`) provides:
- TCP server accepting QEMU connections
- Binary protocol parsing
- Register space emulation (4KB)
- Character output when TXDATA is written
- Persistent CTRL register state

### Firmware Details

The bare metal firmware demonstrates:
- ARMv7-A assembly startup code
- Memory-mapped I/O access functions
- UART-style character transmission
- Proper register polling (TXREADY status)

## Troubleshooting

### Common Issues

1. **"chardev not connected"**: Ensure Python server is running before starting QEMU
2. **"Connection refused"**: Check if port 7890 is available and not blocked by firewall
3. **"ARM toolchain missing"**: Install with `sudo apt install gcc-arm-none-eabi`
4. **QEMU build fails**: Ensure all dependencies are installed (see build script)

### Debug Tips

- Use `make clean` to clean build artifacts if builds fail
- Check Python server output for connection status
- Use `lsof -i :7890` to verify server is listening
- QEMU can be stopped with Ctrl+A, X (in monitor mode) or Ctrl+C

## License

This project is provided as educational material for understanding QEMU device development and system emulation.
