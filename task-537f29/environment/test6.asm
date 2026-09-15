bits 16
mov ax, 0xFF00
mov bx, 0x00FF
and ax, bx
or ax, 0x1234
xor ax, 0xFFFF
not bx
neg ax
mov cx, ax
mov si, 0x100
mov [si], cx
mov [si + 2], bx
mov dx, [si]
xor dx, [si + 2]
