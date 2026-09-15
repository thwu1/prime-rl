def classify_simple(x):
    if x > 99:
        return 100
    elif x > 20:
        return x + 9
    elif x > -2:
        return 103
    else:
        return 99


def quadrant(x, y):
    if x > 0:
        if y > 0:
            return x + y
        else:
            return x - y
    else:
        if y > 0:
            return y - x
        else:
            return -(x + y)


def tricky(x):
    if x > 10:
        if x < 5:
            return 999
        else:
            return x * 2
    else:
        if x > 15:
            return 888
        else:
            return x + 1


def complex_classify(x, y):
    if x + y > 10:
        if x > 0 and y > 0:
            return 1
        elif x > 10:
            return 2
        elif y > 10:
            return 3
        else:
            return 4
    else:
        if x - y > 5:
            return 5
        else:
            return 6


def nested_let(x, y):
    a = x - y
    b = x + y
    if a > 0:
        if b > 0:
            return a + b
        else:
            return a - b
    else:
        if b > 0:
            return b - a
        else:
            return -(a + b)


def range_check(x, y):
    if x > y:
        if y > x:
            return 1
        elif y == x:
            return 2
        else:
            return x - y
    elif x == y:
        if x > y:
            return 4
        else:
            return 0
    else:
        if x > y:
            return 6
        elif x == y:
            return 7
        else:
            return y - x
