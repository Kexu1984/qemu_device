#ifndef FIRMWARE_DRIVERS_OTP_H
#define FIRMWARE_DRIVERS_OTP_H

#define OTP_CTRL_START       0x1U
#define OTP_CTRL_READ        0x2U
#define OTP_CTRL_PROGRAM     0x4U
#define OTP_STATUS_DONE      0x2U
#define OTP_STATUS_ERROR     0x4U
#define OTP_STATUS_READ_PROTECTED 0x800U
#define OTP_ERR_ZERO_TO_ONE  3U
#define OTP_ERR_READ_PROTECTED 11U
#define OTP_UNLOCK0_VALUE    0x4F545031U
#define OTP_UNLOCK1_VALUE    0x50524F47U
#define OTP_ID_EXPECTED      0x3150544FU

void otp_irq_handler(void);
void test_otp(void);

#endif /* FIRMWARE_DRIVERS_OTP_H */
