#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "dma.h"
#include "mmio.h"

#define DMA_DEMO_SRC       (SRAM_BASE + 0x1000U)
#define DMA_DEMO_DST       (SRAM_BASE + 0x2000U)
#define DMA_DEMO_LEN       32U

static volatile int dma_irq_fired = 0;

void dma_irq_handler(void)
{
    dma_irq_fired++;
    send_string("[IRQ] DMA done! INTID=1\n");
}

void dma_clear_irq_done(void)
{
    dma_irq_fired = 0;
}

void dma_wait_irq_done(void)
{
    while (!dma_irq_fired) {
        __asm__ volatile ("wfi");
    }
}

void test_dma_m2m(void)
{
    uint32_t i;
    send_string("[FW] Starting DMA demo: SRAM 0x20001000 -> 0x20002000, 32 bytes.\n");

    {
        volatile uint8_t *src = (volatile uint8_t *)DMA_DEMO_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)DMA_DEMO_DST;
        for (i = 0; i < DMA_DEMO_LEN; i++) src[i] = (uint8_t)(i + 1);
        for (i = 0; i < DMA_DEMO_LEN; i++) dst[i] = 0xFF;
    }

    dma_clear_irq_done();
    mmio_write32(DMA_CH0_SRC_ADDR_REG, (uint32_t)DMA_DEMO_SRC);
    mmio_write32(DMA_CH0_DST_ADDR_REG, (uint32_t)DMA_DEMO_DST);
    mmio_write32(DMA_CH0_LENGTH_REG, DMA_DEMO_LEN);
    send_string("[FW] DMA started. Waiting for IRQ1 (DMA done)...\n");
    mmio_write32(DMA_CH0_CTRL_REG, 0x3u);
    dma_wait_irq_done();

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
