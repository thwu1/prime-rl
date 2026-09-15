g: int = 100

def outer(a: int) -> int:
    x: int = 0
    x = a

    def middle(b: int) -> int:
        y: int = 0

        def inner() -> int:
            nonlocal y
            y = y + x + b
            return y

        y = inner()
        return y

    return middle(10)

print(outer(5))
