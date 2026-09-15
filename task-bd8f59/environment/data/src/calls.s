.text
.globl _start
_start:
    addi x1, x0, 3
    jal  x5, double
    addi x10, x0, 0
    ecall
double:
    add  x2, x1, x1
    jalr x0, x5, 0
