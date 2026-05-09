#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "hsm.h"
#include "mmio.h"
#include "otp.h"

void otp_irq_handler(void)
{
}

static int otp_program_row(uint32_t row, uint32_t value)
{
    mmio_write32(OTP_UNLOCK0_REG, OTP_UNLOCK0_VALUE);
    mmio_write32(OTP_UNLOCK1_REG, OTP_UNLOCK1_VALUE);
    mmio_write32(OTP_ADDR_REG, row);
    mmio_write32(OTP_WDATA_REG, value);
    mmio_write32(OTP_CTRL_REG, OTP_CTRL_START | OTP_CTRL_PROGRAM);
    return ((mmio_read32(OTP_STATUS_REG) & (OTP_STATUS_DONE | OTP_STATUS_ERROR)) == OTP_STATUS_DONE);
}

static int otp_read_row(uint32_t row, uint32_t *value)
{
    mmio_write32(OTP_ADDR_REG, row);
    mmio_write32(OTP_CTRL_REG, OTP_CTRL_START | OTP_CTRL_READ);
    if ((mmio_read32(OTP_STATUS_REG) & (OTP_STATUS_DONE | OTP_STATUS_ERROR)) != OTP_STATUS_DONE) {
        return 0;
    }
    *value = mmio_read32(OTP_RDATA_REG);
    return 1;
}

void test_otp(void)
{
    uint32_t i;
    uint32_t value = 0U;
    int ok;
    static const uint32_t key_words[4] = {
        0x16157E2BU, 0xA6D2AE28U, 0x8815F7ABU, 0x3C4FCF09U
    };
    static const uint8_t plain[16] = {
        0x6BU, 0xC1U, 0xBEU, 0xE2U, 0x2EU, 0x40U, 0x9FU, 0x96U,
        0xE9U, 0x3DU, 0x7EU, 0x11U, 0x73U, 0x93U, 0x17U, 0x2AU
    };
    static const uint8_t cbc_expected[16] = {
        0x76U, 0x49U, 0xABU, 0xACU, 0x81U, 0x19U, 0xB2U, 0x46U,
        0xCEU, 0xE9U, 0x8EU, 0x9BU, 0x12U, 0xE9U, 0x19U, 0x7DU
    };

    send_string("[OTP] OTP controller test.\n");
    send_string(mmio_read32(OTP_ID_REG) == OTP_ID_EXPECTED ? "[OTP] ID OTP1 PASSED!\n"
                                                        : "[OTP] ID FAILED!\n");

    ok = 1;
    for (i = 0; i < 4U; i++) {
        if (!otp_program_row(i, key_words[i])) { ok = 0; }
    }
    send_string(ok ? "[OTP] Key slot0 programmed PASSED!\n"
                   : "[OTP] Key slot0 programmed FAILED!\n");

    mmio_write32(OTP_ADDR_REG, 0U);
    mmio_write32(OTP_CTRL_REG, OTP_CTRL_START | OTP_CTRL_READ);
    send_string(((mmio_read32(OTP_STATUS_REG) & OTP_STATUS_READ_PROTECTED) != 0U) &&
                (mmio_read32(OTP_ERROR_REG) == OTP_ERR_READ_PROTECTED)
                ? "[OTP] Key read protection PASSED!\n"
                : "[OTP] Key read protection FAILED!\n");

    ok = otp_program_row(0x60U, 0x12345678U) && otp_read_row(0x60U, &value) && value == 0x12345678U;
    send_string(ok ? "[OTP] Non-secret row read PASSED!\n"
                   : "[OTP] Non-secret row read FAILED!\n");

    (void)otp_program_row(0x50U, 0xFFFFFFFFU);
    send_string(mmio_read32(OTP_ERROR_REG) == OTP_ERR_ZERO_TO_ONE
                ? "[OTP] Zero-to-one rejection PASSED!\n"
                : "[OTP] Zero-to-one rejection FAILED!\n");

    {
        volatile uint8_t *src = (volatile uint8_t *)(uintptr_t)HSM_TEST_SRC;
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_TEST_DST;
        for (i = 0; i < 16U; i++) {
            src[i] = plain[i];
            dst[i] = 0U;
        }
    }
    hsm_write_iv();
    mmio_write32(HSM_KEY_ID_REG, 0U);
    mmio_write32(HSM_INT_ENABLE_REG, HSM_INT_DONE | HSM_INT_ERROR);
    mmio_write32(HSM_SRC_ADDR_REG, HSM_TEST_SRC);
    mmio_write32(HSM_DST_ADDR_REG, HSM_TEST_DST);
    mmio_write32(HSM_LENGTH_REG, 16U);
    mmio_write32(HSM_MODE_REG, HSM_MODE_CBC);
    mmio_write32(HSM_CTRL_REG, HSM_CTRL_START | HSM_CTRL_IRQ_ENABLE);

    if (hsm_wait_done()) {
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)HSM_TEST_DST;
        ok = 1;
        for (i = 0; i < 16U; i++) {
            if (dst[i] != cbc_expected[i]) { ok = 0; break; }
        }
        send_string(ok ? "[OTP] HSM OTP KEY_ID0 AES-CBC PASSED!\n"
                       : "[OTP] HSM OTP KEY_ID0 AES-CBC FAILED!\n");
    } else {
        send_string("[OTP] HSM OTP KEY_ID0 AES-CBC FAILED!\n");
    }
}
