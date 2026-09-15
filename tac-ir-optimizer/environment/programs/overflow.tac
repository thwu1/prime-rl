# Integer overflow: constant folding must use 32-bit wrapping semantics
function target():
  entry:
    a = 2147483647
    b = 1
    c = add a b
    d = 2147483647
    e = sub c d
    return e
