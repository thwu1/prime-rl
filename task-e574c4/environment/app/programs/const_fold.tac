# Constant propagation and folding stress test
# Every computation can be resolved at compile time
FUNC main():
  entry:
    a = 7
    b = 3
    c = a + b
    d = c * 2
    e = d - 4
    f = e / 4
    g = f + 1
    h = g * g
    i = h % 10
    j = a * b
    k = j + d
    l = k - c
    m = l * i
    n = m + 100
    p = n > 0
    IF p GOTO print_block ELSE GOTO skip_block
  print_block:
    q = n / 2
    r = q + i
    PRINT r
    GOTO done
  skip_block:
    PRINT 0
    GOTO done
  done:
    s = a + b
    t = s == c
    PRINT t
    RETURN 0
END
