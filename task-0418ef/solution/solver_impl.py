
"""
Complete stiff ODE solver for the 1D Brusselator system.
Uses the compiled C library via ctypes for RHS evaluations
and gnuplot for visualization.
"""

import ctypes
import numpy as np
from numpy.ctypeslib import ndpointer
from scipy.linalg import lu_factor, lu_solve
import json
import os
import subprocess
import sys

sys.path.insert(0, "/app")
from problem import sparsity_pattern, N_TOTAL, T_START, T_END


# ---------------------------------------------------------------------------
# Load C shared library via ctypes
# ---------------------------------------------------------------------------

def load_c_library():
    """Load the compiled Brusselator RHS library."""
    lib_path = "/app/rhs_native/librhs.so"
    lib = ctypes.CDLL(lib_path)

    # void brusselator_rhs(const double *y, double t, double *dydt)
    lib.brusselator_rhs.restype = None
    lib.brusselator_rhs.argtypes = [
        ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"),
        ctypes.c_double,
        ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"),
    ]

    lib.get_n_total.restype = ctypes.c_int
    lib.get_n_total.argtypes = []
    lib.get_n_grid.restype = ctypes.c_int
    lib.get_n_grid.argtypes = []

    return lib


def make_rhs_func(lib, n):
    """Create a Python-callable RHS wrapper around the C library."""
    def rhs_c(y, t):
        dydt = np.empty(n, dtype=np.float64)
        lib.brusselator_rhs(np.ascontiguousarray(y, dtype=np.float64),
                            float(t), dydt)
        return dydt
    return rhs_c


# ---------------------------------------------------------------------------
# Graph coloring
# ---------------------------------------------------------------------------

def build_column_intersection_graph(pattern, n_cols):
    """Build adjacency list for the column intersection graph."""
    row_to_cols = {}
    for r, c in pattern:
        row_to_cols.setdefault(r, []).append(c)

    adj = [set() for _ in range(n_cols)]
    for cols in row_to_cols.values():
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                adj[cols[i]].add(cols[j])
                adj[cols[j]].add(cols[i])
    return adj


def greedy_distance1_coloring(adj, n_cols):
    """Greedy distance-1 coloring with largest-degree-first ordering."""
    order = sorted(range(n_cols), key=lambda v: len(adj[v]), reverse=True)
    colors = [-1] * n_cols
    for node in order:
        used = set()
        for nb in adj[node]:
            if colors[nb] >= 0:
                used.add(colors[nb])
        c = 0
        while c in used:
            c += 1
        colors[node] = c
    return colors


# ---------------------------------------------------------------------------
# Compressed Jacobian computation
# ---------------------------------------------------------------------------

def compressed_jacobian(f, y, t, col_to_rows, color_groups, n):
    """Compute df/dy using compressed finite differences."""
    eps_base = np.sqrt(np.finfo(float).eps)
    f0 = f(y, t)
    J = np.zeros((n, n))
    n_f_evals = 1

    for group in color_groups:
        d = np.zeros(n)
        for col in group:
            d[col] = eps_base * max(1.0, abs(y[col]))

        f_pert = f(y + d, t)
        n_f_evals += 1

        for col in group:
            h = d[col]
            for row in col_to_rows.get(col, []):
                J[row, col] = (f_pert[row] - f0[row]) / h

    return J, f0, n_f_evals


# ---------------------------------------------------------------------------
# Gnuplot heatmap generation
# ---------------------------------------------------------------------------

def generate_heatmap(t_hist, y_hist):
    """Write u-species data and invoke gnuplot to produce heatmap.png."""
    t_arr = np.array(t_hist)
    y_arr = np.array(y_hist)
    n_grid = y_arr.shape[1] // 2
    u_data = y_arr[:, :n_grid]  # u-species only

    # Write matrix data file for gnuplot
    data_path = "/app/results/heatmap_data.dat"
    with open(data_path, "w") as fp:
        for row_idx in range(u_data.shape[0]):
            vals = " ".join(f"{v:.6e}" for v in u_data[row_idx])
            fp.write(vals + "\n")

    # Write gnuplot script
    script_path = "/app/results/heatmap.gnp"
    with open(script_path, "w") as fp:
        fp.write("set terminal pngcairo size 800,600 enhanced\n")
        fp.write("set output '/app/results/heatmap.png'\n")
        fp.write("set title 'Brusselator u-species (space-time)'\n")
        fp.write("set xlabel 'Grid index'\n")
        fp.write("set ylabel 'Time step index'\n")
        fp.write("set pm3d map\n")
        fp.write("set palette defined (0 'blue', 0.5 'white', 1 'red')\n")
        fp.write(f"splot '{data_path}' matrix with image notitle\n")

    # Invoke gnuplot
    subprocess.run(["gnuplot", script_path], check=True)


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve():
    # Load C library
    lib = load_c_library()
    n = lib.get_n_total()
    assert n == N_TOTAL

    rhs = make_rhs_func(lib, n)

    # Initial condition (from Python problem module for consistency)
    from problem import initial_condition
    y0 = initial_condition()

    pattern = sparsity_pattern()

    # Pre-compute column -> row mapping
    col_to_rows = {}
    for r, c in pattern:
        col_to_rows.setdefault(c, []).append(r)

    # --- Graph coloring ---
    adj = build_column_intersection_graph(pattern, n)
    colors = greedy_distance1_coloring(adj, n)
    n_colors = max(colors) + 1

    color_groups = [[] for _ in range(n_colors)]
    for col, clr in enumerate(colors):
        color_groups[clr].append(col)

    # --- Solver parameters ---
    rtol = 1e-6
    atol = 1e-9
    dt = 1e-3
    max_newton = 10
    newton_tol = 1e-10
    max_jac_age = 5
    safety = 0.9
    min_factor = 0.2
    max_factor = 5.0
    p = 1  # order of implicit Euler

    # PI controller gains (Gustafsson)
    k_I = 0.7 / p
    k_P = 0.4 / p

    # --- State ---
    t = T_START
    y = y0.copy()

    J_df = None
    lu_piv = None
    jac_age = max_jac_age + 1
    last_factored_dt = -1.0

    q_prev = 1.0
    first_accepted = True

    stats = dict(f_evals=0, jac_evals=0, lu_factorizations=0,
                 steps_accepted=0, steps_rejected=0)

    t_hist = [t]
    y_hist = [y.copy()]
    dt_hist = []

    f_n = rhs(y, t)
    stats["f_evals"] += 1

    # --- Time-stepping loop ---
    while t < T_END - 1e-14:
        dt = min(dt, T_END - t)
        if dt < 1e-15:
            break

        need_jac = J_df is None or jac_age >= max_jac_age
        if need_jac:
            J_df, _, fe = compressed_jacobian(rhs, y, t, col_to_rows,
                                              color_groups, n)
            stats["f_evals"] += fe
            stats["jac_evals"] += 1
            jac_age = 0

        dt_ratio = abs(dt - last_factored_dt) / max(abs(dt),
                                                     abs(last_factored_dt),
                                                     1e-15)
        need_factor = need_jac or dt_ratio > 0.2
        if need_factor:
            W = np.eye(n) - dt * J_df
            lu_piv = lu_factor(W)
            stats["lu_factorizations"] += 1
            last_factored_dt = dt

        # Newton iteration for implicit Euler
        x = y + dt * f_n
        converged = False

        for _ in range(max_newton):
            fx = rhs(x, t + dt)
            stats["f_evals"] += 1
            g = x - y - dt * fx
            a = lu_solve(lu_piv, g)
            x -= a
            if np.linalg.norm(a) < newton_tol * (1.0 + np.linalg.norm(x)):
                converged = True
                break

        if not converged:
            dt *= 0.5
            stats["steps_rejected"] += 1
            J_df = None
            jac_age = max_jac_age + 1
            continue

        f_np1 = rhs(x, t + dt)
        stats["f_evals"] += 1

        # Error estimation (Milne device)
        err_vec = (dt / 2.0) * (f_np1 - f_n)
        sc = atol + rtol * np.maximum(np.abs(y), np.abs(x))
        q = np.sqrt(np.mean((err_vec / sc) ** 2))
        q = max(q, 1e-10)

        if q <= 1.0 or dt < 1e-14:
            t += dt
            y = x.copy()
            f_n = f_np1
            stats["steps_accepted"] += 1
            jac_age += 1

            t_hist.append(t)
            y_hist.append(y.copy())
            dt_hist.append(dt)

            if first_accepted:
                factor = safety * q ** (-1.0 / p)
                first_accepted = False
            else:
                factor = safety * q ** (-k_I) * q_prev ** k_P

            factor = np.clip(factor, min_factor, max_factor)
            q_prev = q
            dt *= factor
        else:
            factor = safety * q ** (-1.0 / p)
            factor = np.clip(factor, min_factor, 1.0)
            dt *= factor
            stats["steps_rejected"] += 1
            J_df = None
            jac_age = max_jac_age + 1

    return dict(
        t=np.array(t_hist),
        y=np.array(y_hist),
        dts=np.array(dt_hist),
        colors=colors,
        n_colors=n_colors,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    os.makedirs("/app/results", exist_ok=True)

    # Compile C library
    print("Compiling C RHS library...")
    subprocess.run(["make", "-C", "/app/rhs_native"], check=True)

    result = solve()

    # solution.npz
    np.savez("/app/results/solution.npz", t=result["t"], y=result["y"])

    # coloring.json
    with open("/app/results/coloring.json", "w") as fp:
        json.dump({"colors": result["colors"],
                    "n_colors": result["n_colors"]}, fp, indent=2)

    # stats.json
    with open("/app/results/stats.json", "w") as fp:
        json.dump(result["stats"], fp, indent=2)

    # step_sizes.csv
    with open("/app/results/step_sizes.csv", "w") as fp:
        for dt_val in result["dts"]:
            fp.write(f"{dt_val:.15e}\n")

    # Generate gnuplot heatmap
    print("Generating gnuplot heatmap...")
    generate_heatmap(result["t"].tolist(), [row.tolist() for row in result["y"]])

    print(f"Solver complete:")
    print(f"  Steps accepted: {result['stats']['steps_accepted']}")
    print(f"  Steps rejected: {result['stats']['steps_rejected']}")
    print(f"  Colors: {result['n_colors']}")
    print(f"  Jacobian evals: {result['stats']['jac_evals']}")
    print(f"  LU factorizations: {result['stats']['lu_factorizations']}")
    print(f"  Function evaluations: {result['stats']['f_evals']}")
    print(f"  Final time: {result['t'][-1]:.6f}")
    print(f"  Solution norm at T_END: {np.linalg.norm(result['y'][-1]):.6f}")


if __name__ == "__main__":
    main()
