def gcd(a, b):
    if a == 0:
        return b
    if b == 0:
        return a
    if a < 0:
        a = -a
    if b < 0:
        b = -b
    while b != 0:
        tmp = b
        b = a % b
        a = tmp
    return b
