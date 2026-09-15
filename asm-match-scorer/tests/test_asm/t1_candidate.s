.text
.globl func_alpha
func_alpha:
    pushq %rbp
    movq %rsp, %rbp
    movl %edi, -4(%rbp)
    movl %esi, -8(%rbp)
    movl -4(%rbp), %eax
    imull -8(%rbp), %eax
    addl $7, %eax
    popq %rbp
    retq
