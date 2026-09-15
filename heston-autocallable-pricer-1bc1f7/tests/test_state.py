"""
Tests for the derivatives pricing engine and pipeline.
"""

import subprocess
import json
import os
import tempfile
import numpy as np
import pytest


def run_pricer(*args):
    """Run the pricer CLI and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/pricer.py"] + list(args),
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        pytest.fail(f"pricer exited with code {result.returncode}:\nstdout: {result.stdout}\nstderr: {result.stderr}")
    output = result.stdout.strip()
    return json.loads(output)


def run_autocallable(config):
    """Helper to run the autocallable subcommand with a config dict."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_file = f.name
    try:
        return run_pricer("autocallable", "--config", config_file)
    finally:
        os.unlink(config_file)


# =============================================================================
# HESTON ANALYTICAL PRICING TESTS
# =============================================================================

class TestHestonCall:
    """Tests for the Heston semi-analytical European call pricer."""

    HESTON_PARAMS = {
        "spot": 1.0, "rate": 0.03, "maturity": 7.0,
        "v0": 0.1, "theta": 0.15, "kappa": 3.0,
        "sigma": 0.2, "rho": -0.2, "div_yield": 0.0,
    }
    REFERENCE_PRICES = [
        (0.25, 0.8081),
        (0.50, 0.6564),
        (0.75, 0.5412),
        (1.00, 0.4527),
        (1.25, 0.3833),
        (1.50, 0.3281),
        (1.75, 0.2834),
    ]

    def _call_heston(self, strike, **overrides):
        params = {**self.HESTON_PARAMS, **overrides}
        return run_pricer(
            "heston-call",
            "--spot", str(params["spot"]),
            "--strike", str(strike),
            "--rate", str(params["rate"]),
            "--maturity", str(params["maturity"]),
            "--v0", str(params["v0"]),
            "--theta", str(params["theta"]),
            "--kappa", str(params["kappa"]),
            "--sigma", str(params["sigma"]),
            "--rho", str(params["rho"]),
            "--div-yield", str(params["div_yield"]),
        )

    def test_reference_values(self):
        """Verify analytical Heston prices match known reference values."""
        for strike, expected in self.REFERENCE_PRICES:
            result = self._call_heston(strike)
            assert "price" in result, f"Missing 'price' key for strike {strike}"
            got = result["price"]
            assert abs(got - expected) < 5e-3, (
                f"Strike {strike}: got {got:.6f}, expected {expected:.4f}, "
                f"diff {abs(got - expected):.6f}"
            )

    def test_deep_itm(self):
        """Deep ITM call should approach S*exp(-qT) - K*exp(-rT)."""
        result = self._call_heston(
            0.01, spot=100.0, rate=0.05, maturity=1.0,
            v0=0.04, theta=0.04, kappa=2.0, sigma=0.3, rho=-0.5, div_yield=0.0
        )
        intrinsic_fwd = 100.0 - 0.01 * np.exp(-0.05)
        assert result["price"] > intrinsic_fwd * 0.99

    def test_deep_otm(self):
        """Deep OTM call should be near zero but non-negative."""
        result = self._call_heston(
            500.0, spot=100.0, rate=0.05, maturity=1.0,
            v0=0.04, theta=0.04, kappa=2.0, sigma=0.3, rho=-0.5, div_yield=0.0
        )
        assert result["price"] >= 0.0
        assert result["price"] < 1.0

    def test_long_maturity_no_overflow(self):
        """30-year maturity must not cause overflow or discontinuities."""
        result = self._call_heston(
            100.0, spot=100.0, rate=0.03, maturity=30.0,
            v0=0.04, theta=0.04, kappa=1.5, sigma=0.3, rho=-0.6, div_yield=0.01
        )
        assert 0.0 < result["price"] < 100.0
        assert result["price"] > 15.0

    def test_short_maturity(self):
        """10-day maturity ATM call should be positive and bounded."""
        result = self._call_heston(
            100.0, spot=100.0, rate=0.05, maturity=10.0 / 365.0,
            v0=0.04, theta=0.04, kappa=2.0, sigma=0.3, rho=-0.7, div_yield=0.0
        )
        assert 0.0 < result["price"] < 10.0

    def test_medium_maturity_stability(self):
        """15-year maturity with high vol-of-vol must produce stable results."""
        result = self._call_heston(
            100.0, spot=100.0, rate=0.03, maturity=15.0,
            v0=0.04, theta=0.06, kappa=2.0, sigma=0.4, rho=-0.7, div_yield=0.01
        )
        price = result["price"]
        assert not np.isnan(price), "NaN price at 15-year maturity"
        assert not np.isinf(price), "Inf price at 15-year maturity"
        assert 5.0 < price < 80.0, f"Price {price} out of range for 15y ATM call"

    def test_call_price_monotonicity(self):
        """Call price must be strictly decreasing in strike."""
        prices = []
        for K in [80, 90, 100, 110, 120]:
            result = self._call_heston(
                K, spot=100.0, rate=0.05, maturity=2.0,
                v0=0.04, theta=0.04, kappa=2.0, sigma=0.3, rho=-0.5, div_yield=0.0
            )
            prices.append(result["price"])
        for i in range(len(prices) - 1):
            assert prices[i] > prices[i + 1], (
                f"Not monotonically decreasing: C({80 + i * 10}) = {prices[i]:.4f} "
                f"<= C({90 + i * 10}) = {prices[i + 1]:.4f}"
            )


# =============================================================================
# CORRELATION MATRIX CLEANING TESTS
# =============================================================================

class TestCleanCorr:
    """Tests for the correlation matrix repair subcommand."""

    def _run_clean(self, matrix):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as fin:
            json.dump(matrix, fin)
            input_file = fin.name
        output_file = input_file + ".cleaned.json"
        try:
            result = run_pricer("clean-corr", "--input-file", input_file, "--output-file", output_file)
            with open(output_file) as fout:
                cleaned = json.load(fout)
            return result, np.array(cleaned)
        finally:
            os.unlink(input_file)
            if os.path.exists(output_file):
                os.unlink(output_file)

    def test_non_psd_matrix(self):
        """Clean the known non-PSD matrix with eigenvalues {2, 2, -1}."""
        matrix = [[1, 1, -1], [1, 1, 1], [-1, 1, 1]]
        result, cleaned = self._run_clean(matrix)

        assert result["is_psd_before"] is False
        assert result["is_psd_after"] is True
        assert result["max_abs_eigenvalue_change"] > 0.9

        assert np.allclose(np.diag(cleaned), 1.0, atol=1e-10)
        assert np.allclose(cleaned, cleaned.T, atol=1e-10)
        eigenvalues = np.linalg.eigvalsh(cleaned)
        assert np.all(eigenvalues >= -1e-10)
        assert np.all(np.abs(cleaned) <= 1.0 + 1e-10)

    def test_already_psd_unchanged(self):
        """A valid PSD correlation matrix should pass through unchanged."""
        matrix = [[1.0, 0.5, 0.3], [0.5, 1.0, 0.4], [0.3, 0.4, 1.0]]
        result, cleaned = self._run_clean(matrix)

        assert result["is_psd_before"] is True
        assert result["is_psd_after"] is True
        assert abs(result["max_abs_eigenvalue_change"]) < 1e-10
        assert np.allclose(cleaned, np.array(matrix), atol=1e-10)

    def test_large_non_psd_matrix(self):
        """Clean a 5x5 non-PSD matrix and verify output properties."""
        matrix = [
            [1.0, 0.9, 0.7, -0.8, 0.3],
            [0.9, 1.0, 0.5, -0.6, 0.4],
            [0.7, 0.5, 1.0, -0.9, 0.8],
            [-0.8, -0.6, -0.9, 1.0, -0.5],
            [0.3, 0.4, 0.8, -0.5, 1.0],
        ]
        result, cleaned = self._run_clean(matrix)

        assert result["is_psd_after"] is True
        assert np.allclose(np.diag(cleaned), 1.0, atol=1e-10)
        assert np.allclose(cleaned, cleaned.T, atol=1e-10)
        eigenvalues = np.linalg.eigvalsh(cleaned)
        assert np.all(eigenvalues >= -1e-10)

    def test_cleaning_preserves_structure(self):
        """Cleaned matrix must have all off-diagonal elements in [-1, 1]."""
        matrix = [
            [1.0, 0.95, 0.95],
            [0.95, 1.0, -0.95],
            [0.95, -0.95, 1.0],
        ]
        result, cleaned = self._run_clean(matrix)

        assert result["is_psd_after"] is True
        n = cleaned.shape[0]
        for i in range(n):
            for j in range(n):
                assert -1.0 - 1e-10 <= cleaned[i, j] <= 1.0 + 1e-10, (
                    f"Element [{i},{j}] = {cleaned[i, j]} out of [-1, 1]"
                )


# =============================================================================
# AUTOCALLABLE PRICING TESTS
# =============================================================================

class TestAutocallable:
    """Tests for the worst-of multi-asset autocallable pricer."""

    def _base_config(self, **overrides):
        config = {
            "assets": [
                {"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2.0,
                 "sigma": 0.3, "rho": -0.5, "div_yield": 0.02}
            ],
            "correlation_matrix": [[1.0]],
            "observation_times": [1.0, 2.0, 3.0],
            "autocall_barrier": 1.05,
            "coupon_barrier": 0.7,
            "coupon_rate": 0.10,
            "knock_in_barrier": None,
            "snowball": False,
            "notional": 1000.0,
            "risk_free_rate": 0.05,
            "n_paths": 50000,
            "n_steps_per_year": 52,
            "seed": 42,
        }
        config.update(overrides)
        return config

    def test_output_structure(self):
        """Verify the autocallable output has the correct structure."""
        config = self._base_config()
        result = run_autocallable(config)

        assert "price" in result
        assert "std_error" in result
        assert "autocall_prob" in result
        assert "expected_coupon_count" in result

        assert isinstance(result["price"], (int, float))
        assert isinstance(result["std_error"], (int, float))
        assert isinstance(result["autocall_prob"], list)
        assert len(result["autocall_prob"]) == 3
        assert isinstance(result["expected_coupon_count"], (int, float))

    def test_basic_bounds(self):
        """Price and statistics should be within reasonable bounds."""
        config = self._base_config()
        result = run_autocallable(config)

        assert result["price"] > 0
        assert result["std_error"] > 0
        assert result["std_error"] < result["price"] * 0.1

        assert sum(result["autocall_prob"]) <= 1.0 + 1e-6
        assert all(p >= -1e-10 for p in result["autocall_prob"])

        assert 0 <= result["expected_coupon_count"] <= 3.0

    def test_certain_autocall_at_first_obs(self):
        """Near-zero vol with very low autocall barrier -> autocall at first observation."""
        config = self._base_config(
            assets=[{"spot": 100, "v0": 1e-6, "theta": 1e-6, "kappa": 10,
                     "sigma": 0.001, "rho": -0.1, "div_yield": 0.0}],
            observation_times=[1.0, 2.0],
            autocall_barrier=0.5,
            coupon_barrier=0.5,
            coupon_rate=0.10,
            knock_in_barrier=None,
            snowball=False,
            risk_free_rate=0.05,
            n_paths=10000,
            n_steps_per_year=12,
            seed=123,
        )
        result = run_autocallable(config)

        assert result["autocall_prob"][0] > 0.99
        assert abs(result["price"] - 1.0465) < 0.02

    def test_no_autocall_all_coupons(self):
        """Very high autocall barrier -> no autocall, all coupons earned."""
        config = self._base_config(
            assets=[{"spot": 100, "v0": 1e-6, "theta": 1e-6, "kappa": 10,
                     "sigma": 0.001, "rho": -0.1, "div_yield": 0.0}],
            observation_times=[1.0, 2.0],
            autocall_barrier=5.0,
            coupon_barrier=0.5,
            coupon_rate=0.10,
            knock_in_barrier=None,
            snowball=False,
            risk_free_rate=0.05,
            n_paths=10000,
            n_steps_per_year=12,
            seed=123,
        )
        result = run_autocallable(config)

        assert sum(result["autocall_prob"]) < 0.01
        assert abs(result["price"] - 1.0904) < 0.02
        assert abs(result["expected_coupon_count"] - 2.0) < 0.1

    def test_multi_asset_worst_of(self):
        """Multi-asset worst-of autocallable should produce valid output."""
        config = self._base_config(
            assets=[
                {"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2,
                 "sigma": 0.3, "rho": -0.5, "div_yield": 0.02},
                {"spot": 50, "v0": 0.06, "theta": 0.05, "kappa": 1.5,
                 "sigma": 0.4, "rho": -0.6, "div_yield": 0.01},
            ],
            correlation_matrix=[[1.0, 0.6], [0.6, 1.0]],
            observation_times=[1.0, 2.0, 3.0],
            n_paths=30000,
            seed=42,
        )
        result = run_autocallable(config)

        assert result["price"] > 0
        assert len(result["autocall_prob"]) == 3
        assert sum(result["autocall_prob"]) <= 1.0 + 1e-6

    def test_knock_in_reduces_value(self):
        """Knock-in put should reduce the note's value vs. no knock-in."""
        base = dict(
            assets=[{"spot": 100, "v0": 0.09, "theta": 0.09, "kappa": 1.5,
                     "sigma": 0.5, "rho": -0.7, "div_yield": 0.0}],
            correlation_matrix=[[1.0]],
            observation_times=[1.0, 2.0, 3.0],
            autocall_barrier=5.0,
            coupon_barrier=0.3,
            coupon_rate=0.10,
            snowball=False,
            notional=1000.0,
            risk_free_rate=0.05,
            n_paths=50000,
            n_steps_per_year=52,
            seed=42,
        )

        result_ki = run_autocallable({**base, "knock_in_barrier": 0.8})
        result_no_ki = run_autocallable({**base, "knock_in_barrier": None})

        assert result_ki["price"] < result_no_ki["price"]

    def test_snowball_increases_value(self):
        """Snowball coupons should increase value vs. non-snowball."""
        base = dict(
            assets=[{"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2,
                     "sigma": 0.3, "rho": -0.5, "div_yield": 0.02}],
            correlation_matrix=[[1.0]],
            observation_times=[1.0, 2.0, 3.0, 4.0],
            autocall_barrier=1.05,
            coupon_barrier=1.0,
            coupon_rate=0.15,
            knock_in_barrier=None,
            notional=1000.0,
            risk_free_rate=0.05,
            n_paths=50000,
            n_steps_per_year=52,
            seed=42,
        )

        result_no_sb = run_autocallable({**base, "snowball": False})
        result_sb = run_autocallable({**base, "snowball": True})

        assert result_sb["price"] > result_no_sb["price"], (
            f"Snowball price {result_sb['price']:.4f} should exceed "
            f"non-snowball price {result_no_sb['price']:.4f}"
        )

    def test_non_psd_correlation_handled(self):
        """Pricer should handle non-PSD equity correlation matrices gracefully."""
        config = self._base_config(
            assets=[
                {"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2,
                 "sigma": 0.3, "rho": -0.5, "div_yield": 0.02},
                {"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2,
                 "sigma": 0.3, "rho": -0.5, "div_yield": 0.02},
                {"spot": 100, "v0": 0.04, "theta": 0.04, "kappa": 2,
                 "sigma": 0.3, "rho": -0.5, "div_yield": 0.02},
            ],
            correlation_matrix=[[1, 1, -1], [1, 1, 1], [-1, 1, 1]],
            observation_times=[1.0, 2.0],
            n_paths=10000,
            n_steps_per_year=12,
            seed=42,
        )
        result = run_autocallable(config)

        assert result["price"] > 0
        assert len(result["autocall_prob"]) == 2
        assert sum(result["autocall_prob"]) <= 1.0 + 1e-6

    def test_snowball_coupon_accumulation(self):
        """Snowball must accumulate missed coupons and pay them at next eligible date."""
        config = {
            "assets": [{"spot": 100, "v0": 1e-6, "theta": 1e-6, "kappa": 10,
                         "sigma": 0.001, "rho": -0.1, "div_yield": 0.0}],
            "correlation_matrix": [[1.0]],
            "observation_times": [0.5, 1.0, 1.5],
            "autocall_barrier": 5.0,
            "coupon_barrier": 1.03,
            "coupon_rate": 0.10,
            "knock_in_barrier": None,
            "snowball": True,
            "notional": 1000.0,
            "risk_free_rate": 0.05,
            "n_paths": 10000,
            "n_steps_per_year": 12,
            "seed": 42,
        }
        result_sb = run_autocallable(config)

        assert abs(result_sb["expected_coupon_count"] - 3.0) < 0.15, (
            f"Snowball expected_coupon_count = {result_sb['expected_coupon_count']:.2f}, "
            f"expected ~3.0"
        )

        config["snowball"] = False
        result_no = run_autocallable(config)
        assert abs(result_no["expected_coupon_count"] - 2.0) < 0.15, (
            f"Non-snowball expected_coupon_count = {result_no['expected_coupon_count']:.2f}, "
            f"expected ~2.0"
        )

        price_diff = result_sb["price"] - result_no["price"]
        assert price_diff > 0.05, (
            f"Snowball price diff = {price_diff:.4f}, expected > 0.05"
        )

    def test_knockin_continuous_monitoring(self):
        """Knock-in must be monitored at every simulation step, not just observation dates."""
        base = {
            "assets": [{"spot": 100, "v0": 0.09, "theta": 0.09, "kappa": 1.5,
                         "sigma": 0.4, "rho": -0.7, "div_yield": 0.0}],
            "correlation_matrix": [[1.0]],
            "observation_times": [3.0],
            "autocall_barrier": 10.0,
            "coupon_barrier": 0.01,
            "coupon_rate": 0.0,
            "snowball": False,
            "notional": 1000.0,
            "risk_free_rate": 0.0,
            "n_paths": 80000,
            "n_steps_per_year": 52,
            "seed": 42,
        }

        result_no_ki = run_autocallable({**base, "knock_in_barrier": None})
        result_ki = run_autocallable({**base, "knock_in_barrier": 0.5})

        impact = result_no_ki["price"] - result_ki["price"]
        assert impact > 0.13, (
            f"Knock-in impact at 0.5 barrier = {impact:.4f}. Expected > 0.13 "
            f"with continuous monitoring over 156 simulation steps. "
            f"Verify knock-in is checked at every timestep."
        )


# =============================================================================
# PIPELINE TESTS (Make + SQLite + jq interoperability)
# =============================================================================

class TestPipeline:
    """Tests for the Make/SQLite/jq pricing pipeline."""

    @classmethod
    def setup_class(cls):
        """Run make all once before all pipeline tests."""
        # Remove any previous pipeline artifacts to ensure clean run
        for f in ["/app/pricing.db", "/app/report.txt", "/app/data/correlation_cleaned.json"]:
            if os.path.exists(f):
                os.unlink(f)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=300
        )
        cls.make_rc = result.returncode
        cls.make_stdout = result.stdout
        cls.make_stderr = result.stderr

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_all_succeeds(self):
        """make all must complete successfully."""
        assert self.make_rc == 0, (
            f"make all failed with exit code {self.make_rc}:\n"
            f"stdout: {self.make_stdout}\nstderr: {self.make_stderr}"
        )

    def test_database_schema(self):
        """pricing.db must exist with correct tables."""
        db_path = "/app/pricing.db"
        assert os.path.exists(db_path), "pricing.db not found"
        result = subprocess.run(
            ["sqlite3", db_path, ".tables"],
            capture_output=True, text=True
        )
        assert "heston_results" in result.stdout, (
            f"heston_results table not found. Tables: {result.stdout}"
        )
        assert "autocall_results" in result.stdout, (
            f"autocall_results table not found. Tables: {result.stdout}"
        )

    def test_heston_results_count(self):
        """heston_results table must have exactly 7 rows (one per CSV row)."""
        result = subprocess.run(
            ["sqlite3", "/app/pricing.db", "SELECT COUNT(*) FROM heston_results;"],
            capture_output=True, text=True
        )
        count = int(result.stdout.strip())
        assert count == 7, f"Expected 7 heston_results rows, got {count}"

    def test_calibration_accuracy_in_db(self):
        """Maximum absolute calibration error stored in DB must be < 5e-3."""
        result = subprocess.run(
            ["sqlite3", "/app/pricing.db", "SELECT MAX(abs_error) FROM heston_results;"],
            capture_output=True, text=True
        )
        max_err = float(result.stdout.strip())
        assert max_err < 5e-3, f"Max calibration error in DB is {max_err:.6f}, must be < 0.005"

    def test_autocall_results_populated(self):
        """autocall_results must have at least one pricing result."""
        result = subprocess.run(
            ["sqlite3", "/app/pricing.db", "SELECT COUNT(*) FROM autocall_results;"],
            capture_output=True, text=True
        )
        count = int(result.stdout.strip())
        assert count >= 1, f"Expected >= 1 autocall_results row, got {count}"

    def test_autocall_price_reasonable(self):
        """Autocallable price stored in DB must be in a reasonable range."""
        result = subprocess.run(
            ["sqlite3", "/app/pricing.db",
             "SELECT price FROM autocall_results LIMIT 1;"],
            capture_output=True, text=True
        )
        price = float(result.stdout.strip())
        assert 0.5 < price < 1.5, (
            f"Autocallable price {price:.6f} outside reasonable range [0.5, 1.5]"
        )

    def test_autocall_prob_stored_as_json(self):
        """autocall_prob_json column must contain valid JSON array."""
        result = subprocess.run(
            ["sqlite3", "/app/pricing.db",
             "SELECT autocall_prob_json FROM autocall_results LIMIT 1;"],
            capture_output=True, text=True
        )
        probs = json.loads(result.stdout.strip())
        assert isinstance(probs, list), "autocall_prob_json must be a JSON array"
        assert len(probs) == 3, f"Expected 3 autocall probabilities, got {len(probs)}"

    def test_report_file_content(self):
        """report.txt must exist and contain calibration and pricing data."""
        report_path = "/app/report.txt"
        assert os.path.exists(report_path), "report.txt not found at /app/report.txt"
        with open(report_path) as f:
            content = f.read()
        assert len(content) > 50, f"Report too short ({len(content)} chars)"
        content_lower = content.lower()
        assert "max_error" in content_lower or "max" in content_lower, (
            "Report must contain max calibration error"
        )
        assert "mean_error" in content_lower or "mean" in content_lower, (
            "Report must contain mean calibration error"
        )
        assert "price" in content_lower, "Report must contain pricing results"

    def test_cleaned_correlation_output(self):
        """Cleaned correlation file must exist and be valid PSD."""
        path = "/app/data/correlation_cleaned.json"
        assert os.path.exists(path), "correlation_cleaned.json not found"
        with open(path) as f:
            matrix = json.load(f)
        M = np.array(matrix)
        eigenvalues = np.linalg.eigvalsh(M)
        assert np.all(eigenvalues >= -1e-10), (
            f"Cleaned correlation not PSD, min eigenvalue: {eigenvalues.min()}"
        )
        assert np.allclose(np.diag(M), 1.0, atol=1e-10), "Diagonal must be 1.0"

    def test_makefile_uses_jq(self):
        """Makefile must use jq for JSON field extraction."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "jq" in content, "Makefile must use jq for JSON processing"

    def test_makefile_uses_sqlite3(self):
        """Makefile must use sqlite3 for database operations."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "sqlite3" in content, "Makefile must use sqlite3 for database operations"

    def test_makefile_has_required_targets(self):
        """Makefile must define all required targets."""
        with open("/app/Makefile") as f:
            content = f.read()
        for target in ["db-init", "calibrate", "clean", "price-note", "report", "all"]:
            assert target in content, f"Required target '{target}' not found in Makefile"
