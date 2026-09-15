    .syntax unified
    .cpu cortex-m4
    .fpu softvfp
    .thumb

    .section .isr_vector,"a",%progbits
    .type isr_vector, %object
isr_vector:
    .word _estack
    .word Reset_Handler
    .size isr_vector, .-isr_vector

    .section .text
    .global Reset_Handler
    .type Reset_Handler, %function
Reset_Handler:
    ldr r0, =_sdata
    ldr r1, =_edata
    ldr r2, =_sidata
    b .Lcopy_check
.Lcopy_loop:
    ldr r3, [r2]
    str r3, [r0]
    adds r0, r0, #4
    adds r2, r2, #4
.Lcopy_check:
    cmp r0, r1
    bcc .Lcopy_loop

    ldr r0, =_sbss
    ldr r1, =_ebss
    movs r3, #0
    b .Lzero_check
.Lzero_loop:
    str r3, [r0]
    adds r0, r0, #4
.Lzero_check:
    cmp r0, r1
    bcc .Lzero_loop

    bl main

.Lhalt:
    bkpt #0
    b .Lhalt
    .size Reset_Handler, .-Reset_Handler
