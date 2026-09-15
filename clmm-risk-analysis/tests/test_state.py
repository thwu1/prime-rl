
import json
import math
import subprocess
import os
import pytest
from scipy.stats import norm


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer before any tests."""
    result = subprocess.run(
        ["python3", "/app/analyzer.py"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"analyzer.py failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def market_data():
    with open("/app/market_data.json") as f:
        return json.load(f)


def get_position(results, pos_id):
    for p in results["positions"]:
        if p["position_id"] == pos_id:
            return p
    pytest.fail(f"Position {pos_id} not found in results")


def get_price_entry(position, price):
    for entry in position["price_grid"]:
        if abs(entry["price"] - price) < 0.001:
            return entry
    pytest.fail(f"Price {price} not found in price_grid for position {position['position_id']}")


# ============================================================
# Position 0: L=10000, pa=81, pb=121, S0=100
# sqrt(81)=9, sqrt(121)=11, sqrt(100)=10
# ============================================================


class TestPosition0EntryValues:
    """Verify entry-point calculations for position 0."""

    def test_entry_x(self, results):
        p = get_position(results, 0)
        # x0 = 10000 * (1/10 - 1/11) = 10000/110 = 90.909090...
        expected = 10000.0 / 110.0
        assert p["entry_x"] == pytest.approx(expected, rel=1e-6)

    def test_entry_y(self, results):
        p = get_position(results, 0)
        # y0 = 10000 * (10 - 9) = 10000
        assert p["entry_y"] == pytest.approx(10000.0, rel=1e-6)

    def test_entry_value(self, results):
        p = get_position(results, 0)
        # V0 = (10000/110)*100 + 10000 = 1000000/110 + 10000
        expected = 1000000.0 / 110.0 + 10000.0
        assert p["entry_value"] == pytest.approx(expected, rel=1e-6)

    def test_delta_at_entry(self, results):
        p = get_position(results, 0)
        # delta = L*(1/sqrt(S0) - 1/sqrt(pb)) = 10000*(1/10 - 1/11) = 10000/110
        expected = 10000.0 / 110.0
        assert p["delta_at_entry"] == pytest.approx(expected, rel=1e-6)

    def test_gamma_at_entry(self, results):
        p = get_position(results, 0)
        # gamma = -L/(2*S^1.5) = -10000/(2*1000) = -5.0
        assert p["gamma_at_entry"] == pytest.approx(-5.0, rel=1e-6)


class TestPosition0PriceGrid:
    """Verify price grid calculations for position 0."""

    def test_below_range_S64(self, results):
        """S=64 (sqrt=8), below range."""
        p = get_position(results, 0)
        e = get_price_entry(p, 64.0)

        # x = L*(1/sqrt(pa) - 1/sqrt(pb)) = 10000*(1/9 - 1/11) = 10000*2/99
        exp_x = 10000.0 * 2.0 / 99.0
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(0.0, abs=1e-6)

        # V = x*S = (20000/99)*64
        exp_v = exp_x * 64.0
        assert e["value"] == pytest.approx(exp_v, rel=1e-6)

        # V_hold = x0*64 + y0 = (10000/110)*64 + 10000
        exp_hold = (10000.0 / 110.0) * 64.0 + 10000.0
        assert e["hold_value"] == pytest.approx(exp_hold, rel=1e-6)

        # IL
        exp_il = exp_v - exp_hold
        assert e["impermanent_loss"] == pytest.approx(exp_il, abs=0.01)

        # Delta below range = x (constant)
        assert e["delta"] == pytest.approx(exp_x, rel=1e-6)
        # Gamma below range = 0
        assert e["gamma"] == pytest.approx(0.0, abs=1e-6)

    def test_lower_bound_S81(self, results):
        """S=81 (sqrt=9), at lower bound."""
        p = get_position(results, 0)
        e = get_price_entry(p, 81.0)

        exp_x = 10000.0 * 2.0 / 99.0
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(0.0, abs=1e-6)

        exp_v = exp_x * 81.0
        assert e["value"] == pytest.approx(exp_v, rel=1e-6)

        exp_hold = (10000.0 / 110.0) * 81.0 + 10000.0
        exp_il = exp_v - exp_hold
        assert e["impermanent_loss"] == pytest.approx(-1000.0, abs=0.01)

    def test_in_range_S90_25(self, results):
        """S=90.25 (sqrt=9.5), in range."""
        p = get_position(results, 0)
        e = get_price_entry(p, 90.25)

        # x = L*(1/9.5 - 1/11) = 10000*(11-9.5)/(9.5*11) = 10000*1.5/104.5
        exp_x = 10000.0 * 1.5 / 104.5
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)

        # y = L*(9.5 - 9) = 5000
        assert e["y"] == pytest.approx(5000.0, rel=1e-6)

        # IL = L*(2*sqrt(S) - S/sqrt(S0) - sqrt(S0)) = 10000*(19 - 9.025 - 10) = -250
        assert e["impermanent_loss"] == pytest.approx(-250.0, abs=0.01)

        # Delta = L*(1/sqrt(S) - 1/sqrt(pb)) = x
        assert e["delta"] == pytest.approx(exp_x, rel=1e-6)

        # Gamma = -L/(2*S^1.5) = -10000/(2*90.25^1.5)
        exp_gamma = -10000.0 / (2.0 * 90.25 ** 1.5)
        assert e["gamma"] == pytest.approx(exp_gamma, rel=1e-4)

    def test_entry_price_S100(self, results):
        """S=100, entry price — IL must be 0."""
        p = get_position(results, 0)
        e = get_price_entry(p, 100.0)

        assert e["impermanent_loss"] == pytest.approx(0.0, abs=0.01)
        assert e["delta"] == pytest.approx(10000.0 / 110.0, rel=1e-6)
        assert e["gamma"] == pytest.approx(-5.0, rel=1e-6)

    def test_in_range_S110_25(self, results):
        """S=110.25 (sqrt=10.5), in range — symmetric IL with S=90.25."""
        p = get_position(results, 0)
        e = get_price_entry(p, 110.25)

        # IL is symmetric: also -250
        assert e["impermanent_loss"] == pytest.approx(-250.0, abs=0.01)

        # x = L*(1/10.5 - 1/11) = 10000*0.5/115.5 = 5000/115.5
        exp_x = 5000.0 / 115.5
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(15000.0, rel=1e-6)

        # Gamma = -10000/(2*110.25^1.5)
        exp_gamma = -10000.0 / (2.0 * 110.25 ** 1.5)
        assert e["gamma"] == pytest.approx(exp_gamma, rel=1e-4)

    def test_upper_bound_S121(self, results):
        """S=121 (sqrt=11), upper bound."""
        p = get_position(results, 0)
        e = get_price_entry(p, 121.0)

        assert e["x"] == pytest.approx(0.0, abs=1e-6)
        assert e["y"] == pytest.approx(20000.0, rel=1e-6)
        assert e["value"] == pytest.approx(20000.0, rel=1e-6)

        exp_hold = (10000.0 / 110.0) * 121.0 + 10000.0
        assert e["hold_value"] == pytest.approx(exp_hold, rel=1e-6)
        assert e["impermanent_loss"] == pytest.approx(-1000.0, abs=0.01)

    def test_above_range_S144(self, results):
        """S=144 (sqrt=12), above range."""
        p = get_position(results, 0)
        e = get_price_entry(p, 144.0)

        assert e["x"] == pytest.approx(0.0, abs=1e-6)
        assert e["y"] == pytest.approx(20000.0, rel=1e-6)
        assert e["value"] == pytest.approx(20000.0, rel=1e-6)
        assert e["delta"] == pytest.approx(0.0, abs=1e-6)
        assert e["gamma"] == pytest.approx(0.0, abs=1e-6)

        exp_hold = (10000.0 / 110.0) * 144.0 + 10000.0
        exp_il = 20000.0 - exp_hold
        assert e["impermanent_loss"] == pytest.approx(exp_il, abs=0.01)


# ============================================================
# Position 1: L=5000, pa=400, pb=900, S0=625
# sqrt(400)=20, sqrt(900)=30, sqrt(625)=25
# ============================================================


class TestPosition1EntryValues:
    """Verify entry-point calculations for position 1."""

    def test_entry_x(self, results):
        p = get_position(results, 1)
        # x0 = 5000*(1/25 - 1/30) = 5000*(6-5)/150 = 5000/150
        expected = 5000.0 / 150.0
        assert p["entry_x"] == pytest.approx(expected, rel=1e-6)

    def test_entry_y(self, results):
        p = get_position(results, 1)
        # y0 = 5000*(25-20) = 25000
        assert p["entry_y"] == pytest.approx(25000.0, rel=1e-6)

    def test_entry_value(self, results):
        p = get_position(results, 1)
        expected = (5000.0 / 150.0) * 625.0 + 25000.0
        assert p["entry_value"] == pytest.approx(expected, rel=1e-6)

    def test_delta_at_entry(self, results):
        p = get_position(results, 1)
        expected = 5000.0 / 150.0
        assert p["delta_at_entry"] == pytest.approx(expected, rel=1e-6)

    def test_gamma_at_entry(self, results):
        p = get_position(results, 1)
        # gamma = -5000/(2*625^1.5) = -5000/(2*15625) = -0.16
        assert p["gamma_at_entry"] == pytest.approx(-0.16, rel=1e-6)


class TestPosition1PriceGrid:
    """Verify price grid calculations for position 1."""

    def test_below_range_S324(self, results):
        """S=324 (sqrt=18), below range."""
        p = get_position(results, 1)
        e = get_price_entry(p, 324.0)

        # x = 5000*(1/20 - 1/30) = 5000/60
        exp_x = 5000.0 / 60.0
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(0.0, abs=1e-6)

        exp_v = exp_x * 324.0  # = 27000
        assert e["value"] == pytest.approx(27000.0, rel=1e-6)

        exp_hold = (5000.0 / 150.0) * 324.0 + 25000.0  # = 10800 + 25000 = 35800
        assert e["hold_value"] == pytest.approx(35800.0, rel=1e-6)
        assert e["impermanent_loss"] == pytest.approx(-8800.0, abs=0.01)
        assert e["delta"] == pytest.approx(exp_x, rel=1e-6)
        assert e["gamma"] == pytest.approx(0.0, abs=1e-6)

    def test_lower_bound_S400(self, results):
        """S=400, lower bound."""
        p = get_position(results, 1)
        e = get_price_entry(p, 400.0)

        assert e["impermanent_loss"] == pytest.approx(-5000.0, abs=0.01)

    def test_in_range_S529(self, results):
        """S=529 (sqrt=23), in range."""
        p = get_position(results, 1)
        e = get_price_entry(p, 529.0)

        # x = 5000*(1/23 - 1/30) = 5000*7/690
        exp_x = 5000.0 * 7.0 / 690.0
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(15000.0, rel=1e-6)

        # IL = -L*sqrt(S0)*(sqrt(S/S0)-1)^2 = -5000*25*(23/25-1)^2 = -125000*(2/25)^2 = -800
        assert e["impermanent_loss"] == pytest.approx(-800.0, abs=0.01)

        # Gamma = -5000/(2*529^1.5) = -5000/(2*12167)
        exp_gamma = -5000.0 / (2.0 * 529.0 ** 1.5)
        assert e["gamma"] == pytest.approx(exp_gamma, rel=1e-4)

    def test_entry_price_S625(self, results):
        """S=625, entry price."""
        p = get_position(results, 1)
        e = get_price_entry(p, 625.0)

        assert e["impermanent_loss"] == pytest.approx(0.0, abs=0.01)
        assert e["gamma"] == pytest.approx(-0.16, rel=1e-6)

    def test_in_range_S784(self, results):
        """S=784 (sqrt=28), in range."""
        p = get_position(results, 1)
        e = get_price_entry(p, 784.0)

        # x = 5000*(1/28 - 1/30) = 5000*2/840 = 10000/840
        exp_x = 10000.0 / 840.0
        assert e["x"] == pytest.approx(exp_x, rel=1e-6)
        assert e["y"] == pytest.approx(40000.0, rel=1e-6)

        # IL = -5000*25*(28/25-1)^2 = -125000*(3/25)^2 = -125000*9/625 = -1800
        assert e["impermanent_loss"] == pytest.approx(-1800.0, abs=0.01)

    def test_upper_bound_S900(self, results):
        """S=900, upper bound."""
        p = get_position(results, 1)
        e = get_price_entry(p, 900.0)

        assert e["x"] == pytest.approx(0.0, abs=1e-6)
        assert e["y"] == pytest.approx(50000.0, rel=1e-6)
        assert e["impermanent_loss"] == pytest.approx(-5000.0, abs=0.01)

    def test_above_range_S1024(self, results):
        """S=1024 (sqrt=32), above range."""
        p = get_position(results, 1)
        e = get_price_entry(p, 1024.0)

        assert e["x"] == pytest.approx(0.0, abs=1e-6)
        assert e["y"] == pytest.approx(50000.0, rel=1e-6)
        assert e["delta"] == pytest.approx(0.0, abs=1e-6)
        assert e["gamma"] == pytest.approx(0.0, abs=1e-6)

        exp_hold = (5000.0 / 150.0) * 1024.0 + 25000.0
        exp_il = 50000.0 - exp_hold
        assert e["impermanent_loss"] == pytest.approx(exp_il, abs=0.01)


# ============================================================
# Break-even volatility tests
# ============================================================


class TestBreakEvenVolatility:
    def test_pos0_fee_income(self, results):
        p = get_position(results, 0)
        # fee_income = 0.003 * 500000 * 10000 / 1000000 = 15.0
        assert p["daily_fee_income"] == pytest.approx(15.0, rel=1e-6)

    def test_pos0_break_even_vol(self, results):
        p = get_position(results, 0)
        # sigma_be = sqrt(4 * 365 * 15 / (10000 * 10)) = sqrt(0.219)
        expected = math.sqrt(4.0 * 365.0 * 15.0 / (10000.0 * math.sqrt(100.0)))
        assert p["break_even_volatility_annual"] == pytest.approx(expected, rel=1e-4)

    def test_pos1_fee_income(self, results):
        p = get_position(results, 1)
        # fee_income = 0.003 * 2000000 * 5000 / 500000 = 60.0
        assert p["daily_fee_income"] == pytest.approx(60.0, rel=1e-6)

    def test_pos1_break_even_vol(self, results):
        p = get_position(results, 1)
        # sigma_be = sqrt(4 * 365 * 60 / (5000 * 25)) = sqrt(0.7008)
        expected = math.sqrt(4.0 * 365.0 * 60.0 / (5000.0 * math.sqrt(625.0)))
        assert p["break_even_volatility_annual"] == pytest.approx(expected, rel=1e-4)


# ============================================================
# Gamma hedge straddle count tests
# ============================================================


class TestGammaHedge:
    @staticmethod
    def _compute_expected_straddles(gamma_lp, S, sigma, r, T):
        """Independently compute expected straddle count."""
        d1 = (r + sigma ** 2 / 2.0) * math.sqrt(T) / sigma
        phi_d1 = norm.pdf(d1)
        gamma_straddle = 2.0 * phi_d1 / (S * sigma * math.sqrt(T))
        return abs(gamma_lp) / gamma_straddle

    def test_pos0_straddle_count(self, results, market_data):
        p = get_position(results, 0)
        r = market_data["risk_free_rate"]
        sigma = market_data["implied_volatility"]
        T = market_data["option_expiry_days"] / market_data["days_per_year"]

        expected = self._compute_expected_straddles(-5.0, 100.0, sigma, r, T)
        assert p["hedge_straddles_count"] == pytest.approx(expected, rel=1e-3)

    def test_pos1_straddle_count(self, results, market_data):
        p = get_position(results, 1)
        r = market_data["risk_free_rate"]
        sigma = market_data["implied_volatility"]
        T = market_data["option_expiry_days"] / market_data["days_per_year"]

        expected = self._compute_expected_straddles(-0.16, 625.0, sigma, r, T)
        assert p["hedge_straddles_count"] == pytest.approx(expected, rel=1e-3)


# ============================================================
# Structural tests
# ============================================================


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_has_positions_key(self, results):
        assert "positions" in results

    def test_two_positions(self, results):
        assert len(results["positions"]) == 2

    def test_pos0_has_required_keys(self, results):
        p = get_position(results, 0)
        required = [
            "position_id", "entry_x", "entry_y", "entry_value",
            "delta_at_entry", "gamma_at_entry", "daily_fee_income",
            "break_even_volatility_annual", "hedge_straddles_count",
            "price_grid",
        ]
        for key in required:
            assert key in p, f"Missing key: {key}"

    def test_pos0_price_grid_length(self, results):
        p = get_position(results, 0)
        assert len(p["price_grid"]) == 7

    def test_pos1_price_grid_length(self, results):
        p = get_position(results, 1)
        assert len(p["price_grid"]) == 7

    def test_price_grid_entry_keys(self, results):
        p = get_position(results, 0)
        entry = p["price_grid"][0]
        required = ["price", "x", "y", "value", "hold_value",
                     "impermanent_loss", "delta", "gamma"]
        for key in required:
            assert key in entry, f"Missing price_grid key: {key}"


# ============================================================
# Consistency checks across the price grid
# ============================================================


class TestConsistency:
    """Cross-check relationships that must hold by construction."""

    def test_il_always_nonpositive_pos0(self, results):
        """IL is always <= 0 for an LP position."""
        p = get_position(results, 0)
        for e in p["price_grid"]:
            assert e["impermanent_loss"] <= 0.01, \
                f"IL should be <= 0 at price {e['price']}, got {e['impermanent_loss']}"

    def test_il_always_nonpositive_pos1(self, results):
        p = get_position(results, 1)
        for e in p["price_grid"]:
            assert e["impermanent_loss"] <= 0.01, \
                f"IL should be <= 0 at price {e['price']}, got {e['impermanent_loss']}"

    def test_value_equals_x_times_s_plus_y(self, results):
        """V(S) = x*S + y for all prices."""
        for pos_id in [0, 1]:
            p = get_position(results, pos_id)
            for e in p["price_grid"]:
                expected_v = e["x"] * e["price"] + e["y"]
                assert e["value"] == pytest.approx(expected_v, rel=1e-6), \
                    f"V != x*S+y at price {e['price']} for pos {pos_id}"

    def test_gamma_nonpositive_in_range_pos0(self, results):
        """Gamma is <= 0 in range (LP is short gamma)."""
        p = get_position(results, 0)
        for e in p["price_grid"]:
            if 81 <= e["price"] <= 121:
                assert e["gamma"] <= 1e-8, \
                    f"Gamma should be <= 0 in range at {e['price']}"

    def test_break_even_vol_positive(self, results):
        for pos_id in [0, 1]:
            p = get_position(results, pos_id)
            assert p["break_even_volatility_annual"] > 0

    def test_hedge_straddles_positive(self, results):
        for pos_id in [0, 1]:
            p = get_position(results, pos_id)
            assert p["hedge_straddles_count"] > 0
