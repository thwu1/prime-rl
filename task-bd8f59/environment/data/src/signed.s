.text
.globl _start
_start:
    addi  x1, x0, -1
    addi  x2, x0, 1
    slt   x3, x1, x2
    sltu  x4, x1, x2
    bltu  x1, x2, .Lskip1
    addi  x5, x0, 1
.Lskip1:
    bgeu  x1, x2, .Lskip2
    addi  x6, x0, 99
.Lskip2:
    addi  x6, x0, 2
    lui   x7, 0x80000
    slt   x8, x7, x2
    sltu  x9, x7, x2
    srai  x10, x7, 16
    srli  x11, x7, 16
    xori  x12, x1, -1
    ori   x13, x0, -1
    andi  x14, x1, 0x7F
    slti  x15, x1, 0
    sltiu x16, x1, 1
    ecall
