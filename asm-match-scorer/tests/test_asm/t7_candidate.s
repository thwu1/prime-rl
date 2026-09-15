.text
.globl func_eta
func_eta:
    xorl %eax, %eax
    cmpl %edi, %esi
    jge .Lend
    subl %esi, %edi
    movl %edi, %eax
.Lend:
    retq
