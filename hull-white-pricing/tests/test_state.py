"""
Tests for Hull-White one-factor model pricing engine.

"""

import json
import math
import subprocess
import os
import pytest


# ---------- helpers ----------

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bachelier_call(forward, sigma_n, T, strike):
    """Bachelier (normal model) call value per unit of payoff-unit."""
    if sigma_n <= 0 or T <= 0:
        return max(forward - strike, 0.0)
    sqrt_t = math.sqrt(T)
    d = (forward - strike) / (sigma_n * sqrt_t)
    return (forward - strike) * norm_cdf(d) + sigma_n * sqrt_t * norm_pdf(d)


def bachelier_implied_vol(forward, strike, T, payoff_unit, price, tol=1e-12):
    """Invert Bachelier formula for normal implied vol via Newton."""
    if price <= 0 or payoff_unit <= 0 or T <= 0:
        return 0.0
    target = price / payoff_unit
    sigma = target / math.sqrt(T / (2.0 * math.pi))  # initial guess
    if sigma <= 0:
        sigma = 1e-6
    for _ in range(200):
        sqrt_t = math.sqrt(T)
        d = (forward - strike) / (sigma * sqrt_t)
        val = (forward - strike) * norm_cdf(d) + sigma * sqrt_t * norm_pdf(d)
        vega = sqrt_t * norm_pdf(d)
        if vega < 1e-30:
            break
        diff = val - target
        if abs(diff) < tol:
            break
        sigma -= diff / vega
        if sigma <= 0:
            sigma = 1e-8
    return sigma


# ---------- model parameters ----------

A = 0.1           # mean reversion
SIGMA = 0.005     # short rate volatility
TENORS = [0.5, 40.0]
RATES = [0.03, 0.04]
BOND_MATS = [1.0, 2.0, 5.0, 10.0, 15.0, 20.0]
CAPLET_MATS = [1.0, 2.0, 5.0, 10.0]
DELTA = 0.5
STRIKE_OFFSET = 0.01


def zero_rate(t):
    if t <= TENORS[0]:
        return RATES[0]
    if t >= TENORS[-1]:
        return RATES[-1]
    w = (t - TENORS[0]) / (TENORS[1] - TENORS[0])
    return RATES[0] + w * (RATES[1] - RATES[0])


def df(t):
    if t <= 0:
        return 1.0
    return math.exp(-zero_rate(t) * t)


def B_func(t, T):
    tau = T - t
    if abs(A * tau) < 1e-12:
        return tau
    return (1.0 - math.exp(-A * tau)) / A


def cond_var(s, t):
    return SIGMA ** 2 / (2.0 * A) * (1.0 - math.exp(-2.0 * A * (t - s)))


def fwd_bond_vol(T, delta):
    phi = cond_var(0, T)
    b = B_func(T, T + delta)
    return math.sqrt(phi * b * b / T)


def total_bond_vol(T, S):
    """Total (non-annualized) lognormal vol of the forward bond P(T,S)."""
    return SIGMA / A * (1.0 - math.exp(-A * (S - T))) * math.sqrt(
        (1.0 - math.exp(-2.0 * A * T)) / (2.0 * A)
    )


def forward_libor(T, delta):
    return (df(T) / df(T + delta) - 1.0) / delta


def analytic_caplet_price(T, delta, K):
    """Analytic HW caplet price via zero-coupon bond put."""
    X = 1.0 / (1.0 + K * delta)   # bond strike
    F = df(T + delta) / df(T)     # forward bond price
    sp = total_bond_vol(T, T + delta)
    if sp <= 0:
        return max(1.0 - (1.0 + K * delta) * df(T + delta) / df(T), 0.0) * df(T)
    d1 = (math.log(F / X) + 0.5 * sp * sp) / sp
    d2 = d1 - sp
    zbp = X * df(T) * norm_cdf(-d2) - df(T + delta) * norm_cdf(-d1)
    return (1.0 + K * delta) * zbp


# ---------- fixture: run engine once ----------

@pytest.fixture(scope="module")
def results():
    os.chdir("/app")
    r = subprocess.run(
        ["bash", "run.sh"],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, (
        f"Engine exited {r.returncode}.\nstdout:\n{r.stdout[-2000:]}\nstderr:\n{r.stderr[-2000:]}"
    )
    with open("/app/results.json") as f:
        return json.load(f)


# ---------- tests ----------

class TestAnalyticValues:
    """Exact analytic quantities computed by the engine."""

    def test_discount_factors(self, results):
        vals = results["discount_factors"]
        for i, T in enumerate(BOND_MATS):
            expected = df(T)
            assert abs(vals[i] - expected) < 1e-8, (
                f"df({T}): got {vals[i]}, expected {expected}"
            )

    def test_B_values(self, results):
        expected = [B_func(0, T) for T in [1, 5, 10, 20]]
        vals = results["B_values"]
        for i in range(4):
            assert abs(vals[i] - expected[i]) < 1e-9, (
                f"B(0,{[1,5,10,20][i]}): got {vals[i]}, expected {expected[i]}"
            )

    def test_conditional_variance(self, results):
        expected = [cond_var(0, t) for t in [1, 5, 10]]
        vals = results["conditional_variance"]
        for i in range(3):
            assert abs(vals[i] - expected[i]) < 1e-12, (
                f"condVar({[1,5,10][i]}): got {vals[i]}, expected {expected[i]}"
            )

    def test_forward_bond_volatility(self, results):
        vals = results["forward_bond_volatility"]
        for i, T in enumerate(CAPLET_MATS):
            expected = fwd_bond_vol(T, DELTA)
            assert abs(vals[i] - expected) < 1e-10, (
                f"fbv({T}): got {vals[i]}, expected {expected}"
            )


class TestMCBonds:
    """MC bond prices vs analytic discount factors."""

    def test_mc_bond_convergence(self, results):
        mc = results["mc_bond_prices"]
        for i, T in enumerate(BOND_MATS):
            expected = df(T)
            assert abs(mc[i] - expected) < 5e-3, (
                f"MC bond({T}): got {mc[i]}, expected {expected}, "
                f"diff={abs(mc[i]-expected):.6f}"
            )


class TestCaplets:
    """Caplet pricing consistency between MC and analytic."""

    def test_forward_rates_and_strikes(self, results):
        fwds = results["caplet_forward_rates"]
        strikes = results["caplet_strikes"]
        for i, T in enumerate(CAPLET_MATS):
            F = forward_libor(T, DELTA)
            assert abs(fwds[i] - F) < 1e-6, f"Forward({T}): {fwds[i]} vs {F}"
            assert abs(strikes[i] - (F + STRIKE_OFFSET)) < 1e-6

    def test_mc_vs_analytic_caplet_iv(self, results):
        mc_iv = results["mc_caplet_implied_normal_vols"]
        an_iv = results["analytic_caplet_implied_normal_vols"]
        for i, T in enumerate(CAPLET_MATS):
            assert abs(mc_iv[i] - an_iv[i]) < 2e-3, (
                f"Caplet IV({T}): MC={mc_iv[i]:.6f} vs analytic={an_iv[i]:.6f}, "
                f"diff={abs(mc_iv[i]-an_iv[i]):.6f}"
            )

    def test_analytic_caplet_iv_cross_check(self, results):
        """Independently compute analytic caplet implied vol in Python."""
        an_iv = results["analytic_caplet_implied_normal_vols"]
        for i, T in enumerate(CAPLET_MATS):
            F = forward_libor(T, DELTA)
            K = F + STRIKE_OFFSET
            price = analytic_caplet_price(T, DELTA, K)
            payoff_unit = df(T + DELTA) * DELTA
            expected_iv = bachelier_implied_vol(F, K, T, payoff_unit, price)
            assert abs(an_iv[i] - expected_iv) < 1e-6, (
                f"Analytic IV cross-check({T}): Java={an_iv[i]:.8f} vs "
                f"Python={expected_iv:.8f}"
            )

    def test_mc_caplet_prices_positive(self, results):
        for i, p in enumerate(results["mc_caplet_prices"]):
            assert p > 0, f"MC caplet price[{i}] should be positive: {p}"


class TestSwaptions:
    """Bermudan and European swaption checks."""

    def test_european_positive(self, results):
        v = results["european_swaption_value"]
        assert v > 0, f"European swaption should be positive: {v}"

    def test_bermudan_ge_european(self, results):
        euro = results["european_swaption_value"]
        berm = results["bermudan_swaption_value"]
        assert berm >= euro - 5e-4, (
            f"Bermudan ({berm}) should be >= European ({euro})"
        )

    def test_swaption_sanity(self, results):
        euro = results["european_swaption_value"]
        berm = results["bermudan_swaption_value"]
        assert euro < 0.05, f"European swaption too large: {euro}"
        assert berm < 0.05, f"Bermudan swaption too large: {berm}"
        assert berm > 0, f"Bermudan swaption should be positive: {berm}"
