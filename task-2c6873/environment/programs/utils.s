; Utility library: sum_range function
.text
.globl sum_range

sum_range:
    ; $a0 = n, returns $v0 = 1+2+...+n
    addiu $v0, $zero, 0
    addiu $t0, $zero, 1
_sr_loop:
    addu $v0, $v0, $t0
    addiu $t0, $t0, 1
    slt $t1, $a0, $t0
    beq $t1, $zero, _sr_loop
    ret $lr
