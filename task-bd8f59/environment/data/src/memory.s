.text
.globl _start
_start:
    lui  x1, 0x10
    addi x2, x0, 0x42
    sw   x2, 0(x1)
    lw   x3, 0(x1)
    addi x4, x0, -1
    sw   x4, 4(x1)
    lb   x5, 4(x1)
    lbu  x6, 4(x1)
    sh   x2, 8(x1)
    lh   x7, 8(x1)
    lhu  x8, 8(x1)
    sb   x4, 12(x1)
    lbu  x9, 12(x1)
    ecall
