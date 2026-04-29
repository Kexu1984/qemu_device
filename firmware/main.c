/*
 * Bare metal Cortex-M3 firmware — MMIO socket device + interrupt test
 *
 * IO addresses and IRQ numbers are NOT hardcoded here.  They come from
 * the auto-generated header build/generated/mmio_devices.h, which is
 * produced by scripts/gen_device_code.py reading spec/devices.yaml.
 *
 * Memory map (KX6625 SoC, Cortex-M3):
 *   0x00000000  FLASH — vector table + code  (512 KB)
 *   0xE000E000  NVIC (Nested Vectored Interrupt Controller)
 *   0x20000000  SRAM (128 KB)
 *   0x40004000  console_uart device (mmio-sockdev, IRQ0)
 *   0x40005000  dma device          (mmio-sockdev, IRQ1)
 *   0x40006000  timer0 device       (mmio-sockdev, IRQ2)
 *   0x40008000  crc device          (mmio-sockdev, polled)
 *   0x40009000  wdt device          (mmio-sockdev, IRQ4)
 */

#include <stdint.h>
#include "mmio_devices.h"   /* auto-generated from spec/devices.yaml */

/* -----------------------------------------------------------------------
 * Convenience aliases — map logical names to generated symbolic names.
 * ----------------------------------------------------------------------- */
#define TXDATA_REG        CONSOLE_UART_TXDATA_REG
#define STATUS_REG        CONSOLE_UART_STATUS_REG
#define CTRL_REG          CONSOLE_UART_CTRL_REG

/* SRAM layout for DMA demo (SRAM_BASE from generated mmio_devices.h)
 * Buffers placed at +0x1000/+0x2000 to avoid overlap with .bss globals
 * (irq_count, dma_irq_fired) which live at the start of SRAM.
 * KX6625 SRAM is 128 KB; buffers well within range. */
#define DMA_DEMO_SRC       (SRAM_BASE + 0x1000U)  /* 512 B source buffer  */
#define DMA_DEMO_DST       (SRAM_BASE + 0x2000U)  /* 512 B dest   buffer  */
#define DMA_DEMO_LEN       32U                    /* bytes to transfer    */

/* DMA client demo buffers — placed further in SRAM to avoid overlap */
#define DMA_CLIENT_SRC     (SRAM_BASE + 0x3000U)  /* 512 B source buffer  */
#define DMA_CLIENT_DST     (SRAM_BASE + 0x4000U)  /* 512 B dest   buffer  */
#define DMA_CLIENT_LEN     32U                    /* bytes to transfer    */

/* DMA address-mode flag: bit0=FIXED — hold address after each byte (xP or Px transfer) */
#define DMA_ADDR_FIXED     0x1U
#define DMA_ADDR_INCR      0x0U   /* address increments after each byte (default) */

#define CRC_CTRL_RESET     0x1U   /* bit0: reset accumulator to 0xFFFFFFFF */
#define DMA_CRC_SRC        (SRAM_BASE + 0x5000U)  /* 16B source for DMA→CRC test */

/* WDT register bit definitions */
#define WDT_CTRL_ENABLE     0x1U
#define WDT_CTRL_INT_ENABLE 0x2U
#define WDT_REASON_POR      0x0U
#define WDT_REASON_WDT      0x1U

/* CRC-32 test vector: CRC-32("123456789") = 0xCBF43926  (ISO-HDLC / IEEE 802.3) */
#define CRC_EXPECTED       0xCBF43926U

/* -----------------------------------------------------------------------
 * Low-level MMIO helpers
 * ----------------------------------------------------------------------- */
static inline void mmio_write32(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)(uintptr_t)addr = value;
}

static inline uint32_t mmio_read32(uint32_t addr)
{
    return *(volatile uint32_t *)(uintptr_t)addr;
}

static inline void mmio_write8(uint32_t addr, uint8_t value)
{
    *(volatile uint8_t *)(uintptr_t)addr = value;
}

/* -----------------------------------------------------------------------
 * MMIO device helpers
 * ----------------------------------------------------------------------- */
static void send_char(char c)
{
    /* STATUS always returns TXREADY=1; skip the poll to avoid MMIO reads
     * that can block QEMU's event loop and delay IRQ delivery. */
    mmio_write8(TXDATA_REG, (uint8_t)c);
}

static void send_string(const char *str)
{
    while (*str) {
        send_char(*str++);
    }
}

/* -----------------------------------------------------------------------
 * Cortex-M3 NVIC initialisation
 *
 * NVIC register addresses (derived from NVIC_BASE = 0xE000E000):
 *   NVIC_ISER0 (0xE000E100) — IRQ enable set  for IRQ  0-31
 *   NVIC_ICPR0 (0xE000E280) — IRQ clear pending for IRQ  0-31
 *   NVIC_IPR0  (0xE000E400) — priority bytes for IRQ 0-3
 *
 * Enables IRQ 0 (UART), IRQ 1 (DMA), IRQ 2 (Timer0).
 * KX6625 has 16 external IRQs (0-15); IRQs 0/1/2 are our devices.
 * ----------------------------------------------------------------------- */
static void nvic_init(void)
{
    /* 1. Clear any stale pending state for IRQ 0, 1, 2, 3, 4 */
    mmio_write32(NVIC_ICPR0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) | (1u << 4));

    /* 2. Set priority 0 (highest) for IRQ 0-3 */
    mmio_write32(NVIC_IPR0, 0x00000000U);

    /* 3. Enable IRQ 0-4 in ISER0 */
    mmio_write32(NVIC_ISER0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) | (1u << 4));
}

/* -----------------------------------------------------------------------
 * IRQ handlers — called directly from the vector table (start.S).
 * Cortex-M3 hardware saves/restores the exception frame automatically;
 * plain C functions with no special attribute are sufficient.
 * ----------------------------------------------------------------------- */
volatile int irq_count          = 0;
volatile int dma_irq_fired      = 0;
volatile int dma_client_done    = 0;
volatile int wdt_irq_fired      = 0;

void uart_irq_handler(void)     /* vector table IRQ0 */
{
    irq_count++;
    send_string("[IRQ] UART interrupt! INTID=0\n");
}

void dma_irq_handler(void)      /* vector table IRQ1 */
{
    dma_irq_fired++;
    send_string("[IRQ] DMA done! INTID=1\n");
}

void timer_irq_handler(void)    /* vector table IRQ2 */
{
    /* timer interrupt — not exercised in this demo */
}

void dma_client_irq_handler(void)  /* vector table IRQ3 */
{
    dma_client_done++;
    send_string("[IRQ] DMA client done! INTID=3\n");
}

void wdt_irq_handler(void)         /* vector table IRQ4 */
{
    wdt_irq_fired++;
    send_string("[IRQ] WDT pre-reset warning IRQ! INTID=4\n");
}

/* -----------------------------------------------------------------------
 * Firmware entry point
 * ----------------------------------------------------------------------- */
void main(void)
{
    uint32_t i;

    /* Enable the device */
    mmio_write32(CTRL_REG, 0x1);

    send_string("=== MMIO SockDev Interrupt Demo ===\n");
    send_string("=== KX6625, Hello World ===\n");
    send_string("[FW] Device enabled.\n");

    /* Initialise NVIC */
    nvic_init();
    send_string("[FW] NVIC initialised (IRQ0=UART, IRQ1=DMA, IRQ2=Timer).\n");

    /* Enable IRQs globally (clear PRIMASK) */
    __asm__ volatile ("cpsie i" ::: "memory");
    send_string("[FW] IRQs enabled. Waiting for UART interrupt from Python server...\n");
    send_string("[FW] (Python server will assert IRQ ~2 s after connection)\n");

    /*
     * ── Phase 1: UART IRQ demo ────────────────────────────────────────────
     * Cortex-M hardware calls uart_irq_handler() automatically.
     * We just spin on WFI until the handler increments irq_count.
     */
    while (irq_count == 0) {
        __asm__ volatile ("wfi");
    }

    send_string("[FW] UART interrupt handled successfully!\n");

    /*
     * ── Phase 2: DMA memory-to-memory copy demo ───────────────────────────
     *
     * 1. Firmware fills SRAM source buffer with 0x01..0x20.
     * 2. Writes DMA registers: SRC=0x20000000, DST=0x20000200, LEN=32.
     * 3. Sets CTRL.START to kick off the transfer.
     * 4. DMA device (Python) reads SRAM via mem-chardev, writes to DST.
     * 5. DMA asserts IRQ33 when done — dma_irq_handler() is called.
     * 6. Firmware verifies DST matches SRC.
     */
    send_string("[FW] Starting DMA demo: SRAM 0x20001000 -> 0x20002000, 32 bytes.\n");

    /* 1. Fill source buffer */
    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_DEMO_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_DEMO_DST;
        for (i = 0; i < DMA_DEMO_LEN; i++) src[i] = (uint8_t)(i + 1);
        for (i = 0; i < DMA_DEMO_LEN; i++) dst[i] = 0xFF;  /* poison dst */
    }

    /* 2+3. Program DMA CH0 and start */
    mmio_write32(DMA_CH0_SRC_ADDR_REG, (uint32_t)DMA_DEMO_SRC);
    mmio_write32(DMA_CH0_DST_ADDR_REG, (uint32_t)DMA_DEMO_DST);
    mmio_write32(DMA_CH0_LENGTH_REG,   DMA_DEMO_LEN);
    mmio_write32(DMA_CH0_CTRL_REG,     0x3u);  /* START | ENABLE */

    send_string("[FW] DMA started. Waiting for IRQ7 (DMA done)...\n");

    /* 4. Wait for DMA IRQ — handler sets dma_irq_fired */
    while (!dma_irq_fired) {
        __asm__ volatile ("wfi");
    }

    /* 5. Verify */
    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_DEMO_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_DEMO_DST;
        int ok = 1;
        for (i = 0; i < DMA_DEMO_LEN; i++) {
            if (dst[i] != src[i]) { ok = 0; break; }
        }
        send_string(ok ? "[DMA] Verification PASSED!\n" : "[DMA] Verification FAILED!\n");
    }

    send_string("[FW] Demo complete.\n");

    /*
     * ── Phase 3: DMA client interface demo ───────────────────────────────
     *
     * Demonstrates the DMA client (DREQ/DACK) architecture:
     *   1. Firmware fills SRAM source buffer.
     *   2. Programs DmaClientDemoDevice registers (same as DMA, but the
     *      device internally uses DmaClientHandle — no direct MemChannel).
     *   3. Writes CTRL.START → device asserts DREQ → DmaController accepts
     *      (DACK) → copies data after transfer_ticks virtual ticks.
     *   4. DmaController calls device callback → device sets STATUS.DONE
     *      and pulses IRQ3.
     *   5. Firmware verifies DST == SRC.
     */
    send_string("[FW] DMA client test: SRAM 0x20003000 -> 0x20004000, 32 bytes.\n");

    /* 1. Fill source buffer */
    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_CLIENT_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_CLIENT_DST;
        for (i = 0; i < DMA_CLIENT_LEN; i++) src[i] = (uint8_t)(0xA0 + i);
        for (i = 0; i < DMA_CLIENT_LEN; i++) dst[i] = 0xFF;  /* poison dst */
    }

    /* 2+3. Program DmaClientDemoDevice and start */
    mmio_write32(DMA_CLIENT_DEMO_SRC_ADDR_REG, (uint32_t)DMA_CLIENT_SRC);
    mmio_write32(DMA_CLIENT_DEMO_DST_ADDR_REG, (uint32_t)DMA_CLIENT_DST);
    mmio_write32(DMA_CLIENT_DEMO_LENGTH_REG,   DMA_CLIENT_LEN);
    mmio_write32(DMA_CLIENT_DEMO_CTRL_REG,     0x1u);  /* START */

    send_string("[FW] DMA client transfer started. Waiting for IRQ3...\n");

    /* 4. Wait for DMA client IRQ */
    while (!dma_client_done) {
        __asm__ volatile ("wfi");
    }

    /* 5. Verify */
    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_CLIENT_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_CLIENT_DST;
        int ok = 1;
        for (i = 0; i < DMA_CLIENT_LEN; i++) {
            if (dst[i] != src[i]) { ok = 0; break; }
        }
        send_string(ok ? "[DMA-CLIENT] Transfer verified PASSED!\n"
                       : "[DMA-CLIENT] Transfer verified FAILED!\n");
    }

    send_string("[FW] All demos complete.\n");

    /*
     * ── Phase 4: CRC-32 hardware accelerator test ─────────────────────────────────────
     *
     * Test vector: CRC-32("123456789") = 0xCBF43926
     * Algorithm  : CRC-32/ISO-HDLC (Ethernet / ZIP / PNG polynomial)
     *
     * Firmware sequence:
     *   1. Write CTRL = 0x1 to reset the accumulator to 0xFFFFFFFF.
     *   2. Write each byte of the test string one at a time to DATA.
     *   3. Read RESULT to obtain the final CRC.
     *   4. Compare against the known reference value 0xCBF43926.
     */
    /*
     * ── Phase 4a: CRC-32 direct-write test ────────────────────────────────────
     *
     * Test vector: CRC-32("123456789") = 0xCBF43926
     * Algorithm  : CRC-32/ISO-HDLC (Ethernet / ZIP / PNG polynomial)
     *
     * Firmware sequence:
     *   1. Write CTRL = 0x1 to reset the accumulator to 0xFFFFFFFF.
     *   2. Write each byte of the test string one at a time to DATA.
     *   3. Read RESULT to obtain the final CRC.
     *   4. Compare against the known reference value 0xCBF43926.
     */
    send_string("[FW] CRC test: computing CRC-32 of \"123456789\".\n");

    /* 1. Reset the CRC accumulator */
    mmio_write32(CRC_CTRL_REG, CRC_CTRL_RESET);

    /* 2. Feed each byte of \"123456789\" (ASCII 0x31..0x39) */
    {
        static const uint8_t crc_data[] = {
            0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
        };
        for (i = 0; i < 9U; i++) {
            mmio_write8(CRC_DATA_REG, crc_data[i]);
        }
    }

    /* 3. Read result and verify */
    {
        uint32_t crc_result = mmio_read32(CRC_RESULT_REG);
        if (crc_result == CRC_EXPECTED) {
            send_string("[CRC] Result 0xCBF43926 PASSED!\n");
        } else {
            send_string("[CRC] Result FAILED!\n");
        }
    }

    /*
     * ── Phase 4b: DMA → CRC (M2P, fixed destination) ─────────────────────
     *
     * Demonstrates decoupled M2P DMA: the CRC device has no interface to
     * the DMA controller.  The DMA engine reads from SRAM (incr src addr)
     * and writes each byte to CRC_DATA_REG (fixed dest addr), feeding
     * the CRC accumulator byte-by-byte via the memory bus.
     *
     *   DMA CH0 MODE.DEST_FIXED = 1  →  M2P transfer:
     *     src: 0x20005000 (SRAM, incremented each byte)
     *     dst: CRC_DATA_REG (0x40008000, fixed)
     *     len: 9 bytes
     */
    send_string("[FW] DMA-CRC test: M2P DMA feeding CRC-32 engine.\n");

    /* 1. Prepare source data in SRAM @ DMA_CRC_SRC */
    {
        static const uint8_t crc_data[] = {
            0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
        };
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)DMA_CRC_SRC;
        for (i = 0; i < 9U; i++) buf[i] = crc_data[i];
    }

    /* 2. Reset CRC accumulator before the DMA feed */
    mmio_write32(CRC_CTRL_REG, CRC_CTRL_RESET);

    /* 3. Program DMA CH0: src=SRAM, dst=CRC_DATA_REG (fixed), len=9 */
    mmio_write32(DMA_CH0_SRC_ADDR_REG, (uint32_t)DMA_CRC_SRC);
    mmio_write32(DMA_CH0_DST_ADDR_REG, (uint32_t)CRC_DATA_REG);
    mmio_write32(DMA_CH0_LENGTH_REG,   9U);
    mmio_write32(DMA_CH0_SRC_MODE_REG, DMA_ADDR_INCR);  /* src increments (SRAM) */
    mmio_write32(DMA_CH0_DST_MODE_REG, DMA_ADDR_FIXED); /* dst fixed (CRC_DATA_REG) */

    /* 4. Arm DMA done flag then start transfer */
    dma_irq_fired = 0;
    mmio_write32(DMA_CH0_CTRL_REG, 0x1u);  /* START */
    send_string("[FW] DMA-CRC started. Waiting for DMA done IRQ...\n");

    /* 5. Wait for DMA completion IRQ (same IRQ1 as Phase 2) */
    while (!dma_irq_fired) {
        __asm__ volatile ("wfi");
    }

    /* 6. Read CRC result (accumulator fed by DMA) and verify */
    {
        uint32_t dma_crc = mmio_read32(CRC_RESULT_REG);
        if (dma_crc == CRC_EXPECTED) {
            send_string("[DMA-CRC] Result 0xCBF43926 PASSED!\n");
        } else {
            send_string("[DMA-CRC] Result FAILED!\n");
        }
    }

    send_string("[FW] All tests done.\n");

    /*
     * ── Phase 5: Watchdog Timer demo ──────────────────────────────────────
     *
     * On the first boot  (RESET_REASON == 0 = POR):
     *   1. Report it is a power-on reset.
     *   2. Load the WDT with 200 ms, enable with INT_ENABLE.
     *   3. KICK twice (at ~50 ms virtual intervals) to prove the reload works.
     *   4. Stop kicking — the WDT fires after 200 ms of virtual time.
     *   5. The WDT model: sets RESET_REASON=1, TIMEOUT_CNT++, then sends
     *      a byte via rst-chardev → QEMU reset.
     *
     * On the second boot (RESET_REASON == 1 = WDT reset):
     *   1. Detect the warm boot, print TIMEOUT_CNT.
     *   2. Disable WDT so it does not reset again.
     *   3. Print "WDT demo complete" and idle.
     */
    {
        uint32_t reason = mmio_read32(WDT_RESET_REASON_REG);
        if (reason == WDT_REASON_WDT) {
            /* ── Second boot: we came back from a WDT reset ────────────── */
            uint32_t cnt = mmio_read32(WDT_TIMEOUT_CNT_REG);
            send_string("[WDT] Warm boot detected: RESET_REASON=WDT\n");
            send_string("[WDT] timeout_cnt=");
            /* Print decimal count (always small — just handle 0-9) */
            send_char((char)('0' + (cnt % 10)));
            send_string("\n");
            send_string("[WDT] WDT demo complete.\n");
            /* Disable WDT so we do not reset again */
            mmio_write32(WDT_CTRL_REG, 0x0U);
        } else {
            /* ── First boot: power-on reset ────────────────────────────── */
            send_string("[WDT] Power-on reset (RESET_REASON=POR)\n");
            send_string("[WDT] Loading WDT 200 ms, kicking twice then letting it fire...\n");

            /* Program the watchdog */
            mmio_write32(WDT_LOAD_REG, 200U);
            mmio_write32(WDT_CTRL_REG, WDT_CTRL_ENABLE | WDT_CTRL_INT_ENABLE);

            /* Kick 1 — reload countdown */
            mmio_write32(WDT_KICK_REG, 0x1U);
            send_string("[WDT] Kick 1\n");

            /* Spin a while (simulate useful work), then kick again */
            for (volatile uint32_t d = 0; d < 50000U; d++) { }
            mmio_write32(WDT_KICK_REG, 0x1U);
            send_string("[WDT] Kick 2\n");

            /* Now stop kicking — WDT will fire after 200 ms virtual time */
            send_string("[WDT] Waiting for WDT timeout and system reset...\n");

            /* Spin until WDT fires (QEMU system reset will interrupt this) */
            while (1) {
                __asm__ volatile ("wfi");
            }
        }
    }

    /* Idle forever (reached only on WDT warm-boot path after disabling WDT) */
    while (1) {
        __asm__ volatile ("wfi");
    }
}
