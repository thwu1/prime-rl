.text
.globl func_delta
func_delta:
    movl %edi, %ebx
    movl %esi, %ecx
    movl $10, %edx
    addl %ebx, %ecx
    addl %ecx, %edx
    imull %ebx, %edx
    movl %edx, %eax
    retq
