; Basic arithmetic: (10+3)*(10-3) = 91
.text
.globl _start
_start:
    addiu $v0, $zero, 10
    addiu $v1, $zero, 3
    addu $a0, $v0, $v1
    subu $a1, $v0, $v1
    mul $t0, $a0, $a1
    addu $v0, $t0, $zero
    ret $lr
