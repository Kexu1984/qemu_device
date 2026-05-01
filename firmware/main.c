/*
 * FreeRTOS Cortex-M4 firmware — MMIO socket device + interrupt test
 *
 * IO addresses and IRQ numbers are NOT hardcoded here.  They come from
 * the auto-generated header build/generated/mmio_devices.h, which is
 * produced by scripts/gen_device_code.py reading spec/devices.yaml.
 *
 * Memory map (KX6625 SoC, Cortex-M4):
 *   0x00000000  FLASH — vector table + code  (512 KB)
 *   0xE000E000  NVIC (Nested Vectored Interrupt Controller)
 *   0x20000000  SRAM (128 KB)
 *   0x40004000  console_uart device (mmio-sockdev, IRQ0)
 *   0x40005000  dma device          (mmio-sockdev, IRQ1)
 *   0x40006000  timer0 device       (mmio-sockdev, IRQ2)
 *   0x40008000  crc device          (mmio-sockdev, polled)
 *   0x40009000  wdt device          (mmio-sockdev, IRQ4)
 *   0x4000B000  sv_timer device     (mmio-sockdev -> Verilated SV, IRQ5)
 */

#include <stdint.h>
#include "FreeRTOS.h"
#include "task.h"
#include "mmio_devices.h"   /* auto-generated from spec/devices.yaml */
#include "ipc.h"             /* IPC + SYSCTRL for dual-CPU demo */

/* -----------------------------------------------------------------------
 * Convenience aliases — map logical names to generated symbolic names.
 * ----------------------------------------------------------------------- */
#define TXDATA_REG        CONSOLE_UART_TXDATA_REG
#define STATUS_REG        CONSOLE_UART_STATUS_REG
#define CTRL_REG          CONSOLE_UART_CTRL_REG
#define RXDATA_REG        CONSOLE_UART_RXDATA_REG

/* STATUS register bits */
#define UART_STATUS_TXREADY  (1u << 0)
#define UART_STATUS_RXREADY  (1u << 1)

/* CTRL register bits */
#define UART_CTRL_ENABLE     (1u << 0)
#define UART_CTRL_RX_IRQ_EN  (1u << 1)

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

/* SV timer register bit definitions */
#define SV_TIMER_CTRL_ENABLE 0x1U
#define SV_TIMER_CTRL_IRQ_EN 0x2U
#define SV_TIMER_STATUS_IRQ  0x1U

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

/* Read one character from UART RX FIFO.
 * Enables RX_IRQ so WFI can be woken by the IRQ, then polls RXREADY. */
static char read_char(void)
{
    /* Enable RX IRQ so WFI wakes on incoming bytes */
    mmio_write32(CTRL_REG, UART_CTRL_ENABLE | UART_CTRL_RX_IRQ_EN);
    while (!(mmio_read32(STATUS_REG) & UART_STATUS_RXREADY)) {
        __asm__ volatile ("wfi");
    }
    return (char)(mmio_read32(RXDATA_REG) & 0x7F);
}

/* Read a line into buf (up to len-1 chars), terminated by '\n'.
 * Echoes each character back to terminal. Returns number of chars read. */
static int recv_line(char *buf, int len)
{
    int n = 0;
    while (n < len - 1) {
        char c = read_char();
        if (c == '\n' || c == '\r') {
            send_string("\n");  /* echo newline */
            break;
        }
        send_char(c);           /* local echo */
        buf[n++] = c;
    }
    buf[n] = '\0';
    return n;
}

/* -----------------------------------------------------------------------
 * Cortex-M4 NVIC initialisation
 *
 * NVIC register addresses (derived from NVIC_BASE = 0xE000E000):
 *   NVIC_ISER0 (0xE000E100) — IRQ enable set  for IRQ  0-31
 *   NVIC_ICPR0 (0xE000E280) — IRQ clear pending for IRQ  0-31
 *   NVIC_IPR0  (0xE000E400) — priority bytes for IRQ 0-3
 *
 * Enables IRQ 0 (UART), IRQ 1 (DMA), IRQ 2 (Timer0), IRQ 5 (SV timer).
 * KX6625 has 16 external IRQs (0-15); IRQs 0/1/2 are our devices.
 * ----------------------------------------------------------------------- */
static void nvic_init(void)
{
    /* 1. Clear any stale pending state for IRQ 0-5 */
    mmio_write32(NVIC_ICPR0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) | (1u << 4) | (1u << 5));

    /* 2. Set priority 0 (highest) for IRQ 0-7 */
    mmio_write32(NVIC_IPR0, 0x00000000U);
    mmio_write32(NVIC_IPR1, 0x00000000U);

    /* 3. Enable IRQ 0-5 in ISER0 */
    mmio_write32(NVIC_ISER0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) | (1u << 4) | (1u << 5));
}

/* -----------------------------------------------------------------------
 * IRQ handlers — called directly from the vector table (start.S).
 * Cortex-M hardware saves/restores the exception frame automatically;
 * plain C functions with no special attribute are sufficient.
 * ----------------------------------------------------------------------- */
volatile int irq_count          = 0;
volatile int dma_irq_fired      = 0;
volatile int dma_client_done    = 0;
volatile int wdt_irq_fired      = 0;
volatile int sv_timer_irq_fired = 0;

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

void sv_timer_irq_handler(void)    /* vector table IRQ5 */
{
    uint32_t status = mmio_read32(SV_TIMER_STATUS_REG);
    if (status & SV_TIMER_STATUS_IRQ) {
        mmio_write32(SV_TIMER_IRQ_CLEAR_REG, SV_TIMER_STATUS_IRQ);
        sv_timer_irq_fired++;
        send_string("[IRQ] SV timer fired! INTID=5\n");
    }
}

/* -----------------------------------------------------------------------
 * Individual test functions (called from the command menu)
 * ----------------------------------------------------------------------- */

/* Test 1: UART IRQ demo */
static void test_uart_irq(void)
{
    send_string("[FW] IRQs enabled. Waiting for UART interrupt from Python server...\n");
    send_string("[FW] (Python server will assert IRQ ~2 s after connection)\n");
    while (irq_count == 0) {
        __asm__ volatile ("wfi");
    }
    send_string("[FW] UART interrupt handled successfully!\n");
}

/* Test 2: DMA memory-to-memory copy */
static void test_dma_m2m(void)
{
    uint32_t i;
    send_string("[FW] Starting DMA demo: SRAM 0x20001000 -> 0x20002000, 32 bytes.\n");

    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_DEMO_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_DEMO_DST;
        for (i = 0; i < DMA_DEMO_LEN; i++) src[i] = (uint8_t)(i + 1);
        for (i = 0; i < DMA_DEMO_LEN; i++) dst[i] = 0xFF;
    }

    dma_irq_fired = 0;
    mmio_write32(DMA_CH0_SRC_ADDR_REG, (uint32_t)DMA_DEMO_SRC);
    mmio_write32(DMA_CH0_DST_ADDR_REG, (uint32_t)DMA_DEMO_DST);
    mmio_write32(DMA_CH0_LENGTH_REG,   DMA_DEMO_LEN);
    send_string("[FW] DMA started. Waiting for IRQ7 (DMA done)...\n");
    mmio_write32(DMA_CH0_CTRL_REG,     0x3u);
    while (!dma_irq_fired) {
        __asm__ volatile ("wfi");
    }

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
}

/* Test 3: DMA client interface */
static void test_dma_client(void)
{
    uint32_t i;
    send_string("[FW] DMA client test: SRAM 0x20003000 -> 0x20004000, 32 bytes.\n");

    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_CLIENT_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_CLIENT_DST;
        for (i = 0; i < DMA_CLIENT_LEN; i++) src[i] = (uint8_t)(0xA0 + i);
        for (i = 0; i < DMA_CLIENT_LEN; i++) dst[i] = 0xFF;
    }

    dma_client_done = 0;
    mmio_write32(DMA_CLIENT_DEMO_SRC_ADDR_REG, (uint32_t)DMA_CLIENT_SRC);
    mmio_write32(DMA_CLIENT_DEMO_DST_ADDR_REG, (uint32_t)DMA_CLIENT_DST);
    mmio_write32(DMA_CLIENT_DEMO_LENGTH_REG,   DMA_CLIENT_LEN);
    send_string("[FW] DMA client transfer started. Waiting for IRQ3...\n");
    mmio_write32(DMA_CLIENT_DEMO_CTRL_REG,     0x1u);
    while (!dma_client_done) {
        __asm__ volatile ("wfi");
    }

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
}

/* Test 4: CRC-32 hardware accelerator (direct + DMA→CRC) */
static void test_crc(void)
{
    uint32_t i;

    /* 4a: direct write */
    send_string("[FW] CRC test: computing CRC-32 of \"123456789\".\n");
    mmio_write32(CRC_CTRL_REG, CRC_CTRL_RESET);
    {
        static const uint8_t crc_data[] = {
            0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
        };
        for (i = 0; i < 9U; i++) mmio_write8(CRC_DATA_REG, crc_data[i]);
    }
    {
        uint32_t r = mmio_read32(CRC_RESULT_REG);
        send_string(r == CRC_EXPECTED ? "[CRC] Result 0xCBF43926 PASSED!\n"
                                      : "[CRC] Result FAILED!\n");
    }

    /* 4b: DMA → CRC */
    send_string("[FW] DMA-CRC test: M2P DMA feeding CRC-32 engine.\n");
    {
        static const uint8_t crc_data[] = {
            0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
        };
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)DMA_CRC_SRC;
        for (i = 0; i < 9U; i++) buf[i] = crc_data[i];
    }
    mmio_write32(CRC_CTRL_REG, CRC_CTRL_RESET);
    mmio_write32(DMA_CH0_SRC_ADDR_REG, (uint32_t)DMA_CRC_SRC);
    mmio_write32(DMA_CH0_DST_ADDR_REG, (uint32_t)CRC_DATA_REG);
    mmio_write32(DMA_CH0_LENGTH_REG,   9U);
    mmio_write32(DMA_CH0_SRC_MODE_REG, DMA_ADDR_INCR);
    mmio_write32(DMA_CH0_DST_MODE_REG, DMA_ADDR_FIXED);
    dma_irq_fired = 0;
    send_string("[FW] DMA-CRC started. Waiting for DMA done IRQ...\n");
    mmio_write32(DMA_CH0_CTRL_REG, 0x1u);
    while (!dma_irq_fired) {
        __asm__ volatile ("wfi");
    }
    {
        uint32_t r = mmio_read32(CRC_RESULT_REG);
        send_string(r == CRC_EXPECTED ? "[DMA-CRC] Result 0xCBF43926 PASSED!\n"
                                      : "[DMA-CRC] Result FAILED!\n");
    }
    send_string("[FW] All tests done.\n");
}

/* Test 6: Dual-CPU IPC — CPU0 posts a request; CPU1 processes it */
static void test_dual_cpu(void)
{
    const uint32_t arg    = 0xDEADBEEFU;
    const uint32_t expect = arg ^ 0xCAFEBABEU;   /* = 0x14537451 */

    send_string("[IPC] Dual-CPU IPC test: CPU0 -> CPU1 XOR 0xDEADBEEF ^ 0xCAFEBABE\n");

    /* Ensure args are visible before posting the PENDING flag. */
    IPC_ARG0 = arg;
    IPC_REQ  = IPC_REQ_ECHO_XOR;
    __asm__ volatile ("dsb" ::: "memory");
    IPC_STATUS = IPC_STATUS_PENDING;  /* CPU1 will see this and start */

    /* Spin until CPU1 writes DONE.
     * ISB forces a TCG TB exit every iteration so the load is fresh. */
    while (IPC_STATUS != IPC_STATUS_DONE) {
        __asm__ volatile ("isb" ::: "memory");
    }

    uint32_t resp = IPC_RESP;
    IPC_STATUS    = IPC_STATUS_IDLE;  /* reset for next round */

    if (resp == expect) {
        send_string("[IPC] Dual-CPU IPC PASS: CPU1 responded correctly\n");
    } else {
        send_string("[IPC] Dual-CPU IPC FAIL: unexpected response\n");
    }
}

/* Test 7: SystemVerilog APB timer through mmio-sockdev */
static void test_sv_timer(void)
{
    send_string("[SVTIMER] Starting SystemVerilog APB timer test.\n");
    sv_timer_irq_fired = 0;

    mmio_write32(SV_TIMER_IRQ_CLEAR_REG, SV_TIMER_STATUS_IRQ);
    mmio_write32(SV_TIMER_LOAD_REG, 8U);
    send_string("[SVTIMER] LOAD=8 cycles, enabling IRQ.\n");
    mmio_write32(SV_TIMER_CTRL_REG, SV_TIMER_CTRL_ENABLE | SV_TIMER_CTRL_IRQ_EN);

    while (!sv_timer_irq_fired) {
        __asm__ volatile ("wfi");
    }

    if ((mmio_read32(SV_TIMER_STATUS_REG) & SV_TIMER_STATUS_IRQ) == 0U) {
        send_string("[SVTIMER] IRQ observed and cleared PASSED!\n");
    } else {
        send_string("[SVTIMER] IRQ clear FAILED!\n");
    }
}

/* Test 5: Watchdog Timer (handles warm-boot detection internally) */
static void test_wdt(void)
{
    uint32_t reason = mmio_read32(WDT_RESET_REASON_REG);
    if (reason == WDT_REASON_WDT) {
        uint32_t cnt = mmio_read32(WDT_TIMEOUT_CNT_REG);
        send_string("[WDT] Warm boot detected: RESET_REASON=WDT\n");
        send_string("[WDT] timeout_cnt=");
        send_char((char)('0' + (cnt % 10)));
        send_string("\n");
        send_string("[WDT] WDT demo complete.\n");
        mmio_write32(WDT_CTRL_REG, 0x0U);
    } else {
        send_string("[WDT] Power-on reset (RESET_REASON=POR)\n");
        send_string("[WDT] Loading WDT 200 ms, kicking twice then letting it fire...\n");
        mmio_write32(WDT_LOAD_REG, 200U);
        mmio_write32(WDT_CTRL_REG, WDT_CTRL_ENABLE | WDT_CTRL_INT_ENABLE);
        mmio_write32(WDT_KICK_REG, 0x1U);
        send_string("[WDT] Kick 1\n");
        for (volatile uint32_t d = 0; d < 50000U; d++) { }
        mmio_write32(WDT_KICK_REG, 0x1U);
        send_string("[WDT] Kick 2\n");
        send_string("[WDT] Waiting for WDT timeout and system reset...\n");
        while (1) { __asm__ volatile ("wfi"); }
    }
}

/* -----------------------------------------------------------------------
 * Firmware entry point
 * ----------------------------------------------------------------------- */
void vAssertCalled(const char *file, uint32_t line)
{
    (void)file;
    (void)line;
    taskDISABLE_INTERRUPTS();
    for (;;) {
    }
}

void vApplicationMallocFailedHook(void)
{
    vAssertCalled(__FILE__, __LINE__);
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
    (void)task;
    (void)task_name;
    vAssertCalled(__FILE__, __LINE__);
}

static void app_task(void *arg)
{
    (void)arg;
    char cmd_buf[4];

    /* Enable UART (TX-only until menu loop enables RX IRQ) */
    mmio_write32(CTRL_REG, UART_CTRL_ENABLE);

    send_string("=== MMIO SockDev Interrupt Demo ===\n");
    send_string("=== KX6625, Hello World ===\n");
    send_string("[FW] Device enabled.\n");

    /* Initialise NVIC */
    nvic_init();
    send_string("[FW] NVIC initialised (IRQ0=UART, IRQ1=DMA, IRQ2=Timer, IRQ5=SV timer).\n");

    /* Enable IRQs globally */
    __asm__ volatile ("cpsie i" ::: "memory");

    /* Release CPU1 from reset — it will start polling IPC immediately */
    SYSCTRL_CPU1RST = 1U;
    send_string("[FW] CPU1 released from reset.\n");

    /* WDT warm-boot fast-path: if we came back from WDT reset, run test 5
     * immediately to print the warm-boot message, then show the menu. */
    if (mmio_read32(WDT_RESET_REASON_REG) == WDT_REASON_WDT) {
        test_wdt();
    }

    /* ── Command prompt loop ─────────────────────────────────────────────
     *
     * Available commands:
     *   1  UART IRQ demo
     *   2  DMA M2M copy
     *   3  DMA client interface
     *   4  CRC-32 accelerator (direct + DMA→CRC)
    *   5  Watchdog Timer demo
    *   7  SV APB timer demo
    *   a  All tests in sequence (1→2→3→4→6→7→5)
     */
    while (1) {
        send_string("=== KX6625 Test Menu ===\n");
        send_string(" 1) UART IRQ demo\n");
        send_string(" 2) DMA M2M copy\n");
        send_string(" 3) DMA client\n");
        send_string(" 4) CRC-32\n");
        send_string(" 5) WDT reset\n");
        send_string(" 6) Dual-CPU IPC\n");
        send_string(" 7) SV APB timer\n");
        send_string(" a) All tests\n");
        send_string("# ");

        recv_line(cmd_buf, sizeof(cmd_buf));
        char cmd = cmd_buf[0];

        if (cmd == '1') {
            test_uart_irq();
        } else if (cmd == '2') {
            test_dma_m2m();
        } else if (cmd == '3') {
            test_dma_client();
        } else if (cmd == '4') {
            test_crc();
        } else if (cmd == '5') {
            test_wdt();
            /* test_wdt() with POR path resets QEMU — never returns */
        } else if (cmd == '6') {
            test_dual_cpu();
        } else if (cmd == '7') {
            test_sv_timer();
        } else if (cmd == 'a') {
            irq_count = 0;
            test_uart_irq();
            test_dma_m2m();
            test_dma_client();
            test_crc();
            test_dual_cpu();
            test_sv_timer();
            test_wdt();
            /* If WDT path causes reset, we return here on warm boot */
        } else {
            send_string("[FW] Unknown command. Enter 1-7 or 'a'.\n");
        }
    }
}

void main(void)
{
    if (xTaskCreate(app_task, "kx6625", 1024U, NULL, tskIDLE_PRIORITY + 1U, NULL) != pdPASS) {
        vAssertCalled(__FILE__, __LINE__);
    }

    vTaskStartScheduler();

    for (;;) {
    }
}
