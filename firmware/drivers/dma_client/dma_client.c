#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "dma_client.h"
#include "mmio.h"

#define DMA_CLIENT_SRC     (SRAM_BASE + 0x3000U)
#define DMA_CLIENT_DST     (SRAM_BASE + 0x4000U)
#define DMA_CLIENT_LEN     32U

static volatile int dma_client_done = 0;

void dma_client_irq_handler(void)
{
    dma_client_done++;
    send_string("[IRQ] DMA client done! INTID=3\n");
}

void test_dma_client(void)
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
    mmio_write32(DMA_CLIENT_DEMO_LENGTH_REG, DMA_CLIENT_LEN);
    send_string("[FW] DMA client transfer started. Waiting for IRQ3...\n");
    mmio_write32(DMA_CLIENT_DEMO_CTRL_REG, 0x1u);
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
