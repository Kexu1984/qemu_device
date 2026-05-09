#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "crc.h"
#include "dma.h"
#include "mmio.h"

#define DMA_ADDR_FIXED     0x1U
#define DMA_ADDR_INCR      0x0U
#define DMA_CRC_SRC        (SRAM_BASE + 0x5000U)

void test_crc(void)
{
    uint32_t i;

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
    mmio_write32(DMA_CH0_LENGTH_REG, 9U);
    mmio_write32(DMA_CH0_SRC_MODE_REG, DMA_ADDR_INCR);
    mmio_write32(DMA_CH0_DST_MODE_REG, DMA_ADDR_FIXED);
    dma_clear_irq_done();
    send_string("[FW] DMA-CRC started. Waiting for DMA done IRQ...\n");
    mmio_write32(DMA_CH0_CTRL_REG, 0x1u);
    dma_wait_irq_done();
    {
        uint32_t r = mmio_read32(CRC_RESULT_REG);
        send_string(r == CRC_EXPECTED ? "[DMA-CRC] Result 0xCBF43926 PASSED!\n"
                                      : "[DMA-CRC] Result FAILED!\n");
    }
    send_string("[FW] All tests done.\n");
}
