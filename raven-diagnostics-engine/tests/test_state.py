"""
Tests for Raven-compatible hydrological diagnostic calculator.
Verifies /app/raven_diag.py backed by /app/libdiag.so against reference implementation.
"""


import pytest
import json
import csv
import math
import os
import subprocess
import tempfile
import sys

sys.path.insert(0, '/tests')
from reference_impl import compute_baseweights, compute_metric, ALMOST_INF

BLANK_VALUE = -1.2345
TOOL = "/app/raven_diag.py"
TOL = 1e-8


def generate_basic_data(n=365):
    """Generate deterministic sinusoidal hydro time series."""
    observed = []
    modeled = []
    for i in range(n):
        obs = 50.0 + 30.0 * math.sin(2 * math.pi * i / 365.0) + 10.0 * math.sin(2 * math.pi * i / 30.0)
        mod = obs * 1.03 + 2.0 * math.cos(2 * math.pi * i / 60.0) + 1.5
        observed.append(obs)
        modeled.append(mod)
    return observed, modeled


def generate_positive_data(n=365):
    """Generate data guaranteed positive (needed for LOG_NASH, RTRMSE, MBF)."""
    observed = []
    modeled = []
    for i in range(n):
        obs = 100.0 + 40.0 * math.sin(2 * math.pi * i / 365.0) + 15.0 * math.sin(2 * math.pi * i / 30.0)
        mod = obs * 1.02 + 3.0 * math.cos(2 * math.pi * i / 60.0) + 1.0
        observed.append(obs)
        modeled.append(mod)
    return observed, modeled


def run_tool(metrics, observed, modeled, weights=None,
             start_date="2000-01-01", timestep=1.0,
             threshold=0.0, comparison="NONE"):
    """Run raven_diag.py and return parsed JSON output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.json")
        data_path = os.path.join(tmpdir, "data.csv")

        config = {
            "metrics": metrics,
            "start_date": start_date,
            "timestep": timestep,
            "blank_value": BLANK_VALUE,
            "threshold": threshold,
            "comparison": comparison
        }
        with open(config_path, 'w') as f:
            json.dump(config, f)

        with open(data_path, 'w') as f:
            writer = csv.writer(f)
            for i in range(len(observed)):
                row = [i, observed[i], modeled[i]]
                if weights:
                    row.append(weights[i])
                writer.writerow(row)

        result = subprocess.run(
            ["python3", TOOL, "--config", config_path, "--data", data_path],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"Tool failed with stderr: {result.stderr[:500]}"

        output = result.stdout.strip()
        return json.loads(output)


def ref_value(name, width, obs, mod, bw, dt=1.0, start_date="2000-01-01"):
    """Compute reference value for a metric."""
    return compute_metric(name, width, obs, mod, bw, 0, len(obs), dt, start_date, BLANK_VALUE)


def assert_close(actual, expected, metric_name, tol=TOL):
    """Assert two values are close, handling large sentinels."""
    if abs(expected) > 1e30:
        assert abs(actual) > 1e30, f"{metric_name}: expected sentinel, got {actual}"
        if expected > 0:
            assert actual > 0, f"{metric_name}: expected positive sentinel"
        else:
            assert actual < 0, f"{metric_name}: expected negative sentinel"
    else:
        assert abs(actual - expected) < tol + tol * abs(expected), \
            f"{metric_name}: expected {expected}, got {actual}, diff={abs(actual-expected)}"


class TestBuildSystem:
    """Verify the C shared library build pipeline."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "/app/Makefile not found"

    def test_c_source_exists(self):
        assert os.path.isfile("/app/diag_engine.c"), "/app/diag_engine.c not found"

    def test_make_build_succeeds(self):
        result = subprocess.run(
            ["make", "-C", "/app", "build"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make build failed: {result.stderr[:500]}"

    def test_shared_library_format(self):
        assert os.path.isfile("/app/libdiag.so"), "libdiag.so not found after build"
        with open("/app/libdiag.so", "rb") as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', "libdiag.so is not an ELF binary"

    def test_exports_required_symbols(self):
        assert os.path.isfile("/app/libdiag.so"), "libdiag.so not found"
        result = subprocess.run(["nm", "-D", "/app/libdiag.so"], capture_output=True, text=True)
        assert "compute_baseweights" in result.stdout, "compute_baseweights not exported"
        assert "compute_metric" in result.stdout, "compute_metric not exported"

    def test_ctypes_loadable(self):
        """Verify shared library loads and exposes required functions via ctypes."""
        import ctypes
        lib = ctypes.CDLL("/app/libdiag.so")
        assert hasattr(lib, "compute_baseweights"), "compute_baseweights not found"
        assert hasattr(lib, "compute_metric"), "compute_metric not found"


class TestCoreMetrics:
    """Test fundamental metrics with clean data."""

    def test_nse_rmse_r2(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        metrics = [{"name": "NASH_SUTCLIFFE"}, {"name": "RMSE"}, {"name": "R2"}]
        result = run_tool(metrics, obs, mod)
        for m in ["NASH_SUTCLIFFE", "RMSE", "R2"]:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, m)

    def test_error_metrics(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        names = ["ABSERR", "ABSMAX", "RSR", "NSE4", "R4MS4E"]
        metrics = [{"name": n} for n in names]
        result = run_tool(metrics, obs, mod)
        for m in names:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, m)

    def test_bias_metrics(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        names = ["PCT_BIAS", "ABS_PCT_BIAS"]
        metrics = [{"name": n} for n in names]
        result = run_tool(metrics, obs, mod)
        for m in names:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, m)

    def test_peak_metrics(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        names = ["PDIFF", "PCT_PDIFF", "ABS_PCT_PDIFF"]
        metrics = [{"name": n} for n in names]
        result = run_tool(metrics, obs, mod)
        for m in names:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, m)

    def test_years_of_record(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "YEARS_OF_RECORD"}], obs, mod)
        expected = ref_value("YEARS_OF_RECORD", 0, obs, mod, bw)
        assert_close(result["YEARS_OF_RECORD"], expected, "YEARS_OF_RECORD")


class TestPositiveDataMetrics:
    """Test metrics requiring positive data."""

    def test_log_nash(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "LOG_NASH"}], obs, mod)
        expected = ref_value("LOG_NASH", 0, obs, mod, bw)
        assert_close(result["LOG_NASH"], expected, "LOG_NASH")

    def test_rtrmse(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "RTRMSE"}], obs, mod)
        expected = ref_value("RTRMSE", 0, obs, mod, bw)
        assert_close(result["RTRMSE"], expected, "RTRMSE")

    def test_mbf(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "MBF"}], obs, mod)
        expected = ref_value("MBF", 0, obs, mod, bw)
        assert_close(result["MBF"], expected, "MBF")

    def test_rabserr(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "RABSERR"}], obs, mod)
        expected = ref_value("RABSERR", 0, obs, mod, bw)
        assert_close(result["RABSERR"], expected, "RABSERR")


class TestKGEFamily:
    """Test KGE variants and verify they differ appropriately."""

    def test_kge_variants(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        names = ["KLING_GUPTA", "KGE_PRIME", "KLING_GUPTA_DEVIATION"]
        metrics = [{"name": n} for n in names]
        result = run_tool(metrics, obs, mod)
        for m in names:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, m)

    def test_kge_differs_from_kge_prime(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        kge = ref_value("KLING_GUPTA", 0, obs, mod, bw)
        kge_prime = ref_value("KGE_PRIME", 0, obs, mod, bw)
        assert abs(kge - kge_prime) > 1e-6, "KGE and KGE' should differ"


class TestDerivativeMetrics:
    """Test derivative-based metrics."""

    def test_nse_der(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "NASH_SUTCLIFFE_DER"}], obs, mod)
        expected = ref_value("NASH_SUTCLIFFE_DER", 0, obs, mod, bw)
        assert_close(result["NASH_SUTCLIFFE_DER"], expected, "NASH_SUTCLIFFE_DER")

    def test_rmse_der(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "RMSE_DER"}], obs, mod)
        expected = ref_value("RMSE_DER", 0, obs, mod, bw)
        assert_close(result["RMSE_DER"], expected, "RMSE_DER")

    def test_kge_der(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "KLING_GUPTA_DER"}], obs, mod)
        expected = ref_value("KLING_GUPTA_DER", 0, obs, mod, bw)
        assert_close(result["KLING_GUPTA_DER"], expected, "KLING_GUPTA_DER")


class TestDailyMetrics:
    """For daily timestep, DAILY_NSE should match NSE and DAILY_KGE should match KGE."""

    def test_daily_nse_equals_nse(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "DAILY_NSE"}, {"name": "NASH_SUTCLIFFE"}], obs, mod)
        expected_nse = ref_value("DAILY_NSE", 0, obs, mod, bw)
        assert_close(result["DAILY_NSE"], expected_nse, "DAILY_NSE")

    def test_daily_kge_equals_kge(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "DAILY_KGE"}, {"name": "KLING_GUPTA"}], obs, mod)
        expected_kge = ref_value("DAILY_KGE", 0, obs, mod, bw)
        assert_close(result["DAILY_KGE"], expected_kge, "DAILY_KGE")


class TestMovingWindowMetrics:
    """Test moving window metrics with different widths."""

    def test_nse_run_odd_width(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        width = 7
        result = run_tool([{"name": "NASH_SUTCLIFFE_RUN", "width": width}], obs, mod)
        expected = ref_value("NASH_SUTCLIFFE_RUN", width, obs, mod, bw)
        assert_close(result["NASH_SUTCLIFFE_RUN"], expected, "NASH_SUTCLIFFE_RUN(7)")

    def test_nse_run_even_width(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        width = 6
        result = run_tool([{"name": "NASH_SUTCLIFFE_RUN", "width": width}], obs, mod)
        expected = ref_value("NASH_SUTCLIFFE_RUN", width, obs, mod, bw)
        assert_close(result["NASH_SUTCLIFFE_RUN"], expected, "NASH_SUTCLIFFE_RUN(6)")

    def test_abserr_run(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        width = 5
        result = run_tool([{"name": "ABSERR_RUN", "width": width}], obs, mod)
        expected = ref_value("ABSERR_RUN", width, obs, mod, bw)
        assert_close(result["ABSERR_RUN"], expected, "ABSERR_RUN(5)")


class TestSpecialMetrics:
    """Test metrics with non-standard computation patterns."""

    def test_spearman(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "SPEARMAN"}], obs, mod)
        expected = ref_value("SPEARMAN", 0, obs, mod, bw)
        assert_close(result["SPEARMAN"], expected, "SPEARMAN")

    def test_persindex(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "PERSINDEX"}], obs, mod)
        expected = ref_value("PERSINDEX", 0, obs, mod, bw)
        assert_close(result["PERSINDEX"], expected, "PERSINDEX")

    def test_rcoef(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "RCOEF"}], obs, mod)
        expected = ref_value("RCOEF", 0, obs, mod, bw)
        assert_close(result["RCOEF"], expected, "RCOEF")

    def test_nsc(self):
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "NSC"}], obs, mod)
        expected = ref_value("NSC", 0, obs, mod, bw)
        assert_close(result["NSC"], expected, "NSC")

    def test_fuzzy_nash_small_width(self):
        """With width < 100, integer division gives pct=0."""
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "FUZZY_NASH", "width": 10}], obs, mod)
        expected = ref_value("FUZZY_NASH", 10, obs, mod, bw)
        assert_close(result["FUZZY_NASH"], expected, "FUZZY_NASH(10)")

    def test_fuzzy_nash_large_width(self):
        """With width=200, pct=2 (integer division 200//100=2), wider tolerance band."""
        obs, mod = generate_basic_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "FUZZY_NASH", "width": 200}], obs, mod)
        expected = ref_value("FUZZY_NASH", 200, obs, mod, bw)
        assert_close(result["FUZZY_NASH"], expected, "FUZZY_NASH(200)")


class TestMonthlyMetrics:
    """Test monthly volumetric metrics across year boundaries."""

    def test_tmvol(self):
        obs, mod = generate_positive_data(730)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool(
            [{"name": "TMVOL"}], obs, mod,
            start_date="2002-01-01"
        )
        expected = ref_value("TMVOL", 0, obs, mod, bw, start_date="2002-01-01")
        assert_close(result["TMVOL"], expected, "TMVOL")

    def test_tmvol_mare(self):
        obs, mod = generate_positive_data(730)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool(
            [{"name": "TMVOL_MARE"}], obs, mod,
            start_date="2002-01-01"
        )
        expected = ref_value("TMVOL_MARE", 0, obs, mod, bw, start_date="2002-01-01")
        assert_close(result["TMVOL_MARE"], expected, "TMVOL_MARE")


class TestBlankData:
    """Test metrics with blank data present."""

    def test_nse_with_blanks(self):
        obs, mod = generate_basic_data(365)
        blank_indices = [10, 50, 100, 150, 200, 250, 300, 350]
        for i in blank_indices:
            obs[i] = BLANK_VALUE
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "NASH_SUTCLIFFE"}, {"name": "RMSE"}], obs, mod)
        for m in ["NASH_SUTCLIFFE", "RMSE"]:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, f"{m}_blanks")

    def test_spearman_with_blanks(self):
        obs, mod = generate_basic_data(365)
        blank_indices = [10, 50, 100, 150, 200]
        for i in blank_indices:
            obs[i] = BLANK_VALUE
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "SPEARMAN"}], obs, mod)
        expected = ref_value("SPEARMAN", 0, obs, mod, bw)
        assert_close(result["SPEARMAN"], expected, "SPEARMAN_blanks")

    def test_years_of_record_with_blanks(self):
        obs, mod = generate_basic_data(365)
        for i in range(0, 50):
            obs[i] = BLANK_VALUE
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "YEARS_OF_RECORD"}], obs, mod)
        expected = ref_value("YEARS_OF_RECORD", 0, obs, mod, bw)
        assert_close(result["YEARS_OF_RECORD"], expected, "YEARS_OF_RECORD_blanks")


class TestThresholdFiltering:
    """Test quantile-based threshold filtering."""

    def test_nse_greaterthan(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.5, "GREATERTHAN")
        result = run_tool(
            [{"name": "NASH_SUTCLIFFE"}], obs, mod,
            threshold=0.5, comparison="GREATERTHAN"
        )
        expected = ref_value("NASH_SUTCLIFFE", 0, obs, mod, bw)
        assert_close(result["NASH_SUTCLIFFE"], expected, "NSE_GT")

    def test_rmse_lessthan(self):
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.5, "LESSTHAN")
        result = run_tool(
            [{"name": "RMSE"}], obs, mod,
            threshold=0.5, comparison="LESSTHAN"
        )
        expected = ref_value("RMSE", 0, obs, mod, bw)
        assert_close(result["RMSE"], expected, "RMSE_LT")


class TestEdgeCases:
    """Test edge cases: constant series, small datasets."""

    def test_constant_obs_returns_invalid_nse(self):
        """Constant observed series has zero variance -> NSE invalid."""
        n = 100
        obs = [50.0] * n
        mod = [50.0 + 0.1 * i for i in range(n)]
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "NASH_SUTCLIFFE"}], obs, mod)
        expected = ref_value("NASH_SUTCLIFFE", 0, obs, mod, bw)
        assert_close(result["NASH_SUTCLIFFE"], expected, "NSE_constant")

    def test_all_metrics_batch(self):
        """Run all metrics at once and verify each."""
        obs, mod = generate_positive_data(365)
        bw = compute_baseweights(obs, mod, None, BLANK_VALUE, 0.0, "NONE")
        all_metrics = [
            {"name": "NASH_SUTCLIFFE"},
            {"name": "RMSE"},
            {"name": "R2"},
            {"name": "ABSERR"},
            {"name": "ABSMAX"},
            {"name": "PCT_BIAS"},
            {"name": "ABS_PCT_BIAS"},
            {"name": "PDIFF"},
            {"name": "PCT_PDIFF"},
            {"name": "ABS_PCT_PDIFF"},
            {"name": "RSR"},
            {"name": "NSE4"},
            {"name": "R4MS4E"},
            {"name": "RTRMSE"},
            {"name": "RABSERR"},
            {"name": "PERSINDEX"},
            {"name": "YEARS_OF_RECORD"},
            {"name": "NSC"},
            {"name": "RCOEF"},
            {"name": "SPEARMAN"},
            {"name": "LOG_NASH"},
            {"name": "MBF"},
            {"name": "KLING_GUPTA"},
            {"name": "KGE_PRIME"},
            {"name": "KLING_GUPTA_DEVIATION"},
            {"name": "NASH_SUTCLIFFE_DER"},
            {"name": "RMSE_DER"},
            {"name": "KLING_GUPTA_DER"},
            {"name": "DAILY_NSE"},
            {"name": "DAILY_KGE"},
        ]
        result = run_tool(all_metrics, obs, mod)
        for m_spec in all_metrics:
            name = m_spec["name"]
            width = m_spec.get("width", 0)
            expected = ref_value(name, width, obs, mod, bw)
            assert_close(result[name], expected, f"batch_{name}")


class TestWeightedData:
    """Test with explicitly provided weights."""

    def test_nse_with_custom_weights(self):
        obs, mod = generate_basic_data(200)
        weights = [1.0 if i % 2 == 0 else 0.5 for i in range(200)]
        bw = compute_baseweights(obs, mod, weights, BLANK_VALUE, 0.0, "NONE")
        result = run_tool([{"name": "NASH_SUTCLIFFE"}, {"name": "RMSE"}],
                          obs, mod, weights=weights)
        for m in ["NASH_SUTCLIFFE", "RMSE"]:
            expected = ref_value(m, 0, obs, mod, bw)
            assert_close(result[m], expected, f"{m}_weighted")
