bits 16
mov al, 65
mov ah, 66
mov bl, 67
mov bh, 68
mov bp, 256
mov di, 8
mov [bp+di], al
mov [bp+di+1], ah
mov cl, [bp+di]
mov ch, [bp+di+1]
inc cx
dec cx
mov dx, cx
