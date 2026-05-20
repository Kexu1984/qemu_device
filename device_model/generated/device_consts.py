# =============================================================================
# AUTO-GENERATED — do not edit by hand.
# Source: spec/devices.yaml
# Regenerate: make gen   (or: python3 scripts/gen_device_code.py)
# =============================================================================
# Python constants mirroring the C header mmio_devices.h.
# Import in scripts or tests that need symbolic device constants:
#
#     from device_model.generated.device_consts import CONSOLE_UART_BASE

# ── Bus master IDs (from spec/soc.yaml) ─────────────────────────────────────
MASTER_ID_CPU0                     = 0x00  # Cortex-M4F CPU0
MASTER_ID_CPU1                     = 0x01  # Cortex-M4F CPU1
MASTER_ID_DMA                      = 0x10  # Python DMA controller bus master
MASTER_ID_HSM                      = 0x11  # Python HSM internal DMA bus master
MASTER_ID_FLASH_CTRL               = 0x12  # Python FLASH controller bus master
MASTER_ID_PY_FABRIC_DEMO           = 0x13  # Python fabric demo master
MASTER_ID_SV_DMA                   = 0x20  # SystemVerilog DMA prototype bus master
MASTER_ID_SYSCTRL                  = 0xF0  # Native QEMU SYSCTRL privileged SoC master
MASTER_ID_QEMU_INTERNAL            = 0xFE  # Generic QEMU internal access with no explicit SoC master
MASTER_ID_UNKNOWN                  = 0xFF  # Unknown bus master

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

# ── SYSCTRL ─────────────────────────────────────────────────────
# System controller — CPU reset release, boot policy, device clock/reset state, indirect device register access
SYSCTRL_BASE         = 0x4000A000
SYSCTRL_SIZE         = 0x1000
SYSCTRL_NATIVE_MMIO  = True

# Registers
SYSCTRL_CPUID_REG                        = 0x4000A000  # offset 0x0000  R  Current CPU index from the QEMU vCPU performing the access: 0=CPU0, 1=CPU1
SYSCTRL_CPU1RST_REG                      = 0x4000A004  # offset 0x0004  W  Legacy CPU1 reset-release alias. Write 1 to release CPU1 from reset/hold state. Prefer CPU_CTRL.CPU1_RELEASE for new code.
SYSCTRL_ID_REG                           = 0x4000A008  # offset 0x0008  R  Device ID: ASCII 'SCTL' encoded little-endian
SYSCTRL_VERSION_REG                      = 0x4000A00C  # offset 0x000C  R  SYSCTRL model version: major.minor encoded as 0x00010000 for v1.0
SYSCTRL_RESET_CTRL_REG                   = 0x4000A010  # offset 0x0010  RW  System reset control. bit0=SYS_RESET_REQ (write 1 requests QEMU subsystem reset, self-clears); bit1=HOLD_CPU1_AFTER_RESET.
SYSCTRL_RESET_STATUS_REG                 = 0x4000A014  # offset 0x0014  R  Reset status. bit0=POR_SEEN; bit1=SYS_RESET_REQUESTED_BY_SYSCTRL; bit2=CPU1_HELD_IN_RESET.
SYSCTRL_CPU_CTRL_REG                     = 0x4000A018  # offset 0x0018  RW  CPU control. bit0=CPU0_ENABLE (read-only 1 in this model); bit1=CPU1_RELEASE (write 1 releases CPU1, read reflects released state); bit2=CPU1_HALT_REQ reserved.
SYSCTRL_CPU_STATUS_REG                   = 0x4000A01C  # offset 0x001C  R  CPU status. bit0=CPU0_ACTIVE; bit1=CPU1_RELEASED; bit2=CPU1_HALTED_OR_HELD.
SYSCTRL_BOOT_MODE_REG                    = 0x4000A020  # offset 0x0020  RW  Boot mode straps/policy. bits[1:0]=BOOT_SRC (0=FLASH_HEX, 1=BOOTROM reserved, 2=SRAM reserved); bit8 reflects SECURE_BOOT_EN after OTP metadata is decoded.
SYSCTRL_BOOT_STATUS_REG                  = 0x4000A024  # offset 0x0024  R  Boot status. bit0=FLASH_IMAGE_LOADED; bit1=BOOT_VECTOR_VALID; bit2=SECURE_BOOT_DONE; bit3=SECURE_BOOT_PASS; bit4=SECURE_BOOT_FAIL.
SYSCTRL_DEVICE_CLK_EN_REG                = 0x4000A030  # offset 0x0030  RW  Coarse peripheral clock enable bitmap. bit0=UART, bit1=DMA, bit2=TIMER0, bit3=DMA_CLIENT_DEMO, bit4=CRC, bit5=WDT, bit6=SV_ISLAND, bit7=HSM. Current models keep clocks effectively enabled but expose policy state here.
SYSCTRL_DEVICE_RST_CTRL_REG              = 0x4000A034  # offset 0x0034  RW  Peripheral reset request bitmap, W1 pulse semantic in QEMU model. bit assignments match DEVICE_CLK_EN. Actual Python-device reset propagation is future work; QEMU records requested reset pulses in DEVICE_RST_STATUS.
SYSCTRL_DEVICE_RST_STATUS_REG            = 0x4000A038  # offset 0x0038  R  Last peripheral reset request bitmap latched from DEVICE_RST_CTRL writes. Firmware can use this as an observable SYSCTRL policy state.
SYSCTRL_DEVCTL_ADDR_REG                  = 0x4000A040  # offset 0x0040  RW  Indirect device register access target physical address. Must be 32-bit aligned and must not point back into SYSCTRL.
SYSCTRL_DEVCTL_WDATA_REG                 = 0x4000A044  # offset 0x0044  RW  Indirect device register write data. Used when DEVCTL_CTRL.WRITE is set.
SYSCTRL_DEVCTL_RDATA_REG                 = 0x4000A048  # offset 0x0048  R  Indirect device register read data. Updated after a successful DEVCTL read.
SYSCTRL_DEVCTL_CTRL_REG                  = 0x4000A04C  # offset 0x004C  RW  Indirect access control. bit0=START (self-clears); bit1=READ; bit2=WRITE. Exactly one of READ/WRITE must be set with START.
SYSCTRL_DEVCTL_STATUS_REG                = 0x4000A050  # offset 0x0050  R  Indirect access status. bit0=BUSY; bit1=DONE; bit2=ERROR; bit3=ADDR_ALIGN_ERR; bit4=ADDR_RANGE_ERR; bit5=BUS_ERROR.
SYSCTRL_DEVCTL_ERROR_REG                 = 0x4000A054  # offset 0x0054  R  Indirect access last error code. 0=NONE; 1=BAD_CTRL; 2=ADDR_ALIGN; 3=ADDR_RANGE; 4=BUS_ERROR.

# ── CRU ─────────────────────────────────────────────────────────
# Clock Reset Unit — device clock gating and reset control (QEMU-native)
CRU_BASE         = 0x4000F000
CRU_SIZE         = 0x1000
CRU_NATIVE_MMIO  = True

# Registers
CRU_ID_REG                               = 0x4000F000  # offset 0x0000  R  Device identifier
CRU_VERSION_REG                          = 0x4000F004  # offset 0x0004  R  Hardware version (major.minor.patch)
CRU_CLK_EN0_REG                          = 0x4000F008  # offset 0x0008  RW  Clock enable register for devices 0–8. Bit N=1 enables the clock for device N. Must be set before accessing the device; clear to save power.

CRU_CLK_EN1_REG                          = 0x4000F00C  # offset 0x000C  RW  Reserved for future devices 9–31 (reads 0, writes ignored)
CRU_RST_CTRL0_REG                        = 0x4000F010  # offset 0x0010  RW  Reset control for devices 0–8. Bit N=0 holds the device in reset (default at POR). Bit N=1 releases the device from reset. Both CLK_EN0 and RST_CTRL0 bit must be set to allow device access.

CRU_RST_CTRL1_REG                        = 0x4000F014  # offset 0x0014  RW  Reserved for future devices 9–31 (reads 0, writes ignored)
CRU_RESET_REASON_REG                     = 0x4000F018  # offset 0x0018  R  Retention register — survives Level-1 system resets, cleared only on POR. 0 = Power-on reset (POR) 1 = Watchdog timeout reset 2 = Software system reset (SOFT_SYSRST_REQ)

CRU_SOFT_SYSRST_REQ_REG                  = 0x4000F01C  # offset 0x001C  W  Write the magic value 0xDEADBEEF to request a software system reset. Sets RESET_REASON = 2, then triggers QEMU subsystem reset. All other write values are ignored.  Reads return 0.


# ── SV_ISLAND ───────────────────────────────────────────────────
# SystemVerilog APB peripheral island — timer, GPIO, and DMA prototype
SV_ISLAND_BASE         = 0x4000B000
SV_ISLAND_SIZE         = 0x1000
SV_ISLAND_IRQ_INTID    = 5
SV_ISLAND_IRQ_DELAY_S  = 0.0
SV_ISLAND_IRQ_PORT     = 7907
SV_ISLAND_RW_PORT      = 7906

# Registers
SV_ISLAND_CTRL_REG                       = 0x4000B000  # offset 0x0000  RW  Control: bit0=ENABLE, bit1=IRQ_EN
SV_ISLAND_LOAD_REG                       = 0x4000B004  # offset 0x0004  RW  Countdown load value in SV clock cycles
SV_ISLAND_VALUE_REG                      = 0x4000B008  # offset 0x0008  R  Current countdown value
SV_ISLAND_STATUS_REG                     = 0x4000B00C  # offset 0x000C  R  Status: bit0=IRQ_PENDING
SV_ISLAND_IRQ_CLEAR_REG                  = 0x4000B010  # offset 0x0010  W  Write bit0=1 to clear IRQ_PENDING and deassert IRQ
SV_ISLAND_DMA_ID_REG                     = 0x4000B100  # offset 0x0100  R  SV DMA ID: ASCII 'SDMA' little-endian
SV_ISLAND_DMA_CTRL_REG                   = 0x4000B104  # offset 0x0104  RW  SV DMA control: bit0=START, bit1=IRQ_EN
SV_ISLAND_DMA_STATUS_REG                 = 0x4000B108  # offset 0x0108  R  SV DMA status: bit0=BUSY, bit1=DONE, bit2=ERROR
SV_ISLAND_DMA_SRC_ADDR_REG               = 0x4000B10C  # offset 0x010C  RW  SV DMA source physical address; first prototype requires 32-bit alignment
SV_ISLAND_DMA_DST_ADDR_REG               = 0x4000B110  # offset 0x0110  RW  SV DMA destination physical address; first prototype requires 32-bit alignment
SV_ISLAND_DMA_LENGTH_REG                 = 0x4000B114  # offset 0x0114  RW  SV DMA transfer length in bytes; first prototype requires a non-zero multiple of 4
SV_ISLAND_DMA_ERROR_REG                  = 0x4000B118  # offset 0x0118  R  SV DMA error: 0=NONE, 1=BAD_CONFIG, 2=AHB_READ_ERROR, 3=AHB_WRITE_ERROR
SV_ISLAND_DMA_IRQ_CLEAR_REG              = 0x4000B11C  # offset 0x011C  W  Write bit0=1 to clear SV DMA DONE/ERROR IRQ and return DMA FSM to idle
SV_ISLAND_DMA_COUNT_REG                  = 0x4000B120  # offset 0x0120  R  Number of bytes completed by the SV DMA engine
SV_ISLAND_DMA_CH1_ID_REG                 = 0x4000B140  # offset 0x0140  R  SV DMA CH1 ID: ASCII 'DCH1' little-endian
SV_ISLAND_DMA_CH1_CTRL_REG               = 0x4000B144  # offset 0x0144  RW  SV DMA CH1 control: bit0=START, bit1=IRQ_EN
SV_ISLAND_DMA_CH1_STATUS_REG             = 0x4000B148  # offset 0x0148  R  SV DMA CH1 status: bit0=BUSY, bit1=DONE, bit2=ERROR
SV_ISLAND_DMA_CH1_SRC_ADDR_REG           = 0x4000B14C  # offset 0x014C  RW  SV DMA CH1 source physical address; first prototype requires 32-bit alignment
SV_ISLAND_DMA_CH1_LENGTH_REG             = 0x4000B150  # offset 0x0150  RW  SV DMA CH1 transfer length in bytes; first prototype requires a non-zero multiple of 4
SV_ISLAND_DMA_CH1_DST_ADDR_REG           = 0x4000B154  # offset 0x0154  RW  SV DMA CH1 fixed destination physical address; for SPI TX use SPI_TX_TXDATA
SV_ISLAND_DMA_CH1_PERIPH_SEL_REG         = 0x4000B158  # offset 0x0158  RW  SV DMA CH1 request source selector: 1=SPI_TX dma_req
SV_ISLAND_DMA_CH1_ERROR_REG              = 0x4000B15C  # offset 0x015C  R  SV DMA CH1 error: 0=NONE, 1=BAD_CONFIG, 2=FABRIC_READ_ERROR, 3=FABRIC_WRITE_ERROR
SV_ISLAND_DMA_CH1_IRQ_CLEAR_REG          = 0x4000B160  # offset 0x0160  W  Write bit0=1 to clear SV DMA CH1 DONE/ERROR IRQ and return CH1 FSM to idle
SV_ISLAND_DMA_CH1_COUNT_REG              = 0x4000B164  # offset 0x0164  R  Number of bytes completed by SV DMA CH1
SV_ISLAND_GPIO_ID_REG                    = 0x4000B200  # offset 0x0200  R  SV GPIO ID: ASCII 'GPIO' little-endian
SV_ISLAND_GPIO_DATA_OUT_REG              = 0x4000B204  # offset 0x0204  RW  GPIO output data shadow
SV_ISLAND_GPIO_DATA_IN_REG               = 0x4000B208  # offset 0x0208  R  GPIO sampled input data; output pins read back DATA_OUT
SV_ISLAND_GPIO_DIR_REG                   = 0x4000B20C  # offset 0x020C  RW  GPIO direction bitmap: bit=1 output, bit=0 input
SV_ISLAND_GPIO_SET_REG                   = 0x4000B210  # offset 0x0210  W  Write-one set bits in GPIO_DATA_OUT
SV_ISLAND_GPIO_CLR_REG                   = 0x4000B214  # offset 0x0214  W  Write-one clear bits in GPIO_DATA_OUT
SV_ISLAND_GPIO_TOGGLE_REG                = 0x4000B218  # offset 0x0218  W  Write-one toggle bits in GPIO_DATA_OUT
SV_ISLAND_GPIO_IRQ_EN_REG                = 0x4000B21C  # offset 0x021C  RW  GPIO data-change IRQ enable bitmap
SV_ISLAND_GPIO_IRQ_STATUS_REG            = 0x4000B220  # offset 0x0220  RW  GPIO data-change IRQ pending bitmap; write-one clears bits
SV_ISLAND_GPIO_INPUT_SIM_REG             = 0x4000B224  # offset 0x0224  RW  Simulation input value for pins configured as inputs
SV_ISLAND_SPI_TX_ID_REG                  = 0x4000B300  # offset 0x0300  R  SPI TX ID: ASCII 'SPTX' little-endian
SV_ISLAND_SPI_TX_VERSION_REG             = 0x4000B304  # offset 0x0304  R  SPI TX spec version: 0x00010000 for v1.0
SV_ISLAND_SPI_TX_CTRL_REG                = 0x4000B308  # offset 0x0308  RW  SPI TX control: bit0=ENABLE, bit1=START, bit2=ABORT, bit3=SOFT_RESET, bit4=CS_AUTO, bit5=CS_HOLD_ACTIVE
SV_ISLAND_SPI_TX_STATUS_REG              = 0x4000B30C  # offset 0x030C  R  SPI TX status: bit0=BUSY, bit1=DONE, bit2=ERROR, bit3=TX_EMPTY, bit4=TX_FULL, bit5=TX_THRESHOLD_HIT, bit6=CS_ACTIVE, bit7=IRQ_PENDING, bits15:8=TX_LEVEL
SV_ISLAND_SPI_TX_INT_STATUS_REG          = 0x4000B310  # offset 0x0310  RW  SPI TX interrupt status, W1C: bit0=DONE_IRQ, bit1=TX_THRESHOLD_IRQ, bit2=ERROR_IRQ
SV_ISLAND_SPI_TX_INT_ENABLE_REG          = 0x4000B314  # offset 0x0314  RW  SPI TX interrupt enable: bit0=DONE_IRQ, bit1=TX_THRESHOLD_IRQ, bit2=ERROR_IRQ
SV_ISLAND_SPI_TX_ERROR_REG               = 0x4000B318  # offset 0x0318  R  SPI TX last error: 0=NONE, 1=TX_OVERFLOW, 2=TX_UNDERRUN, 3=INVALID_CFG, 4=BUSY_START, 5=ABORTED
SV_ISLAND_SPI_TX_CFG_REG                 = 0x4000B31C  # offset 0x031C  RW  SPI TX format: bit0=CPOL, bit1=CPHA, bit2=LSB_FIRST, bits12:8=FRAME_BITS_MINUS_1
SV_ISLAND_SPI_TX_BAUD_DIV_REG            = 0x4000B320  # offset 0x0320  RW  SPI TX clock divider. Legal values >=2; SCLK = PCLK / (2 * BAUD_DIV).
SV_ISLAND_SPI_TX_TXDATA_REG              = 0x4000B324  # offset 0x0324  W  SPI TX FIFO write port. One write enqueues one frame using low FRAME_BITS bits.
SV_ISLAND_SPI_TX_TX_LEVEL_REG            = 0x4000B328  # offset 0x0328  R  SPI TX FIFO queued frame count, range 0..16
SV_ISLAND_SPI_TX_TX_THRESHOLD_REG        = 0x4000B32C  # offset 0x032C  RW  SPI TX threshold level; IRQ condition is TX_LEVEL <= TX_THRESHOLD
SV_ISLAND_SPI_TX_FRAME_COUNT_REG         = 0x4000B330  # offset 0x0330  RW  SPI TX frames remaining in the active transfer; firmware writes the requested frame count before START
SV_ISLAND_SPI_TX_CS_SETUP_REG            = 0x4000B334  # offset 0x0334  RW  SPI TX chip-select setup delay in SV clock cycles
SV_ISLAND_SPI_TX_CS_HOLD_REG             = 0x4000B338  # offset 0x0338  RW  SPI TX chip-select hold delay in SV clock cycles
SV_ISLAND_SPI_TX_FIFO_CTRL_REG           = 0x4000B33C  # offset 0x033C  W  SPI TX FIFO control: write bit0=1 to clear the TX FIFO
SV_ISLAND_SPI_TX_LAST_FRAME_REG          = 0x4000B340  # offset 0x0340  R  SPI TX debug: most recently completed frame, right-aligned
SV_ISLAND_SPI_TX_FRAME_DONE_COUNT_REG    = 0x4000B344  # offset 0x0344  R  SPI TX debug: number of completed frames since reset or SOFT_RESET
SV_ISLAND_SPI_TX_BIT_COUNT_REG           = 0x4000B348  # offset 0x0348  R  SPI TX debug: number of shifted bits since reset or SOFT_RESET

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

# ── OTP ─────────────────────────────────────────────────────────
# OTP controller — one-time-programmable storage with ECC and HSM direct key provider
OTP_BASE         = 0x4000D000
OTP_SIZE         = 0x1000
OTP_IRQ_INTID    = 7
OTP_IRQ_DELAY_S  = 0.0
OTP_IRQ_PORT     = 7911
OTP_RW_PORT      = 7910

# Registers
OTP_ID_REG                               = 0x4000D000  # offset 0x0000  R  Device ID: ASCII 'OTP1' encoded little-endian
OTP_VERSION_REG                          = 0x4000D004  # offset 0x0004  R  OTP controller model version: major.minor encoded as 0x00010000 for v1.0
OTP_CTRL_REG                             = 0x4000D008  # offset 0x0008  RW  Control register. bit0 = START (write 1 to execute command, self-clears); bit1 = READ row into RDATA/ECC_RDATA; bit2 = PROGRAM row from WDATA; bit3 = RELOAD storage file and refresh shadow registers; bit4 = SAVE current rows to storage file; bit5 = IRQ_ENABLE; exactly one of READ/PROGRAM/RELOAD/SAVE must be set with START.

OTP_STATUS_REG                           = 0x4000D00C  # offset 0x000C  R  Status register. bit0 = BUSY; bit1 = DONE; bit2 = ERROR; bit3 = IRQ_PENDING; bit4 = UNLOCKED; bit5 = FILE_LOADED; bit6 = FILE_DIRTY; bit7 = ECC_CORRECTED sticky until STATUS_CLEAR; bit8 = ECC_UNCORRECTABLE sticky until STATUS_CLEAR; bit9 = LOCKED_REGION; bit10 = SHADOW_VALID; bit11 = READ_PROTECTED sticky until STATUS_CLEAR.

OTP_INT_STATUS_REG                       = 0x4000D010  # offset 0x0010  RW  Interrupt/status latch, W1C. bit0 = DONE_IRQ; bit1 = ERROR_IRQ; bit2 = ECC_CORRECTED_IRQ; bit3 = ECC_UNCORRECTABLE_IRQ.

OTP_INT_ENABLE_REG                       = 0x4000D014  # offset 0x0014  RW  Interrupt enable mask corresponding to INT_STATUS bits. CTRL.IRQ_ENABLE must also be set for the Python model to pulse the IRQ line.

OTP_ERROR_REG                            = 0x4000D018  # offset 0x0018  R  Last error code. 0=NONE; 1=BAD_COMMAND; 2=ADDR_RANGE; 3=ZERO_TO_ONE_PROGRAM; 4=LOCKED; 5=UNLOCK_REQUIRED; 6=FILE_IO; 7=FILE_FORMAT; 8=ECC_CORRECTED; 9=ECC_UNCORRECTABLE; 10=BUSY; 11=READ_PROTECTED.

OTP_STATUS_CLEAR_REG                     = 0x4000D01C  # offset 0x001C  W  Write-1-to-clear sticky STATUS bits. bit7 clears ECC_CORRECTED; bit8 clears ECC_UNCORRECTABLE; bit11 clears READ_PROTECTED.

OTP_ADDR_REG                             = 0x4000D020  # offset 0x0020  RW  OTP row index for command READ/PROGRAM. Valid range: 0 .. row_count-1.
OTP_WDATA_REG                            = 0x4000D024  # offset 0x0024  RW  32-bit data word used by PROGRAM command. Only 1->0 transitions are allowed.
OTP_RDATA_REG                            = 0x4000D028  # offset 0x0028  R  32-bit data word returned by the last successful non-secret READ command.
OTP_ECC_RDATA_REG                        = 0x4000D02C  # offset 0x002C  R  ECC byte associated with the last READ command. bits[7:0] carry the model ECC.
OTP_UNLOCK0_REG                          = 0x4000D030  # offset 0x0030  W  First programming unlock word. Write 0x4F545031 ('OTP1') before PROGRAM. Reads return 0.
OTP_UNLOCK1_REG                          = 0x4000D034  # offset 0x0034  W  Second programming unlock word. Write 0x50524F47 ('PROG') before PROGRAM. Reads return 0.
OTP_LOCK_CTRL_REG                        = 0x4000D038  # offset 0x0038  RW  Region lock request register. W1 locks regions permanently for this model instance and persists lock bits in the OTP metadata row. bit0 locks HSM key slots 0..14; bit1 locks lifecycle rows; bit2 locks customer configuration rows; bit3 locks general-purpose rows.

OTP_LOCK_STATUS_REG                      = 0x4000D03C  # offset 0x003C  R  Latched region lock status. Same bit assignment as LOCK_CTRL.
OTP_ROW_COUNT_REG                        = 0x4000D040  # offset 0x0040  R  Total number of OTP rows implemented by this model. Reset value follows model.row_count.
OTP_ROW_BITS_REG                         = 0x4000D044  # offset 0x0044  R  Data bits per OTP row. First model uses 32-bit rows.
OTP_ECC_STATUS_REG                       = 0x4000D048  # offset 0x0048  R  ECC summary. bits[7:0] = corrected error count modulo 256; bits[15:8] = uncorrectable error count modulo 256; bits[31:16] = last row index with an ECC event.

OTP_FILE_STATUS_REG                      = 0x4000D04C  # offset 0x004C  R  Storage file summary. bit0 = EXISTS; bit1 = LOADED; bit2 = DIRTY; bit3 = STRICT_FILE; bit4 = FORMAT_ERROR.

OTP_LIFECYCLE_WORD0_REG                  = 0x4000D100  # offset 0x0100  R  Shadow of non-secret lifecycle / boot policy row 0x0040
OTP_LIFECYCLE_WORD1_REG                  = 0x4000D104  # offset 0x0104  R  Shadow of non-secret lifecycle / boot policy row 0x0041
OTP_LIFECYCLE_WORD2_REG                  = 0x4000D108  # offset 0x0108  R  Shadow of non-secret lifecycle / boot policy row 0x0042
OTP_LIFECYCLE_WORD3_REG                  = 0x4000D10C  # offset 0x010C  R  Shadow of non-secret lifecycle / boot policy row 0x0043
OTP_CUSTOMER_WORD0_REG                   = 0x4000D120  # offset 0x0120  R  Shadow of non-secret customer configuration row 0x0050
OTP_CUSTOMER_WORD1_REG                   = 0x4000D124  # offset 0x0124  R  Shadow of non-secret customer configuration row 0x0051
OTP_CUSTOMER_WORD2_REG                   = 0x4000D128  # offset 0x0128  R  Shadow of non-secret customer configuration row 0x0052
OTP_CUSTOMER_WORD3_REG                   = 0x4000D12C  # offset 0x012C  R  Shadow of non-secret customer configuration row 0x0053

# ── FLASH_CTRL ──────────────────────────────────────────────────
# FLASH controller — command sequencer for data FLASH read/program/erase
FLASH_CTRL_BASE         = 0x4000E000
FLASH_CTRL_SIZE         = 0x1000
FLASH_CTRL_IRQ_INTID    = 8
FLASH_CTRL_IRQ_DELAY_S  = 0.0
FLASH_CTRL_IRQ_PORT     = 7914
FLASH_CTRL_RW_PORT      = 7913

# Registers
FLASH_CTRL_ID_REG                        = 0x4000E000  # offset 0x0000  R  Device ID: ASCII 'FLSH' encoded little-endian
FLASH_CTRL_VERSION_REG                   = 0x4000E004  # offset 0x0004  R  Model version: major.minor encoded as 0x00010000 for v1.0
FLASH_CTRL_CTRL_REG                      = 0x4000E008  # offset 0x0008  RW  Control register. bit0 = START (write 1 to start command, self-clears); bit1 = IRQ_ENABLE; bit2 = ABORT reserved for future long-running command cancellation.

FLASH_CTRL_STATUS_REG                    = 0x4000E00C  # offset 0x000C  R  Status register. bit0 = BUSY; bit1 = DONE; bit2 = ERROR; bit3 = IRQ_PENDING; bit4 = LOCKED; bit5 = PROGRAM_ALLOWED after valid PROGRAM unlock; bit6 = ERASE_ALLOWED after valid ERASE unlock; bit7 = ECC_CORRECTED; bit8 = ECC_UNCORRECTABLE; bit9 = FILE_LOADED; bit10 = FILE_DIRTY.

FLASH_CTRL_INT_STATUS_REG                = 0x4000E010  # offset 0x0010  RW  Interrupt/status latch, W1C. bit0 = DONE_IRQ; bit1 = ERROR_IRQ; bit2 = ECC_CORRECTED_IRQ; bit3 = ECC_UNCORRECTABLE_IRQ.

FLASH_CTRL_INT_ENABLE_REG                = 0x4000E014  # offset 0x0014  RW  Interrupt enable mask. bit0 enables DONE interrupt; bit1 enables ERROR interrupt; bit2 enables ECC_CORRECTED interrupt; bit3 enables ECC_UNCORRECTABLE interrupt.

FLASH_CTRL_ERROR_REG                     = 0x4000E018  # offset 0x0018  R  Last error code. 0=NONE; 1=BUSY; 2=INVALID_CMD; 3=ADDR_RANGE; 4=LENGTH_RANGE; 5=ADDR_ALIGN; 6=LENGTH_ALIGN; 7=LOCKED; 8=UNLOCK_REQUIRED; 9=PROGRAM_ZERO_TO_ONE; 10=MEM_READ_ERROR; 11=MEM_WRITE_ERROR; 12=VERIFY_ERROR; 13=ECC_CORRECTED; 14=ECC_UNCORRECTABLE; 15=FILE_IO; 16=FILE_FORMAT.

FLASH_CTRL_CMD_REG                       = 0x4000E01C  # offset 0x001C  RW  Command selector. 0=NONE; 1=READ; 2=PROGRAM; 3=ERASE_WORDLINE; 4=ERASE_CHIP; 5=VERIFY.

FLASH_CTRL_ADDR_REG                      = 0x4000E020  # offset 0x0020  RW  Byte offset inside data FLASH for READ/PROGRAM/ERASE_WORDLINE/VERIFY
FLASH_CTRL_SRC_ADDR_REG                  = 0x4000E024  # offset 0x0024  RW  QEMU physical source address for PROGRAM input buffer
FLASH_CTRL_DST_ADDR_REG                  = 0x4000E028  # offset 0x0028  RW  QEMU physical destination address for READ output buffer
FLASH_CTRL_LENGTH_REG                    = 0x4000E02C  # offset 0x002C  RW  Transfer length in bytes for READ/PROGRAM/VERIFY commands
FLASH_CTRL_WORDLINE_SIZE_REG             = 0x4000E030  # offset 0x0030  R  Data wordline size in bytes
FLASH_CTRL_FLASH_BASE_REG                = 0x4000E034  # offset 0x0034  R  Data FLASH memory window base address
FLASH_CTRL_FLASH_SIZE_REG                = 0x4000E038  # offset 0x0038  R  Data FLASH memory window size in bytes
FLASH_CTRL_ERASED_VALUE_REG              = 0x4000E03C  # offset 0x003C  R  Erased byte value in bits[7:0]
FLASH_CTRL_UNLOCK0_REG                   = 0x4000E040  # offset 0x0040  W  Unlock word 0. Write 0x464C5331 ('FLS1') before PROGRAM or ERASE unlock word.
FLASH_CTRL_UNLOCK1_REG                   = 0x4000E044  # offset 0x0044  W  Unlock word 1. Write 0x50524F47 ('PROG') after UNLOCK0 to allow one PROGRAM command; write 0x45524153 ('ERAS') after UNLOCK0 to allow one ERASE command.

FLASH_CTRL_LOCK_REG                      = 0x4000E048  # offset 0x0048  W  Write any value to clear PROGRAM_ALLOWED/ERASE_ALLOWED and return to locked state
FLASH_CTRL_STATUS_CLEAR_REG              = 0x4000E04C  # offset 0x004C  W  W1C sticky status bits. bit1 clears DONE; bit2 clears ERROR; bit3 clears IRQ_PENDING; bit7 clears ECC_CORRECTED; bit8 clears ECC_UNCORRECTABLE.

FLASH_CTRL_TIMING_READ_REG               = 0x4000E050  # offset 0x0050  R  Nominal READ timing: bits[15:0]=base ns, bits[31:16]=per 64-bit wordline ns
FLASH_CTRL_TIMING_PROGRAM_REG            = 0x4000E054  # offset 0x0054  R  Nominal PROGRAM timing: bits[15:0]=base ns, bits[31:16]=per 64-bit wordline ns
FLASH_CTRL_TIMING_ERASE_WORDLINE_REG     = 0x4000E058  # offset 0x0058  R  Nominal ERASE_WORDLINE latency in nanoseconds
FLASH_CTRL_TIMING_ERASE_CHIP_REG         = 0x4000E05C  # offset 0x005C  R  Nominal ERASE_CHIP latency in nanoseconds
FLASH_CTRL_LAST_OP_ADDR_REG              = 0x4000E060  # offset 0x0060  R  Latched ADDR from the most recently completed command
FLASH_CTRL_LAST_OP_LENGTH_REG            = 0x4000E064  # offset 0x0064  R  Latched LENGTH from the most recently completed READ/PROGRAM/VERIFY command
FLASH_CTRL_LAST_OP_CRC32_REG             = 0x4000E068  # offset 0x0068  R  Optional CRC32/checksum of the most recent command payload; first model may leave zero
FLASH_CTRL_ECC_STATUS_REG                = 0x4000E06C  # offset 0x006C  R  ECC status for the most recent checked wordline. bit0 = CHECKED; bit1 = CORRECTED; bit2 = UNCORRECTABLE; bits[15:8] = syndrome.

FLASH_CTRL_ECC_ADDR_REG                  = 0x4000E070  # offset 0x0070  R  Byte offset of the most recent ECC event/check
FLASH_CTRL_ECC_SYNDROME_REG              = 0x4000E074  # offset 0x0074  R  Raw ECC syndrome for the most recent ECC check
FLASH_CTRL_ECC_CORRECTED_COUNT_REG       = 0x4000E078  # offset 0x0078  R  Number of corrected ECC events since model start
FLASH_CTRL_ECC_UNCORRECTABLE_COUNT_REG   = 0x4000E07C  # offset 0x007C  R  Number of uncorrectable ECC events since model start
FLASH_CTRL_INJECT_ADDR_REG               = 0x4000E080  # offset 0x0080  RW  Byte offset of the 64-bit wordline targeted by error injection
FLASH_CTRL_INJECT_MASK_LO_REG            = 0x4000E084  # offset 0x0084  RW  Data-bit injection mask bits[31:0] for the selected wordline
FLASH_CTRL_INJECT_MASK_HI_REG            = 0x4000E088  # offset 0x0088  RW  Data-bit injection mask bits[63:32] for the selected wordline
FLASH_CTRL_INJECT_ECC_MASK_REG           = 0x4000E08C  # offset 0x008C  RW  ECC-bit injection mask bits[7:0] for the selected wordline
FLASH_CTRL_INJECT_CTRL_REG               = 0x4000E090  # offset 0x0090  W  Error injection control. bit0 = APPLY once by XORing data/ecc masks into the backend without recomputing ECC; bit1 = CLEAR_MASKS after apply.


# ── COVERAGE ────────────────────────────────────────────────────
# Coverage capture sink — receives LLVM coverage/profile sections from firmware over MMIO
COVERAGE_BASE         = 0x40010000
COVERAGE_SIZE         = 0x1000
COVERAGE_RW_PORT      = 7918

# Registers
COVERAGE_ID_REG                          = 0x40010000  # offset 0x0000  R  Device ID: ASCII 'COV1' encoded little-endian
COVERAGE_VERSION_REG                     = 0x40010004  # offset 0x0004  R  Coverage device model version: major.minor encoded as 0x00010000 for v1.0
COVERAGE_CTRL_REG                        = 0x40010008  # offset 0x0008  W  Control: bit0=RESET_CAPTURE, bit1=FLUSH_CAPTURE
COVERAGE_STATUS_REG                      = 0x4001000C  # offset 0x000C  R  Status: bit0=ACTIVE, bit1=COMPLETE, bit2=ERROR
COVERAGE_ERROR_REG                       = 0x40010010  # offset 0x0010  R  Last error code: 0=NONE, 1=BAD_REGION, 2=OVERFLOW, 3=IO_ERROR
COVERAGE_REGION_REG                      = 0x40010014  # offset 0x0014  RW  Active region ID: 1=prf_data, 2=prf_cnts, 3=prf_names, 4=covmap
COVERAGE_SIZE_REG                        = 0x40010018  # offset 0x0018  RW  Expected byte size for the active region; writing starts a new region capture
COVERAGE_WRITTEN_REG                     = 0x4001001C  # offset 0x001C  R  Bytes written for the active region
COVERAGE_DATA_REG                        = 0x40010020  # offset 0x0020  W  Streaming data window. Byte/halfword/word writes append to the active region
COVERAGE_TOTAL_BYTES_REG                 = 0x40010024  # offset 0x0024  R  Total captured bytes across all regions
COVERAGE_CHUNKS_REG                      = 0x40010028  # offset 0x0028  R  Number of DATA writes received
COVERAGE_NONZERO_WORDS_REG               = 0x4001002C  # offset 0x002C  R  Number of non-zero 64-bit words seen in profile counter data
COVERAGE_REGION_COUNT_REG                = 0x40010030  # offset 0x0030  R  Number of non-empty regions captured
COVERAGE_CRC32_REG                       = 0x40010034  # offset 0x0034  R  CRC-32 of captured KXCV payload bytes

# ── DISPLAY ─────────────────────────────────────────────────────
# Display controller — RGB565 framebuffer scanout to a host window
DISPLAY_BASE         = 0x40011000
DISPLAY_SIZE         = 0x1000
DISPLAY_IRQ_INTID    = 9
DISPLAY_IRQ_DELAY_S  = 0.0
DISPLAY_IRQ_PORT     = 7920
DISPLAY_RW_PORT      = 7919

# Registers
DISPLAY_ID_REG                           = 0x40011000  # offset 0x0000  R  Display controller ID: ASCII 'DISP' little-endian
DISPLAY_VERSION_REG                      = 0x40011004  # offset 0x0004  R  Display controller spec version: 0x00010000 for v1.0
DISPLAY_CTRL_REG                         = 0x40011008  # offset 0x0008  RW  Control: bit0=ENABLE, bit1=SOFT_RESET(W1P), bit2=OUTPUT_ENABLE
DISPLAY_STATUS_REG                       = 0x4001100C  # offset 0x000C  R  Status: bit0=BUSY, bit1=FRAME_DONE, bit2=ERROR, bit3=ENABLED, bit4=ACTIVE_VIDEO, bit5=SHADOW_PENDING, bits23:16=LINE_STATE, bits31:24=FRAME_STATE
DISPLAY_INT_STATUS_REG                   = 0x40011010  # offset 0x0010  RW  Interrupt status W1C: bit0=FRAME_DONE
DISPLAY_INT_ENABLE_REG                   = 0x40011014  # offset 0x0014  RW  Interrupt enable: bit0=FRAME_DONE
DISPLAY_INT_CLEAR_REG                    = 0x40011018  # offset 0x0018  W  Interrupt clear alias: write bit0=1 to clear FRAME_DONE
DISPLAY_ERROR_REG                        = 0x4001101C  # offset 0x001C  R  Error code: 0=NONE, 1=BAD_CONFIG, 2=BAD_FORMAT, 3=BAD_FB_ADDR, 4=FABRIC_READ_ERROR, 5=BUSY_CFG
DISPLAY_FB_BASE_REG                      = 0x40011020  # offset 0x0020  RW  Framebuffer base physical address for active scanout; first model requires 4-byte alignment
DISPLAY_FB_STRIDE_REG                    = 0x40011024  # offset 0x0024  RW  Framebuffer stride in bytes per line; must be at least WIDTH * bytes_per_pixel
DISPLAY_WIDTH_REG                        = 0x40011028  # offset 0x0028  RW  Active width in pixels
DISPLAY_HEIGHT_REG                       = 0x4001102C  # offset 0x002C  RW  Active height in lines
DISPLAY_FORMAT_REG                       = 0x40011030  # offset 0x0030  RW  Pixel format: 0=RGB565 little-endian only; other values report BAD_FORMAT
DISPLAY_BG_COLOR_REG                     = 0x40011034  # offset 0x0034  RW  Background/fill color in native FORMAT encoding, used only if the model supports blanking artifact output
DISPLAY_H_TIMING_REG                     = 0x40011038  # offset 0x0038  RW  Horizontal timing: bits9:0=H_FRONT_PORCH, bits19:10=H_SYNC_WIDTH, bits29:20=H_BACK_PORCH
DISPLAY_V_TIMING_REG                     = 0x4001103C  # offset 0x003C  RW  Vertical timing: bits9:0=V_FRONT_PORCH, bits19:10=V_SYNC_WIDTH, bits29:20=V_BACK_PORCH
DISPLAY_PIXEL_CLOCK_HZ_REG               = 0x40011040  # offset 0x0040  RW  Nominal pixel clock in Hz; used to compute scanout completion time
DISPLAY_SHADOW_FB_BASE_REG               = 0x40011048  # offset 0x0048  RW  Next framebuffer base physical address; latched to FB_BASE at the next frame boundary after SHADOW_CTRL.APPLY
DISPLAY_SHADOW_CTRL_REG                  = 0x4001104C  # offset 0x004C  RW  Shadow control: bit0=APPLY(W1P), bit1=PENDING(R), bit2=CANCEL(W1P)
DISPLAY_CUR_LINE_REG                     = 0x40011050  # offset 0x0050  R  Current scanout line index; active-video lines start at 0
DISPLAY_CUR_PIXEL_REG                    = 0x40011054  # offset 0x0054  R  Current scanout pixel index within the current line
DISPLAY_FRAME_COUNT_REG                  = 0x40011058  # offset 0x0058  R  Number of frames completed since reset or SOFT_RESET
DISPLAY_FRAME_CRC_REG                    = 0x4001105C  # offset 0x005C  R  CRC-32 of the last completed active pixel bytes only, computed in scanout order
DISPLAY_LAST_FB_BASE_REG                 = 0x40011060  # offset 0x0060  R  Framebuffer base address used for the last completed frame
DISPLAY_OUTPUT_CTRL_REG                  = 0x40011064  # offset 0x0064  RW  Output control: bit0=WINDOW_ENABLE, bit1=TRACE_EVENTS
DISPLAY_OUTPUT_INDEX_REG                 = 0x40011068  # offset 0x0068  R  Index of the last rendered frame in the host display window
DISPLAY_LAYER_CTRL_REG                   = 0x4001106C  # offset 0x006C  RW  Layer control: bit0=LAYER0_ENABLE, bit1=LAYER1_ENABLE, bit8=LAYER1_COLORKEY_ENABLE. Reset 0 keeps legacy layer0-only behavior.
DISPLAY_L1_FB_BASE_REG                   = 0x40011070  # offset 0x0070  RW  Layer1 framebuffer base physical address; requires 4-byte alignment when LAYER1_ENABLE=1
DISPLAY_L1_FB_STRIDE_REG                 = 0x40011074  # offset 0x0074  RW  Layer1 framebuffer stride in bytes per line; must be at least L1_WIDTH * bytes_per_pixel
DISPLAY_L1_X_REG                         = 0x40011078  # offset 0x0078  RW  Layer1 top-left X position in output pixels
DISPLAY_L1_Y_REG                         = 0x4001107C  # offset 0x007C  RW  Layer1 top-left Y position in output pixels
DISPLAY_L1_WIDTH_REG                     = 0x40011080  # offset 0x0080  RW  Layer1 width in pixels
DISPLAY_L1_HEIGHT_REG                    = 0x40011084  # offset 0x0084  RW  Layer1 height in lines
DISPLAY_L1_FORMAT_REG                    = 0x40011088  # offset 0x0088  RW  Layer1 pixel format: 0=RGB565 little-endian only; other values report BAD_FORMAT
DISPLAY_L1_COLORKEY_REG                  = 0x4001108C  # offset 0x008C  RW  Layer1 transparent color key in native FORMAT encoding when LAYER1_COLORKEY_ENABLE=1
DISPLAY_LAST_L1_FB_BASE_REG              = 0x40011090  # offset 0x0090  R  Layer1 framebuffer base address used for the last completed composed frame, or zero if layer1 was disabled

# ── DATA_FLASH memory region ──────────────────────────────────────────────────
# Data FLASH read-only memory window; program/erase via FLASH controller
DATA_FLASH_BASE         = 0x10000000
DATA_FLASH_SIZE         = 0x00080000

# ── SRAM memory region ────────────────────────────────────────────────────────
# Scratchpad SRAM for device DMA transfers
SRAM_BASE         = 0x20000000
SRAM_SIZE         = 0x00020000

