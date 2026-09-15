func:
    pushq   %rcx
    pushq   %rbx
    movq    %rdi, %rcx
    movq    %rsi, %rbx
    addq    %rbx, %rcx
    movq    %rcx, %rax
    popq    %rbx
    popq    %rcx
    retq
