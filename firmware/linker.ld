/*
 * Linker script for Cortex-M4 FreeRTOS firmware (KX6625 SoC)
 *
 * Memory layout:
 *   0x00000000  FLASH — vector table + code + rodata  (512 KB)
 *   0x20000000  SRAM  — data + bss + stack            (128 KB, top = _stack_top)
 *
 * The first word in FLASH (0x00000000) must be _stack_top so the Cortex-M
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

/*
 * Stack layout (top of 128 KB SRAM, both stacks grow downward):
 *   0x20020000 <- _cpu1_stack_top  CPU1 stack (4 KB, grows down to 0x2001F000)
 *   0x2001F000 <- _stack_top       CPU0 stack (grows down)
 *   0x2001E000                     IPC area start (fixed in ipc.h)
 */
_stack_top      = ORIGIN(RAM) + LENGTH(RAM) - 4K;   /* 0x2001F000 — CPU0 initial MSP */
_cpu1_stack_top = ORIGIN(RAM) + LENGTH(RAM);         /* 0x20020000 — CPU1 switches here */

SECTIONS
{
    /* Cortex-M vector table must be at the very start of FLASH */
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
        . = ALIGN(4);
        __llvm_covmap_start = .;
        KEEP(*(__llvm_covmap))
        __llvm_covmap_end = .;
        . = ALIGN(4);
        __llvm_prf_names_start = .;
        KEEP(*(__llvm_prf_names))
        __llvm_prf_names_end = .;
    } > FLASH

    . = ALIGN(4);
    _sidata = LOADADDR(.data);
    .data : {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data.*)
        . = ALIGN(8);
        __llvm_prf_data_start = .;
        KEEP(*(__llvm_prf_data))
        __llvm_prf_data_end = .;
        . = ALIGN(8);
        __llvm_prf_cnts_start = .;
        KEEP(*(__llvm_prf_cnts))
        __llvm_prf_cnts_end = .;
        . = ALIGN(4);
        _edata = .;
    } > RAM AT > FLASH

    .bss : {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM
}
