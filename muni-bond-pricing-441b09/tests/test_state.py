"""
MSRB Rule G-33 Municipal Bond Pricing Engine + Reconciliation — verification tests.
"""

import subprocess
import json
import os
import tempfile
import pytest


def run_calc(spec):
    """Run the muni_calc CLI and return parsed JSON output."""
    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(spec, f)
        result = subprocess.run(
            ["python3", "/app/muni_calc.py", path],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"CLI exited {result.returncode}. stderr:\n{result.stderr}"
        )
        out = json.loads(result.stdout)
        return out
    finally:
        if os.path.exists(path):
            os.unlink(path)


def make_periodic(coupon_rate, settlement, maturity, dated, first_coupon,
                  frequency=2, rv=100.0, compute="price",
                  yield_input=None, price_input=None, call_schedule=None):
    spec = {
        "security_type": "periodic",
        "coupon_rate": coupon_rate,
        "settlement_date": settlement,
        "maturity_date": maturity,
        "dated_date": dated,
        "first_coupon_date": first_coupon,
        "frequency": frequency,
        "redemption_value": rv,
        "compute": compute,
        "yield_input": yield_input,
        "price_input": price_input,
        "call_schedule": call_schedule or [],
    }
    return spec


# ---------------------------------------------------------------------------
# 1. Par-bond identity: Y == R on coupon date => P == 100.000
# ---------------------------------------------------------------------------
class TestParBond:
    def test_semiannual_par(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.05,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 100.0
        assert out["accrued_interest"] == 0.0

    def test_quarterly_par(self):
        spec = make_periodic(
            0.08, "2024-01-01", "2026-01-01",
            "2024-01-01", "2024-04-01",
            frequency=4, yield_input=0.08,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 100.0
        assert out["accrued_interest"] == 0.0


# ---------------------------------------------------------------------------
# 2. Premium bond (Y < R): known price
# ---------------------------------------------------------------------------
class TestPremiumBond:
    def test_premium_price(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.04,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 102.800
        assert out["accrued_interest"] == 0.0


# ---------------------------------------------------------------------------
# 3. Discount bond (Y > R): price < 100
# ---------------------------------------------------------------------------
class TestDiscountBond:
    def test_discount_price(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.06,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 97.291
        assert out["dollar_price"] < 100.0


# ---------------------------------------------------------------------------
# 4. One coupon period or less to redemption
# ---------------------------------------------------------------------------
class TestOnePeriod:
    def test_one_period_price(self):
        spec = make_periodic(
            0.05, "2024-10-01", "2025-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.06,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 99.735
        assert out["accrued_interest"] == 1.25

    def test_one_period_yield(self):
        spec = make_periodic(
            0.05, "2024-10-01", "2025-01-01",
            "2024-01-01", "2024-07-01",
            compute="yield", price_input=99.735,
        )
        out = run_calc(spec)
        assert out["yield"] == 0.060


# ---------------------------------------------------------------------------
# 5. Accrued interest precision: truncation then rounding
# ---------------------------------------------------------------------------
class TestAccruedInterestPrecision:
    def test_ai_rounds_up(self):
        spec = make_periodic(
            0.07, "2024-03-14", "2025-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.07,
        )
        out = run_calc(spec)
        assert out["accrued_interest"] == 1.42

    def test_ai_rounds_down(self):
        spec = make_periodic(
            0.07, "2024-02-18", "2025-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.07,
        )
        out = run_calc(spec)
        assert out["accrued_interest"] == 0.91


# ---------------------------------------------------------------------------
# 6. Round-trip consistency: price -> yield -> price
# ---------------------------------------------------------------------------
class TestRoundTrip:
    def test_semiannual_round_trip(self):
        spec_p = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.04,
        )
        out_p = run_calc(spec_p)
        price = out_p["dollar_price"]

        spec_y = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            compute="yield", price_input=price,
        )
        out_y = run_calc(spec_y)
        assert out_y["yield"] == 0.040

    def test_mid_period_round_trip(self):
        spec_p = make_periodic(
            0.05, "2024-04-01", "2028-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.045,
        )
        out_p = run_calc(spec_p)
        price = out_p["dollar_price"]

        spec_y = make_periodic(
            0.05, "2024-04-01", "2028-01-01",
            "2024-01-01", "2024-07-01",
            compute="yield", price_input=price,
        )
        out_y = run_calc(spec_y)
        assert out_y["yield"] == 0.045

    def test_quarterly_round_trip(self):
        spec_p = make_periodic(
            0.08, "2024-01-01", "2026-01-01",
            "2024-01-01", "2024-04-01",
            frequency=4, yield_input=0.06,
        )
        out_p = run_calc(spec_p)
        price = out_p["dollar_price"]

        spec_y = make_periodic(
            0.08, "2024-01-01", "2026-01-01",
            "2024-01-01", "2024-04-01",
            frequency=4, compute="yield", price_input=price,
        )
        out_y = run_calc(spec_y)
        assert out_y["yield"] == 0.060


# ---------------------------------------------------------------------------
# 7. Yield-to-worst: callable bond
# ---------------------------------------------------------------------------
class TestYieldToWorst:
    def test_ytw_price_from_yield(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2029-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.04,
            call_schedule=[{"date": "2027-01-01", "price": 100.0}],
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 102.800
        assert out["worst_date"] == "2027-01-01"
        assert out["worst_rv"] == 100.0
        assert out["yield_to_worst"] == 0.040

    def test_ytw_yield_from_price(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2029-01-01",
            "2024-01-01", "2024-07-01",
            compute="yield", price_input=102.800,
            call_schedule=[{"date": "2027-01-01", "price": 100.0}],
        )
        out = run_calc(spec)
        assert out["yield_to_worst"] is not None
        assert out["worst_date"] == "2027-01-01"
        assert out["worst_rv"] == 100.0
        assert out["yield_to_worst"] <= out["yield"]

    def test_no_call_schedule(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.05,
        )
        out = run_calc(spec)
        assert out["yield_to_worst"] is None
        assert out["worst_date"] is None
        assert out["worst_rv"] is None


# ---------------------------------------------------------------------------
# 8. At-redemption securities
# ---------------------------------------------------------------------------
class TestAtRedemption:
    def test_price_from_yield(self):
        spec = {
            "security_type": "at_redemption",
            "coupon_rate": 0.06,
            "settlement_date": "2024-03-31",
            "maturity_date": "2025-01-30",
            "dated_date": "2024-01-30",
            "first_coupon_date": "2025-01-30",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "price",
            "yield_input": 0.05,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["dollar_price"] == 101.760
        assert out["accrued_interest"] == 1.0

    def test_yield_from_price(self):
        spec = {
            "security_type": "at_redemption",
            "coupon_rate": 0.06,
            "settlement_date": "2024-03-31",
            "maturity_date": "2025-01-30",
            "dated_date": "2024-01-30",
            "first_coupon_date": "2025-01-30",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "yield",
            "price_input": 101.76,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["yield"] == 0.050


# ---------------------------------------------------------------------------
# 9. Discounted securities
# ---------------------------------------------------------------------------
class TestDiscountedSecurity:
    def test_price_from_discount_rate(self):
        spec = {
            "security_type": "discounted",
            "coupon_rate": 0.0,
            "settlement_date": "2024-07-01",
            "maturity_date": "2025-01-01",
            "dated_date": "2024-07-01",
            "first_coupon_date": "2025-01-01",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "price",
            "yield_input": None,
            "discount_rate": 0.04,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["dollar_price"] == 98.0
        assert out["yield"] == 0.041
        assert out["accrued_interest"] == 0.0

    def test_roi_from_price(self):
        spec = {
            "security_type": "discounted",
            "coupon_rate": 0.0,
            "settlement_date": "2024-07-01",
            "maturity_date": "2025-01-01",
            "dated_date": "2024-07-01",
            "first_coupon_date": "2025-01-01",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "yield",
            "price_input": 98.0,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["yield"] == 0.041


# ---------------------------------------------------------------------------
# 10. End-of-month day count edge cases
# ---------------------------------------------------------------------------
class TestEOMDayCount:
    def test_d1_30_d2_31_adjusted(self):
        """D1=30 (Jan 30), D2=31 (Mar 31). D1>=30 so D2->30. A=60."""
        spec = {
            "security_type": "at_redemption",
            "coupon_rate": 0.06,
            "settlement_date": "2024-03-31",
            "maturity_date": "2025-01-30",
            "dated_date": "2024-01-30",
            "first_coupon_date": "2025-01-30",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "price",
            "yield_input": 0.05,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["accrued_interest"] == 1.0

    def test_d1_29_d2_31_not_adjusted(self):
        """D1=29 (Jan 29), D2=31 (Mar 31). D1<30 so D2 stays 31. A=62."""
        spec = {
            "security_type": "at_redemption",
            "coupon_rate": 0.06,
            "settlement_date": "2024-03-31",
            "maturity_date": "2025-01-29",
            "dated_date": "2024-01-29",
            "first_coupon_date": "2025-01-29",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "price",
            "yield_input": 0.05,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["accrued_interest"] == 1.03

    def test_d1_31_d2_31_both_adjusted(self):
        """D1=31 (Jan 31)->30, D2=31 (Mar 31), adj D1>=30 -> D2=30. A=60."""
        spec = {
            "security_type": "at_redemption",
            "coupon_rate": 0.06,
            "settlement_date": "2024-03-31",
            "maturity_date": "2025-01-31",
            "dated_date": "2024-01-31",
            "first_coupon_date": "2025-01-31",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "price",
            "yield_input": 0.05,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["accrued_interest"] == 1.0


# ---------------------------------------------------------------------------
# 11. Zero yield edge case
# ---------------------------------------------------------------------------
class TestZeroYield:
    def test_zero_yield_price(self):
        spec = make_periodic(
            0.06, "2024-01-01", "2026-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.0,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 112.0


# ---------------------------------------------------------------------------
# 12. Yield precision: truncate to 4 then round to 3
# ---------------------------------------------------------------------------
class TestYieldPrecision:
    def test_yield_rounding(self):
        spec = {
            "security_type": "discounted",
            "coupon_rate": 0.0,
            "settlement_date": "2024-07-01",
            "maturity_date": "2025-01-01",
            "dated_date": "2024-07-01",
            "first_coupon_date": "2025-01-01",
            "frequency": 2,
            "redemption_value": 100.0,
            "compute": "yield",
            "price_input": 98.0,
            "call_schedule": [],
        }
        out = run_calc(spec)
        assert out["yield"] == 0.041


# ---------------------------------------------------------------------------
# 13. Dollar price truncation (not rounding)
# ---------------------------------------------------------------------------
class TestPriceTruncation:
    def test_price_truncated_not_rounded(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.04,
        )
        out = run_calc(spec)
        assert out["dollar_price"] == 102.800


# ---------------------------------------------------------------------------
# 14. Output schema completeness
# ---------------------------------------------------------------------------
class TestOutputSchema:
    def test_all_fields_present(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2027-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.05,
        )
        out = run_calc(spec)
        required = {"accrued_interest", "dollar_price", "yield",
                     "yield_to_worst", "worst_date", "worst_rv"}
        assert required.issubset(set(out.keys())), (
            f"Missing keys: {required - set(out.keys())}"
        )

    def test_output_types(self):
        spec = make_periodic(
            0.05, "2024-01-01", "2029-01-01",
            "2024-01-01", "2024-07-01",
            yield_input=0.04,
            call_schedule=[{"date": "2027-01-01", "price": 100.0}],
        )
        out = run_calc(spec)
        assert isinstance(out["accrued_interest"], (int, float))
        assert isinstance(out["dollar_price"], (int, float))
        assert isinstance(out["yield"], (int, float))
        assert isinstance(out["yield_to_worst"], (int, float))
        assert isinstance(out["worst_date"], str)
        assert isinstance(out["worst_rv"], (int, float))


# ---------------------------------------------------------------------------
# 15. Reconciliation — JSON discrepancies
# ---------------------------------------------------------------------------
class TestReconciliation:
    @pytest.fixture(autouse=True, scope="class")
    def run_reconcile(self):
        """Run reconcile.sh once for the entire class."""
        result = subprocess.run(
            ["bash", "/app/reconcile.sh"],
            capture_output=True, text=True, timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"reconcile.sh exited {result.returncode}. stderr:\n{result.stderr}"
        )

    def _load_discrepancies(self):
        path = "/app/output/discrepancies.json"
        assert os.path.exists(path), "discrepancies.json not found"
        with open(path) as f:
            return json.load(f)

    def test_output_exists(self):
        assert os.path.exists("/app/output/discrepancies.json")

    def test_discrepancy_count(self):
        discs = self._load_discrepancies()
        assert len(discs) == 7, (
            f"Expected 7 discrepancies, got {len(discs)}: "
            f"{[(d['trade_id'], d['field']) for d in discs]}"
        )

    def test_t002_price_truncation(self):
        discs = self._load_discrepancies()
        match = [d for d in discs
                 if d["trade_id"] == "T002" and d["field"] == "dollar_price"]
        assert len(match) == 1, "Missing T002 dollar_price discrepancy"
        assert match[0]["vendor_value"] == 102.801
        assert match[0]["correct_value"] == 102.800

    def test_t006_yield_precision(self):
        discs = self._load_discrepancies()
        match = [d for d in discs
                 if d["trade_id"] == "T006" and d["field"] == "yield"]
        assert len(match) == 1, "Missing T006 yield discrepancy"
        assert match[0]["vendor_value"] == 0.040
        assert match[0]["correct_value"] == 0.041

    def test_t007_call_schedule(self):
        discs = self._load_discrepancies()
        t007 = [d for d in discs if d["trade_id"] == "T007"]
        assert len(t007) == 4, (
            f"Expected 4 T007 discrepancies, got {len(t007)}"
        )
        fields = {d["field"] for d in t007}
        assert "dollar_price" in fields
        assert "yield_to_worst" in fields
        assert "worst_date" in fields
        assert "worst_rv" in fields

        dp = [d for d in t007 if d["field"] == "dollar_price"][0]
        assert dp["vendor_value"] == 104.491
        assert dp["correct_value"] == 102.800

    def test_t009_eom_daycount(self):
        discs = self._load_discrepancies()
        match = [d for d in discs
                 if d["trade_id"] == "T009" and d["field"] == "accrued_interest"]
        assert len(match) == 1, "Missing T009 accrued_interest discrepancy"
        assert match[0]["vendor_value"] == 1.02
        assert match[0]["correct_value"] == 1.03

    def test_correct_trades_not_flagged(self):
        discs = self._load_discrepancies()
        flagged_ids = {d["trade_id"] for d in discs}
        correct_ids = {"T001", "T003", "T004", "T005", "T008", "T010",
                       "T011", "T012"}
        wrongly_flagged = flagged_ids & correct_ids
        assert len(wrongly_flagged) == 0, (
            f"Correct trades wrongly flagged: {wrongly_flagged}"
        )

    def test_discrepancy_schema(self):
        discs = self._load_discrepancies()
        for d in discs:
            assert "trade_id" in d
            assert "field" in d
            assert "vendor_value" in d
            assert "correct_value" in d


# ---------------------------------------------------------------------------
# 16. Audit database — structure and content
# ---------------------------------------------------------------------------
class TestAuditDatabase:
    @pytest.fixture(autouse=True, scope="class")
    def ensure_reconcile_ran(self):
        """Ensure reconcile.sh has been run (idempotent)."""
        if not os.path.exists("/app/output/audit.db"):
            result = subprocess.run(
                ["bash", "/app/reconcile.sh"],
                capture_output=True, text=True, timeout=120,
                cwd="/app",
            )
            assert result.returncode == 0, (
                f"reconcile.sh exited {result.returncode}. stderr:\n{result.stderr}"
            )

    def _sql(self, query):
        """Run a sqlite3 query and return parsed JSON rows."""
        result = subprocess.run(
            ["sqlite3", "-json", "/app/output/audit.db", query],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"sqlite3 failed: {result.stderr}"
        )
        out = result.stdout.strip()
        if not out:
            return []
        return json.loads(out)

    def test_db_exists(self):
        assert os.path.exists("/app/output/audit.db"), (
            "audit.db not found at /app/output/audit.db"
        )

    def test_trades_table_count(self):
        rows = self._sql("SELECT COUNT(*) as cnt FROM trades")
        assert rows[0]["cnt"] == 12

    def test_computed_values_count(self):
        rows = self._sql("SELECT COUNT(*) as cnt FROM computed_values")
        assert rows[0]["cnt"] == 12

    def test_vendor_values_count(self):
        rows = self._sql("SELECT COUNT(*) as cnt FROM vendor_values")
        assert rows[0]["cnt"] == 12

    def test_db_discrepancies_count(self):
        rows = self._sql("SELECT COUNT(*) as cnt FROM discrepancies")
        assert rows[0]["cnt"] == 7

    def test_trades_schema_has_key_columns(self):
        rows = self._sql("PRAGMA table_info(trades)")
        col_names = {r["name"] for r in rows}
        for col in ("trade_id", "security_type", "coupon_rate",
                     "settlement_date", "maturity_date", "frequency"):
            assert col in col_names, f"Missing column {col} in trades table"

    def test_computed_values_schema(self):
        rows = self._sql("PRAGMA table_info(computed_values)")
        col_names = {r["name"] for r in rows}
        for col in ("trade_id", "accrued_interest", "dollar_price",
                     "yield", "yield_to_worst", "worst_date", "worst_rv"):
            assert col in col_names, f"Missing column {col} in computed_values"

    def test_discrepancies_schema(self):
        rows = self._sql("PRAGMA table_info(discrepancies)")
        col_names = {r["name"] for r in rows}
        for col in ("trade_id", "field", "vendor_value", "correct_value"):
            assert col in col_names, f"Missing column {col} in discrepancies"

    def test_computed_par_bond_t001(self):
        rows = self._sql(
            "SELECT dollar_price, accrued_interest FROM computed_values "
            "WHERE trade_id='T001'"
        )
        assert len(rows) == 1
        assert abs(rows[0]["dollar_price"] - 100.0) < 1e-3
        assert abs(rows[0]["accrued_interest"] - 0.0) < 1e-3

    def test_computed_premium_t002(self):
        rows = self._sql(
            "SELECT dollar_price FROM computed_values WHERE trade_id='T002'"
        )
        assert len(rows) == 1
        assert abs(rows[0]["dollar_price"] - 102.8) < 1e-3

    def test_computed_callable_t007(self):
        rows = self._sql(
            "SELECT dollar_price, yield_to_worst, worst_date, worst_rv "
            "FROM computed_values WHERE trade_id='T007'"
        )
        assert len(rows) == 1
        assert abs(rows[0]["dollar_price"] - 102.8) < 1e-3
        assert rows[0]["yield_to_worst"] is not None
        assert rows[0]["worst_date"] == "2027-01-01"
        assert abs(rows[0]["worst_rv"] - 100.0) < 1e-3

    def test_vendor_values_t007_missing_call(self):
        rows = self._sql(
            "SELECT yield_to_worst, worst_date, worst_rv "
            "FROM vendor_values WHERE trade_id='T007'"
        )
        assert len(rows) == 1
        assert rows[0]["yield_to_worst"] is None
        assert rows[0]["worst_date"] is None
        assert rows[0]["worst_rv"] is None

    def test_validation_summary_view_exists(self):
        rows = self._sql(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='validation_summary'"
        )
        assert len(rows) == 1, "validation_summary view not found"

    def test_validation_summary_content(self):
        rows = self._sql(
            "SELECT trade_id, num_discrepancies, discrepant_fields "
            "FROM validation_summary ORDER BY trade_id"
        )
        assert len(rows) == 4, (
            f"Expected 4 rows in validation_summary, got {len(rows)}"
        )
        summary = {r["trade_id"]: r for r in rows}

        assert summary["T002"]["num_discrepancies"] == 1
        assert summary["T002"]["discrepant_fields"] == "dollar_price"

        assert summary["T006"]["num_discrepancies"] == 1
        assert summary["T006"]["discrepant_fields"] == "yield"

        assert summary["T007"]["num_discrepancies"] == 4
        assert summary["T007"]["discrepant_fields"] == (
            "dollar_price,worst_date,worst_rv,yield_to_worst"
        )

        assert summary["T009"]["num_discrepancies"] == 1
        assert summary["T009"]["discrepant_fields"] == "accrued_interest"

    def test_db_json_consistency(self):
        """Database discrepancies must match JSON discrepancies."""
        db_discs = self._sql(
            "SELECT trade_id, field FROM discrepancies "
            "ORDER BY trade_id, field"
        )
        path = "/app/output/discrepancies.json"
        assert os.path.exists(path)
        with open(path) as f:
            json_discs = json.load(f)

        db_keys = [(d["trade_id"], d["field"]) for d in db_discs]
        json_keys = [(d["trade_id"], d["field"]) for d in json_discs]
        assert db_keys == json_keys, (
            f"DB keys {db_keys} != JSON keys {json_keys}"
        )
