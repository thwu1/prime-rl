func:
    cmpl    $0, %edi
    je      .L1
    movl    $1, %eax
    retq
.L1:
    xorl    %eax, %eax
    retq
