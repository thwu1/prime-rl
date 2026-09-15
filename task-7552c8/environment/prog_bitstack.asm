bits 16
mov ax, 0xFF00
mov bx, 0x00FF
xor cx, cx
or cx, ax
xor cx, bx
not cx
neg bx
mov dx, 1
shl dx, 1
shl dx, 1
shr dx, 1
mov si, 100
mov di, 200
xchg si, di
mov sp, 1000
push ax
push bx
pop cx
pop dx
