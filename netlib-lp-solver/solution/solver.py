#!/usr/bin/env python3
"""
Netlib LP Benchmark Solver
MPS parser and two-phase revised simplex method implementation.
No external LP solver libraries -- only numpy for linear algebra.

"""

import numpy as np
import json
import os
import sys


# ---------------------------------------------------------------------------
# MPS Parser
# ---------------------------------------------------------------------------

def parse_mps(filename):
    """
    Parse a standard (expanded) MPS format file.

    Returns
    -------
    obj_name : str
    con_names : list[str]
    con_types : list[str]   ('L', 'G', or 'E')
    var_names : list[str]
    c : ndarray (n,)        objective coefficients (minimisation)
    A : ndarray (m, n)      constraint matrix
    b : ndarray (m,)        right-hand side
    lo : ndarray (n,)       lower bounds
    up : ndarray (n,)       upper bounds
    """
    with open(filename, "r") as fh:
        lines = fh.readlines()

    section = None
    obj_name = None
    row_list = []
    row_type_map = {}
    col_list = []
    col_seen = set()
    coeff = {}          # (row, col) -> value
    rhs_map = {}        # row -> value
    bound_map = {}      # col -> [lo, up]

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.startswith("*"):
            continue

        # Section headers are NOT indented (column 0 is not a space)
        if line[0] != " ":
            token = line.split()[0]
            section = {
                "NAME": "NAME", "ROWS": "ROWS", "COLUMNS": "COLUMNS",
                "RHS": "RHS", "RANGES": "RANGES", "BOUNDS": "BOUNDS",
            }.get(token, section)
            if token == "ENDATA":
                break
            continue

        parts = line.split()
        if not parts:
            continue

        # ---- ROWS ----
        if section == "ROWS":
            rtype, rname = parts[0], parts[1]
            row_type_map[rname] = rtype
            row_list.append(rname)
            if rtype == "N" and obj_name is None:
                obj_name = rname

        # ---- COLUMNS ----
        elif section == "COLUMNS":
            if "'MARKER'" in line:
                continue
            cname = parts[0]
            if cname not in col_seen:
                col_list.append(cname)
                col_seen.add(cname)
            i = 1
            while i + 1 < len(parts):
                rname, val = parts[i], float(parts[i + 1])
                coeff[(rname, cname)] = coeff.get((rname, cname), 0.0) + val
                i += 2

        # ---- RHS ----
        elif section == "RHS":
            i = 1
            while i + 1 < len(parts):
                rhs_map[parts[i]] = float(parts[i + 1])
                i += 2

        # ---- BOUNDS ----
        elif section == "BOUNDS":
            btype = parts[0]
            cname = parts[2]
            if cname not in bound_map:
                bound_map[cname] = [0.0, float("inf")]
            if btype == "UP":
                bound_map[cname][1] = float(parts[3])
            elif btype == "LO":
                bound_map[cname][0] = float(parts[3])
            elif btype == "FX":
                v = float(parts[3])
                bound_map[cname] = [v, v]
            elif btype == "FR":
                bound_map[cname] = [float("-inf"), float("inf")]
            elif btype == "MI":
                bound_map[cname][0] = float("-inf")
            elif btype == "PL":
                bound_map[cname][1] = float("inf")
            elif btype == "BV":
                bound_map[cname] = [0.0, 1.0]

        # RANGES not needed for selected problems
        elif section == "RANGES":
            pass

    # Build arrays
    con_names = [r for r in row_list if r != obj_name]
    con_types = [row_type_map[r] for r in con_names]
    m, n = len(con_names), len(col_list)

    c = np.zeros(n)
    for j, cn in enumerate(col_list):
        c[j] = coeff.get((obj_name, cn), 0.0)

    A = np.zeros((m, n))
    for i, rn in enumerate(con_names):
        for j, cn in enumerate(col_list):
            A[i, j] = coeff.get((rn, cn), 0.0)

    b = np.zeros(m)
    for i, rn in enumerate(con_names):
        b[i] = rhs_map.get(rn, 0.0)

    lo = np.zeros(n)
    up = np.full(n, np.inf)
    for j, cn in enumerate(col_list):
        if cn in bound_map:
            lo[j], up[j] = bound_map[cn]

    return obj_name, con_names, con_types, col_list, c, A, b, lo, up


# ---------------------------------------------------------------------------
# Revised Simplex (Bland's rule)
# ---------------------------------------------------------------------------

def _simplex(c, A, b, basis, max_iter=500000):
    """
    Revised simplex for  min c^T x,  Ax = b,  x >= 0.
    Uses Bland's smallest-subscript rule for anti-cycling.

    Returns (x, obj, basis, status).
    """
    m, n = A.shape
    basis = basis.copy()

    for _ in range(max_iter):
        B = A[:, basis]
        try:
            xB = np.linalg.solve(B, b)
        except np.linalg.LinAlgError:
            return None, None, basis, "singular"

        cB = c[basis]
        try:
            pi = np.linalg.solve(B.T, cB)
        except np.linalg.LinAlgError:
            return None, None, basis, "singular"

        # Pricing -- Bland's rule: first j with negative reduced cost
        bset = set(basis.tolist())
        entering = -1
        for j in range(n):
            if j not in bset:
                rc = c[j] - pi @ A[:, j]
                if rc < -1e-8:
                    entering = j
                    break

        if entering == -1:
            # Optimal
            x = np.zeros(n)
            for i in range(m):
                x[basis[i]] = max(xB[i], 0.0)
            return x, float(cB @ xB), basis.copy(), "optimal"

        d = np.linalg.solve(B, A[:, entering])

        # Ratio test (Bland tie-breaking on basis index)
        min_ratio = np.inf
        leave = -1
        for i in range(m):
            if d[i] > 1e-10:
                r = max(xB[i], 0.0) / d[i]
                if r < min_ratio - 1e-12:
                    min_ratio = r
                    leave = i
                elif leave >= 0 and abs(r - min_ratio) <= 1e-12:
                    if basis[i] < basis[leave]:
                        leave = i

        if leave == -1:
            return None, None, basis.copy(), "unbounded"

        basis[leave] = entering

    return None, None, basis.copy(), "iteration_limit"


# ---------------------------------------------------------------------------
# Full LP solver  (two-phase simplex with bound handling)
# ---------------------------------------------------------------------------

def solve_lp(c_orig, A_orig, b_orig, con_types_orig, lo_orig, up_orig):
    """
    Solve  min c^T x  subject to constraints and bounds.

    Returns (optimal_value, status_string).
    """
    c = c_orig.copy()
    A = A_orig.copy()
    b = b_orig.copy()
    lo = lo_orig.copy()
    up = up_orig.copy()
    con_types = list(con_types_orig)
    m_orig, n_orig = A.shape
    obj_offset = 0.0

    # ---- 1. Shift lower bounds to zero ----
    for j in range(n_orig):
        if lo[j] != 0.0 and np.isfinite(lo[j]):
            b -= A[:, j] * lo[j]
            obj_offset += c[j] * lo[j]
            if np.isfinite(up[j]):
                up[j] -= lo[j]
            lo[j] = 0.0

    # ---- 2. Split free variables (lo=-inf) ----
    free_idx = [j for j in range(n_orig) if lo[j] < -1e30]
    n_free = len(free_idx)
    if n_free > 0:
        Ae = np.zeros((m_orig, n_orig + n_free))
        Ae[:, :n_orig] = A
        ce = np.zeros(n_orig + n_free)
        ce[:n_orig] = c
        upe = np.full(n_orig + n_free, np.inf)
        upe[:n_orig] = up
        for k, j in enumerate(free_idx):
            Ae[:, n_orig + k] = -A[:, j]
            ce[n_orig + k] = -c[j]
            lo[j] = 0.0
            up[j] = np.inf
            upe[j] = np.inf
        A, c, up = Ae, ce, upe

    n_cur = A.shape[1]

    # ---- 3. Add slack / surplus variables ----
    n_ineq = sum(1 for t in con_types if t in ("L", "G"))
    ub_pairs = [(j, up[j]) for j in range(n_cur) if np.isfinite(up[j]) and up[j] < 1e30]
    n_ub = len(ub_pairs)

    m_total = m_orig + n_ub
    n_total = n_cur + n_ineq + n_ub

    Aeq = np.zeros((m_total, n_total))
    Aeq[:m_orig, :n_cur] = A
    beq = np.zeros(m_total)
    beq[:m_orig] = b
    ceq = np.zeros(n_total)
    ceq[:n_cur] = c

    scol = n_cur
    row_slack = {}
    for i in range(m_orig):
        if con_types[i] == "L":
            Aeq[i, scol] = 1.0
            row_slack[i] = scol
            scol += 1
        elif con_types[i] == "G":
            Aeq[i, scol] = -1.0
            row_slack[i] = scol
            scol += 1

    ub_slack_base = scol
    for k, (j, uj) in enumerate(ub_pairs):
        r = m_orig + k
        Aeq[r, j] = 1.0
        Aeq[r, ub_slack_base + k] = 1.0
        beq[r] = uj

    # ---- 4. Negate rows with b < 0 so all RHS >= 0 ----
    for i in range(m_total):
        if beq[i] < -1e-15:
            Aeq[i, :] *= -1
            beq[i] *= -1

    # ---- 5. Identify natural basic variables ----
    natural = {}
    for i in range(m_orig):
        if i in row_slack:
            sc = row_slack[i]
            if abs(Aeq[i, sc] - 1.0) < 1e-12:
                natural[i] = sc
    for k in range(n_ub):
        r = m_orig + k
        sc = ub_slack_base + k
        if abs(Aeq[r, sc] - 1.0) < 1e-12:
            natural[r] = sc

    # ---- 6. Phase 1 ----
    need_art = [i for i in range(m_total) if i not in natural]
    n_art = len(need_art)

    if n_art > 0:
        n_ph1 = n_total + n_art
        A1 = np.zeros((m_total, n_ph1))
        A1[:, :n_total] = Aeq
        for k, i in enumerate(need_art):
            A1[i, n_total + k] = 1.0

        c1 = np.zeros(n_ph1)
        for k in range(n_art):
            c1[n_total + k] = 1.0

        basis = np.empty(m_total, dtype=int)
        art_idx_map = {row: k for k, row in enumerate(need_art)}
        for i in range(m_total):
            if i in natural:
                basis[i] = natural[i]
            else:
                basis[i] = n_total + art_idx_map[i]

        _, obj1, basis, status = _simplex(c1, A1, beq, basis)
        if status != "optimal":
            return None, "phase1_" + status
        if obj1 > 1e-6:
            return None, "infeasible"

        # Remove artificial variables still in basis (degenerate, value 0)
        for i in range(m_total):
            if basis[i] >= n_total:
                B = A1[:, basis]
                for j in range(n_total):
                    if j not in basis:
                        try:
                            d = np.linalg.solve(B, A1[:, j])
                        except np.linalg.LinAlgError:
                            continue
                        if abs(d[i]) > 1e-10:
                            basis[i] = j
                            break
    else:
        basis = np.array([natural[i] for i in range(m_total)])

    # ---- 7. Phase 2 ----
    _, obj2, _, status = _simplex(ceq, Aeq, beq, basis)
    if status != "optimal":
        return None, "phase2_" + status

    return obj2 + obj_offset, "optimal"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

PROBLEMS = ["afiro", "sc50b", "kb2", "share2b", "adlittle"]


def main():
    results = {}
    all_ok = True

    for name in PROBLEMS:
        mps_file = f"/app/problems/{name}.mps"
        if not os.path.exists(mps_file):
            print(f"[SKIP] {mps_file} not found", file=sys.stderr)
            results[name] = None
            all_ok = False
            continue

        print(f"Solving {name} ... ", end="", flush=True)
        _, _, con_types, _, c, A, b, lo, up = parse_mps(mps_file)
        opt, status = solve_lp(c, A, b, con_types, lo, up)

        if status == "optimal" and opt is not None:
            results[name] = opt
            print(f"obj={opt:.10e}  status={status}")
        else:
            results[name] = None
            print(f"FAILED ({status})")
            all_ok = False

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
