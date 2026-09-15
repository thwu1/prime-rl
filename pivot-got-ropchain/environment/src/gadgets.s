.text
.global usefulGadgets
.type usefulGadgets, @function
usefulGadgets:
    pop %rax
    ret
    xchg %rax, %rsp
    ret
    mov (%rax), %rax
    ret
    add %rbp, %rax
    ret
    pop %rbp
    ret
    pop %rdi
    ret
    pop %rsi
    ret
    pop %rdx
    ret
    jmpq *%rax
