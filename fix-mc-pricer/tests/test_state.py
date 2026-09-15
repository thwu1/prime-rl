"""
Tests for the hybrid C/Python Monte Carlo option pricing engine.
Verifies: C library loads, Sobol stratification, inverse CDF accuracy,
GBM path statistics, payoff correctness, geometric Asian closed-form,
control variate effectiveness, integrated MC pricing, and variance analysis.
"""
import math
import sys
import os
import json
import random

import pytest

sys.path.insert(0, "/app")

from qrng_wrapper import SobolEngine, norm_inv
from gbm_paths import simulate_paths
from payoffs import european_call, european_put, asian_call, barrier_up_out_call
from mc_pricer import price_option
from geo_asian import geometric_asian_call


# ---------------------------------------------------------------------------
# 1. C library loading
# ---------------------------------------------------------------------------

def test_c_library_is_shared_object():
    """libqrng.so must be a valid shared object, not an ar archive."""
    lib_path = "/app/libqrng.so"
    assert os.path.exists(lib_path), f"Shared library not found at {lib_path}"
    with open(lib_path, "rb") as f:
        magic = f.read(4)
    assert magic == b"\x7fELF", (
        f"libqrng.so is not a valid ELF binary (magic={magic!r}). "
        "Check the Makefile — it may be building a static archive instead."
    )


# ---------------------------------------------------------------------------
# 2. Sobol sequence tests
# ---------------------------------------------------------------------------

def test_sobol_stratification_dim1_8():
    """First 8 points of dim-1 Sobol must be exactly {0/8, 1/8, ..., 7/8}."""
    engine = SobolEngine(1)
    pts = engine.generate(8)
    vals = sorted(p[0] for p in pts)
    expected = [i / 8.0 for i in range(8)]
    for v, e in zip(vals, expected):
        assert abs(v - e) < 1e-9, (
            f"Dim-1 stratification at 8 pts: got {v}, expected {e}"
        )


def test_sobol_stratification_dim1_16():
    """First 16 points of dim-1 Sobol must be exactly {0/16, ..., 15/16}."""
    engine = SobolEngine(1)
    pts = engine.generate(16)
    vals = sorted(p[0] for p in pts)
    expected = [i / 16.0 for i in range(16)]
    for v, e in zip(vals, expected):
        assert abs(v - e) < 1e-9, (
            f"Dim-1 stratification at 16 pts: got {v}, expected {e}"
        )


def test_sobol_stratification_dim2():
    """First 8 points: each 1-D projection covers {0/8, ..., 7/8}."""
    engine = SobolEngine(2)
    pts = engine.generate(8)
    for d in range(2):
        vals = sorted(p[d] for p in pts)
        expected = [i / 8.0 for i in range(8)]
        for v, e in zip(vals, expected):
            assert abs(v - e) < 1e-9, (
                f"Dim-{d + 1} stratification at 8 pts: got {v}, expected {e}"
            )


def test_sobol_first_point_is_origin():
    """Point 0 of any Sobol engine must be the origin."""
    for dim in (1, 3, 6):
        engine = SobolEngine(dim)
        pts = engine.generate(1)
        assert pts[0] == [0.0] * dim


# ---------------------------------------------------------------------------
# 3. Inverse normal CDF tests
# ---------------------------------------------------------------------------

def test_norm_inv_at_half():
    assert abs(norm_inv(0.5)) < 1e-12


def test_norm_inv_central_values():
    """Check several central-region values against known CDF lookups."""
    cases = [
        (0.8413447, 1.0),
        (0.1586553, -1.0),
        (0.9772499, 2.0),
        (0.0227501, -2.0),
    ]
    for u, expected in cases:
        got = norm_inv(u)
        assert abs(got - expected) < 0.005, (
            f"norm_inv({u}) = {got}, expected ~ {expected}"
        )


def test_norm_inv_tail_values():
    """Tail region must also be accurate (q = sqrt(-2 log p))."""
    cases = [
        (0.001,  -3.09023),
        (0.01,   -2.32635),
        (0.99,    2.32635),
        (0.999,   3.09023),
        (0.005,  -2.57583),
    ]
    for u, expected in cases:
        got = norm_inv(u)
        assert abs(got - expected) < 0.005, (
            f"norm_inv({u}) = {got}, expected ~ {expected}"
        )


# ---------------------------------------------------------------------------
# 4. GBM path tests
# ---------------------------------------------------------------------------

def test_gbm_log_return_mean():
    """Mean of log(S_T / S_0) must equal (r - sigma^2/2) * T."""
    S0, r, sigma, T = 100.0, 0.05, 0.2, 1.0
    n_steps = 1
    rng = random.Random(42)
    n_trials = 20000
    log_rets = []
    for _ in range(n_trials):
        z = [rng.gauss(0, 1)]
        path = simulate_paths(S0, r, sigma, T, n_steps, z)
        log_rets.append(math.log(path[-1] / S0))
    mean_lr = sum(log_rets) / len(log_rets)
    expected = (r - 0.5 * sigma ** 2) * T
    assert abs(mean_lr - expected) < 0.008, (
        f"GBM mean log-return = {mean_lr:.5f}, expected ~ {expected:.5f}"
    )


def test_gbm_log_return_variance():
    """Variance of log(S_T / S_0) must equal sigma^2 * T."""
    S0, r, sigma, T = 100.0, 0.05, 0.2, 1.0
    rng = random.Random(42)
    n_trials = 20000
    log_rets = []
    for _ in range(n_trials):
        z = [rng.gauss(0, 1)]
        path = simulate_paths(S0, r, sigma, T, 1, z)
        log_rets.append(math.log(path[-1] / S0))
    mean_lr = sum(log_rets) / len(log_rets)
    var_lr = sum((x - mean_lr) ** 2 for x in log_rets) / (len(log_rets) - 1)
    expected_var = sigma ** 2 * T
    assert abs(var_lr - expected_var) < 0.005, (
        f"GBM log-return variance = {var_lr:.5f}, expected ~ {expected_var:.5f}"
    )


# ---------------------------------------------------------------------------
# 5. Payoff tests
# ---------------------------------------------------------------------------

def test_asian_call_payoff():
    """Asian average must cover monitoring prices only (exclude S0)."""
    path = [110.0, 105.0, 115.0]
    K, r, T, S0 = 100.0, 0.0, 1.0, 100.0
    result = asian_call(path, K, r, T, S0)
    correct_avg = (110.0 + 105.0 + 115.0) / 3.0
    correct_payoff = max(correct_avg - K, 0.0)
    assert abs(result - correct_payoff) < 0.01, (
        f"Asian payoff = {result}, expected {correct_payoff}"
    )


def test_european_call_payoff():
    path = [120.0]
    assert abs(european_call(path, 100, 0.0, 1.0) - 20.0) < 1e-10


def test_european_put_payoff():
    path = [80.0]
    assert abs(european_put(path, 100, 0.0, 1.0) - 20.0) < 1e-10


def test_barrier_payoff_no_breach():
    """If barrier is never hit, payoff equals vanilla call."""
    path = [105.0, 110.0, 108.0, 112.0]
    K, r, T, S0, barrier = 100.0, 0.05, 1.0, 100.0, 130.0
    result = barrier_up_out_call(path, K, r, T, S0, barrier)
    expected = math.exp(-r * T) * max(path[-1] - K, 0.0)
    assert abs(result - expected) < 1e-10, (
        f"No-breach barrier payoff = {result}, expected {expected}"
    )


def test_barrier_payoff_breach():
    """If barrier is hit at any step, payoff must be 0."""
    path = [105.0, 135.0, 110.0, 108.0]
    K, r, T, S0, barrier = 100.0, 0.05, 1.0, 100.0, 130.0
    result = barrier_up_out_call(path, K, r, T, S0, barrier)
    assert result == 0.0, f"Breached barrier should give 0, got {result}"


def test_barrier_payoff_breach_at_boundary():
    """Barrier is breached when S >= barrier (not just >)."""
    path = [105.0, 130.0, 110.0]
    K, r, T, S0, barrier = 100.0, 0.0, 1.0, 100.0, 130.0
    result = barrier_up_out_call(path, K, r, T, S0, barrier)
    assert result == 0.0, f"Touch at barrier should give 0, got {result}"


def test_barrier_payoff_otm_no_breach():
    """OTM barrier option with no breach should give 0 payoff."""
    path = [95.0, 98.0, 90.0]
    K, r, T, S0, barrier = 100.0, 0.0, 1.0, 100.0, 130.0
    result = barrier_up_out_call(path, K, r, T, S0, barrier)
    assert result == 0.0, f"OTM barrier payoff should be 0, got {result}"


# ---------------------------------------------------------------------------
# 6. Geometric Asian closed-form tests
# ---------------------------------------------------------------------------

def _bs_call(S0, K, r, sigma, T):
    st = sigma * math.sqrt(T)
    d1 = (math.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / st
    d2 = d1 - st
    def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return S0 * N(d1) - K * math.exp(-r * T) * N(d2)


def _bs_put(S0, K, r, sigma, T):
    st = sigma * math.sqrt(T)
    d1 = (math.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / st
    d2 = d1 - st
    def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return K * math.exp(-r * T) * N(-d2) - S0 * N(-d1)


def test_geo_asian_single_step_equals_bs():
    """With n_steps=1, geometric Asian must reduce exactly to Black-Scholes."""
    S0, K, r, sigma, T = 100.0, 100.0, 0.05, 0.2, 1.0
    geo = geometric_asian_call(S0, K, r, sigma, T, 1)
    bs = _bs_call(S0, K, r, sigma, T)
    assert abs(geo - bs) < 0.01, (
        f"n=1 geo Asian={geo:.6f}, BS={bs:.6f}, diff={abs(geo - bs):.6f}"
    )


def test_geo_asian_single_step_otm():
    """OTM case: n=1 geometric Asian must also equal Black-Scholes."""
    S0, K, r, sigma, T = 100.0, 110.0, 0.05, 0.2, 1.0
    geo = geometric_asian_call(S0, K, r, sigma, T, 1)
    bs = _bs_call(S0, K, r, sigma, T)
    assert abs(geo - bs) < 0.01, (
        f"n=1 OTM geo Asian={geo:.6f}, BS={bs:.6f}, diff={abs(geo - bs):.6f}"
    )


def test_geo_asian_single_step_high_vol():
    """High vol case: n=1 geometric Asian must equal BS."""
    S0, K, r, sigma, T = 100.0, 100.0, 0.08, 0.4, 2.0
    geo = geometric_asian_call(S0, K, r, sigma, T, 1)
    bs = _bs_call(S0, K, r, sigma, T)
    assert abs(geo - bs) < 0.01, (
        f"n=1 high-vol geo Asian={geo:.6f}, BS={bs:.6f}, diff={abs(geo - bs):.6f}"
    )


def test_geo_asian_less_than_european():
    """Geometric Asian call must be strictly less than European call for n > 1."""
    S0, K, r, sigma, T = 100.0, 100.0, 0.05, 0.2, 1.0
    bs = _bs_call(S0, K, r, sigma, T)
    for n in [2, 4, 6, 12]:
        geo = geometric_asian_call(S0, K, r, sigma, T, n)
        assert 0 < geo < bs, (
            f"n={n}: geo={geo:.4f} should be in (0, {bs:.4f})"
        )


def test_geo_asian_decreases_with_n():
    """Geometric Asian price should decrease with n (more averaging reduces price)."""
    S0, K, r, sigma, T = 100.0, 100.0, 0.05, 0.2, 1.0
    bs = _bs_call(S0, K, r, sigma, T)
    prev = bs  # n=1 equals BS (upper bound)
    for n in [2, 6, 12, 50, 200]:
        geo = geometric_asian_call(S0, K, r, sigma, T, n)
        assert 0 < geo < prev, (
            f"n={n}: geo={geo:.4f} should be in (0, {prev:.4f})"
        )
        prev = geo


def test_geo_asian_cross_parameter():
    """Test with different sigma, maturity, and strike combinations."""
    geo1 = geometric_asian_call(100.0, 100.0, 0.05, 0.3, 0.5, 4)
    bs1 = _bs_call(100.0, 100.0, 0.05, 0.3, 0.5)
    assert 0 < geo1 < bs1, f"geo1={geo1:.4f}, bs1={bs1:.4f}"

    geo2 = geometric_asian_call(100.0, 95.0, 0.08, 0.25, 2.0, 8)
    bs2 = _bs_call(100.0, 95.0, 0.08, 0.25, 2.0)
    assert 0 < geo2 < bs2, f"geo2={geo2:.4f}, bs2={bs2:.4f}"


# ---------------------------------------------------------------------------
# 7. Control variate effectiveness
# ---------------------------------------------------------------------------

def test_cv_asian_price_reasonable():
    """Asian call with control variate should be bounded by geo and BS."""
    c = {"type": "asian_call", "S0": 100.0, "K": 100.0,
         "r": 0.05, "sigma": 0.2, "T": 1.0, "n_steps": 6}
    mc_cv = price_option(c, n_paths=8192, method="control_variate")
    bs = _bs_call(100, 100, 0.05, 0.2, 1.0)
    geo = geometric_asian_call(100, 100, 0.05, 0.2, 1.0, 6)
    # Arithmetic Asian >= Geometric Asian (Jensen's inequality), both < European
    assert geo - 0.5 < mc_cv < bs + 0.5, (
        f"CV Asian={mc_cv:.4f}, geo={geo:.4f}, bs={bs:.4f}"
    )


def test_cv_matches_crude_for_asian():
    """CV and crude MC should agree on Asian price (same expectation)."""
    c = {"type": "asian_call", "S0": 100.0, "K": 100.0,
         "r": 0.05, "sigma": 0.2, "T": 1.0, "n_steps": 6}
    mc_cv = price_option(c, n_paths=16384, method="control_variate")
    mc_crude = price_option(c, n_paths=16384, method="crude")
    assert abs(mc_cv - mc_crude) < 0.60, (
        f"CV={mc_cv:.4f}, crude={mc_crude:.4f}, diff={abs(mc_cv - mc_crude):.4f}"
    )


def test_cv_falls_back_for_non_asian():
    """Control variate method should handle non-Asian options gracefully."""
    c = {"type": "european_call", "S0": 100.0, "K": 100.0,
         "r": 0.05, "sigma": 0.2, "T": 1.0}
    mc = price_option(c, n_paths=8192, method="control_variate")
    bs = _bs_call(100, 100, 0.05, 0.2, 1.0)
    assert abs(mc - bs) < 1.0, (
        f"European with CV fallback: MC={mc:.4f}, BS={bs:.4f}"
    )


# ---------------------------------------------------------------------------
# 8. Integrated MC pricing tests
# ---------------------------------------------------------------------------

def test_european_call_vs_bs():
    c = {"type": "european_call", "S0": 100.0, "K": 100.0,
         "r": 0.05, "sigma": 0.2, "T": 1.0}
    mc = price_option(c, n_paths=16384)
    bs = _bs_call(100, 100, 0.05, 0.2, 1.0)
    assert abs(mc - bs) < 0.50, (
        f"ATM call: MC={mc:.4f}  BS={bs:.4f}  diff={abs(mc - bs):.4f}"
    )


def test_european_put_vs_bs():
    c = {"type": "european_put", "S0": 100.0, "K": 100.0,
         "r": 0.08, "sigma": 0.25, "T": 2.0}
    mc = price_option(c, n_paths=16384)
    bs = _bs_put(100, 100, 0.08, 0.25, 2.0)
    assert abs(mc - bs) < 0.50, (
        f"ATM put: MC={mc:.4f}  BS={bs:.4f}  diff={abs(mc - bs):.4f}"
    )


def test_otm_call_vs_bs():
    c = {"type": "european_call", "S0": 100.0, "K": 110.0,
         "r": 0.05, "sigma": 0.2, "T": 1.0}
    mc = price_option(c, n_paths=16384)
    bs = _bs_call(100, 110, 0.05, 0.2, 1.0)
    assert abs(mc - bs) < 0.50, (
        f"OTM call: MC={mc:.4f}  BS={bs:.4f}  diff={abs(mc - bs):.4f}"
    )


def test_put_call_parity():
    """C - P must equal S0 - K e^{-rT}."""
    call = {"type": "european_call", "S0": 100.0, "K": 100.0,
            "r": 0.05, "sigma": 0.2, "T": 1.0}
    put  = {"type": "european_put",  "S0": 100.0, "K": 100.0,
            "r": 0.05, "sigma": 0.2, "T": 1.0}
    mc_c = price_option(call, n_paths=16384)
    mc_p = price_option(put,  n_paths=16384)
    lhs = mc_c - mc_p
    rhs = 100.0 - 100.0 * math.exp(-0.05)
    assert abs(lhs - rhs) < 0.50, (
        f"Parity: C-P={lhs:.4f}  S-Ke^{{-rT}}={rhs:.4f}  diff={abs(lhs - rhs):.4f}"
    )


# ---------------------------------------------------------------------------
# 9. Barrier option tests
# ---------------------------------------------------------------------------

def test_barrier_bounded_by_vanilla():
    """Barrier price must be <= vanilla call price."""
    vanilla = {"type": "european_call", "S0": 100.0, "K": 100.0,
               "r": 0.05, "sigma": 0.2, "T": 1.0}
    barrier = {"type": "barrier_up_out_call", "S0": 100.0, "K": 100.0,
               "r": 0.05, "sigma": 0.2, "T": 1.0, "barrier": 130.0, "n_steps": 6}
    mc_v = price_option(vanilla, n_paths=16384)
    mc_b = price_option(barrier, n_paths=16384)
    assert mc_b <= mc_v + 0.50, (
        f"Barrier {mc_b:.4f} should be <= vanilla {mc_v:.4f}"
    )
    assert mc_b > 0.0, "Barrier price should be positive"


def test_barrier_high_barrier_equals_vanilla():
    """With extremely high barrier, barrier call ~ vanilla call."""
    vanilla = {"type": "european_call", "S0": 100.0, "K": 100.0,
               "r": 0.05, "sigma": 0.2, "T": 1.0}
    barrier = {"type": "barrier_up_out_call", "S0": 100.0, "K": 100.0,
               "r": 0.05, "sigma": 0.2, "T": 1.0, "barrier": 10000.0, "n_steps": 6}
    mc_v = price_option(vanilla, n_paths=16384)
    mc_b = price_option(barrier, n_paths=16384)
    assert abs(mc_v - mc_b) < 0.50, (
        f"High-barrier={mc_b:.4f}  vanilla={mc_v:.4f}  diff={abs(mc_v - mc_b):.4f}"
    )


# ---------------------------------------------------------------------------
# 10. Variance analysis report
# ---------------------------------------------------------------------------

def test_variance_analysis_exists():
    """variance_analysis.json must exist at /app/."""
    assert os.path.exists("/app/variance_analysis.json"), (
        "Missing /app/variance_analysis.json — run your variance analysis"
    )


def test_variance_analysis_structure():
    """variance_analysis.json must have entries for all three option types."""
    with open("/app/variance_analysis.json") as f:
        data = json.load(f)
    for key in ["european_call", "asian_call", "barrier_up_out_call"]:
        assert key in data, f"Missing key: {key}"
        entry = data[key]
        assert "best_method" in entry, f"{key}: missing 'best_method'"
        assert "variance_reduction_ratio" in entry, (
            f"{key}: missing 'variance_reduction_ratio'"
        )
        assert isinstance(entry["variance_reduction_ratio"], (int, float)), (
            f"{key}: variance_reduction_ratio must be numeric"
        )


def test_variance_analysis_asian_uses_cv():
    """For Asian options, control variate must be identified as best method."""
    with open("/app/variance_analysis.json") as f:
        data = json.load(f)
    asian = data["asian_call"]
    assert asian["best_method"] == "control_variate", (
        f"Asian best_method should be 'control_variate', got '{asian['best_method']}'"
    )
    assert asian["variance_reduction_ratio"] > 2.0, (
        f"Asian CV VR ratio should be > 2.0, got {asian['variance_reduction_ratio']}"
    )


def test_variance_analysis_vr_positive():
    """All variance reduction ratios must be positive."""
    with open("/app/variance_analysis.json") as f:
        data = json.load(f)
    for key, entry in data.items():
        assert entry["variance_reduction_ratio"] > 0, (
            f"{key}: VR ratio must be positive, got {entry['variance_reduction_ratio']}"
        )
