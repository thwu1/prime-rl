"""Target functions for fuzzing and coverage testing."""


def classify_triangle(a: int, b: int, c: int) -> str:
    """Classify a triangle by its side lengths."""
    if a <= 0 or b <= 0 or c <= 0:
        return "invalid"
    if a + b <= c or b + c <= a or a + c <= b:
        return "invalid"
    if a == b == c:
        return "equilateral"
    if a == b or b == c or a == c:
        return "isosceles"
    return "scalene"


def binary_search(arr: list[int], target: int) -> int:
    """Binary search returning index or -1."""
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1


def collatz_steps(n: int) -> int:
    """Count steps to reach 1 in the Collatz sequence."""
    if n <= 0:
        raise ValueError("n must be positive")
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps += 1
    return steps
