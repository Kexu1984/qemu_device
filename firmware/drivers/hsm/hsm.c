#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "hsm.h"
#include "mmio.h"

static volatile int hsm_irq_fired = 0;

void hsm_irq_handler(void)
{
    uint32_t int_status = mmio_read32(HSM_INT_STATUS_REG);
    if (int_status) {
        mmio_write32(HSM_INT_STATUS_REG, int_status);
    }
    if (int_status & HSM_INT_DONE) {
        hsm_irq_fired++;
        send_string("[IRQ] HSM done! INTID=6\n");
    }
    if (int_status & HSM_INT_ERROR) {
        hsm_irq_fired++;
        send_string("[IRQ] HSM error! INTID=6\n");
    }
}

void hsm_write_iv(void)
{
    mmio_write32(HSM_IV_WORD0_REG, 0x03020100U);
    mmio_write32(HSM_IV_WORD1_REG, 0x07060504U);
    mmio_write32(HSM_IV_WORD2_REG, 0x0B0A0908U);
    mmio_write32(HSM_IV_WORD3_REG, 0x0F0E0D0CU);
}

static void hsm_write_key_and_iv(void)
{
    mmio_write32(HSM_KEY_ID_REG, HSM_KEY_ID_REGISTER);
    mmio_write32(HSM_KEY_WORD0_REG, 0x16157E2BU);
    mmio_write32(HSM_KEY_WORD1_REG, 0xA6D2AE28U);
    mmio_write32(HSM_KEY_WORD2_REG, 0x8815F7ABU);
    mmio_write32(HSM_KEY_WORD3_REG, 0x3C4FCF09U);
    hsm_write_iv();
}

int hsm_wait_done(void)
{
    hsm_irq_fired = 0;
    while (!hsm_irq_fired) {
        __asm__ volatile ("wfi");
    }
    return (mmio_read32(HSM_STATUS_REG) & HSM_STATUS_ERROR) == 0U;
}

void test_hsm(void)
{
    uint32_t i;
    static const uint8_t plain[16] = {
        0x6BU, 0xC1U, 0xBEU, 0xE2U, 0x2EU, 0x40U, 0x9FU, 0x96U,
        0xE9U, 0x3DU, 0x7EU, 0x11U, 0x73U, 0x93U, 0x17U, 0x2AU
    };
    static const uint8_t cbc_expected[16] = {
        0x76U, 0x49U, 0xABU, 0xACU, 0x81U, 0x19U, 0xB2U, 0x46U,
        0xCEU, 0xE9U, 0x8EU, 0x9BU, 0x12U, 0xE9U, 0x19U, 0x7DU
    };
    static const uint8_t cmac_expected[16] = {
        0x07U, 0x0AU, 0x16U, 0xB4U, 0x6BU, 0x4DU, 0x41U, 0x44U,
        0xF7U, 0x9BU, 0xDDU, 0x9DU, 0xD0U, 0x4AU, 0x28U, 0x7CU
    };

    send_string("[HSM] HSM AES-CBC encrypt test.\n");
    {
        volatile uint8_t *src = (volatile uint8_t *)(uintptr_t)HSM_TEST_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_TEST_DST;
        for (i = 0; i < 16U; i++) {
            src[i] = plain[i];
            dst[i] = 0U;
        }
    }

    hsm_write_key_and_iv();
    mmio_write32(HSM_INT_ENABLE_REG, HSM_INT_DONE | HSM_INT_ERROR);
    mmio_write32(HSM_SRC_ADDR_REG, HSM_TEST_SRC);
    mmio_write32(HSM_DST_ADDR_REG, HSM_TEST_DST);
    mmio_write32(HSM_LENGTH_REG, 16U);
    mmio_write32(HSM_MODE_REG, HSM_MODE_CBC);
    mmio_write32(HSM_CTRL_REG, HSM_CTRL_START | HSM_CTRL_IRQ_ENABLE);

    if (hsm_wait_done()) {
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_TEST_DST;
        int ok = 1;
        for (i = 0; i < 16U; i++) {
            if (dst[i] != cbc_expected[i]) { ok = 0; break; }
        }
        send_string(ok ? "[HSM] HSM AES-CBC encrypt PASSED!\n"
                       : "[HSM] HSM AES-CBC encrypt FAILED!\n");
    } else {
        send_string("[HSM] HSM AES-CBC encrypt FAILED!\n");
    }

    send_string("[HSM] HSM AES-CMAC test.\n");
    {
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_CMAC_DST;
        for (i = 0; i < 16U; i++) dst[i] = 0U;
    }
    hsm_write_key_and_iv();
    mmio_write32(HSM_INT_ENABLE_REG, HSM_INT_DONE | HSM_INT_ERROR);
    mmio_write32(HSM_SRC_ADDR_REG, HSM_TEST_SRC);
    mmio_write32(HSM_DST_ADDR_REG, HSM_CMAC_DST);
    mmio_write32(HSM_LENGTH_REG, 16U);
    mmio_write32(HSM_MODE_REG, HSM_MODE_CMAC);
    mmio_write32(HSM_CTRL_REG, HSM_CTRL_START | HSM_CTRL_IRQ_ENABLE);

    if (hsm_wait_done()) {
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_CMAC_DST;
        int ok = 1;
        for (i = 0; i < 16U; i++) {
            if (dst[i] != cmac_expected[i]) { ok = 0; break; }
        }
        send_string(ok ? "[HSM] HSM AES-CMAC PASSED!\n"
                       : "[HSM] HSM AES-CMAC FAILED!\n");
    } else {
        send_string("[HSM] HSM AES-CMAC FAILED!\n");
    }
}
