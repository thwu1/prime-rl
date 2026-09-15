bits 16
mov bp, 0x2000
mov cx, 4
mov ax, 1
loop_start:
mov bx, ax
shl bx, 1
mov [bp], bx
add bp, 2
add ax, bx
sub cx, 1
jnz loop_start
