"""Mathematical utility library for mutation analysis testing."""


def gcd(a, b):
    """Compute GCD using Euclidean algorithm."""
    a, b = abs(a), abs(b)
    while b != 0:
        a, b = b, a % b
    return a


def lcm(a, b):
    """Compute LCM using GCD."""
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // gcd(a, b)


def is_prime(n):
    """Check if n is prime."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i = i + 2
    return True


def fibonacci(n):
    """Return nth Fibonacci number (0-indexed)."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def binary_search(arr, target):
    """Binary search returning index or -1 if not found."""
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1


def insertion_sort(arr):
    """Sort array using insertion sort. Returns new sorted list."""
    result = list(arr)
    for i in range(1, len(result)):
        key = result[i]
        j = i - 1
        while j >= 0 and result[j] > key:
            result[j + 1] = result[j]
            j = j - 1
        result[j + 1] = key
    return result


def clamp(value, low, high):
    """Clamp value between low and high bounds."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def weighted_average(values, weights):
    """Compute weighted average of values."""
    if len(values) != len(weights):
        raise ValueError("values and weights must have same length")
    total_weight = 0
    weighted_sum = 0
    for i in range(len(values)):
        if weights[i] < 0:
            raise ValueError("weights must be non-negative")
        weighted_sum = weighted_sum + values[i] * weights[i]
        total_weight = total_weight + weights[i]
    if total_weight == 0:
        return 0
    return weighted_sum / total_weight


def is_sorted(arr, ascending=True):
    """Check if array is sorted."""
    for i in range(len(arr) - 1):
        if ascending and arr[i] > arr[i + 1]:
            return False
        if not ascending and arr[i] < arr[i + 1]:
            return False
    return True
