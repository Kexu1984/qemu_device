/*
 * Linker script for Cortex-M3 bare metal firmware (KX6625 SoC)
 *
 * Memory layout:
 *   0x00000000  FLASH — vector table + code + rodata  (512 KB)
 *   0x20000000  SRAM  — data + bss + stack            (128 KB, top = _stack_top)
 *
 * The first word in FLASH (0x00000000) must be _stack_top so the Cortex-M3
 * hardware can load the initial MSP during reset.
 * The second word (0x00000004) must be the address of reset_handler (Thumb,
 * so the linker sets bit 0 automatically for .thumb_func symbols).
 */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

/* Initial Main Stack Pointer — top of RAM */
_stack_top = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
    /* Cortex-M3 vector table must be at the very start of FLASH */
    .vectors : {
        *(.vectors)
    } > FLASH

    .text : {
        *(.text)
        *(.text.*)
    } > FLASH

    .rodata : {
        *(.rodata)
        *(.rodata.*)
    } > FLASH

    /* Initialised data: stored in FLASH, copied to RAM at startup if needed.
     * For simplicity this firmware keeps .data in FLASH (no copy loop). */
    .data : {
        *(.data)
        *(.data.*)
    } > RAM AT > FLASH

    .bss : {
        *(.bss)
        *(.bss.*)
        *(COMMON)
    } > RAM
}
