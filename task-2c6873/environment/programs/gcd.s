; GCD(252, 105) = 21 via Euclidean algorithm
.text
.globl _start
_start:
    addiu $v0, $zero, 252
    addiu $v1, $zero, 105
gcd_loop:
    beq $v1, $zero, gcd_done
    divu $v0, $v1
    mfhi $t0
    addu $v0, $v1, $zero
    addu $v1, $t0, $zero
    jmp gcd_loop
gcd_done:
    ret $lr
