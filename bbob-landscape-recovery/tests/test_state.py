"""
Tests for BBOB Landscape Parameter Recovery task.
Verifies recovered parameters and standalone implementations against cocoex ground truth.
"""

import json
import sys
import os
import numpy as np
import pytest
import cocoex

D = 5
INSTANCE = 1
SEED = 42
N_TEST = 20
REL_TOL = 1e-3
ABS_TOL_FOPT = 1e-6


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def test_points():
    rng = np.random.RandomState(SEED)
    return rng.uniform(-3, 3, size=(N_TEST, D))


@pytest.fixture(scope="module")
def bbob_impl():
    sys.path.insert(0, "/app")
    import bbob_impl
    return bbob_impl


def _make_problem(fid):
    """Create a cocoex problem for the given function ID."""
    suite = cocoex.Suite(
        "bbob", "", f"function_indices: {fid} instance_indices: {INSTANCE} dimensions: {D}"
    )
    for problem in suite:
        return problem
    raise RuntimeError(f"Could not create problem f{fid}")


def _rel_error(pred, true_val):
    """Relative error with safe denominator."""
    return abs(pred - true_val) / max(abs(true_val), 1.0)


# ---- Structural checks ----


class TestStructure:
    def test_results_has_all_functions(self, results):
        for key in ["f1", "f2", "f8", "f10"]:
            assert key in results, f"Missing '{key}' in results.json"

    def test_results_fields(self, results):
        for key in ["f1", "f2", "f8", "f10"]:
            entry = results[key]
            assert "xopt" in entry, f"{key}: missing 'xopt'"
            assert "fopt" in entry, f"{key}: missing 'fopt'"
            assert "condition_number" in entry, f"{key}: missing 'condition_number'"
            assert "predictions" in entry, f"{key}: missing 'predictions'"
            assert len(entry["xopt"]) == D, f"{key}: xopt should have {D} elements"
            assert len(entry["predictions"]) == N_TEST, (
                f"{key}: predictions should have {N_TEST} elements"
            )

    def test_f10_has_rotation_matrix(self, results):
        entry = results["f10"]
        assert "rotation_matrix" in entry, "f10: missing 'rotation_matrix'"
        R = np.array(entry["rotation_matrix"])
        assert R.shape == (D, D), f"f10: rotation_matrix should be {D}x{D}"

    def test_impl_no_forbidden_imports(self):
        with open("/app/bbob_impl.py") as f:
            source = f.read()
        assert "import cocoex" not in source, "bbob_impl.py must not import cocoex"
        assert "from cocoex" not in source, "bbob_impl.py must not import cocoex"
        assert "import scipy" not in source, "bbob_impl.py must not import scipy"
        assert "from scipy" not in source, "bbob_impl.py must not import scipy"


# ---- f1 (Sphere) ----


class TestF1:
    def test_fopt_recovery(self, results):
        problem = _make_problem(1)
        entry = results["f1"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        f_at_xopt = problem(xopt)
        assert abs(f_at_xopt - fopt) < ABS_TOL_FOPT, (
            f"f1: f(xopt)={f_at_xopt}, reported fopt={fopt}"
        )

    def test_condition_number(self, results):
        cond = results["f1"]["condition_number"]
        assert 0.8 < cond < 1.2, f"f1: condition number should be ~1, got {cond}"

    def test_predictions(self, results, test_points, bbob_impl):
        problem = _make_problem(1)
        entry = results["f1"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        for i, tp in enumerate(test_points):
            pred = bbob_impl.evaluate_f1(tp, xopt, fopt)
            true_val = problem(tp)
            err = _rel_error(pred, true_val)
            assert err < REL_TOL, (
                f"f1 point {i}: pred={pred}, true={true_val}, rel_err={err}"
            )


# ---- f2 (Ellipsoidal, separable) ----


class TestF2:
    def test_fopt_recovery(self, results):
        problem = _make_problem(2)
        entry = results["f2"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        f_at_xopt = problem(xopt)
        assert abs(f_at_xopt - fopt) < ABS_TOL_FOPT, (
            f"f2: f(xopt)={f_at_xopt}, reported fopt={fopt}"
        )

    def test_condition_number(self, results):
        cond = results["f2"]["condition_number"]
        assert 1e5 < cond < 1e7, (
            f"f2: condition number should be ~1e6, got {cond}"
        )

    def test_predictions(self, results, test_points, bbob_impl):
        problem = _make_problem(2)
        entry = results["f2"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        for i, tp in enumerate(test_points):
            pred = bbob_impl.evaluate_f2(tp, xopt, fopt)
            true_val = problem(tp)
            err = _rel_error(pred, true_val)
            assert err < REL_TOL, (
                f"f2 point {i}: pred={pred}, true={true_val}, rel_err={err}"
            )


# ---- f8 (Rosenbrock) ----


class TestF8:
    def test_fopt_recovery(self, results):
        problem = _make_problem(8)
        entry = results["f8"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        f_at_xopt = problem(xopt)
        assert abs(f_at_xopt - fopt) < ABS_TOL_FOPT, (
            f"f8: f(xopt)={f_at_xopt}, reported fopt={fopt}"
        )

    def test_condition_number_positive(self, results):
        cond = results["f8"]["condition_number"]
        assert cond > 1.0, f"f8: condition number should be > 1, got {cond}"

    def test_predictions(self, results, test_points, bbob_impl):
        problem = _make_problem(8)
        entry = results["f8"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        for i, tp in enumerate(test_points):
            pred = bbob_impl.evaluate_f8(tp, xopt, fopt)
            true_val = problem(tp)
            err = _rel_error(pred, true_val)
            assert err < REL_TOL, (
                f"f8 point {i}: pred={pred}, true={true_val}, rel_err={err}"
            )


# ---- f10 (Ellipsoidal, rotated) ----


class TestF10:
    def test_fopt_recovery(self, results):
        problem = _make_problem(10)
        entry = results["f10"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        f_at_xopt = problem(xopt)
        assert abs(f_at_xopt - fopt) < ABS_TOL_FOPT, (
            f"f10: f(xopt)={f_at_xopt}, reported fopt={fopt}"
        )

    def test_condition_number(self, results):
        cond = results["f10"]["condition_number"]
        assert 1e5 < cond < 1e7, (
            f"f10: condition number should be ~1e6, got {cond}"
        )

    def test_rotation_orthogonal(self, results):
        R = np.array(results["f10"]["rotation_matrix"])
        ortho_err = np.max(np.abs(R @ R.T - np.eye(D)))
        assert ortho_err < 1e-3, (
            f"f10: rotation matrix not orthogonal, max|R R^T - I| = {ortho_err}"
        )

    def test_predictions(self, results, test_points, bbob_impl):
        problem = _make_problem(10)
        entry = results["f10"]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        R = np.array(entry["rotation_matrix"])
        for i, tp in enumerate(test_points):
            pred = bbob_impl.evaluate_f10(tp, xopt, fopt, R)
            true_val = problem(tp)
            err = _rel_error(pred, true_val)
            assert err < REL_TOL, (
                f"f10 point {i}: pred={pred}, true={true_val}, rel_err={err}"
            )


# ---- Cross-check: stored predictions match bbob_impl ----


class TestPredictionConsistency:
    @pytest.mark.parametrize("fid", [1, 2, 8, 10])
    def test_stored_vs_computed(self, fid, results, test_points, bbob_impl):
        key = f"f{fid}"
        entry = results[key]
        xopt = np.array(entry["xopt"])
        fopt = entry["fopt"]
        preds_stored = entry["predictions"]

        for i, tp in enumerate(test_points):
            if fid == 1:
                pred = bbob_impl.evaluate_f1(tp, xopt, fopt)
            elif fid == 2:
                pred = bbob_impl.evaluate_f2(tp, xopt, fopt)
            elif fid == 8:
                pred = bbob_impl.evaluate_f8(tp, xopt, fopt)
            elif fid == 10:
                R = np.array(entry["rotation_matrix"])
                pred = bbob_impl.evaluate_f10(tp, xopt, fopt, R)

            assert abs(pred - preds_stored[i]) < 1e-6, (
                f"{key} prediction {i}: stored={preds_stored[i]}, computed={pred}"
            )
