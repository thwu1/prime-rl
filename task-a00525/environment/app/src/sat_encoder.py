"""SAT encoder for n-Queens Completion instances.

Encodes the n-Queens Completion problem as a propositional satisfiability
problem in DIMACS CNF format. Variables represent queen placement on free
cells (those not occupied or attacked by pre-placed queens).

Constraints:
- Each non-pre-placed row has exactly one queen among free cells
- At-most-one queen per column (for non-pre-placed columns)
- At-most-one queen per forward diagonal (r - c = constant)
- At-most-one queen per backward diagonal (r + c = constant)
"""


def compute_free_cells(n, pre_placed):
    """Compute cells not occupied or attacked by pre-placed queens.

    A cell is 'free' if no pre-placed queen occupies it or attacks it
    via row, column, or diagonal.
    """
    attacked = set()
    pre_set = set(pre_placed)

    for qr, qc in pre_placed:
        # Row and column attacks
        for c in range(n):
            attacked.add((qr, c))
        for r in range(n):
            attacked.add((r, qc))
        # Diagonal attacks in all four directions
        for d in range(1, n):
            for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nr, nc = qr + dr * d, qc + dc * d
                if 0 <= nr < n and 0 <= nc < n:
                    attacked.add((nr, nc))

    free = set()
    for r in range(n):
        for c in range(n):
            if (r, c) not in pre_set and (r, c) not in attacked:
                free.add((r, c))
    return free


def encode_to_sat(n, pre_placed):
    """Encode n-Queens Completion as DIMACS CNF.

    Returns (num_vars, clauses, var_map) where var_map maps (r,c) -> var_number,
    or None if the instance is trivially unsatisfiable.
    """
    pre_placed = [(int(r), int(c)) for r, c in pre_placed]
    free = compute_free_cells(n, pre_placed)
    pre_rows = {r for r, c in pre_placed}
    pre_cols = {c for r, c in pre_placed}

    # Variable mapping: one boolean per free cell
    var_map = {}
    idx = 1
    for r in range(n):
        for c in range(n):
            if (r, c) in free:
                var_map[(r, c)] = idx
                idx += 1
    num_vars = idx - 1

    clauses = []

    # Row constraints: exactly one queen per non-pre-placed row
    for r in range(n):
        if r in pre_rows:
            continue
        row_cells = [(r, c) for c in range(n) if (r, c) in free]
        if not row_cells:
            return None  # No valid cell in this row -> UNSAT
        # At-least-one queen in this row
        clauses.append([var_map[cell] for cell in row_cells])
        # At-most-one queen in this row (pairwise encoding)
        for i in range(len(row_cells)):
            for j in range(i + 1, len(row_cells)):
                clauses.append([-var_map[row_cells[i]], -var_map[row_cells[j]]])

    # Column at-most-one constraints
    for c in range(n):
        if c in pre_cols:
            continue
        col_cells = [(r, c) for r in range(n) if (r, c) in free]
        for i in range(len(col_cells)):
            for j in range(i + 1, len(col_cells)):
                clauses.append([-var_map[col_cells[i]], -var_map[col_cells[j]]])

    # Forward diagonal at-most-one (r - c = constant)
    # Diagonal index d = r - c
    pre_fwd = {r - c for r, c in pre_placed}
    for d in range(n):
        if d in pre_fwd:
            continue
        cells = [
            (r, r - d) for r in range(n)
            if 0 <= r - d < n and (r, r - d) in free
        ]
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                clauses.append([-var_map[cells[i]], -var_map[cells[j]]])

    # Backward diagonal at-most-one (r + c = constant)
    pre_bwd = {r + c for r, c in pre_placed}
    for d in range(2 * n - 1):
        if d in pre_bwd:
            continue
        cells = [
            (r, d - r) for r in range(n)
            if 0 <= d - r < n and (r, d - r) in free
        ]
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                clauses.append([-var_map[cells[i]], -var_map[cells[j]]])

    return num_vars, clauses, var_map


def write_dimacs(num_vars, clauses, filepath):
    """Write clauses in DIMACS CNF format."""
    with open(filepath, "w") as f:
        f.write(f"p cnf {num_vars} {len(clauses)}\n")
        for clause in clauses:
            f.write(" ".join(map(str, clause)) + " 0\n")
