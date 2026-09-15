bits 16
mov bp, 64
mov dx, 0
y_loop:
    mov cx, 0
    x_loop:
        mov word [bp + 0], cx
        mov word [bp + 2], dx
        mov byte [bp + 3], 255
        add bp, 4
        add cx, 1
        cmp cx, 8
        jnz x_loop
    add dx, 1
    cmp dx, 8
    jnz y_loop
