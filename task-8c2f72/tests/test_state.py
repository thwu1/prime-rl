
import json
import math
import subprocess
import os
import pytest


@pytest.fixture(scope="module")
def build_and_run():
    """Compile the parallel solver and run it with 4 MPI processes."""
    src = "/app/solver_parallel.c"
    assert os.path.exists(src), f"Source file {src} not found"

    result = subprocess.run(
        ["mpicc", "-O2", "-Wall", "-o", "/app/solver_parallel_verify",
         src, "-lm"],
        capture_output=True, text=True, cwd="/app"
    )
    assert result.returncode == 0, \
        f"Compilation failed:\n{result.stderr}"

    result = subprocess.run(
        ["mpirun", "--allow-run-as-root", "--oversubscribe",
         "--mca", "osc", "pt2pt",
         "-n", "4", "/app/solver_parallel_verify"],
        capture_output=True, text=True, cwd="/app", timeout=180
    )
    assert result.returncode == 0, \
        f"Execution failed (exit {result.returncode}):\n" \
        f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert os.path.exists("/app/results.json"), \
        "results.json not produced by the program"
    with open("/app/results.json") as f:
        return json.load(f)


def test_source_uses_rma():
    """Verify the solution uses MPI one-sided communication primitives."""
    src = "/app/solver_parallel.c"
    assert os.path.exists(src), f"Source file {src} not found"
    with open(src) as f:
        code = f.read()
    assert "MPI_Win_create" in code or "MPI_Win_allocate" in code, \
        "Must create an MPI RMA window (MPI_Win_create or MPI_Win_allocate)"
    assert "MPI_Get" in code or "MPI_Put" in code, \
        "Must use one-sided data movement (MPI_Get or MPI_Put)"
    assert "MPI_Win_fence" in code or "MPI_Win_lock" in code, \
        "Must use RMA synchronization (MPI_Win_fence or MPI_Win_lock)"


def test_source_uses_cartesian_topology():
    """Verify the solution uses 2D Cartesian process topology."""
    src = "/app/solver_parallel.c"
    with open(src) as f:
        code = f.read()
    assert "MPI_Cart_create" in code, \
        "Must use MPI_Cart_create for 2D Cartesian topology"
    assert "MPI_Cart_shift" in code, \
        "Must use MPI_Cart_shift to determine neighbor ranks"


def test_method_field(build_and_run):
    """Verify the output declares the rma_fence communication method."""
    assert "method" in build_and_run, \
        "results.json must include a 'method' field"
    assert build_and_run["method"] == "rma_fence", \
        f"Method must be 'rma_fence', got '{build_and_run['method']}'"


def test_grid_size(build_and_run):
    """Verify the grid size is 32."""
    assert build_and_run["grid_size"] == 32, \
        f"Grid size should be 32, got {build_and_run['grid_size']}"


def test_convergence(build_and_run):
    """Verify the solver converged within iteration and residual limits."""
    data = build_and_run
    assert data["residual"] < 1e-5, \
        f"Residual {data['residual']:.2e} exceeds threshold 1e-5"
    assert data["iterations"] > 0, \
        "Must complete at least 1 iteration"
    assert data["iterations"] <= 10000, \
        f"Exceeded max iterations: {data['iterations']}"


def test_solution_accuracy(build_and_run):
    """Verify computed solution matches analytical solution at query points."""
    data = build_and_run
    N = data["grid_size"]
    h = 1.0 / (N + 1)
    pi = math.pi

    points = data["points"]
    assert len(points) == 5, \
        f"Expected 5 query points, got {len(points)}"

    expected_coords = [(8, 8), (16, 16), (24, 24), (8, 24), (24, 8)]
    for pt, (ei, ej) in zip(points, expected_coords):
        assert pt["i"] == ei and pt["j"] == ej, \
            f"Expected point ({ei},{ej}), got ({pt['i']},{pt['j']})"

        computed = pt["computed"]
        exact = math.sin(pi * pt["i"] * h) * math.sin(pi * pt["j"] * h)
        error = abs(computed - exact)
        assert error < 3e-3, \
            f"Point ({pt['i']},{pt['j']}): |computed - exact| = {error:.6e} >= 3e-3 " \
            f"(computed={computed:.10f}, exact={exact:.10f})"


def test_point_symmetry(build_and_run):
    """Verify that symmetric query points (8,24) and (24,8) have equal values."""
    points = build_and_run["points"]

    pt_8_24 = next(p for p in points if p["i"] == 8 and p["j"] == 24)
    pt_24_8 = next(p for p in points if p["i"] == 24 and p["j"] == 8)

    diff = abs(pt_8_24["computed"] - pt_24_8["computed"])
    assert diff < 1e-8, \
        f"Symmetric points (8,24) and (24,8) differ by {diff:.2e}"


def test_query_exact_values(build_and_run):
    """Verify the 'exact' field matches the analytical formula."""
    data = build_and_run
    N = data["grid_size"]
    h = 1.0 / (N + 1)
    pi = math.pi

    for pt in data["points"]:
        reported = pt["exact"]
        expected = math.sin(pi * pt["i"] * h) * math.sin(pi * pt["j"] * h)
        diff = abs(reported - expected)
        assert diff < 1e-12, \
            f"Point ({pt['i']},{pt['j']}): 'exact' = {reported} " \
            f"does not match sin(pi*i*h)*sin(pi*j*h) = {expected}"
