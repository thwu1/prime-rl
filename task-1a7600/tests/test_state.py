
import json
import math
import numpy as np
import scipy.stats as st
import pytest


@pytest.fixture
def market_data():
    with open("/app/market_data.json") as f:
        return json.load(f)


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture
def config():
    with open("/app/config.json") as f:
        return json.load(f)


# ---------- helpers ----------

def bs_call(S0, K, sigma, T, r):
    d1 = (math.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return st.norm.cdf(d1) * S0 - st.norm.cdf(d2) * K * math.exp(-r * T)


def bs_put(S0, K, sigma, T, r):
    return bs_call(S0, K, sigma, T, r) - S0 + K * math.exp(-r * T)


def implied_vol_bisect(price, S0, K, T, r, tol=1e-10):
    lo, hi = 0.001, 3.0
    for _ in range(300):
        mid = (lo + hi) / 2.0
        p = bs_call(S0, K, mid, T, r)
        if p < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


# ---------- 1. results.json exists and has required keys ----------

class TestResultsStructure:
    def test_results_file_exists(self, results):
        assert results is not None

    def test_has_calibrated_params(self, results):
        assert "calibrated_params" in results
        params = results["calibrated_params"]
        for key in ["kappa", "gamma", "vbar", "v0", "rho"]:
            assert key in params, f"Missing parameter: {key}"
            assert isinstance(params[key], (int, float)), f"{key} must be numeric"

    def test_has_model_prices(self, results):
        assert "model_prices" in results

    def test_has_model_implied_vols(self, results):
        assert "model_implied_vols" in results

    def test_has_greeks(self, results):
        assert "greeks" in results


# ---------- 2. calibrated parameters within bounds ----------

class TestParameterBounds:
    def test_kappa_bounds(self, results, config):
        kappa = results["calibrated_params"]["kappa"]
        lo, hi = config["parameter_bounds"]["kappa"]
        assert lo <= kappa <= hi, f"kappa={kappa} out of bounds [{lo},{hi}]"

    def test_gamma_bounds(self, results, config):
        gamma = results["calibrated_params"]["gamma"]
        lo, hi = config["parameter_bounds"]["gamma"]
        assert lo <= gamma <= hi, f"gamma={gamma} out of bounds [{lo},{hi}]"

    def test_vbar_bounds(self, results, config):
        vbar = results["calibrated_params"]["vbar"]
        lo, hi = config["parameter_bounds"]["vbar"]
        assert lo <= vbar <= hi, f"vbar={vbar} out of bounds [{lo},{hi}]"

    def test_v0_bounds(self, results, config):
        v0 = results["calibrated_params"]["v0"]
        lo, hi = config["parameter_bounds"]["v0"]
        assert lo <= v0 <= hi, f"v0={v0} out of bounds [{lo},{hi}]"

    def test_rho_bounds(self, results, config):
        rho = results["calibrated_params"]["rho"]
        lo, hi = config["parameter_bounds"]["rho"]
        assert lo <= rho <= hi, f"rho={rho} out of bounds [{lo},{hi}]"


# ---------- 3. pricing accuracy ----------

class TestPricingAccuracy:
    def test_all_prices_within_tolerance(self, results, market_data):
        """Calibrated model prices must match market within 0.1% relative error."""
        model_prices = results["model_prices"]
        market_prices = market_data["call_prices"]
        max_rel_err = 0.0
        for T_str in market_prices:
            mkt = market_prices[T_str]
            mdl = model_prices[T_str]
            assert len(mdl) == len(mkt), f"Price count mismatch at T={T_str}"
            for j in range(len(mkt)):
                if mkt[j] > 0.01:  # skip near-zero prices
                    rel_err = abs(mdl[j] - mkt[j]) / mkt[j]
                    max_rel_err = max(max_rel_err, rel_err)
                    assert rel_err < 0.001, (
                        f"T={T_str}, strike idx {j}: model={mdl[j]:.6f}, "
                        f"market={mkt[j]:.6f}, rel_err={rel_err:.6f}"
                    )
        print(f"Max relative pricing error: {max_rel_err:.8f}")

    def test_prices_positive(self, results, market_data):
        """All model call prices must be non-negative."""
        for T_str, prices in results["model_prices"].items():
            for j, p in enumerate(prices):
                assert p >= -1e-10, f"Negative price at T={T_str}, idx={j}: {p}"

    def test_put_call_parity(self, results, market_data):
        """Put-call parity: C - P = S0 - K*exp(-rT)."""
        S0 = market_data["S0"]
        r = market_data["r"]
        strikes = market_data["strikes"]
        for T_str, call_prices in results["model_prices"].items():
            T = float(T_str)
            for j, K in enumerate(strikes):
                C = call_prices[j]
                intrinsic_fwd = S0 - K * math.exp(-r * T)
                # Call >= max(S0 - K*exp(-rT), 0)
                if intrinsic_fwd > 0:
                    assert C >= intrinsic_fwd - 0.01, (
                        f"Call below lower bound at T={T}, K={K}"
                    )


# ---------- 4. implied volatility structure ----------

class TestImpliedVolStructure:
    def test_implied_vols_positive(self, results):
        for T_str, ivs in results["model_implied_vols"].items():
            for j, iv in enumerate(ivs):
                assert iv > 0, f"Non-positive IV at T={T_str}, idx={j}"
                assert iv < 2.0, f"Implausibly large IV at T={T_str}, idx={j}: {iv}"

    def test_smile_skew_negative_rho(self, results, market_data):
        """With negative rho, IV should generally decrease from low to high strikes (skew)."""
        for T_str, ivs in results["model_implied_vols"].items():
            # The lowest strike IV should be higher than the highest
            assert ivs[0] > ivs[-1], (
                f"Expected negative skew at T={T_str}: IV[low_K]={ivs[0]} "
                f"should exceed IV[high_K]={ivs[-1]}"
            )

    def test_implied_vols_match_market(self, results, market_data):
        """Model implied vols should be close to market-implied values
        (recomputed from model prices)."""
        S0 = market_data["S0"]
        r = market_data["r"]
        strikes = market_data["strikes"]
        for T_str, model_prices in results["model_prices"].items():
            T = float(T_str)
            model_ivs = results["model_implied_vols"][T_str]
            for j, K in enumerate(strikes):
                if model_prices[j] > 0.01:
                    recomputed_iv = implied_vol_bisect(model_prices[j], S0, K, T, r)
                    assert abs(recomputed_iv - model_ivs[j]) < 0.005, (
                        f"IV mismatch at T={T_str}, K={K}: "
                        f"reported={model_ivs[j]:.6f}, recomputed={recomputed_iv:.6f}"
                    )


# ---------- 5. Greeks ----------

# Reference Greeks computed from the ground-truth Heston parameters
GREEKS_REFERENCE = {
    "90.0": {"delta": 0.827081, "gamma": 0.009783, "vega": 32.961081},
    "95.0": {"delta": 0.765315, "gamma": 0.013218, "vega": 38.332642},
    "100.0": {"delta": 0.687339, "gamma": 0.017313, "vega": 42.613790},
    "105.0": {"delta": 0.592281, "gamma": 0.021673, "vega": 44.805864},
    "110.0": {"delta": 0.482461, "gamma": 0.025338, "vega": 43.897993},
}


class TestGreeks:
    def test_delta_in_range(self, results):
        """Call delta must be in [0, 1]."""
        greeks = results["greeks"]
        for K_str, g in greeks.items():
            assert 0.0 <= g["delta"] <= 1.0, (
                f"Delta out of range at K={K_str}: {g['delta']}"
            )

    def test_delta_monotone_decreasing(self, results):
        """Call delta should decrease as strike increases."""
        greeks = results["greeks"]
        sorted_strikes = sorted(greeks.keys(), key=float)
        deltas = [greeks[k]["delta"] for k in sorted_strikes]
        for j in range(len(deltas) - 1):
            assert deltas[j] >= deltas[j + 1] - 0.001, (
                f"Delta not monotone: K={sorted_strikes[j]} delta={deltas[j]}, "
                f"K={sorted_strikes[j+1]} delta={deltas[j+1]}"
            )

    def test_gamma_positive(self, results):
        """Gamma must be positive for European calls."""
        greeks = results["greeks"]
        for K_str, g in greeks.items():
            assert g["gamma_greek"] > 0, (
                f"Non-positive gamma at K={K_str}: {g['gamma_greek']}"
            )

    def test_vega_positive(self, results):
        """Vega must be positive."""
        greeks = results["greeks"]
        for K_str, g in greeks.items():
            assert g["vega"] > 0, f"Non-positive vega at K={K_str}: {g['vega']}"

    def test_delta_accuracy(self, results):
        """Delta should match reference within tolerance."""
        greeks = results["greeks"]
        for K_str, ref in GREEKS_REFERENCE.items():
            assert K_str in greeks, f"Missing Greeks for K={K_str}"
            computed = greeks[K_str]["delta"]
            expected = ref["delta"]
            assert abs(computed - expected) < 0.02, (
                f"Delta mismatch at K={K_str}: computed={computed:.6f}, "
                f"expected={expected:.6f}"
            )

    def test_gamma_accuracy(self, results):
        """Gamma should match reference within tolerance."""
        greeks = results["greeks"]
        for K_str, ref in GREEKS_REFERENCE.items():
            assert K_str in greeks, f"Missing Greeks for K={K_str}"
            computed = greeks[K_str]["gamma_greek"]
            expected = ref["gamma"]
            assert abs(computed - expected) / expected < 0.1, (
                f"Gamma mismatch at K={K_str}: computed={computed:.6f}, "
                f"expected={expected:.6f}"
            )

    def test_vega_accuracy(self, results):
        """Vega should match reference within tolerance."""
        greeks = results["greeks"]
        for K_str, ref in GREEKS_REFERENCE.items():
            assert K_str in greeks, f"Missing Greeks for K={K_str}"
            computed = greeks[K_str]["vega"]
            expected = ref["vega"]
            assert abs(computed - expected) / expected < 0.1, (
                f"Vega mismatch at K={K_str}: computed={computed:.6f}, "
                f"expected={expected:.6f}"
            )
