#!/usr/bin/env python3
"""
Classical Algebraic Multigrid (AMG) preconditioned Conjugate Gradient solver
for 2D heterogeneous diffusion: -div(K(x,y) grad(u)) = f on [0,1]^2.
"""
import json
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve, spsolve_triangular


def load_problem(path="/app/problem.json"):
    with open(path) as f:
        return json.load(f)


def eval_K(x, y, inclusions, background):
    """Evaluate piecewise-constant diffusion coefficient at (x, y)."""
    for inc in inclusions:
        xr, yr = inc["x_range"], inc["y_range"]
        if xr[0] <= x <= xr[1] and yr[0] <= y <= yr[1]:
            return inc["value"]
    return background


def assemble_system(config):
    """Assemble sparse matrix and RHS for the 5-point stencil discretization."""
    n = config["grid_size"]
    N = n * n
    h = 1.0 / (n + 1)
    h2 = h * h
    inclusions = config["coefficients"]["inclusions"]
    background = config["coefficients"]["background"]

    rows, cols, vals = [], [], []
    b = np.full(N, config["rhs_value"])

    neighbors = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    for j in range(n):
        for i in range(n):
            idx = j * n + i
            x = (i + 1) * h
            y = (j + 1) * h

            diag = 0.0
            for di, dj in neighbors:
                face_x = x + di * h * 0.5
                face_y = y + dj * h * 0.5
                k_face = eval_K(face_x, face_y, inclusions, background)
                coeff = k_face / h2

                ni, nj = i + di, j + dj
                if 0 <= ni < n and 0 <= nj < n:
                    neighbor_idx = nj * n + ni
                    rows.append(idx)
                    cols.append(neighbor_idx)
                    vals.append(-coeff)

                diag += coeff

            rows.append(idx)
            cols.append(idx)
            vals.append(diag)

    A = sparse.csr_matrix((vals, (rows, cols)), shape=(N, N))
    return A, b


# ============================================================
# AMG Setup: Strength, Coarsening, Interpolation, RAP
# ============================================================

def strength_of_connection(A, theta=0.25):
    """Classical strength-of-connection matrix.

    S[i,j] = 1 iff |a_ij| >= theta * max_{k != i} |a_ik|
    (i.e., j strongly influences i).
    """
    n = A.shape[0]
    rows_s, cols_s = [], []

    for i in range(n):
        start, end = A.indptr[i], A.indptr[i + 1]

        max_abs = 0.0
        for jj in range(start, end):
            if A.indices[jj] != i:
                aij = abs(A.data[jj])
                if aij > max_abs:
                    max_abs = aij

        threshold = theta * max_abs

        for jj in range(start, end):
            j = A.indices[jj]
            if j != i and abs(A.data[jj]) >= threshold:
                rows_s.append(i)
                cols_s.append(j)

    data = np.ones(len(rows_s), dtype=np.float64)
    S = sparse.csr_matrix((data, (rows_s, cols_s)), shape=(n, n))
    return S


def classical_cf_splitting(S):
    """Classical Ruge-Stuben C/F splitting (first pass).

    Returns array: 1 = C-point, 0 = F-point.
    """
    n = S.shape[0]
    ST = S.T.tocsr()  # ST[j,i] = 1 means j influences i, i.e., i depends on j

    # Lambda = number of undecided points that depend on each node
    lam = np.array([ST.indptr[i + 1] - ST.indptr[i] for i in range(n)],
                   dtype=np.int64)

    cf = np.full(n, -1, dtype=np.int32)  # -1 = undecided
    undecided = set(range(n))

    while undecided:
        # Select undecided point with maximum lambda
        best = max(undecided, key=lambda i: lam[i])

        # Make it a C-point
        cf[best] = 1
        undecided.discard(best)

        # All undecided points that depend on best become F-points
        # (these are the points that best influences: row best of ST)
        new_f = []
        for jj in range(ST.indptr[best], ST.indptr[best + 1]):
            dep = ST.indices[jj]
            if cf[dep] == -1:
                cf[dep] = 0
                undecided.discard(dep)
                new_f.append(dep)

        # Update lambda: each new F-point's influencees get lambda + 1
        for f_pt in new_f:
            for kk in range(ST.indptr[f_pt], ST.indptr[f_pt + 1]):
                k = ST.indices[kk]
                if cf[k] == -1:
                    lam[k] += 1

        # Points that best depends on (S row best) get lambda - 1
        for jj in range(S.indptr[best], S.indptr[best + 1]):
            j = S.indices[jj]
            if cf[j] == -1:
                lam[j] = max(0, lam[j] - 1)

    # Mark remaining undecided as C-points
    cf[cf == -1] = 1

    # Safety: ensure every F-point has at least one strong C-neighbor
    for i in range(n):
        if cf[i] == 0:
            has_c = False
            for jj in range(S.indptr[i], S.indptr[i + 1]):
                if cf[S.indices[jj]] == 1:
                    has_c = True
                    break
            if not has_c:
                cf[i] = 1

    return cf


def build_interpolation(A, S, cf):
    """Direct interpolation operator P.

    C-points: identity (injection).
    F-points: weighted average from strongly-connected C-neighbors.
    """
    n = A.shape[0]
    c_points = np.where(cf == 1)[0]
    nc = len(c_points)

    coarse_map = np.full(n, -1, dtype=np.int64)
    for ci, idx in enumerate(c_points):
        coarse_map[idx] = ci

    rows_p, cols_p, vals_p = [], [], []

    # Precompute strong sets
    strong_sets = []
    for i in range(n):
        s_start, s_end = S.indptr[i], S.indptr[i + 1]
        strong_sets.append(set(S.indices[s_start:s_end]))

    for i in range(n):
        if cf[i] == 1:
            rows_p.append(i)
            cols_p.append(coarse_map[i])
            vals_p.append(1.0)
        else:
            start, end = A.indptr[i], A.indptr[i + 1]
            strong = strong_sets[i]

            # Diagonal
            a_ii = 0.0
            for jj in range(start, end):
                if A.indices[jj] == i:
                    a_ii = A.data[jj]
                    break

            # Denominator = a_ii + weak off-diag + strong F-neighbor entries
            denom = a_ii
            for jj in range(start, end):
                j = A.indices[jj]
                if j != i:
                    if j not in strong:
                        # Weak connection: lump into diagonal
                        denom += A.data[jj]
                    elif cf[j] == 0:
                        # Strong F-neighbor: lump into diagonal
                        denom += A.data[jj]

            if abs(denom) < 1e-30:
                denom = a_ii if abs(a_ii) > 1e-30 else 1.0

            # Weights from strong C-neighbors
            has_weight = False
            for jj in range(start, end):
                j = A.indices[jj]
                if j != i and j in strong and cf[j] == 1:
                    w = -A.data[jj] / denom
                    rows_p.append(i)
                    cols_p.append(coarse_map[j])
                    vals_p.append(w)
                    has_weight = True

            if not has_weight:
                # Safety: should not happen with correct CF splitting.
                # Fall back to simple diagonal scaling.
                rows_p.append(i)
                cols_p.append(0)
                vals_p.append(0.0)

    P = sparse.csr_matrix((vals_p, (rows_p, cols_p)), shape=(n, nc))
    return P


def amg_setup(A, theta=0.25, max_levels=25, coarsest_size=50):
    """Build AMG hierarchy."""
    levels = [{"A": A.tocsr(), "n": A.shape[0]}]

    current_A = A.tocsr()
    for lev in range(max_levels - 1):
        n_current = current_A.shape[0]
        if n_current <= coarsest_size:
            break

        S = strength_of_connection(current_A, theta)
        cf = classical_cf_splitting(S)

        nc = int(np.sum(cf == 1))
        if nc == 0 or nc == n_current:
            break

        P = build_interpolation(current_A, S, cf)
        R = P.T.tocsr()

        # Galerkin coarse grid operator
        Ac = (R @ current_A @ P).tocsr()

        levels[-1]["P"] = P
        levels[-1]["R"] = R

        levels.append({"A": Ac, "n": nc})
        current_A = Ac

        print(f"  Level {lev + 1}: {nc} unknowns, {Ac.nnz} nnz")

    return levels


# ============================================================
# Smoother and V-Cycle
# ============================================================

def symmetric_gauss_seidel(A, x, b):
    """One step of symmetric Gauss-Seidel via sparse triangular solves."""
    U_strict = sparse.triu(A, 1, format='csr')
    DL = sparse.tril(A, format='csr')

    L_strict = sparse.tril(A, -1, format='csr')
    DU = sparse.triu(A, format='csr')

    # Forward sweep: (D + L) x = b - U x
    rhs = b - U_strict @ x
    x = spsolve_triangular(DL, rhs, lower=True)

    # Backward sweep: (D + U) x = b - L x
    rhs = b - L_strict @ x
    x = spsolve_triangular(DU, rhs, lower=False)

    return x


def v_cycle(levels, level, b, x):
    """Apply one V(1,1) cycle."""
    A = levels[level]["A"]

    if level == len(levels) - 1:
        # Coarsest level: direct solve
        x[:] = spsolve(A.tocsc(), b)
        return x

    # Pre-smoothing
    x = symmetric_gauss_seidel(A, x, b)

    # Residual
    r = b - A @ x

    # Restrict
    R = levels[level]["R"]
    r_c = R @ r

    # Recurse on coarser level
    e_c = np.zeros(levels[level + 1]["n"])
    e_c = v_cycle(levels, level + 1, r_c, e_c)

    # Prolongate correction
    P = levels[level]["P"]
    x = x + P @ e_c

    # Post-smoothing
    x = symmetric_gauss_seidel(A, x, b)

    return x


# ============================================================
# PCG Solver
# ============================================================

def pcg_solve(A, b, levels, tol=1e-10, max_iter=200):
    """Preconditioned Conjugate Gradient with AMG V-cycle preconditioner."""
    n = A.shape[0]
    x = np.zeros(n)
    r = b.copy()

    # Apply preconditioner: z = M^{-1} r
    z = np.zeros(n)
    z = v_cycle(levels, 0, r.copy(), z)

    p = z.copy()
    rz = np.dot(r, z)
    r0_norm = np.linalg.norm(r)

    residual_norms = [r0_norm]

    iterations = 0
    for k in range(max_iter):
        Ap = A @ p
        pAp = np.dot(p, Ap)
        if abs(pAp) < 1e-30:
            break
        alpha = rz / pAp

        x = x + alpha * p
        r = r - alpha * Ap

        r_norm = np.linalg.norm(r)
        residual_norms.append(r_norm)

        iterations = k + 1
        if r_norm / r0_norm < tol:
            print(f"  PCG converged at iteration {iterations}: "
                  f"||r||/||r0|| = {r_norm / r0_norm:.2e}")
            break

        # Apply preconditioner
        z = np.zeros(n)
        z = v_cycle(levels, 0, r.copy(), z)

        rz_new = np.dot(r, z)
        if abs(rz) < 1e-30:
            break
        beta = rz_new / rz
        p = z + beta * p
        rz = rz_new

    # Convergence factor: average over all iterations
    if len(residual_norms) > 1:
        conv_factor = (residual_norms[-1] / residual_norms[0]) ** (
            1.0 / (len(residual_norms) - 1))
    else:
        conv_factor = 0.0

    return x, iterations, conv_factor, residual_norms


# ============================================================
# Main
# ============================================================

def main():
    config = load_problem("/app/problem.json")

    print("Assembling matrix...")
    A, b = assemble_system(config)
    N = A.shape[0]
    print(f"  Matrix size: {N} x {N}, nnz: {A.nnz}")

    print("Setting up AMG hierarchy...")
    amg_config = config["amg"]
    levels = amg_setup(
        A,
        theta=amg_config["strength_threshold"],
        max_levels=amg_config["max_levels"],
        coarsest_size=amg_config.get("coarsest_size", 50),
    )

    n_levels = len(levels)
    total_grid = sum(lev["n"] for lev in levels)
    grid_complexity = total_grid / levels[0]["n"]
    total_nnz = sum(lev["A"].nnz for lev in levels)
    op_complexity = total_nnz / levels[0]["A"].nnz

    print(f"  Levels: {n_levels}")
    print(f"  Grid complexity: {grid_complexity:.4f}")
    print(f"  Operator complexity: {op_complexity:.4f}")

    print("Solving with PCG...")
    solver_config = config["solver"]
    x, iterations, conv_factor, residual_norms = pcg_solve(
        A, b, levels,
        tol=solver_config["tolerance"],
        max_iter=solver_config["max_iterations"],
    )
    print(f"  Iterations: {iterations}")
    print(f"  Convergence factor: {conv_factor:.6f}")
    print(f"  Final residual: {residual_norms[-1]:.2e}")

    # Extract probe values
    n = config["grid_size"]
    probe_values = {}
    for pt in config["output"]["probe_points_ij"]:
        i, j = pt
        idx = j * n + i
        key = f"{i}_{j}"
        probe_values[key] = float(x[idx])

    sol_norm = float(np.linalg.norm(x))
    print(f"  Solution norm: {sol_norm:.6e}")

    # Write results
    results = {
        "n_unknowns": int(N),
        "n_levels": int(n_levels),
        "grid_complexity": float(grid_complexity),
        "operator_complexity": float(op_complexity),
        "pcg_iterations": int(iterations),
        "convergence_factor": float(conv_factor),
        "solution_norm": sol_norm,
        "probe_values": probe_values,
    }

    output_path = config["output"]["file"]
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
