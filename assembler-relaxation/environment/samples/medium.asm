# Forward jump that exceeds short-form range
    jmp target
    .fill 200
target:
    ret
