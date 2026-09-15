def make_adder(base: int) -> int:
    total: int = 0
    total = base

    def add(n: int) -> int:
        nonlocal total
        total = total + n
        return total

    x: int = 0
    x = add(10)
    x = add(20)
    return x

print(make_adder(5))
