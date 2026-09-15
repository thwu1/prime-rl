bits 16

mov ax, 10
mov bx, 20
cmp ax, bx
jge skip_swap
mov cx, ax
mov ax, bx
mov bx, cx
skip_swap:
sub ax, bx
