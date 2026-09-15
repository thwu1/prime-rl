bits 16
mov cx, 10
mov ax, 0
mov bx, 1
fib_loop:
add ax, bx
mov dx, ax
mov ax, bx
mov bx, dx
sub cx, 1
jnz fib_loop
