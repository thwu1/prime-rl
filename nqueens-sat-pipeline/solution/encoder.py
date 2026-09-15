"""
n-Queens Completion SAT encoder using Commander encoding for at-most-one constraints.

Encodes the problem as DIMACS CNF. Primary variable for queen at (i, j) is i*n + j + 1.
Commander encoding groups variables into groups of size <= 3, introduces a commander
variable per group, and recurses on the commanders.
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
    next_aux = [n * n + 1]

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

    # ---- Commander at-most-one encoding ----
    def amo_commander(variables):
        """Add at-most-one constraints using Commander encoding (group size <= 3)."""
        if len(variables) <= 1:
            return
        if len(variables) <= 3:
            # Small group: use pairwise encoding directly
            for a in range(len(variables)):
                for b in range(a + 1, len(variables)):
                    clauses.append([-variables[a], -variables[b]])
            return

        # Split into groups of size <= 3
        groups = [variables[i:i + 3] for i in range(0, len(variables), 3)]
        commanders = []

        for group in groups:
            # Pairwise within group
            for a in range(len(group)):
                for b in range(a + 1, len(group)):
                    clauses.append([-group[a], -group[b]])

            # Commander variable for this group
            cmd = next_aux[0]
            next_aux[0] += 1
            commanders.append(cmd)

            # x_i -> commander (if any variable in group is true, commander is true)
            for x in group:
                clauses.append([-x, cmd])

            # commander -> disjunction of group (if commander true, some variable true)
            clauses.append([-cmd] + list(group))

        # Recurse: at-most-one among commanders
        amo_commander(commanders)

    def exactly_one(variables):
        """Add exactly-one constraint: at-least-one + at-most-one."""
        if not variables:
            # No valid positions: add empty clause to force UNSAT
            clauses.append([])
            return
        clauses.append(list(variables))  # at-least-one
        amo_commander(variables)

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
        amo_commander(free_vars)

    # ---- Diagonal constraints (r + c = d) ----
    for d in range(2 * n - 1):
        if d in placed_diags:
            continue
        free_vars = []
        for r in range(max(0, d - n + 1), min(n, d + 1)):
            c = d - r
            if is_free(r, c):
                free_vars.append(var(r, c))
        amo_commander(free_vars)

    # ---- Anti-diagonal constraints (r - c = a) ----
    for a in range(-(n - 1), n):
        if a in placed_antis:
            continue
        free_vars = []
        for r in range(max(0, a), min(n, n + a)):
            c = r - a
            if 0 <= c < n and is_free(r, c):
                free_vars.append(var(r, c))
        amo_commander(free_vars)

    # ---- Build DIMACS string ----
    num_vars = next_aux[0] - 1
    header = f"p cnf {num_vars} {len(clauses)}"
    lines = [header]
    for clause in clauses:
        parts = [str(l) for l in clause] + ['0']
        lines.append(' '.join(parts))
    return '\n'.join(lines) + '\n'
