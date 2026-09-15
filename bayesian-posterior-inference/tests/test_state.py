"""
Tests for Bayesian posterior inference benchmark.
Verifies posterior mean estimates against high-accuracy reference posteriors
using a z-score accuracy criterion.

Reference values are stored in compressed form and decoded at runtime.
"""


import pytest
import os
import json
import zlib
import base64
import glob

Z_THRESHOLD = 0.25

# Compressed reference posteriors (zlib + base64).
# Decoded at runtime — not human-readable in source.
_REFERENCE_BLOB = (
    "eNplU+2K2zAQfBf/VoW03+qrGBN8vZAEEnIkLvQofffblXNNSPAPgWZmZ3ZX"
    "/jtsD7v9srn+2p/Px+vwcxyH0+8hUcbGmDBj5SmNwzL7JWZu2vwAYOm3++0y"
    "b5bD8X071mlIxeli7GezJvpMgU4pTaF1DjZ5KYPO+eEkYxYLkvj3TKK1kFSB"
    "FhwifSnEa6EqhVezQvzMkZuZVmXthRjwmaRrY8wGQeGXNLamURLsDG/v3nqf"
    "i2SopIl9fo3uUMyD3LRWP8TKgyrGgLkBkqtASr1D1FXKaHHYQ+DeM2apgFGQ"
    "8QGSripUwst8AXdI14TNnYrKA2BdY9QzmLZpSsPuY3PZ7i79oVz251Bag5qq"
    "M6ynnI8f+3lIkAkVfR5qDXvR62F3cqBmwxKr5ah3Pay13twwsFJjhoWgIYRo"
    "N59C5Its8fYcKiZofd1/Dq7wOiRhEy8vbt+3x2VeVyY1AhTgW7+fI6fYh1bz"
    "2Ilavq3qc6ylIyTkHScFV8kNWTVU1EMk5ax6Q2DVYDPNJalkb/jbJnbLBbNS"
    "Aspk/N8mEADLmCr7/9K+FbHXSiQeOHGjDHdJQCpY3R/U803Tvy9pXvSA"
)


def _load_reference():
    """Decode compressed reference posteriors."""
    raw = zlib.decompress(base64.b64decode(_REFERENCE_BLOB))
    return json.loads(raw)


def parse_fit_file(filepath):
    """Parse a .fit file: param_name estimated_mean per line."""
    results = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            results[parts[0]] = float(parts[1])
    return results


def evaluate_z_scores(fit_path, ground_truth):
    """Compute z-scores against reference posteriors."""
    results = parse_fit_file(fit_path)
    z_scores = {}
    missing = []
    for item in ground_truth:
        name, true_mean, true_std = item[0], item[1], item[2]
        if name not in results:
            missing.append(name)
            continue
        est_mean = results[name]
        z = abs(true_mean - est_mean) / true_std
        z_scores[name] = z
    return z_scores, missing


# ---- Verify solution contains actual inference code ----

class TestInferenceCode:
    """Anti-shortcut: verify Python inference code exists in /app."""

    def test_python_source_exists(self):
        py_files = glob.glob("/app/**/*.py", recursive=True)
        assert len(py_files) >= 1, "No Python source files found in /app"

    def test_code_implements_sampling(self):
        py_files = glob.glob("/app/**/*.py", recursive=True)
        all_code = ""
        for fpath in py_files:
            with open(fpath) as fh:
                all_code += fh.read().lower()
        markers = [
            "log", "sample", "accept", "propos",
            "posterior", "density", "mcmc", "metropolis",
            "chain", "warmup", "burn",
        ]
        found = [m for m in markers if m in all_code]
        assert len(found) >= 4, (
            f"Solution lacks inference logic. Found only: {found}"
        )

    def test_code_uses_numerical_libs(self):
        py_files = glob.glob("/app/**/*.py", recursive=True)
        all_code = ""
        for fpath in py_files:
            with open(fpath) as fh:
                all_code += fh.read().lower()
        numerical = ["numpy", "np.", "scipy", "linalg", "np.exp", "np.log"]
        found = [m for m in numerical if m in all_code]
        assert len(found) >= 2, (
            f"Solution lacks numerical computation. Found only: {found}"
        )


# ---- Eight Schools ----

class TestEightSchools:
    fit_path = "/app/results/eight_schools.fit"

    def test_results_file_exists(self):
        assert os.path.exists(self.fit_path), (
            f"Results file {self.fit_path} does not exist"
        )

    def test_results_file_not_empty(self):
        assert os.path.getsize(self.fit_path) > 0, (
            f"Results file {self.fit_path} is empty"
        )

    def test_all_parameters_present(self):
        results = parse_fit_file(self.fit_path)
        ref = _load_reference()["eight_schools"]
        expected = [item[0] for item in ref]
        missing = [name for name in expected if name not in results]
        assert not missing, f"Missing parameters: {missing}"

    def test_z_scores_below_threshold(self):
        ref = _load_reference()["eight_schools"]
        z_scores, missing = evaluate_z_scores(self.fit_path, ref)
        assert not missing, f"Missing parameters: {missing}"
        failures = {k: v for k, v in z_scores.items() if v >= Z_THRESHOLD}
        assert not failures, (
            f"Parameters with z-score >= {Z_THRESHOLD}: "
            + ", ".join(f"{k}={v:.4f}" for k, v in sorted(failures.items()))
        )


# ---- GP Regression ----

class TestGPRegr:
    fit_path = "/app/results/gp_regr.fit"

    def test_results_file_exists(self):
        assert os.path.exists(self.fit_path), (
            f"Results file {self.fit_path} does not exist"
        )

    def test_results_file_not_empty(self):
        assert os.path.getsize(self.fit_path) > 0, (
            f"Results file {self.fit_path} is empty"
        )

    def test_all_parameters_present(self):
        results = parse_fit_file(self.fit_path)
        ref = _load_reference()["gp_regr"]
        expected = [item[0] for item in ref]
        missing = [name for name in expected if name not in results]
        assert not missing, f"Missing parameters: {missing}"

    def test_z_scores_below_threshold(self):
        ref = _load_reference()["gp_regr"]
        z_scores, missing = evaluate_z_scores(self.fit_path, ref)
        assert not missing, f"Missing parameters: {missing}"
        failures = {k: v for k, v in z_scores.items() if v >= Z_THRESHOLD}
        assert not failures, (
            f"Parameters with z-score >= {Z_THRESHOLD}: "
            + ", ".join(f"{k}={v:.4f}" for k, v in sorted(failures.items()))
        )


# ---- SIR Epidemic Model ----

class TestSIR:
    fit_path = "/app/results/sir.fit"

    def test_results_file_exists(self):
        assert os.path.exists(self.fit_path), (
            f"Results file {self.fit_path} does not exist"
        )

    def test_results_file_not_empty(self):
        assert os.path.getsize(self.fit_path) > 0, (
            f"Results file {self.fit_path} is empty"
        )

    def test_base_parameters_present(self):
        results = parse_fit_file(self.fit_path)
        for name in ["beta", "gamma", "xi", "delta"]:
            assert name in results, f"Missing base parameter: {name}"

    def test_all_transformed_parameters_present(self):
        """All 80 ODE-derived y[t,k] values must be reported."""
        results = parse_fit_file(self.fit_path)
        missing = []
        for t in range(1, 21):
            for k in range(1, 5):
                name = f"y[{t},{k}]"
                if name not in results:
                    missing.append(name)
        assert not missing, (
            f"Missing {len(missing)} transformed parameters, "
            f"first 5: {missing[:5]}"
        )

    def test_z_scores_below_threshold(self):
        ref = _load_reference()["sir"]
        z_scores, missing = evaluate_z_scores(self.fit_path, ref)
        assert not missing, f"Missing parameters: {missing}"
        failures = {k: v for k, v in z_scores.items() if v >= Z_THRESHOLD}
        assert not failures, (
            f"Parameters with z-score >= {Z_THRESHOLD}: "
            + ", ".join(f"{k}={v:.4f}" for k, v in sorted(failures.items()))
        )
