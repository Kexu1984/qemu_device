#include <stdint.h>
#include "mmio_devices.h"
#include "irq.h"
#include "mmio.h"

void nvic_init(void)
{
    mmio_write32(NVIC_ICPR0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) |
                            (1u << 4) | (1u << 5) | (1u << 6) | (1u << 7) |
                            (1u << 9));
    mmio_write32(NVIC_IPR0, 0x00000000U);
    mmio_write32(NVIC_IPR1, 0x00000000U);
    mmio_write32(NVIC_IPR2, 0x00000000U);
    mmio_write32(NVIC_ISER0, (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3) |
                            (1u << 4) | (1u << 5) | (1u << 6) | (1u << 7) |
                            (1u << 9));
}

void timer_irq_handler(void)
{
}
