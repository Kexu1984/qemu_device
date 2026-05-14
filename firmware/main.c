/*
 * FreeRTOS Cortex-M4 firmware -- MMIO socket device regression shell.
 *
 * Device-specific firmware code lives under drivers/<module>/, with public
 * interfaces in drivers/includes/. This file owns only the FreeRTOS app
 * entry point, platform bring-up sequence, and command menu dispatch.
 */

#include <stdint.h>
#include "FreeRTOS.h"
#include "task.h"
#include "console_uart.h"
#include "crc.h"
#include "cru.h"
#include "dma.h"
#include "dma_client.h"
#include "dual_cpu.h"
#include "gpio.h"
#include "hsm.h"
#include "irq.h"
#include "otp.h"
#include "spi_tx.h"
#include "sv_periph.h"
#include "sysctrl.h"
#include "wdt.h"

#ifdef COVERAGE_BUILD
extern uint32_t coverage_dump_mmio(void);
#endif

static void coverage_dump_if_enabled(void)
{
#ifdef COVERAGE_BUILD
    uint32_t status = coverage_dump_mmio();
    send_string((status & 0x2U) ? "[COV] MMIO coverage dump complete\n"
                              : "[COV] MMIO coverage dump failed\n");
#endif
}

void vAssertCalled(const char *file, uint32_t line)
{
    (void)file;
    (void)line;
    taskDISABLE_INTERRUPTS();
    for (;;) {
    }
}

void vApplicationMallocFailedHook(void)
{
    vAssertCalled(__FILE__, __LINE__);
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
    (void)task;
    (void)task_name;
    vAssertCalled(__FILE__, __LINE__);
}

static void app_task(void *arg)
{
    (void)arg;
    char cmd_buf[4];

    cru_init_all_devices();
    console_uart_init();

    send_string("=== MMIO SockDev Interrupt Demo ===\n");
    send_string("=== KX6625, Hello World ===\n");
    send_string("[FW] Device enabled.\n");

    nvic_init();
    send_string("[FW] NVIC initialised (IRQ0=UART, IRQ1=DMA, IRQ2=Timer, IRQ5=SV island, IRQ6=HSM, IRQ7=OTP).\n");

    __asm__ volatile ("cpsie i" ::: "memory");

    sysctrl_release_cpu1();
    send_string("[FW] CPU1 released from reset.\n");

    if (wdt_is_warm_boot()) {
        test_wdt();
    }

    while (1) {
        send_string("=== KX6625 Test Menu ===\n");
        send_string(" 1) UART IRQ demo\n");
        send_string(" 2) DMA M2M copy\n");
        send_string(" 3) DMA client\n");
        send_string(" 4) CRC-32\n");
        send_string(" 5) WDT reset\n");
        send_string(" 6) Dual-CPU IPC\n");
        send_string(" 7) SV APB island timer/DMA\n");
        send_string(" 8) HSM AES/CMAC\n");
        send_string(" 9) SYSCTRL native controller\n");
        send_string(" 0) OTP controller\n");
        send_string(" g) SV GPIO\n");
        send_string(" s) SV SPI TX\n");
        send_string(" a) All tests\n");
        send_string("# ");

        recv_line(cmd_buf, sizeof(cmd_buf));
        char cmd = cmd_buf[0];

        if (cmd == '1') {
            test_uart_irq();
        } else if (cmd == '2') {
            test_dma_m2m();
        } else if (cmd == '3') {
            test_dma_client();
        } else if (cmd == '4') {
            test_crc();
        } else if (cmd == '5') {
            test_wdt();
        } else if (cmd == '6') {
            test_dual_cpu();
        } else if (cmd == '7') {
            test_sv_timer();
            test_sv_dma();
        } else if (cmd == '8') {
            test_hsm();
        } else if (cmd == '9') {
            test_sysctrl();
        } else if (cmd == '0') {
            test_otp();
        } else if (cmd == 'g') {
            test_gpio();
        } else if (cmd == 's') {
            test_spi_tx();
        } else if (cmd == 'a') {
            console_uart_reset_irq_count();
            test_uart_irq();
            test_dma_m2m();
            test_dma_client();
            test_crc();
            test_dual_cpu();
            test_sv_timer();
            test_sv_dma();
            test_gpio();
            test_spi_tx();
            test_otp();
            test_hsm();
            test_sysctrl();
            coverage_dump_if_enabled();
            test_wdt();
        } else {
            send_string("[FW] Unknown command. Enter 0-9, 'g', or 'a'.\n");
        }
    }
}

void main(void)
{
    if (xTaskCreate(app_task, "kx6625", 1024U, NULL, tskIDLE_PRIORITY + 1U, NULL) != pdPASS) {
        vAssertCalled(__FILE__, __LINE__);
    }

    vTaskStartScheduler();

    for (;;) {
    }
}
