items: [int] = None
items = [1, 2, 3]
x: int = items[0]
items[1] = 42
n: int = len(items)
more: [int] = items + [4, 5]
empty: [int] = []
print(n)
print(x)
