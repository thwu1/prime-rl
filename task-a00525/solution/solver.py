#!/usr/bin/env python3
"""
Complete solver for n-Queens Completion (QC) and Excluded Diagonals Problem (EDP)
with phase transition analysis.

Fixes the buggy SAT encoder and extends support to EDP instances.
"""

import json
import os
import random
import subprocess
import tempfile
from pathlib import Path


def compute_free_cells(n, pre_placed):
    """Compute cells not occupied or attacked by pre-placed queens."""
    attacked = set()
    pre_set = set(pre_placed)
    for qr, qc in pre_placed:
        for c in range(n):
            attacked.add((qr, c))
        for r in range(n):
            attacked.add((r, qc))
        for d in range(1, n):
            for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nr, nc = qr + dr * d, qc + dc * d
                if 0 <= nr < n and 0 <= nc < n:
                    attacked.add((nr, nc))
    return {
        (r, c) for r in range(n) for c in range(n)
        if (r, c) not in pre_set and (r, c) not in attacked
    }


def compute_edp_valid_cells(n, excl_fwd, excl_bwd):
    """Compute cells not on any excluded diagonal."""
    excl_fwd_set = set(excl_fwd)
    excl_bwd_set = set(excl_bwd)
    return {
        (r, c) for r in range(n) for c in range(n)
        if (r - c) not in excl_fwd_set and (r + c) not in excl_bwd_set
    }


def encode_sat(n, valid_cells, pre_placed=None):
    """Encode n-Queens variant as SAT with CORRECT diagonal constraints.

    Key fix: forward diagonal range is -(n-1) to n-1, not 0 to n-1.
    """
    pre_placed = pre_placed or []
    pre_rows = {r for r, c in pre_placed}
    pre_cols = {c for r, c in pre_placed}
    pre_fwd = {r - c for r, c in pre_placed}
    pre_bwd = {r + c for r, c in pre_placed}

    var_map = {}
    idx = 1
    for r in range(n):
        for c in range(n):
            if (r, c) in valid_cells:
                var_map[(r, c)] = idx
                idx += 1
    num_vars = idx - 1
    clauses = []

    # Row: exactly one per non-pre-placed row
    for r in range(n):
        if r in pre_rows:
            continue
        row_cells = [(r, c) for c in range(n) if (r, c) in valid_cells]
        if not row_cells:
            return None
        clauses.append([var_map[cell] for cell in row_cells])
        for i in range(len(row_cells)):
            for j in range(i + 1, len(row_cells)):
                clauses.append([-var_map[row_cells[i]], -var_map[row_cells[j]]])

    # Column: at-most-one
    for c in range(n):
        if c in pre_cols:
            continue
        col_cells = [(r, c) for r in range(n) if (r, c) in valid_cells]
        for i in range(len(col_cells)):
            for j in range(i + 1, len(col_cells)):
                clauses.append([-var_map[col_cells[i]], -var_map[col_cells[j]]])

    # Forward diagonal at-most-one: d = r - c ranges from -(n-1) to (n-1)
    for d in range(-(n - 1), n):
        if d in pre_fwd:
            continue
        cells = [
            (r, r - d) for r in range(n)
            if 0 <= r - d < n and (r, r - d) in valid_cells
        ]
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                clauses.append([-var_map[cells[i]], -var_map[cells[j]]])

    # Backward diagonal at-most-one: d = r + c ranges from 0 to 2(n-1)
    for d in range(2 * n - 1):
        if d in pre_bwd:
            continue
        cells = [
            (r, d - r) for r in range(n)
            if 0 <= d - r < n and (r, d - r) in valid_cells
        ]
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                clauses.append([-var_map[cells[i]], -var_map[cells[j]]])

    return num_vars, clauses, var_map


def write_dimacs(num_vars, clauses, filepath):
    with open(filepath, "w") as f:
        f.write(f"p cnf {num_vars} {len(clauses)}\n")
        for clause in clauses:
            f.write(" ".join(map(str, clause)) + " 0\n")


def run_minisat(dimacs_path, output_path):
    subprocess.run(
        ["minisat", dimacs_path, output_path],
        capture_output=True, text=True,
    )
    with open(output_path) as f:
        lines = f.readlines()
    if not lines or lines[0].strip() != "SAT":
        return False, set()
    if len(lines) > 1:
        vals = list(map(int, lines[1].strip().split()))
        return True, {v for v in vals if v > 0}
    return True, set()


def solve_with_sat(n, valid_cells, pre_placed=None):
    """Encode, solve, and decode a SAT instance."""
    pre_placed = pre_placed or []
    result = encode_sat(n, valid_cells, pre_placed)
    if result is None:
        return False, None

    num_vars, clauses, var_map = result
    if any(len(c) == 0 for c in clauses):
        return False, None
    if num_vars == 0:
        sol = sorted([[int(r), int(c)] for r, c in pre_placed])
        return True, sol

    with tempfile.NamedTemporaryFile(suffix=".cnf", delete=False) as f:
        dimacs = f.name
    out = dimacs + ".out"
    try:
        write_dimacs(num_vars, clauses, dimacs)
        sat, pos = run_minisat(dimacs, out)
        if sat:
            queens = [[int(r), int(c)] for r, c in pre_placed]
            for (r, c), v in var_map.items():
                if v in pos:
                    queens.append([r, c])
            return True, sorted(queens)
        return False, None
    finally:
        for p in [dimacs, out]:
            if os.path.exists(p):
                os.unlink(p)


def solve_qc(n, pre_placed_list):
    """Solve an n-Queens Completion instance."""
    pre_tuples = [(int(r), int(c)) for r, c in pre_placed_list]
    free = compute_free_cells(n, pre_tuples)
    return solve_with_sat(n, free, pre_tuples)


def solve_edp(n, excl_fwd, excl_bwd):
    """Solve an Excluded Diagonals Problem instance."""
    valid = compute_edp_valid_cells(n, excl_fwd, excl_bwd)
    return solve_with_sat(n, valid)


def load_edp(filepath):
    """Parse .edp file format."""
    n = None
    fwd = []
    bwd = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line.startswith("n="):
                n = int(line.split("=")[1].strip())
            elif line.startswith("D+"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    fwd = [int(x.strip()) for x in content.split(",")]
            elif line.startswith("D-"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    bwd = [int(x.strip()) for x in content.split(",")]
    inst_id = os.path.splitext(os.path.basename(filepath))[0]
    return n, fwd, bwd, inst_id


def generate_random_instance(n, m, rng):
    """Generate a random n-Queens Completion instance with m pre-placed queens."""
    queens = []
    rows, cols, d1, d2 = set(), set(), set(), set()
    for _ in range(m):
        valid = [
            (r, c) for r in range(n) for c in range(n)
            if r not in rows and c not in cols
            and (r - c) not in d1 and (r + c) not in d2
        ]
        if not valid:
            break
        r, c = rng.choice(valid)
        queens.append([r, c])
        rows.add(r)
        cols.add(c)
        d1.add(r - c)
        d2.add(r + c)
    return n, sorted(queens)


def main():
    os.makedirs("/app/results", exist_ok=True)

    # Load experiment configuration
    with open("/app/experiments/config.json") as f:
        config = json.load(f)
    pt_config = config["phase_transition"]

    # ---- Solve QC instances ----
    print("Solving QC instances...")
    qc_dir = Path("/app/data/qc_instances")
    for fp in sorted(qc_dir.glob("*.json")):
        with open(fp) as f:
            inst = json.load(f)
        sat, sol = solve_qc(inst["n"], inst["pre_placed"])
        result = {"id": inst["id"], "satisfiable": sat, "solution": sol}
        with open(f"/app/results/{inst['id']}_result.json", "w") as f:
            json.dump(result, f, indent=2)
        print(f"  {inst['id']}: {'SAT' if sat else 'UNSAT'}")

    # ---- Solve EDP instances ----
    print("Solving EDP instances...")
    edp_dir = Path("/app/data/edp_instances")
    for fp in sorted(edp_dir.glob("*.edp")):
        n, fwd, bwd, inst_id = load_edp(str(fp))
        sat, sol = solve_edp(n, fwd, bwd)
        result = {"id": inst_id, "satisfiable": sat, "solution": sol}
        with open(f"/app/results/{inst_id}_result.json", "w") as f:
            json.dump(result, f, indent=2)
        print(f"  {inst_id}: {'SAT' if sat else 'UNSAT'}")

    # ---- Phase transition experiment ----
    board_size = pt_config["board_size"]
    m_lo, m_hi = pt_config["m_range"]
    samples = pt_config["samples_per_m"]
    seed = pt_config["random_seed"]

    print(f"\nPhase transition: n={board_size}, m={m_lo}..{m_hi}, "
          f"samples={samples}, seed={seed}")
    rng = random.Random(seed)
    results = []

    for m in range(m_lo, m_hi + 1):
        sat_count = 0
        total = 0
        max_attempts = samples * 20
        attempts = 0
        while total < samples and attempts < max_attempts:
            attempts += 1
            n_gen, pre = generate_random_instance(board_size, m, rng)
            if len(pre) < m:
                continue
            sat, _ = solve_qc(n_gen, pre)
            total += 1
            if sat:
                sat_count += 1
        ratio = round(sat_count / total, 4) if total > 0 else 0.0
        results.append({
            "m": m, "total": total,
            "sat_count": sat_count, "sat_ratio": ratio,
        })
        print(f"  m={m}: {sat_count}/{total} ({ratio})")

    critical_m = m_hi
    for entry in results:
        if entry["sat_ratio"] < 0.5:
            critical_m = entry["m"]
            break

    pt = {
        "board_size": board_size,
        "results": results,
        "critical_m": critical_m,
    }
    with open("/app/results/phase_transition.json", "w") as f:
        json.dump(pt, f, indent=2)

    print(f"\nCritical m: {critical_m}")
    print("Done!")


if __name__ == "__main__":
    main()
