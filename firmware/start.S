/*
 * ARM startup code for bare metal firmware
 * Sets up stack and jumps to main()
 */

.section .text
.global _start

_start:
    /* Set up stack pointer (use some safe address) */
    ldr sp, =0x40300000
    
    /* Call main function */
    bl main
    
    /* If main returns, infinite loop */
1:
    wfi
    b 1b
