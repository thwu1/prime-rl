.text
.globl func_epsilon
func_epsilon:
    movl %edi, %eax
    subl %esi, %eax
    retq
