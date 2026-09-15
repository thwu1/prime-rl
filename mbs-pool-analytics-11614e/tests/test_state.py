
import json
import math
import os
import sqlite3
import subprocess
import pytest


REPORT_PATH = "/app/output/report.json"
DB_PATH = "/app/output/mbs.db"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def db():
    assert os.path.exists(DB_PATH), f"SQLite database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# =============================================
# Structure Tests
# =============================================

class TestStructure:
    def test_top_level_keys(self, report):
        required = {"pool_metrics", "prepayment", "losses", "cashflow_projection", "ginniemae_pools"}
        assert required.issubset(set(report.keys())), (
            f"Missing top-level keys: {required - set(report.keys())}"
        )

    def test_pool_ids_exist(self, report):
        assert "2020Q1" in report["pool_metrics"]
        assert "2020Q2" in report["pool_metrics"]

    def test_pool_metrics_is_list(self, report):
        for pool_id in ["2020Q1", "2020Q2"]:
            assert isinstance(report["pool_metrics"][pool_id], list)
            assert len(report["pool_metrics"][pool_id]) > 0

    def test_period_record_keys(self, report):
        required_keys = {
            "period", "active_loans", "total_upb", "pool_factor",
            "wac", "wam", "wala", "dlq_30_count", "dlq_60_count", "dlq_90plus_count"
        }
        first_rec = report["pool_metrics"]["2020Q1"][0]
        assert required_keys.issubset(set(first_rec.keys())), (
            f"Missing keys: {required_keys - set(first_rec.keys())}"
        )

    def test_prepayment_record_keys(self, report):
        required_keys = {"period", "smm", "cpr", "implied_psa"}
        recs = report["prepayment"]["2020Q1"]
        assert len(recs) > 0
        assert required_keys.issubset(set(recs[0].keys()))

    def test_losses_record_keys(self, report):
        assert isinstance(report["losses"], list)
        assert len(report["losses"]) > 0
        required_keys = {
            "loan_seq", "zb_code", "zb_date", "zb_removal_upb",
            "mi_recoveries", "net_sale_proceeds", "non_mi_recoveries",
            "expenses", "dlq_accrued_interest", "computed_actual_loss"
        }
        assert required_keys.issubset(set(report["losses"][0].keys()))

    def test_cashflow_projection_keys(self, report):
        required_keys = {
            "month", "beginning_upb", "scheduled_principal", "prepayment",
            "total_principal", "ending_upb", "pool_factor", "interest"
        }
        for pool_id in ["2020Q1", "2020Q2"]:
            assert pool_id in report["cashflow_projection"]
            recs = report["cashflow_projection"][pool_id]
            assert len(recs) > 0
            assert required_keys.issubset(set(recs[0].keys()))


# =============================================
# Pool Metrics Tests
# =============================================

class TestPoolMetrics:
    def test_q1_initial_loan_count(self, report):
        """Q1 pool starts with 4 loans."""
        first_period = report["pool_metrics"]["2020Q1"][0]
        assert first_period["active_loans"] == 4

    def test_q2_initial_loan_count(self, report):
        """Q2 pool starts with 4 loans."""
        first_period = report["pool_metrics"]["2020Q2"][0]
        assert first_period["active_loans"] == 4

    def test_q1_initial_total_upb(self, report):
        """Q1 pool original UPB = 200k + 300k + 100k + 400k = 1,000,000."""
        first_period = report["pool_metrics"]["2020Q1"][0]
        assert abs(first_period["total_upb"] - 1000000.00) < 0.01

    def test_q2_initial_total_upb(self, report):
        """Q2 pool original UPB = 250k + 275k + 500k + 150k = 1,175,000."""
        first_period = report["pool_metrics"]["2020Q2"][0]
        assert abs(first_period["total_upb"] - 1175000.00) < 0.01

    def test_q1_initial_pool_factor(self, report):
        """Initial pool factor should be 1.0."""
        first_period = report["pool_metrics"]["2020Q1"][0]
        assert abs(first_period["pool_factor"] - 1.0) < 1e-6

    def test_q1_wac_at_origination(self, report):
        """Q1 WAC at origination should be 0.035 (3.5% as decimal)."""
        first_period = report["pool_metrics"]["2020Q1"][0]
        assert abs(first_period["wac"] - 0.035) < 0.0001

    def test_q2_wac_at_origination(self, report):
        """Q2 WAC at origination should be approximately 0.030851."""
        first_period = report["pool_metrics"]["2020Q2"][0]
        expected_wac = 3625000.0 / 1175000.0 / 100.0
        assert abs(first_period["wac"] - expected_wac) < 0.0002

    def test_q1_wam_at_origination(self, report):
        """All Q1 loans are 360-month, so initial WAM = 360."""
        first_period = report["pool_metrics"]["2020Q1"][0]
        assert abs(first_period["wam"] - 360.0) < 1.0

    def test_q2_wam_at_origination(self, report):
        """Q2 pool has 3x360-mo and 1x180-mo loans."""
        first_period = report["pool_metrics"]["2020Q2"][0]
        expected_wam = (360*250000 + 360*275000 + 360*500000 + 180*150000) / 1175000.0
        assert abs(first_period["wam"] - expected_wam) < 1.5

    def test_q1_pool_factor_decreases(self, report):
        """Pool factor should decrease over time."""
        periods = report["pool_metrics"]["2020Q1"]
        factors = [p["pool_factor"] for p in periods]
        for i in range(1, min(5, len(factors))):
            assert factors[i] < factors[i-1], (
                f"Pool factor did not decrease at period {i}: {factors[i]} vs {factors[i-1]}"
            )

    def test_q1_loan_count_after_prepay(self, report):
        """After F20Q10000002 prepays (period 202011), Q1 should have 3 active loans."""
        periods = report["pool_metrics"]["2020Q1"]
        for p in periods:
            if p["period"] == "202011":
                assert p["active_loans"] == 3, (
                    f"Expected 3 active loans at 202011, got {p['active_loans']}"
                )
                break

    def test_q1_loan_count_after_default(self, report):
        """After F20Q10000003 REO disposition (period 202103), Q1 should have 2 active loans."""
        periods = report["pool_metrics"]["2020Q1"]
        for p in periods:
            if p["period"] >= "202104":
                assert p["active_loans"] == 2, (
                    f"Expected 2 active loans after 202104, got {p['active_loans']}"
                )
                break

    def test_q1_delinquency_tracking(self, report):
        """F20Q10000003 goes 30-day DQ at period 202007."""
        periods = report["pool_metrics"]["2020Q1"]
        for p in periods:
            if p["period"] == "202007":
                assert p["dlq_30_count"] >= 1, (
                    f"Expected at least 1 loan 30-day DQ at 202007"
                )
                break

    def test_q1_90plus_delinquency(self, report):
        """F20Q10000003 goes 90+ DQ at period 202009 (status=3)."""
        periods = report["pool_metrics"]["2020Q1"]
        for p in periods:
            if p["period"] == "202009":
                assert p["dlq_90plus_count"] >= 1, (
                    f"Expected at least 1 loan 90+ day DQ at 202009"
                )
                break

    def test_q1_pool_factor_at_month6(self, report):
        """Q1 pool factor at period 202009 should be approximately 0.9909."""
        periods = report["pool_metrics"]["2020Q1"]
        for p in periods:
            if p["period"] == "202009":
                assert abs(p["pool_factor"] - 0.99086213) < 0.005, (
                    f"Expected pool factor ~0.9909 at 202009, got {p['pool_factor']}"
                )
                break

    def test_periods_sorted_chronologically(self, report):
        """Periods should be in chronological order."""
        for pool_id in ["2020Q1", "2020Q2"]:
            periods = [p["period"] for p in report["pool_metrics"][pool_id]]
            assert periods == sorted(periods), f"Periods not sorted for {pool_id}"

    def test_q2_loan_count_after_prepay(self, report):
        """After F20Q20000003 prepays at period 202012, Q2 should have 3 active loans."""
        periods = report["pool_metrics"]["2020Q2"]
        for p in periods:
            if p["period"] == "202012":
                assert p["active_loans"] == 3
                break


# =============================================
# Prepayment Tests
# =============================================

class TestPrepayment:
    def test_q1_prepayment_smm_at_prepay_event(self, report):
        """When F20Q10000002 prepays at 202011, SMM should spike significantly."""
        recs = report["prepayment"]["2020Q1"]
        for r in recs:
            if r["period"] == "202011":
                assert r["smm"] > 0.1, (
                    f"Expected high SMM at 202011 due to prepayment, got {r['smm']}"
                )
                assert abs(r["smm"] - 0.2998) < 0.05, (
                    f"SMM at 202011 expected ~0.30, got {r['smm']}"
                )
                break

    def test_q1_cpr_at_prepay_event(self, report):
        """CPR at the prepay period should be very high (near 1.0)."""
        recs = report["prepayment"]["2020Q1"]
        for r in recs:
            if r["period"] == "202011":
                assert r["cpr"] > 0.5, (
                    f"Expected high CPR at 202011, got {r['cpr']}"
                )
                break

    def test_smm_cpr_consistency(self, report):
        """CPR should equal 1 - (1 - SMM)^12 for each record."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["prepayment"][pool_id]
            for r in recs:
                expected_cpr = 1.0 - (1.0 - r["smm"]) ** 12
                assert abs(r["cpr"] - expected_cpr) < 1e-6, (
                    f"CPR/SMM inconsistency at {r['period']}: "
                    f"SMM={r['smm']}, CPR={r['cpr']}, expected CPR={expected_cpr}"
                )

    def test_smm_non_negative(self, report):
        """SMM should be non-negative."""
        for pool_id in ["2020Q1", "2020Q2"]:
            for r in report["prepayment"][pool_id]:
                assert r["smm"] >= -1e-8, f"Negative SMM at {r['period']}: {r['smm']}"

    def test_normal_periods_low_smm(self, report):
        """Periods with no voluntary prepayments should have low SMM (< 1%)."""
        recs = report["prepayment"]["2020Q1"]
        for r in recs:
            if r["period"] < "202011" and r["period"] > "202003":
                assert r["smm"] < 0.01, (
                    f"Expected low SMM at {r['period']} (no prepayments), got {r['smm']}"
                )

    def test_implied_psa_positive(self, report):
        """Implied PSA should be positive when SMM > 0."""
        for pool_id in ["2020Q1", "2020Q2"]:
            for r in report["prepayment"][pool_id]:
                if r["smm"] > 1e-8:
                    assert r["implied_psa"] > 0, (
                        f"Implied PSA should be positive when SMM > 0 at {r['period']}"
                    )

    def test_prepayment_starts_from_second_period(self, report):
        """Prepayment analysis should start from the second reporting period."""
        q1_first_period = report["pool_metrics"]["2020Q1"][0]["period"]
        prep_periods = [r["period"] for r in report["prepayment"]["2020Q1"]]
        assert q1_first_period not in prep_periods, (
            f"First pool period {q1_first_period} should not be in prepayment records"
        )


# =============================================
# Loss Analysis Tests
# =============================================

class TestLosses:
    def test_loss_record_exists(self, report):
        """Should have at least one loss record (F20Q10000003 with ZB=09)."""
        assert len(report["losses"]) >= 1

    def test_f20q10000003_loss_present(self, report):
        """Loan F20Q10000003 should be in losses (ZB code 09, REO disposition)."""
        seqs = [r["loan_seq"] for r in report["losses"]]
        assert "F20Q10000003" in seqs

    def test_f20q10000003_loss_values(self, report):
        """Verify actual loss components for F20Q10000003."""
        loss_rec = None
        for r in report["losses"]:
            if r["loan_seq"] == "F20Q10000003":
                loss_rec = r
                break
        assert loss_rec is not None

        assert loss_rec["zb_code"] in ("09", 9)
        assert abs(loss_rec["zb_removal_upb"] - 99603.46) < 0.02
        assert abs(loss_rec["mi_recoveries"] - 15000.00) < 0.01
        assert abs(loss_rec["net_sale_proceeds"] - 65000.00) < 0.01
        assert abs(loss_rec["non_mi_recoveries"] - 0.00) < 0.01
        assert abs(loss_rec["expenses"] - 9000.00) < 0.01
        assert abs(loss_rec["dlq_accrued_interest"] - 2755.70) < 1.0

    def test_f20q10000003_actual_loss_formula(self, report):
        """Computed actual loss should match the documented formula."""
        loss_rec = None
        for r in report["losses"]:
            if r["loan_seq"] == "F20Q10000003":
                loss_rec = r
                break
        assert loss_rec is not None

        expected = (
            loss_rec["zb_removal_upb"] + loss_rec["dlq_accrued_interest"]
            - loss_rec["net_sale_proceeds"]
            - loss_rec["mi_recoveries"]
            - loss_rec["non_mi_recoveries"]
            + loss_rec["expenses"]
        )
        assert abs(loss_rec["computed_actual_loss"] - expected) < 0.05, (
            f"Actual loss {loss_rec['computed_actual_loss']} doesn't match formula result {expected}"
        )

    def test_f20q10000003_actual_loss_value(self, report):
        """Actual loss for F20Q10000003 should be approximately $31,359."""
        loss_rec = None
        for r in report["losses"]:
            if r["loan_seq"] == "F20Q10000003":
                loss_rec = r
                break
        assert loss_rec is not None
        assert abs(loss_rec["computed_actual_loss"] - 31359.16) < 5.0, (
            f"Expected actual loss ~$31,359, got ${loss_rec['computed_actual_loss']}"
        )

    def test_prepaid_loans_not_in_losses(self, report):
        """Voluntarily prepaid loans (ZB=01) should NOT appear in losses."""
        for r in report["losses"]:
            assert r["zb_code"] not in ("01", 1), (
                f"Loan {r['loan_seq']} with ZB=01 should not be in losses"
            )


# =============================================
# Cash Flow Projection Tests
# =============================================

class TestCashflowProjection:
    def test_projection_length(self, report):
        """Projection should have 36 months (as specified by --projection-months)."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            assert len(recs) == 36, (
                f"Expected 36 projection months for {pool_id}, got {len(recs)}"
            )

    def test_months_1_indexed(self, report):
        """Projection months should be 1-indexed."""
        recs = report["cashflow_projection"]["2020Q1"]
        assert recs[0]["month"] == 1
        assert recs[-1]["month"] == 36

    def test_balance_continuity(self, report):
        """Each month's beginning UPB should equal prior month's ending UPB."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            for i in range(1, len(recs)):
                expected_begin = recs[i-1]["ending_upb"]
                actual_begin = recs[i]["beginning_upb"]
                assert abs(actual_begin - expected_begin) < 0.05, (
                    f"Balance discontinuity at month {recs[i]['month']} for {pool_id}: "
                    f"prev ending={expected_begin}, cur beginning={actual_begin}"
                )

    def test_principal_reduces_balance(self, report):
        """ending_upb = beginning_upb - total_principal."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            for r in recs:
                expected_ending = r["beginning_upb"] - r["total_principal"]
                assert abs(r["ending_upb"] - expected_ending) < 0.05, (
                    f"Principal/balance inconsistency at month {r['month']} for {pool_id}"
                )

    def test_total_principal_composition(self, report):
        """total_principal = scheduled_principal + prepayment."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            for r in recs:
                expected = r["scheduled_principal"] + r["prepayment"]
                assert abs(r["total_principal"] - expected) < 0.05, (
                    f"Total principal composition wrong at month {r['month']} for {pool_id}"
                )

    def test_pool_factor_monotonically_decreasing(self, report):
        """Pool factor should decrease monotonically in projection."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            for i in range(1, len(recs)):
                assert recs[i]["pool_factor"] <= recs[i-1]["pool_factor"] + 1e-8, (
                    f"Pool factor increased at month {recs[i]['month']} for {pool_id}"
                )

    def test_prepayment_increases_with_psa(self, report):
        """With PSA > 0, prepayment should be positive."""
        recs = report["cashflow_projection"]["2020Q1"]
        positive_prepay = sum(1 for r in recs if r["prepayment"] > 0)
        assert positive_prepay >= len(recs) * 0.8, (
            f"Expected most months to have positive prepayment under 150% PSA"
        )

    def test_interest_positive(self, report):
        """Interest should be positive for all projection months."""
        for pool_id in ["2020Q1", "2020Q2"]:
            for r in report["cashflow_projection"][pool_id]:
                assert r["interest"] > 0, (
                    f"Interest should be positive at month {r['month']} for {pool_id}"
                )

    def test_q1_beginning_upb_matches_final_pool_state(self, report):
        """Q1 projection beginning UPB should approximate the pool's last active UPB."""
        first_rec = report["cashflow_projection"]["2020Q1"][0]
        assert 500000 < first_rec["beginning_upb"] < 650000, (
            f"Q1 projection beginning UPB expected ~583k, got {first_rec['beginning_upb']}"
        )

    def test_ending_balance_at_month_36(self, report):
        """After 36 months at 150% PSA, balances should have decreased substantially."""
        for pool_id in ["2020Q1", "2020Q2"]:
            recs = report["cashflow_projection"][pool_id]
            first_upb = recs[0]["beginning_upb"]
            last_upb = recs[-1]["ending_upb"]
            reduction_pct = (first_upb - last_upb) / first_upb
            assert reduction_pct > 0.05, (
                f"Expected > 5% balance reduction over 36 months at 150% PSA for {pool_id}, "
                f"got {reduction_pct*100:.1f}%"
            )


# =============================================
# Format and Precision Tests
# =============================================

class TestFormat:
    def test_monetary_values_two_decimals(self, report):
        """Monetary values should have at most 2 decimal places."""
        rec = report["pool_metrics"]["2020Q1"][0]
        upb_str = f"{rec['total_upb']:.10f}"
        decimals = upb_str.split(".")[1]
        assert all(c == "0" for c in decimals[2:]), (
            f"total_upb has more than 2 decimal places: {rec['total_upb']}"
        )

    def test_rate_values_reasonable(self, report):
        """WAC should be expressed as a decimal (0.03-0.05 range, not 3-5)."""
        rec = report["pool_metrics"]["2020Q1"][0]
        assert 0.01 < rec["wac"] < 0.10, (
            f"WAC looks wrong - should be decimal not percentage: {rec['wac']}"
        )

    def test_pool_factor_between_0_and_1(self, report):
        """Pool factor should be between 0 and 1."""
        for pool_id in ["2020Q1", "2020Q2"]:
            for p in report["pool_metrics"][pool_id]:
                assert 0 <= p["pool_factor"] <= 1.01, (
                    f"Pool factor out of range at {p['period']}: {p['pool_factor']}"
                )


# =============================================
# SQLite Database Tests
# =============================================

class TestSQLiteDatabase:
    def test_required_tables_exist(self, db):
        """All required tables must exist in the database."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor}
        required = {
            "freddie_origination", "freddie_performance",
            "ginniemae_factors", "pool_metrics", "cross_agency_summary",
            "prepayment_detail"
        }
        assert required.issubset(tables), (
            f"Missing tables: {required - tables}"
        )

    def test_freddie_origination_count(self, db):
        """8 origination records (4 per pool)."""
        row = db.execute("SELECT count(*) as cnt FROM freddie_origination").fetchone()
        assert row["cnt"] == 8

    def test_freddie_performance_count(self, db):
        """119 monthly performance records total."""
        row = db.execute("SELECT count(*) as cnt FROM freddie_performance").fetchone()
        assert row["cnt"] == 119

    def test_ginniemae_factors_count(self, db):
        """18 Ginnie Mae factor records (3 pools x 6 months)."""
        row = db.execute("SELECT count(*) as cnt FROM ginniemae_factors").fetchone()
        assert row["cnt"] == 18

    def test_freddie_origination_specific_loan(self, db):
        """Verify specific origination data was loaded correctly."""
        row = db.execute(
            "SELECT orig_upb, orig_rate FROM freddie_origination "
            "WHERE loan_seq = 'F20Q10000001'"
        ).fetchone()
        assert row is not None, "Loan F20Q10000001 not found in freddie_origination"
        assert abs(row["orig_upb"] - 200000.0) < 0.01
        assert abs(row["orig_rate"] - 4.0) < 0.01

    def test_freddie_origination_q2_loan(self, db):
        """Verify Q2 loan data in database."""
        row = db.execute(
            "SELECT orig_upb, orig_rate, orig_term FROM freddie_origination "
            "WHERE loan_seq = 'F20Q20000004'"
        ).fetchone()
        assert row is not None
        assert abs(row["orig_upb"] - 150000.0) < 0.01
        assert abs(row["orig_rate"] - 2.75) < 0.01
        assert row["orig_term"] == 180

    def test_ginniemae_specific_record(self, db):
        """Verify Ginnie Mae fixed-width data was parsed and loaded correctly."""
        row = db.execute(
            "SELECT current_face, pool_factor, wac, loan_count FROM ginniemae_factors "
            "WHERE pool_id = 'GN0001' AND report_date = '20200201'"
        ).fetchone()
        assert row is not None, "GN0001 at 20200201 not found in ginniemae_factors"
        assert abs(row["current_face"] - 4993415.22) < 0.01
        assert abs(row["pool_factor"] - 0.99868304) < 1e-6
        assert abs(row["wac"] - 4.5) < 0.01
        assert row["loan_count"] == 85

    def test_ginniemae_15yr_pool(self, db):
        """Verify GN0003 (15-year pool) data is correctly loaded."""
        row = db.execute(
            "SELECT original_face, current_face, pool_factor, wam FROM ginniemae_factors "
            "WHERE pool_id = 'GN0003' AND report_date = '20200401'"
        ).fetchone()
        assert row is not None
        assert abs(row["original_face"] - 3200000.0) < 0.01
        assert abs(row["current_face"] - 3144200.18) < 0.01
        assert abs(row["pool_factor"] - 0.98256256) < 1e-6
        assert row["wam"] == 177

    def test_pool_metrics_table_count(self, db):
        """Pool metrics should have 36 rows (18 periods x 2 pools)."""
        row = db.execute("SELECT count(*) as cnt FROM pool_metrics").fetchone()
        assert row["cnt"] == 36

    def test_cross_agency_summary_count(self, db):
        """Cross-agency summary should have at least 5 rows (2 Freddie + 3 Ginnie Mae)."""
        row = db.execute("SELECT count(*) as cnt FROM cross_agency_summary").fetchone()
        assert row["cnt"] >= 5

    def test_cross_agency_has_both_agencies(self, db):
        """Summary must contain entries for both FREDDIE and GINNIEMAE."""
        cursor = db.execute("SELECT DISTINCT agency FROM cross_agency_summary")
        agencies = {row["agency"] for row in cursor}
        assert "FREDDIE" in agencies, "Missing FREDDIE entries in cross_agency_summary"
        assert "GINNIEMAE" in agencies, "Missing GINNIEMAE entries in cross_agency_summary"

    def test_cross_agency_freddie_pool(self, db):
        """Verify a Freddie Mac pool appears in cross_agency_summary."""
        row = db.execute(
            "SELECT pool_id, total_upb, loan_count FROM cross_agency_summary "
            "WHERE agency = 'FREDDIE' AND pool_id = '2020Q1'"
        ).fetchone()
        assert row is not None, "2020Q1 not found in cross_agency_summary"
        assert row["total_upb"] > 0
        assert row["loan_count"] >= 1

    def test_cross_agency_ginniemae_pool(self, db):
        """Verify a Ginnie Mae pool appears in cross_agency_summary."""
        row = db.execute(
            "SELECT pool_id, total_upb, pool_factor, loan_count FROM cross_agency_summary "
            "WHERE agency = 'GINNIEMAE' AND pool_id = 'GN0002'"
        ).fetchone()
        assert row is not None, "GN0002 not found in cross_agency_summary"
        assert row["loan_count"] == 120


# =============================================
# Ginnie Mae Pool Tests (JSON)
# =============================================

class TestGinnieMaePools:
    def test_ginniemae_pools_key_exists(self, report):
        """Report must contain ginniemae_pools key."""
        assert "ginniemae_pools" in report

    def test_pool_ids_present(self, report):
        """All three Ginnie Mae pools should be present."""
        gm = report["ginniemae_pools"]
        assert "GN0001" in gm, "GN0001 missing from ginniemae_pools"
        assert "GN0002" in gm, "GN0002 missing from ginniemae_pools"
        assert "GN0003" in gm, "GN0003 missing from ginniemae_pools"

    def test_gn0001_record_count(self, report):
        """GN0001 should have 6 monthly records."""
        assert len(report["ginniemae_pools"]["GN0001"]) == 6

    def test_gn0002_record_count(self, report):
        """GN0002 should have 6 monthly records."""
        assert len(report["ginniemae_pools"]["GN0002"]) == 6

    def test_gn0003_record_count(self, report):
        """GN0003 should have 6 monthly records."""
        assert len(report["ginniemae_pools"]["GN0003"]) == 6

    def test_gn0001_initial_values(self, report):
        """Verify GN0001 first record values from fixed-width parse."""
        first = report["ginniemae_pools"]["GN0001"][0]
        assert abs(first["original_face"] - 5000000.00) < 0.01
        assert abs(first["current_face"] - 5000000.00) < 0.01
        assert abs(first["pool_factor"] - 1.0) < 1e-6
        assert abs(first["security_rate"] - 4.0) < 0.01
        assert abs(first["wac"] - 4.5) < 0.01
        assert first["wam"] == 360
        assert first["wala"] == 0
        assert first["loan_count"] == 85

    def test_gn0002_initial_values(self, report):
        """Verify GN0002 first record values."""
        first = report["ginniemae_pools"]["GN0002"][0]
        assert abs(first["original_face"] - 8000000.00) < 0.01
        assert abs(first["security_rate"] - 3.5) < 0.01
        assert abs(first["wac"] - 3.875) < 0.01
        assert first["loan_count"] == 120

    def test_gn0003_month4_values(self, report):
        """Verify GN0003 at month 4 (April 2020)."""
        recs = report["ginniemae_pools"]["GN0003"]
        rec = recs[3]  # April = index 3
        assert abs(rec["current_face"] - 3144200.18) < 0.01
        assert abs(rec["pool_factor"] - 0.98256256) < 1e-6
        assert rec["wam"] == 177
        assert rec["wala"] == 3

    def test_factor_consistency(self, report):
        """Pool factor should equal current_face / original_face."""
        for pool_id in ["GN0001", "GN0002", "GN0003"]:
            for rec in report["ginniemae_pools"][pool_id]:
                expected_factor = rec["current_face"] / rec["original_face"]
                assert abs(rec["pool_factor"] - expected_factor) < 1e-5, (
                    f"Factor inconsistency for {pool_id}: "
                    f"{rec['pool_factor']} vs computed {expected_factor}"
                )

    def test_records_sorted_chronologically(self, report):
        """Records within each pool should be sorted by report_date."""
        for pool_id in ["GN0001", "GN0002", "GN0003"]:
            dates = [r["report_date"] for r in report["ginniemae_pools"][pool_id]]
            assert dates == sorted(dates), (
                f"Records not sorted for {pool_id}"
            )

    def test_ginniemae_record_keys(self, report):
        """Each Ginnie Mae pool record should have all required keys."""
        required_keys = {
            "report_date", "original_face", "current_face", "pool_factor",
            "security_rate", "wac", "wam", "wala", "loan_count"
        }
        for pool_id in ["GN0001", "GN0002", "GN0003"]:
            for rec in report["ginniemae_pools"][pool_id]:
                assert required_keys.issubset(set(rec.keys())), (
                    f"Missing keys in {pool_id}: {required_keys - set(rec.keys())}"
                )

    def test_gn0001_factor_decline(self, report):
        """GN0001 pool factor should decline month over month."""
        recs = report["ginniemae_pools"]["GN0001"]
        for i in range(1, len(recs)):
            assert recs[i]["pool_factor"] < recs[i-1]["pool_factor"], (
                f"GN0001 factor did not decline from {recs[i-1]['report_date']} "
                f"to {recs[i]['report_date']}"
            )

    def test_gn0003_faster_amortization(self, report):
        """GN0003 (15-year) should amortize faster than GN0001 (30-year)."""
        gn1_last = report["ginniemae_pools"]["GN0001"][-1]["pool_factor"]
        gn3_last = report["ginniemae_pools"]["GN0003"][-1]["pool_factor"]
        assert gn3_last < gn1_last, (
            f"15-year pool GN0003 ({gn3_last}) should have lower factor "
            f"than 30-year pool GN0001 ({gn1_last})"
        )


# =============================================
# Prepayment Detail Table Tests
# =============================================

class TestPrepaymentDetailTable:
    def test_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prepayment_detail'"
        )
        assert cursor.fetchone() is not None, "prepayment_detail table not found"

    def test_row_count(self, db):
        row = db.execute("SELECT count(*) as cnt FROM prepayment_detail").fetchone()
        assert row["cnt"] == 34, f"Expected 34 prepayment_detail rows, got {row['cnt']}"

    def test_columns(self, db):
        cursor = db.execute("PRAGMA table_info(prepayment_detail)")
        cols = {row["name"] for row in cursor}
        required = {"pool_id", "period", "smm", "cpr", "implied_psa"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_q1_prepay_smm_spike(self, db):
        """At 202011 when a loan prepays, SMM should spike."""
        row = db.execute(
            "SELECT smm FROM prepayment_detail WHERE pool_id='2020Q1' AND period='202011'"
        ).fetchone()
        assert row is not None, "Missing prepayment record for 2020Q1 at 202011"
        assert row["smm"] > 0.1, f"Expected high SMM at 202011, got {row['smm']}"

    def test_smm_cpr_consistency_in_table(self, db):
        """CPR should equal 1 - (1 - SMM)^12 for each record."""
        rows = db.execute("SELECT smm, cpr FROM prepayment_detail").fetchall()
        for row in rows:
            expected_cpr = 1.0 - (1.0 - row["smm"]) ** 12
            assert abs(row["cpr"] - expected_cpr) < 1e-6, (
                f"CPR/SMM inconsistency: smm={row['smm']}, cpr={row['cpr']}, expected={expected_cpr}"
            )

    def test_q2_pools_present(self, db):
        row = db.execute(
            "SELECT count(*) as cnt FROM prepayment_detail WHERE pool_id='2020Q2'"
        ).fetchone()
        assert row["cnt"] == 17, f"Expected 17 prepayment records for 2020Q2, got {row['cnt']}"


# =============================================
# Analytical View Tests
# =============================================

class TestAnalyticalViews:
    def test_v_prepayment_momentum_is_view(self, db):
        """v_prepayment_momentum must be a VIEW, not a table."""
        row = db.execute(
            "SELECT type FROM sqlite_master WHERE name='v_prepayment_momentum'"
        ).fetchone()
        assert row is not None, "v_prepayment_momentum not found in sqlite_master"
        assert row["type"] == "view", (
            f"v_prepayment_momentum should be a view, got type={row['type']}"
        )

    def test_v_prepayment_momentum_columns(self, db):
        cursor = db.execute("SELECT * FROM v_prepayment_momentum LIMIT 1")
        cols = {desc[0] for desc in cursor.description}
        required = {"pool_id", "period", "smm", "prev_smm", "smm_acceleration"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_v_prepayment_momentum_row_count(self, db):
        row = db.execute("SELECT count(*) as cnt FROM v_prepayment_momentum").fetchone()
        assert row["cnt"] == 34

    def test_v_prepayment_momentum_first_row_null(self, db):
        """First period per pool should have NULL prev_smm."""
        row = db.execute(
            "SELECT prev_smm, smm_acceleration FROM v_prepayment_momentum "
            "WHERE pool_id='2020Q1' ORDER BY period LIMIT 1"
        ).fetchone()
        assert row["prev_smm"] is None, "First period prev_smm should be NULL"
        assert row["smm_acceleration"] is None, "First period smm_acceleration should be NULL"

    def test_v_prepayment_momentum_acceleration_at_prepay(self, db):
        """At 202011 (prepay event), smm_acceleration should be strongly positive."""
        row = db.execute(
            "SELECT smm_acceleration FROM v_prepayment_momentum "
            "WHERE pool_id='2020Q1' AND period='202011'"
        ).fetchone()
        assert row is not None
        assert row["smm_acceleration"] > 0.1, (
            f"Expected positive acceleration at prepay event, got {row['smm_acceleration']}"
        )

    def test_v_prepayment_momentum_deceleration_after_prepay(self, db):
        """Period after bulk prepay should show negative acceleration."""
        row = db.execute(
            "SELECT smm_acceleration FROM v_prepayment_momentum "
            "WHERE pool_id='2020Q1' AND period='202012'"
        ).fetchone()
        assert row is not None
        assert row["smm_acceleration"] < -0.1, (
            f"Expected negative acceleration after prepay, got {row['smm_acceleration']}"
        )

    def test_v_factor_decline_rate_is_view(self, db):
        """v_factor_decline_rate must be a VIEW, not a table."""
        row = db.execute(
            "SELECT type FROM sqlite_master WHERE name='v_factor_decline_rate'"
        ).fetchone()
        assert row is not None, "v_factor_decline_rate not found in sqlite_master"
        assert row["type"] == "view", (
            f"v_factor_decline_rate should be a view, got type={row['type']}"
        )

    def test_v_factor_decline_rate_columns(self, db):
        cursor = db.execute("SELECT * FROM v_factor_decline_rate LIMIT 1")
        cols = {desc[0] for desc in cursor.description}
        required = {"pool_id", "report_date", "pool_factor", "prior_factor",
                     "decline_rate", "avg_decline_3"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_v_factor_decline_rate_row_count(self, db):
        row = db.execute("SELECT count(*) as cnt FROM v_factor_decline_rate").fetchone()
        assert row["cnt"] == 18, f"Expected 18 rows (3 pools x 6 dates), got {row['cnt']}"

    def test_v_factor_decline_rate_first_row_null(self, db):
        """First date per pool should have NULL prior_factor."""
        row = db.execute(
            "SELECT prior_factor, decline_rate FROM v_factor_decline_rate "
            "WHERE pool_id='GN0001' ORDER BY report_date LIMIT 1"
        ).fetchone()
        assert row["prior_factor"] is None, "First row prior_factor should be NULL"
        assert row["decline_rate"] is None, "First row decline_rate should be NULL"

    def test_v_factor_decline_rate_gn0001_feb(self, db):
        """Verify GN0001 decline rate at 20200201: prior=1.0, factor=0.99868304."""
        row = db.execute(
            "SELECT prior_factor, decline_rate, avg_decline_3 "
            "FROM v_factor_decline_rate "
            "WHERE pool_id='GN0001' AND report_date='20200201'"
        ).fetchone()
        assert row is not None
        assert abs(row["prior_factor"] - 1.0) < 1e-6
        expected_decline = 1.0 - 0.99868304
        assert abs(row["decline_rate"] - expected_decline) < 1e-5
        assert abs(row["avg_decline_3"] - expected_decline) < 1e-5

    def test_v_factor_decline_rate_trailing_avg(self, db):
        """Verify trailing average at 20200301 for GN0001 (avg of 2 non-null values)."""
        row = db.execute(
            "SELECT decline_rate, avg_decline_3 "
            "FROM v_factor_decline_rate "
            "WHERE pool_id='GN0001' AND report_date='20200301'"
        ).fetchone()
        assert row is not None
        decline_feb = 1.0 - 0.99868304
        decline_mar = 0.99868304 - 0.99736128
        expected_avg = (decline_feb + decline_mar) / 2.0
        assert abs(row["avg_decline_3"] - expected_avg) < 1e-5, (
            f"Trailing avg expected {expected_avg}, got {row['avg_decline_3']}"
        )

    def test_gn0003_faster_decline_in_view(self, db):
        """GN0003 (15-year) should decline faster than GN0001 (30-year) in the view."""
        gn1 = db.execute(
            "SELECT decline_rate FROM v_factor_decline_rate "
            "WHERE pool_id='GN0001' AND report_date='20200201'"
        ).fetchone()
        gn3 = db.execute(
            "SELECT decline_rate FROM v_factor_decline_rate "
            "WHERE pool_id='GN0003' AND report_date='20200201'"
        ).fetchone()
        assert gn3["decline_rate"] > gn1["decline_rate"] * 3, (
            f"15-year pool should decline much faster: GN0003={gn3['decline_rate']}, "
            f"GN0001={gn1['decline_rate']}"
        )


# =============================================
# Validation Script Tests
# =============================================

VALIDATE_SQL_PATH = "/app/output/validate.sql"


class TestValidationScript:
    def test_validate_sql_exists(self):
        assert os.path.exists(VALIDATE_SQL_PATH), "validate.sql not found"

    def test_validate_sql_executable(self):
        """validate.sql should be executable by sqlite3 without errors."""
        with open(VALIDATE_SQL_PATH) as f:
            result = subprocess.run(
                ["sqlite3", DB_PATH],
                stdin=f,
                capture_output=True, text=True, timeout=30
            )
        assert result.returncode == 0, f"sqlite3 failed: {result.stderr}"

    def test_validate_sql_output_format(self):
        """Each output line must be CHECK_NAME|PASS or CHECK_NAME|FAIL|detail."""
        with open(VALIDATE_SQL_PATH) as f:
            result = subprocess.run(
                ["sqlite3", DB_PATH],
                stdin=f,
                capture_output=True, text=True, timeout=30
            )
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        assert len(lines) >= 4, f"Expected at least 4 check lines, got {len(lines)}"
        for line in lines:
            parts = line.split('|')
            assert len(parts) >= 2, f"Invalid format: {line}"
            assert parts[1] in ('PASS', 'FAIL'), f"Invalid status in: {line}"

    def test_all_checks_pass(self):
        """All 4 required validation checks should pass."""
        with open(VALIDATE_SQL_PATH) as f:
            result = subprocess.run(
                ["sqlite3", DB_PATH],
                stdin=f,
                capture_output=True, text=True, timeout=30
            )
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        check_names = set()
        for line in lines:
            parts = line.split('|')
            check_names.add(parts[0])
            assert parts[1] == 'PASS', f"Check failed: {line}"

        required_checks = {'gm_factor_consistency', 'upb_non_negative',
                           'pool_factor_bounds', 'origination_upb_match'}
        assert required_checks.issubset(check_names), (
            f"Missing checks: {required_checks - check_names}"
        )
