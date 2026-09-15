# Copy propagation feeds constants into operations enabling folding
function target():
  entry:
    x = 10
    y = 20
    z = add x y
    w = mul z 3
    v = sub w x
    u = div v 4
    return u
