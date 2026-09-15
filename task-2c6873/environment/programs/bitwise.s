; bitwise.s - Shift, rotate, and logic operations
; Expected result: $v0 = 29
    addiu $v0, $zero, 255     ; v0 = 0xFF
    shl   $v1, $v0, 8         ; v1 = 0xFF00
    ori   $v1, $v1, 0xAA      ; v1 = 0xFFAA
    shr   $a0, $v1, 4         ; a0 = 0x0FFA (logical shift right)
    andi  $a1, $a0, 0xFF      ; a1 = 0xFA = 250
    xori  $t0, $a1, 0xFF      ; t0 = 0x05 = 5
    nor   $t1, $t0, $zero     ; t1 = ~5 = 0xFFFFFFFA
    clz   $v0, $t0            ; v0 = clz(5) = 29
    ret   $lr
