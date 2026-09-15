# signed_test.asm - Test signed arithmetic and comparison

# Test 1: Signed less-than with runtime-computed negative value
# Compute -5 by subtracting: 0 - 5 = -5
# Then check: -5 < 3 should be true (1)
    push 0
    push 5
    sub             # 0 - 5 = -5
    push 3
    lt              # (int16)-5 < (int16)3 → 1
    puti
    push 10
    putc

# Test 2: Arithmetic right shift on a negative value
# Compute -16 by subtracting: 0 - 16 = -16
# Arithmetic shift right by 2: -16 >> 2 = -4
    push 0
    push 16
    sub             # 0 - 16 = -16
    push 2
    shr             # arithmetic right shift: -4
    puti
    push 10
    putc

# Test 3: Verify PUSH with negative immediate
# PUSH -1 should produce 0xFFFF = -1 as a signed 16-bit value
    push -1
    puti            # should print -1
    push 10
    putc

    halt
