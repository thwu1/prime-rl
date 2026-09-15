.text
.globl func_beta
func_beta:
    movl %edi, %ebx
    movl %esi, %ecx
    imull %ecx, %ebx
    addl $3, %ebx
    movl %ebx, %eax
    retq
