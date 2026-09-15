bits 16
mov bx, 0x100
mov si, 0
mov word [bx+si], 0x0a0a
add si, 2
mov word [bx+si], 0x0b0b
add si, 2
mov word [bx+si], 0x0c0c
mov si, 0
mov ax, [bx+si]
add si, 2
mov cx, [bx+si]
add ax, cx
