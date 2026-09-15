bits 16
mov cx, 5
mov ax, 0
loop_start:
add ax, cx
sub cx, 1
jnz loop_start
