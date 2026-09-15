# Comprehensive sample: exercises every instruction type
    nop
    push r0
    push r3
    pop r7
    pop r2
    mov r0, r1
    mov r5, r6
    mov r0, 42
    mov r3, -1
    add r2, r4
    add r0, 10
    sub r1, r7
    sub r5, -5
    cmp r3, r6
    cmp r0, 0
    call helper
    jmp end
    jz end
    jnz end
    jl end
    jg end
    jle end
    jge end
helper:
    nop
    ret
end:
    ret
