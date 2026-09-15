bits 16
mov cx, 100
mov ax, 0
sum_loop:
add ax, cx
loop sum_loop
mov bx, ax
mov dx, 0x1000
sub dx, ax
mov [0x300], dx
mov si, [0x300]
