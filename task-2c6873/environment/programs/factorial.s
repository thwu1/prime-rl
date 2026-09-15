; 10! = 3628800 via loop
.text
.globl _start
_start:
    addiu $v0, $zero, 1
    addiu $t0, $zero, 10
loop:
    mul $v0, $v0, $t0
    addiu $t0, $t0, -1
    slti $t1, $t0, 1
    beq $t1, $zero, loop
    ret $lr
