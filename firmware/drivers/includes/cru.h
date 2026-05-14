#ifndef FIRMWARE_DRIVERS_CRU_H
#define FIRMWARE_DRIVERS_CRU_H

#include <stdint.h>

#define CRU_BIT_CONSOLE_UART   (1U << 0)
#define CRU_BIT_DMA            (1U << 1)
#define CRU_BIT_TIMER0         (1U << 2)
#define CRU_BIT_DMA_DEMO       (1U << 3)
#define CRU_BIT_CRC            (1U << 4)
#define CRU_BIT_WDT            (1U << 5)
#define CRU_BIT_SV_ISLAND      (1U << 6)
#define CRU_BIT_HSM            (1U << 7)
#define CRU_BIT_OTP            (1U << 8)
#define CRU_ALL_DEVICES        0x1FFU

#define CRU_RESET_REASON_POR    0x00U
#define CRU_RESET_REASON_WDT    0x01U
#define CRU_RESET_REASON_SW_SYS 0x02U
#define CRU_SOFT_SYSRST_KEY     0xDEADBEEFU

void cru_init_all_devices(void);
uint32_t cru_reset_reason(void);

#endif /* FIRMWARE_DRIVERS_CRU_H */
