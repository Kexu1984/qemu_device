#include <stdint.h>
#include "mmio_devices.h"
#include "cru.h"
#include "mmio.h"

void cru_init_all_devices(void)
{
    mmio_write32(CRU_CLK_EN0_REG, CRU_ALL_DEVICES);
    mmio_write32(CRU_RST_CTRL0_REG, CRU_ALL_DEVICES);
}

uint32_t cru_reset_reason(void)
{
    return mmio_read32(CRU_RESET_REASON_REG);
}
