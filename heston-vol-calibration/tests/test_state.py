
import json
import os
import sqlite3
import numpy as np
from scipy.stats import norm
import pytest


# ---------------------------------------------------------------------------
# Independent COS method implementation for verification
# ---------------------------------------------------------------------------

def _heston_characteristic_fn(u, T, r, kappa, gamma, vbar, v0, rho):
    """Heston log-price characteristic function (stable formulation)."""
    j = 1j
    alpha = kappa - gamma * rho * j * u
    D = np.sqrt(alpha ** 2 + gamma ** 2 * (u ** 2 + j * u))
    g = (alpha - D) / (alpha + D)
    exp_DT = np.exp(-D * T)
    C = (alpha - D) / (gamma ** 2) * (1.0 - exp_DT) / (1.0 - g * exp_DT)
    A = (r * j * u * T
         + kappa * vbar / (gamma ** 2)
         * ((alpha - D) * T - 2.0 * np.log((1.0 - g * exp_DT) / (1.0 - g))))
    return np.exp(A + C * v0)


def _cos_european_call(S0, K, T, r, kappa, gamma, vbar, v0, rho,
                       N=4096, L=12):
    """COS method for a single European call (via put + parity)."""
    j = 1j
    x0 = np.log(S0 / K)
    a = -L * np.sqrt(T)
    b = L * np.sqrt(T)
    bma = b - a

    k_vec = np.arange(N).reshape(-1, 1)
    omega = k_vec * np.pi / bma

    c_lo, c_hi = a, 0.0
    arg_hi = omega * (c_hi - a)
    arg_lo = omega * (c_lo - a)

    psi = np.sin(arg_hi) - np.sin(arg_lo)
    psi[1:] = psi[1:] * bma / (k_vec[1:] * np.pi)
    psi[0] = c_hi - c_lo

    denom = 1.0 + omega ** 2
    t1 = np.cos(arg_hi) * np.exp(c_hi) - np.cos(arg_lo) * np.exp(c_lo)
    t2 = (omega * np.sin(arg_hi) * np.exp(c_hi)
          - omega * np.sin(arg_lo) * np.exp(c_lo))
    chi = (t1 + t2) / denom

    Hk = 2.0 / bma * (-chi + psi)

    cf = _heston_characteristic_fn(omega, T, r, kappa, gamma, vbar, v0, rho)
    coeff = cf * Hk
    coeff[0] = 0.5 * coeff[0]

    basis = np.exp(j * (x0 - a) * omega.flatten())
    put_price = float(np.exp(-r * T) * K * np.real(basis @ coeff).item())
    call_price = put_price + S0 - K * np.exp(-r * T)
    return call_price


def _bs_call(S0, K, T, r, sigma):
    if sigma <= 1e-12:
        return max(S0 - K * np.exp(-r * T), 0.0)
    d1 = (np.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return float(S0 * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))


def _newton_iv(price, S0, K, T, r, tol=1e-10, max_iter=200):
    intrinsic = max(S0 - K * np.exp(-r * T), 0.0)
    if price <= intrinsic + 1e-10:
        return 0.001
    sig = 0.25
    for _ in range(max_iter):
        d1 = (np.log(S0 / K) + (r + 0.5 * sig ** 2) * T) / (sig * np.sqrt(T))
        d2 = d1 - sig * np.sqrt(T)
        bs_p = S0 * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        vega = S0 * np.sqrt(T) * norm.pdf(d1)
        if vega < 1e-14:
            sig += 0.05
            continue
        diff = bs_p - price
        if abs(diff) < tol:
            break
        sig -= diff / vega
        sig = np.clip(sig, 1e-4, 5.0)
    return float(sig)


# ---------------------------------------------------------------------------
# Fixtures — extract clean market data from the SQLite database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def market_data():
    conn = sqlite3.connect("/app/options.db")
    c = conn.cursor()

    c.execute("SELECT value FROM market_info WHERE key='spot_price'")
    spot = float(c.fetchone()[0])

    # Use latest-date OIS rate
    c.execute("""SELECT rate FROM yield_curves
                 WHERE curve_id='OIS'
                 ORDER BY as_of_date DESC, tenor_years ASC LIMIT 1""")
    rate = float(c.fetchone()[0])

    # Extract clean GOOD-quality call IVs
    c.execute("""SELECT maturity_years, strike, implied_vol
                 FROM option_quotes
                 WHERE quality_flag='GOOD' AND option_type='C'
                       AND implied_vol IS NOT NULL
                 ORDER BY maturity_years, strike""")
    rows = c.fetchall()
    conn.close()

    maturities = sorted(set(r[0] for r in rows))
    strikes = sorted(set(r[1] for r in rows))
    iv_map = {(r[0], r[1]): r[2] for r in rows}
    implied_vols = [[iv_map[(T, K)] for K in strikes] for T in maturities]

    return {
        "spot": spot,
        "rate": rate,
        "maturities": maturities,
        "strikes": strikes,
        "implied_vols": implied_vols,
    }


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1. Results structure
# ---------------------------------------------------------------------------

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json missing"

    def test_top_level_keys(self, results):
        for key in ("calibrated_params", "calibration_rmse_iv_pct",
                     "feller_satisfied", "forward_variance",
                     "repriced_ivs", "greeks"):
            assert key in results, f"Missing key: {key}"

    def test_param_keys(self, results):
        p = results["calibrated_params"]
        for name in ("kappa", "gamma", "vbar", "v0", "rho"):
            assert name in p, f"Missing param: {name}"
            assert isinstance(p[name], (int, float)), f"{name} not numeric"

    def test_param_reasonable(self, results):
        p = results["calibrated_params"]
        assert 0.0 < p["kappa"] < 50.0, f"kappa={p['kappa']} unreasonable"
        assert 0.0 < p["gamma"] < 5.0, f"gamma={p['gamma']} unreasonable"
        assert 0.0 < p["vbar"] < 1.0, f"vbar={p['vbar']} unreasonable"
        assert 0.0 < p["v0"] < 1.0, f"v0={p['v0']} unreasonable"
        assert -1.0 < p["rho"] < 1.0, f"rho={p['rho']} unreasonable"

    def test_repriced_ivs_shape(self, results, market_data):
        n_mat = len(market_data["maturities"])
        n_str = len(market_data["strikes"])
        ivs = results["repriced_ivs"]
        assert len(ivs) == n_mat
        for row in ivs:
            assert len(row) == n_str

    def test_greeks_shape(self, results, market_data):
        n_mat = len(market_data["maturities"])
        n_str = len(market_data["strikes"])
        for name in ("delta", "vega"):
            g = results["greeks"][name]
            assert len(g) == n_mat
            for row in g:
                assert len(row) == n_str

    def test_forward_variance_keys(self, results):
        fv = results["forward_variance"]
        for key in ("T_0.5", "T_1.0", "T_2.0", "T_5.0"):
            assert key in fv, f"Missing forward variance key: {key}"


# ---------------------------------------------------------------------------
# 2. Calibration quality — independent repricing
# ---------------------------------------------------------------------------

class TestCalibrationQuality:
    def test_reported_rmse(self, results):
        assert results["calibration_rmse_iv_pct"] < 1.0, \
            f"Reported RMSE {results['calibration_rmse_iv_pct']:.4f} >= 1.0 pp"

    def test_independent_rmse(self, results, market_data):
        """Reprice from agent's params using test's own COS implementation."""
        p = results["calibrated_params"]
        S0 = market_data["spot"]
        r = market_data["rate"]
        sq_err_sum, count = 0.0, 0
        for i, T in enumerate(market_data["maturities"]):
            for j, K in enumerate(market_data["strikes"]):
                price = _cos_european_call(
                    S0, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"], p["rho"])
                iv_model = _newton_iv(price, S0, K, T, r)
                iv_mkt = market_data["implied_vols"][i][j]
                sq_err_sum += (iv_model - iv_mkt) ** 2
                count += 1
        rmse_pct = 100.0 * np.sqrt(sq_err_sum / count)
        assert rmse_pct < 1.0, \
            f"Independent RMSE {rmse_pct:.4f} pp >= 1.0 pp"

    def test_repriced_ivs_vs_independent(self, results, market_data):
        """Agent's reported IVs must match test's independent COS computation."""
        p = results["calibrated_params"]
        S0 = market_data["spot"]
        r = market_data["rate"]
        for i, T in enumerate(market_data["maturities"]):
            for j, K in enumerate(market_data["strikes"]):
                iv_reported = results["repriced_ivs"][i][j]
                price = _cos_european_call(
                    S0, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"], p["rho"])
                iv_computed = _newton_iv(price, S0, K, T, r)
                assert abs(iv_reported - iv_computed) < 0.005, \
                    (f"IV mismatch T={T} K={K}: "
                     f"reported={iv_reported:.6f} vs computed={iv_computed:.6f}")


# ---------------------------------------------------------------------------
# 3. Forward variance consistency
# ---------------------------------------------------------------------------

class TestForwardVariance:
    def test_formula(self, results):
        p = results["calibrated_params"]
        fv = results["forward_variance"]
        for key, T_val in [("T_0.5", 0.5), ("T_1.0", 1.0),
                           ("T_2.0", 2.0), ("T_5.0", 5.0)]:
            expected = p["vbar"] + (p["v0"] - p["vbar"]) * np.exp(
                -p["kappa"] * T_val)
            assert abs(fv[key] - expected) < 1e-6, \
                f"Forward variance {key}: got {fv[key]:.8f}, expected {expected:.8f}"


# ---------------------------------------------------------------------------
# 4. Feller condition
# ---------------------------------------------------------------------------

class TestFellerCondition:
    def test_correct(self, results):
        p = results["calibrated_params"]
        expected = (2.0 * p["kappa"] * p["vbar"]) > (p["gamma"] ** 2)
        assert results["feller_satisfied"] == expected, \
            (f"Feller mismatch: 2*{p['kappa']}*{p['vbar']}="
             f"{2*p['kappa']*p['vbar']:.6f} vs gamma^2={p['gamma']**2:.6f}")


# ---------------------------------------------------------------------------
# 5. Greeks consistency
# ---------------------------------------------------------------------------

class TestGreeks:
    def test_delta(self, results, market_data):
        p = results["calibrated_params"]
        S0 = market_data["spot"]
        r = market_data["rate"]
        dS = 0.5
        for i, T in enumerate(market_data["maturities"]):
            for j, K in enumerate(market_data["strikes"]):
                p_up = _cos_european_call(
                    S0 + dS, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"], p["rho"])
                p_dn = _cos_european_call(
                    S0 - dS, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"], p["rho"])
                delta_ref = (p_up - p_dn) / (2.0 * dS)
                delta_rep = results["greeks"]["delta"][i][j]
                assert abs(delta_rep - delta_ref) < 0.03, \
                    (f"Delta T={T} K={K}: "
                     f"reported={delta_rep:.6f} vs ref={delta_ref:.6f}")

    def test_vega(self, results, market_data):
        p = results["calibrated_params"]
        S0 = market_data["spot"]
        r = market_data["rate"]
        dv = 0.001
        for i, T in enumerate(market_data["maturities"]):
            for j, K in enumerate(market_data["strikes"]):
                p_up = _cos_european_call(
                    S0, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"] + dv, p["rho"])
                p_dn = _cos_european_call(
                    S0, K, T, r,
                    p["kappa"], p["gamma"], p["vbar"], p["v0"] - dv, p["rho"])
                vega_ref = (p_up - p_dn) / (2.0 * dv)
                vega_rep = results["greeks"]["vega"][i][j]
                if abs(vega_ref) > 0.5:
                    assert abs(vega_rep - vega_ref) / abs(vega_ref) < 0.15, \
                        (f"Vega T={T} K={K}: "
                         f"reported={vega_rep:.4f} vs ref={vega_ref:.4f}")
                else:
                    assert abs(vega_rep - vega_ref) < 1.0, \
                        (f"Vega T={T} K={K}: "
                         f"reported={vega_rep:.4f} vs ref={vega_ref:.4f}")
