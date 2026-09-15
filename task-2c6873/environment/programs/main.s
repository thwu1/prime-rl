; Multi-file main: square(7) + cube(3) + sum_range(10) = 49 + 27 + 55 = 131
; Requires linking with mathlib.s and utils.s
.text
.globl _start

_start:
    addiu $sp, $sp, -16
    st $lr, 12($sp)

    ; square(7)
    addiu $a0, $zero, 7
    jsub square
    st $v0, 0($sp)

    ; cube(3)
    addiu $a0, $zero, 3
    jsub cube
    ld $t0, 0($sp)
    addu $t0, $t0, $v0
    st $t0, 0($sp)

    ; sum_range(10)
    addiu $a0, $zero, 10
    jsub sum_range
    ld $t0, 0($sp)
    addu $v0, $t0, $v0

    ld $lr, 12($sp)
    addiu $sp, $sp, 16
    ret $lr
