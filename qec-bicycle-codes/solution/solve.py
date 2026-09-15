#!/usr/bin/env python3

"""
Bivariate Bicycle Code Analysis and Circuit Synthesis -- Solution

Constructs BB codes from group algebra specifications, computes [[n, k, d]]
parameters, builds stim syndrome measurement circuits, extracts detector
error models, and constructs pymatching MWPM decoders.
"""

import json
import sys
import os
import numpy as np
import stim
import pymatching


# ======================================================================
# GF(2) Linear Algebra
# ======================================================================

def gf2_rref(M):
    """Row-reduce M over GF(2). Returns (rref_rows, pivot_cols, rank)."""
    M = np.array(M, dtype=np.int32).copy() % 2
    rows, cols = M.shape
    pivot_cols = []
    cur_row = 0
    for col in range(cols):
        pivot = None
        for r in range(cur_row, rows):
            if M[r, col] == 1:
                pivot = r
                break
        if pivot is None:
            continue
        M[[cur_row, pivot]] = M[[pivot, cur_row]]
        for r in range(rows):
            if r != cur_row and M[r, col] == 1:
                M[r] = (M[r] + M[cur_row]) % 2
        pivot_cols.append(col)
        cur_row += 1
    return M[:cur_row].astype(np.uint8), pivot_cols, cur_row


def gf2_rank(M):
    """Rank of binary matrix over GF(2)."""
    _, _, r = gf2_rref(M)
    return r


def gf2_nullspace(M):
    """Basis for ker(M) over GF(2). Returns array of row vectors."""
    M = np.array(M, dtype=np.int32).copy() % 2
    rows, cols = M.shape

    rref = M.copy()
    pivot_cols = []
    cur_row = 0
    for col in range(cols):
        pivot = None
        for r in range(cur_row, rows):
            if rref[r, col] == 1:
                pivot = r
                break
        if pivot is None:
            continue
        rref[[cur_row, pivot]] = rref[[pivot, cur_row]]
        for r in range(rows):
            if r != cur_row and rref[r, col] == 1:
                rref[r] = (rref[r] + rref[cur_row]) % 2
        pivot_cols.append(col)
        cur_row += 1

    free_cols = [c for c in range(cols) if c not in pivot_cols]
    if not free_cols:
        return np.zeros((0, cols), dtype=np.uint8)

    null_vecs = []
    for fc in free_cols:
        v = np.zeros(cols, dtype=np.uint8)
        v[fc] = 1
        for i, pc in enumerate(pivot_cols):
            v[pc] = rref[i, fc] % 2
        null_vecs.append(v)
    return np.array(null_vecs, dtype=np.uint8)


# ======================================================================
# Bivariate Bicycle Code Construction
# ======================================================================

def perm_matrix(l, m, a, b):
    """Permutation matrix for x^a * y^b in left-regular rep of Z_l x Z_m."""
    N = l * m
    mat = np.zeros((N, N), dtype=np.uint8)
    for i in range(l):
        for j in range(m):
            src = i * m + j
            dst = ((i + a) % l) * m + ((j + b) % m)
            mat[dst, src] = 1
    return mat


def group_element_matrix(l, m, terms):
    """Matrix for GF(2) group algebra element sum_t x^{a_t} y^{b_t}."""
    N = l * m
    mat = np.zeros((N, N), dtype=np.uint8)
    for a, b in terms:
        mat = (mat + perm_matrix(l, m, a, b)) % 2
    return mat


def build_bb_code(l, m, A_terms, B_terms):
    """Construct Hx, Hz for a bivariate bicycle code."""
    A = group_element_matrix(l, m, A_terms)
    B = group_element_matrix(l, m, B_terms)
    Hx = np.hstack([A, B]).astype(np.uint8)
    Hz = np.hstack([B.T, A.T]).astype(np.uint8)
    return Hx, Hz


# ======================================================================
# Code Distance Computation
# ======================================================================

def greedy_weight_reduce(v, stab_rows):
    """Greedily reduce Hamming weight of v by XOR-ing stabilizer rows."""
    v = v.copy().astype(np.uint8)
    improved = True
    while improved:
        improved = False
        cur_w = int(np.sum(v))
        if cur_w == 0:
            break
        candidates = v ^ stab_rows
        weights = np.sum(candidates, axis=1)
        best_idx = int(np.argmin(weights))
        if weights[best_idx] < cur_w:
            v = candidates[best_idx].copy()
            improved = True
    return v, int(np.sum(v))


def find_logical_reps(ker_basis, H_stab, k):
    """Find k independent logical representatives from ker_basis not in rowspace(H_stab)."""
    r_stab = gf2_rank(H_stab)
    logicals = []
    augmented = H_stab.astype(np.int32).copy()
    current_rank = r_stab

    for v in ker_basis:
        test = np.vstack([augmented, v.reshape(1, -1).astype(np.int32)])
        new_rank = gf2_rank(test)
        if new_rank > current_rank:
            logicals.append(v.copy())
            augmented = test
            current_rank = new_rank
        if len(logicals) >= k:
            break

    return np.array(logicals, dtype=np.uint8)


def compute_one_distance(H_check, H_stab, k, n_perturb_top=50, n_perturb_rounds=1000):
    """Compute min weight of v in ker(H_check) \\ rowspace(H_stab)."""
    n = H_check.shape[1]
    if k == 0:
        return n

    ker_basis = gf2_nullspace(H_check)
    if len(ker_basis) == 0:
        return n

    logicals = find_logical_reps(ker_basis, H_stab, k)
    if len(logicals) == 0:
        return n
    logicals = logicals[:k]

    stab_rows = H_stab.astype(np.uint8)
    min_weight = n

    # Phase 1: greedy reduction for all 2^k - 1 non-trivial combinations
    phase1_results = []
    for mask in range(1, 2**k):
        bits = np.array([(mask >> i) & 1 for i in range(k)], dtype=np.uint8)
        v = (bits @ logicals) % 2
        v_red, w = greedy_weight_reduce(v, stab_rows)
        phase1_results.append((w, v_red))
        if w < min_weight:
            min_weight = w

    print(f"    Phase 1: best weight = {min_weight} (over {2**k - 1} cosets)",
          file=sys.stderr)

    # Phase 2: random perturbation on top candidates
    phase1_results.sort(key=lambda x: x[0])
    top = phase1_results[:min(n_perturb_top, len(phase1_results))]

    rng = np.random.RandomState(42)
    n_stab = stab_rows.shape[0]

    for w0, v0 in top:
        for _ in range(n_perturb_rounds):
            sel = rng.randint(0, 2, size=n_stab).astype(np.uint8)
            perturbation = (sel @ stab_rows) % 2
            perturbed = v0 ^ perturbation
            v_red, w = greedy_weight_reduce(perturbed, stab_rows)
            if w < min_weight:
                min_weight = w

    print(f"    Phase 2: best weight = {min_weight}", file=sys.stderr)
    return min_weight


def compute_code_distance(Hx, Hz, k):
    """Compute CSS code distance d = min(d_x, d_z)."""
    print("  Computing d_x (X-distance)...", file=sys.stderr)
    dx = compute_one_distance(Hz, Hx, k)
    print(f"  d_x = {dx}", file=sys.stderr)

    print("  Computing d_z (Z-distance)...", file=sys.stderr)
    dz = compute_one_distance(Hx, Hz, k)
    print(f"  d_z = {dz}", file=sys.stderr)

    return min(dx, dz)


# ======================================================================
# Logical Operator
# ======================================================================

def find_logical_z_rep(Hx, Hz, k):
    """Find one logical Z representative (in ker(Hx) \\ rowspace(Hz))."""
    if k == 0:
        return np.zeros(Hx.shape[1], dtype=np.uint8)

    ker = gf2_nullspace(Hx)
    if len(ker) == 0:
        return np.zeros(Hx.shape[1], dtype=np.uint8)

    rz = gf2_rank(Hz)
    aug = Hz.astype(np.int32).copy()
    cur_rank = rz

    for v in ker:
        test = np.vstack([aug, v.reshape(1, -1).astype(np.int32)])
        nr = gf2_rank(test)
        if nr > cur_rank:
            return v

    return np.zeros(Hx.shape[1], dtype=np.uint8)


# ======================================================================
# Stim Circuit Construction
# ======================================================================

def build_z_memory_circuit(Hz, n, logical_z, p=0.001):
    """Build a Z-basis memory experiment circuit for a CSS code.

    Single round of Z-stabilizer syndrome extraction with phenomenological noise.
    """
    n_z = Hz.shape[0]
    data = list(range(n))
    z_anc = list(range(n, n + n_z))

    c = stim.Circuit()

    # Reset all qubits
    c.append("R", data + z_anc)
    c.append("TICK")

    # Data qubit noise (models idle/preparation errors)
    c.append("DEPOLARIZE1", data, p)
    c.append("TICK")

    # Z-syndrome extraction: CNOT from data to ancilla for each Z-check
    for i in range(n_z):
        support = sorted([j for j in range(n) if Hz[i, j] == 1])
        for j in support:
            c.append("CX", [j, z_anc[i]])
    c.append("TICK")

    # Measurement noise on ancillas
    c.append("X_ERROR", z_anc, p)
    c.append("M", z_anc)

    # Detectors: each Z-check syndrome expected 0 for |0⟩ initial state
    for i in range(n_z):
        c.append("DETECTOR", [stim.target_rec(-(n_z - i))])

    c.append("TICK")

    # Final data measurement
    c.append("M", data)

    # Logical Z observable
    obs_targets = [stim.target_rec(-(n - j)) for j in range(n) if logical_z[j] == 1]
    if obs_targets:
        c.append("OBSERVABLE_INCLUDE", obs_targets, 0)

    return c


# ======================================================================
# Main
# ======================================================================

def main():
    with open("/app/codes.json") as f:
        codes = json.load(f)

    os.makedirs("/app/circuits", exist_ok=True)
    os.makedirs("/app/dem", exist_ok=True)

    results = {}

    for spec in codes["codes"]:
        name = spec["name"]
        l, m = spec["l"], spec["m"]
        print(f"\n=== Processing {name} (l={l}, m={m}) ===", file=sys.stderr)

        # Build code
        Hx, Hz = build_bb_code(l, m, spec["A_terms"], spec["B_terms"])
        n = Hx.shape[1]

        # CSS verification
        css_product = (Hx.astype(np.int32) @ Hz.T.astype(np.int32)) % 2
        css_valid = bool(np.all(css_product == 0))
        print(f"  n = {n}, CSS valid = {css_valid}", file=sys.stderr)

        # Ranks and k
        hx_rank = gf2_rank(Hx)
        hz_rank = gf2_rank(Hz)
        k = n - hx_rank - hz_rank
        rank_symmetric = bool(hx_rank == hz_rank)
        print(f"  rank(Hx) = {hx_rank}, rank(Hz) = {hz_rank}, k = {k}",
              file=sys.stderr)

        # Check weight (uniform for BB codes)
        check_weight = int(np.sum(Hx[0]))

        # Distance
        d = compute_code_distance(Hx, Hz, k)
        print(f"  d = {d}", file=sys.stderr)

        encoding_rate = k / n

        # Find logical Z representative for observable
        logical_z = find_logical_z_rep(Hx, Hz, k)
        assert np.any(logical_z), f"Failed to find logical Z representative for {name}"

        # Build stim circuit
        circuit = build_z_memory_circuit(Hz, n, logical_z, p=0.001)
        circuit_path = f"/app/circuits/{name}.stim"
        with open(circuit_path, "w") as f:
            f.write(str(circuit))
        print(f"  Circuit: {circuit.num_qubits} qubits, "
              f"{circuit.num_detectors} detectors, "
              f"{circuit.num_observables} observables", file=sys.stderr)

        # Extract detector error model with graphlike decomposition
        dem = circuit.detector_error_model(
            decompose_errors=True,
            approximate_disjoint_errors=True,
        )
        dem_path = f"/app/dem/{name}.dem"
        with open(dem_path, "w") as f:
            f.write(str(dem))
        print(f"  DEM: {dem.num_detectors} detectors, "
              f"{dem.num_errors} error mechanisms", file=sys.stderr)

        # Construct pymatching decoder from DEM
        matching = pymatching.Matching.from_detector_error_model(dem)
        matching_nodes = int(matching.num_nodes)
        matching_edges = int(matching.num_edges)
        print(f"  Matching: {matching_nodes} nodes, {matching_edges} edges",
              file=sys.stderr)

        results[name] = {
            "n": int(n),
            "k": int(k),
            "d": int(d),
            "css_valid": css_valid,
            "hx_rank": int(hx_rank),
            "hz_rank": int(hz_rank),
            "rank_symmetric": rank_symmetric,
            "encoding_rate": float(encoding_rate),
            "check_weight": int(check_weight),
            "matching_nodes": matching_nodes,
            "matching_edges": matching_edges,
        }

    # Best encoding rate
    code_names = [name for name in results if isinstance(results[name], dict)]
    best = max(code_names, key=lambda x: results[x]["encoding_rate"])
    results["best_encoding_rate"] = best

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nBest encoding rate: {best}", file=sys.stderr)
    print("Results written to /app/results.json", file=sys.stderr)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
