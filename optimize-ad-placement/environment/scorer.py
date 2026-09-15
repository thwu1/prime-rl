#!/usr/bin/env python3
"""Validates and scores a rectangle packing solution for the ad placement problem."""

import sys


def validate_and_score(input_path, output_path):
    """Validate output and compute average satisfaction score.

    Returns (score, error_message). On success error_message is None.
    On failure score is None.
    """
    with open(input_path) as f:
        input_lines = f.read().strip().split('\n')
    with open(output_path) as f:
        output_lines = f.read().strip().split('\n')

    n = int(input_lines[0])
    companies = []
    for i in range(1, n + 1):
        x, y, r = map(int, input_lines[i].split())
        companies.append((x, y, r))

    # Filter out empty lines from output
    output_lines = [line for line in output_lines if line.strip()]

    if len(output_lines) != n:
        return None, f"Expected {n} output lines, got {len(output_lines)}"

    rects = []
    for i in range(n):
        parts = output_lines[i].split()
        if len(parts) != 4:
            return None, f"Line {i}: expected 4 integers, got {len(parts)} values"
        try:
            a, b, c, d = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            return None, f"Line {i}: non-integer values"
        if not (0 <= a < c <= 10000):
            return None, f"Rect {i}: invalid x-range [{a}, {c}] (need 0 <= a < c <= 10000)"
        if not (0 <= b < d <= 10000):
            return None, f"Rect {i}: invalid y-range [{b}, {d}] (need 0 <= b < d <= 10000)"
        rects.append((a, b, c, d))

    # Check pairwise non-overlapping (O(n^2), fine for n <= 200)
    for i in range(n):
        for j in range(i + 1, n):
            a1, b1, c1, d1 = rects[i]
            a2, b2, c2, d2 = rects[j]
            # Two rectangles overlap iff their x-intervals and y-intervals both overlap
            if a1 < c2 and a2 < c1 and b1 < d2 and b2 < d1:
                return None, f"Rectangles {i} and {j} overlap"

    # Compute satisfaction
    total_p = 0.0
    for i in range(n):
        x, y, r = companies[i]
        a, b, c, d = rects[i]
        # Check containment of point (x + 0.5, y + 0.5)
        if a <= x and x + 1 <= c and b <= y and y + 1 <= d:
            s = (c - a) * (d - b)
            ratio = min(r, s) / max(r, s)
            p = 1.0 - (1.0 - ratio) ** 2
        else:
            p = 0.0
        total_p += p

    return total_p / n, None


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_file> <output_file>", file=sys.stderr)
        sys.exit(1)
    score, err = validate_and_score(sys.argv[1], sys.argv[2])
    if err:
        print(f"ERROR: {err}")
        sys.exit(1)
    print(f"Satisfaction: {score:.6f}")
