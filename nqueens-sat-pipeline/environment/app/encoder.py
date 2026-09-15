"""
SAT encoder for n-Queens Completion.

Encodes the problem as DIMACS CNF. Primary variable for queen at (i, j) is i*n + j + 1.
Uses pairwise constraints for at-most-one on rows, columns, and diagonals.
"""


def encode(instance):
    """Encode an n-Queens Completion instance as DIMACS CNF.

    Args:
        instance: Dict with "n" (int) and "queens" (list of [r, c] pairs).

    Returns:
        DIMACS CNF string.
    """
    n = instance["n"]
    pre_placed = [tuple(q) for q in instance["queens"]]
    pre_placed_set = set(pre_placed)

    def var(i, j):
        return i * n + j + 1

    clauses = []

    placed_rows = {r for r, _ in pre_placed_set}
    placed_cols = {c for _, c in pre_placed_set}
    placed_diags = {r + c for r, c in pre_placed_set}
    placed_antis = {r - c for r, c in pre_placed_set}

    def is_free(i, j):
        """Check if cell (i,j) is neither pre-placed nor attacked by any pre-placed queen."""
        if (i, j) in pre_placed_set:
            return False
        return (
            i not in placed_rows
            and j not in placed_cols
            and (i + j) not in placed_diags
            and (i - j) not in placed_antis
        )

    # ---- Unit clauses for pre-placed queens ----
    for r, c in pre_placed:
        clauses.append([var(r, c)])

    # ---- Blocking clauses for attacked cells ----
    for i in range(n):
        for j in range(n):
            if (i, j) not in pre_placed_set and not is_free(i, j):
                clauses.append([-var(i, j)])

    # ---- Pairwise at-most-one encoding ----
    def amo_pairwise(variables):
        """Add at-most-one constraints using pairwise encoding."""
        for a in range(len(variables)):
            for b in range(a + 1, len(variables)):
                clauses.append([-variables[a], -variables[b]])

    def exactly_one(variables):
        """Add exactly-one constraint: at-least-one + at-most-one."""
        if not variables:
            clauses.append([])
            return
        clauses.append(list(variables))
        amo_pairwise(variables)

    # ---- Row constraints (exactly one queen per unplaced row) ----
    for r in range(n):
        if r in placed_rows:
            continue
        free_vars = [var(r, c) for c in range(n) if is_free(r, c)]
        exactly_one(free_vars)

    # ---- Column constraints (at most one queen per unoccupied column) ----
    for c in range(n):
        if c in placed_cols:
            continue
        free_vars = [var(r, c) for r in range(n) if is_free(r, c)]
        amo_pairwise(free_vars)

    # ---- Diagonal constraints (r + c = d) ----
    for d in range(2 * n - 1):
        if d in placed_diags:
            continue
        free_vars = []
        for r in range(max(0, d - n + 1), min(n, d + 1)):
            c = d - r
            if is_free(r, c):
                free_vars.append(var(r, c))
        amo_pairwise(free_vars)

    # ---- Anti-diagonal constraints (r - c = a) ----
    for a in range(-(n - 1), n):
        if a in placed_antis:
            continue
        free_vars = []
        for r in range(max(0, a), min(n, n + a)):
            c = r - a
            if 0 <= c < n and is_free(r, c):
                free_vars.append(var(r, c))
        amo_pairwise(free_vars)

    # ---- Build DIMACS string ----
    num_vars = n * n
    header = f"p cnf {num_vars} {len(clauses)}"
    lines = [header]
    for clause in clauses:
        parts = [str(l) for l in clause] + ['0']
        lines.append(' '.join(parts))
    return '\n'.join(lines) + '\n'
