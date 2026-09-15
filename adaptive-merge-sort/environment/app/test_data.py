"""Test data generators for sorting benchmarks."""

import random


def random_data(n, seed=42):
    """Generate n random integers in [0, 10*n]."""
    rng = random.Random(seed)
    return [rng.randint(0, n * 10) for _ in range(n)]


def sorted_data(n):
    """Generate a sorted list [0, 1, ..., n-1]."""
    return list(range(n))


def reverse_sorted(n):
    """Generate a reverse-sorted list [n-1, n-2, ..., 0]."""
    return list(range(n - 1, -1, -1))


def pipe_organ(n):
    """Generate a pipe-organ pattern: ascending then descending."""
    half = n // 2
    return list(range(half)) + list(range(n - half - 1, -1, -1))


def saw_tooth(n, teeth=5):
    """Generate a sawtooth pattern: repeated ascending segments."""
    tooth_len = max(1, n // teeth)
    arr = []
    for _ in range(teeth):
        arr.extend(range(tooth_len))
    while len(arr) < n:
        arr.append(0)
    return arr[:n]


def nearly_sorted(n, num_swaps=10, seed=42):
    """Generate a nearly-sorted list: sorted with a few random swaps."""
    rng = random.Random(seed)
    arr = list(range(n))
    for _ in range(num_swaps):
        i = rng.randint(0, n - 1)
        j = rng.randint(0, n - 1)
        arr[i], arr[j] = arr[j], arr[i]
    return arr
