#ifndef FIRMWARE_DRIVERS_DMA_H
#define FIRMWARE_DRIVERS_DMA_H

void dma_irq_handler(void);
void dma_clear_irq_done(void);
void dma_wait_irq_done(void);
void test_dma_m2m(void);

#endif /* FIRMWARE_DRIVERS_DMA_H */
