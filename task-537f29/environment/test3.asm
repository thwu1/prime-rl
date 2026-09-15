bits 16
mov ax, 42
mov [0x1000], ax
mov ax, 58
mov [0x1002], ax
mov ax, [0x1000]
mov bx, [0x1002]
add ax, bx
mov [0x1004], ax
