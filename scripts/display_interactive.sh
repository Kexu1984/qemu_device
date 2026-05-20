#!/bin/bash
#
# display_interactive.sh - Display-path interactive validation.
#
# Starts the Python device server, SV host shell, and QEMU with the display
# mmio-sockdev instance, then injects firmware menu command 'd'. The Python
# display model renders the RGB565 framebuffer in a host Tk window when a GUI
# display is available. The simulation stays alive until Ctrl-C so the rendered
# frame can be inspected.
#
# Usage:
#   bash scripts/display_interactive.sh
#   ICOUNT_SHIFT=5 bash scripts/display_interactive.sh
#   BUILD_FIRMWARE=0 bash scripts/display_interactive.sh
#   AWTK_DEMO=1 bash scripts/display_interactive.sh
#   DISPLAY_KEEPALIVE=0 AWTK_DEMO=1 bash scripts/display_interactive.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

QEMU_BIN="$PROJECT_ROOT/scripts/qemu-fork/build/qemu-system-arm"
FIRMWARE_HEX="$PROJECT_ROOT/build/firmware.hex"
SERVER_SCRIPT="$PROJECT_ROOT/device_model/mmio_device_server.py"
SV_BRIDGE="$PROJECT_ROOT/sv_device/build/sv_host_shell"
SECBOOT_SCRIPT="$PROJECT_ROOT/scripts/secure_boot_otp.py"

UART_TERM_PORT=7904
RW_PORT=7890
IRQ_PORT=7891
IRQ_DELAY=2

BUILD_FIRMWARE="${BUILD_FIRMWARE:-1}"
AWTK_DEMO="${AWTK_DEMO:-0}"
ICOUNT_SHIFT="${ICOUNT_SHIFT:-5}"
DISPLAY_CMD="${DISPLAY_CMD:-d}"
DISPLAY_EXPECT="${DISPLAY_EXPECT:-Frame CRC 0xD57022DF PASSED}"
DISPLAY_KEEPALIVE="${DISPLAY_KEEPALIVE:-1}"
DISPLAY_VALIDATE_TRIES="${DISPLAY_VALIDATE_TRIES:-}"
if [[ "$AWTK_DEMO" == "1" && "${DISPLAY_CMD}" == "d" ]]; then
    DISPLAY_CMD="w"
    DISPLAY_EXPECT="[AWTK] RGB565 display demo done."
fi
DISPLAY_VALIDATE_TRIES="${DISPLAY_VALIDATE_TRIES:-$([[ "$AWTK_DEMO" == "1" ]] && echo 600 || echo 120)}"
if [[ -n "$ICOUNT_SHIFT" ]]; then
    ICOUNT_OPTS="-icount shift=${ICOUNT_SHIFT},sleep=off,align=off"
else
    ICOUNT_OPTS=""
fi

LOG_DIR="$PROJECT_ROOT/build"
SERVER_LOG="$LOG_DIR/display_interactive_server.log"
QEMU_LOG="$LOG_DIR/display_interactive_qemu.log"
UART_LOG="$LOG_DIR/display_interactive_uart.log"
SV_LOG="$LOG_DIR/display_interactive_sv_host_shell.log"
SV_WAVE="$LOG_DIR/display_interactive_sv_host_shell.vcd"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[display]${NC} $*"; }
ok()   { echo -e "${GREEN}[display]${NC} $*"; }
warn() { echo -e "${YELLOW}[display]${NC} $*"; }
err()  { echo -e "${RED}[display]${NC} $*" >&2; }

QEMU_PID=""
SERVER_PID=""
SV_PID=""
UART_PID=""
TAIL_PID=""
CLEANED_UP=0

cleanup() {
    [[ "$CLEANED_UP" -eq 1 ]] && return
    CLEANED_UP=1
    echo ""
    info "Stopping display interactive session..."
    [[ -n "${TAIL_PID:-}"   ]] && kill "$TAIL_PID"   2>/dev/null || true
    [[ -n "${UART_PID:-}"   ]] && kill "$UART_PID"   2>/dev/null || true
    [[ -n "${QEMU_PID:-}"   ]] && kill "$QEMU_PID"   2>/dev/null || true
    [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
    [[ -n "${SV_PID:-}"     ]] && kill "$SV_PID"     2>/dev/null || true
    wait 2>/dev/null || true
    ok "Stopped. Logs are under $LOG_DIR."
}
trap cleanup EXIT INT TERM

for f in "$QEMU_BIN" "$SERVER_SCRIPT" "$SV_BRIDGE" "$SECBOOT_SCRIPT"; do
    if [[ ! -f "$f" ]]; then
        err "Required file not found: $f"
        exit 1
    fi
done

if [[ "$BUILD_FIRMWARE" == "1" ]]; then
    info "Building firmware..."
    make -C "$PROJECT_ROOT/firmware" AWTK_DEMO="$AWTK_DEMO"
fi

if [[ ! -f "$FIRMWARE_HEX" ]]; then
    err "Firmware image not found: $FIRMWARE_HEX"
    err "Run make -C firmware or set BUILD_FIRMWARE=1."
    exit 1
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    warn "No DISPLAY/WAYLAND_DISPLAY detected; the display model will still run, but no Tk window can open."
else
    info "GUI environment detected: DISPLAY=${DISPLAY:-<unset>} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>}"
fi

mkdir -p "$LOG_DIR"
rm -f "$SERVER_LOG" "$QEMU_LOG" "$UART_LOG" "$SV_LOG" "$SV_WAVE" "$LOG_DIR/otp.hex"

info "Releasing simulator ports..."
for PORT in 7890 7891 7892 7893 7894 7895 7896 7897 7898 7899 7900 7901 7902 7903 7904 7905 7906 7907 7908 7909 7910 7911 7912 7913 7914 7915 7916 7918 7919 7920; do
    fuser -k "${PORT}/tcp" 2>/dev/null || true
done

info "Installing secure boot OTP metadata..."
python3 "$SECBOOT_SCRIPT" --firmware-hex "$FIRMWARE_HEX" --otp "$LOG_DIR/otp.hex" --fresh

info "Starting Python device server..."
python3 "$SERVER_SCRIPT" \
    --port "$RW_PORT" \
    --irq-port "$IRQ_PORT" \
    --irq-delay "$IRQ_DELAY" \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

TRIES=0
while ! nc -z 127.0.0.1 "$RW_PORT" 2>/dev/null; do
    TRIES=$((TRIES + 1))
    if [[ "$TRIES" -ge 60 ]]; then
        err "Device server did not start. Server log:"
        cat "$SERVER_LOG" >&2 || true
        exit 1
    fi
    sleep 0.2
done
ok "Device server ready."

info "Starting SV host shell..."
"$SV_BRIDGE" --rw-port 7906 --irq-port 7907 --mem-port 7912 --wave-file "$SV_WAVE" > "$SV_LOG" 2>&1 &
SV_PID=$!

TRIES=0
while ! nc -z 127.0.0.1 7906 2>/dev/null; do
    TRIES=$((TRIES + 1))
    if [[ "$TRIES" -ge 60 ]]; then
        err "SV host shell did not start. SV log:"
        cat "$SV_LOG" >&2 || true
        exit 1
    fi
    sleep 0.2
done
ok "SV host shell ready."

info "Connecting UART log capture..."
TRIES=0
while ! nc -z 127.0.0.1 "$UART_TERM_PORT" 2>/dev/null; do
    TRIES=$((TRIES + 1))
    if [[ "$TRIES" -ge 60 ]]; then
        err "UART terminal port did not open. Server log:"
        cat "$SERVER_LOG" >&2 || true
        exit 1
    fi
    sleep 0.2
done
nc 127.0.0.1 "$UART_TERM_PORT" > "$UART_LOG" 2>/dev/null &
UART_PID=$!

info "Starting QEMU..."
[[ -n "$ICOUNT_OPTS" ]] && info "icount mode: $ICOUNT_OPTS"
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
    -chardev socket,id=display_rw,host=127.0.0.1,port=7919 \
    -chardev socket,id=display_irq,host=127.0.0.1,port=7920 \
    -device mmio-sockdev,chardev=display_rw,irq-chardev=display_irq,addr=0x40011000,irq-num=9 \
    -kernel "$FIRMWARE_HEX" \
    </dev/null > "$QEMU_LOG" 2>&1 &
QEMU_PID=$!

touch "$UART_LOG"
tail -n +1 -F "$UART_LOG" &
TAIL_PID=$!

info "Waiting for firmware menu, then injecting display command '$DISPLAY_CMD'..."
TRIES=0
while ! grep -q "KX6625 Test Menu" "$SERVER_LOG" 2>/dev/null; do
    TRIES=$((TRIES + 1))
    if [[ "$TRIES" -ge "$DISPLAY_VALIDATE_TRIES" ]]; then
        err "Firmware menu not seen. QEMU log:"
        cat "$QEMU_LOG" >&2 || true
        exit 1
    fi
    sleep 0.25
done

printf '%s\n' "$DISPLAY_CMD" | nc -q1 127.0.0.1 "$UART_TERM_PORT" 2>/dev/null || true
ok "Display command injected."

TRIES=0
while ! grep -Fq "$DISPLAY_EXPECT" "$SERVER_LOG" 2>/dev/null; do
    TRIES=$((TRIES + 1))
    if [[ "$TRIES" -ge 120 ]]; then
        err "Display validation did not complete. Server log:"
        tail -n 160 "$SERVER_LOG" >&2 || true
        exit 1
    fi
    sleep 0.25
done

ok "Display path validation passed. Inspect the KX6625 Display window."
info "UART log   : $UART_LOG"
info "Server log : $SERVER_LOG"
info "QEMU log   : $QEMU_LOG"
if [[ "$DISPLAY_KEEPALIVE" != "1" ]]; then
    ok "DISPLAY_KEEPALIVE=0; stopping after validation."
    exit 0
fi
info "Press Ctrl-C to stop the session."

while true; do
    if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        warn "QEMU exited; stopping session."
        exit 0
    fi
    sleep 1
done