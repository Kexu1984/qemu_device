#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "cru.h"
#include "dual_cpu.h"
#include "ipc.h"
#include "mmio.h"

#define CPU1_MMIO_SEED            0x13579BDFU
#define CPU0_PARALLEL_MMIO_ROUNDS 64U

void test_dual_cpu(void)
{
    const uint32_t arg = 0xDEADBEEFU;
    const uint32_t expect = arg ^ 0xCAFEBABEU;
    uint32_t cpu0_signature = 0xC0000000U;

    send_string("[IPC] Dual-CPU IPC test: CPU0 -> CPU1 XOR 0xDEADBEEF ^ 0xCAFEBABE\n");

    IPC_ARG0 = arg;
    IPC_REQ = IPC_REQ_ECHO_XOR;
    __asm__ volatile ("dsb" ::: "memory");
    IPC_STATUS = IPC_STATUS_PENDING;

    while (IPC_STATUS != IPC_STATUS_DONE) {
        __asm__ volatile ("isb" ::: "memory");
    }

    uint32_t resp = IPC_RESP;
    IPC_STATUS = IPC_STATUS_IDLE;

    if (resp == expect) {
        send_string("[IPC] Dual-CPU IPC PASS: CPU1 responded correctly\n");
    } else {
        send_string("[IPC] Dual-CPU IPC FAIL: unexpected response\n");
    }

    send_string("[IPC] Dual-master MMIO test: CPU1 MMIO while CPU0 polls fabric\n");
    IPC_ARG0 = CPU1_MMIO_SEED;
    IPC_REQ = IPC_REQ_MMIO_BURST;
    __asm__ volatile ("dsb" ::: "memory");
    IPC_STATUS = IPC_STATUS_PENDING;

    while (IPC_STATUS != IPC_STATUS_DONE) {
        uint32_t status = mmio_read32(CONSOLE_UART_STATUS_REG);
        uint32_t sys_id = mmio_read32(SYSCTRL_ID_REG);
        uint32_t boot_status = mmio_read32(SYSCTRL_BOOT_STATUS_REG);
        uint32_t cru_reason = cru_reset_reason();
        cpu0_signature ^= status + sys_id + boot_status + cru_reason;
        cpu0_signature = (cpu0_signature << 3) | (cpu0_signature >> 29);
        __asm__ volatile ("isb" ::: "memory");
    }

    resp = IPC_RESP;
    IPC_STATUS = IPC_STATUS_IDLE;

    for (uint32_t i = 0; i < CPU0_PARALLEL_MMIO_ROUNDS; i++) {
        cpu0_signature ^= mmio_read32(CONSOLE_UART_STATUS_REG) + i;
        cpu0_signature ^= mmio_read32(SYSCTRL_CPU_STATUS_REG);
    }

    if ((resp & 0xFFF00000U) != 0xBAD00000U &&
        (mmio_read32(CONSOLE_UART_STATUS_REG) & UART_STATUS_TXREADY) != 0U) {
        send_string("[IPC] Dual-master MMIO PASS: CPU1 and CPU0 parallel MMIO completed\n");
    } else {
        send_string("[IPC] Dual-master MMIO FAIL: fabric parallel access error\n");
    }
    (void)cpu0_signature;
}
