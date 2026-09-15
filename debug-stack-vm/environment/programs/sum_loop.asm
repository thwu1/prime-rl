# sum_loop.asm - Compute 1 + 2 + ... + 10 = 55
    push 0          # sum = 0
    push 10         # counter = 10

loop:
    dup             # duplicate counter for zero test
    jz done         # if counter == 0, exit loop

    # Add counter to sum: stack is [sum, counter]
    swap            # [counter, sum]
    over            # [counter, sum, counter]
    add             # [counter, sum + counter]
    swap            # [new_sum, counter]

    # Decrement counter
    push 1
    sub             # [new_sum, counter - 1]

    jmp loop

done:
    pop             # remove the zero counter
    puti            # print the sum
    push 10
    putc            # newline
    halt
