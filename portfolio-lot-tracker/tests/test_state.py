"""Tests for portfolio lot-tracking engine with wash-sale and holding-period analysis.

Verifies FIFO/LIFO/HIFO lot matching, wash-sale detection and cost-basis
adjustment, holding-period classification, realized/unrealized gains,
market valuation, and ledger-CLI cross-validation.
"""

import json
import os
import subprocess

import pytest

PORTFOLIO = "/app/portfolio"
TOL = 0.015  # dollar tolerance for floating-point rounding


def run(*args):
    """Run the portfolio tool and return parsed JSON."""
    result = subprocess.run(
        [PORTFOLIO] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"portfolio {' '.join(args)} failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )
    return json.loads(result.stdout)


def approx(v):
    return pytest.approx(v, abs=TOL)


# ---------------------------------------------------------------------------
# Executable sanity
# ---------------------------------------------------------------------------
class TestExecutable:
    def test_exists(self):
        assert os.path.isfile(PORTFOLIO), f"{PORTFOLIO} does not exist"

    def test_executable(self):
        assert os.access(PORTFOLIO, os.X_OK), f"{PORTFOLIO} is not executable"


# ---------------------------------------------------------------------------
# FIFO lots — all transactions
# ---------------------------------------------------------------------------
class TestLotsFIFO:
    def test_count(self):
        data = run("lots")
        assert len(data["lots"]) == 11

    def test_lot_details(self):
        lots = run("lots")["lots"]
        # Sorted by (acquisition_date, commodity, cost_per_unit)
        expected = [
            ("TSLA", 10, 196.81, 1968.10, "2023/02/06"),
            ("AAPL", 10, 165.50, 1655.00, "2023/03/15"),
            ("MSFT", 4, 288.30, 1153.20, "2023/04/10"),
            ("VTI", 5, 206.00, 1030.00, "2023/04/20"),
            ("AAPL", 20, 142.30, 2846.00, "2023/05/20"),
            ("TSLA", 15, 251.61, 3774.15, "2023/06/01"),
            ("AAPL", 35, 191.94, 6717.90, "2023/07/20"),
            ("MSFT", 6, 343.80, 2062.80, "2023/09/05"),
            ("VTI", 20, 213.52, 4270.40, "2023/09/20"),
            ("VTI", 25, 229.30, 5732.50, "2023/11/25"),
            ("AAPL", 15, 194.27, 2914.05, "2023/12/10"),
        ]
        assert len(lots) == len(expected)
        for lot, (com, qty, cpu, tc, ad) in zip(lots, expected):
            assert lot["commodity"] == com
            assert lot["quantity"] == approx(qty)
            assert lot["cost_per_unit"] == approx(cpu)
            assert lot["total_cost"] == approx(tc)
            assert lot["acquisition_date"] == ad

    def test_wash_adjusted_tsla(self):
        """TSLA replacement lot cost must reflect wash sale adjustment."""
        lots = run("lots")["lots"]
        tsla_lots = [l for l in lots if l["commodity"] == "TSLA"]
        replacement = [l for l in tsla_lots
                       if l["acquisition_date"] == "2023/06/01"][0]
        # Original cost $213.10 + wash adjustment $577.65/15 = $251.61
        assert replacement["cost_per_unit"] == approx(251.61)

    def test_wash_adjusted_vti(self):
        """VTI replacement lot cost must reflect wash sale adjustment."""
        lots = run("lots")["lots"]
        vti_lots = [l for l in lots if l["commodity"] == "VTI"]
        replacement = [l for l in vti_lots
                       if l["acquisition_date"] == "2023/11/25"][0]
        # Original $228.30 + $25.00/25 = $229.30
        assert replacement["cost_per_unit"] == approx(229.30)


# ---------------------------------------------------------------------------
# LIFO lots — all transactions
# ---------------------------------------------------------------------------
class TestLotsLIFO:
    def test_count(self):
        data = run("lots", "--method", "lifo")
        assert len(data["lots"]) == 10

    def test_lot_details(self):
        lots = run("lots", "--method", "lifo")["lots"]
        expected = [
            ("AAPL", 50, 131.86, 6593.00, "2023/01/18"),
            ("TSLA", 10, 196.81, 1968.10, "2023/02/06"),
            ("AAPL", 15, 165.50, 2482.50, "2023/03/15"),
            ("MSFT", 4, 288.30, 1153.20, "2023/04/10"),
            ("VTI", 25, 206.00, 5150.00, "2023/04/20"),
            ("TSLA", 15, 251.61, 3774.15, "2023/06/01"),
            ("AAPL", 10, 191.94, 1919.40, "2023/07/20"),
            ("MSFT", 6, 343.80, 2062.80, "2023/09/05"),
            ("VTI", 25, 233.60, 5839.93, "2023/11/25"),
            ("AAPL", 5, 194.27, 971.35, "2023/12/10"),
        ]
        assert len(lots) == len(expected)
        for lot, (com, qty, cpu, tc, ad) in zip(lots, expected):
            assert lot["commodity"] == com
            assert lot["quantity"] == approx(qty)
            assert lot["cost_per_unit"] == approx(cpu)
            assert lot["total_cost"] == approx(tc)
            assert lot["acquisition_date"] == ad

    def test_vti_wash_adjusted_higher_than_fifo(self):
        """LIFO VTI sell produces larger loss, so replacement lot has higher
        adjusted cost than under FIFO."""
        fifo_lots = run("lots")["lots"]
        lifo_lots = run("lots", "--method", "lifo")["lots"]

        fifo_vti = [l for l in fifo_lots
                    if l["commodity"] == "VTI"
                    and l["acquisition_date"] == "2023/11/25"][0]
        lifo_vti = [l for l in lifo_lots
                    if l["commodity"] == "VTI"
                    and l["acquisition_date"] == "2023/11/25"][0]

        # FIFO: $229.30 vs LIFO: $233.60
        assert lifo_vti["cost_per_unit"] > fifo_vti["cost_per_unit"] + 1.0


# ---------------------------------------------------------------------------
# HIFO lots — all transactions
# ---------------------------------------------------------------------------
class TestLotsHIFO:
    def test_count(self):
        data = run("lots", "--method", "hifo")
        assert len(data["lots"]) == 10

    def test_differs_from_lifo(self):
        """HIFO and LIFO produce different AAPL lots because HIFO consumes
        highest-cost lots while LIFO consumes most-recent."""
        hifo_lots = run("lots", "--method", "hifo")["lots"]
        lifo_lots = run("lots", "--method", "lifo")["lots"]

        hifo_aapl = sorted(
            [(l["acquisition_date"], l["quantity"], l["cost_per_unit"])
             for l in hifo_lots if l["commodity"] == "AAPL"]
        )
        lifo_aapl = sorted(
            [(l["acquisition_date"], l["quantity"], l["cost_per_unit"])
             for l in lifo_lots if l["commodity"] == "AAPL"]
        )
        assert hifo_aapl != lifo_aapl

    def test_hifo_specific_lots(self):
        """Under HIFO, AAPL should have [01/18:50], [05/20:15], [07/20:10],
        [12/10:5] — different from LIFO which has [01/18:50], [03/15:15]."""
        lots = run("lots", "--method", "hifo")["lots"]
        aapl = [(l["acquisition_date"], l["quantity"], l["cost_per_unit"])
                for l in lots if l["commodity"] == "AAPL"]
        aapl.sort()
        assert len(aapl) == 4
        assert aapl[0] == ("2023/01/18", approx(50), approx(131.86))
        assert aapl[1] == ("2023/05/20", approx(15), approx(142.30))
        assert aapl[2] == ("2023/07/20", approx(10), approx(191.94))
        assert aapl[3] == ("2023/12/10", approx(5), approx(194.27))


# ---------------------------------------------------------------------------
# FIFO lots at intermediate date (2023/07/01)
# ---------------------------------------------------------------------------
class TestLotsFIFOMidDate:
    def test_count(self):
        data = run("lots", "--date", "2023/07/01")
        assert len(data["lots"]) == 7

    def test_details(self):
        lots = run("lots", "--date", "2023/07/01")["lots"]
        expected = [
            ("AAPL", 20, 131.86, "2023/01/18"),
            ("TSLA", 10, 196.81, "2023/02/06"),
            ("AAPL", 25, 165.50, "2023/03/15"),
            ("MSFT", 12, 288.30, "2023/04/10"),
            ("VTI", 40, 206.00, "2023/04/20"),
            ("AAPL", 20, 142.30, "2023/05/20"),
            ("TSLA", 15, 251.61, "2023/06/01"),
        ]
        assert len(lots) == len(expected)
        for lot, (com, qty, cpu, ad) in zip(lots, expected):
            assert lot["commodity"] == com
            assert lot["quantity"] == approx(qty)
            assert lot["cost_per_unit"] == approx(cpu)
            assert lot["acquisition_date"] == ad


# ---------------------------------------------------------------------------
# Realized gains — FIFO all
# ---------------------------------------------------------------------------
class TestRealizedGainsFIFO:
    def test_transaction_count(self):
        data = run("realized-gains")
        assert len(data["transactions"]) == 6

    def test_tsla_wash_sale(self):
        """First sell: TSLA at loss with repurchase within 30 days."""
        data = run("realized-gains")
        txn = data["transactions"][0]
        assert txn["date"] == "2023/05/15"
        assert txn["commodity"] == "TSLA"
        assert txn["quantity_sold"] == approx(20)
        assert txn["total_proceeds"] == approx(3166.00)
        assert txn["total_cost_basis"] == approx(3936.20)
        assert txn["realized_gain"] == approx(-770.20)
        assert txn["wash_sale_disallowed"] == approx(577.65)
        assert txn["adjusted_gain"] == approx(-192.55)
        assert txn["holding_period"] == "short-term"

    def test_aapl_gain(self):
        """Second sell: AAPL profitable, no wash sale."""
        data = run("realized-gains")
        txn = data["transactions"][1]
        assert txn["date"] == "2023/06/15"
        assert txn["commodity"] == "AAPL"
        assert txn["realized_gain"] == approx(1431.60)
        assert txn["wash_sale_disallowed"] == approx(0)
        assert txn["adjusted_gain"] == approx(1431.60)
        assert txn["holding_period"] == "short-term"

    def test_msft_wash_sale(self):
        """Third sell: MSFT at loss with repurchase within 30 days."""
        data = run("realized-gains")
        txn = data["transactions"][2]
        assert txn["date"] == "2023/08/15"
        assert txn["commodity"] == "MSFT"
        assert txn["realized_gain"] == approx(-106.40)
        assert txn["wash_sale_disallowed"] == approx(79.80)
        assert txn["adjusted_gain"] == approx(-26.60)

    def test_aapl_sell_4(self):
        """Fourth sell: AAPL profitable under FIFO."""
        data = run("realized-gains")
        txn = data["transactions"][3]
        assert txn["date"] == "2023/10/15"
        assert txn["commodity"] == "AAPL"
        assert txn["total_cost_basis"] == approx(3464.70)
        assert txn["realized_gain"] == approx(797.80)
        assert txn["wash_sale_disallowed"] == approx(0)

    def test_vti_wash_sale(self):
        """Fifth sell: VTI at loss with partial wash sale."""
        data = run("realized-gains")
        txn = data["transactions"][4]
        assert txn["date"] == "2023/11/05"
        assert txn["commodity"] == "VTI"
        assert txn["realized_gain"] == approx(-35.00)
        assert txn["wash_sale_disallowed"] == approx(25.00)
        assert txn["adjusted_gain"] == approx(-10.00)

    def test_aapl_long_term(self):
        """Sixth sell: AAPL long-term holding."""
        data = run("realized-gains")
        txn = data["transactions"][5]
        assert txn["date"] == "2024/06/01"
        assert txn["commodity"] == "AAPL"
        assert txn["realized_gain"] == approx(345.00)
        assert txn["holding_period"] == "long-term"

    def test_totals(self):
        data = run("realized-gains")
        assert data["total_realized_gain"] == approx(1662.80)
        assert data["total_wash_sale_disallowed"] == approx(682.45)
        assert data["total_adjusted_gain"] == approx(2345.25)
        assert data["short_term_adjusted_gain"] == approx(2000.25)
        assert data["long_term_adjusted_gain"] == approx(345.00)


# ---------------------------------------------------------------------------
# Realized gains — LIFO all
# ---------------------------------------------------------------------------
class TestRealizedGainsLIFO:
    def test_transaction_count(self):
        data = run("realized-gains", "--method", "lifo")
        assert len(data["transactions"]) == 6

    def test_aapl_sell_2_lifo(self):
        """LIFO consumes most recent AAPL lots first."""
        data = run("realized-gains", "--method", "lifo")
        txn = data["transactions"][1]
        assert txn["commodity"] == "AAPL"
        assert txn["total_cost_basis"] == approx(4501.00)
        assert txn["realized_gain"] == approx(886.40)

    def test_aapl_sell_4_lifo_loss(self):
        """LIFO produces a loss on sell 4 (consumed high-cost [07/20] lot)."""
        data = run("realized-gains", "--method", "lifo")
        txn = data["transactions"][3]
        assert txn["commodity"] == "AAPL"
        assert txn["realized_gain"] == approx(-536.00)
        # No wash sale (next AAPL buy is 56 days later)
        assert txn["wash_sale_disallowed"] == approx(0)

    def test_vti_larger_wash_sale(self):
        """LIFO VTI sell has larger loss => larger wash sale disallowance."""
        data = run("realized-gains", "--method", "lifo")
        txn = data["transactions"][4]
        assert txn["commodity"] == "VTI"
        assert txn["realized_gain"] == approx(-185.40)
        assert txn["wash_sale_disallowed"] == approx(132.43)
        assert txn["adjusted_gain"] == approx(-52.97)

    def test_totals(self):
        data = run("realized-gains", "--method", "lifo")
        assert data["total_realized_gain"] == approx(-654.30)
        assert data["total_wash_sale_disallowed"] == approx(789.88)
        assert data["total_adjusted_gain"] == approx(135.58)
        assert data["short_term_adjusted_gain"] == approx(135.58)
        assert data["long_term_adjusted_gain"] == approx(0)

    def test_all_short_term(self):
        """Under LIFO, all transactions should be short-term."""
        data = run("realized-gains", "--method", "lifo")
        for txn in data["transactions"]:
            assert txn["holding_period"] == "short-term"


# ---------------------------------------------------------------------------
# Realized gains — HIFO all
# ---------------------------------------------------------------------------
class TestRealizedGainsHIFO:
    def test_transaction_count(self):
        data = run("realized-gains", "--method", "hifo")
        assert len(data["transactions"]) == 6

    def test_aapl_sell_2_hifo(self):
        """HIFO consumes highest-cost lots first, producing different gain
        than both FIFO and LIFO."""
        data = run("realized-gains", "--method", "hifo")
        txn = data["transactions"][1]
        assert txn["commodity"] == "AAPL"
        # HIFO: 25@165.50 + 5@142.30 = 4849.00
        assert txn["total_cost_basis"] == approx(4849.00)
        assert txn["realized_gain"] == approx(538.40)

    def test_differs_from_fifo_and_lifo(self):
        """HIFO sell 2 gain differs from both FIFO and LIFO."""
        fifo = run("realized-gains")["transactions"][1]["realized_gain"]
        lifo = run("realized-gains", "--method", "lifo")["transactions"][1]["realized_gain"]
        hifo = run("realized-gains", "--method", "hifo")["transactions"][1]["realized_gain"]
        # FIFO: 1431.60, LIFO: 886.40, HIFO: 538.40
        assert abs(fifo - hifo) > 100
        assert abs(lifo - hifo) > 100
        assert abs(fifo - lifo) > 100

    def test_totals(self):
        data = run("realized-gains", "--method", "hifo")
        assert data["total_realized_gain"] == approx(-1002.30)
        assert data["total_wash_sale_disallowed"] == approx(789.88)
        assert data["total_adjusted_gain"] == approx(-212.42)
        assert data["short_term_adjusted_gain"] == approx(-212.42)
        assert data["long_term_adjusted_gain"] == approx(0)


# ---------------------------------------------------------------------------
# Realized gains — FIFO at intermediate date
# ---------------------------------------------------------------------------
class TestRealizedGainsFIFOMidDate:
    def test_two_sells(self):
        data = run("realized-gains", "--date", "2023/07/01")
        assert len(data["transactions"]) == 2

    def test_totals(self):
        data = run("realized-gains", "--date", "2023/07/01")
        assert data["total_realized_gain"] == approx(661.40)
        assert data["total_wash_sale_disallowed"] == approx(577.65)
        assert data["total_adjusted_gain"] == approx(1239.05)


# ---------------------------------------------------------------------------
# Holding period verification
# ---------------------------------------------------------------------------
class TestHoldingPeriod:
    def test_fifo_has_one_long_term(self):
        """Under FIFO the 2024/06/01 AAPL sell is long-term (444 days)."""
        data = run("realized-gains")
        periods = [t["holding_period"] for t in data["transactions"]]
        assert periods.count("long-term") == 1
        assert data["transactions"][5]["holding_period"] == "long-term"

    def test_lifo_all_short_term(self):
        """Under LIFO the same sell uses [12/10] lot (174 days) — short-term."""
        data = run("realized-gains", "--method", "lifo")
        for txn in data["transactions"]:
            assert txn["holding_period"] == "short-term"

    def test_hifo_all_short_term(self):
        """Under HIFO the same sell uses [12/10] lot (174 days) — short-term."""
        data = run("realized-gains", "--method", "hifo")
        for txn in data["transactions"]:
            assert txn["holding_period"] == "short-term"


# ---------------------------------------------------------------------------
# Wash sale cascading effect
# ---------------------------------------------------------------------------
class TestWashSaleCascade:
    def test_adjusted_cost_in_lots(self):
        """Wash sale cost adjustments must flow through to lots output."""
        lots = run("lots")["lots"]
        msft_replacement = [l for l in lots
                            if l["commodity"] == "MSFT"
                            and l["acquisition_date"] == "2023/09/05"][0]
        # Original $330.50 + $79.80/6 = $343.80
        assert msft_replacement["cost_per_unit"] == approx(343.80)

    def test_adjusted_cost_in_market_value(self):
        """Wash sale adjustments affect market-value cost basis."""
        fifo_mv = run("market-value", "--date", "2024/06/01")
        lifo_mv = run("market-value", "--date", "2024/06/01", "--method", "lifo")
        # Different methods produce different cost bases due to different
        # wash sale amounts on VTI
        assert fifo_mv["total_cost_basis"] != approx(
            lifo_mv["total_cost_basis"]
        )


# ---------------------------------------------------------------------------
# Market value — FIFO at 2024/06/01
# ---------------------------------------------------------------------------
class TestMarketValueFIFO:
    def test_holdings(self):
        data = run("market-value", "--date", "2024/06/01")
        h = data["holdings"]
        assert len(h) == 4

        assert h[0]["commodity"] == "AAPL"
        assert h[0]["total_quantity"] == approx(80)
        assert h[0]["market_price"] == approx(198.50)
        assert h[0]["market_value"] == approx(15880.00)

        assert h[1]["commodity"] == "MSFT"
        assert h[1]["total_quantity"] == approx(10)
        assert h[1]["market_price"] == approx(430.15)
        assert h[1]["market_value"] == approx(4301.50)

        assert h[2]["commodity"] == "TSLA"
        assert h[2]["total_quantity"] == approx(25)
        assert h[2]["market_price"] == approx(182.45)
        assert h[2]["market_value"] == approx(4561.25)

        assert h[3]["commodity"] == "VTI"
        assert h[3]["total_quantity"] == approx(50)
        assert h[3]["market_price"] == approx(248.35)
        assert h[3]["market_value"] == approx(12417.50)

    def test_totals(self):
        data = run("market-value", "--date", "2024/06/01")
        assert data["total_market_value"] == approx(37160.25)
        assert data["total_cost_basis"] == approx(34124.10)
        assert data["total_unrealized_gain"] == approx(3036.15)


# ---------------------------------------------------------------------------
# Market value — LIFO at 2024/06/01
# ---------------------------------------------------------------------------
class TestMarketValueLIFO:
    def test_totals(self):
        data = run("market-value", "--date", "2024/06/01", "--method", "lifo")
        assert data["total_market_value"] == approx(37160.25)
        assert data["total_cost_basis"] == approx(31914.43)
        assert data["total_unrealized_gain"] == approx(5245.82)


# ---------------------------------------------------------------------------
# Market value — HIFO at 2024/06/01
# ---------------------------------------------------------------------------
class TestMarketValueHIFO:
    def test_totals(self):
        data = run("market-value", "--date", "2024/06/01", "--method", "hifo")
        assert data["total_market_value"] == approx(37160.25)
        assert data["total_cost_basis"] == approx(31566.43)
        assert data["total_unrealized_gain"] == approx(5593.82)

    def test_lowest_cost_remaining(self):
        """HIFO should leave the lowest-cost lots, maximizing unrealized gain
        potential relative to both FIFO and LIFO."""
        fifo = run("market-value", "--date", "2024/06/01")
        lifo = run("market-value", "--date", "2024/06/01", "--method", "lifo")
        hifo = run("market-value", "--date", "2024/06/01", "--method", "hifo")
        assert hifo["total_unrealized_gain"] >= lifo["total_unrealized_gain"]
        assert hifo["total_unrealized_gain"] >= fifo["total_unrealized_gain"]


# ---------------------------------------------------------------------------
# Market value — FIFO at intermediate date
# ---------------------------------------------------------------------------
class TestMarketValueMidFIFO:
    def test_totals(self):
        data = run("market-value", "--date", "2023/07/01")
        assert data["total_market_value"] == approx(31974.38)
        assert data["total_cost_basis"] == approx(27062.55)
        assert data["total_unrealized_gain"] == approx(4911.83)

    def test_holdings_count(self):
        data = run("market-value", "--date", "2023/07/01")
        assert len(data["holdings"]) == 4


# ---------------------------------------------------------------------------
# Validate — cross-check against ledger CLI at end date
# ---------------------------------------------------------------------------
class TestValidateEnd:
    def test_valid(self):
        data = run("validate", "--date", "2024/06/01")
        assert data["valid"] is True

    def test_holdings_quantities(self):
        data = run("validate", "--date", "2024/06/01")
        assert data["holdings"]["AAPL"] == approx(80)
        assert data["holdings"]["MSFT"] == approx(10)
        assert data["holdings"]["TSLA"] == approx(25)
        assert data["holdings"]["VTI"] == approx(50)

    def test_ledger_matches(self):
        data = run("validate", "--date", "2024/06/01")
        for com in ["AAPL", "MSFT", "TSLA", "VTI"]:
            assert data["holdings"][com] == approx(
                data["ledger_holdings"][com]
            ), (f"{com}: tool={data['holdings'][com]}, "
                f"ledger={data['ledger_holdings'].get(com)}")


# ---------------------------------------------------------------------------
# Validate — cross-check against ledger CLI at mid date
# ---------------------------------------------------------------------------
class TestValidateMid:
    def test_valid(self):
        data = run("validate", "--date", "2023/07/01")
        assert data["valid"] is True

    def test_holdings_quantities(self):
        data = run("validate", "--date", "2023/07/01")
        assert data["holdings"]["AAPL"] == approx(65)
        assert data["holdings"]["MSFT"] == approx(12)
        assert data["holdings"]["TSLA"] == approx(25)
        assert data["holdings"]["VTI"] == approx(40)

    def test_ledger_agrees(self):
        data = run("validate", "--date", "2023/07/01")
        for com in ["AAPL", "MSFT", "TSLA", "VTI"]:
            assert data["holdings"][com] == approx(
                data["ledger_holdings"][com]
            )


# ---------------------------------------------------------------------------
# Edge cases — journal noise must not leak into lot tracking
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_no_cancelled_commodities(self):
        """Commented-out orders must not appear."""
        data = run("lots")
        commodities = set(l["commodity"] for l in data["lots"])
        assert commodities == {"AAPL", "TSLA", "MSFT", "VTI"}

    def test_lot_count_early_may(self):
        """By 2023/05/02 exactly 5 real lots exist — no leakage from
        non-trade entries that appear around the same date."""
        data = run("lots", "--date", "2023/05/02")
        assert len(data["lots"]) == 5

    def test_total_aapl_quantity_end(self):
        """Total AAPL across all lots must be 80 — virtual postings
        with AAPL commodity must not inflate this."""
        data = run("lots")
        aapl_qty = sum(
            l["quantity"] for l in data["lots"] if l["commodity"] == "AAPL"
        )
        assert aapl_qty == approx(80)

    def test_total_tsla_quantity_end(self):
        """Total TSLA must be 25."""
        data = run("lots")
        tsla_qty = sum(
            l["quantity"] for l in data["lots"] if l["commodity"] == "TSLA"
        )
        assert tsla_qty == approx(25)

    def test_total_msft_quantity_end(self):
        """Total MSFT must be 10."""
        data = run("lots")
        msft_qty = sum(
            l["quantity"] for l in data["lots"] if l["commodity"] == "MSFT"
        )
        assert msft_qty == approx(10)

    def test_total_vti_quantity_end(self):
        """Total VTI must be 50."""
        data = run("lots")
        vti_qty = sum(
            l["quantity"] for l in data["lots"] if l["commodity"] == "VTI"
        )
        assert vti_qty == approx(50)

    def test_dividends_not_in_gains(self):
        """Dividend transactions must not appear in realized gains."""
        data = run("realized-gains")
        for txn in data["transactions"]:
            assert txn["quantity_sold"] > 0
            assert txn["commodity"] in {"AAPL", "TSLA", "MSFT", "VTI"}

    def test_method_quantities_agree(self):
        """All three methods must agree on total commodity quantities."""
        for method in ["fifo", "lifo", "hifo"]:
            data = run("lots", "--method", method)
            totals = {}
            for lot in data["lots"]:
                totals[lot["commodity"]] = (
                    totals.get(lot["commodity"], 0) + lot["quantity"]
                )
            assert totals["AAPL"] == approx(80), f"{method}: AAPL wrong"
            assert totals["TSLA"] == approx(25), f"{method}: TSLA wrong"
            assert totals["MSFT"] == approx(10), f"{method}: MSFT wrong"
            assert totals["VTI"] == approx(50), f"{method}: VTI wrong"
