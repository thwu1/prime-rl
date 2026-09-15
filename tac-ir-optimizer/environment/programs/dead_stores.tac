# Dead stores: overwritten before use and never-used variables
function target():
  entry:
    a = 5
    b = 10
    c = 15
    a = 42
    b = 99
    d = add a c
    x = 1000
    y = 2000
    z = add x y
    return d
