bits 16
mov bx, 1001
mov word [bx], 0x1234
mov ax, [bx]
mov si, 2000
mov word [si], 0x5678
add ax, [si]
