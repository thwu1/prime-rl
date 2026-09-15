"""
Tests for baseline correction engine.

"""

import ast
import sys
import os

import numpy as np
import pytest

# Ensure /app is on the path
sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Deterministic test spectrum generators
# ---------------------------------------------------------------------------

def _gaussian(x, height, center, sigma):
    return height * np.exp(-((x - center) / sigma) ** 2)


def make_spectrum_1():
    """Linear baseline + Gaussian peaks + noise (500 points)."""
    rng = np.random.default_rng(42)
    x = np.linspace(1, 1000, 500)
    peaks = (
        _gaussian(x, 8, 200, 10)
        + _gaussian(x, 12, 400, 15)
        + _gaussian(x, 6, 700, 8)
        + _gaussian(x, 10, 850, 12)
    )
    baseline = 3 + 0.01 * x
    noise = rng.normal(0, 0.2, 500)
    return peaks + baseline + noise


def make_spectrum_2():
    """Exponential baseline + Gaussian peaks + noise (500 points)."""
    rng = np.random.default_rng(123)
    x = np.linspace(1, 1000, 500)
    peaks = (
        _gaussian(x, 6, 150, 8)
        + _gaussian(x, 9, 350, 12)
        + _gaussian(x, 15, 550, 10)
        + _gaussian(x, 7, 800, 15)
    )
    baseline = 5 + 15 * np.exp(-x / 400)
    noise = rng.normal(0, 0.2, 500)
    return peaks + baseline + noise


def make_spectrum_3():
    """Gaussian-shaped baseline + Gaussian peaks + noise (500 points)."""
    rng = np.random.default_rng(789)
    x = np.linspace(1, 1000, 500)
    peaks = (
        _gaussian(x, 10, 100, 12)
        + _gaussian(x, 8, 300, 10)
        + _gaussian(x, 13, 600, 15)
        + _gaussian(x, 11, 900, 8)
    )
    baseline = 5 + _gaussian(x, 20, 500, 500)
    noise = rng.normal(0, 0.2, 500)
    return peaks + baseline + noise


def make_spectrum_4():
    """Sinusoidal + linear baseline + many peaks + noise (1000 points)."""
    rng = np.random.default_rng(2024)
    x = np.linspace(0, 2000, 1000)
    peaks = sum(
        _gaussian(x, h, c, s) for h, c, s in [
            (10, 200, 15), (8, 500, 10), (12, 800, 20),
            (6, 1100, 8), (15, 1400, 12), (9, 1700, 18),
        ]
    )
    baseline = 10 + 5 * np.sin(2 * np.pi * x / 2000) + 0.002 * x
    noise = rng.normal(0, 0.3, 1000)
    return peaks + baseline + noise


SPECTRA = [make_spectrum_1(), make_spectrum_2(), make_spectrum_3()]
SPECTRUM_LONG = make_spectrum_4()


# ---------------------------------------------------------------------------
# Helper: relative error check
# ---------------------------------------------------------------------------

def check_baseline_match(solver_bl, ref_bl, algo_name, tol=5e-3):
    max_ref = np.max(np.abs(ref_bl))
    assert max_ref > 0, f"{algo_name}: reference baseline is all zeros"
    max_err = np.max(np.abs(solver_bl - ref_bl))
    rel_err = max_err / max_ref
    assert rel_err < tol, (
        f"{algo_name}: max relative error {rel_err:.6f} exceeds tolerance {tol} "
        f"(max_err={max_err:.6e}, max_ref={max_ref:.6e})"
    )


# ---------------------------------------------------------------------------
# Tests: diff_penalty_diags
# ---------------------------------------------------------------------------

class TestDiffPenaltyDiags:
    """Verify the banded difference-penalty matrix construction."""

    def test_order1_lower(self):
        from baseline_engine import diff_penalty_diags

        diags = diff_penalty_diags(5, 1, lower_only=True)
        assert diags.shape == (2, 5)
        np.testing.assert_allclose(diags[0], [1, 2, 2, 2, 1])
        np.testing.assert_allclose(diags[1], [-1, -1, -1, -1, 0])

    def test_order2_lower(self):
        from baseline_engine import diff_penalty_diags

        diags = diff_penalty_diags(7, 2, lower_only=True)
        assert diags.shape == (3, 7)
        np.testing.assert_allclose(diags[0], [1, 5, 6, 6, 6, 5, 1])
        np.testing.assert_allclose(diags[1], [-2, -4, -4, -4, -4, -2, 0])
        np.testing.assert_allclose(diags[2], [1, 1, 1, 1, 1, 0, 0])

    def test_order2_full(self):
        from baseline_engine import diff_penalty_diags

        diags = diff_penalty_diags(7, 2, lower_only=False)
        assert diags.shape == (5, 7)
        np.testing.assert_allclose(diags[2], [1, 5, 6, 6, 6, 5, 1])
        np.testing.assert_allclose(diags[1], [0, -2, -4, -4, -4, -4, -2])
        np.testing.assert_allclose(diags[0], [0, 0, 1, 1, 1, 1, 1])
        np.testing.assert_allclose(diags[3], [-2, -4, -4, -4, -4, -2, 0])
        np.testing.assert_allclose(diags[4], [1, 1, 1, 1, 1, 0, 0])

    def test_order3_lower(self):
        from baseline_engine import diff_penalty_diags

        diags = diff_penalty_diags(10, 3, lower_only=True)
        assert diags.shape == (4, 10)
        np.testing.assert_allclose(diags[0, 3:-3], [20, 20, 20, 20])

    def test_order4_lower(self):
        from baseline_engine import diff_penalty_diags

        diags = diff_penalty_diags(12, 4, lower_only=True)
        assert diags.shape == (5, 12)
        # Interior main-diagonal entry for order 4: 1+16+36+16+1 = 70
        np.testing.assert_allclose(diags[0, 4:-4], [70, 70, 70, 70])

    def test_matches_reference_various_sizes(self):
        """Compare against pybaselines reference for multiple sizes and orders."""
        from baseline_engine import diff_penalty_diags
        from pybaselines._banded_utils import diff_penalty_diagonals

        for n in [20, 50, 100, 200]:
            for d in [1, 2, 3, 4]:
                for lo in [True, False]:
                    mine = diff_penalty_diags(n, d, lower_only=lo)
                    ref = diff_penalty_diagonals(n, d, lower_only=lo)
                    np.testing.assert_allclose(
                        mine, ref, atol=1e-12,
                        err_msg=f"Mismatch for n={n}, d={d}, lower_only={lo}",
                    )


# ---------------------------------------------------------------------------
# Tests: Individual algorithms against pybaselines
# ---------------------------------------------------------------------------

class TestAsls:
    def test_matches_reference(self):
        from baseline_engine import asls as solver_asls
        from pybaselines.whittaker import asls as ref_asls

        for idx, y in enumerate(SPECTRA):
            ref_bl, _ = ref_asls(y, lam=1e6, p=0.01, diff_order=2, max_iter=50, tol=1e-3)
            sol_bl, sol_p = solver_asls(y, lam=1e6, p=0.01, diff_order=2, max_iter=50, tol=1e-3)
            check_baseline_match(sol_bl, ref_bl, f"asls/spectrum_{idx}")
            assert "weights" in sol_p
            assert "tol_history" in sol_p
            assert sol_p["weights"].shape == y.shape

    def test_different_params(self):
        from baseline_engine import asls as solver_asls
        from pybaselines.whittaker import asls as ref_asls

        y = SPECTRA[0]
        for lam, p in [(1e4, 0.05), (1e8, 0.001)]:
            ref_bl, _ = ref_asls(y, lam=lam, p=p)
            sol_bl, _ = solver_asls(y, lam=lam, p=p)
            check_baseline_match(sol_bl, ref_bl, f"asls(lam={lam},p={p})")

    def test_diff_order_variations(self):
        from baseline_engine import asls as solver_asls
        from pybaselines.whittaker import asls as ref_asls

        y = SPECTRA[0]
        for d in [1, 3]:
            ref_bl, _ = ref_asls(y, lam=1e6, p=0.01, diff_order=d)
            sol_bl, _ = solver_asls(y, lam=1e6, p=0.01, diff_order=d)
            check_baseline_match(sol_bl, ref_bl, f"asls/diff_order={d}")

    def test_long_signal(self):
        from baseline_engine import asls as solver_asls
        from pybaselines.whittaker import asls as ref_asls

        y = SPECTRUM_LONG
        ref_bl, _ = ref_asls(y, lam=1e6, p=0.01)
        sol_bl, _ = solver_asls(y, lam=1e6, p=0.01)
        check_baseline_match(sol_bl, ref_bl, "asls/long_signal")


class TestArpls:
    def test_matches_reference(self):
        from baseline_engine import arpls as solver_arpls
        from pybaselines.whittaker import arpls as ref_arpls

        for idx, y in enumerate(SPECTRA):
            ref_bl, _ = ref_arpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)
            sol_bl, sol_p = solver_arpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)
            check_baseline_match(sol_bl, ref_bl, f"arpls/spectrum_{idx}")
            assert "weights" in sol_p
            assert "tol_history" in sol_p

    def test_different_lam(self):
        from baseline_engine import arpls as solver_arpls
        from pybaselines.whittaker import arpls as ref_arpls

        y = SPECTRA[1]
        for lam in [1e3, 1e7]:
            ref_bl, _ = ref_arpls(y, lam=lam)
            sol_bl, _ = solver_arpls(y, lam=lam)
            check_baseline_match(sol_bl, ref_bl, f"arpls(lam={lam})")

    def test_diff_order_variations(self):
        from baseline_engine import arpls as solver_arpls
        from pybaselines.whittaker import arpls as ref_arpls

        y = SPECTRA[1]
        for d in [1, 3]:
            ref_bl, _ = ref_arpls(y, lam=1e5, diff_order=d)
            sol_bl, _ = solver_arpls(y, lam=1e5, diff_order=d)
            check_baseline_match(sol_bl, ref_bl, f"arpls/diff_order={d}")


class TestIarpls:
    def test_matches_reference(self):
        from baseline_engine import iarpls as solver_iarpls
        from pybaselines.whittaker import iarpls as ref_iarpls

        for idx, y in enumerate(SPECTRA):
            ref_bl, _ = ref_iarpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)
            sol_bl, sol_p = solver_iarpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)
            check_baseline_match(sol_bl, ref_bl, f"iarpls/spectrum_{idx}")
            assert "weights" in sol_p
            assert "tol_history" in sol_p

    def test_different_lam(self):
        from baseline_engine import iarpls as solver_iarpls
        from pybaselines.whittaker import iarpls as ref_iarpls

        y = SPECTRA[2]
        for lam in [1e4, 1e6]:
            ref_bl, _ = ref_iarpls(y, lam=lam)
            sol_bl, _ = solver_iarpls(y, lam=lam)
            check_baseline_match(sol_bl, ref_bl, f"iarpls(lam={lam})")

    def test_diff_order_3(self):
        from baseline_engine import iarpls as solver_iarpls
        from pybaselines.whittaker import iarpls as ref_iarpls

        y = SPECTRA[0]
        ref_bl, _ = ref_iarpls(y, lam=1e5, diff_order=3)
        sol_bl, _ = solver_iarpls(y, lam=1e5, diff_order=3)
        check_baseline_match(sol_bl, ref_bl, "iarpls/diff_order=3")


class TestDrpls:
    def test_matches_reference(self):
        from baseline_engine import drpls as solver_drpls
        from pybaselines.whittaker import drpls as ref_drpls

        for idx, y in enumerate(SPECTRA):
            ref_bl, _ = ref_drpls(y, lam=1e5, eta=0.5, diff_order=2, max_iter=50, tol=1e-3)
            sol_bl, sol_p = solver_drpls(
                y, lam=1e5, eta=0.5, diff_order=2, max_iter=50, tol=1e-3
            )
            check_baseline_match(sol_bl, ref_bl, f"drpls/spectrum_{idx}")
            assert "weights" in sol_p
            assert "tol_history" in sol_p

    def test_different_params(self):
        from baseline_engine import drpls as solver_drpls
        from pybaselines.whittaker import drpls as ref_drpls

        y = SPECTRA[0]
        for lam, eta in [(1e6, 0.3), (1e4, 0.8)]:
            ref_bl, _ = ref_drpls(y, lam=lam, eta=eta)
            sol_bl, _ = solver_drpls(y, lam=lam, eta=eta)
            check_baseline_match(sol_bl, ref_bl, f"drpls(lam={lam},eta={eta})")

    def test_diff_order_3(self):
        from baseline_engine import drpls as solver_drpls
        from pybaselines.whittaker import drpls as ref_drpls

        y = SPECTRA[1]
        ref_bl, _ = ref_drpls(y, lam=1e5, eta=0.5, diff_order=3)
        sol_bl, _ = solver_drpls(y, lam=1e5, eta=0.5, diff_order=3)
        check_baseline_match(sol_bl, ref_bl, "drpls/diff_order=3")

    def test_rejects_low_diff_order(self):
        """drpls should reject diff_order < 2, matching pybaselines behavior."""
        from baseline_engine import drpls

        y = make_spectrum_1()
        with pytest.raises(Exception):
            drpls(y, diff_order=1)

    def test_long_signal(self):
        from baseline_engine import drpls as solver_drpls
        from pybaselines.whittaker import drpls as ref_drpls

        y = SPECTRUM_LONG
        ref_bl, _ = ref_drpls(y, lam=1e5, eta=0.5)
        sol_bl, _ = solver_drpls(y, lam=1e5, eta=0.5)
        check_baseline_match(sol_bl, ref_bl, "drpls/long_signal")


class TestAspls:
    def test_matches_reference(self):
        from baseline_engine import aspls as solver_aspls
        from pybaselines.whittaker import aspls as ref_aspls

        for idx, y in enumerate(SPECTRA):
            ref_bl, ref_p = ref_aspls(
                y, lam=1e5, diff_order=2, max_iter=100, tol=1e-3, asymmetric_coef=0.5
            )
            sol_bl, sol_p = solver_aspls(
                y, lam=1e5, diff_order=2, max_iter=100, tol=1e-3, asymmetric_coef=0.5
            )
            check_baseline_match(sol_bl, ref_bl, f"aspls/spectrum_{idx}")
            assert "weights" in sol_p
            assert "tol_history" in sol_p
            assert "alpha" in sol_p
            assert sol_p["alpha"].shape == y.shape

    def test_different_coef(self):
        from baseline_engine import aspls as solver_aspls
        from pybaselines.whittaker import aspls as ref_aspls

        y = SPECTRA[1]
        for k in [0.2, 1.0]:
            ref_bl, _ = ref_aspls(y, lam=1e5, asymmetric_coef=k)
            sol_bl, _ = solver_aspls(y, lam=1e5, asymmetric_coef=k)
            check_baseline_match(sol_bl, ref_bl, f"aspls(k={k})")

    def test_long_signal(self):
        from baseline_engine import aspls as solver_aspls
        from pybaselines.whittaker import aspls as ref_aspls

        y = SPECTRUM_LONG
        ref_bl, _ = ref_aspls(y, lam=1e5)
        sol_bl, _ = solver_aspls(y, lam=1e5)
        check_baseline_match(sol_bl, ref_bl, "aspls/long_signal")

    def test_diff_order_1(self):
        from baseline_engine import aspls as solver_aspls
        from pybaselines.whittaker import aspls as ref_aspls

        y = SPECTRA[2]
        ref_bl, _ = ref_aspls(y, lam=1e5, diff_order=1)
        sol_bl, _ = solver_aspls(y, lam=1e5, diff_order=1)
        check_baseline_match(sol_bl, ref_bl, "aspls/diff_order=1")


# ---------------------------------------------------------------------------
# Tests: Convergence and return structure
# ---------------------------------------------------------------------------

class TestConvergenceProperties:
    """Verify return value structure and convergence behavior for all algorithms."""

    @pytest.mark.parametrize("algo_name", ["asls", "arpls", "iarpls", "drpls", "aspls"])
    def test_return_structure(self, algo_name):
        import baseline_engine

        func = getattr(baseline_engine, algo_name)
        y = make_spectrum_1()
        baseline, params = func(y)

        assert isinstance(baseline, np.ndarray)
        assert baseline.shape == y.shape
        assert np.all(np.isfinite(baseline))

        assert isinstance(params, dict)
        assert "weights" in params
        assert isinstance(params["weights"], np.ndarray)
        assert params["weights"].shape == y.shape
        assert np.all(np.isfinite(params["weights"]))

        assert "tol_history" in params
        assert isinstance(params["tol_history"], np.ndarray)
        assert len(params["tol_history"]) >= 1
        assert np.all(np.isfinite(params["tol_history"]))
        assert np.all(params["tol_history"] >= 0)

        if algo_name == "aspls":
            assert "alpha" in params
            assert isinstance(params["alpha"], np.ndarray)
            assert params["alpha"].shape == y.shape

    @pytest.mark.parametrize("algo_name", ["asls", "arpls", "iarpls", "drpls", "aspls"])
    def test_baseline_below_data_peaks(self, algo_name):
        """Baseline should generally be below the peak maxima of the data."""
        import baseline_engine

        func = getattr(baseline_engine, algo_name)
        y = make_spectrum_2()
        baseline, _ = func(y)

        # The maximum of the baseline should be less than the maximum of the data
        # (since the data has peaks above the baseline)
        assert np.max(baseline) < np.max(y), (
            f"{algo_name}: baseline max ({np.max(baseline):.4f}) should be "
            f"below data max ({np.max(y):.4f})"
        )


# ---------------------------------------------------------------------------
# Tests: auto_baseline
# ---------------------------------------------------------------------------

class TestAutoBaseline:
    def test_returns_valid_structure(self):
        from baseline_engine import auto_baseline

        y = make_spectrum_1()
        baseline, info = auto_baseline(y)
        assert isinstance(baseline, np.ndarray)
        assert baseline.shape == y.shape
        assert "algorithm" in info
        assert "lam" in info
        assert "score" in info
        assert info["algorithm"] in ("asls", "arpls", "iarpls", "drpls", "aspls")
        assert isinstance(info["lam"], (int, float))
        assert isinstance(info["score"], (int, float))
        assert np.isfinite(info["score"])

    def test_baseline_is_smooth(self):
        from baseline_engine import auto_baseline

        y = make_spectrum_2()
        baseline, info = auto_baseline(y)
        data_roughness = np.sum(np.diff(y, 2) ** 2)
        baseline_roughness = np.sum(np.diff(baseline, 2) ** 2)
        assert baseline_roughness < data_roughness * 0.1, (
            f"Baseline roughness ({baseline_roughness:.4f}) should be much less than "
            f"data roughness ({data_roughness:.4f})"
        )

    def test_custom_algorithms_and_lambdas(self):
        from baseline_engine import auto_baseline

        y = make_spectrum_3()
        baseline, info = auto_baseline(
            y, algorithms=["asls", "arpls"], lam_candidates=[1e4, 1e6]
        )
        assert info["algorithm"] in ("asls", "arpls")
        assert info["lam"] in (1e4, 1e6)
        assert baseline.shape == y.shape

    def test_single_algorithm(self):
        from baseline_engine import auto_baseline

        y = make_spectrum_1()
        baseline, info = auto_baseline(y, algorithms=["asls"], lam_candidates=[1e6])
        assert info["algorithm"] == "asls"
        assert info["lam"] == 1e6

    def test_default_coverage(self):
        """Default call must sweep all 5 algorithms over the default lambda grid."""
        from baseline_engine import auto_baseline

        y = make_spectrum_1()
        baseline, info = auto_baseline(y)
        assert info["algorithm"] in ("asls", "arpls", "iarpls", "drpls", "aspls")
        assert info["lam"] in (1e3, 1e4, 1e5, 1e6, 1e7)

    def test_long_signal(self):
        from baseline_engine import auto_baseline

        y = SPECTRUM_LONG
        baseline, info = auto_baseline(
            y, algorithms=["asls", "arpls"], lam_candidates=[1e5, 1e6]
        )
        assert baseline.shape == y.shape
        assert info["algorithm"] in ("asls", "arpls")
        data_roughness = np.sum(np.diff(y, 2) ** 2)
        baseline_roughness = np.sum(np.diff(baseline, 2) ** 2)
        assert baseline_roughness < data_roughness * 0.2


# ---------------------------------------------------------------------------
# Tests: no pybaselines import
# ---------------------------------------------------------------------------

class TestNoPybaselinesImport:
    def test_source_does_not_import_pybaselines(self):
        """Verify the solver implementation does not import pybaselines."""
        source_path = "/app/baseline_engine.py"
        assert os.path.isfile(source_path), f"{source_path} does not exist"

        with open(source_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "pybaselines" not in alias.name, (
                        f"baseline_engine.py must not import pybaselines (found: import {alias.name})"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module and "pybaselines" in node.module:
                    pytest.fail(
                        f"baseline_engine.py must not import from pybaselines "
                        f"(found: from {node.module} import ...)"
                    )
