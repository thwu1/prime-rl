bits 16

mov bx, 1000
mov word [bx], 1
mov word [bx+2], 2
mov word [bx+4], 3
mov ax, [bx]
add ax, [bx+2]
add ax, [bx+4]
