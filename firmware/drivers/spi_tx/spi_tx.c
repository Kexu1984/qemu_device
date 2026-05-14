#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "mmio.h"
#include "spi_tx.h"

#define SPI_TX_CTRL_ENABLE     0x00000001U
#define SPI_TX_CTRL_START      0x00000002U
#define SPI_TX_CTRL_SOFT_RESET 0x00000008U
#define SPI_TX_CTRL_CS_AUTO    0x00000010U

#define SPI_TX_STATUS_DONE     0x00000002U
#define SPI_TX_STATUS_ERROR    0x00000004U

#define SPI_TX_INT_DONE        0x00000001U
#define SPI_TX_INT_THRESHOLD   0x00000002U
#define SPI_TX_INT_ERROR       0x00000004U

static volatile int spi_tx_done_irq_fired = 0;
static volatile int spi_tx_error_irq_fired = 0;

static void spi_tx_wait_done_or_error(void)
{
    while (!spi_tx_done_irq_fired && !spi_tx_error_irq_fired) {
        __asm__ volatile ("wfi");
    }
}

void spi_tx_init(void)
{
    mmio_write32(SV_ISLAND_SPI_TX_CTRL_REG, SPI_TX_CTRL_SOFT_RESET);
    mmio_write32(SV_ISLAND_SPI_TX_INT_STATUS_REG, 0xFFFFFFFFU);
    mmio_write32(SV_ISLAND_SPI_TX_INT_ENABLE_REG, SPI_TX_INT_DONE | SPI_TX_INT_ERROR);
    spi_tx_done_irq_fired = 0;
    spi_tx_error_irq_fired = 0;
}

void spi_tx_config(uint32_t mode, uint32_t frame_bits, uint32_t lsb_first, uint32_t baud_div)
{
    uint32_t frame_bits_minus_1 = (frame_bits == 0U) ? 0U : (frame_bits - 1U);
    uint32_t cfg = (mode & 0x3U) | ((lsb_first & 0x1U) << 2) |
                   ((frame_bits_minus_1 & 0x1FU) << 8);
    mmio_write32(SV_ISLAND_SPI_TX_CFG_REG, cfg);
    mmio_write32(SV_ISLAND_SPI_TX_BAUD_DIV_REG, baud_div);
}

void spi_tx_write_frame(uint32_t frame)
{
    mmio_write32(SV_ISLAND_SPI_TX_TXDATA_REG, frame);
}

void spi_tx_start(uint32_t frame_count)
{
    spi_tx_done_irq_fired = 0;
    spi_tx_error_irq_fired = 0;
    mmio_write32(SV_ISLAND_SPI_TX_FRAME_COUNT_REG, frame_count);
    mmio_write32(SV_ISLAND_SPI_TX_CTRL_REG, SPI_TX_CTRL_ENABLE | SPI_TX_CTRL_START | SPI_TX_CTRL_CS_AUTO);
}

uint32_t spi_tx_status(void)
{
    return mmio_read32(SV_ISLAND_SPI_TX_STATUS_REG);
}

uint32_t spi_tx_error(void)
{
    return mmio_read32(SV_ISLAND_SPI_TX_ERROR_REG);
}

uint32_t spi_tx_irq_status(void)
{
    return mmio_read32(SV_ISLAND_SPI_TX_INT_STATUS_REG);
}

void spi_tx_clear_irq(uint32_t mask)
{
    mmio_write32(SV_ISLAND_SPI_TX_INT_STATUS_REG, mask);
}

void spi_tx_handle_irq(void)
{
    uint32_t irq_status = spi_tx_irq_status();
    if (irq_status == 0U) {
        return;
    }

    spi_tx_clear_irq(irq_status);
    if (irq_status & SPI_TX_INT_DONE) {
        spi_tx_done_irq_fired++;
        send_string("[IRQ] SV SPI TX done! INTID=5\n");
    }
    if (irq_status & SPI_TX_INT_ERROR) {
        spi_tx_error_irq_fired++;
        send_string("[IRQ] SV SPI TX error! INTID=5\n");
    }
}

void test_spi_tx(void)
{
    int ok;

    send_string("[SPI] SV SPI TX test.\n");
    spi_tx_init();

    send_string(mmio_read32(SV_ISLAND_SPI_TX_ID_REG) == SPI_TX_ID_EXPECTED
                ? "[SPI] SPI TX ID SPTX PASSED!\n"
                : "[SPI] SPI TX ID FAILED!\n");

    spi_tx_config(0U, 8U, 0U, 2U);
    spi_tx_write_frame(0xA5U);
    spi_tx_write_frame(0x5AU);
    spi_tx_write_frame(0x3CU);
    ok = mmio_read32(SV_ISLAND_SPI_TX_TX_LEVEL_REG) == 3U;
    spi_tx_start(3U);
    spi_tx_wait_done_or_error();

    ok = ok && !spi_tx_error_irq_fired;
    ok = ok && ((spi_tx_status() & SPI_TX_STATUS_DONE) != 0U);
    ok = ok && (mmio_read32(SV_ISLAND_SPI_TX_TX_LEVEL_REG) == 0U);
    ok = ok && (mmio_read32(SV_ISLAND_SPI_TX_FRAME_DONE_COUNT_REG) == 3U);
    ok = ok && (mmio_read32(SV_ISLAND_SPI_TX_LAST_FRAME_REG) == 0x3CU);
    ok = ok && (mmio_read32(SV_ISLAND_SPI_TX_BIT_COUNT_REG) == 24U);
    send_string(ok ? "[SPI] SPI TX CPU FIFO transfer PASSED!\n"
                   : "[SPI] SPI TX CPU FIFO transfer FAILED!\n");

    spi_tx_init();
    spi_tx_config(0U, 1U, 0U, 2U);
    spi_tx_write_frame(0x1U);
    spi_tx_start(1U);
    spi_tx_wait_done_or_error();
    ok = spi_tx_error_irq_fired && ((spi_tx_status() & SPI_TX_STATUS_ERROR) != 0U) &&
         (spi_tx_error() == 3U);
    send_string(ok ? "[SPI] SPI TX error path PASSED!\n"
                   : "[SPI] SPI TX error path FAILED!\n");
}