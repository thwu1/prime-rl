func:
    pushq   %rbx
    pushq   %rcx
    movq    %rdi, %rbx
    movq    %rsi, %rcx
    addq    %rcx, %rbx
    movq    %rbx, %rax
    popq    %rcx
    popq    %rbx
    retq
