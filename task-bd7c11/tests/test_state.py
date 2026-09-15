
"""
Tests for Nelson-Siegel-Svensson yield curve fitting pipeline.
Verifies fitted parameters, spot/forward/par rates, model prices, and classifications.
"""

import json
import csv
import math
import os
import pytest
import numpy as np


# --- Reference values from the data-generating process ---

REFERENCE_SPOT_RATES = {
    0.5: 0.02856219,
    1.0: 0.03424272,
    2.0: 0.04031005,
    3.0: 0.04259320,
    5.0: 0.04304470,
    7.0: 0.04217487,
    10.0: 0.04097521,
    20.0: 0.03957608,
    30.0: 0.03961841,
}

REFERENCE_CLASSIFICATIONS = {
    "91280000A": "fair", "91280001A": "fair", "91280002A": "cheap",
    "91280003A": "fair", "91280004A": "fair", "91280005A": "fair",
    "91280006A": "fair", "91280007A": "fair", "91280008A": "fair",
    "91280009A": "fair", "91280010A": "fair", "91280011A": "fair",
    "91280012A": "fair", "91280013A": "fair", "91280014A": "fair",
    "91280015A": "fair", "91280016A": "rich", "91280017A": "rich",
    "91280018A": "fair", "91280019A": "fair", "91280020A": "fair",
    "91280021A": "fair", "91280022A": "fair", "91280023A": "fair",
    "91280024A": "fair", "91280025A": "cheap", "91280026A": "fair",
    "91280027A": "fair", "91280028A": "fair", "91280029A": "fair",
    "91280030A": "cheap", "91280031A": "fair", "91280032A": "fair",
    "91280033A": "fair", "91280034A": "fair", "91280035A": "fair",
    "91280036A": "fair", "91280037A": "fair", "91280038A": "fair",
    "91280039A": "fair", "91280040A": "rich", "91280041A": "fair",
    "91280042A": "fair", "91280043A": "cheap", "91280044A": "fair",
    "91280045A": "fair", "91280046A": "cheap", "91280047A": "fair",
    "91280048A": "fair", "91280049A": "fair", "91280050A": "fair",
    "91280051A": "fair", "91280052A": "fair", "91280053A": "fair",
    "91280054A": "fair", "91280055A": "fair", "91280056A": "fair",
    "91280057A": "fair", "91280058A": "fair", "91280059A": "fair",
    "91280060A": "fair", "91280061A": "fair", "91280062A": "fair",
    "91280063A": "fair",
}

KEY_MATURITIES = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
SPOT_RATE_TOL_BPS = 25  # 25 basis points
RICH_CHEAP_THRESHOLD = 0.0015  # 0.15%


# --- NSS model functions for internal consistency checks ---

def _nss_spot(t, tau1, tau2, beta1, beta2, beta3, beta4):
    if t < 1e-10:
        return beta1 + beta2
    x1 = t / tau1
    x2 = t / tau2
    e1 = math.exp(-x1)
    e2 = math.exp(-x2)
    f1 = (1 - e1) / x1
    f2 = (1 - e2) / x2
    return beta1 + beta2 * f1 + beta3 * (f1 - e1) + beta4 * (f2 - e2)


def _nss_forward(t, tau1, tau2, beta1, beta2, beta3, beta4):
    if t < 1e-10:
        return beta1 + beta2
    x1 = t / tau1
    x2 = t / tau2
    return (beta1 + beta2 * math.exp(-x1)
            + beta3 * x1 * math.exp(-x1)
            + beta4 * x2 * math.exp(-x2))


def _discount(t, tau1, tau2, beta1, beta2, beta3, beta4):
    if t < 1e-10:
        return 1.0
    y = _nss_spot(t, tau1, tau2, beta1, beta2, beta3, beta4)
    return math.exp(-y * t)


def _cashflow_times(ytm):
    n = int(math.ceil(ytm * 2))
    times = []
    for i in range(n):
        t = ytm - i * 0.5
        if t > 0.001:
            times.append(t)
    return sorted(times)


def _par_yield(maturity, tau1, tau2, beta1, beta2, beta3, beta4):
    times = _cashflow_times(maturity)
    if not times:
        return _nss_spot(maturity, tau1, tau2, beta1, beta2, beta3, beta4)
    df_sum = sum(_discount(t, tau1, tau2, beta1, beta2, beta3, beta4) for t in times)
    df_mat = _discount(maturity, tau1, tau2, beta1, beta2, beta3, beta4)
    return 2.0 * (1.0 - df_mat) / df_sum


def _price_bond(coupon_rate_pct, ytm, tau1, tau2, beta1, beta2, beta3, beta4):
    sc = coupon_rate_pct / 2.0
    times = _cashflow_times(ytm)
    price = 0.0
    for t in times:
        cf = sc
        if abs(t - ytm) < 0.001:
            cf += 100.0
        df = _discount(t, tau1, tau2, beta1, beta2, beta3, beta4)
        price += cf * df
    return price


# --- Helper to read CSV ---

def _read_csv(path):
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


# --- Test fixtures ---

@pytest.fixture(scope="module")
def fitted_params():
    path = "/app/output/fitted_params.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        params = json.load(f)
    required = {"tau1", "tau2", "beta1", "beta2", "beta3", "beta4"}
    assert required <= set(params.keys()), f"Missing params: {required - set(params.keys())}"
    for k in required:
        assert isinstance(params[k], (int, float)), f"{k} must be numeric, got {type(params[k])}"
    assert params["tau1"] > 0, "tau1 must be positive"
    assert params["tau2"] > 0, "tau2 must be positive"
    return params


@pytest.fixture(scope="module")
def spot_rates():
    path = "/app/output/spot_rates.csv"
    assert os.path.exists(path), f"Missing output file: {path}"
    rows = _read_csv(path)
    return {float(r["maturity"]): float(r["rate"]) for r in rows}


@pytest.fixture(scope="module")
def forward_rates():
    path = "/app/output/forward_rates.csv"
    assert os.path.exists(path), f"Missing output file: {path}"
    rows = _read_csv(path)
    return {float(r["maturity"]): float(r["rate"]) for r in rows}


@pytest.fixture(scope="module")
def par_yields():
    path = "/app/output/par_yields.csv"
    assert os.path.exists(path), f"Missing output file: {path}"
    rows = _read_csv(path)
    return {float(r["maturity"]): float(r["rate"]) for r in rows}


@pytest.fixture(scope="module")
def model_prices():
    path = "/app/output/model_prices.csv"
    assert os.path.exists(path), f"Missing output file: {path}"
    return _read_csv(path)


@pytest.fixture(scope="module")
def rich_cheap():
    path = "/app/output/rich_cheap.csv"
    assert os.path.exists(path), f"Missing output file: {path}"
    return _read_csv(path)


@pytest.fixture(scope="module")
def bond_data():
    path = "/app/data/treasury_bonds.csv"
    return _read_csv(path)


# --- Tests ---

class TestFittedParams:
    """Test that fitted parameters are reasonable."""

    def test_params_exist(self, fitted_params):
        assert fitted_params is not None

    def test_tau_positive(self, fitted_params):
        assert fitted_params["tau1"] > 0.01, "tau1 too small"
        assert fitted_params["tau2"] > 0.01, "tau2 too small"
        assert fitted_params["tau1"] < 50, "tau1 too large"
        assert fitted_params["tau2"] < 50, "tau2 too large"

    def test_beta1_reasonable(self, fitted_params):
        # beta1 is the long-run yield level, should be in [0, 0.15] (0% to 15%)
        assert 0.0 < fitted_params["beta1"] < 0.15, \
            f"beta1={fitted_params['beta1']} outside reasonable range"


class TestSpotRates:
    """Test that fitted spot rates match reference curve."""

    def test_all_maturities_present(self, spot_rates):
        for m in KEY_MATURITIES:
            assert m in spot_rates, f"Missing maturity {m} in spot_rates.csv"

    def test_spot_rates_close_to_reference(self, spot_rates):
        max_diff_bps = 0
        for m in KEY_MATURITIES:
            fitted = spot_rates[m]
            ref = REFERENCE_SPOT_RATES[m]
            diff_bps = abs(fitted - ref) * 10000
            max_diff_bps = max(max_diff_bps, diff_bps)
            assert diff_bps < SPOT_RATE_TOL_BPS, \
                f"Spot rate at {m}y: {fitted*100:.4f}% vs ref {ref*100:.4f}%, diff={diff_bps:.1f}bps > {SPOT_RATE_TOL_BPS}bps"

    def test_spot_rates_consistent_with_params(self, spot_rates, fitted_params):
        """Verify reported spot rates match the reported fitted parameters."""
        p = fitted_params
        for m in KEY_MATURITIES:
            expected = _nss_spot(m, p["tau1"], p["tau2"], p["beta1"], p["beta2"], p["beta3"], p["beta4"])
            actual = spot_rates[m]
            assert abs(actual - expected) < 1e-4, \
                f"Spot rate at {m}y ({actual:.6f}) inconsistent with fitted params ({expected:.6f})"

    def test_upward_sloping_short_end(self, spot_rates):
        """The fitted curve should be upward-sloping from 0.5y to ~5y."""
        assert spot_rates[2.0] > spot_rates[0.5], \
            "Yield curve should be upward-sloping from 0.5y to 2y"


class TestForwardRates:
    """Test forward rates are correctly derived from fitted parameters."""

    def test_all_maturities_present(self, forward_rates):
        for m in KEY_MATURITIES:
            assert m in forward_rates, f"Missing maturity {m} in forward_rates.csv"

    def test_forward_rates_consistent_with_params(self, forward_rates, fitted_params):
        """Forward rates must match the NSS forward rate formula applied to fitted params."""
        p = fitted_params
        for m in KEY_MATURITIES:
            expected = _nss_forward(m, p["tau1"], p["tau2"], p["beta1"], p["beta2"], p["beta3"], p["beta4"])
            actual = forward_rates[m]
            assert abs(actual - expected) < 1e-4, \
                f"Forward rate at {m}y ({actual:.6f}) inconsistent with fitted params ({expected:.6f})"

    def test_forward_rates_reasonable(self, forward_rates):
        for m in KEY_MATURITIES:
            r = forward_rates[m]
            assert -0.05 < r < 0.20, f"Forward rate at {m}y={r} outside reasonable range"


class TestParYields:
    """Test par yields are correctly derived from fitted parameters."""

    def test_all_maturities_present(self, par_yields):
        for m in KEY_MATURITIES:
            assert m in par_yields, f"Missing maturity {m} in par_yields.csv"

    def test_par_yields_consistent_with_params(self, par_yields, fitted_params):
        """Par yields must match the par yield formula applied to fitted params."""
        p = fitted_params
        for m in KEY_MATURITIES:
            expected = _par_yield(m, p["tau1"], p["tau2"], p["beta1"], p["beta2"], p["beta3"], p["beta4"])
            actual = par_yields[m]
            assert abs(actual - expected) < 1e-4, \
                f"Par yield at {m}y ({actual:.6f}) inconsistent with fitted params ({expected:.6f})"

    def test_par_yields_reasonable(self, par_yields):
        for m in KEY_MATURITIES:
            r = par_yields[m]
            assert 0.0 < r < 0.15, f"Par yield at {m}y={r} outside reasonable range"


class TestModelPrices:
    """Test model pricing quality."""

    def test_correct_number_of_bonds(self, model_prices):
        assert len(model_prices) == 64, f"Expected 64 bonds, got {len(model_prices)}"

    def test_all_errors_within_tolerance(self, model_prices):
        """Every bond's model price should be within 2% of observed."""
        for row in model_prices:
            err = abs(float(row["error_pct"]))
            assert err < 0.02, \
                f"Bond {row['cusip']}: |error_pct|={err:.4f} > 2%"

    def test_mean_absolute_error_small(self, model_prices):
        """Mean absolute pricing error should be below 0.5%."""
        errors = [abs(float(r["error_pct"])) for r in model_prices]
        mae = sum(errors) / len(errors)
        assert mae < 0.005, f"Mean absolute error {mae*100:.4f}% > 0.5%"

    def test_model_prices_consistent_with_params(self, model_prices, fitted_params, bond_data):
        """Verify reported model prices are actually computed from fitted params."""
        p = fitted_params
        from datetime import date
        settlement = date(2024, 6, 15)

        # Check a sample of bonds for consistency
        bond_map = {b["cusip"]: b for b in bond_data}
        checked = 0
        for row in model_prices:
            cusip = row["cusip"]
            if cusip not in bond_map:
                continue
            bd = bond_map[cusip]
            coupon = float(bd["coupon_rate"])
            mat_parts = bd["maturity_date"].split("-")
            mat_date = date(int(mat_parts[0]), int(mat_parts[1]), int(mat_parts[2]))
            ytm = (mat_date - settlement).days / 365.25

            expected_price = _price_bond(
                coupon, ytm, p["tau1"], p["tau2"],
                p["beta1"], p["beta2"], p["beta3"], p["beta4"]
            )
            reported_price = float(row["model_price"])

            # Allow 0.5% tolerance for minor implementation differences
            rel_diff = abs(reported_price - expected_price) / max(expected_price, 1.0)
            assert rel_diff < 0.005, \
                f"Bond {cusip}: reported model_price={reported_price:.4f} vs expected={expected_price:.4f} (diff={rel_diff*100:.3f}%)"
            checked += 1

        assert checked >= 50, f"Only verified {checked} bonds, expected >= 50"


class TestRichCheap:
    """Test rich/cheap/fair bond classification."""

    def test_correct_number(self, rich_cheap):
        assert len(rich_cheap) == 64, f"Expected 64 classifications, got {len(rich_cheap)}"

    def test_valid_classifications(self, rich_cheap):
        for row in rich_cheap:
            assert row["classification"] in {"rich", "cheap", "fair"}, \
                f"Invalid classification: {row['classification']}"

    def test_classification_accuracy(self, rich_cheap):
        """At least 75% of classifications should match reference."""
        correct = 0
        total = 0
        for row in rich_cheap:
            cusip = row["cusip"]
            if cusip in REFERENCE_CLASSIFICATIONS:
                total += 1
                if row["classification"] == REFERENCE_CLASSIFICATIONS[cusip]:
                    correct += 1

        accuracy = correct / total if total > 0 else 0
        assert accuracy >= 0.75, \
            f"Classification accuracy {accuracy*100:.1f}% < 75% ({correct}/{total} correct)"

    def test_classification_consistent_with_errors(self, rich_cheap):
        """Classifications must be consistent with reported error_pct."""
        for row in rich_cheap:
            err = float(row["error_pct"])
            cls = row["classification"]
            if cls == "rich":
                assert err > 0, f"Bond {row['cusip']} classified as rich but error_pct={err} <= 0"
            elif cls == "cheap":
                assert err < 0, f"Bond {row['cusip']} classified as cheap but error_pct={err} >= 0"
