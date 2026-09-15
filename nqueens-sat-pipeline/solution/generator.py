"""
n-Queens Completion instance generator.

Generates random partial placements of non-attacking queens on an n x n board.
"""

import random


def generate(n, m, seed):
    """Generate a random n-Queens Completion instance.

    Args:
        n: Board size.
        m: Number of pre-placed queens.
        seed: Random seed for reproducibility.

    Returns:
        Dictionary with keys "n" and "queens" (list of [row, col] pairs).
    """
    rng = random.Random(seed)

    for _attempt in range(100):
        queens = []
        cols = set()
        diags = set()
        antis = set()

        rows = list(range(n))
        rng.shuffle(rows)

        for row in rows:
            if len(queens) >= m:
                break
            valid = [
                c for c in range(n)
                if c not in cols
                and (row + c) not in diags
                and (row - c) not in antis
            ]
            if not valid:
                continue
            col = rng.choice(valid)
            queens.append([row, col])
            cols.add(col)
            diags.add(row + col)
            antis.add(row - col)

        if len(queens) >= m:
            queens.sort()
            return {"n": n, "queens": queens[:m]}

    # Fallback: return whatever was placed
    queens.sort()
    return {"n": n, "queens": queens}
