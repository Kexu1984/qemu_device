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
#
# Requirements:
#   - xterm (preferred), or gnome-terminal / konsole / xfce4-terminal / lxterminal
#   - The firmware must already be built: make (in firmware/)
#   - The QEMU fork must already be built: bash scripts/build_qemu.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

QEMU_BIN="$PROJECT_ROOT/scripts/qemu-fork/build/qemu-system-arm"
FIRMWARE_BIN="$PROJECT_ROOT/build/firmware.bin"
SERVER_SCRIPT="$PROJECT_ROOT/device_model/mmio_device_server.py"
CONSOLE_SCRIPT="$PROJECT_ROOT/scripts/uart_console.py"

UART_TERM_PORT=7904
RW_PORT=7890
IRQ_PORT=7891
IRQ_DELAY=2

LOG_DIR="$PROJECT_ROOT/build"
SERVER_LOG="$LOG_DIR/interactive_server.log"
QEMU_LOG="$LOG_DIR/interactive_qemu.log"

# Colours for this script's own messages
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[demo]${NC} $*"; }
ok()    { echo -e "${GREEN}[demo]${NC} $*"; }
warn()  { echo -e "${YELLOW}[demo]${NC} $*"; }
err()   { echo -e "${RED}[demo]${NC} $*" >&2; }

# ── Sanity checks ──────────────────────────────────────────────────────────────
for f in "$QEMU_BIN" "$FIRMWARE_BIN" "$SERVER_SCRIPT" "$CONSOLE_SCRIPT"; do
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
    warn "No graphical terminal found — running uart_console.py inline."
    warn "Press Ctrl-C to stop the simulation."
    python3 "$CONSOLE_SCRIPT" 127.0.0.1 "$UART_TERM_PORT" &
    TERM_PID=$!
}

if   command -v xterm          &>/dev/null; then TERM_OPEN=_open_xterm
elif command -v xfce4-terminal &>/dev/null; then TERM_OPEN=_open_xfce4
elif command -v lxterminal     &>/dev/null; then TERM_OPEN=_open_lxterminal
elif command -v konsole        &>/dev/null; then TERM_OPEN=_open_konsole
elif command -v gnome-terminal &>/dev/null; then TERM_OPEN=_open_gnome
else                                             TERM_OPEN=_open_inline
fi

# ── Cleanup ────────────────────────────────────────────────────────────────────
QEMU_PID=""
SERVER_PID=""
TERM_PID=""

cleanup() {
    echo ""
    info "Shutting down simulation..."
    [[ -n "${TERM_PID:-}"   ]] && kill "$TERM_PID"   2>/dev/null || true
    [[ -n "${QEMU_PID:-}"   ]] && kill "$QEMU_PID"   2>/dev/null || true
    [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    ok "All processes stopped."
}
trap cleanup EXIT INT TERM

# ── Release ports from any previous run ───────────────────────────────────────
info "Releasing ports from any previous run..."
for PORT in 7890 7891 7892 7893 7894 7895 7896 7897 7898 7899 7900 7901 7902 7903 7904 7905; do
    fuser -k "${PORT}/tcp" 2>/dev/null || true
done
sleep 0.3

mkdir -p "$LOG_DIR"

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
    -chardev socket,id=dma_tick,host=127.0.0.1,port=7905 \
    -device mmio-sockdev,chardev=dma_rw,irq-chardev=dma_irq,mem-chardev=dma_mem,tick-chardev=dma_tick,tick-period-ms=0,addr=0x40005000,irq-num=1 \
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
    -kernel "${FIRMWARE_BIN%.bin}.elf" \
    </dev/null > "$QEMU_LOG" 2>&1 &
QEMU_PID=$!
info "QEMU PID $QEMU_PID  →  $QEMU_LOG"

echo ""
ok "Simulation running."
info "  UART output  : xterm window (port $UART_TERM_PORT)"
info "  Server log   : $SERVER_LOG"
info "  QEMU log     : $QEMU_LOG"
echo ""
info "Close the UART terminal window to stop the simulation."
echo ""

# ── 4. Wait for the terminal window to be closed ──────────────────────────────
# This is the main blocking wait.  When the user closes xterm, TERM_PID exits
# and this wait returns, triggering the cleanup trap.
wait "$TERM_PID" 2>/dev/null || true
TERM_PID=""   # already gone; don't kill again in cleanup
info "Terminal window closed — stopping simulation."
