.text
.globl _start
_start:
    addi x1, x0, 10
    addi x2, x0, -1
    addi x3, x0, 1
    beq  x1, x2, .Lset4
    bne  x1, x2, .Lset4
    addi x4, x0, 99
.Lset4:
    addi x4, x0, 42
    blt  x2, x1, .Lset5
    addi x5, x0, 99
.Lset5:
    addi x5, x0, 77
    bge  x1, x2, .Lset6
    addi x6, x0, 99
.Lset6:
    addi x6, x0, 33
    ecall
