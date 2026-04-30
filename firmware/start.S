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
.extern cpu1_main
.extern uart_irq_handler
.extern dma_irq_handler
.extern timer_irq_handler
.extern dma_client_irq_handler
.extern wdt_irq_handler

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

    /* ── External IRQs 0-4 (indices 16-20) ─────────────────────────────── */
    .word   uart_irq_handler       /* IRQ0: console_uart device  */
    .word   dma_irq_handler        /* IRQ1: dma device           */
    .word   timer_irq_handler      /* IRQ2: timer0 device        */
    .word   dma_client_irq_handler /* IRQ3: dma_client_demo      */
    .word   wdt_irq_handler        /* IRQ4: watchdog timer       */

    /* ── External IRQs 5-15 (indices 21-31) — default ────────────────── */
    .rept 10
    .word   default_handler
    .endr

/* ── Exception/IRQ handlers ─────────────────────────────────────────── */
.section .text
.align 2

.thumb_func
.global reset_handler
reset_handler:
    /*
     * First thing: read SYSCTRL.CPUID to determine which CPU we are.
     * This must happen BEFORE any stack access (both CPUs start with the
     * same initial MSP from word 0 of the vector table).
     * r0-r1 are caller-saved scratch; safe to use here.
     */
    ldr     r0, =0x4000A000     /* SYSCTRL base address */
    ldr     r1, [r0]            /* r1 = cpu_index (0=CPU0, 1=CPU1) */
    cmp     r1, #1
    beq     cpu1_entry          /* CPU1: switch stack and branch to cpu1_main */

    /* CPU0: hardware has already loaded MSP from _vectors[0]; call main */
    bl      main
    /* main() should never return; spin if it does */
    b       default_handler

cpu1_entry:
    /*
     * CPU1: switch to dedicated stack BEFORE any stack operation.
     * _cpu1_stack_top is defined in linker.ld (0x20020000).
     */
    ldr     sp, =_cpu1_stack_top
    bl      cpu1_main
    b       default_handler

.thumb_func
.global hardfault_handler
hardfault_handler:
    b       .

.thumb_func
.global default_handler
default_handler:
    b       .
