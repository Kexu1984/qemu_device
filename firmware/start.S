/*
 * Cortex-M4 startup code for bare metal firmware
 *
 * Image is loaded at 0x00000000 (FLASH on KX6625 SoC).
 * The Cortex-M vector table must sit at the very first bytes of FLASH.
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
 *   IRQ5: sv_island
 *   IRQ6: hsm
 */

.syntax unified
.cpu cortex-m4
.thumb

/* ── External symbols defined in main.c ─────────────────────────────── */
.extern main
.extern cpu1_main
.extern _sidata
.extern _sdata
.extern _edata
.extern _sbss
.extern _ebss
.extern uart_irq_handler
.extern dma_irq_handler
.extern timer_irq_handler
.extern dma_client_irq_handler
.extern wdt_irq_handler
.extern sv_island_irq_handler
.extern hsm_irq_handler
.extern vPortSVCHandler
.extern xPortPendSVHandler
.extern xPortSysTickHandler

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
    .word   vPortSVCHandler     /* 11: SVCall                                 */
    .word   default_handler     /* 12: Debug Monitor                          */
    .word   0                   /* 13: Reserved                               */
    .word   xPortPendSVHandler  /* 14: PendSV                                 */
    .word   xPortSysTickHandler /* 15: SysTick                                */

    /* ── External IRQs 0-6 (indices 16-22) ─────────────────────────────── */
    .word   uart_irq_handler       /* IRQ0: console_uart device  */
    .word   dma_irq_handler        /* IRQ1: dma device           */
    .word   timer_irq_handler      /* IRQ2: timer0 device        */
    .word   dma_client_irq_handler /* IRQ3: dma_client_demo      */
    .word   wdt_irq_handler        /* IRQ4: watchdog timer       */
    .word   sv_island_irq_handler  /* IRQ5: SV APB island        */
    .word   hsm_irq_handler        /* IRQ6: HSM crypto           */

    /* ── External IRQs 7-15 (indices 23-31) — default ────────────────── */
    .rept 9
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

    /* CPU0: initialise C runtime state before calling main. */
    ldr     r0, =_sidata
    ldr     r1, =_sdata
    ldr     r2, =_edata
1:
    cmp     r1, r2
    bcc     2f
    b       3f
2:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    b       1b
3:
    ldr     r0, =_sbss
    ldr     r1, =_ebss
    movs    r2, #0
4:
    cmp     r0, r1
    bcc     5f
    b       6f
5:
    str     r2, [r0], #4
    b       4b
6:

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
