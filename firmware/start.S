/*
 * Cortex-M3 startup code for bare metal firmware
 *
 * Image is loaded at 0x00000000 (FLASH on KX6625 SoC).
 * The Cortex-M3 vector table must sit at the very first bytes of FLASH.
 * Hardware reads the initial MSP from word 0 and the reset handler address
 * from word 1 during reset — no VBAR or mode-switch needed.
 *
 * IRQ dispatch is fully automatic: the hardware saves/restores context and
 * calls the handler named in the vector table.  C handlers require no
 * special prologue/epilogue.
 *
 * KX6625 external IRQ assignment:
 *   IRQ0: console_uart
 *   IRQ1: dma
 *   IRQ2: timer0
 */

.syntax unified
.cpu cortex-m3
.thumb

/* ── External symbols defined in main.c ─────────────────────────────── */
.extern main
.extern uart_irq_handler
.extern dma_irq_handler
.extern timer_irq_handler
.extern dma_client_irq_handler

/* ── Vector table — must be the very first thing in the image ───────── */
.section .vectors, "a"
.align 2

_vectors:
    /* ── Core exceptions (indices 0-15) ───────────────────────────── */
    .word   _stack_top          /*  0: Initial MSP value (from linker script) */
    .word   reset_handler       /*  1: Reset                                  */
    .word   default_handler     /*  2: NMI                                    */
    .word   hardfault_handler   /*  3: HardFault                              */
    .word   default_handler     /*  4: MemManage                              */
    .word   default_handler     /*  5: BusFault                               */
    .word   default_handler     /*  6: UsageFault                             */
    .word   0                   /*  7: Reserved                               */
    .word   0                   /*  8: Reserved                               */
    .word   0                   /*  9: Reserved                               */
    .word   0                   /* 10: Reserved                               */
    .word   default_handler     /* 11: SVCall                                 */
    .word   default_handler     /* 12: Debug Monitor                          */
    .word   0                   /* 13: Reserved                               */
    .word   default_handler     /* 14: PendSV                                 */
    .word   default_handler     /* 15: SysTick                                */

    /* ── External IRQs 0-3 (indices 16-19) — our devices ───────────────── */
    .word   uart_irq_handler       /* IRQ0: console_uart device  */
    .word   dma_irq_handler        /* IRQ1: dma device           */
    .word   timer_irq_handler      /* IRQ2: timer0 device        */
    .word   dma_client_irq_handler /* IRQ3: dma_client_demo      */

    /* ── External IRQs 4-15 (indices 20-31) — default ──────────────── */
    .rept 12
    .word   default_handler
    .endr

/* ── Exception/IRQ handlers ─────────────────────────────────────────── */
.section .text
.align 2

.thumb_func
.global reset_handler
reset_handler:
    /* Hardware has already loaded MSP from _vectors[0] and jumped here. */
    bl      main
    /* main() should never return; spin if it does */
    b       default_handler

.thumb_func
.global hardfault_handler
hardfault_handler:
    b       .

.thumb_func
.global default_handler
default_handler:
    b       .
