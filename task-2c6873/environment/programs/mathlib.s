; Math library: square and cube functions
.text
.globl square
.globl cube

square:
    ; $a0 = n, returns $v0 = n*n
    mul $v0, $a0, $a0
    ret $lr

cube:
    ; $a0 = n, returns $v0 = n*n*n
    mul $v0, $a0, $a0
    mul $v0, $v0, $a0
    ret $lr
