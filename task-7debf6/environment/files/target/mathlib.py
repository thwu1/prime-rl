def abs_val(x):
    """Absolute value."""
    if x < 0:
        return -x
    return x


def clamp(value, low, high):
    """Clamp value to [low, high] range."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def linear_search(arr, target):
    """Return index of target in arr, or -1 if not found."""
    for i in range(len(arr)):
        if arr[i] == target:
            return i
    return -1


def is_sorted(arr):
    """Check if array is sorted in non-decreasing order."""
    for i in range(len(arr) - 1):
        if arr[i] > arr[i + 1]:
            return False
    return True


def dot_product(a, b):
    """Compute dot product of two vectors."""
    if len(a) != len(b):
        raise ValueError("Vectors must have same length")
    result = 0
    for i in range(len(a)):
        result = result + a[i] * b[i]
    return result


def mean(values):
    """Compute arithmetic mean."""
    if len(values) == 0:
        raise ValueError("Empty list")
    total = 0
    for v in values:
        total = total + v
    return total / len(values)


def variance(values):
    """Compute sample variance."""
    if len(values) < 2:
        raise ValueError("Need at least 2 values")
    m = mean(values)
    total = 0
    for v in values:
        diff = v - m
        total = total + diff * diff
    return total / (len(values) - 1)


def gcd(a, b):
    """Greatest common divisor."""
    while b != 0:
        a, b = b, a % b
    return a


def is_leap_year(year):
    """Check if a year is a leap year."""
    if year % 4 != 0:
        return False
    if year % 100 != 0:
        return True
    if year % 400 != 0:
        return False
    return True


def is_valid_triangle(a, b, c):
    """Check if three sides can form a valid triangle."""
    if a <= 0 or b <= 0 or c <= 0:
        return False
    return a + b > c and a + c > b and b + c > a
