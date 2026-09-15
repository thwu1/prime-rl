.text
.globl sample_fn
sample_fn:
    pushq %rbp
    movq %rsp, %rbp
    movl %edi, %ebx
    subl %esi, %ebx
    shll $2, %ebx
    movl %ebx, %eax
    popq %rbp
    retq
