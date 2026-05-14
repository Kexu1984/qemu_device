#ifndef FIRMWARE_DRIVERS_SPI_TX_H
#define FIRMWARE_DRIVERS_SPI_TX_H

#include <stdint.h>

#define SPI_TX_ID_EXPECTED 0x58545053U

void spi_tx_init(void);
void spi_tx_config(uint32_t mode, uint32_t frame_bits, uint32_t lsb_first, uint32_t baud_div);
void spi_tx_write_frame(uint32_t frame);
void spi_tx_start(uint32_t frame_count);
uint32_t spi_tx_status(void);
uint32_t spi_tx_error(void);
uint32_t spi_tx_irq_status(void);
void spi_tx_clear_irq(uint32_t mask);
void spi_tx_handle_irq(void);
void test_spi_tx(void);

#endif /* FIRMWARE_DRIVERS_SPI_TX_H */