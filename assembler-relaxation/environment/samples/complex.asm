# Multi-feature program with alignment, mixed jumps, calls
    push r0
    push r1
    mov r0, 0
    jmp loop_start
    .align 16
setup:
    mov r1, 100
    call helper
    jz done
    .fill 130
loop_start:
    add r0, 1
    cmp r0, r1
    jl loop_start
    jmp done
    .fill 50
helper:
    nop
    ret
done:
    pop r1
    pop r0
    ret
