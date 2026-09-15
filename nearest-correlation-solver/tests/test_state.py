
import pytest
import json
import numpy as np
import os


def load_problem(n):
    with open(f"/app/problems/problem_{n}.json") as f:
        return json.load(f)


def load_solution(n):
    path = f"/app/solutions/solution_{n}.json"
    assert os.path.exists(path), f"Solution file {path} does not exist"
    with open(path) as f:
        return json.load(f)


def reference_ncm(A, weights=None, fixed_entries=None, tol=1e-12, maxits=100000):
    """Reference NCM via alternating projections with Dykstra's correction.

    Based on N. J. Higham, Computing the Nearest Correlation Matrix (2002).
    """
    A = np.array(A, dtype=np.float64)
    n = A.shape[0]

    if weights is not None:
        w = np.array(weights, dtype=np.float64)
        Whalf = np.sqrt(np.outer(w, w))
    else:
        Whalf = np.ones((n, n))

    X = A.copy()
    Y = A.copy()
    dS = np.zeros_like(A)

    for iteration in range(maxits):
        Xold = X.copy()
        R = Y - dS
        R_wtd = Whalf * R

        eigvals, eigvecs = np.linalg.eigh(R_wtd)
        eigvals = np.maximum(eigvals, 0.0)
        X = eigvecs @ np.diag(eigvals) @ eigvecs.T
        X = (X + X.T) / 2.0
        X = X / Whalf

        dS = X - R
        Yold = Y.copy()
        Y = X.copy()
        np.fill_diagonal(Y, 1.0)

        if fixed_entries is not None:
            for i, j in fixed_entries:
                Y[i, j] = A[i, j]

        rdX = np.linalg.norm(X - Xold, "fro") / max(np.linalg.norm(X, "fro"), 1e-30)
        rdY = np.linalg.norm(Y - Yold, "fro") / max(np.linalg.norm(Y, "fro"), 1e-30)
        rdXY = np.linalg.norm(Y - X, "fro") / max(np.linalg.norm(Y, "fro"), 1e-30)

        if max(rdX, rdY, rdXY) < tol:
            break
    else:
        raise RuntimeError(f"Reference NCM did not converge after {maxits} iterations")

    return Y


# ────────────────────────────────────────────────────────────────────
# Problem 1: Basic 6x6 NCM
# ────────────────────────────────────────────────────────────────────
class TestProblem1:
    def setup_method(self):
        self.prob = load_problem(1)
        self.sol = load_solution(1)
        self.A = np.array(self.prob["matrix"])
        self.X = np.array(self.sol["nearest_correlation_matrix"])

    def test_symmetric(self):
        diff = np.max(np.abs(self.X - self.X.T))
        assert diff < 1e-10, f"Not symmetric: max |X-X^T| = {diff}"

    def test_unit_diagonal(self):
        diag_err = np.max(np.abs(np.diag(self.X) - 1.0))
        assert diag_err < 1e-10, f"Diagonal not unit: max error = {diag_err}"

    def test_psd(self):
        eigvals = np.linalg.eigvalsh(self.X)
        assert eigvals[0] >= -1e-8, f"Not PSD: min eigenvalue = {eigvals[0]}"

    def test_min_eigenvalue_reported(self):
        actual_min = float(np.min(np.linalg.eigvalsh(self.X)))
        reported_min = self.sol["min_eigenvalue"]
        assert abs(actual_min - reported_min) < 1e-6, (
            f"Reported min eigenvalue {reported_min} != actual {actual_min}"
        )

    def test_frobenius_distance_reported(self):
        actual_dist = float(np.linalg.norm(self.A - self.X, "fro"))
        reported_dist = self.sol["frobenius_distance"]
        assert abs(actual_dist - reported_dist) < 1e-6, (
            f"Reported distance {reported_dist} != actual {actual_dist}"
        )

    def test_optimality(self):
        X_ref = reference_ncm(self.A, tol=1e-14)
        ref_dist = np.linalg.norm(self.A - X_ref, "fro")
        actual_dist = np.linalg.norm(self.A - self.X, "fro")
        assert actual_dist <= ref_dist * 1.001 + 1e-8, (
            f"Suboptimal: dist={actual_dist:.8e}, ref={ref_dist:.8e}"
        )

    def test_nontrivial(self):
        assert np.linalg.norm(self.A - self.X, "fro") > 1e-10, (
            "Distance is zero — input has negative eigenvalues, so NCM != input"
        )


# ────────────────────────────────────────────────────────────────────
# Problem 2: Weighted 10x10 NCM
# ────────────────────────────────────────────────────────────────────
class TestProblem2:
    def setup_method(self):
        self.prob = load_problem(2)
        self.sol = load_solution(2)
        self.A = np.array(self.prob["matrix"])
        self.X = np.array(self.sol["nearest_correlation_matrix"])
        self.w = np.array(self.prob["weights"])
        self.Whalf = np.sqrt(np.outer(self.w, self.w))

    def test_symmetric(self):
        diff = np.max(np.abs(self.X - self.X.T))
        assert diff < 1e-10, f"Not symmetric: max |X-X^T| = {diff}"

    def test_unit_diagonal(self):
        diag_err = np.max(np.abs(np.diag(self.X) - 1.0))
        assert diag_err < 1e-10, f"Diagonal not unit: max error = {diag_err}"

    def test_psd(self):
        eigvals = np.linalg.eigvalsh(self.X)
        assert eigvals[0] >= -1e-8, f"Not PSD: min eigenvalue = {eigvals[0]}"

    def test_weighted_distance_reported(self):
        actual_dist = float(np.linalg.norm(self.Whalf * (self.A - self.X), "fro"))
        reported_dist = self.sol["frobenius_distance"]
        assert abs(actual_dist - reported_dist) < 1e-6, (
            f"Reported weighted dist {reported_dist} != actual {actual_dist}"
        )

    def test_weighted_optimality(self):
        X_ref = reference_ncm(self.A, weights=self.w.tolist(), tol=1e-14)
        ref_dist = np.linalg.norm(self.Whalf * (self.A - X_ref), "fro")
        actual_dist = np.linalg.norm(self.Whalf * (self.A - self.X), "fro")
        assert actual_dist <= ref_dist * 1.001 + 1e-8, (
            f"Suboptimal weighted: dist={actual_dist:.8e}, ref={ref_dist:.8e}"
        )

    def test_nontrivial(self):
        assert np.linalg.norm(self.A - self.X, "fro") > 1e-10


# ────────────────────────────────────────────────────────────────────
# Problem 3: Constrained 8x8 NCM (preserve trailing 3x3 block)
# ────────────────────────────────────────────────────────────────────
class TestProblem3:
    def setup_method(self):
        self.prob = load_problem(3)
        self.sol = load_solution(3)
        self.A = np.array(self.prob["matrix"])
        self.X = np.array(self.sol["nearest_correlation_matrix"])
        self.fixed = self.prob["fixed_entries"]

    def test_symmetric(self):
        diff = np.max(np.abs(self.X - self.X.T))
        assert diff < 1e-10, f"Not symmetric: max |X-X^T| = {diff}"

    def test_unit_diagonal(self):
        diag_err = np.max(np.abs(np.diag(self.X) - 1.0))
        assert diag_err < 1e-10, f"Diagonal not unit: max error = {diag_err}"

    def test_psd(self):
        eigvals = np.linalg.eigvalsh(self.X)
        assert eigvals[0] >= -1e-8, f"Not PSD: min eigenvalue = {eigvals[0]}"

    def test_fixed_entries_preserved(self):
        for i, j in self.fixed:
            diff = abs(self.X[i, j] - self.A[i, j])
            assert diff < 1e-10, (
                f"Entry ({i},{j}) not preserved: expected {self.A[i,j]}, got {self.X[i,j]}"
            )

    def test_constrained_optimality(self):
        X_ref = reference_ncm(self.A, fixed_entries=self.fixed, tol=1e-14)
        ref_dist = np.linalg.norm(self.A - X_ref, "fro")
        actual_dist = np.linalg.norm(self.A - self.X, "fro")
        assert actual_dist <= ref_dist * 1.001 + 1e-8, (
            f"Suboptimal constrained: dist={actual_dist:.8e}, ref={ref_dist:.8e}"
        )

    def test_frobenius_distance_reported(self):
        actual_dist = float(np.linalg.norm(self.A - self.X, "fro"))
        reported_dist = self.sol["frobenius_distance"]
        assert abs(actual_dist - reported_dist) < 1e-6


# ────────────────────────────────────────────────────────────────────
# Problem 4: 15x15 NCM + Modified Cholesky
# ────────────────────────────────────────────────────────────────────
class TestProblem4:
    def setup_method(self):
        self.prob = load_problem(4)
        self.sol = load_solution(4)
        self.A = np.array(self.prob["matrix"])
        self.X = np.array(self.sol["nearest_correlation_matrix"])
        self.mc = self.sol["modified_cholesky"]

    def test_ncm_symmetric(self):
        diff = np.max(np.abs(self.X - self.X.T))
        assert diff < 1e-10

    def test_ncm_unit_diagonal(self):
        diag_err = np.max(np.abs(np.diag(self.X) - 1.0))
        assert diag_err < 1e-10

    def test_ncm_psd(self):
        eigvals = np.linalg.eigvalsh(self.X)
        assert eigvals[0] >= -1e-8, f"Not PSD: min eigenvalue = {eigvals[0]}"

    def test_ncm_optimality(self):
        X_ref = reference_ncm(self.A, tol=1e-14)
        ref_dist = np.linalg.norm(self.A - X_ref, "fro")
        actual_dist = np.linalg.norm(self.A - self.X, "fro")
        assert actual_dist <= ref_dist * 1.001 + 1e-8

    def test_modified_cholesky_present(self):
        assert self.mc is not None, "modified_cholesky should not be null"
        assert "perturbation_frobenius_norm" in self.mc
        assert "perturbed_min_eigenvalue" in self.mc
        assert "condition_number" in self.mc

    def test_perturbation_lower_bound(self):
        """Perturbation norm must be at least the distance to the PSD cone."""
        eigvals = np.linalg.eigvalsh(self.A)
        neg_eigvals = eigvals[eigvals < 0]
        optimal_perturbation = float(np.sqrt(np.sum(neg_eigvals ** 2)))
        reported = self.mc["perturbation_frobenius_norm"]
        assert reported >= optimal_perturbation * 0.99 - 1e-8, (
            f"Perturbation {reported} < optimal lower bound {optimal_perturbation}"
        )

    def test_perturbation_upper_bound(self):
        """Perturbation should not be excessively large."""
        eigvals = np.linalg.eigvalsh(self.A)
        neg_eigvals = eigvals[eigvals < 0]
        optimal_perturbation = float(np.sqrt(np.sum(neg_eigvals ** 2)))
        reported = self.mc["perturbation_frobenius_norm"]
        n = self.A.shape[0]
        assert reported <= optimal_perturbation * n * 5.0 + 1e-3, (
            f"Perturbation {reported} excessively large vs optimal {optimal_perturbation}"
        )

    def test_perturbed_is_psd(self):
        assert self.mc["perturbed_min_eigenvalue"] > -1e-10, (
            f"Perturbed matrix not PSD: min eig = {self.mc['perturbed_min_eigenvalue']}"
        )

    def test_condition_number_valid(self):
        cond = self.mc["condition_number"]
        assert cond > 0, f"Condition number should be positive, got {cond}"
        assert cond < 1e16, f"Condition number unreasonably large: {cond}"


# ────────────────────────────────────────────────────────────────────
# Problem 5: 12x12 NCM + Linear system + Backward error
# ────────────────────────────────────────────────────────────────────
class TestProblem5:
    def setup_method(self):
        self.prob = load_problem(5)
        self.sol = load_solution(5)
        self.A = np.array(self.prob["matrix"])
        self.X = np.array(self.sol["nearest_correlation_matrix"])
        self.b = np.array(self.prob["solve_system_rhs"])
        self.ls = self.sol["linear_system"]
        self.mc = self.sol["modified_cholesky"]

    def test_ncm_symmetric(self):
        diff = np.max(np.abs(self.X - self.X.T))
        assert diff < 1e-10

    def test_ncm_unit_diagonal(self):
        diag_err = np.max(np.abs(np.diag(self.X) - 1.0))
        assert diag_err < 1e-10

    def test_ncm_psd(self):
        eigvals = np.linalg.eigvalsh(self.X)
        assert eigvals[0] >= -1e-8

    def test_ncm_optimality(self):
        X_ref = reference_ncm(self.A, tol=1e-14)
        ref_dist = np.linalg.norm(self.A - X_ref, "fro")
        actual_dist = np.linalg.norm(self.A - self.X, "fro")
        assert actual_dist <= ref_dist * 1.001 + 1e-8

    def test_linear_system_present(self):
        assert self.ls is not None, "linear_system should not be null"
        assert "solution" in self.ls
        assert "normwise_backward_error" in self.ls
        assert "componentwise_backward_error" in self.ls

    def test_solution_accuracy(self):
        x = np.array(self.ls["solution"])
        r = self.b - self.X @ x
        rel_res = np.linalg.norm(r) / np.linalg.norm(self.b)
        assert rel_res < 1e-4, f"Relative residual too large: {rel_res}"

    def test_normwise_backward_error(self):
        x = np.array(self.ls["solution"])
        r = self.b - self.X @ x
        denom = (
            np.linalg.norm(self.X, np.inf) * np.linalg.norm(x, np.inf)
            + np.linalg.norm(self.b, np.inf)
        )
        eta = float(np.linalg.norm(r, np.inf) / max(denom, 1e-30))
        reported_eta = self.ls["normwise_backward_error"]
        # Allow 1% relative error or 1e-14 absolute
        assert abs(eta - reported_eta) / max(eta, 1e-30) < 0.01 or abs(eta - reported_eta) < 1e-14, (
            f"Normwise BE mismatch: computed {eta}, reported {reported_eta}"
        )

    def test_componentwise_backward_error(self):
        x = np.array(self.ls["solution"])
        r = self.b - self.X @ x
        denom = np.abs(self.X) @ np.abs(x) + np.abs(self.b)
        valid = denom > 1e-30
        if np.any(valid):
            omega = float(np.max(np.abs(r[valid]) / denom[valid]))
        else:
            omega = 0.0
        reported_omega = self.ls["componentwise_backward_error"]
        assert abs(omega - reported_omega) / max(omega, 1e-30) < 0.01 or abs(omega - reported_omega) < 1e-14, (
            f"Componentwise BE mismatch: computed {omega}, reported {reported_omega}"
        )

    def test_modified_cholesky_present(self):
        assert self.mc is not None, "modified_cholesky should not be null for problem 5"

    def test_modified_cholesky_perturbation(self):
        eigvals = np.linalg.eigvalsh(self.A)
        neg_eigvals = eigvals[eigvals < 0]
        optimal_perturbation = float(np.sqrt(np.sum(neg_eigvals ** 2)))
        reported = self.mc["perturbation_frobenius_norm"]
        assert reported >= optimal_perturbation * 0.99 - 1e-8
        n = self.A.shape[0]
        assert reported <= optimal_perturbation * n * 5.0 + 1e-3
