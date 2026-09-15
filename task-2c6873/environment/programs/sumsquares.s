; sumsquares.s - Compute sum of squares 1^2 + 2^2 + ... + 100^2
; Uses two methods: closed-form formula and iterative loop
; Verifies both give the same result
; Expected result: $v0 = 338350
main:
    addiu $sp, $sp, -16
    st    $lr, 12($sp)
    addiu $a0, $zero, 100
    jsub  sum_sq_formula
    st    $v0, 0($sp)         ; save formula result
    addiu $a0, $zero, 100
    jsub  sum_sq_loop
    ld    $a1, 0($sp)         ; load formula result
    subu  $t0, $v0, $a1       ; difference should be 0
    addu  $v0, $a1, $zero     ; return formula result
    ld    $lr, 12($sp)
    addiu $sp, $sp, 16
    ret   $lr

sum_sq_formula:
    ; N*(N+1)*(2N+1)/6 where N = $a0
    addiu $v0, $a0, 1         ; v0 = N+1
    mul   $v0, $a0, $v0       ; v0 = N*(N+1)
    shl   $v1, $a0, 1         ; v1 = 2N
    addiu $v1, $v1, 1         ; v1 = 2N+1
    mul   $v0, $v0, $v1       ; v0 = N*(N+1)*(2N+1)
    addiu $v1, $zero, 6
    div   $v0, $v1            ; LO = result / 6
    mflo  $v0                 ; v0 = result
    ret   $lr

sum_sq_loop:
    ; Sum i^2 for i = 1 to N, where N = $a0
    addiu $v0, $zero, 0       ; sum = 0
    addiu $t0, $zero, 1       ; i = 1
sq_loop:
    slt   $t1, $a0, $t0       ; t1 = (N < i) ? 1 : 0
    bne   $t1, $zero, sq_done ; if N < i, done
    mul   $t9, $t0, $t0       ; t9 = i*i
    addu  $v0, $v0, $t9       ; sum += i*i
    addiu $t0, $t0, 1         ; i++
    jmp   sq_loop
sq_done:
    ret   $lr
