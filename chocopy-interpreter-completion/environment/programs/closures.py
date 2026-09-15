x:int = 10

def outer() -> int:
    y:int = 20
    def inner() -> int:
        nonlocal y
        y = y + x
        return y
    return inner()

print(outer())

def modify_global() -> int:
    global x
    x = x + 5
    return x

print(modify_global())
print(x)
print(modify_global())
print(x)

def counter() -> int:
    n:int = 0
    def inc() -> int:
        nonlocal n
        n = n + 1
        return n
    r:int = 0
    r = inc()
    r = inc()
    r = inc()
    return r

print(counter())

def global_bypass() -> int:
    x:int = 999
    def read_global() -> int:
        global x
        return x
    return read_global()

print(global_bypass())
