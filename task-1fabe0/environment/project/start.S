/*
 * start.S - AArch64 bare-metal startup code for Raspberry Pi 4 (BCM2711)
 *
 * Boot sequence:
 *   1. armstub8 drops us at EL2
 *   2. Transition EL2 -> EL1
 *   3. Park secondary cores
 *   4. Set up stack for primary core
 *   5. Clear BSS
 *   6. Jump to main()
 */

.section ".text.boot"

.global _start

_start:
    /* Determine current exception level */
    mrs     x0, CurrentEL
    lsr     x0, x0, #2
    cmp     x0, #2
    b.ne    el1_entry

    /* === EL2 to EL1 transition === */

    /* Set EL1 execution state to AArch64 (HCR_EL2.RW = bit 31) */
    mov     x0, #(1 << 31)
    msr     hcr_el2, x0

    /* Disable coprocessor traps to EL2 */
    mov     x0, #0x33ff
    msr     cptr_el2, x0

    /* Set SPSR_EL2: return to EL1h with DAIF masked */
    mov     x0, #0x3c5
    msr     spsr_el2, x0

    /* Set EL1 entry point */
    adr     x0, el1_entry
    msr     elr_el2, x0

    eret

el1_entry:
    /* Read core ID from MPIDR_EL1 */
    mrs     x0, mpidr_el1
    and     x0, x0, #3
    cbz     x0, primary_core

    /* Secondary cores: park in WFE loop */
secondary_wait:
    wfe
    b       secondary_wait

primary_core:
    /* Set up stack pointer (stack grows downward from _start) */
    ldr     x0, =_start
    mov     sp, x0

    /* Clear BSS section */
    ldr     x0, =__bss_start
    ldr     x1, =__bss_end
bss_clear:
    cmp     x0, x1
    b.ge    bss_done
    str     xzr, [x0], #8
    b       bss_clear

bss_done:
    /* Jump to C entry point */
    bl      main

    /* Should never return; halt if it does */
halt:
    wfe
    b       halt


/*
 * Exception Vector Table
 * Must be 2048-byte aligned (VBAR_EL1 bits [10:0] are RES0)
 * Each vector entry occupies 128 bytes (32 instructions max)
 * 4 groups x 4 entries = 16 entries total
 */
.align 4
.global vectors
vectors:
    /* Current EL with SP_EL0 */
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128

    /* Current EL with SP_ELx */
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128

    /* Lower EL using AArch64 */
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128

    /* Lower EL using AArch32 */
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
    .balign 128
    b       halt
