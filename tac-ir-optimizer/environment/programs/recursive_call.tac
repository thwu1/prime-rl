# Recursive function call: optimizer must preserve calls and handle multi-function programs
function factorial(n):
  entry:
    base = 1
    cond = le n base
    jnz cond base_case
    nm1 = sub n 1
    sub_result = call factorial(nm1)
    result = mul n sub_result
    debug = add result 0
    return result
  base_case:
    return 1

function target():
  entry:
    n = 6
    result = call factorial(n)
    unused = mul n 100
    return result
