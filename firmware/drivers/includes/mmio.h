#ifndef FIRMWARE_DRIVERS_MMIO_H
#define FIRMWARE_DRIVERS_MMIO_H

#include <stdint.h>

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

#endif /* FIRMWARE_DRIVERS_MMIO_H */
