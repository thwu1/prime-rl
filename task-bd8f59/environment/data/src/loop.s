.text
.globl _start
_start:
    addi x1, x0, 0
    addi x2, x0, 5
    addi x3, x0, 1
.Lloop:
    add  x1, x1, x3
    addi x3, x3, 1
    bge  x2, x3, .Lloop
    ecall
