"""Tests for the ZNE inference framework.

"""

import json
import math
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")


# ── Ground-truth zero-noise values for each circuit ──────────────────────
GROUND_TRUTH = {
    "A": 0.8,   # quadratic polynomial
    "B": 1.0,   # exponential decay with asymptote 0.25
    "C": 0.7,   # polynomial-exponential mix
    "D": 0.9,   # cubic polynomial
    "E": 1.0,   # fast exponential decay with asymptote 0.5
}


# ── Helper: generate known data for unit-testing factories directly ──────
def _poly2_data():
    """Quadratic polynomial: f(x) = 3 - 2x + 0.5x^2, f(0) = 3."""
    sf = [1.0, 2.0, 3.0, 4.0]
    ev = [3 - 2 * x + 0.5 * x ** 2 for x in sf]
    return sf, ev, 3.0


def _exp_data():
    """Exponential: f(x) = 0.3 + 0.7*exp(-0.5*x), f(0) = 1.0."""
    sf = [1.0, 2.0, 3.0, 4.0, 5.0]
    ev = [0.3 + 0.7 * math.exp(-0.5 * x) for x in sf]
    return sf, ev, 1.0


def _polyexp_data():
    """Poly-exp: f(x) = 0.2 + 0.8*exp(-0.3*x - 0.05*x^2), f(0) = 1.0."""
    sf = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
    ev = [0.2 + 0.8 * math.exp(-0.3 * x - 0.05 * x ** 2) for x in sf]
    return sf, ev, 1.0


# ═══════════════════════════════════════════════════════════════════════════
#  1. Individual factory tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRichardsonFactory:
    """RichardsonFactory must reproduce polynomial data exactly."""

    def test_quadratic(self):
        from zne_inference import RichardsonFactory

        sf, ev, true_val = _poly2_data()
        result = RichardsonFactory.extrapolate(sf, ev)
        assert abs(result - true_val) < 1e-8, (
            f"Richardson on quadratic data: got {result}, expected {true_val}"
        )

    def test_cubic(self):
        from zne_inference import RichardsonFactory

        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        ev = [5 - 3 * x + 0.8 * x ** 2 - 0.1 * x ** 3 for x in sf]
        true_val = 5.0
        result = RichardsonFactory.extrapolate(sf, ev)
        assert abs(result - true_val) < 1e-6, (
            f"Richardson on cubic data: got {result}, expected {true_val}"
        )

    def test_predict_at_interior_point(self):
        from zne_inference import RichardsonFactory

        sf = [1.0, 2.0, 3.0, 4.0]
        ev = [3 - 2 * x + 0.5 * x ** 2 for x in sf]
        predicted = RichardsonFactory.fit_and_predict(sf, ev, 2.5)
        true_val = 3 - 2 * 2.5 + 0.5 * 2.5 ** 2
        assert abs(predicted - true_val) < 1e-8


class TestExpFactory:
    """ExpFactory must fit exponential decay accurately."""

    def test_basic_exponential(self):
        from zne_inference import ExpFactory

        sf, ev, true_val = _exp_data()
        result = ExpFactory.extrapolate(sf, ev)
        assert abs(result - true_val) < 0.01, (
            f"ExpFactory: got {result}, expected {true_val}"
        )

    def test_predict_at_data_point(self):
        from zne_inference import ExpFactory

        sf, ev, _ = _exp_data()
        predicted = ExpFactory.fit_and_predict(sf, ev, sf[2])
        assert abs(predicted - ev[2]) < 0.01

    def test_different_parameters(self):
        from zne_inference import ExpFactory

        sf = [1.0, 2.0, 3.0, 4.0, 5.0]
        ev = [0.5 + 0.5 * math.exp(-1.0 * x) for x in sf]
        result = ExpFactory.extrapolate(sf, ev)
        assert abs(result - 1.0) < 0.01


class TestPolyExpFactory:
    """PolyExpFactory must handle polynomial-exponential noise models."""

    def test_basic_polyexp(self):
        from zne_inference import PolyExpFactory

        sf, ev, true_val = _polyexp_data()
        result = PolyExpFactory.extrapolate(sf, ev)
        assert abs(result - true_val) < 0.05, (
            f"PolyExpFactory: got {result}, expected {true_val}"
        )

    def test_reduces_to_exponential(self):
        from zne_inference import PolyExpFactory

        sf, ev, true_val = _exp_data()
        result = PolyExpFactory.extrapolate(sf, ev)
        assert abs(result - true_val) < 0.05, (
            f"PolyExpFactory on exponential data: got {result}, expected {true_val}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  2. Pipeline integration tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def pipeline_results():
    """Run the analysis pipeline and return parsed results."""
    result = subprocess.run(
        [sys.executable, "/app/analyze.py"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Pipeline failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open("/app/results.json") as f:
        return json.load(f)


class TestPipelineResults:
    """The full pipeline must produce correct extrapolated values."""

    def test_all_circuits_present(self, pipeline_results):
        for cid in GROUND_TRUTH:
            assert cid in pipeline_results, f"Missing circuit {cid}"

    def test_all_factories_attempted(self, pipeline_results):
        for cid in GROUND_TRUTH:
            fr = pipeline_results[cid]["factory_results"]
            assert "linear" in fr
            assert "richardson" in fr
            assert "exponential" in fr
            assert "poly_exponential" in fr

    # ── Extrapolation accuracy ──────────────────────────────────────────

    def test_circuit_a_accuracy(self, pipeline_results):
        val = pipeline_results["A"]["extrapolated_value"]
        assert abs(val - 0.8) < 1e-4, f"Circuit A: {val} vs 0.8"

    def test_circuit_b_accuracy(self, pipeline_results):
        val = pipeline_results["B"]["extrapolated_value"]
        assert abs(val - 1.0) < 0.02, f"Circuit B: {val} vs 1.0"

    def test_circuit_c_accuracy(self, pipeline_results):
        val = pipeline_results["C"]["extrapolated_value"]
        assert abs(val - 0.7) < 0.05, f"Circuit C: {val} vs 0.7"

    def test_circuit_d_accuracy(self, pipeline_results):
        val = pipeline_results["D"]["extrapolated_value"]
        assert abs(val - 0.9) < 1e-4, f"Circuit D: {val} vs 0.9"

    def test_circuit_e_accuracy(self, pipeline_results):
        val = pipeline_results["E"]["extrapolated_value"]
        assert abs(val - 1.0) < 0.02, f"Circuit E: {val} vs 1.0"

    # ── Richardson must be exact for polynomial data ────────────────────

    def test_richardson_exact_circuit_a(self, pipeline_results):
        val = pipeline_results["A"]["factory_results"]["richardson"]
        assert val is not None, "Richardson failed on circuit A"
        assert abs(val - 0.8) < 1e-6, f"Richardson on A: {val} vs 0.8"

    def test_richardson_exact_circuit_d(self, pipeline_results):
        val = pipeline_results["D"]["factory_results"]["richardson"]
        assert val is not None, "Richardson failed on circuit D"
        assert abs(val - 0.9) < 1e-6, f"Richardson on D: {val} vs 0.9"

    # ── Exponential must be accurate for exponential data ───────────────

    def test_exponential_accurate_circuit_b(self, pipeline_results):
        val = pipeline_results["B"]["factory_results"]["exponential"]
        assert val is not None, "ExpFactory failed on circuit B"
        assert abs(val - 1.0) < 0.01, f"Exp on B: {val} vs 1.0"

    def test_exponential_accurate_circuit_e(self, pipeline_results):
        val = pipeline_results["E"]["factory_results"]["exponential"]
        assert val is not None, "ExpFactory failed on circuit E"
        assert abs(val - 1.0) < 0.01, f"Exp on E: {val} vs 1.0"

    # ── Model selection ─────────────────────────────────────────────────

    def test_model_selection_polynomial_circuits(self, pipeline_results):
        """Richardson should be selected for polynomial-noise circuits."""
        assert pipeline_results["A"]["best_factory"] == "richardson"
        assert pipeline_results["D"]["best_factory"] == "richardson"

    def test_model_selection_exponential_circuits(self, pipeline_results):
        """An exponential-family factory should be selected for exp-decay circuits."""
        assert pipeline_results["B"]["best_factory"] in (
            "exponential",
            "poly_exponential",
        )
        assert pipeline_results["E"]["best_factory"] in (
            "exponential",
            "poly_exponential",
        )

    def test_model_selection_mixed_circuit(self, pipeline_results):
        """A non-linear factory should be selected for the mixed-noise circuit."""
        assert pipeline_results["C"]["best_factory"] in (
            "exponential",
            "poly_exponential",
            "richardson",
        )
