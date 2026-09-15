"""Verification tests for topology optimization solution.

Independent FEM evaluator re-computes compliance from the agent's density field
to verify correctness without trusting the agent's solver implementation.
"""

import csv
import json
import os

import numpy as np
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


# ---------------------------------------------------------------------------
# Independent FEM evaluator
# ---------------------------------------------------------------------------

def _compute_ke(nu):
    """8x8 element stiffness for a unit-square Q4 plane-stress element.

    Node order: BL(0,0) BR(1,0) TR(1,1) TL(0,1).
    DOF order per node: (ux, uy).
    """
    factor = 1.0 / (1.0 - nu ** 2)
    D = factor * np.array([
        [1.0, nu, 0.0],
        [nu, 1.0, 0.0],
        [0.0, 0.0, (1.0 - nu) / 2.0],
    ])
    KE = np.zeros((8, 8))
    gp = 1.0 / np.sqrt(3.0)
    coords = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    for xi in (-gp, gp):
        for eta in (-gp, gp):
            dNdxi = np.array([
                [-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)],
                [-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)],
            ]) / 4.0
            J = dNdxi @ coords
            detJ = np.linalg.det(J)
            dNdx = np.linalg.solve(J, dNdxi)
            B = np.zeros((3, 8))
            for i in range(4):
                B[0, 2 * i] = dNdx[0, i]
                B[1, 2 * i + 1] = dNdx[1, i]
                B[2, 2 * i] = dNdx[1, i]
                B[2, 2 * i + 1] = dNdx[0, i]
            KE += B.T @ D @ B * detJ
    return KE


def evaluate_compliance(density_2d, prob):
    """Solve the FEM problem with given densities and return compliance."""
    nelx = prob["mesh"]["nelx"]
    nely = prob["mesh"]["nely"]
    E0 = prob["material"]["E0"]
    Emin = prob["material"]["Emin"]
    nu = prob["material"]["nu"]
    penal = prob["optimization"]["penal"]

    nele = nelx * nely
    ndof = 2 * (nelx + 1) * (nely + 1)
    KE = _compute_ke(nu)

    # density_2d[i, j] -> element (ex=j, ey=i); C-order flatten gives ey*nelx+ex
    xPhys = density_2d.flatten()

    # Build element-DOF table
    ey_arr, ex_arr = np.meshgrid(np.arange(nely), np.arange(nelx), indexing="ij")
    ey_f = ey_arr.flatten()
    ex_f = ex_arr.flatten()
    n_bl = ey_f * (nelx + 1) + ex_f
    n_br = n_bl + 1
    n_tl = (ey_f + 1) * (nelx + 1) + ex_f
    n_tr = n_tl + 1
    edofMat = np.column_stack([
        2 * n_bl, 2 * n_bl + 1,
        2 * n_br, 2 * n_br + 1,
        2 * n_tr, 2 * n_tr + 1,
        2 * n_tl, 2 * n_tl + 1,
    ])

    # Assembly triplets
    iK = np.repeat(edofMat, 8, axis=1).flatten()
    jK = np.tile(edofMat, (1, 8)).flatten()
    Ee = Emin + xPhys ** penal * (E0 - Emin)
    sK = (KE.flatten()[np.newaxis, :] * Ee[:, np.newaxis]).flatten()
    K = coo_matrix((sK, (iK, jK)), shape=(ndof, ndof)).tocsc()

    # BCs — left edge fully fixed
    fixed = []
    for iy in range(nely + 1):
        n = iy * (nelx + 1)
        fixed.extend([2 * n, 2 * n + 1])
    fixed = np.array(fixed, dtype=int)
    free = np.setdiff1d(np.arange(ndof), fixed)

    # Load — unit downward at mid-right
    F = np.zeros(ndof)
    load_node = (nely // 2) * (nelx + 1) + nelx
    F[2 * load_node + 1] = -1.0

    U = np.zeros(ndof)
    U[free] = spsolve(K[np.ix_(free, free)], F[free])

    Ue = U[edofMat]
    ce = np.sum((Ue @ KE) * Ue, axis=1)
    return float(np.sum(Ee * ce))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_problem():
    with open("/app/problem.json") as f:
        return json.load(f)


def _load_density():
    return np.load("/app/results/density.npy")


def _load_compliance():
    with open("/app/results/compliance.txt") as f:
        return float(f.read().strip())


def _load_history():
    rows = []
    with open("/app/results/history.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


# ---------------------------------------------------------------------------
# Tests — output format
# ---------------------------------------------------------------------------

class TestOutputFiles:
    def test_density_exists(self):
        assert os.path.isfile("/app/results/density.npy"), "density.npy missing"

    def test_compliance_exists(self):
        assert os.path.isfile("/app/results/compliance.txt"), "compliance.txt missing"

    def test_history_exists(self):
        assert os.path.isfile("/app/results/history.csv"), "history.csv missing"


# ---------------------------------------------------------------------------
# Tests — density field properties
# ---------------------------------------------------------------------------

class TestDensityField:
    def test_shape(self):
        prob = _load_problem()
        rho = _load_density()
        expected = (prob["mesh"]["nely"], prob["mesh"]["nelx"])
        assert rho.shape == expected, f"Expected shape {expected}, got {rho.shape}"

    def test_values_in_range(self):
        rho = _load_density()
        assert np.all(rho >= -1e-6), "Density contains negative values"
        assert np.all(rho <= 1.0 + 1e-6), "Density exceeds 1"

    def test_nontrivial_topology(self):
        rho = _load_density()
        assert np.std(rho) > 0.1, (
            f"Density field is nearly uniform (std={np.std(rho):.4f}); "
            "optimization likely did not produce a meaningful topology"
        )


# ---------------------------------------------------------------------------
# Tests — optimization quality
# ---------------------------------------------------------------------------

class TestOptimizationQuality:
    def test_volume_fraction(self):
        prob = _load_problem()
        rho = _load_density()
        target = prob["optimization"]["volfrac"]
        actual = float(np.mean(rho))
        assert abs(actual - target) < 0.02, (
            f"Volume fraction {actual:.4f} deviates from target {target}"
        )

    def test_compliance_positive(self):
        c = _load_compliance()
        assert c > 0, "Compliance must be positive"

    def test_compliance_independent_reeval(self):
        """Re-evaluate compliance with an independent FEM solver."""
        prob = _load_problem()
        rho = _load_density()
        c_reported = _load_compliance()
        c_check = evaluate_compliance(rho, prob)
        rel_err = abs(c_check - c_reported) / max(abs(c_reported), 1e-12)
        assert rel_err < 0.05, (
            f"Compliance mismatch: reported={c_reported:.6f}, "
            f"re-evaluated={c_check:.6f}, relative error={rel_err:.4f}"
        )

    def test_better_than_uniform(self):
        """Optimized design must outperform uniform density by >= 10 %."""
        prob = _load_problem()
        rho = _load_density()
        nelx, nely = prob["mesh"]["nelx"], prob["mesh"]["nely"]
        volfrac = prob["optimization"]["volfrac"]
        c_opt = evaluate_compliance(rho, prob)
        c_uni = evaluate_compliance(np.full((nely, nelx), volfrac), prob)
        assert c_opt < 0.9 * c_uni, (
            f"Optimized compliance ({c_opt:.2f}) is not 10 %+ better "
            f"than uniform baseline ({c_uni:.2f})"
        )

    def test_convergence_change(self):
        """Final design-variable change must be small."""
        hist = _load_history()
        assert len(hist) >= 5, "Too few iterations recorded"
        final_change = hist[-1]["change"]
        assert final_change < 0.05, (
            f"Optimization did not converge (final change={final_change:.4f})"
        )

    def test_compliance_decreased(self):
        """Compliance must decrease from first to last iteration."""
        hist = _load_history()
        assert len(hist) >= 2, "Need at least 2 iterations"
        c_first = hist[0]["compliance"]
        c_last = hist[-1]["compliance"]
        assert c_last < c_first, (
            f"Compliance did not decrease: {c_first:.2f} -> {c_last:.2f}"
        )
