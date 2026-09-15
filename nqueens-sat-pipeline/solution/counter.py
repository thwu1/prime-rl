"""
Exact solution counter for n-Queens Completion.

Uses backtracking with bitmask-based attack tracking for columns, diagonals,
and anti-diagonals.
"""


def count(instance):
    """Count all valid completions of an n-Queens Completion instance.

    Args:
        instance: Dict with "n" and "queens".

    Returns:
        Integer count of valid completions.
    """
    n = instance["n"]
    pre_placed = instance["queens"]

    placed = {}
    init_cols = 0
    init_diags = 0
    init_antis = 0

    for r, c in pre_placed:
        placed[r] = c
        init_cols |= (1 << c)
        init_diags |= (1 << (r + c))
        init_antis |= (1 << (r - c + n - 1))

    free_rows = sorted(r for r in range(n) if r not in placed)
    result = 0

    def backtrack(idx, cols, diags, antis):
        nonlocal result
        if idx == len(free_rows):
            result += 1
            return
        r = free_rows[idx]
        for c in range(n):
            cb = 1 << c
            db = 1 << (r + c)
            ab = 1 << (r - c + n - 1)
            if (cols & cb) or (diags & db) or (antis & ab):
                continue
            backtrack(idx + 1, cols | cb, diags | db, antis | ab)

    backtrack(0, init_cols, init_diags, init_antis)
    return result
