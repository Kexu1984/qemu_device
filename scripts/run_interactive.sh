#!/bin/bash
#
# run_interactive.sh — Interactive firmware simulation with UART terminal window
#
# Starts the Python device server and QEMU, then opens a dedicated terminal
# window showing the firmware UART output in real-time.  The simulation runs
# until you close the terminal window, at which point everything is shut down.
#
# Usage:
#   bash scripts/run_interactive.sh
#   RUN_INLINE=1 bash scripts/run_interactive.sh   # use current terminal
#
# Requirements:
#   - xterm (preferred), or gnome-terminal / konsole / xfce4-terminal / lxterminal
#   - The firmware must already be built: make (in firmware/)
#   - The QEMU fork must already be built: bash scripts/build_qemu.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

QEMU_BIN="$PROJECT_ROOT/scripts/qemu-fork/build/qemu-system-arm"
FIRMWARE_HEX="$PROJECT_ROOT/build/firmware.hex"
SERVER_SCRIPT="$PROJECT_ROOT/device_model/mmio_device_server.py"
CONSOLE_SCRIPT="$PROJECT_ROOT/scripts/uart_console.py"
SV_BRIDGE="$PROJECT_ROOT/sv_device/build/sv_timer_bridge"
SECBOOT_SCRIPT="$PROJECT_ROOT/scripts/secure_boot_otp.py"

UART_TERM_PORT=7904
RW_PORT=7890
IRQ_PORT=7891
IRQ_DELAY=2

# Optional: ICOUNT_SHIFT=N enables icount mode (-icount shift=N,sleep=off,align=off)
ICOUNT_SHIFT="${ICOUNT_SHIFT:-}"
if [ -n "$ICOUNT_SHIFT" ]; then
    ICOUNT_OPTS="-icount shift=${ICOUNT_SHIFT},sleep=off,align=off"
else
    ICOUNT_OPTS=""
fi

# Optional: RUN_INLINE=1 keeps the UART console in the current terminal.
# This is useful in VS Code/SSH sessions where a spawned xterm can be hidden.
RUN_INLINE="${RUN_INLINE:-0}"

LOG_DIR="$PROJECT_ROOT/build"
SERVER_LOG="$LOG_DIR/interactive_server.log"
QEMU_LOG="$LOG_DIR/interactive_qemu.log"
SV_LOG="$LOG_DIR/interactive_sv_timer.log"
SV_WAVE="$LOG_DIR/interactive_sv_timer.vcd"
QEMU_PID_FILE="$LOG_DIR/interactive_qemu.pid"

# Colours for this script's own messages
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[demo]${NC} $*"; }
ok()    { echo -e "${GREEN}[demo]${NC} $*"; }
warn()  { echo -e "${YELLOW}[demo]${NC} $*"; }
err()   { echo -e "${RED}[demo]${NC} $*" >&2; }

# ── Sanity checks ──────────────────────────────────────────────────────────────
for f in "$QEMU_BIN" "$FIRMWARE_HEX" "$SERVER_SCRIPT" "$CONSOLE_SCRIPT" "$SV_BRIDGE" "$SECBOOT_SCRIPT"; do
    if [[ ! -f "$f" ]]; then
        err "Required file not found: $f"
        exit 1
    fi
done

# ── Find a terminal emulator ───────────────────────────────────────────────────
# We need one whose process stays alive until the window is closed so we can
# wait on it.  Priority: xterm > xfce4-terminal > lxterminal > konsole >
# gnome-terminal (--wait).  Falls back to running inline (no GUI).
TERM_CMD=""
TERM_OPEN=""   # function name that actually opens the window

_open_xterm() {
    xterm \
        -title "KX6625 UART Console" \
        -fa "Monospace" -fs 11 \
        -bg black -fg "#00ff88" \
        -geometry 100x30 \
        -e python3 "$CONSOLE_SCRIPT" 127.0.0.1 "$UART_TERM_PORT" &
    TERM_PID=$!
}

_open_xfce4() {
    xfce4-terminal \
        --title="KX6625 UART Console" \
        --geometry=100x30 \
        --command="python3 $CONSOLE_SCRIPT 127.0.0.1 $UART_TERM_PORT" &
    TERM_PID=$!
}

_open_lxterminal() {
    lxterminal \
        --title="KX6625 UART Console" \
        --geometry=100x30 \
        -e "python3 $CONSOLE_SCRIPT 127.0.0.1 $UART_TERM_PORT" &
    TERM_PID=$!
}

_open_konsole() {
    konsole \
        --title "KX6625 UART Console" \
        --noclose \
        -e python3 "$CONSOLE_SCRIPT" 127.0.0.1 "$UART_TERM_PORT" &
    TERM_PID=$!
}

_open_gnome() {
    # --wait makes gnome-terminal block until the window is closed
    gnome-terminal \
        --title="KX6625 UART Console" \
        --geometry=100x30 \
        --wait \
        -- python3 "$CONSOLE_SCRIPT" 127.0.0.1 "$UART_TERM_PORT" &
    TERM_PID=$!
}

_open_inline() {
    if [[ "$RUN_INLINE" == "1" ]]; then
        warn "Inline mode requested — running uart_console.py in this terminal."
    else
        warn "No graphical terminal found — running uart_console.py in this terminal."
    fi
    warn "Press Ctrl-C or Ctrl-] to disconnect and stop the simulation."
    INLINE_MODE=1
    TERM_PID=0   # no background PID; foreground run happens at end of script
}

if [[ "$RUN_INLINE" == "1" ]]; then
    TERM_OPEN=_open_inline
elif command -v xterm          &>/dev/null; then TERM_OPEN=_open_xterm
elif command -v xfce4-terminal &>/dev/null; then TERM_OPEN=_open_xfce4
elif command -v lxterminal     &>/dev/null; then TERM_OPEN=_open_lxterminal
elif command -v konsole        &>/dev/null; then TERM_OPEN=_open_konsole
elif command -v gnome-terminal &>/dev/null; then TERM_OPEN=_open_gnome
else                                             TERM_OPEN=_open_inline
fi

# ── Cleanup ────────────────────────────────────────────────────────────────────
QEMU_PID=""
SERVER_PID=""
SV_PID=""
TERM_PID=""
QEMU_LAUNCHER_PID=""
INLINE_MODE=0
CLEANED_UP=0

cleanup() {
    [[ "$CLEANED_UP" -eq 1 ]] && return
    CLEANED_UP=1

    echo ""
    info "Shutting down simulation..."
    [[ "${TERM_PID:-0}" -gt 0 ]] && kill "$TERM_PID"   2>/dev/null || true
    [[ -n "${QEMU_LAUNCHER_PID:-}" ]] && kill "$QEMU_LAUNCHER_PID" 2>/dev/null || true
    if [[ -z "${QEMU_PID:-}" && -f "$QEMU_PID_FILE" ]]; then
        QEMU_PID="$(cat "$QEMU_PID_FILE" 2>/dev/null || true)"
    fi
    [[ -n "${QEMU_PID:-}"      ]] && kill "$QEMU_PID"   2>/dev/null || true
    [[ -n "${SERVER_PID:-}"    ]] && kill "$SERVER_PID" 2>/dev/null || true
    [[ -n "${SV_PID:-}"        ]] && kill "$SV_PID"     2>/dev/null || true
    rm -f "$QEMU_PID_FILE"
    wait 2>/dev/null || true
    ok "All processes stopped."
}
trap cleanup EXIT INT TERM

# ── Release ports from any previous run ───────────────────────────────────────
info "Releasing ports from any previous run..."
for PORT in 7890 7891 7892 7893 7894 7895 7896 7897 7898 7899 7900 7901 7902 7903 7904 7905 7906 7907 7908 7909 7910 7911 7912 7913 7914 7915 7916; do
    fuser -k "${PORT}/tcp" 2>/dev/null || true
done
sleep 0.3

mkdir -p "$LOG_DIR"
rm -f "$QEMU_PID_FILE" "$SV_WAVE"

info "Installing secure boot OTP metadata..."
python3 "$SECBOOT_SCRIPT" --firmware-hex "$FIRMWARE_HEX" --otp "$LOG_DIR/otp.hex" --fresh

start_qemu() {
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
        -chardev socket,id=sv_timer_rw,host=127.0.0.1,port=7906 \
        -chardev socket,id=sv_timer_irq,host=127.0.0.1,port=7907 \
        -chardev socket,id=sv_timer_mem,host=127.0.0.1,port=7912 \
        -device mmio-sockdev,chardev=sv_timer_rw,irq-chardev=sv_timer_irq,fabric-chardev=sv_timer_mem,addr=0x4000B000,irq-num=5 \
        -chardev socket,id=hsm_rw,host=127.0.0.1,port=7908 \
        -chardev socket,id=hsm_irq,host=127.0.0.1,port=7909 \
        -device mmio-sockdev,chardev=hsm_rw,irq-chardev=hsm_irq,addr=0x4000C000,irq-num=6 \
        -chardev socket,id=otp_rw,host=127.0.0.1,port=7910 \
        -chardev socket,id=otp_irq,host=127.0.0.1,port=7911 \
        -device mmio-sockdev,chardev=otp_rw,irq-chardev=otp_irq,addr=0x4000D000,irq-num=7 \
        -chardev socket,id=flash_ctrl_rw,host=127.0.0.1,port=7913 \
        -chardev socket,id=flash_ctrl_irq,host=127.0.0.1,port=7914 \
        -chardev socket,id=flash_ctrl_mem,host=127.0.0.1,port=7915 \
        -device mmio-sockdev,chardev=flash_ctrl_rw,irq-chardev=flash_ctrl_irq,fabric-chardev=flash_ctrl_mem,addr=0x4000E000,irq-num=8 \
        -chardev socket,id=dflash_rw,host=127.0.0.1,port=7916 \
        -device mmio-sockdev,chardev=dflash_rw,addr=0x10000000,size=0x80000 \
        -kernel "$FIRMWARE_HEX" \
        </dev/null > "$QEMU_LOG" 2>&1 &
    QEMU_PID=$!
    echo "$QEMU_PID" > "$QEMU_PID_FILE"
    info "QEMU PID $QEMU_PID  →  $QEMU_LOG"
}

# ── 1. Start Python device server ─────────────────────────────────────────────
info "Starting Python device server..."
python3 "$SERVER_SCRIPT" \
    --port         "$RW_PORT" \
    --irq-port     "$IRQ_PORT" \
    --irq-delay    "$IRQ_DELAY" \
    > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
info "Server PID $SERVER_PID  →  $SERVER_LOG"

# Wait until RW port is ready
TRIES=0
while true; do
    if nc -z 127.0.0.1 "$RW_PORT" 2>/dev/null; then break; fi
    TRIES=$((TRIES + 1))
    if [[ $TRIES -ge 40 ]]; then
        err "Device server did not come up after 8s:"
        cat "$SERVER_LOG"
        exit 1
    fi
    sleep 0.2
done
ok "Device server ready."

# ── 1b. Start SystemVerilog/Verilator timer bridge ──────────────────────────
info "Starting SV peripheral bridge..."
"$SV_BRIDGE" --rw-port 7906 --irq-port 7907 --mem-port 7912 --wave-file "$SV_WAVE" > "$SV_LOG" 2>&1 &
SV_PID=$!
info "SV timer PID $SV_PID  →  $SV_LOG"
info "SV wave      →  $SV_WAVE"
sleep 0.5

# ── 2. Open UART terminal window ───────────────────────────────────────────────
info "Opening UART terminal window (${TERM_OPEN#_open_})..."
# Wait for UART terminal port to be ready before launching the window
TRIES=0
while true; do
    if nc -z 127.0.0.1 "$UART_TERM_PORT" 2>/dev/null; then break; fi
    TRIES=$((TRIES + 1))
    if [[ $TRIES -ge 40 ]]; then
        err "UART terminal port $UART_TERM_PORT not ready after 8s."
        exit 1
    fi
    sleep 0.2
done

$TERM_OPEN   # sets TERM_PID
ok "Terminal window PID $TERM_PID"

# ── 3. Start QEMU ─────────────────────────────────────────────────────────────
if [[ "$INLINE_MODE" -eq 1 ]]; then
    # Let uart_console.py connect first so the boot banner and menu prompt are
    # visible in the current terminal.  The launcher writes QEMU_PID_FILE for
    # cleanup because it runs in a subshell.
    (sleep 0.5; start_qemu) &
    QEMU_LAUNCHER_PID=$!
else
    start_qemu
fi

echo ""
ok "Simulation running."
if [[ "$INLINE_MODE" -eq 1 ]]; then
    info "  UART output  : current terminal (port $UART_TERM_PORT)"
else
    info "  UART output  : ${TERM_OPEN#_open_} window (port $UART_TERM_PORT)"
fi
info "  Server log   : $SERVER_LOG"
info "  SV timer log : $SV_LOG"
info "  SV wave dump : $SV_WAVE"
info "  QEMU log     : $QEMU_LOG"
echo ""
if [[ "$INLINE_MODE" -eq 1 ]]; then
    info "Press Ctrl-C or Ctrl-] in the UART console to stop the simulation."
else
    info "Close the UART terminal window to stop the simulation."
fi
echo ""

# ── 4. Wait for the terminal window to be closed (or run inline) ─────────────
if [[ "$INLINE_MODE" -eq 1 ]]; then
    # Foreground: uart_console.py takes over this terminal.
    # Ctrl-C or Ctrl-] exits it, then cleanup trap fires.
    python3 "$CONSOLE_SCRIPT" 127.0.0.1 "$UART_TERM_PORT" || true
    TERM_PID=0
    info "Console session ended — stopping simulation."
else
    # GUI: block until the user closes the terminal window.
    wait "$TERM_PID" 2>/dev/null || true
    TERM_PID=""   # already gone; don't kill again in cleanup
    info "Terminal window closed — stopping simulation."
fi
