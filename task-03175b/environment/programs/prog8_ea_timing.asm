bits 16
mov bx, 0x400
mov bp, 0x500
mov si, 8
mov di, 16
mov [bx+di], bx
mov ax, [bx+di]
mov [bp+si], ax
mov cx, [bx+si]
mov word [bp+di+2], 999
mov dx, [bp+di+2]
add [bp+si+2], dx
mov si, [bx+di+2]
add ax, dx
