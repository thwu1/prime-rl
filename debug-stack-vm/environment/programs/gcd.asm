# gcd.asm - Compute GCD(48, 18) = 6 using Euclidean algorithm
    push 48         # a
    push 18         # b

gcd_loop:
    # Stack: [a, b]
    dup             # [a, b, b]
    jz gcd_done     # if b == 0, done

    # Compute a mod b, rearrange to [b, a%b]
    swap            # [b, a]
    over            # [b, a, b]
    mod             # [b, a % b]

    jmp gcd_loop

gcd_done:
    # Stack: [gcd_result, 0]
    pop             # discard zero
    puti            # print GCD
    push 10
    putc            # newline
    halt
