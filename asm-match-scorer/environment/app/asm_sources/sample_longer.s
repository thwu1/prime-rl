.text
.globl sample_fn
sample_fn:
    pushq %rbp
    movq %rsp, %rbp
    movl %edi, %ebx
    addl %esi, %ebx
    shll $2, %ebx
    addl $42, %ebx
    subl $7, %ebx
    movl %ebx, %eax
    popq %rbp
    retq
