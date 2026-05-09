#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "mmio.h"
#include "wdt.h"

static volatile int wdt_irq_fired = 0;

int wdt_is_warm_boot(void)
{
    return mmio_read32(WDT_RESET_REASON_REG) == WDT_REASON_WDT;
}

void wdt_irq_handler(void)
{
    wdt_irq_fired++;
    send_string("[IRQ] WDT pre-reset warning IRQ! INTID=4\n");
}

void test_wdt(void)
{
    uint32_t reason = mmio_read32(WDT_RESET_REASON_REG);
    if (reason == WDT_REASON_WDT) {
        uint32_t cnt = mmio_read32(WDT_TIMEOUT_CNT_REG);
        send_string("[WDT] Warm boot detected: RESET_REASON=WDT\n");
        send_string("[WDT] timeout_cnt=");
        send_char((char)('0' + (cnt % 10)));
        send_string("\n");
        send_string("[WDT] WDT demo complete.\n");
        mmio_write32(WDT_CTRL_REG, 0x0U);
    } else {
        send_string("[WDT] Power-on reset (RESET_REASON=POR)\n");
        send_string("[WDT] Loading WDT 200 ms, kicking twice then letting it fire...\n");
        mmio_write32(WDT_LOAD_REG, 200U);
        mmio_write32(WDT_CTRL_REG, WDT_CTRL_ENABLE | WDT_CTRL_INT_ENABLE);
        mmio_write32(WDT_KICK_REG, 0x1U);
        send_string("[WDT] Kick 1\n");
        for (volatile uint32_t d = 0; d < 50000U; d++) { }
        mmio_write32(WDT_KICK_REG, 0x1U);
        send_string("[WDT] Kick 2\n");
        send_string("[WDT] Waiting for WDT timeout and system reset...\n");
        while (1) { __asm__ volatile ("wfi"); }
    }
    (void)wdt_irq_fired;
}
