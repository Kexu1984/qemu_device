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
FIRMWARE_HEX="$PROJECT_ROOT/build/firmware.hex"
SERVER_SCRIPT="$PROJECT_ROOT/device_model/mmio_device_server.py"
SV_BRIDGE="$PROJECT_ROOT/sv_device/build/sv_host_shell"
SECBOOT_SCRIPT="$PROJECT_ROOT/scripts/secure_boot_otp.py"

RW_PORT=7890
IRQ_PORT=7891
IRQ_DELAY=2       # seconds before server fires first IRQ (UART)
TIMEOUT=120        # polling iterations (0.5s each = 60s total) — WDT adds one boot cycle

# Optional: set ICOUNT_SHIFT=N to enable icount mode (-icount shift=N,sleep=off,align=off)
# E.g.  ICOUNT_SHIFT=5  bash scripts/e2e_test.sh
# shift=5 → 1 instr=32ns vtime, matching HCLK=48MHz CPI=2 (real=41.6ns/instr)
ICOUNT_SHIFT="${ICOUNT_SHIFT:-}"
if [ -n "$ICOUNT_SHIFT" ]; then
    ICOUNT_OPTS="-icount shift=${ICOUNT_SHIFT},sleep=off,align=off"
else
    ICOUNT_OPTS=""
fi

LOG_DIR="$PROJECT_ROOT/build"
SERVER_LOG="$LOG_DIR/e2e_server.log"
QEMU_LOG="$LOG_DIR/e2e_qemu.log"
UART_LOG="$LOG_DIR/e2e_uart.log"
SV_LOG="$LOG_DIR/e2e_sv_host_shell.log"
SV_WAVE="$LOG_DIR/e2e_sv_host_shell.vcd"
UART_TERM_PORT=7904

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}[INFO]${NC} $*"; }

cleanup() {
    info "Cleaning up background processes..."
    [ -n "${QEMU_PID:-}" ]    && kill "$QEMU_PID"    2>/dev/null || true
    [ -n "${SERVER_PID:-}" ]  && kill "$SERVER_PID"  2>/dev/null || true
    [ -n "${SV_PID:-}" ]      && kill "$SV_PID"      2>/dev/null || true
    [ -n "${UART_PID:-}" ]    && kill "$UART_PID"    2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# -----------------------------------------------------------------------
# Sanity checks
# -----------------------------------------------------------------------
for f in "$QEMU_BIN" "$FIRMWARE_HEX" "$SERVER_SCRIPT" "$SV_BRIDGE" "$SECBOOT_SCRIPT"; do
    if [ ! -f "$f" ]; then
        fail "Required file not found: $f"
        exit 1
    fi
done

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR/otp.hex" "$SV_WAVE"
info "Installing secure boot OTP metadata..."
python3 "$SECBOOT_SCRIPT" --firmware-hex "$FIRMWARE_HEX" --otp "$LOG_DIR/otp.hex" --fresh || exit 1
info "QEMU    : $QEMU_BIN"
info "Firmware HEX: $FIRMWARE_HEX"
echo ""

# -----------------------------------------------------------------------
# Kill any leftover processes from a previous run that may hold our ports
# -----------------------------------------------------------------------
for PORT in 7890 7891 7892 7893 7894 7895 7896 7897 7898 7899 7900 7901 7902 7903 7904 7905 7906 7907 7908 7909 7910 7911 7912 7913 7914 7915 7916 7918; do
    fuser -k "${PORT}/tcp" 2>/dev/null || true
done
sleep 0.3

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
# 2b. Connect UART terminal client (captures firmware output via port 7904)
# -----------------------------------------------------------------------
info "Waiting for UART terminal port $UART_TERM_PORT..."
TRIES=0
while true; do
    if nc -z 127.0.0.1 "$UART_TERM_PORT" 2>/dev/null; then
        info "Port $UART_TERM_PORT (UART terminal) ready."
        break
    fi
    TRIES=$((TRIES + 1))
    if [ "$TRIES" -ge 40 ]; then
        fail "Port $UART_TERM_PORT not ready after 8s. Server log:"
        cat "$SERVER_LOG"
        exit 1
    fi
    sleep 0.2
done

# Start nc as a passive terminal client; output goes to UART_LOG.
# We use python3 uart_console.py if available for ANSI passthrough, but
# plain nc is sufficient for log capture.
nc 127.0.0.1 "$UART_TERM_PORT" > "$UART_LOG" 2>/dev/null &
UART_PID=$!
info "UART terminal client PID: $UART_PID  (log: $UART_LOG)"

# -----------------------------------------------------------------------
# 2c. Start SystemVerilog/Verilator timer bridge
# -----------------------------------------------------------------------
info "Starting SV host shell (RW:7906, IRQ:7907, FABRIC:7912)..."
"$SV_BRIDGE" --rw-port 7906 --irq-port 7907 --mem-port 7912 --wave-file "$SV_WAVE" > "$SV_LOG" 2>&1 &
SV_PID=$!
info "SV host shell PID: $SV_PID  (log: $SV_LOG, wave: $SV_WAVE)"
sleep 0.5

# -----------------------------------------------------------------------
# 3. Start QEMU (background, capture to log)
# -----------------------------------------------------------------------
info "Starting QEMU..."
[ -n "$ICOUNT_OPTS" ] && info "icount mode: $ICOUNT_OPTS"
"$QEMU_BIN" \
    -M kx6625 \
    -smp 2 \
    -nographic \
    -monitor none \
    -no-reboot \
    ${ICOUNT_OPTS:+$ICOUNT_OPTS} \
    -chardev socket,id=uart_rw,host=127.0.0.1,port=7890 \
    -chardev socket,id=uart_irq,host=127.0.0.1,port=7891 \
    -device mmio-sockdev,chardev=uart_rw,irq-chardev=uart_irq,addr=0x40004000,irq-num=0 \
    -chardev socket,id=dma_rw,host=127.0.0.1,port=7892 \
    -chardev socket,id=dma_irq,host=127.0.0.1,port=7893 \
    -chardev socket,id=dma_mem,host=127.0.0.1,port=7897 \
    -chardev socket,id=dma_tick,host=127.0.0.1,port=7905 \
    -device mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,fabric-chardev=dma_mem,tick-chardev=dma_tick,tick-period-ms=0,addr=0x40005000,irq-num=1 \
    -chardev socket,id=timer_rw,host=127.0.0.1,port=7894 \
    -chardev socket,id=timer_irq,host=127.0.0.1,port=7895 \
    -chardev socket,id=timer_tick,host=127.0.0.1,port=7896 \
    -device mmio-sockdev,chardev=timer_rw,irq-chardev=timer_irq,tick-chardev=timer_tick,tick-period-ms=1,addr=0x40006000,irq-num=2 \
    -chardev socket,id=demo_rw,host=127.0.0.1,port=7898 \
    -chardev socket,id=demo_irq,host=127.0.0.1,port=7899 \
    -device mmio-sockdev,chardev=demo_rw,irq-chardev=demo_irq,addr=0x40007000,irq-num=3 \
    -chardev socket,id=crc_rw,host=127.0.0.1,port=7900 \
    -device mmio-sockdev,chardev=crc_rw,addr=0x40008000 \
    -chardev socket,id=wdt_rw,host=127.0.0.1,port=7901 \
    -chardev socket,id=wdt_irq,host=127.0.0.1,port=7902 \
    -chardev socket,id=wdt_rst,host=127.0.0.1,port=7903 \
    -device mmio-sockdev,chardev=wdt_rw,irq-chardev=wdt_irq,rst-chardev=wdt_rst,addr=0x40009000,irq-num=4 \
    -chardev socket,id=sv_island_rw,host=127.0.0.1,port=7906 \
    -chardev socket,id=sv_island_irq,host=127.0.0.1,port=7907 \
    -chardev socket,id=sv_island_mem,host=127.0.0.1,port=7912 \
    -device mmio-sockdev,chardev=sv_island_rw,irq-chardev=sv_island_irq,fabric-chardev=sv_island_mem,addr=0x4000B000,irq-num=5 \
    -chardev socket,id=hsm_rw,host=127.0.0.1,port=7908 \
    -chardev socket,id=hsm_irq,host=127.0.0.1,port=7909 \
    -device mmio-sockdev,chardev=hsm_rw,irq-chardev=hsm_irq,addr=0x4000C000,irq-num=6 \
    -chardev socket,id=otp_rw,host=127.0.0.1,port=7910 \
    -chardev socket,id=otp_irq,host=127.0.0.1,port=7911 \
    -device mmio-sockdev,chardev=otp_rw,irq-chardev=otp_irq,addr=0x4000D000,irq-num=7 \
    -chardev socket,id=coverage_rw,host=127.0.0.1,port=7918 \
    -device mmio-sockdev,chardev=coverage_rw,addr=0x40010000 \
    -kernel "$FIRMWARE_HEX" \
    </dev/null > "$QEMU_LOG" 2>&1 &
QEMU_PID=$!
info "QEMU PID: $QEMU_PID  (log: $QEMU_LOG)"

# -----------------------------------------------------------------------
# 4. Poll QEMU output until all expected lines appear or timeout
# -----------------------------------------------------------------------
EXPECTED=(
    "MMIO SockDev Interrupt Demo"
    "NVIC initialised"
    "KX6625 Test Menu"
    "UART IRQ demo"
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
    "Dual-CPU IPC PASS"
    "Dual-master MMIO PASS"
    "SV APB island timer"
    "SV timer fired"
    "IRQ observed and cleared PASSED"
    "Python master SV register access PASSED"
    "SV DMA prototype"
    "SV DMA ID SDMA PASSED"
    "SV DMA M2M copy PASSED"
    "SV DMA CH1 ID DCH1 PASSED"
    "SV DMA CH1 SPI TX PASSED"
    "SV GPIO test"
    "SV GPIO ID GPIO PASSED"
    "Output toggle PASSED"
    "Input simulation PASSED"
    "Change IRQ PASSED"
    "MCAL output toggle PASSED"
    "SV SPI TX test"
    "SPI TX ID SPTX PASSED"
    "SPI TX CPU FIFO transfer PASSED"
    "SV DMA CH1 SPI TX PASSED"
    "SPI TX error path PASSED"
    "HSM AES-CBC encrypt test"
    "HSM AES-CBC encrypt PASSED"
    "HSM AES-CMAC PASSED"
    "OTP controller test"
    "OTP] ID OTP1 PASSED"
    "OTP] Key slot0 programmed PASSED"
    "OTP] Key read protection PASSED"
    "OTP] Non-secret row read PASSED"
    "OTP] Zero-to-one rejection PASSED"
    "OTP] HSM OTP KEY_ID0 AES-CBC PASSED"
    "Native SYSCTRL register test"
    "SYSCTRL] ID SCTL PASSED"
    "SYSCTRL] BOOT_STATUS flash/vector PASSED"
    "SYSCTRL] SECURE_BOOT CMAC PASSED"
    "SYSCTRL] CPU_STATUS CPU1 released PASSED"
    "SYSCTRL] DEVICE reset policy PASSED"
    "SYSCTRL] DEVCTL UART STATUS read PASSED"
    "Power-on reset (RESET_REASON=POR)"
    "Kick 1"
    "Kick 2"
    "Waiting for WDT timeout"
    "WDT] TIMEOUT"
    "Warm boot detected: RESET_REASON=WDT"
    "WDT demo complete"
)

info "Waiting up to ${TIMEOUT}s for expected firmware output (in SERVER_LOG)..."

# -----------------------------------------------------------------------
# 4a. Wait for the menu prompt '# ' then inject command 'a' (all tests)
# -----------------------------------------------------------------------
info "Waiting for firmware menu prompt '# '..."
PROMPT_TRIES=0
while true; do
    if grep -q "KX6625 Test Menu" "$SERVER_LOG" 2>/dev/null; then
        info "Menu prompt detected. Injecting command 'a' (all tests)..."
        # Give the firmware a moment to be ready for RX, then send 'a\n'
        sleep 0.2
        printf 'a\n' | nc -q1 127.0.0.1 "$UART_TERM_PORT" 2>/dev/null || true
        info "Command 'a' injected into UART RX (port $UART_TERM_PORT)."
        break
    fi
    PROMPT_TRIES=$((PROMPT_TRIES + 1))
    if [ "$PROMPT_TRIES" -ge 60 ]; then
        fail "Menu prompt not seen after 15s. Server log:"
        cat "$SERVER_LOG"
        exit 1
    fi
    sleep 0.25
done

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
echo "============================ SV host shell log ============================="
cat "$SV_LOG"
echo "============================================================================="
echo ""

# Firmware text is emitted via TXDATA -> Python server stdout -> SERVER_LOG
RESULT=0
if [ -f "$SV_WAVE" ]; then
    pass "SV wave dump: $SV_WAVE"
else
    fail "SV wave dump missing: $SV_WAVE"
    RESULT=1
fi
for LINE in "${EXPECTED[@]}"; do
    if grep -q "$LINE" "$SERVER_LOG" 2>/dev/null; then
        pass "Found: \"$LINE\""
    else
        fail "Missing: \"$LINE\""
        RESULT=1
    fi
done

SV_EXPECTED=(
    "[SVSPI] frame done data=0xa5"
    "[SVSPI] frame done data=0x5a"
    "[SVSPI] frame done data=0x3c"
    "[SV-FABRIC] local write addr=0x4000b324 data=0x00000011"
    "[SV-FABRIC] local write addr=0x4000b324 data=0x00000022"
    "[SV-FABRIC] local write addr=0x4000b324 data=0x00000033"
    "[SV-FABRIC] local write addr=0x4000b324 data=0x00000044"
    "[SVSPI] frame done data=0x11"
    "[SVSPI] frame done data=0x22"
    "[SVSPI] frame done data=0x33"
    "[SVSPI] frame done data=0x44"
)

for LINE in "${SV_EXPECTED[@]}"; do
    if grep -Fq "$LINE" "$SV_LOG" 2>/dev/null; then
        pass "[SV] Found: \"$LINE\""
    else
        fail "[SV] Missing: \"$LINE\""
        RESULT=1
    fi
done

# -----------------------------------------------------------------------
# 5b. Verify UART terminal channel (port 7904) received firmware output
# -----------------------------------------------------------------------
# Give nc a moment to flush buffered data before we kill it.
sleep 0.3
[ -n "${UART_PID:-}" ] && kill "$UART_PID" 2>/dev/null || true
UART_PID=""

echo ""
echo "=========================== UART terminal output ============================"
# Strip \r so the log prints cleanly on any terminal
tr -d '\r' < "$UART_LOG" 2>/dev/null || true
echo "============================================================================="
echo ""

# A subset of expected strings that must also arrive via the UART channel.
# LF is translated to CRLF by UartChannel, but grep matches substrings so
# \r at end-of-line does not break the match.
UART_EXPECTED=(
    "MMIO SockDev Interrupt Demo"
    "KX6625 Test Menu"
    "UART interrupt handled"
    "All tests done"
    "Dual-master MMIO PASS"
    "MCAL output toggle PASSED"
    "SPI TX CPU FIFO transfer PASSED"
    "HSM AES-CMAC PASSED"
    "HSM OTP KEY_ID0 AES-CBC PASSED"
    "DEVCTL UART STATUS read PASSED"
    "SECURE_BOOT CMAC PASSED"
    "Warm boot detected"
    "WDT demo complete"
)

for LINE in "${UART_EXPECTED[@]}"; do
    if grep -q "$LINE" "$UART_LOG" 2>/dev/null; then
        pass "[UART] Found: \"$LINE\""
    else
        fail "[UART] Missing: \"$LINE\""
        RESULT=1
    fi
done

echo ""
if [ "$RESULT" -eq 0 ]; then
    pass "End-to-end IRQ test PASSED"
else
    fail "End-to-end IRQ test FAILED"
fi

# -----------------------------------------------------------------------
# 6. Generate HTML trace report
# -----------------------------------------------------------------------
TRACE_FILE="$LOG_DIR/device_trace.jsonl"
TRACE_HTML="$LOG_DIR/trace_report.html"
VISUALIZE="$SCRIPT_DIR/visualize_trace.py"

echo ""
info "Generating HTML trace report..."
if [ ! -f "$TRACE_FILE" ]; then
    info "No trace file found at $TRACE_FILE — skipping report."
elif [ ! -f "$VISUALIZE" ]; then
    info "visualize_trace.py not found — skipping report."
else
    ICOUNT_LABEL=""
    [ -n "${ICOUNT_SHIFT:-}" ] && ICOUNT_LABEL=" (icount shift=${ICOUNT_SHIFT})"
    python3 "$VISUALIZE" \
        "$TRACE_FILE" \
        -o "$TRACE_HTML" \
        --title "KX6625 Device Trace${ICOUNT_LABEL}" \
    && pass "Trace report: $TRACE_HTML" \
    || info "Trace report generation failed (non-fatal)."
fi

exit $RESULT
