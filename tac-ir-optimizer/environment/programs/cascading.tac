# Cascading: constant fold -> copy prop -> dead store, multiple rounds
function target():
  entry:
    a = 2
    b = 3
    c = add a b
    d = copy c
    e = mul d 4
    f = copy e
    g = sub f 10
    h = copy g
    trash1 = 777
    trash2 = copy h
    trash3 = add trash2 trash1
    return h
