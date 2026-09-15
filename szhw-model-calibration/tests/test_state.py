
"""Tests for the SZHW model calibration pipeline.

Verifies Makefile targets, SQLite database, CSV output, pricer module,
calibrated parameters, and no-arbitrage bounds.
"""
import pytest
import json
import numpy as np
import sys
import os
import subprocess
import sqlite3
import csv

sys.path.insert(0, "/app")


def load_market_data():
    with open("/app/market_data.json", "r") as f:
        return json.load(f)


def load_results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Makefile tests
# ---------------------------------------------------------------------------
class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile missing"

    def test_calibrate_target(self):
        result = subprocess.run(
            ["make", "-n", "calibrate"], cwd="/app",
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Makefile must have 'calibrate' target: {result.stderr}"
        )

    def test_report_target(self):
        result = subprocess.run(
            ["make", "-n", "report"], cwd="/app",
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Makefile must have 'report' target: {result.stderr}"
        )

    def test_clean_target(self):
        result = subprocess.run(
            ["make", "-n", "clean"], cwd="/app",
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Makefile must have 'clean' target: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------
class TestDatabase:
    def test_db_exists(self):
        assert os.path.isfile("/app/calibration.db"), "calibration.db missing"

    def test_runs_table_schema(self):
        conn = sqlite3.connect("/app/calibration.db")
        cursor = conn.execute("PRAGMA table_info(runs)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {
            "id", "gamma", "sigmabar", "Rrsigma",
            "Rxsigma", "sigma0", "l2_error",
        }
        assert required.issubset(columns), (
            f"Missing columns: {required - columns}"
        )

    def test_at_least_one_run(self):
        conn = sqlite3.connect("/app/calibration.db")
        count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        conn.close()
        assert count >= 1, "Must have at least one calibration run"

    def test_best_run_error_nonneg(self):
        conn = sqlite3.connect("/app/calibration.db")
        row = conn.execute("SELECT MIN(l2_error) FROM runs").fetchone()
        conn.close()
        assert row[0] is not None and row[0] >= 0, (
            "l2_error must be non-negative"
        )


# ---------------------------------------------------------------------------
# Smile CSV tests
# ---------------------------------------------------------------------------
class TestSmileCSV:
    def test_csv_exists(self):
        assert os.path.isfile("/app/smile.csv"), "smile.csv missing"

    def test_csv_header(self):
        with open("/app/smile.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == [
            "strike", "model_price", "market_price", "implied_vol"
        ], f"Bad CSV header: {header}"

    def test_csv_row_count(self):
        market = load_market_data()
        with open("/app/smile.csv") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == len(market["strikes"]), (
            f"Expected {len(market['strikes'])} data rows, got {len(rows)}"
        )

    def test_csv_values_numeric(self):
        with open("/app/smile.csv") as f:
            reader = csv.reader(f)
            next(reader)
            for i, row in enumerate(reader):
                for j, val in enumerate(row):
                    try:
                        float(val)
                    except ValueError:
                        pytest.fail(
                            f"Non-numeric value in row {i}, col {j}: {val}"
                        )


# ---------------------------------------------------------------------------
# Results format tests
# ---------------------------------------------------------------------------
class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json missing"

    def test_calibrated_params_present(self):
        results = load_results()
        assert "calibrated_params" in results
        params = results["calibrated_params"]
        for key in ("gamma", "sigmabar", "Rrsigma", "Rxsigma", "sigma0"):
            assert key in params, f"Missing parameter: {key}"
            assert isinstance(params[key], (int, float)), f"{key} not numeric"

    def test_model_prices_length(self):
        results = load_results()
        market = load_market_data()
        assert len(results["model_call_prices"]) == len(market["strikes"])

    def test_implied_vols_length(self):
        results = load_results()
        market = load_market_data()
        assert len(results["model_implied_vols"]) == len(market["strikes"])


# ---------------------------------------------------------------------------
# Parameter bounds
# ---------------------------------------------------------------------------
class TestParameterBounds:
    def test_gamma_positive(self):
        p = load_results()["calibrated_params"]
        assert p["gamma"] > 0, "gamma must be positive"

    def test_sigmabar_positive(self):
        p = load_results()["calibrated_params"]
        assert p["sigmabar"] > 0, "sigmabar must be positive"

    def test_sigma0_positive(self):
        p = load_results()["calibrated_params"]
        assert p["sigma0"] > 0, "sigma0 must be positive"

    def test_correlations_bounded(self):
        p = load_results()["calibrated_params"]
        assert -1 < p["Rrsigma"] < 1, "Rrsigma must be in (-1,1)"
        assert -1 < p["Rxsigma"] < 1, "Rxsigma must be in (-1,1)"


# ---------------------------------------------------------------------------
# Calibration quality
# ---------------------------------------------------------------------------
class TestCalibrationQuality:
    def test_calibration_error_l2(self):
        results = load_results()
        market = load_market_data()
        model_prices = np.array(results["model_call_prices"])
        market_prices = np.array(market["call_prices"])
        error = np.linalg.norm(model_prices - market_prices)
        assert error < 2.0, (
            f"L2 calibration error {error:.4f} exceeds threshold 2.0"
        )


# ---------------------------------------------------------------------------
# Implied volatilities
# ---------------------------------------------------------------------------
class TestImpliedVolatilities:
    def test_ivs_positive(self):
        ivs = np.array(load_results()["model_implied_vols"])
        assert np.all(ivs > 0.01), "All IVs must be > 1%"

    def test_ivs_reasonable_range(self):
        ivs = np.array(load_results()["model_implied_vols"])
        assert np.all(ivs < 2.0), "All IVs must be < 200%"
        assert np.all(ivs > 0.05), "All IVs must be > 5%"


# ---------------------------------------------------------------------------
# Pricer implementation
# ---------------------------------------------------------------------------
class TestPricerImplementation:
    def test_pricer_importable(self):
        from szhw_pricer import compute_call_prices
        assert callable(compute_call_prices)

    def test_pricer_self_consistency(self):
        """Re-pricing with calibrated params must match claimed prices."""
        from szhw_pricer import compute_call_prices

        results = load_results()
        market = load_market_data()
        params = results["calibrated_params"]

        prices = compute_call_prices(
            S0=market["S0"],
            K=market["strikes"],
            T=market["T"],
            P0T=np.exp(-market["r"] * market["T"]),
            kappa=market["szhw_fixed_params"]["kappa"],
            Rxr=market["szhw_fixed_params"]["Rxr"],
            lambd=market["szhw_fixed_params"]["lambd"],
            eta=market["szhw_fixed_params"]["eta"],
            gamma=params["gamma"],
            sigmabar=params["sigmabar"],
            Rrsigma=params["Rrsigma"],
            Rxsigma=params["Rxsigma"],
            sigma0=params["sigma0"],
        )

        claimed = np.array(results["model_call_prices"])
        computed = np.array(prices).flatten()
        np.testing.assert_allclose(
            computed, claimed, rtol=1e-3,
            err_msg="Pricer output doesn't match claimed model_call_prices",
        )

    def test_pricer_out_of_sample(self):
        """Out-of-sample strikes must give positive, non-increasing prices."""
        from szhw_pricer import compute_call_prices

        results = load_results()
        market = load_market_data()
        params = results["calibrated_params"]

        K_oos = [65.0, 75.0, 85.0, 110.0, 145.0]
        prices = compute_call_prices(
            S0=market["S0"],
            K=K_oos,
            T=market["T"],
            P0T=np.exp(-market["r"] * market["T"]),
            kappa=market["szhw_fixed_params"]["kappa"],
            Rxr=market["szhw_fixed_params"]["Rxr"],
            lambd=market["szhw_fixed_params"]["lambd"],
            eta=market["szhw_fixed_params"]["eta"],
            gamma=params["gamma"],
            sigmabar=params["sigmabar"],
            Rrsigma=params["Rrsigma"],
            Rxsigma=params["Rxsigma"],
            sigma0=params["sigma0"],
        )

        prices = np.array(prices).flatten()
        assert np.all(prices > 0), "OOS call prices must be positive"
        for j in range(len(prices) - 1):
            assert prices[j] >= prices[j + 1] - 0.01, (
                f"Call prices must decrease with strike: "
                f"P(K={K_oos[j]})={prices[j]:.4f} < "
                f"P(K={K_oos[j+1]})={prices[j+1]:.4f}"
            )


# ---------------------------------------------------------------------------
# No-arbitrage bounds
# ---------------------------------------------------------------------------
class TestNoArbitrage:
    def test_call_upper_bound(self):
        results = load_results()
        market = load_market_data()
        prices = np.array(results["model_call_prices"])
        assert np.all(prices <= market["S0"] + 0.1), (
            "Call price cannot exceed S0"
        )

    def test_call_lower_bound(self):
        results = load_results()
        market = load_market_data()
        prices = np.array(results["model_call_prices"])
        K = np.array(market["strikes"])
        P0T = np.exp(-market["r"] * market["T"])
        lower = np.maximum(market["S0"] - K * P0T, 0)
        assert np.all(prices >= lower - 0.1), (
            "Call price below intrinsic value"
        )
