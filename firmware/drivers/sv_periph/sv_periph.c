#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "gpio.h"
#include "mmio.h"
#include "sv_periph.h"

#define SV_DMA_SRC         (SRAM_BASE + 0x6300U)
#define SV_DMA_DST         (SRAM_BASE + 0x6400U)
#define SV_DMA_LEN         32U

#define SV_TIMER_CTRL_ENABLE 0x1U
#define SV_TIMER_CTRL_IRQ_EN 0x2U
#define SV_TIMER_STATUS_IRQ  0x1U

#define SV_DMA_ID_EXPECTED  0x414D4453U
#define SV_DMA_CTRL_START   0x1U
#define SV_DMA_CTRL_IRQ_EN  0x2U
#define SV_DMA_STATUS_DONE  0x2U
#define SV_DMA_STATUS_ERROR 0x4U

static volatile int sv_timer_irq_fired = 0;
static volatile int sv_dma_irq_fired = 0;

void sv_timer_irq_handler(void)
{
    uint32_t status = mmio_read32(SV_TIMER_STATUS_REG);
    uint32_t dma_status = mmio_read32(SV_TIMER_DMA_STATUS_REG);
    uint32_t gpio_status = gpio_irq_status();
    if (status & SV_TIMER_STATUS_IRQ) {
        mmio_write32(SV_TIMER_IRQ_CLEAR_REG, SV_TIMER_STATUS_IRQ);
        sv_timer_irq_fired++;
        send_string("[IRQ] SV timer fired! INTID=5\n");
    }
    if (dma_status & (SV_DMA_STATUS_DONE | SV_DMA_STATUS_ERROR)) {
        mmio_write32(SV_TIMER_DMA_IRQ_CLEAR_REG, 1U);
        sv_dma_irq_fired++;
        if (dma_status & SV_DMA_STATUS_DONE) {
            send_string("[IRQ] SV DMA done! INTID=5\n");
        } else {
            send_string("[IRQ] SV DMA error! INTID=5\n");
        }
    }
    if (gpio_status != 0U) {
        gpio_handle_irq();
    }
}

void test_sv_timer(void)
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

void test_sv_dma(void)
{
    uint32_t i;
    int ok = 1;

    send_string("[SVDMA] SV DMA prototype test.\n");
    send_string(mmio_read32(SV_TIMER_DMA_ID_REG) == SV_DMA_ID_EXPECTED
                ? "[SVDMA] SV DMA ID SDMA PASSED!\n"
                : "[SVDMA] SV DMA ID FAILED!\n");

    {
        volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)SV_DMA_SRC;
        volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)SV_DMA_DST;
        for (i = 0; i < SV_DMA_LEN / 4U; i++) {
            src[i] = 0xC0DE0000U + i;
            dst[i] = 0xFFFFFFFFU;
        }
    }

    sv_dma_irq_fired = 0;
    mmio_write32(SV_TIMER_DMA_SRC_ADDR_REG, SV_DMA_SRC);
    mmio_write32(SV_TIMER_DMA_DST_ADDR_REG, SV_DMA_DST);
    mmio_write32(SV_TIMER_DMA_LENGTH_REG, SV_DMA_LEN);
    mmio_write32(SV_TIMER_DMA_CTRL_REG, SV_DMA_CTRL_START | SV_DMA_CTRL_IRQ_EN);
    while (!sv_dma_irq_fired) {
        __asm__ volatile ("wfi");
    }

    if (mmio_read32(SV_TIMER_DMA_ERROR_REG) != 0U) {
        ok = 0;
    }
    {
        volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)SV_DMA_SRC;
        volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)SV_DMA_DST;
        for (i = 0; i < SV_DMA_LEN / 4U; i++) {
            if (dst[i] != src[i]) { ok = 0; break; }
        }
    }

    send_string(ok ? "[SVDMA] SV DMA M2M copy PASSED!\n"
                   : "[SVDMA] SV DMA M2M copy FAILED!\n");
}
