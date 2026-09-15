#!/usr/bin/env python3
"""Find counterexamples for buggy targets and fix the bugs."""

import sys
import json

sys.path.insert(0, "/app")

from pbt.shrink import shrink_int, shrink_nonneg, shrink_list, shrink_tuple
from pbt.engine import quickcheck, TestResult


# ---- Target 1: safe_divide (buggy: uses floor division) ----

def _buggy_safe_divide(a, b):
    if b == 0:
        return 0
    return a // b


def prop_safe_divide(args):
    a, b = args
    if b == 0:
        return True
    q = _buggy_safe_divide(a, b)
    r = a - q * b
    if r == 0:
        return True
    return (r > 0) == (a > 0)


result1 = quickcheck(
    prop_safe_divide,
    generator=lambda gen: (gen.small_int(-50, 50), gen.small_int(-50, 50)),
    shrinker=lambda args: list(shrink_tuple(args, [shrink_int, shrink_int])),
    seed=42,
)
print(f"safe_divide: {result1}")


# ---- Target 2: rle_encode (buggy: missing last run) ----

def _buggy_rle_encode(xs):
    if not xs:
        return []
    result = []
    count = 1
    for i in range(1, len(xs)):
        if xs[i] == xs[i - 1]:
            count += 1
        else:
            result.append((xs[i - 1], count))
            count = 1
    return result


def _rle_decode(encoded):
    result = []
    for val, count in encoded:
        result.extend([val] * count)
    return result


def prop_rle(xs):
    return _rle_decode(_buggy_rle_encode(xs)) == xs


result2 = quickcheck(
    prop_rle,
    generator=lambda gen: gen.list(lambda: gen.small_int(0, 5), max_len=10),
    shrinker=lambda xs: list(shrink_list(xs, shrink_nonneg)),
    seed=42,
)
print(f"rle_encode: {result2}")


# ---- Target 3: unique_sorted (buggy: off-by-one) ----

def _buggy_unique_sorted(xs):
    if not xs:
        return []
    s = sorted(xs)
    result = [s[0]]
    for i in range(1, len(s) - 1):
        if s[i] != result[-1]:
            result.append(s[i])
    return result


def prop_unique_sorted(xs):
    return set(_buggy_unique_sorted(xs)) == set(xs)


result3 = quickcheck(
    prop_unique_sorted,
    generator=lambda gen: gen.list(lambda: gen.small_int(0, 10), max_len=10),
    shrinker=lambda xs: list(shrink_list(xs, shrink_nonneg)),
    seed=42,
)
print(f"unique_sorted: {result3}")


# ---- Write counterexamples ----

counterexamples = {
    "safe_divide": (
        list(result1["counterexample"]) if result1["status"] == "failed" else None
    ),
    "rle_encode": (
        result2["counterexample"] if result2["status"] == "failed" else None
    ),
    "unique_sorted": (
        result3["counterexample"] if result3["status"] == "failed" else None
    ),
}

with open("/app/counterexamples.json", "w") as f:
    json.dump(counterexamples, f, indent=2)

print(f"Counterexamples written: {counterexamples}")


# ---- Fix targets.py ----

fixed_code = '''\
"""Target functions - fixed versions."""


def safe_divide(a, b):
    """Integer division that truncates toward zero (like C and Rust)."""
    if b == 0:
        return 0
    q, r = divmod(a, b)
    # Python divmod uses floor division; adjust for truncation toward zero
    if r != 0 and (a < 0) != (b < 0):
        q += 1
    return q


def rle_encode(xs):
    """Run-length encode a list."""
    if not xs:
        return []
    result = []
    count = 1
    for i in range(1, len(xs)):
        if xs[i] == xs[i - 1]:
            count += 1
        else:
            result.append((xs[i - 1], count))
            count = 1
    result.append((xs[-1], count))
    return result


def rle_decode(encoded):
    """Decode a run-length encoded list."""
    result = []
    for val, count in encoded:
        result.extend([val] * count)
    return result


def unique_sorted(xs):
    """Return a sorted list with duplicate elements removed."""
    if not xs:
        return []
    s = sorted(xs)
    result = [s[0]]
    for i in range(1, len(s)):
        if s[i] != result[-1]:
            result.append(s[i])
    return result
'''

with open("/app/targets.py", "w") as f:
    f.write(fixed_code)

print("targets.py fixed")
