/*
 * linker.ld — Linker script for TM4C123GXL (ARM Cortex-M4F)
 * 256 KB Flash, 32 KB SRAM
 */

ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 256K
    SRAM  (rwx) : ORIGIN = 0x20000000, LENGTH = 32K
}

_stack_top = ORIGIN(SRAM) + LENGTH(SRAM);

SECTIONS
{
    .text :
    {
        KEEP(*(.isr_vector))
        *(.text*)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    .data :
    {
        . = ALIGN(4);
        _data_start = .;
        *(.data*)
        . = ALIGN(4);
        _data_end = .;
    } > SRAM AT > FLASH

    _data_load = LOADADDR(.data);

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _bss_start = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _bss_end = .;
    } > SRAM

    /* Heap starts after BSS — needed by newlib's sbrk */
    end = .;
    _end = .;
    PROVIDE(end = .);
}
