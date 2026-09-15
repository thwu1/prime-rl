# Combined optimization with loop
# Requires iterative dataflow, CSE, constant propagation, and DCE
FUNC main():
  entry:
    n = 10
    sum = 0
    i = 0
    base = 5
    factor = 3
    offset = base * factor
    GOTO loop_header
  loop_header:
    cond = i < n
    IF cond GOTO loop_body ELSE GOTO loop_exit
  loop_body:
    invariant = base * factor
    temp = i + invariant
    sum = sum + temp
    dead1 = i * i
    dead2 = dead1 + sum
    j = i + 1
    extra = base * factor
    dead3 = extra + dead2
    i = j
    GOTO loop_header
  loop_exit:
    redundant = base * factor
    result = sum + redundant
    PRINT result
    PRINT sum
    RETURN 0
END
