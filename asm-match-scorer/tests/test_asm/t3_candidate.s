.text
.globl func_gamma
func_gamma:
    movq %rdi, %r9
    movl %esi, %r8d
    addl %r8d, %r9d
    shll $2, %r9d
    movl %r9d, %eax
    retq
