#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "ipc.h"
#include "mmio.h"
#include "sysctrl.h"

void sysctrl_release_cpu1(void)
{
    SYSCTRL_CPU1RST = 1U;
}

void test_sysctrl(void)
{
    uint32_t id = mmio_read32(SYSCTRL_ID_REG);
    uint32_t boot_status = mmio_read32(SYSCTRL_BOOT_STATUS_REG);
    uint32_t cpu_status = mmio_read32(SYSCTRL_CPU_STATUS_REG);

    send_string("[SYSCTRL] Native SYSCTRL register test.\n");
    send_string(id == SYSCTRL_ID_EXPECTED ? "[SYSCTRL] ID SCTL PASSED!\n"
                                      : "[SYSCTRL] ID FAILED!\n");
    send_string((boot_status & (SYSCTRL_BOOT_FLASH_LOADED | SYSCTRL_BOOT_VECTOR_VALID)) ==
                (SYSCTRL_BOOT_FLASH_LOADED | SYSCTRL_BOOT_VECTOR_VALID)
                ? "[SYSCTRL] BOOT_STATUS flash/vector PASSED!\n"
                : "[SYSCTRL] BOOT_STATUS FAILED!\n");
    send_string((boot_status & (SYSCTRL_BOOT_SECURE_DONE | SYSCTRL_BOOT_SECURE_PASS)) ==
                (SYSCTRL_BOOT_SECURE_DONE | SYSCTRL_BOOT_SECURE_PASS)
                ? "[SYSCTRL] SECURE_BOOT CMAC PASSED!\n"
                : "[SYSCTRL] SECURE_BOOT CMAC FAILED!\n");
    send_string((cpu_status & SYSCTRL_CPU1_RELEASED) != 0U
                ? "[SYSCTRL] CPU_STATUS CPU1 released PASSED!\n"
                : "[SYSCTRL] CPU_STATUS FAILED!\n");

    mmio_write32(SYSCTRL_DEVICE_CLK_EN_REG, 0xFFU);
    mmio_write32(SYSCTRL_DEVICE_RST_CTRL_REG, 0x1U);
    send_string((mmio_read32(SYSCTRL_DEVICE_RST_STATUS_REG) & 0x1U) != 0U
                ? "[SYSCTRL] DEVICE reset policy PASSED!\n"
                : "[SYSCTRL] DEVICE reset policy FAILED!\n");

    mmio_write32(SYSCTRL_DEVCTL_ADDR_REG, CONSOLE_UART_STATUS_REG);
    mmio_write32(SYSCTRL_DEVCTL_CTRL_REG, SYSCTRL_DEVCTL_START | SYSCTRL_DEVCTL_READ);
    {
        uint32_t devctl_status = mmio_read32(SYSCTRL_DEVCTL_STATUS_REG);
        uint32_t uart_status = mmio_read32(SYSCTRL_DEVCTL_RDATA_REG);
        send_string(((devctl_status & SYSCTRL_DEVCTL_STATUS_DONE) != 0U) &&
                    ((devctl_status & SYSCTRL_DEVCTL_STATUS_ERROR) == 0U) &&
                    ((uart_status & UART_STATUS_TXREADY) != 0U)
                    ? "[SYSCTRL] DEVCTL UART STATUS read PASSED!\n"
                    : "[SYSCTRL] DEVCTL UART STATUS read FAILED!\n");
    }
}
