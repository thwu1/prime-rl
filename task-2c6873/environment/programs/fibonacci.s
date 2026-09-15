; fibonacci.s - Compute fib(12) = 144
; Tests function calls via JSUB/RET and stack operations
; Expected result: $v0 = 144
main:
    addiu $sp, $sp, -8
    st    $lr, 4($sp)
    addiu $a0, $zero, 12
    jsub  fibonacci
    ld    $lr, 4($sp)
    addiu $sp, $sp, 8
    ret   $lr

fibonacci:
    ; Iterative fibonacci: fib(n) where n = $a0
    ; Returns result in $v0
    addiu $v0, $zero, 0       ; a = 0
    addiu $v1, $zero, 1       ; b = 1
    addiu $t0, $zero, 0       ; i = 0
fib_loop:
    slt   $t1, $t0, $a0       ; t1 = (i < n) ? 1 : 0
    beq   $t1, $zero, fib_done
    addu  $t9, $v0, $v1       ; temp = a + b
    addu  $v0, $v1, $zero     ; a = b
    addu  $v1, $t9, $zero     ; b = temp
    addiu $t0, $t0, 1         ; i++
    jmp   fib_loop
fib_done:
    ret   $lr
