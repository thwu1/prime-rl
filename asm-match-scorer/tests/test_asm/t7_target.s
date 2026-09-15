.text
.globl func_eta
func_eta:
    movl %edi, %eax
    imull %esi, %eax
    addl %edx, %eax
    shll $3, %eax
    orl $0xff, %eax
    xorl %ecx, %eax
    retq
