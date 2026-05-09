/*
 * cpu1_main.c — CPU1 entry point for KX6625 dual-core demo.
 *
 * CPU1 is released from reset when CPU0 writes 1 to SYSCTRL.CPU1RST.
 * It polls the IPC area in shared SRAM for requests from CPU0,
 * processes them, and writes back the result.
 *
 * CPU1 can also be asked to issue a deterministic MMIO burst so the
 * platform fabric sees CPU0 and CPU1 as active masters at the same time.
 * It does not generate IRQs; completion still uses shared SRAM IPC.
 */

#include <stdint.h>
#include "mmio_devices.h"
#include "ipc.h"

#define UART_STATUS_TXREADY  (1u << 0)
#define CRC_CTRL_RESET       0x1U
#define CRC_EXPECTED         0xCBF43926U
#define CPU1_MMIO_ROUNDS     16U

static inline void cpu1_mmio_write32(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)(uintptr_t)addr = value;
}

static inline uint32_t cpu1_mmio_read32(uint32_t addr)
{
    return *(volatile uint32_t *)(uintptr_t)addr;
}

static inline void cpu1_mmio_write8(uint32_t addr, uint8_t value)
{
    *(volatile uint8_t *)(uintptr_t)addr = value;
}

static uint32_t cpu1_mmio_burst(uint32_t seed)
{
    static const uint8_t crc_data[] = {
        0x31U, 0x32U, 0x33U, 0x34U, 0x35U, 0x36U, 0x37U, 0x38U, 0x39U
    };
    uint32_t signature = 0xC1010000U ^ seed;

    for (uint32_t round = 0; round < CPU1_MMIO_ROUNDS; round++) {
        cpu1_mmio_write32(CRC_CTRL_REG, CRC_CTRL_RESET);
        for (uint32_t i = 0; i < sizeof(crc_data); i++) {
            cpu1_mmio_write8(CRC_DATA_REG, crc_data[i]);
        }

        if (cpu1_mmio_read32(CRC_RESULT_REG) != CRC_EXPECTED) {
            return 0xBAD10000U | round;
        }
        if ((cpu1_mmio_read32(CONSOLE_UART_STATUS_REG) & UART_STATUS_TXREADY) == 0U) {
            return 0xBAD20000U | round;
        }
        if (SYSCTRL_CPUID != 1U) {
            return 0xBAD30000U | round;
        }
        if (cpu1_mmio_read32(SYSCTRL_ID_REG) != 0x4C544353U) {
            return 0xBAD40000U | round;
        }

        signature ^= cpu1_mmio_read32(TIMER0_VALUE_REG) + (round << 8);
        signature ^= cpu1_mmio_read32(CRU_RESET_REASON_REG) + round;
        __asm__ volatile ("dsb" ::: "memory");
    }

    return signature ^ 0x1A5A5A5AU;
}

void cpu1_main(void)
{
    for (;;) {
        /* Spin until CPU0 posts a request.
         * ISB forces QEMU TCG to exit the translation block on every
         * iteration so the load of IPC_STATUS is never stale across
         * a TB-chain boundary in MTTCG mode. */
        while (IPC_STATUS != IPC_STATUS_PENDING) {
            __asm__ volatile ("isb" ::: "memory");
        }

        uint32_t req  = IPC_REQ;
        uint32_t arg0 = IPC_ARG0;
        uint32_t resp;

        switch (req) {
        case IPC_REQ_ECHO_XOR:
            resp = arg0 ^ 0xCAFEBABEU;
            break;
        case IPC_REQ_MMIO_BURST:
            resp = cpu1_mmio_burst(arg0);
            break;
        default:
            resp = 0xDEADDEADU;
            break;
        }

        /* Ensure RESP is visible before we flip STATUS to DONE. */
        IPC_RESP = resp;
        __asm__ volatile ("dsb" ::: "memory");
        IPC_STATUS = IPC_STATUS_DONE;
    }
}
