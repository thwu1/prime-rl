"""Tests for the TPFA reservoir pressure solver.

Verifies correctness against analytical solutions for simple cases
and against an independently computed reference for the main problem.
"""

import csv
import json
import os
import subprocess
import tempfile

import numpy as np
import pytest
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

SOLVER = "/app/solver.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_case(d, nx, ny, dx, dy, h, kx, ky, wells, mu, ri, rj, rp):
    """Write a complete set of input JSON files into directory *d*."""
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "grid.json"), "w") as f:
        json.dump({"nx": nx, "ny": ny, "dx": dx, "dy": dy, "thickness": h}, f)
    with open(os.path.join(d, "permeability.json"), "w") as f:
        json.dump({"kx": kx, "ky": ky}, f)
    with open(os.path.join(d, "wells.json"), "w") as f:
        json.dump({"wells": wells}, f)
    with open(os.path.join(d, "fluid.json"), "w") as f:
        json.dump({"viscosity": mu}, f)
    with open(os.path.join(d, "config.json"), "w") as f:
        json.dump({"reference_pressure": {"i": ri, "j": rj, "value": rp}}, f)


def _run_solver(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    r = subprocess.run(
        ["python3", SOLVER, input_dir, output_dir],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, (
        f"Solver exited with code {r.returncode}\n"
        f"--- stdout ---\n{r.stdout[-2000:]}\n"
        f"--- stderr ---\n{r.stderr[-2000:]}"
    )


def _read_pressures(output_dir, nx, ny):
    path = os.path.join(output_dir, "pressure.csv")
    assert os.path.exists(path), f"pressure.csv not found in {output_dir}"
    p = np.full((nx, ny), np.nan)
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            i, j = int(row["i"]), int(row["j"])
            p[i][j] = float(row["pressure"])
    assert not np.any(np.isnan(p)), "Missing pressure entries in pressure.csv"
    return p


def _reference_solve(nx, ny, dx, dy, h, kx, ky, mu, wells, ri, rj, rp):
    """Independently compute the TPFA reference solution using scipy."""
    N = nx * ny

    def cidx(i, j):
        return i * ny + j

    A = lil_matrix((N, N))
    b = np.zeros(N)

    # x-faces (between column i and i+1)
    for i in range(nx - 1):
        for j in range(ny):
            c1, c2 = cidx(i, j), cidx(i + 1, j)
            d1 = dx[i] / 2.0
            d2 = dx[i + 1] / 2.0
            area = dy[j] * h
            T = area / (mu * (d1 / kx[i][j] + d2 / kx[i + 1][j]))
            A[c1, c1] -= T
            A[c1, c2] += T
            A[c2, c2] -= T
            A[c2, c1] += T

    # y-faces (between row j and j+1)
    for i in range(nx):
        for j in range(ny - 1):
            c1, c2 = cidx(i, j), cidx(i, j + 1)
            d1 = dy[j] / 2.0
            d2 = dy[j + 1] / 2.0
            area = dx[i] * h
            T = area / (mu * (d1 / ky[i][j] + d2 / ky[i][j + 1]))
            A[c1, c1] -= T
            A[c1, c2] += T
            A[c2, c2] -= T
            A[c2, c1] += T

    # well source terms: sum T*(p_nb - p_cell) = -Q_well
    for w in wells:
        c = cidx(w["i"], w["j"])
        b[c] -= w["value"]

    # reference pressure constraint
    rc = cidx(ri, rj)
    A[rc, :] = 0
    A[rc, rc] = 1.0
    b[rc] = rp

    p = spsolve(A.tocsr(), b)
    return p.reshape((nx, ny))


# ---------------------------------------------------------------------------
# Test 1 — 1-D linear flow, uniform permeability & grid
# ---------------------------------------------------------------------------

class TestLinear1D:
    """5x1 grid, uniform k, two rate-controlled wells.

    Analytical pressure: linear gradient between injector and producer.
    """

    def test_pressure_gradient(self):
        with tempfile.TemporaryDirectory() as td:
            idir = os.path.join(td, "in")
            odir = os.path.join(td, "out")
            nx, ny = 5, 1
            dx = [100.0] * 5
            dy = [100.0]
            h, mu, k = 10.0, 1e-3, 1e-13
            kx = [[k]] * nx
            ky = [[k]] * nx
            wells = [
                {"name": "INJ", "i": 0, "j": 0, "type": "rate", "value": 1e-5},
                {"name": "PROD", "i": 4, "j": 0, "type": "rate", "value": -1e-5},
            ]
            _write_case(idir, nx, ny, dx, dy, h, kx, ky, wells, mu, 2, 0, 1e7)
            _run_solver(idir, odir)
            p = _read_pressures(odir, nx, ny)
            expected = [10020000.0, 10010000.0, 10000000.0, 9990000.0, 9980000.0]
            for i in range(nx):
                assert p[i][0] == pytest.approx(expected[i], rel=1e-6), (
                    f"Cell ({i},0): expected {expected[i]}, got {p[i][0]}"
                )


# ---------------------------------------------------------------------------
# Test 2 — 1-D heterogeneous: harmonic-mean transmissibility
# ---------------------------------------------------------------------------

class TestHarmonicMean:
    """4x1 grid with a 100x lower-k cell.

    Using arithmetic mean gives ~990 Pa drop across the low-k cell instead of
    the correct ~50 500 Pa.  This test reliably catches that error.
    """

    def test_heterogeneous_permeability(self):
        with tempfile.TemporaryDirectory() as td:
            idir = os.path.join(td, "in")
            odir = os.path.join(td, "out")
            nx, ny = 4, 1
            dx = [100.0] * 4
            dy = [100.0]
            h, mu = 10.0, 1e-3
            k_vals = [1e-13, 1e-15, 1e-13, 1e-13]
            kx = [[kv] for kv in k_vals]
            ky = [[kv] for kv in k_vals]
            wells = [
                {"name": "INJ", "i": 0, "j": 0, "type": "rate", "value": 1e-6},
                {"name": "PROD", "i": 3, "j": 0, "type": "rate", "value": -1e-6},
            ]
            _write_case(idir, nx, ny, dx, dy, h, kx, ky, wells, mu, 0, 0, 1e7)
            _run_solver(idir, odir)
            p = _read_pressures(odir, nx, ny)

            # Exact analytical values
            expected = [10000000.0, 9949500.0, 9899000.0, 9898000.0]
            for i in range(nx):
                assert p[i][0] == pytest.approx(expected[i], rel=1e-4), (
                    f"Cell ({i},0): expected {expected[i]}, got {p[i][0]}"
                )


# ---------------------------------------------------------------------------
# Test 3 — 1-D non-uniform grid spacing
# ---------------------------------------------------------------------------

class TestNonUniformGrid:
    """3x1 grid with dx = [60, 100, 40].

    Ensures face transmissibilities use the correct half-cell distances
    rather than a constant spacing.
    """

    def test_variable_spacing(self):
        with tempfile.TemporaryDirectory() as td:
            idir = os.path.join(td, "in")
            odir = os.path.join(td, "out")
            nx, ny = 3, 1
            dx = [60.0, 100.0, 40.0]
            dy = [100.0]
            h, mu, k = 10.0, 1e-3, 1e-13
            kx = [[k]] * nx
            ky = [[k]] * nx
            wells = [
                {"name": "INJ", "i": 0, "j": 0, "type": "rate", "value": 1e-5},
                {"name": "PROD", "i": 2, "j": 0, "type": "rate", "value": -1e-5},
            ]
            _write_case(idir, nx, ny, dx, dy, h, kx, ky, wells, mu, 1, 0, 1e7)
            _run_solver(idir, odir)
            p = _read_pressures(odir, nx, ny)

            expected = [10008000.0, 10000000.0, 9993000.0]
            for i in range(nx):
                assert p[i][0] == pytest.approx(expected[i], rel=1e-6), (
                    f"Cell ({i},0): expected {expected[i]}, got {p[i][0]}"
                )


# ---------------------------------------------------------------------------
# Test 4 — 2-D symmetric 3x3
# ---------------------------------------------------------------------------

class TestSymmetric2D:
    """3x3 grid with center injector and four corner producers.

    The full 4-fold symmetry lets us verify the 2-D assembly analytically:
      corners  = 9 985 000
      edges    = 9 990 000
      center   = 10 000 000
    """

    def test_3x3_symmetric(self):
        with tempfile.TemporaryDirectory() as td:
            idir = os.path.join(td, "in")
            odir = os.path.join(td, "out")
            nx, ny = 3, 3
            dx = [100.0] * 3
            dy = [100.0] * 3
            h, mu, k = 10.0, 1e-3, 1e-13
            kx = [[k, k, k] for _ in range(3)]
            ky = [[k, k, k] for _ in range(3)]
            wells = [
                {"name": "I", "i": 1, "j": 1, "type": "rate", "value": 4e-5},
                {"name": "P1", "i": 0, "j": 0, "type": "rate", "value": -1e-5},
                {"name": "P2", "i": 0, "j": 2, "type": "rate", "value": -1e-5},
                {"name": "P3", "i": 2, "j": 0, "type": "rate", "value": -1e-5},
                {"name": "P4", "i": 2, "j": 2, "type": "rate", "value": -1e-5},
            ]
            _write_case(idir, nx, ny, dx, dy, h, kx, ky, wells, mu, 1, 1, 1e7)
            _run_solver(idir, odir)
            p = _read_pressures(odir, nx, ny)

            # Corners
            for ci, cj in [(0, 0), (0, 2), (2, 0), (2, 2)]:
                assert p[ci][cj] == pytest.approx(9985000.0, rel=1e-6), (
                    f"Corner ({ci},{cj}): expected 9985000, got {p[ci][cj]}"
                )
            # Edges
            for ci, cj in [(1, 0), (0, 1), (1, 2), (2, 1)]:
                assert p[ci][cj] == pytest.approx(9990000.0, rel=1e-6), (
                    f"Edge ({ci},{cj}): expected 9990000, got {p[ci][cj]}"
                )
            # Center
            assert p[1][1] == pytest.approx(10000000.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Test 5 — main 20x20 problem
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_output():
    """Run solver on the provided 20x20 problem once for all main tests."""
    _run_solver("/app/input", "/app/output")
    return "/app/output"


class TestMainProblem:
    """Validation of the solver on the 20x20 heterogeneous, anisotropic,
    non-uniform-grid problem shipped with the task."""

    def test_output_files_exist(self, main_output):
        assert os.path.isfile(os.path.join(main_output, "pressure.csv"))
        assert os.path.isfile(os.path.join(main_output, "diagnostics.json"))

    def test_pressure_count(self, main_output):
        p = _read_pressures(main_output, 20, 20)
        assert p.shape == (20, 20)

    def test_mass_balance(self, main_output):
        with open(os.path.join(main_output, "diagnostics.json")) as f:
            diag = json.load(f)
        assert "mass_balance_error" in diag
        assert abs(diag["mass_balance_error"]) < 1e-8

    def test_pressure_ordering(self, main_output):
        """Injectors should have higher pressure than producers."""
        p = _read_pressures(main_output, 20, 20)
        inj_avg = (p[2][2] + p[2][17]) / 2.0
        prod_avg = (p[17][17] + p[17][2]) / 2.0
        assert inj_avg > prod_avg, (
            f"Injector avg {inj_avg} should exceed producer avg {prod_avg}"
        )

    def test_pressure_vs_reference(self, main_output):
        """Compare solver output against an independently computed reference."""
        with open("/app/input/grid.json") as f:
            grid = json.load(f)
        with open("/app/input/permeability.json") as f:
            perm = json.load(f)
        with open("/app/input/wells.json") as f:
            wells = json.load(f)
        with open("/app/input/fluid.json") as f:
            fluid = json.load(f)
        with open("/app/input/config.json") as f:
            config = json.load(f)

        rc = config["reference_pressure"]
        p_ref = _reference_solve(
            grid["nx"],
            grid["ny"],
            grid["dx"],
            grid["dy"],
            grid["thickness"],
            perm["kx"],
            perm["ky"],
            fluid["viscosity"],
            wells["wells"],
            rc["i"],
            rc["j"],
            rc["value"],
        )
        p_agent = _read_pressures(main_output, 20, 20)
        np.testing.assert_allclose(
            p_agent, p_ref, rtol=1e-4,
            err_msg="Solver pressures diverge from the TPFA reference solution",
        )
