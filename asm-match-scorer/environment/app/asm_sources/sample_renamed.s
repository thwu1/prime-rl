.text
.globl sample_fn
sample_fn:
    pushq %rbp
    movq %rsp, %rbp
    movl %edi, %ecx
    addl %esi, %ecx
    shll $2, %ecx
    movl %ecx, %eax
    popq %rbp
    retq
