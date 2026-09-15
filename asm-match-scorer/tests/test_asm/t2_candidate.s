.text
.globl func_beta
func_beta:
    movl %edi, %ecx
    movl %esi, %ebx
    imull %ebx, %ecx
    addl $3, %ecx
    movl %ecx, %eax
    retq
