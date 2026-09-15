count: int = 0

def bump() -> object:
    global count
    count = count + 1

bump()
bump()
bump()
print(count)
