
"""Tests for Heston model calibration with multi-feed anomaly detection.

Reads the SQLite database to obtain reference prices from the clean feed,
independently implements a Fourier pricing engine and Heston characteristic
function to verify calibrated parameters produce prices matching the market data.
"""

import json
import os
import sqlite3
import numpy as np
import pytest
from scipy.stats import norm
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    return sqlite3.connect("/app/options.db")


def get_feed_names():
    """Return dict of feed_id -> feed_name."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT feed_id, feed_name FROM feeds")
    result = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return result


def get_market_config():
    """Return dict of param_name -> param_value."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT param_name, param_value FROM market_config")
    result = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return result


def get_maturities_and_strikes():
    """Return sorted lists of unique maturities and strikes."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT expiry FROM instruments ORDER BY expiry")
    maturities = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT DISTINCT strike FROM instruments ORDER BY strike")
    strikes = [row[0] for row in cur.fetchall()]
    conn.close()
    return maturities, strikes


def get_reference_prices(feed_id=1):
    """Get prices from the specified feed as {maturity: [prices by strike]}."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT i.expiry, i.strike, p.px
        FROM price_observations p
        JOIN instruments i USING(instrument_id)
        WHERE p.feed_id = ?
        ORDER BY i.expiry, i.strike
    """, (feed_id,))
    rows = cur.fetchall()
    conn.close()

    prices = {}
    for expiry, strike, px in rows:
        key = str(expiry)
        if key not in prices:
            prices[key] = []
        prices[key].append(px)
    return prices


# ---------------------------------------------------------------------------
# Independent pricing engine
# ---------------------------------------------------------------------------

def heston_cf(u_arr, r, tau, kappa, gamma, vbar, v0, rho):
    """Heston characteristic function of log(S_T / S_0)."""
    i = 1j
    u = np.asarray(u_arr, dtype=np.complex128)
    a1 = kappa - gamma * rho * i * u
    D = np.sqrt(a1 ** 2 + gamma ** 2 * (u ** 2 + i * u))
    g = (a1 - D) / (a1 + D)
    exp_neg = np.exp(-D * tau)

    C = (a1 - D) / (gamma ** 2) * (1.0 - exp_neg) / (1.0 - g * exp_neg)
    A = (r * i * u * tau
         + kappa * vbar / (gamma ** 2)
         * ((a1 - D) * tau - 2.0 * np.log((1.0 - g * exp_neg) / (1.0 - g))))
    return np.exp(A + C * v0)


def cos_call_prices(S0, r, tau, strikes, cf_func, N=4096, L=12):
    """Fourier cosine expansion for European call option prices via put-call parity."""
    i = 1j
    K = np.asarray(strikes, dtype=float).reshape(-1, 1)
    x0 = np.log(S0 / K)
    a = -L * np.sqrt(tau)
    b = L * np.sqrt(tau)

    k = np.arange(N, dtype=float).reshape(1, -1)
    u = k * np.pi / (b - a)

    c_int, d_int = a, 0.0

    psi = (np.sin(k * np.pi * (d_int - a) / (b - a))
           - np.sin(k * np.pi * (c_int - a) / (b - a)))
    psi[:, 1:] = psi[:, 1:] * (b - a) / (k[:, 1:] * np.pi)
    psi[:, 0] = d_int - c_int

    denom = 1.0 + (k * np.pi / (b - a)) ** 2
    expr1 = (np.cos(k * np.pi * (d_int - a) / (b - a)) * np.exp(d_int)
             - np.cos(k * np.pi * (c_int - a) / (b - a)) * np.exp(c_int))
    expr2 = (k * np.pi / (b - a)
             * np.sin(k * np.pi * (d_int - a) / (b - a)) * np.exp(d_int)
             - k * np.pi / (b - a)
             * np.sin(k * np.pi * (c_int - a) / (b - a)) * np.exp(c_int))
    chi = (expr1 + expr2) / denom

    H_k = 2.0 / (b - a) * (-chi + psi)

    cf_vals = cf_func(u.flatten()).reshape(1, -1)

    mat = np.exp(i * (x0 - a) * u)
    temp = cf_vals * H_k
    temp[:, 0] *= 0.5

    put = np.exp(-r * tau) * K * np.real(np.sum(mat * temp, axis=1, keepdims=True))
    call = put + S0 - K * np.exp(-r * tau)
    return call.flatten()


def bs_call(S, K, sigma, T, r):
    """Black-Scholes European call price."""
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def implied_vol(price, S, K, T, r):
    """Extract Black-Scholes implied volatility via Brent's method."""
    intrinsic = max(S - K * np.exp(-r * T), 0.0)
    if price <= intrinsic + 1e-8:
        return 0.001
    try:
        return brentq(lambda s: bs_call(S, K, s, T, r) - price, 0.001, 5.0)
    except (ValueError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


@pytest.fixture
def market_config():
    return get_market_config()


@pytest.fixture
def ref_prices():
    """Reference prices from reuters_eikon (feed_id=1)."""
    return get_reference_prices(feed_id=1)


@pytest.fixture
def maturities_strikes():
    return get_maturities_and_strikes()


@pytest.fixture
def calibrated_params():
    return load_json("/app/calibrated_params.json")


@pytest.fixture
def model_prices():
    return load_json("/app/model_prices.json")


@pytest.fixture
def iv_surface():
    return load_json("/app/iv_surface.json")


@pytest.fixture
def anomaly_report():
    return load_json("/app/anomaly_report.json")


# ---------------------------------------------------------------------------
# Test: output files exist
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_calibrated_params_exists(self):
        assert os.path.isfile("/app/calibrated_params.json"), \
            "Missing /app/calibrated_params.json"

    def test_model_prices_exists(self):
        assert os.path.isfile("/app/model_prices.json"), \
            "Missing /app/model_prices.json"

    def test_iv_surface_exists(self):
        assert os.path.isfile("/app/iv_surface.json"), \
            "Missing /app/iv_surface.json"

    def test_anomaly_report_exists(self):
        assert os.path.isfile("/app/anomaly_report.json"), \
            "Missing /app/anomaly_report.json"


# ---------------------------------------------------------------------------
# Test: anomaly detection
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_excluded_feeds_key_exists(self, anomaly_report):
        assert "excluded_feeds" in anomaly_report, \
            "anomaly_report.json must have key 'excluded_feeds'"

    def test_excluded_feeds_is_list(self, anomaly_report):
        assert isinstance(anomaly_report["excluded_feeds"], list), \
            "excluded_feeds must be a list"

    def test_darkpool_excluded(self, anomaly_report):
        assert "darkpool_composite" in anomaly_report["excluded_feeds"], \
            "darkpool_composite feed should be identified as anomalous"

    def test_reuters_not_excluded(self, anomaly_report):
        assert "reuters_eikon" not in anomaly_report["excluded_feeds"], \
            "reuters_eikon is a clean feed and must not be excluded"

    def test_bloomberg_not_excluded(self, anomaly_report):
        assert "bloomberg_bpipe" not in anomaly_report["excluded_feeds"], \
            "bloomberg_bpipe is a clean feed and must not be excluded"


# ---------------------------------------------------------------------------
# Test: calibrated parameters format and bounds
# ---------------------------------------------------------------------------

class TestCalibratedParams:
    REQUIRED_KEYS = {"kappa", "gamma", "vbar", "v0", "rho"}

    def test_has_all_keys(self, calibrated_params):
        missing = self.REQUIRED_KEYS - set(calibrated_params.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_values_are_finite(self, calibrated_params):
        for key in self.REQUIRED_KEYS:
            v = calibrated_params[key]
            assert isinstance(v, (int, float)), f"{key} is not numeric"
            assert np.isfinite(v), f"{key} is not finite: {v}"

    def test_kappa_bounds(self, calibrated_params):
        assert 0.001 < calibrated_params["kappa"] < 20.0

    def test_gamma_bounds(self, calibrated_params):
        assert 0.001 < calibrated_params["gamma"] < 3.0

    def test_vbar_bounds(self, calibrated_params):
        assert 0.0001 < calibrated_params["vbar"] < 1.0

    def test_v0_bounds(self, calibrated_params):
        assert 0.0001 < calibrated_params["v0"] < 1.0

    def test_rho_bounds(self, calibrated_params):
        assert -0.999 < calibrated_params["rho"] < 0.999


# ---------------------------------------------------------------------------
# Test: pricing accuracy against reference feed
# ---------------------------------------------------------------------------

class TestPricingAccuracy:
    """Verify calibrated parameters reproduce reference (clean) market prices."""

    def test_all_prices_within_tolerance(self, market_config, ref_prices,
                                          maturities_strikes, calibrated_params):
        S0 = market_config["spot_price"]
        r = market_config["risk_free_rate"]
        maturities, strikes = maturities_strikes
        p = calibrated_params
        kappa, gamma, vbar = p["kappa"], p["gamma"], p["vbar"]
        v0, rho = p["v0"], p["rho"]

        violations = []

        for T in maturities:
            T_str = str(T)
            if T_str not in ref_prices:
                continue
            mkt_prices = ref_prices[T_str]
            cf = lambda u, T=T: heston_cf(u, r, T, kappa, gamma, vbar, v0, rho)
            model = cos_call_prices(S0, r, T, strikes, cf)

            for idx, (mp, mdl) in enumerate(zip(mkt_prices, model)):
                if mp > 0.50:
                    rel_err = abs(mdl - mp) / mp
                    if rel_err > 0.05:
                        violations.append(
                            f"T={T}, K={strikes[idx]}: market={mp:.4f}, "
                            f"model={mdl:.4f}, rel_err={rel_err:.4f}"
                        )
                else:
                    abs_err = abs(mdl - mp)
                    if abs_err > 0.10:
                        violations.append(
                            f"T={T}, K={strikes[idx]}: market={mp:.4f}, "
                            f"model={mdl:.4f}, abs_err={abs_err:.4f}"
                        )

        assert len(violations) == 0, (
            f"{len(violations)} price(s) exceed tolerance:\n"
            + "\n".join(violations[:10])
        )


# ---------------------------------------------------------------------------
# Test: model_prices.json consistency
# ---------------------------------------------------------------------------

class TestModelPricesConsistency:
    def test_model_prices_format(self, model_prices, maturities_strikes):
        """model_prices has all maturities with correct strike count."""
        maturities, strikes = maturities_strikes
        for T in maturities:
            T_str = str(T)
            assert T_str in model_prices, f"Missing maturity {T_str}"
            assert len(model_prices[T_str]) == len(strikes), \
                f"Wrong number of prices for T={T_str}: got {len(model_prices[T_str])}, expected {len(strikes)}"

    def test_model_prices_match_independent(self, model_prices, market_config,
                                             maturities_strikes, calibrated_params):
        """Reported model prices agree with independently computed prices."""
        S0 = market_config["spot_price"]
        r = market_config["risk_free_rate"]
        maturities, strikes = maturities_strikes
        p = calibrated_params
        kappa, gamma, vbar = p["kappa"], p["gamma"], p["vbar"]
        v0, rho = p["v0"], p["rho"]

        for T in maturities:
            T_str = str(T)
            if T_str not in model_prices:
                continue
            reported = model_prices[T_str]
            cf = lambda u, T=T: heston_cf(u, r, T, kappa, gamma, vbar, v0, rho)
            independent = cos_call_prices(S0, r, T, strikes, cf)

            for idx, (rep, ind) in enumerate(zip(reported, independent)):
                denom = max(abs(ind), 1.0)
                rel_diff = abs(rep - ind) / denom
                assert rel_diff < 0.02, (
                    f"T={T}, K={strikes[idx]}: reported={rep:.4f}, "
                    f"independent={ind:.4f}, rel_diff={rel_diff:.4f}"
                )


# ---------------------------------------------------------------------------
# Test: implied volatility surface properties
# ---------------------------------------------------------------------------

class TestIVSurface:
    def test_iv_surface_format(self, iv_surface):
        assert "maturities" in iv_surface
        assert "strikes" in iv_surface
        assert "implied_vols" in iv_surface

    def test_iv_all_positive(self, iv_surface):
        for T_str, ivs in iv_surface["implied_vols"].items():
            for iv in ivs:
                assert 0 < iv < 1.5, \
                    f"IV out of range at T={T_str}: {iv}"

    def test_iv_negative_skew(self, iv_surface):
        """IV at lowest strike should exceed IV at highest strike."""
        for T_str, ivs in iv_surface["implied_vols"].items():
            assert ivs[0] > ivs[-1], (
                f"Expected negative skew at T={T_str}: "
                f"IV(K_low)={ivs[0]:.4f} <= IV(K_high)={ivs[-1]:.4f}"
            )
