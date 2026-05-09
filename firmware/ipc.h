/*
 * ipc.h — Inter-Processor Communication (IPC) between CPU0 and CPU1.
 *
 * Protocol (shared SRAM at IPC_BASE):
 *
 *   CPU0 fills IPC_ARG0 + IPC_REQ, then writes IPC_STATUS = PENDING.
 *   CPU1 spins on IPC_STATUS; on PENDING it processes the request,
 *   writes IPC_RESP, then sets IPC_STATUS = DONE.  Some requests also
 *   let CPU1 issue MMIO accesses so CPU0/CPU1 can exercise the fabric as
 *   concurrent masters.
 *   CPU0 spins on IPC_STATUS == DONE, reads IPC_RESP, resets to IDLE.
 *
 * SRAM layout (top 8 KB of 128 KB SRAM):
 *   0x2001E000  IPC area    (4 KB, this file)
 *   0x2001F000  CPU0 stack  (4 KB, grows down)  ← _stack_top
 *   0x20020000  CPU1 stack  (4 KB, grows down)  ← _cpu1_stack_top
 *
 * SYSCTRL (native MMIO at 0x4000A000, implemented in kx6625.c):
 *   0x4000A000  SYSCTRL_CPUID    [RO] returns current CPU's cpu_index
 *   0x4000A004  SYSCTRL_CPU1RST  [WO] legacy write-1 CPU1 reset release
 *   0x4000A018  SYSCTRL_CPU_CTRL [RW] bit1 also releases CPU1
 *   0x4000A040+ SYSCTRL_DEVCTL_* indirect device-register access window
 */

#ifndef IPC_H
#define IPC_H

#include <stdint.h>

/* ── IPC shared-SRAM area ────────────────────────────────────────────── */
#define IPC_BASE         0x2001E000U

#define IPC_STATUS_OFF   0x00U   /* 0=idle, 1=req pending, 2=done        */
#define IPC_REQ_OFF      0x04U   /* request opcode (CPU0 writes)          */
#define IPC_ARG0_OFF     0x08U   /* argument 0    (CPU0 writes)           */
#define IPC_RESP_OFF     0x0CU   /* response value (CPU1 writes)          */

#define IPC_STATUS  (*(volatile uint32_t *)(IPC_BASE + IPC_STATUS_OFF))
#define IPC_REQ     (*(volatile uint32_t *)(IPC_BASE + IPC_REQ_OFF))
#define IPC_ARG0    (*(volatile uint32_t *)(IPC_BASE + IPC_ARG0_OFF))
#define IPC_RESP    (*(volatile uint32_t *)(IPC_BASE + IPC_RESP_OFF))

#define IPC_STATUS_IDLE     0U
#define IPC_STATUS_PENDING  1U
#define IPC_STATUS_DONE     2U

/* ── Request opcodes ─────────────────────────────────────────────────── */
/* CPU1 XORs IPC_ARG0 with 0xCAFEBABEU and returns the result in IPC_RESP */
#define IPC_REQ_ECHO_XOR   0x01U
/* CPU1 performs a deterministic MMIO access burst and returns a signature */
#define IPC_REQ_MMIO_BURST 0x02U

/* ── SYSCTRL registers ───────────────────────────────────────────────── */
#ifndef SYSCTRL_BASE
#define SYSCTRL_BASE    0x4000A000U
#endif
#define SYSCTRL_CPUID   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x00U))
#define SYSCTRL_CPU1RST (*(volatile uint32_t *)(SYSCTRL_BASE + 0x04U))
#define SYSCTRL_ID      (*(volatile uint32_t *)(SYSCTRL_BASE + 0x08U))
#define SYSCTRL_VERSION (*(volatile uint32_t *)(SYSCTRL_BASE + 0x0CU))
#define SYSCTRL_RESET_CTRL   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x10U))
#define SYSCTRL_RESET_STATUS (*(volatile uint32_t *)(SYSCTRL_BASE + 0x14U))
#define SYSCTRL_CPU_CTRL     (*(volatile uint32_t *)(SYSCTRL_BASE + 0x18U))
#define SYSCTRL_CPU_STATUS   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x1CU))
#define SYSCTRL_BOOT_MODE    (*(volatile uint32_t *)(SYSCTRL_BASE + 0x20U))
#define SYSCTRL_BOOT_STATUS  (*(volatile uint32_t *)(SYSCTRL_BASE + 0x24U))
#define SYSCTRL_DEVICE_CLK_EN     (*(volatile uint32_t *)(SYSCTRL_BASE + 0x30U))
#define SYSCTRL_DEVICE_RST_CTRL   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x34U))
#define SYSCTRL_DEVICE_RST_STATUS (*(volatile uint32_t *)(SYSCTRL_BASE + 0x38U))
#define SYSCTRL_DEVCTL_ADDR   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x40U))
#define SYSCTRL_DEVCTL_WDATA  (*(volatile uint32_t *)(SYSCTRL_BASE + 0x44U))
#define SYSCTRL_DEVCTL_RDATA  (*(volatile uint32_t *)(SYSCTRL_BASE + 0x48U))
#define SYSCTRL_DEVCTL_CTRL   (*(volatile uint32_t *)(SYSCTRL_BASE + 0x4CU))
#define SYSCTRL_DEVCTL_STATUS (*(volatile uint32_t *)(SYSCTRL_BASE + 0x50U))
#define SYSCTRL_DEVCTL_ERROR  (*(volatile uint32_t *)(SYSCTRL_BASE + 0x54U))

#define SYSCTRL_CPU_CTRL_CPU1_RELEASE 0x2U
#define SYSCTRL_DEVCTL_START          0x1U
#define SYSCTRL_DEVCTL_READ           0x2U
#define SYSCTRL_DEVCTL_WRITE          0x4U
#define SYSCTRL_DEVCTL_STATUS_DONE    0x2U
#define SYSCTRL_DEVCTL_STATUS_ERROR   0x4U

#endif /* IPC_H */
