/*
 * cpu1_main.c — CPU1 entry point for KX6625 dual-core demo.
 *
 * CPU1 is released from reset when CPU0 writes 1 to SYSCTRL.CPU1RST.
 * It polls the IPC area in shared SRAM for requests from CPU0,
 * processes them, and writes back the result.
 *
 * CPU1 intentionally does NOT use any MMIO peripherals or generate IRQs;
 * all communication is via the shared SRAM IPC protocol (ipc.h).
 */

#include <stdint.h>
#include "ipc.h"

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
