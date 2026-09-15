# Pure constant folding: all operands are already literals
function target():
  entry:
    a = add 100 200
    b = sub 50 8
    c = mul 6 7
    d = div 100 3
    e = mod 17 5
    f = neg -5
    g = not 0
    h = bnot 0
    r1 = add a b
    r2 = sub c d
    r3 = mul e f
    r4 = add r1 r2
    r5 = add r4 r3
    r6 = add r5 g
    r7 = add r6 h
    return r7
