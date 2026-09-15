.text
.globl _start
_start:
    addi x1, x0, 5
    addi x2, x0, 7
    add  x3, x1, x2
    sub  x4, x1, x2
    and  x5, x1, x2
    or   x6, x1, x2
    xor  x7, x1, x2
    slt  x8, x1, x2
    sltu x9, x1, x2
    slli x10, x1, 2
    srli x11, x2, 1
    srai x12, x2, 1
    lui  x13, 0x12345
    auipc x14, 0x1000
    ecall
