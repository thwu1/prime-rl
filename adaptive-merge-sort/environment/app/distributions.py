"""
Run-length distribution generators for testing and experimentation.

"""

import random


def uniform_random(n, lo=1, hi=100, seed=42):
    """Uniformly random run lengths in [lo, hi]."""
    rng = random.Random(seed)
    return [rng.randint(lo, hi) for _ in range(n)]


def geometric_increasing(n, base=1, ratio=1.5):
    """Geometrically increasing run lengths."""
    return [max(1, int(base * ratio ** i)) for i in range(n)]


def geometric_decreasing(n, base=1, ratio=1.5):
    """Geometrically decreasing run lengths."""
    return [max(1, int(base * ratio ** (n - 1 - i))) for i in range(n)]


def alternating_short_long(n, short=1, long_val=100):
    """Alternating short and long runs."""
    return [short if i % 2 == 0 else long_val for i in range(n)]


def nearly_equal(n, base=100, jitter=5, seed=42):
    """Nearly equal run lengths with small jitter."""
    rng = random.Random(seed)
    return [base + rng.randint(-jitter, jitter) for _ in range(n)]


def single_spike(n, spike_val=10000, base=10, spike_pos=None):
    """One very large run among many small ones."""
    if spike_pos is None:
        spike_pos = n // 2
    return [spike_val if i == spike_pos else base for i in range(n)]


def fibonacci_like(n):
    """Fibonacci-like increasing run lengths."""
    if n == 0:
        return []
    if n == 1:
        return [1]
    lengths = [1, 1]
    for _ in range(2, n):
        lengths.append(lengths[-1] + lengths[-2])
    return lengths


def exponential_powers(n):
    """Powers of 2: [1, 2, 4, 8, ...]."""
    return [2 ** i for i in range(n)]
