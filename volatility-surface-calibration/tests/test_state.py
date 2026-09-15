
import pytest
import csv
import json
import math
import os


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs_price(S, K, T, r, q, sigma, opt_type):
    d1 = (math.log(S / K) + (r - q + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "call":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def svi_total_variance(k, a, b, rho, m, sigma):
    return a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + sigma**2))


def load_chain():
    chain = {}
    with open("/app/data/option_chain.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (int(row["expiry_days"]), int(row["strike"]), row["option_type"])
            chain[key] = float(row["mid_price"])
    return chain


def load_ivs():
    ivs = {}
    with open("/app/output/implied_vols.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (int(row["expiry_days"]), int(row["strike"]), row["option_type"])
            ivs[key] = float(row["implied_vol"])
    return ivs


# ===========================================================================
# Implied Volatilities
# ===========================================================================
class TestImpliedVols:
    def test_file_exists(self):
        assert os.path.exists("/app/output/implied_vols.csv"), "implied_vols.csv missing"

    def test_correct_columns(self):
        with open("/app/output/implied_vols.csv") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            for col in ["expiry_days", "strike", "option_type", "implied_vol"]:
                assert col in row, f"Missing column: {col}"

    def test_all_options_present(self):
        chain = load_chain()
        ivs = load_ivs()
        missing = set(chain.keys()) - set(ivs.keys())
        assert len(missing) == 0, f"Missing IVs for {len(missing)} options: {list(missing)[:5]}"

    def test_iv_range(self):
        ivs = load_ivs()
        for key, iv in ivs.items():
            assert 0.05 < iv < 1.5, f"IV {iv:.4f} out of range for {key}"

    def test_roundtrip_consistency(self):
        """BS(IV) must approximately match market price."""
        chain = load_chain()
        ivs = load_ivs()
        S = 5000.0
        r = 0.045
        q = 0.015
        max_error = 0
        count = 0
        for key, iv in ivs.items():
            exp, strike, opt_type = key
            T = exp / 365.0
            market_price = chain[key]
            computed = bs_price(S, strike, T, r, q, iv, opt_type)
            error = abs(computed - market_price)
            max_error = max(max_error, error)
            assert error < 0.05, f"Roundtrip error {error:.6f} for {key}"
            count += 1
        assert count >= 100, f"Expected >= 100 IVs, got {count}"

    def test_call_put_iv_consistency(self):
        """Call and put IVs at the same (expiry, strike) should be nearly equal."""
        ivs = load_ivs()
        tested = 0
        for (exp, strike, opt_type), iv in ivs.items():
            if opt_type != "call":
                continue
            put_key = (exp, strike, "put")
            if put_key not in ivs:
                continue
            call_iv = iv
            put_iv = ivs[put_key]
            assert abs(call_iv - put_iv) < 0.002, (
                f"Call/put IV mismatch at K={strike}, T={exp}d: {call_iv:.6f} vs {put_iv:.6f}"
            )
            tested += 1
        assert tested >= 50, f"Expected >= 50 call/put IV pairs, got {tested}"


# ===========================================================================
# SVI Parameters
# ===========================================================================
class TestSVIParams:
    def test_file_exists(self):
        assert os.path.exists("/app/output/svi_params.json"), "svi_params.json missing"

    def test_all_expirations_present(self):
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        for exp in ["30", "90", "180", "365", "730"]:
            assert exp in params, f"Missing expiration {exp}"

    def test_param_keys(self):
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        for exp, p in params.items():
            for k in ["a", "b", "rho", "m", "sigma"]:
                assert k in p, f"Missing param '{k}' for T={exp}"

    def test_param_constraints(self):
        """SVI parameters must satisfy basic constraints."""
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        for exp, p in params.items():
            assert p["b"] >= 0, f"b must be >= 0 for T={exp}, got {p['b']}"
            assert -1 < p["rho"] < 1, f"rho must be in (-1,1) for T={exp}, got {p['rho']}"
            assert p["sigma"] > 0, f"sigma must be > 0 for T={exp}, got {p['sigma']}"
            # ATM total variance must be non-negative
            w_atm = p["a"] + p["b"] * p["sigma"]
            assert w_atm > 0, f"ATM total variance negative for T={exp}: {w_atm}"

    def test_fit_quality(self):
        """RMSE of fitted total variance vs market total variance must be < 5e-5."""
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        ivs = load_ivs()
        S = 5000.0
        r = 0.045
        q = 0.015

        for exp_str, p in params.items():
            exp = int(exp_str)
            T = exp / 365.0
            F = S * math.exp((r - q) * T)

            # Collect unique strikes with averaged IVs
            strike_ivs = {}
            for (e, strike, ot), iv in ivs.items():
                if e != exp:
                    continue
                if strike not in strike_ivs:
                    strike_ivs[strike] = []
                strike_ivs[strike].append(iv)

            sse = 0
            count = 0
            for strike, iv_list in strike_ivs.items():
                avg_iv = sum(iv_list) / len(iv_list)
                k = math.log(strike / F)
                w_market = avg_iv**2 * T
                w_svi = svi_total_variance(
                    k, p["a"], p["b"], p["rho"], p["m"], p["sigma"]
                )
                sse += (w_svi - w_market) ** 2
                count += 1

            rmse = math.sqrt(sse / count) if count > 0 else 0
            assert rmse < 5e-5, f"RMSE {rmse:.2e} too high for T={exp}d"

    def test_skew_direction(self):
        """SVI should show negative skew (rho < 0) for equity index options."""
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        for exp, p in params.items():
            assert p["rho"] < 0, f"Expected negative skew (rho < 0) for T={exp}, got {p['rho']}"


# ===========================================================================
# Arbitrage Checks
# ===========================================================================
class TestArbitrage:
    def test_file_exists(self):
        assert os.path.exists("/app/output/arbitrage_check.json"), "arbitrage_check.json missing"

    def test_required_keys(self):
        with open("/app/output/arbitrage_check.json") as f:
            result = json.load(f)
        assert "butterfly_free" in result
        assert "calendar_free" in result

    def test_butterfly_free(self):
        with open("/app/output/arbitrage_check.json") as f:
            result = json.load(f)
        assert result["butterfly_free"] is True, "Surface should be butterfly-arbitrage-free"

    def test_calendar_free(self):
        with open("/app/output/arbitrage_check.json") as f:
            result = json.load(f)
        assert result["calendar_free"] is True, "Surface should be calendar-arbitrage-free"

    def test_butterfly_independently(self):
        """Independently verify Durrleman's condition on the fitted surface."""
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)

        for exp_str, p in params.items():
            a, b, rho, m, sig = p["a"], p["b"], p["rho"], p["m"], p["sigma"]
            for k in [i * 0.005 for i in range(-100, 101)]:
                w = svi_total_variance(k, a, b, rho, m, sig)
                if w <= 1e-12:
                    continue
                wp = b * (rho + (k - m) / math.sqrt((k - m) ** 2 + sig**2))
                wpp = b * sig**2 / ((k - m) ** 2 + sig**2) ** 1.5
                g = (1 - k * wp / (2 * w)) ** 2 - wp**2 / 4 * (1 / w + 0.25) + wpp / 2
                assert g >= -1e-6, (
                    f"Butterfly arbitrage at k={k:.3f}, T={exp_str}: g={g:.8f}"
                )

    def test_calendar_independently(self):
        """Independently verify total variance is non-decreasing in T at each strike."""
        with open("/app/output/svi_params.json") as f:
            params = json.load(f)
        S = 5000.0
        r = 0.045
        q = 0.015
        strikes = [4200, 4500, 4800, 5000, 5200, 5500, 5800]
        expirations = sorted(params.keys(), key=int)

        for K in strikes:
            prev_w = None
            for exp_str in expirations:
                exp = int(exp_str)
                T = exp / 365.0
                F = S * math.exp((r - q) * T)
                k = math.log(K / F)
                p = params[exp_str]
                w = svi_total_variance(k, p["a"], p["b"], p["rho"], p["m"], p["sigma"])
                if prev_w is not None:
                    assert w >= prev_w - 1e-8, (
                        f"Calendar arbitrage at K={K}: w decreases from {prev_w:.8f} to {w:.8f}"
                    )
                prev_w = w


# ===========================================================================
# Exotic Option Prices
# ===========================================================================
class TestExoticPrices:
    def test_file_exists(self):
        assert os.path.exists("/app/output/exotic_prices.json"), "exotic_prices.json missing"

    def test_all_exotics_present(self):
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        expected = [
            "down_and_out_call_180",
            "up_and_out_call_365",
            "asian_call_180",
            "down_and_in_put_365",
        ]
        for name in expected:
            assert name in prices, f"Missing exotic: {name}"
            assert "price" in prices[name], f"Missing price for {name}"
            assert "std_error" in prices[name], f"Missing std_error for {name}"

    def test_prices_positive(self):
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        for name, data in prices.items():
            assert data["price"] > 0, f"Price must be > 0 for {name}, got {data['price']}"

    def test_standard_errors_reasonable(self):
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        for name, data in prices.items():
            rel_se = data["std_error"] / max(data["price"], 0.01)
            assert rel_se < 0.05, (
                f"Relative SE {rel_se:.4f} too large for {name}"
            )

    def test_down_out_call_bounds(self):
        """Down-and-out call < vanilla call (180d K=5000 vanilla ≈ 220)."""
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        doc = prices["down_and_out_call_180"]["price"]
        assert doc < 225, f"DOC {doc:.2f} should be < vanilla call (~220)"
        assert doc > 50, f"DOC {doc:.2f} unreasonably low"

    def test_up_out_call_bounds(self):
        """Up-and-out call < vanilla call (365d K=5000 vanilla ≈ 335)."""
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        uoc = prices["up_and_out_call_365"]["price"]
        assert uoc < 345, f"UOC {uoc:.2f} should be < vanilla call (~335)"
        assert uoc > 20, f"UOC {uoc:.2f} unreasonably low"

    def test_asian_call_bounds(self):
        """Asian call < vanilla call (Jensen's inequality). Vanilla ≈ 220."""
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        asian = prices["asian_call_180"]["price"]
        assert asian < 225, f"Asian {asian:.2f} should be < vanilla call (~220)"
        assert asian > 30, f"Asian {asian:.2f} unreasonably low"

    def test_down_in_put_bounds(self):
        """Down-and-in put < vanilla put (365d K=5000 vanilla ≈ 189)."""
        with open("/app/output/exotic_prices.json") as f:
            prices = json.load(f)
        dip = prices["down_and_in_put_365"]["price"]
        assert dip < 200, f"DIP {dip:.2f} should be < vanilla put (~189)"
        assert dip > 5, f"DIP {dip:.2f} unreasonably low"


# ===========================================================================
# Portfolio Greeks
# ===========================================================================
class TestPortfolioGreeks:
    def test_file_exists(self):
        assert os.path.exists("/app/output/portfolio_greeks.json"), "portfolio_greeks.json missing"

    def test_all_greeks_present(self):
        with open("/app/output/portfolio_greeks.json") as f:
            greeks = json.load(f)
        for g in ["delta", "gamma", "vega", "theta", "rho"]:
            assert g in greeks, f"Missing greek: {g}"
            assert isinstance(greeks[g], (int, float)), f"{g} is not numeric"

    def test_short_iron_condor_gamma(self):
        """Short iron condor must have negative gamma."""
        with open("/app/output/portfolio_greeks.json") as f:
            greeks = json.load(f)
        assert greeks["gamma"] < 0, f"Gamma should be < 0, got {greeks['gamma']}"

    def test_short_iron_condor_vega(self):
        """Short iron condor must have negative vega."""
        with open("/app/output/portfolio_greeks.json") as f:
            greeks = json.load(f)
        assert greeks["vega"] < 0, f"Vega should be < 0, got {greeks['vega']}"

    def test_short_iron_condor_theta(self):
        """Short iron condor must have positive theta (benefits from time decay)."""
        with open("/app/output/portfolio_greeks.json") as f:
            greeks = json.load(f)
        assert greeks["theta"] > 0, f"Theta should be > 0, got {greeks['theta']}"

    def test_near_delta_neutral(self):
        """Short iron condor should be approximately delta neutral."""
        with open("/app/output/portfolio_greeks.json") as f:
            greeks = json.load(f)
        assert abs(greeks["delta"]) < 5.0, (
            f"Delta should be near zero, got {greeks['delta']}"
        )


# ===========================================================================
# Put-Call Parity Cross-check
# ===========================================================================
class TestPutCallParity:
    def test_parity_holds(self):
        """C - P = S*exp(-qT) - K*exp(-rT) must hold for matched pairs."""
        ivs = load_ivs()
        S = 5000.0
        r = 0.045
        q = 0.015
        tested = 0
        for (exp, strike, opt_type), iv in ivs.items():
            if opt_type != "call":
                continue
            put_key = (exp, strike, "put")
            if put_key not in ivs:
                continue
            T = exp / 365.0
            call_price = bs_price(S, strike, T, r, q, iv, "call")
            put_price = bs_price(S, strike, T, r, q, ivs[put_key], "put")
            theoretical = S * math.exp(-q * T) - strike * math.exp(-r * T)
            parity_error = abs((call_price - put_price) - theoretical)
            assert parity_error < 1.0, (
                f"Put-call parity error {parity_error:.4f} at K={strike}, T={exp}d"
            )
            tested += 1
        assert tested >= 50, f"Expected >= 50 parity tests, got {tested}"
