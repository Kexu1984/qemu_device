/*
 * Linker script for bare metal ARM firmware
 * Links code to run at 0x40200000
 */

ENTRY(_start)

MEMORY
{
    ROM (rx) : ORIGIN = 0x40200000, LENGTH = 1M
}

SECTIONS
{
    .text : {
        *(.text)
        *(.text.*)
    } > ROM
    
    .rodata : {
        *(.rodata)
        *(.rodata.*)
    } > ROM
    
    .data : {
        *(.data)
        *(.data.*)
    } > ROM
    
    .bss : {
        *(.bss)
        *(.bss.*)
        *(COMMON)
    } > ROM
}