#!/usr/bin/env python3
"""
Scorer for the Rectangle Ad Placement problem.
Usage: python3 scorer.py <input_file> <output_file>
Prints Score and Status lines.
"""
import sys


def score_solution(input_path, output_path):
    """Return (score: int, message: str)."""
    # --- read input ---
    with open(input_path) as f:
        n = int(f.readline())
        companies = []
        for _ in range(n):
            x, y, r = map(int, f.readline().split())
            companies.append((x, y, r))

    # --- read output ---
    try:
        with open(output_path) as f:
            rects = []
            for idx in range(n):
                line = f.readline()
                if line is None or line.strip() == "":
                    return 0, f"Missing output for company {idx} (expected {n} lines)"
                parts = line.split()
                if len(parts) != 4:
                    return 0, f"Line {idx}: expected 4 integers, got '{line.strip()}'"
                a, b, c, d = map(int, parts)
                rects.append((a, b, c, d))
    except Exception as e:
        return 0, f"Error reading output: {e}"

    # --- validate rectangles ---
    for i, (a, b, c, d) in enumerate(rects):
        if not (0 <= a < c <= 10000):
            return 0, f"Rect {i}: invalid x range ({a}, {c})"
        if not (0 <= b < d <= 10000):
            return 0, f"Rect {i}: invalid y range ({b}, {d})"

    # --- check pairwise non-overlap (positive common area) ---
    for i in range(n):
        a1, b1, c1, d1 = rects[i]
        for j in range(i + 1, n):
            a2, b2, c2, d2 = rects[j]
            if a1 < c2 and c1 > a2 and b1 < d2 and d1 > b2:
                return 0, f"Rectangles {i} and {j} overlap"

    # --- compute satisfaction ---
    total_p = 0.0
    for i in range(n):
        x, y, r = companies[i]
        a, b, c, d = rects[i]
        s = (c - a) * (d - b)
        # containment of (x+0.5, y+0.5)
        if a <= x and c >= x + 1 and b <= y and d >= y + 1:
            ratio = min(r, s) / max(r, s)
            p = 1.0 - (1.0 - ratio) ** 2
        else:
            p = 0.0
        total_p += p

    final_score = round(1e9 * total_p / n)
    return final_score, "OK"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_file> <output_file>", file=sys.stderr)
        sys.exit(2)
    score, msg = score_solution(sys.argv[1], sys.argv[2])
    print(f"Score: {score}")
    print(f"Status: {msg}")
    sys.exit(0 if msg == "OK" else 1)
