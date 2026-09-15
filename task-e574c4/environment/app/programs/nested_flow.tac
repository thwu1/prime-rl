# Complex nested control flow with function calls
# Requires all optimization passes working together
FUNC fibonacci_sum(limit):
  entry:
    a = 0
    b = 1
    total = 0
    count = 0
    GOTO check
  check:
    done = count >= limit
    IF done GOTO finish ELSE GOTO compute
  compute:
    total = total + a
    next = a + b
    a = b
    b = next
    dead_fib1 = a * a
    dead_fib2 = b * b
    dead_fib3 = dead_fib1 + dead_fib2
    count = count + 1
    GOTO check
  finish:
    RETURN total
END

FUNC main():
  entry:
    magic = 6
    scale = 2
    bias = 10
    r1 = CALL fibonacci_sum(magic)
    adjusted = r1 * scale
    with_bias = adjusted + bias
    PRINT with_bias
    redundant_scale = r1 * scale
    redundant_bias = redundant_scale + bias
    chk = with_bias == redundant_bias
    PRINT chk
    dead_final = r1 * r1
    dead_final2 = dead_final + magic
    RETURN 0
END
