# =============================================================================
# AUTO-GENERATED — do not edit by hand.
# Source: spec/devices.yaml
# Regenerate: make gen   (or: python3 scripts/gen_device_code.py)
# =============================================================================
# Python constants mirroring the C header mmio_devices.h.
# Import in scripts or tests that need symbolic device constants:
#
#     from device_model.generated.device_consts import CONSOLE_UART_BASE
# ── CONSOLE_UART ────────────────────────────────────────────────
# Console UART — byte-at-a-time character output + one-shot IRQ
CONSOLE_UART_BASE         = 0x40004000
CONSOLE_UART_SIZE         = 0x1000
CONSOLE_UART_IRQ_INTID    = 0
CONSOLE_UART_IRQ_DELAY_S  = 2.0
CONSOLE_UART_RW_PORT      = 7890
CONSOLE_UART_IRQ_PORT     = 7891

# Registers
CONSOLE_UART_TXDATA_REG                  = 0x40004000  # offset 0x0000  W  Transmit data byte (low 8 bits → stdout)
CONSOLE_UART_STATUS_REG                  = 0x40004004  # offset 0x0004  R  Status: bit0=TXREADY (always 1)
CONSOLE_UART_CTRL_REG                    = 0x40004008  # offset 0x0008  RW  Control: bit0=ENABLE

# ── DMA ─────────────────────────────────────────────────────────
# Simple DMA controller
DMA_BASE         = 0x40005000
DMA_SIZE         = 0x1000
DMA_IRQ_INTID    = 1
DMA_IRQ_DELAY_S  = 0.0
DMA_RW_PORT      = 7892
DMA_IRQ_PORT     = 7893

# Registers
DMA_CH0_SRC_ADDR_REG                     = 0x40005000  # offset 0x0000  RW  CH0 DMA source address
DMA_CH0_DST_ADDR_REG                     = 0x40005004  # offset 0x0004  RW  CH0 DMA destination address
DMA_CH0_LENGTH_REG                       = 0x40005008  # offset 0x0008  RW  CH0 transfer length in bytes
DMA_CH0_CTRL_REG                         = 0x4000500C  # offset 0x000C  RW  CH0 control: bit0=START, bit1=ENABLE
DMA_CH0_STATUS_REG                       = 0x40005010  # offset 0x0010  R  CH0 status: bit0=BUSY, bit1=DONE
DMA_CH1_SRC_ADDR_REG                     = 0x40005020  # offset 0x0020  RW  CH1 DMA source address
DMA_CH1_DST_ADDR_REG                     = 0x40005024  # offset 0x0024  RW  CH1 DMA destination address
DMA_CH1_LENGTH_REG                       = 0x40005028  # offset 0x0028  RW  CH1 transfer length in bytes
DMA_CH1_CTRL_REG                         = 0x4000502C  # offset 0x002C  RW  CH1 control: bit0=START, bit1=ENABLE
DMA_CH1_STATUS_REG                       = 0x40005030  # offset 0x0030  R  CH1 status: bit0=BUSY, bit1=DONE

# ── TIMER0 ──────────────────────────────────────────────────────
# Countdown timer — one-shot and periodic modes, ms resolution
TIMER0_BASE         = 0x40006000
TIMER0_SIZE         = 0x1000
TIMER0_IRQ_INTID    = 2
TIMER0_IRQ_DELAY_S  = 0.0
TIMER0_RW_PORT      = 7894
TIMER0_IRQ_PORT     = 7895

# Registers
TIMER0_LOAD_REG                          = 0x40006000  # offset 0x0000  RW  Countdown load value in milliseconds (0 = no-op)
TIMER0_VALUE_REG                         = 0x40006004  # offset 0x0004  R  Remaining time in milliseconds (approximate, wall-clock)
TIMER0_CTRL_REG                          = 0x40006008  # offset 0x0008  RW  Control: bit0=ENABLE, bit1=PERIODIC, bit2=INT_ENABLE
TIMER0_STATUS_REG                        = 0x4000600C  # offset 0x000C  R  Status: bit0=INT_PENDING (set on expiry, cleared by INTCLR)
TIMER0_INTCLR_REG                        = 0x40006010  # offset 0x0010  W  Write any value to clear INT_PENDING and deassert IRQ

# ── DMA_CLIENT_DEMO ─────────────────────────────────────────────
# DMA client demo peripheral — uses DmaClientHandle (DREQ/DACK interface)
DMA_CLIENT_DEMO_BASE         = 0x40007000
DMA_CLIENT_DEMO_SIZE         = 0x1000
DMA_CLIENT_DEMO_IRQ_INTID    = 3
DMA_CLIENT_DEMO_IRQ_DELAY_S  = 0.0
DMA_CLIENT_DEMO_RW_PORT      = 7898
DMA_CLIENT_DEMO_IRQ_PORT     = 7899

# Registers
DMA_CLIENT_DEMO_SRC_ADDR_REG             = 0x40007000  # offset 0x0000  RW  DMA source address
DMA_CLIENT_DEMO_DST_ADDR_REG             = 0x40007004  # offset 0x0004  RW  DMA destination address
DMA_CLIENT_DEMO_LENGTH_REG               = 0x40007008  # offset 0x0008  RW  Transfer length in bytes
DMA_CLIENT_DEMO_CTRL_REG                 = 0x4000700C  # offset 0x000C  RW  Control: bit0=START (write 1 to kick off transfer)
DMA_CLIENT_DEMO_STATUS_REG               = 0x40007010  # offset 0x0010  R  Status: bit0=BUSY, bit1=DONE

# ── SRAM memory region ────────────────────────────────────────────────────────
# Scratchpad SRAM for device DMA transfers
SRAM_BASE         = 0x20000000
SRAM_SIZE         = 0x00020000

