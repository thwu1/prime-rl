.text
.globl func_delta
func_delta:
    movl %edi, %ecx
    movl %esi, %edx
    movl $10, %ebx
    addl %ecx, %edx
    addl %edx, %ebx
    imull %ecx, %ebx
    movl %ebx, %eax
    retq
