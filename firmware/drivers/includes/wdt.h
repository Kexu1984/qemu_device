#ifndef FIRMWARE_DRIVERS_WDT_H
#define FIRMWARE_DRIVERS_WDT_H

#define WDT_CTRL_ENABLE     0x1U
#define WDT_CTRL_INT_ENABLE 0x2U
#define WDT_REASON_POR      0x0U
#define WDT_REASON_WDT      0x1U

int wdt_is_warm_boot(void);
void wdt_irq_handler(void);
void test_wdt(void);

#endif /* FIRMWARE_DRIVERS_WDT_H */
