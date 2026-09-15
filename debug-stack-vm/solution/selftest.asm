# selftest.asm - Comprehensive MiniStack-16 ISA verification
# Tests each instruction category, one result per line.
# Expected output: /app/expected/selftest.txt

# ADD: 100 + 200 = 300
    push 100
    push 200
    add
    puti
    push 10
    putc

# SUB: 80 - 30 = 50
    push 80
    push 30
    sub
    puti
    push 10
    putc

# MUL: 20 * 30 = 600
    push 20
    push 30
    mul
    puti
    push 10
    putc

# DIV: -7 / 2 = -3 (truncated toward zero)
    push -7
    push 2
    div
    puti
    push 10
    putc

# MOD: -7 % 3 = -1 (signed modulo)
    push -7
    push 3
    mod
    puti
    push 10
    putc

# AND: 0x0F0F & 0xF0FF = 0x000F = 15
    push 0x0F0F
    push 0xF0FF
    and
    puti
    push 10
    putc

# OR: 0x0F00 | 0x00F0 = 0x0FF0 = 4080
    push 0x0F00
    push 0x00F0
    or
    puti
    push 10
    putc

# XOR: 0xFF00 ^ 0x0FF0 = 0xF0F0 = -3856 (signed)
    push 0xFF00
    push 0x0FF0
    xor
    puti
    push 10
    putc

# NOT: ~0 = -1
    push 0
    not
    puti
    push 10
    putc

# NEG: -(42) = -42
    push 42
    neg
    puti
    push 10
    putc

# SHL: 5 << 4 = 80
    push 5
    push 4
    shl
    puti
    push 10
    putc

# SHR: -16 >> 2 = -4 (arithmetic right shift)
    push -16
    push 2
    shr
    puti
    push 10
    putc

# EQ: 42 == 42 = 1
    push 42
    push 42
    eq
    puti
    push 10
    putc

# LT: -1 < 1 = 1 (signed comparison)
    push -1
    push 1
    lt
    puti
    push 10
    putc

# GT: 1 > -1 = 1 (signed comparison)
    push 1
    push -1
    gt
    puti
    push 10
    putc

# DUP: push 7, dup, add = 14
    push 7
    dup
    add
    puti
    push 10
    putc

# OVER: push 10, push 20, over -> [10,20,10], add -> [10,30], add -> 40
    push 10
    push 20
    over
    add
    add
    puti
    push 10
    putc

# LOAD/STORE: store 999 at 0xFFF0, load it back
    push 999
    push 0xFFF0
    store
    push 0xFFF0
    load
    puti
    push 10
    putc

    halt
