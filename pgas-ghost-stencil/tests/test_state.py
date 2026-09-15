"""
Tests for the PGAS distributed array ghost-cell stencil task.

Verifies that the agent's pgas_array.c implementation:
  1. Exists and uses MPI RMA (MPI_Win)
  2. Compiles and links with the provided main.c / Makefile
  3. Runs correctly with mpirun -n 4
  4. Produces a Jacobi solver that converges
  5. Yields solution values matching the analytical Laplace solution

"""

import math
import os
import subprocess
import pytest

# --------------- constants ------------------------------------------------

N = 34
H = 1.0 / (N - 1)

VPOINTS = [
    (8,  8), (8, 17), (8, 25),
    (17,  8), (17, 17), (17, 25),
    (25,  8), (25, 17), (25, 25),
]


def _analytical(gi, gj):
    """Exact solution: u(x,y) = 100*sin(pi*x)*sinh(pi*y)/sinh(pi)."""
    x = gj * H
    y = gi * H
    return (100.0 * math.sin(math.pi * x)
            * math.sinh(math.pi * y) / math.sinh(math.pi))


# --------------- session fixture: build & run once ------------------------

@pytest.fixture(scope="session")
def program_output():
    """Build the program, run it with 4 MPI ranks, return output lines."""
    # clean build
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True, timeout=30)

    r = subprocess.run(["make", "-C", "/app"],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, (
        "Compilation failed:\n" + r.stderr.decode()
    )

    # remove stale output
    try:
        os.remove("/app/output.txt")
    except FileNotFoundError:
        pass

    r = subprocess.run(
        ["mpirun", "--allow-run-as-root", "-n", "4", "/app/laplace_solver"],
        capture_output=True, timeout=180,
    )
    assert r.returncode == 0, (
        f"Execution failed (rc={r.returncode}):\n"
        f"stdout:\n{r.stdout.decode()}\n"
        f"stderr:\n{r.stderr.decode()}"
    )

    assert os.path.isfile("/app/output.txt"), "Output file not produced"
    with open("/app/output.txt") as fh:
        return fh.readlines()


# --------------- tests ----------------------------------------------------

def test_source_file_exists():
    """Implementation file must exist."""
    assert os.path.isfile("/app/pgas_array.c"), \
        "pgas_array.c not found in /app/"


def test_uses_mpi_rma():
    """Implementation must use MPI RMA windows."""
    assert os.path.isfile("/app/pgas_array.c"), "No source file"
    with open("/app/pgas_array.c") as fh:
        src = fh.read()
    assert "MPI_Win" in src, \
        "Implementation must use MPI RMA windows (MPI_Win)"


def test_output_format(program_output):
    """Output file must have at least 10 lines (1 header + 9 data)."""
    assert len(program_output) >= 10, (
        f"Expected >= 10 output lines, got {len(program_output)}"
    )


def test_convergence(program_output):
    """Solver must converge in a reasonable number of iterations."""
    niter = int(program_output[0].strip())
    assert niter < 8000, f"Did not converge: {niter} iterations"
    assert niter > 10, f"Suspiciously few iterations: {niter}"


def test_numerical_accuracy(program_output):
    """Solution values must match the analytical Laplace solution."""
    data_lines = program_output[1:]
    assert len(data_lines) >= 9, (
        f"Expected 9 data lines, got {len(data_lines)}"
    )

    for line in data_lines[:9]:
        parts = line.strip().split()
        assert len(parts) == 3, f"Malformed output line: {line.strip()}"
        gi, gj = int(parts[0]), int(parts[1])
        val = float(parts[2])
        ref = _analytical(gi, gj)
        diff = abs(val - ref)
        assert diff < 0.5, (
            f"Point ({gi},{gj}): computed={val:.6f}, "
            f"analytical={ref:.6f}, diff={diff:.6f} > 0.5"
        )
