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
CONSOLE_UART_IRQ_PORT     = 7891
CONSOLE_UART_RW_PORT      = 7890

# Registers
CONSOLE_UART_TXDATA_REG                  = 0x40004000  # offset 0x0000  W  Transmit data byte (low 8 bits → stdout)
CONSOLE_UART_STATUS_REG                  = 0x40004004  # offset 0x0004  R  Status: bit0=TXREADY (always 1), bit1=RXREADY (1 if RX FIFO non-empty)
CONSOLE_UART_CTRL_REG                    = 0x40004008  # offset 0x0008  RW  Control: bit0=ENABLE, bit1=RX_IRQ_EN (IRQ on RX data available)
CONSOLE_UART_RXDATA_REG                  = 0x4000400C  # offset 0x000C  R  Receive data byte (low 8 bits); reads 0x00 when FIFO empty

# ── DMA ─────────────────────────────────────────────────────────
# Simple DMA controller
DMA_BASE         = 0x40005000
DMA_SIZE         = 0x1000
DMA_IRQ_INTID    = 1
DMA_IRQ_DELAY_S  = 0.0
DMA_IRQ_PORT     = 7893
DMA_RW_PORT      = 7892

# Registers
DMA_CH0_SRC_ADDR_REG                     = 0x40005000  # offset 0x0000  RW  CH0 DMA source address
DMA_CH0_DST_ADDR_REG                     = 0x40005004  # offset 0x0004  RW  CH0 DMA destination address
DMA_CH0_LENGTH_REG                       = 0x40005008  # offset 0x0008  RW  CH0 transfer length in bytes
DMA_CH0_CTRL_REG                         = 0x4000500C  # offset 0x000C  RW  CH0 control: bit0=START, bit1=ENABLE
DMA_CH0_STATUS_REG                       = 0x40005010  # offset 0x0010  R  CH0 status: bit0=BUSY, bit1=DONE
DMA_CH0_SRC_MODE_REG                     = 0x40005014  # offset 0x0014  RW  CH0 source address mode: bit0=FIXED (0=increment after each byte, 1=hold fixed — P2x transfer)
DMA_CH0_DST_MODE_REG                     = 0x40005018  # offset 0x0018  RW  CH0 destination address mode: bit0=FIXED (0=increment after each byte, 1=hold fixed — xP transfer)
DMA_CH1_SRC_ADDR_REG                     = 0x40005020  # offset 0x0020  RW  CH1 DMA source address
DMA_CH1_DST_ADDR_REG                     = 0x40005024  # offset 0x0024  RW  CH1 DMA destination address
DMA_CH1_LENGTH_REG                       = 0x40005028  # offset 0x0028  RW  CH1 transfer length in bytes
DMA_CH1_CTRL_REG                         = 0x4000502C  # offset 0x002C  RW  CH1 control: bit0=START, bit1=ENABLE
DMA_CH1_STATUS_REG                       = 0x40005030  # offset 0x0030  R  CH1 status: bit0=BUSY, bit1=DONE
DMA_CH1_SRC_MODE_REG                     = 0x40005034  # offset 0x0034  RW  CH1 source address mode: bit0=FIXED (0=increment after each byte, 1=hold fixed — P2x transfer)
DMA_CH1_DST_MODE_REG                     = 0x40005038  # offset 0x0038  RW  CH1 destination address mode: bit0=FIXED (0=increment after each byte, 1=hold fixed — xP transfer)

# ── TIMER0 ──────────────────────────────────────────────────────
# Countdown timer — one-shot and periodic modes, ms resolution
TIMER0_BASE         = 0x40006000
TIMER0_SIZE         = 0x1000
TIMER0_IRQ_INTID    = 2
TIMER0_IRQ_DELAY_S  = 0.0
TIMER0_IRQ_PORT     = 7895
TIMER0_RW_PORT      = 7894

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
DMA_CLIENT_DEMO_IRQ_PORT     = 7899
DMA_CLIENT_DEMO_RW_PORT      = 7898

# Registers
DMA_CLIENT_DEMO_SRC_ADDR_REG             = 0x40007000  # offset 0x0000  RW  DMA source address
DMA_CLIENT_DEMO_DST_ADDR_REG             = 0x40007004  # offset 0x0004  RW  DMA destination address
DMA_CLIENT_DEMO_LENGTH_REG               = 0x40007008  # offset 0x0008  RW  Transfer length in bytes
DMA_CLIENT_DEMO_CTRL_REG                 = 0x4000700C  # offset 0x000C  RW  Control: bit0=START (write 1 to kick off transfer)
DMA_CLIENT_DEMO_STATUS_REG               = 0x40007010  # offset 0x0010  R  Status: bit0=BUSY, bit1=DONE

# ── CRC ─────────────────────────────────────────────────────────
# CRC-32 hardware accelerator (ISO-HDLC / IEEE 802.3 polynomial)
CRC_BASE         = 0x40008000
CRC_SIZE         = 0x1000
CRC_RW_PORT      = 7900

# Registers
CRC_DATA_REG                             = 0x40008000  # offset 0x0000  RW  Write: feed one or more bytes into the CRC-32 accumulator. Byte writes (size=1) feed exactly one byte. Word writes (size=4) feed four bytes in little-endian order. Read: returns the current raw accumulator value (before final XOR).

CRC_RESULT_REG                           = 0x40008004  # offset 0x0004  R  Current CRC-32 result with final XOR applied: RESULT = accumulator ^ 0xFFFFFFFF. Read this register after feeding all data bytes to obtain the CRC.

CRC_CTRL_REG                             = 0x40008008  # offset 0x0008  RW  Control register. bit0 = RESET — write 1 to clear the accumulator back to 0xFFFFFFFF. Writing 0 has no effect.  The bit reads back as 0.


# ── WDT ─────────────────────────────────────────────────────────
# Watchdog timer — countdown reset with retention registers (RESET_REASON, TIMEOUT_CNT)
WDT_BASE         = 0x40009000
WDT_SIZE         = 0x1000
WDT_IRQ_INTID    = 4
WDT_IRQ_DELAY_S  = 0.0
WDT_IRQ_PORT     = 7902
WDT_RW_PORT      = 7901

# Registers
WDT_LOAD_REG                             = 0x40009000  # offset 0x0000  RW  Timeout load value in milliseconds (0 = no-op)
WDT_VALUE_REG                            = 0x40009004  # offset 0x0004  R  Remaining time in ms (virtual-clock based)
WDT_CTRL_REG                             = 0x40009008  # offset 0x0008  RW  Control: bit0=ENABLE, bit1=INT_ENABLE (IRQ before reset)
WDT_KICK_REG                             = 0x4000900C  # offset 0x000C  W  Write any value to reload countdown and clear STATUS.TIMEOUT
WDT_STATUS_REG                           = 0x40009010  # offset 0x0010  R  Status: bit0=TIMEOUT (set on expiry)
WDT_RESET_REASON_REG                     = 0x40009014  # offset 0x0014  R  Retention: 0=POR/global-reset  1=WDT-reset. Survives watchdog reset.
WDT_TIMEOUT_CNT_REG                      = 0x40009018  # offset 0x0018  R  Retention: cumulative WDT timeout count since power-on.

# ── SV_TIMER ────────────────────────────────────────────────────
# SystemVerilog APB timer prototype — Verilator-backed external model
SV_TIMER_BASE         = 0x4000B000
SV_TIMER_SIZE         = 0x1000
SV_TIMER_IRQ_INTID    = 5
SV_TIMER_IRQ_DELAY_S  = 0.0
SV_TIMER_IRQ_PORT     = 7907
SV_TIMER_RW_PORT      = 7906

# Registers
SV_TIMER_CTRL_REG                        = 0x4000B000  # offset 0x0000  RW  Control: bit0=ENABLE, bit1=IRQ_EN
SV_TIMER_LOAD_REG                        = 0x4000B004  # offset 0x0004  RW  Countdown load value in SV clock cycles
SV_TIMER_VALUE_REG                       = 0x4000B008  # offset 0x0008  R  Current countdown value
SV_TIMER_STATUS_REG                      = 0x4000B00C  # offset 0x000C  R  Status: bit0=IRQ_PENDING
SV_TIMER_IRQ_CLEAR_REG                   = 0x4000B010  # offset 0x0010  W  Write bit0=1 to clear IRQ_PENDING and deassert IRQ

# ── HSM ─────────────────────────────────────────────────────────
# HSM crypto accelerator — AES-128 ECB/CBC/CFB/CTR/CMAC with OTP KEY_ID or open-register key source
HSM_BASE         = 0x4000C000
HSM_SIZE         = 0x1000
HSM_IRQ_INTID    = 6
HSM_IRQ_DELAY_S  = 0.0
HSM_IRQ_PORT     = 7909
HSM_RW_PORT      = 7908

# Registers
HSM_ID_REG                               = 0x4000C000  # offset 0x0000  R  Device ID: ASCII 'HSM1' encoded little-endian
HSM_VERSION_REG                          = 0x4000C004  # offset 0x0004  R  Model version: major.minor encoded as 0x00010000 for v1.0
HSM_CTRL_REG                             = 0x4000C008  # offset 0x0008  RW  Control register. bit0 = START (write 1 to start operation, self-clears); bit1 = IRQ_ENABLE; other bits reserved. Device reset is intentionally not exposed here; future CRU support should manage HSM reset/clock.

HSM_STATUS_REG                           = 0x4000C00C  # offset 0x000C  R  Status register. bit0 = BUSY; bit1 = DONE; bit2 = ERROR; bit3 = IRQ_PENDING; bit4 = KEY_VALID; bit5 = OTP_KEY_LOADED; bit6 = ACCESS_ERR (sticky illegal master access; cleared only by HSM reset).

HSM_INT_STATUS_REG                       = 0x4000C010  # offset 0x0010  RW  Interrupt/status latch, W1C in the Python model. bit0 = DONE_IRQ; bit1 = ERROR_IRQ; bit2 = ACCESS_ERR_IRQ. Clearing ACCESS_ERR_IRQ does not clear STATUS.ACCESS_ERR; that sticky state requires HSM reset.

HSM_INT_ENABLE_REG                       = 0x4000C014  # offset 0x0014  RW  Interrupt enable mask. bit0 enables DONE interrupt; bit1 enables ERROR interrupt; bit2 enables ACCESS_ERR interrupt.

HSM_ERROR_REG                            = 0x4000C018  # offset 0x0018  R  Last error code. 0=NONE; 1=ACCESS_DENIED; 2=INVALID_MODE; 3=INVALID_LENGTH; 4=KEY_NOT_VALID; 5=OTP_FILE_ERROR; 6=OTP_SLOT_INVALID; 7=DMA_READ_ERROR; 8=DMA_WRITE_ERROR; 9=DST_BUS_ERROR.

HSM_MODE_REG                             = 0x4000C01C  # offset 0x001C  RW  Crypto mode selection. bits[3:0] = MODE: 0=AES_ECB, 1=AES_CBC, 2=AES_CFB, 3=AES_CTR, 4=AES_CMAC; bit8 = DECRYPT (0=encrypt/compute, 1=decrypt; ignored for CMAC and CTR).

HSM_SRC_ADDR_REG                         = 0x4000C020  # offset 0x0020  RW  Source physical address for DMA input buffer (FLASH or SRAM)
HSM_DST_ADDR_REG                         = 0x4000C024  # offset 0x0024  RW  Destination physical address for DMA output buffer/tag. Expected to point to writable memory such as SRAM; writes to read-only FLASH should surface as a DMA/memory bus error.

HSM_LENGTH_REG                           = 0x4000C028  # offset 0x0028  RW  Input length in bytes. ECB/CBC require a non-zero multiple of 16. CFB/CTR/CMAC accept any non-zero byte length. CMAC produces a 16-byte output tag regardless of input length.

HSM_DMA_STATUS_REG                       = 0x4000C02C  # offset 0x002C  R  DMA/client phase status. bit0 = DMA_READ_BUSY; bit1 = DMA_READ_DONE; bit2 = DMA_WRITE_BUSY; bit3 = DMA_WRITE_DONE; bit4 = DMA_ERROR.

HSM_KEY_ID_REG                           = 0x4000C030  # offset 0x0030  RW  Active key selector. values 0..14 select OTP key slots 0..14; value 15 selects the open KEY_WORD0..3 register key. Other values are invalid and should latch ERROR.OTP_SLOT_INVALID.

HSM_KEY_STATUS_REG                       = 0x4000C034  # offset 0x0034  R  Key status. bit0 = REG_KEY_WRITTEN; bit1 = OTP_KEY_AVAILABLE; bit2 = ACTIVE_KEY_VALID; bits[15:8] = active KEY_ID.

HSM_KEY_WORD0_REG                        = 0x4000C038  # offset 0x0038  W  Open key register word 0, bits [31:0] of AES-128 key; CPU reads return 0
HSM_KEY_WORD1_REG                        = 0x4000C03C  # offset 0x003C  W  Open key register word 1, bits [63:32] of AES-128 key; CPU reads return 0
HSM_KEY_WORD2_REG                        = 0x4000C040  # offset 0x0040  W  Open key register word 2, bits [95:64] of AES-128 key; CPU reads return 0
HSM_KEY_WORD3_REG                        = 0x4000C044  # offset 0x0044  W  Open key register word 3, bits [127:96] of AES-128 key; CPU reads return 0
HSM_IV_WORD0_REG                         = 0x4000C050  # offset 0x0050  RW  IV/counter word 0, bits [31:0], used by CBC/CFB/CTR
HSM_IV_WORD1_REG                         = 0x4000C054  # offset 0x0054  RW  IV/counter word 1, bits [63:32], used by CBC/CFB/CTR
HSM_IV_WORD2_REG                         = 0x4000C058  # offset 0x0058  RW  IV/counter word 2, bits [95:64], used by CBC/CFB/CTR
HSM_IV_WORD3_REG                         = 0x4000C05C  # offset 0x005C  RW  IV/counter word 3, bits [127:96], used by CBC/CFB/CTR
HSM_TAG_WORD0_REG                        = 0x4000C060  # offset 0x0060  R  CMAC tag/result word 0, bits [31:0]
HSM_TAG_WORD1_REG                        = 0x4000C064  # offset 0x0064  R  CMAC tag/result word 1, bits [63:32]
HSM_TAG_WORD2_REG                        = 0x4000C068  # offset 0x0068  R  CMAC tag/result word 2, bits [95:64]
HSM_TAG_WORD3_REG                        = 0x4000C06C  # offset 0x006C  R  CMAC tag/result word 3, bits [127:96]

# ── SRAM memory region ────────────────────────────────────────────────────────
# Scratchpad SRAM for device DMA transfers
SRAM_BASE         = 0x20000000
SRAM_SIZE         = 0x00020000

