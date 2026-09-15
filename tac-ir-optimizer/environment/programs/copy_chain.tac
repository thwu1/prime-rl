# Long chain of copies that should all collapse
function target():
  entry:
    origin = 42
    a = copy origin
    b = copy a
    c = copy b
    d = copy c
    e = copy d
    f = copy e
    g = copy f
    h = copy g
    return h
