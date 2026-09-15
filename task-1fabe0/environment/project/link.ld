/*
 * link.ld - Linker script for bare-metal Raspberry Pi 4 (AArch64)
 *
 * The RPi4 firmware loads the AArch64 kernel at a specific address.
 * Sections must be laid out for correct boot and BSS initialization.
 */

ENTRY(_start)

SECTIONS
{
    . = 0x8000;

    .text : {
        KEEP(*(.text.boot))
        *(.text)
    }

    .rodata : {
        *(.rodata)
    }

    .data : {
        *(.data)
    }

    .bss (NOLOAD) : {
        . = ALIGN(16);
        *(.bss)
        *(COMMON)
    }

    /DISCARD/ : {
        *(.comment)
        *(.note*)
    }
}
