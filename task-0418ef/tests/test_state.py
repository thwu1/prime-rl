
"""
Verification tests for the stiff ODE solver task.
Tests C library compilation, ctypes usage, gnuplot output,
coloring validity, Jacobian accuracy, solution correctness,
Jacobian reuse, step-size smoothness, and implementation constraints.
"""

import pytest
import numpy as np
import json
import os
import sys
import glob
import struct

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_coloring():
    with open("/app/results/coloring.json") as f:
        return json.load(f)


def _load_stats():
    with open("/app/results/stats.json") as f:
        return json.load(f)


def _load_step_sizes():
    dts = []
    with open("/app/results/step_sizes.csv") as f:
        for line in f:
            line = line.strip()
            if line:
                dts.append(float(line))
    return np.array(dts)


def _build_column_intersection_graph(pattern, n_cols):
    """Build adjacency from sparsity pattern for verification."""
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


# ---------------------------------------------------------------------------
# Tests: output files exist
# ---------------------------------------------------------------------------

def test_output_files_exist():
    """All required output files must be present."""
    for name in ["solution.npz", "coloring.json", "stats.json", "step_sizes.csv",
                  "heatmap.png"]:
        path = f"/app/results/{name}"
        assert os.path.exists(path), f"Missing output file: {path}"


# ---------------------------------------------------------------------------
# Tests: C library and tool interop
# ---------------------------------------------------------------------------

def test_c_library_compiled():
    """The C shared library must have been compiled from source."""
    so_path = "/app/rhs_native/librhs.so"
    assert os.path.exists(so_path), (
        f"Missing compiled C library: {so_path}. "
        "The Makefile in /app/rhs_native/ must be used to build it."
    )
    assert os.path.getsize(so_path) > 1000, (
        f"librhs.so is suspiciously small ({os.path.getsize(so_path)} bytes)"
    )


def test_solver_uses_ctypes():
    """The solver must use ctypes to call the compiled C library."""
    py_files = glob.glob("/app/**/*.py", recursive=True)
    solver_files = [f for f in py_files
                    if os.path.basename(f) != "problem.py"
                    and "__pycache__" not in f
                    and "/results/" not in f]

    found_ctypes = False
    found_librhs = False
    for fpath in solver_files:
        with open(fpath) as f:
            content = f.read()
        if "ctypes" in content:
            found_ctypes = True
        if "librhs" in content or "rhs_native" in content:
            found_librhs = True

    assert found_ctypes, (
        "No 'ctypes' usage found in solver code under /app/. "
        "The solver must load the C library via ctypes."
    )
    assert found_librhs, (
        "No reference to 'librhs' or 'rhs_native' found in solver code. "
        "The solver must call the compiled C library for RHS evaluations."
    )


def test_heatmap_valid_png():
    """The gnuplot-generated heatmap must be a valid PNG image."""
    heatmap_path = "/app/results/heatmap.png"
    assert os.path.exists(heatmap_path), "Missing heatmap.png"
    assert os.path.getsize(heatmap_path) > 1000, (
        f"heatmap.png is too small ({os.path.getsize(heatmap_path)} bytes) — "
        "likely not a real image"
    )
    with open(heatmap_path, "rb") as f:
        header = f.read(8)
    # PNG magic bytes: 137 80 78 71 13 10 26 10
    png_magic = b'\x89PNG\r\n\x1a\n'
    assert header == png_magic, (
        f"heatmap.png does not have valid PNG header (got {header!r})"
    )


# ---------------------------------------------------------------------------
# Tests: coloring
# ---------------------------------------------------------------------------

def test_coloring_valid():
    """The reported coloring must be a valid labeling: no two columns
    sharing a nonzero row in the sparsity pattern may have the same label."""
    data = _load_coloring()
    colors = data["colors"]
    n_colors = data["n_colors"]

    from problem import sparsity_pattern, N_TOTAL
    pattern = sparsity_pattern()
    n = N_TOTAL

    assert len(colors) == n, f"Expected {n} color entries, got {len(colors)}"
    assert all(isinstance(c, int) and c >= 0 for c in colors), "Labels must be non-negative ints"
    assert n_colors == max(colors) + 1, "n_colors must equal max(colors)+1"

    adj = _build_column_intersection_graph(pattern, n)

    for node in range(n):
        for nb in adj[node]:
            assert colors[node] != colors[nb], (
                f"Columns {node} and {nb} share a nonzero row but have the same "
                f"label {colors[node]}. The labeling is invalid."
            )


def test_coloring_efficient():
    """The column labeling should use a reasonable number of distinct labels.
    For the Brusselator with N=40 the minimum is 4; we allow up to 10."""
    data = _load_coloring()
    n_colors = data["n_colors"]
    assert n_colors <= 10, f"Labeling uses {n_colors} labels (expected <=10)"
    assert n_colors >= 3, f"Labeling uses only {n_colors} labels (suspiciously few)"


# ---------------------------------------------------------------------------
# Tests: compressed Jacobian correctness
# ---------------------------------------------------------------------------

def test_compressed_jacobian_accuracy():
    """Using the agent's column labeling, grouped perturbation must reproduce
    the dense finite-difference Jacobian at the initial condition."""
    data = _load_coloring()
    colors = data["colors"]

    from problem import rhs, initial_condition, sparsity_pattern, N_TOTAL
    y0 = initial_condition()
    n = N_TOTAL
    pattern = sparsity_pattern()

    eps = np.sqrt(np.finfo(float).eps)
    f0 = rhs(y0, 0.0)

    # Dense Jacobian via standard finite differences
    J_dense = np.zeros((n, n))
    for j in range(n):
        h = eps * max(1.0, abs(y0[j]))
        ej = np.zeros(n)
        ej[j] = h
        J_dense[:, j] = (rhs(y0 + ej, 0.0) - f0) / h

    # Compressed Jacobian using the agent's labeling
    col_to_rows = {}
    for r, c in pattern:
        col_to_rows.setdefault(c, []).append(r)

    n_colors = max(colors) + 1
    color_groups = [[] for _ in range(n_colors)]
    for j, clr in enumerate(colors):
        color_groups[clr].append(j)

    J_compressed = np.zeros((n, n))
    for group in color_groups:
        d = np.zeros(n)
        for j in group:
            d[j] = eps * max(1.0, abs(y0[j]))
        f_pert = rhs(y0 + d, 0.0)
        for j in group:
            h = d[j]
            for r in col_to_rows.get(j, []):
                J_compressed[r, j] = (f_pert[r] - f0[r]) / h

    # Compare on the sparsity-pattern positions
    max_err = 0.0
    for r, c in pattern:
        ref = J_dense[r, c]
        comp = J_compressed[r, c]
        err = abs(ref - comp) / (1.0 + abs(ref))
        if err > max_err:
            max_err = err
    assert max_err < 1e-4, (
        f"Compressed Jacobian max relative error = {max_err:.2e} (threshold 1e-4)"
    )


# ---------------------------------------------------------------------------
# Tests: solution accuracy
# ---------------------------------------------------------------------------

def test_solution_accuracy():
    """The solver's final state must match a scipy Radau reference within 10%
    relative error."""
    sol = np.load("/app/results/solution.npz")
    t_sol = sol["t"]
    y_sol = sol["y"]

    from problem import rhs, initial_condition, N_TOTAL, T_START, T_END

    # Basic shape checks
    assert t_sol.ndim == 1
    assert y_sol.ndim == 2
    assert y_sol.shape[1] == N_TOTAL, f"Expected {N_TOTAL} columns, got {y_sol.shape[1]}"
    assert len(t_sol) == len(y_sol)
    assert abs(t_sol[0] - T_START) < 1e-10, "First time must be T_START"
    assert abs(t_sol[-1] - T_END) < 1e-6, f"Last time {t_sol[-1]} != T_END={T_END}"

    # Compute reference solution
    from scipy.integrate import solve_ivp
    y0 = initial_condition()
    ref = solve_ivp(
        lambda t, y: rhs(y, t),
        [T_START, T_END],
        y0,
        method="Radau",
        rtol=1e-10,
        atol=1e-12,
    )
    assert ref.success, f"Reference solver failed: {ref.message}"
    y_ref = ref.y[:, -1]
    y_final = y_sol[-1]

    rel_err = np.max(np.abs(y_final - y_ref) / (1.0 + np.abs(y_ref)))
    assert rel_err < 0.1, f"Solution relative error {rel_err:.4f} exceeds 10%"


def test_solution_bounded():
    """Solution values should be finite, mostly positive, and bounded."""
    sol = np.load("/app/results/solution.npz")
    y_sol = sol["y"]

    assert np.all(np.isfinite(y_sol)), "Solution contains non-finite values"
    assert np.all(y_sol > -1.0), "Solution has values below -1 (unphysical)"
    assert np.all(y_sol < 100.0), "Solution values exceed 100 (likely divergence)"


# ---------------------------------------------------------------------------
# Tests: solver behaviour
# ---------------------------------------------------------------------------

def test_jacobian_reuse():
    """Matrix factorizations should be reused, resulting in fewer factorizations
    than the number of accepted time steps."""
    stats = _load_stats()
    steps = stats["steps_accepted"]
    lu_facts = stats["lu_factorizations"]
    jac_evals = stats["jac_evals"]

    assert steps > 0, "No accepted steps"
    assert lu_facts > 0, "No LU factorizations reported"
    assert jac_evals > 0, "No Jacobian evaluations reported"

    assert lu_facts < steps, (
        f"No factorization reuse detected: {lu_facts} LU factorizations "
        f"for {steps} accepted steps"
    )
    assert jac_evals <= lu_facts, (
        f"More Jacobian evaluations ({jac_evals}) than "
        f"LU factorizations ({lu_facts})"
    )


def test_step_sizes_smooth():
    """Adaptive step sizing should produce reasonably smooth trajectories.
    After the initial transient, consecutive step-size ratios should stay
    within [0.1, 10]."""
    dts = _load_step_sizes()
    assert len(dts) >= 10, f"Only {len(dts)} steps — too few for smoothness test"
    assert np.all(dts > 0), "Step sizes must be positive"

    # Skip first 20% as transient
    skip = max(5, len(dts) // 5)
    if len(dts) > skip + 2:
        steady = dts[skip:]
        ratios = steady[1:] / steady[:-1]
        assert np.all(ratios < 10.0), (
            f"Step size jumped by factor {np.max(ratios):.1f} "
            f"(after transient) — adaptation not smoothing"
        )
        assert np.all(ratios > 0.1), (
            f"Step size dropped by factor {np.min(ratios):.3f} "
            f"(after transient) — adaptation not smoothing"
        )


def test_no_scipy_integrate():
    """The solver implementation must not use scipy.integrate."""
    py_files = glob.glob("/app/**/*.py", recursive=True)
    for fpath in py_files:
        basename = os.path.basename(fpath)
        if basename == "problem.py":
            continue
        if "/results/" in fpath or "__pycache__" in fpath:
            continue
        with open(fpath) as f:
            content = f.read()
        assert "scipy.integrate" not in content, (
            f"Found 'scipy.integrate' in {fpath} — ODE solver libraries are prohibited"
        )
        assert "from scipy import integrate" not in content, (
            f"Found scipy.integrate import in {fpath}"
        )
