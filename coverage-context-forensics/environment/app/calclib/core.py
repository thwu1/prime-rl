"""Core mathematical operations."""

import math


def safe_divide(a, b, mode="float"):
    """Divide a by b with configurable zero-handling."""
    if b == 0:
        if mode == "float":
            if a > 0:
                return float('inf')
            elif a < 0:
                return float('-inf')
            else:
                return float('nan')
        elif mode == "int":
            raise ZeroDivisionError("integer division by zero")
        elif mode == "safe":
            return 0
        else:
            raise ValueError(f"Unknown mode: {mode}")
    if mode == "float":
        return a / b
    elif mode == "int":
        return a // b
    elif mode == "safe":
        return a / b
    else:
        raise ValueError(f"Unknown mode: {mode}")


def classify_number(n):
    """Classify a number into a category string."""
    if not isinstance(n, (int, float)):
        raise TypeError(f"Expected number, got {type(n).__name__}")
    if isinstance(n, float):
        if math.isnan(n):
            return "nan"
        if math.isinf(n):
            return "positive_infinity" if n > 0 else "negative_infinity"
    if n == 0:
        return "zero"
    elif n > 0:
        if isinstance(n, int) and is_prime(n):
            return "positive_prime"
        elif isinstance(n, int) and n % 2 == 0:
            return "positive_even"
        elif isinstance(n, int):
            return "positive_odd"
        else:
            return "positive_float"
    else:
        if isinstance(n, int) and n % 2 == 0:
            return "negative_even"
        elif isinstance(n, int):
            return "negative_odd"
        else:
            return "negative_float"


def is_prime(n):
    """Check if n is prime."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(math.sqrt(n)) + 1, 2):
        if n % i == 0:
            return False
    return True


def fibonacci(n, method="iterative"):
    """Generate first n Fibonacci numbers."""
    if n <= 0:
        return []
    if n == 1:
        return [0]
    if method == "iterative":
        seq = [0, 1]
        for _ in range(2, n):
            seq.append(seq[-1] + seq[-2])
        return seq
    elif method == "recursive":
        def _fib(k):
            if k <= 1:
                return k
            return _fib(k - 1) + _fib(k - 2)
        return [_fib(i) for i in range(n)]
    elif method == "closed":
        phi = (1 + math.sqrt(5)) / 2
        return [round(phi**i / math.sqrt(5)) for i in range(n)]
    else:
        raise ValueError(f"Unknown method: {method}")
