import json
import math
import os
import pytest


RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── Structure tests ──────────────────────────────────────────────────

class TestStructure:
    def test_top_level_keys(self, results):
        assert "bs_swing" in results, "Missing 'bs_swing' key"
        assert "kluge" in results, "Missing 'kluge' key"
        assert "convergence" in results, "Missing 'convergence' key"

    def test_bs_swing_length(self, results):
        assert len(results["bs_swing"]) == 12, \
            f"Expected 12 bs_swing entries, got {len(results['bs_swing'])}"

    def test_bs_swing_entry_keys(self, results):
        required = {"n", "swing_price", "bermudan_price", "european_prices",
                     "upper_bound", "lower_bound", "upper_ok", "lower_ok"}
        for entry in results["bs_swing"]:
            missing = required - set(entry.keys())
            assert not missing, f"Missing keys in bs_swing entry n={entry.get('n')}: {missing}"

    def test_kluge_keys(self, results):
        required = {"std_dev", "skewness", "excess_kurtosis", "bs_price",
                     "ccs3_price", "ccs4_price", "rubinstein_price",
                     "mc_price", "mc_error", "implied_vols"}
        missing = required - set(results["kluge"].keys())
        assert not missing, f"Missing kluge keys: {missing}"

    def test_implied_vol_keys(self, results):
        required = {"bs", "ccs3", "ccs4", "rubinstein"}
        missing = required - set(results["kluge"]["implied_vols"].keys())
        assert not missing, f"Missing implied_vol keys: {missing}"

    def test_convergence_keys(self, results):
        for key in ["n1", "n6", "n12"]:
            assert key in results["convergence"], \
                f"Missing convergence key: {key}"
            required = {"coarse", "medium", "fine", "richardson",
                        "convergence_ratio"}
            missing = required - set(results["convergence"][key].keys())
            assert not missing, \
                f"Missing keys in convergence[{key}]: {missing}"


# ── BS Swing Option Bounds ───────────────────────────────────────────

class TestBSSwingBounds:
    def test_upper_bounds_hold(self, results):
        for entry in results["bs_swing"]:
            n = entry["n"]
            assert entry["upper_ok"], (
                f"Upper bound violated for n={n}: "
                f"swing={entry['swing_price']:.6f}, bound={entry['upper_bound']:.6f}")

    def test_lower_bounds_hold(self, results):
        for entry in results["bs_swing"]:
            n = entry["n"]
            assert entry["lower_ok"], (
                f"Lower bound violated for n={n}: "
                f"swing={entry['swing_price']:.6f}, bound={entry['lower_bound']:.6f}")

    def test_swing_prices_positive(self, results):
        for entry in results["bs_swing"]:
            assert entry["swing_price"] > 0, \
                f"Swing price not positive for n={entry['n']}"

    def test_bermudan_price_positive(self, results):
        assert results["bs_swing"][0]["bermudan_price"] > 0

    def test_swing_monotonicity(self, results):
        """More exercise rights cannot decrease swing value."""
        prices = [e["swing_price"] for e in results["bs_swing"]]
        for i in range(1, len(prices)):
            assert prices[i] >= prices[i - 1] - 0.01, (
                f"Swing price not non-decreasing: "
                f"n={i}: {prices[i-1]:.6f} > n={i+1}: {prices[i]:.6f}")

    def test_european_prices_count(self, results):
        for entry in results["bs_swing"]:
            assert len(entry["european_prices"]) == 12, \
                f"Expected 12 European prices for n={entry['n']}"

    def test_european_prices_positive(self, results):
        for p in results["bs_swing"][0]["european_prices"]:
            assert p > 0, "European price should be positive"

    def test_upper_bound_is_n_times_bermudan(self, results):
        """Verify upper_bound = n * bermudan_price."""
        for entry in results["bs_swing"]:
            expected = entry["n"] * entry["bermudan_price"]
            assert abs(entry["upper_bound"] - expected) < 1e-10, (
                f"upper_bound mismatch for n={entry['n']}: "
                f"got {entry['upper_bound']}, expected {expected}")

    def test_lower_bound_is_sum_of_last_n_euros(self, results):
        """Verify lower_bound = sum of last n European prices."""
        for entry in results["bs_swing"]:
            n = entry["n"]
            euros = entry["european_prices"]
            expected = sum(euros[len(euros) - n:])
            assert abs(entry["lower_bound"] - expected) < 1e-10, (
                f"lower_bound mismatch for n={n}: "
                f"got {entry['lower_bound']}, expected {expected}")

    def test_swing_bounded_by_n_times_bermudan_numerically(self, results):
        """Direct numerical check of upper bound (tolerance 0.01)."""
        for entry in results["bs_swing"]:
            n = entry["n"]
            assert entry["swing_price"] <= n * entry["bermudan_price"] + 0.01, (
                f"Swing price exceeds n*bermudan+tol for n={n}")

    def test_swing_exceeds_lower_bound_numerically(self, results):
        """Direct numerical check of lower bound (tolerance 0.04)."""
        for entry in results["bs_swing"]:
            n = entry["n"]
            euros = entry["european_prices"]
            lb = sum(euros[len(euros) - n:])
            assert entry["swing_price"] >= lb - 0.04, (
                f"Swing price below lower bound for n={n}")


# ── Kluge Cumulants ──────────────────────────────────────────────────

class TestKlugeCumulants:
    """Independently compute expected cumulants and compare."""

    @staticmethod
    def _expected_cumulants():
        t = 182.0 / 365.0
        alpha, sig = 4.0, 1.0
        beta, eta, lam = 5.0, 5.0, 4.0

        var = ((2 - 2 * math.exp(-2 * beta * t)) * lam / (beta * eta ** 2) +
               (1 - math.exp(-2 * alpha * t)) * sig ** 2 / alpha) / 2.0
        std_dev = math.sqrt(var)

        g1 = ((2 - 2 * math.exp(-3 * beta * t)) * lam /
              (beta * eta ** 3)) / std_dev ** 3

        e_2at = math.exp(2 * alpha * t)
        e_2bt = math.exp(2 * beta * t)
        inner = (2 * alpha * e_2at * (-1 + e_2bt) * lam +
                 beta * e_2bt * (-1 + e_2at) * eta ** 2 * sig ** 2)
        term1 = inner ** 2
        term2 = (16 * alpha ** 2 * beta *
                 math.exp((5 * alpha + 3 * beta) * t) * lam *
                 math.sinh(2 * beta * t))
        num = 3 * (math.exp((alpha + beta) * t) * term1 + term2)
        denom = (4 * alpha ** 2 * beta ** 2 *
                 math.exp(5 * (alpha + beta) * t) * eta ** 4)
        g2 = num / denom / std_dev ** 4 - 3.0

        return std_dev, g1, g2

    def test_std_dev(self, results):
        expected_std, _, _ = self._expected_cumulants()
        got = results["kluge"]["std_dev"]
        assert abs(got - expected_std) < 1e-8, \
            f"std_dev: got {got}, expected {expected_std}"

    def test_skewness(self, results):
        _, expected_g1, _ = self._expected_cumulants()
        got = results["kluge"]["skewness"]
        assert abs(got - expected_g1) < 1e-8, \
            f"skewness: got {got}, expected {expected_g1}"

    def test_excess_kurtosis(self, results):
        _, _, expected_g2 = self._expected_cumulants()
        got = results["kluge"]["excess_kurtosis"]
        assert abs(got - expected_g2) < 1e-6, \
            f"excess_kurtosis: got {got}, expected {expected_g2}"


# ── Kluge Moment-Matching Prices ─────────────────────────────────────

class TestKlugeMomentMatching:
    """Independently compute moment-matching prices and compare."""

    @staticmethod
    def _expected_prices():
        from scipy.stats import norm

        t = 182.0 / 365.0
        alpha, sig = 4.0, 1.0
        beta, eta, lam = 5.0, 5.0, 4.0
        f0, strike = 30.0, 30.0

        # Cumulants
        var = ((2 - 2 * math.exp(-2 * beta * t)) * lam / (beta * eta ** 2) +
               (1 - math.exp(-2 * alpha * t)) * sig ** 2 / alpha) / 2.0
        std_dev = math.sqrt(var)

        g1 = ((2 - 2 * math.exp(-3 * beta * t)) * lam /
              (beta * eta ** 3)) / std_dev ** 3

        e_2at = math.exp(2 * alpha * t)
        e_2bt = math.exp(2 * beta * t)
        inner = (2 * alpha * e_2at * (-1 + e_2bt) * lam +
                 beta * e_2bt * (-1 + e_2at) * eta ** 2 * sig ** 2)
        term1 = inner ** 2
        term2 = (16 * alpha ** 2 * beta *
                 math.exp((5 * alpha + 3 * beta) * t) * lam *
                 math.sinh(2 * beta * t))
        num = 3 * (math.exp((alpha + beta) * t) * term1 + term2)
        denom = (4 * alpha ** 2 * beta ** 2 *
                 math.exp(5 * (alpha + beta) * t) * eta ** 4)
        g2 = num / denom / std_dev ** 4 - 3.0

        # Black's formula
        d = (math.log(f0 / strike) + 0.5 * std_dev ** 2) / std_dev
        n_d = norm.pdf(d)
        bs_npv = f0 * norm.cdf(d) - strike * norm.cdf(d - std_dev)

        # Gram-Charlier expansion terms
        q3 = (1.0 / math.factorial(3)) * f0 * std_dev * \
             (2 * std_dev - d) * n_d
        q4 = (1.0 / math.factorial(4)) * f0 * std_dev * \
             (d ** 2 - 3 * d * std_dev - 1) * n_d
        q5 = (10.0 / math.factorial(6)) * f0 * std_dev * \
             (d ** 4 - 5 * d ** 3 * std_dev - 6 * d ** 2 +
              15 * d * std_dev + 3) * n_d

        ccs3 = bs_npv + g1 * q3
        ccs4 = ccs3 + g2 * q4
        cr = ccs4 + g1 ** 2 * q5

        return bs_npv, ccs3, ccs4, cr

    def test_bs_price(self, results):
        bs, _, _, _ = self._expected_prices()
        got = results["kluge"]["bs_price"]
        assert abs(got - bs) < 1e-6, \
            f"BS price: got {got}, expected {bs}"

    def test_ccs3_price(self, results):
        _, ccs3, _, _ = self._expected_prices()
        got = results["kluge"]["ccs3_price"]
        assert abs(got - ccs3) < 1e-6, \
            f"CCS3 price: got {got}, expected {ccs3}"

    def test_ccs4_price(self, results):
        _, _, ccs4, _ = self._expected_prices()
        got = results["kluge"]["ccs4_price"]
        assert abs(got - ccs4) < 1e-6, \
            f"CCS4 price: got {got}, expected {ccs4}"

    def test_rubinstein_price(self, results):
        _, _, _, cr = self._expected_prices()
        got = results["kluge"]["rubinstein_price"]
        assert abs(got - cr) < 1e-6, \
            f"Rubinstein price: got {got}, expected {cr}"


# ── Kluge Monte Carlo ────────────────────────────────────────────────

class TestKlugeMC:
    def test_mc_positive(self, results):
        assert results["kluge"]["mc_price"] > 0, "MC price should be positive"

    def test_mc_error_positive(self, results):
        assert results["kluge"]["mc_error"] > 0, "MC error should be positive"

    def test_mc_error_reasonable(self, results):
        """MC error should be small relative to price with 200K paths."""
        mc = results["kluge"]["mc_price"]
        err = results["kluge"]["mc_error"]
        assert err / mc < 0.05, \
            f"MC error too large relative to price: {err}/{mc} = {err/mc:.4f}"

    def test_mc_agrees_with_rubinstein(self, results):
        mc = results["kluge"]["mc_price"]
        mc_err = results["kluge"]["mc_error"]
        rubinstein = results["kluge"]["rubinstein_price"]
        assert abs(mc - rubinstein) < 3 * mc_err, (
            f"MC ({mc:.4f}) doesn't agree with Rubinstein ({rubinstein:.4f}) "
            f"within 3*sigma ({3*mc_err:.4f})")


# ── Kluge Implied Vols ───────────────────────────────────────────────

class TestKlugeImpliedVols:
    def test_implied_vols_positive(self, results):
        for method, vol in results["kluge"]["implied_vols"].items():
            assert vol > 0, f"Implied vol for {method} is not positive: {vol}"

    def test_implied_vols_reasonable_range(self, results):
        for method, vol in results["kluge"]["implied_vols"].items():
            assert 0.1 < vol < 10.0, \
                f"Implied vol for {method} out of range: {vol}"

    def test_implied_vols_distinct(self, results):
        """Different moment-matching orders produce distinct implied vols."""
        ivols = results["kluge"]["implied_vols"]
        vals = list(ivols.values())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                assert abs(vals[i] - vals[j]) > 1e-10, (
                    f"Implied vols should be distinct: {list(ivols.keys())[i]}="
                    f"{vals[i]}, {list(ivols.keys())[j]}={vals[j]}")

    def test_implied_vol_roundtrip(self, results):
        """Each implied vol must reproduce its price through Black's call formula."""
        from scipy.stats import norm as sp_norm

        f0, strike, t = 30.0, 30.0, 182.0 / 365.0
        kluge = results["kluge"]
        price_map = {"bs": "bs_price", "ccs3": "ccs3_price",
                     "ccs4": "ccs4_price", "rubinstein": "rubinstein_price"}

        for method, price_key in price_map.items():
            vol = kluge["implied_vols"][method]
            total_sd = vol * math.sqrt(t)
            d = (math.log(f0 / strike) + 0.5 * total_sd ** 2) / total_sd
            reprice = f0 * sp_norm.cdf(d) - strike * sp_norm.cdf(d - total_sd)
            original = kluge[price_key]

            assert abs(reprice - original) < 1e-4, (
                f"Implied vol roundtrip failed for {method}: "
                f"repriced={reprice:.6f}, original={original:.6f}, "
                f"vol={vol:.6f}")


# ── Convergence / Richardson Extrapolation ───────────────────────────

class TestConvergence:
    def test_medium_matches_bs_swing(self, results):
        """Medium grid (50x200) prices must equal bs_swing swing prices."""
        bs = results["bs_swing"]
        conv = results["convergence"]
        for n, key in [(1, "n1"), (6, "n6"), (12, "n12")]:
            bs_price = bs[n - 1]["swing_price"]
            medium_price = conv[key]["medium"]
            assert abs(bs_price - medium_price) < 1e-10, (
                f"Medium price mismatch for n={n}: "
                f"bs_swing={bs_price:.10f}, convergence={medium_price:.10f}")

    def test_prices_positive(self, results):
        """All grid prices and Richardson estimates must be positive."""
        for key in ["n1", "n6", "n12"]:
            for ptype in ["coarse", "medium", "fine", "richardson"]:
                val = results["convergence"][key][ptype]
                assert val > 0, (
                    f"convergence[{key}][{ptype}] not positive: {val}")

    def test_richardson_formula_p2(self, results):
        """Richardson with p=2, k=2: richardson = (4*fine - medium) / 3."""
        for key in ["n1", "n6", "n12"]:
            medium = results["convergence"][key]["medium"]
            fine = results["convergence"][key]["fine"]
            richardson = results["convergence"][key]["richardson"]
            expected = (4.0 * fine - medium) / 3.0
            assert abs(richardson - expected) < 1e-10, (
                f"Richardson formula mismatch for {key}: "
                f"got {richardson:.10f}, expected {expected:.10f} "
                f"(4*fine-medium)/3")

    def test_convergence_ratio_range(self, results):
        """For 2nd-order scheme, ratio (coarse-medium)/(medium-fine) > 1."""
        for key in ["n1", "n6", "n12"]:
            ratio = results["convergence"][key]["convergence_ratio"]
            assert 1.2 < ratio < 15.0, (
                f"Convergence ratio out of range for {key}: {ratio:.4f} "
                f"(expected > 1 for convergent scheme)")

    def test_grid_refinement_improves(self, results):
        """Fine grid should be closer to Richardson estimate than coarse."""
        for key in ["n1", "n6", "n12"]:
            coarse = results["convergence"][key]["coarse"]
            fine = results["convergence"][key]["fine"]
            richardson = results["convergence"][key]["richardson"]
            assert abs(fine - richardson) < abs(coarse - richardson), (
                f"Grid refinement not improving for {key}: "
                f"|fine-rich|={abs(fine-richardson):.8f} >= "
                f"|coarse-rich|={abs(coarse-richardson):.8f}")

    def test_monotone_refinement(self, results):
        """Successive grids should converge (differences shrink)."""
        for key in ["n1", "n6", "n12"]:
            coarse = results["convergence"][key]["coarse"]
            medium = results["convergence"][key]["medium"]
            fine = results["convergence"][key]["fine"]
            assert abs(medium - fine) < abs(coarse - medium), (
                f"Convergence not monotone for {key}: "
                f"|medium-fine|={abs(medium-fine):.8f} >= "
                f"|coarse-medium|={abs(coarse-medium):.8f}")
