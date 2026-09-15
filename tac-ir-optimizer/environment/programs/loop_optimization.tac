# Loop with dead stores; loop-carried variables must NOT be eliminated
function target():
  entry:
    sum = 0
    i = 0
    jump loop_test
  loop_body:
    prev = copy sum
    sum = add sum i
    doubled = mul i 2
    tripled = mul i 3
    i = add i 1
  loop_test:
    cond = lt i 10
    jnz cond loop_body
    return sum
