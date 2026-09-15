.text
.globl func_gamma
func_gamma:
    movq %rdi, %r8
    movl %esi, %r9d
    addl %r9d, %r8d
    shll $2, %r8d
    movl %r8d, %eax
    retq
