#!/bin/bash
#
# End-to-end IRQ smoke test for mmio-sockdev
#
# Sequence:
#   1. Start Python device server (RW port=7890, IRQ port=7891, irq-delay=3s)
#   2. Wait for both ports to be ready (using nc)
#   3. Start QEMU with the custom device and firmware
#   4. Capture combined output for up to TIMEOUT seconds
#   5. Assert that the firmware printed the expected log lines
#   6. Kill QEMU and Python server
#   7. Report PASS or FAIL
#
# NOTE: No set -e so background-job failures don't abort polling loops.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

QEMU_BIN="$PROJECT_ROOT/scripts/qemu-fork/build/qemu-system-arm"
FIRMWARE_BIN="$PROJECT_ROOT/build/firmware.bin"
SERVER_SCRIPT="$PROJECT_ROOT/device_model/mmio_device_server.py"

RW_PORT=7890
IRQ_PORT=7891
IRQ_DELAY=2       # seconds before server fires first IRQ (UART)
TIMEOUT=80        # polling iterations (0.5s each = 40s total)

LOG_DIR="$PROJECT_ROOT/build"
SERVER_LOG="$LOG_DIR/e2e_server.log"
QEMU_LOG="$LOG_DIR/e2e_qemu.log"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}[INFO]${NC} $*"; }

cleanup() {
    info "Cleaning up background processes..."
    [ -n "${QEMU_PID:-}" ]   && kill "$QEMU_PID"   2>/dev/null || true
    [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# -----------------------------------------------------------------------
# Sanity checks
# -----------------------------------------------------------------------
for f in "$QEMU_BIN" "$FIRMWARE_BIN" "$SERVER_SCRIPT"; do
    if [ ! -f "$f" ]; then
        fail "Required file not found: $f"
        exit 1
    fi
done

mkdir -p "$LOG_DIR"
info "QEMU    : $QEMU_BIN"
info "Firmware: $FIRMWARE_BIN"
echo ""

# -----------------------------------------------------------------------
# 1. Start Python device server
# -----------------------------------------------------------------------
info "Starting Python device server (RW:$RW_PORT, IRQ:$IRQ_PORT, delay:${IRQ_DELAY}s)..."
python3 "$SERVER_SCRIPT" \
    --port "$RW_PORT" \
    --irq-port "$IRQ_PORT" \
    --irq-delay "$IRQ_DELAY" \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
info "Server PID: $SERVER_PID  (log: $SERVER_LOG)"
sleep 0.5   # give Python time to bind before polling

# -----------------------------------------------------------------------
# 2. Wait for both TCP ports to be ready (nc is simpler than Python one-liner)
# -----------------------------------------------------------------------
info "Waiting for RW server port..."
for PORT in $RW_PORT; do
    TRIES=0
    while true; do
        if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
            info "Port $PORT ready."
            break
        fi
        TRIES=$((TRIES + 1))
        if [ "$TRIES" -ge 40 ]; then
            fail "Port $PORT not ready after 8s. Server log:"
            cat "$SERVER_LOG"
            exit 1
        fi
        sleep 0.2
    done
done

# Avoid probing IRQ port directly: an active connect check would consume
# the IRQ channel and perturb one-shot interrupt timing.
sleep 0.3

# -----------------------------------------------------------------------
# 3. Start QEMU (background, capture to log)
# -----------------------------------------------------------------------
info "Starting QEMU..."
"$QEMU_BIN" \
    -M kx6625 \
    -nographic \
    -monitor none \
    -no-reboot \
    -chardev socket,id=uart_rw,host=127.0.0.1,port=7890 \
    -chardev socket,id=uart_irq,host=127.0.0.1,port=7891 \
    -device mmio-sockdev,chardev=uart_rw,irq-chardev=uart_irq,addr=0x40004000,irq-num=0 \
    -chardev socket,id=dma_rw,host=127.0.0.1,port=7892 \
    -chardev socket,id=dma_irq,host=127.0.0.1,port=7893 \
    -chardev socket,id=dma_mem,host=127.0.0.1,port=7897 \
    -device mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,mem-chardev=dma_mem,addr=0x40005000,irq-num=1 \
    -chardev socket,id=timer_rw,host=127.0.0.1,port=7894 \
    -chardev socket,id=timer_irq,host=127.0.0.1,port=7895 \
    -chardev socket,id=timer_tick,host=127.0.0.1,port=7896 \
    -device mmio-sockdev,chardev=timer_rw,irq-chardev=timer_irq,tick-chardev=timer_tick,tick-period-ms=1,addr=0x40006000,irq-num=2 \
    -chardev socket,id=demo_rw,host=127.0.0.1,port=7898 \
    -chardev socket,id=demo_irq,host=127.0.0.1,port=7899 \
    -device mmio-sockdev,chardev=demo_rw,irq-chardev=demo_irq,addr=0x40007000,irq-num=3 \
    -chardev socket,id=crc_rw,host=127.0.0.1,port=7900 \
    -device mmio-sockdev,chardev=crc_rw,addr=0x40008000 \
    -kernel "${FIRMWARE_BIN%.bin}.elf" \
    </dev/null > "$QEMU_LOG" 2>&1 &
QEMU_PID=$!
info "QEMU PID: $QEMU_PID  (log: $QEMU_LOG)"

# -----------------------------------------------------------------------
# 4. Poll QEMU output until all expected lines appear or timeout
# -----------------------------------------------------------------------
EXPECTED=(
    "MMIO SockDev Interrupt Demo"
    "NVIC initialised"
    "IRQs enabled"
    "UART interrupt handled"
    "DMA demo"
    "DMA started"
    "Verification PASSED"
    "Demo complete"
    "DMA client test"
    "DMA client transfer started"
    "Transfer verified PASSED"
    "All demos complete"
    "CRC test"
    "0xCBF43926 PASSED"
    "DMA-CRC test"
    "DMA-CRC] Result 0xCBF43926 PASSED"
    "All tests done"
)

info "Waiting up to ${TIMEOUT}s for expected firmware output (in SERVER_LOG)..."
ELAPSED=0
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    ALL_FOUND=1
    for LINE in "${EXPECTED[@]}"; do
        if ! grep -q "$LINE" "$SERVER_LOG" 2>/dev/null; then
            ALL_FOUND=0
            break
        fi
    done
    if [ "$ALL_FOUND" -eq 1 ]; then
        break
    fi
    sleep 0.5
    ELAPSED=$((ELAPSED + 1))

    # Bail early if QEMU has already exited
    if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        break
    fi
done

# -----------------------------------------------------------------------
# 5. Evaluate results
# -----------------------------------------------------------------------
echo ""
echo "============================== Firmware output =============================="
cat "$QEMU_LOG"
echo "============================================================================="
echo ""
echo "============================== Server output ================================"
cat "$SERVER_LOG"
echo "============================================================================="
echo ""

# Firmware text is emitted via TXDATA -> Python server stdout -> SERVER_LOG
RESULT=0
for LINE in "${EXPECTED[@]}"; do
    if grep -q "$LINE" "$SERVER_LOG" 2>/dev/null; then
        pass "Found: \"$LINE\""
    else
        fail "Missing: \"$LINE\""
        RESULT=1
    fi
done

echo ""
if [ "$RESULT" -eq 0 ]; then
    pass "End-to-end IRQ test PASSED"
else
    fail "End-to-end IRQ test FAILED"
fi
exit $RESULT
