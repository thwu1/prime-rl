.text
.globl func_zeta
func_zeta:
    movl %edi, %eax
    addl %esi, %eax
    shll $1, %eax
    addl $5, %eax
    retq
