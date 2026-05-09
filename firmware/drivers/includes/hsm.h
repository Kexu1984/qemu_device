#ifndef FIRMWARE_DRIVERS_HSM_H
#define FIRMWARE_DRIVERS_HSM_H

#include <stdint.h>

#define HSM_TEST_SRC       (SRAM_BASE + 0x6000U)
#define HSM_TEST_DST       (SRAM_BASE + 0x6100U)
#define HSM_CMAC_DST       (SRAM_BASE + 0x6200U)

#define HSM_CTRL_START       0x1U
#define HSM_CTRL_IRQ_ENABLE  0x2U
#define HSM_STATUS_ERROR     0x4U
#define HSM_INT_DONE         0x1U
#define HSM_INT_ERROR        0x2U
#define HSM_MODE_CBC         0x1U
#define HSM_MODE_CMAC        0x4U
#define HSM_KEY_ID_REGISTER  15U

void hsm_write_iv(void);
int hsm_wait_done(void);
void hsm_irq_handler(void);
void test_hsm(void);

#endif /* FIRMWARE_DRIVERS_HSM_H */
