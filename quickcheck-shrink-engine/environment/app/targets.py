"""Target functions with subtle bugs.

Each function has a documented contract that it violates due to a bug.
Use the property-based testing framework to find minimal counterexamples,
then fix the bugs.
"""


def safe_divide(a, b):
    """Integer division that truncates toward zero (like C and Rust).

    For example:
        safe_divide(7, 2)   ->  3
        safe_divide(-7, 2)  -> -3   (NOT -4, which is Python's -7 // 2)
        safe_divide(7, -2)  -> -3
        safe_divide(0, 5)   ->  0
        safe_divide(5, 0)   ->  0   (defined as 0 for division by zero)

    Property to test: for any a, b with b != 0, the remainder
    r = a - safe_divide(a, b) * b should satisfy:
      - r == 0, OR
      - sign(r) == sign(a)  (remainder has same sign as dividend)
    """
    if b == 0:
        return 0
    return a // b


def rle_encode(xs):
    """Run-length encode a list.

    Returns a list of (value, count) tuples representing consecutive
    runs of equal values.

    Examples:
        rle_encode([])              -> []
        rle_encode([1])             -> [(1, 1)]
        rle_encode([1, 1, 2, 3, 3]) -> [(1, 2), (2, 1), (3, 2)]

    Property to test: rle_decode(rle_encode(xs)) == xs for all lists xs.
    """
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


def rle_decode(encoded):
    """Decode a run-length encoded list."""
    result = []
    for val, count in encoded:
        result.extend([val] * count)
    return result


def unique_sorted(xs):
    """Return a sorted list with duplicate elements removed.

    Examples:
        unique_sorted([])          -> []
        unique_sorted([1])         -> [1]
        unique_sorted([3, 1, 2])   -> [1, 2, 3]
        unique_sorted([3, 1, 2, 1]) -> [1, 2, 3]

    Property to test: set(unique_sorted(xs)) == set(xs) for all lists xs.
    """
    if not xs:
        return []
    s = sorted(xs)
    result = [s[0]]
    for i in range(1, len(s) - 1):
        if s[i] != result[-1]:
            result.append(s[i])
    return result
