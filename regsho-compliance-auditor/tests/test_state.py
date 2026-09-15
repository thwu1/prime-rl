
import json
import os
import sqlite3
import subprocess
import math
import pytest

AUDITOR = "/app/regsho_auditor.py"
SI_CSV = "/app/data/consolidated_si.csv"
FNSQ = "/app/data/fnsq_volume.txt"
FNYX = "/app/data/fnyx_volume.txt"
THRESHOLD = "/app/data/threshold_list.csv"
OUTPUT_DIR = "/app/output"
DB_PATH = "/app/regsho.db"


def run_cmd(args, timeout=120):
    result = subprocess.run(
        ["python3"] + args,
        capture_output=True, text=True, timeout=timeout, cwd="/app"
    )
    return result


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run pipeline.sh to create the SQLite database and generate reports."""
    result = subprocess.run(
        ["bash", "/app/pipeline.sh"],
        capture_output=True, text=True, timeout=180, cwd="/app"
    )
    return result


@pytest.fixture(scope="module")
def si_report():
    run_cmd([AUDITOR, "verify-si", SI_CSV])
    path = os.path.join(OUTPUT_DIR, "si_verification.json")
    assert os.path.exists(path), "si_verification.json not created"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def venue_report():
    run_cmd([AUDITOR, "reconcile-venues", FNSQ, FNYX])
    path = os.path.join(OUTPUT_DIR, "venue_reconciliation.json")
    assert os.path.exists(path), "venue_reconciliation.json not created"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def threshold_report():
    run_cmd([AUDITOR, "threshold-monitor", THRESHOLD])
    path = os.path.join(OUTPUT_DIR, "threshold_report.json")
    assert os.path.exists(path), "threshold_report.json not created"
    with open(path) as f:
        return json.load(f)


# -- pipeline and SQLite database tests ------------------------------------


class TestPipelineAndDatabase:
    def test_pipeline_succeeds(self, run_pipeline):
        assert run_pipeline.returncode == 0, \
            f"pipeline.sh failed (rc={run_pipeline.returncode}): {run_pipeline.stderr[:500]}"

    def test_database_exists(self, run_pipeline):
        assert os.path.exists(DB_PATH), "pipeline.sh must create /app/regsho.db"

    def test_short_interest_table_exists(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "short_interest" in tables, f"Missing short_interest table. Found: {tables}"

    def test_short_interest_row_count(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]
        conn.close()
        assert count == 200, f"short_interest should have 200 rows, has {count}"

    def test_short_interest_queryable(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        cols = [desc[0] for desc in conn.execute(
            "SELECT * FROM short_interest LIMIT 0"
        ).description]
        rows = conn.execute(
            "SELECT * FROM short_interest WHERE symbolCode = 'A'"
        ).fetchall()
        conn.close()
        assert "symbolCode" in cols, f"short_interest missing symbolCode column. Columns: {cols}"
        assert len(rows) >= 1, "Cannot query symbol A from short_interest"

    def test_short_interest_data_integrity(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT currentShortPositionQuantity, previousShortPositionQuantity, "
            "averageDailyVolumeQuantity FROM short_interest WHERE symbolCode = 'A'"
        ).fetchone()
        conn.close()
        assert row is not None, "Symbol A not found in short_interest"
        assert int(row[0]) == 4851353
        assert int(row[1]) == 4767556
        assert int(row[2]) == 2012318

    def test_venue_volume_table_exists(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "venue_volume" in tables, f"Missing venue_volume table. Found: {tables}"

    def test_venue_volume_has_venue_column(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        cols = [desc[0] for desc in conn.execute(
            "SELECT * FROM venue_volume LIMIT 0"
        ).description]
        conn.close()
        assert "venue" in cols, f"venue_volume missing venue column. Columns: {cols}"

    def test_venue_volume_row_count(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM venue_volume").fetchone()[0]
        conn.close()
        # FNSQ: 12120 data rows, FNYX: 7649 data rows = 19769 total
        assert count == 19769, f"venue_volume should have 19769 rows, has {count}"

    def test_venue_volume_venues(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        venues = {row[0] for row in conn.execute(
            "SELECT DISTINCT venue FROM venue_volume"
        ).fetchall()}
        conn.close()
        assert venues == {"FNSQ", "FNYX"}, f"Expected venues FNSQ, FNYX; got {venues}"

    def test_venue_volume_aggregation_via_sql(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT SUM(CAST(ShortVolume AS REAL)), SUM(CAST(TotalVolume AS REAL)) "
            "FROM venue_volume WHERE Symbol = 'A'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(float(row[0]) - 581786.026184) < 0.01
        assert abs(float(row[1]) - 822671.040863) < 0.01

    def test_threshold_list_table_exists(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "threshold_list" in tables, f"Missing threshold_list table. Found: {tables}"

    def test_threshold_list_row_count(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM threshold_list").fetchone()[0]
        conn.close()
        assert count == 52, f"threshold_list should have 52 rows, has {count}"

    def test_threshold_regsho_query(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(DISTINCT issueSymbolIdentifier) FROM threshold_list "
            "WHERE regShoThresholdFlag = 'Y'"
        ).fetchone()[0]
        conn.close()
        assert count == 7, f"Expected 7 regSho=Y symbols, got {count}"


# -- SQL view tests --------------------------------------------------------


class TestSQLViews:
    def test_venue_agg_view_exists(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        views = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()}
        conn.close()
        assert "venue_symbol_agg" in views, f"Missing venue_symbol_agg view. Found: {views}"

    def test_venue_agg_symbol_a_volumes(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT short_volume, short_exempt_volume, total_volume "
            "FROM venue_symbol_agg WHERE symbol = 'A'"
        ).fetchone()
        conn.close()
        assert row is not None, "Symbol A not in venue_symbol_agg"
        assert row[0] == 581786, f"short_volume expected 581786, got {row[0]}"
        assert row[1] == 2210, f"short_exempt_volume expected 2210, got {row[1]}"
        assert row[2] == 822671, f"total_volume expected 822671, got {row[2]}"

    def test_venue_agg_symbol_a_ratio(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT short_ratio FROM venue_symbol_agg WHERE symbol = 'A'"
        ).fetchone()
        conn.close()
        assert row is not None
        expected = round(581786 / 822671, 6)
        assert abs(row[0] - expected) < 1e-4, \
            f"short_ratio expected ~{expected}, got {row[0]}"

    def test_venue_agg_symbol_a_venue_count(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT venue_count FROM venue_symbol_agg WHERE symbol = 'A'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 2, f"venue_count expected 2, got {row[0]}"

    def test_venue_agg_truncation_not_rounding(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT short_volume FROM venue_symbol_agg WHERE symbol = 'AA'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 1485766, f"AA short_volume expected 1485766 (truncated), got {row[0]}"

    def test_venue_agg_single_venue_symbol(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT venue_count, total_volume FROM venue_symbol_agg WHERE symbol = 'AAA'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 1, f"AAA venue_count expected 1, got {row[0]}"
        assert row[1] == 8779, f"AAA total_volume expected 8779, got {row[1]}"

    def test_threshold_streaks_view_exists(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        views = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()}
        conn.close()
        assert "threshold_streaks" in views, \
            f"Missing threshold_streaks view. Found: {views}"

    def test_threshold_streaks_acmex(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT max_consecutive_days, closeout_eligible "
            "FROM threshold_streaks WHERE symbol = 'ACMEX'"
        ).fetchone()
        conn.close()
        assert row is not None, "ACMEX not in threshold_streaks"
        assert row[0] == 10, f"ACMEX max_consecutive expected 10, got {row[0]}"
        assert row[1] == 1, f"ACMEX closeout_eligible expected 1, got {row[1]}"

    def test_threshold_streaks_dpqrt_gap_reset(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT max_consecutive_days, closeout_eligible "
            "FROM threshold_streaks WHERE symbol = 'DPQRT'"
        ).fetchone()
        conn.close()
        assert row is not None, "DPQRT not in threshold_streaks"
        assert row[0] == 5, f"DPQRT max_consecutive expected 5, got {row[0]}"
        assert row[1] == 1, f"DPQRT closeout_eligible expected 1, got {row[1]}"

    def test_threshold_streaks_cxlnr_no_trigger(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT max_consecutive_days, closeout_eligible "
            "FROM threshold_streaks WHERE symbol = 'CXLNR'"
        ).fetchone()
        conn.close()
        assert row is not None, "CXLNR not in threshold_streaks"
        assert row[0] == 4, f"CXLNR max_consecutive expected 4, got {row[0]}"
        assert row[1] == 0, f"CXLNR closeout_eligible expected 0, got {row[1]}"

    def test_threshold_streaks_hjktw(self, run_pipeline):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT max_consecutive_days, closeout_eligible "
            "FROM threshold_streaks WHERE symbol = 'HJKTW'"
        ).fetchone()
        conn.close()
        assert row is not None, "HJKTW not in threshold_streaks"
        assert row[0] == 2, f"HJKTW max_consecutive expected 2, got {row[0]}"
        assert row[1] == 0, f"HJKTW closeout_eligible expected 0, got {row[1]}"


# -- verify-si tests ------------------------------------------------------


class TestVerifySI:
    def test_output_has_required_keys(self, si_report):
        for key in ["total_records", "pass_count", "fail_count",
                     "dtc_cap_symbols", "dtc_floor_symbols", "records"]:
            assert key in si_report, f"Missing key: {key}"

    def test_total_records(self, si_report):
        assert si_report["total_records"] == 200

    def test_records_count_matches(self, si_report):
        assert len(si_report["records"]) == 200

    def test_pass_fail_sum(self, si_report):
        assert si_report["pass_count"] + si_report["fail_count"] == 200

    def test_high_pass_rate(self, si_report):
        assert si_report["pass_count"] >= 195

    def test_change_number_symbol_a(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "A")
        assert rec["changePreviousNumber"]["computed"] == 83797
        assert rec["changePreviousNumber"]["reported"] == 83797
        assert rec["changePreviousNumber"]["pass"] is True

    def test_change_number_symbol_aal(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "AAL")
        assert rec["changePreviousNumber"]["computed"] == 26294698
        assert rec["changePreviousNumber"]["pass"] is True

    def test_change_percent_symbol_a(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "A")
        assert abs(rec["changePercent"]["computed"] - 1.76) < 0.015
        assert rec["changePercent"]["pass"] is True

    def test_change_percent_negative(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "AAALF")
        assert abs(rec["changePercent"]["computed"] - (-21.01)) < 0.015
        assert rec["changePercent"]["pass"] is True

    def test_dtc_cap_zero_volume(self, si_report):
        assert "AAALF" in si_report["dtc_cap_symbols"]

    def test_dtc_cap_high_ratio(self, si_report):
        assert "AACAF" in si_report["dtc_cap_symbols"]

    def test_dtc_floor_low_ratio(self, si_report):
        assert "AACAY" in si_report["dtc_floor_symbols"]

    def test_dtc_floor_another(self, si_report):
        assert "AACTF" in si_report["dtc_floor_symbols"]

    def test_dtc_normal_computation(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "A")
        assert abs(rec["daysToCoverQuantity"]["computed"] - 2.41) < 0.015
        assert rec["daysToCoverQuantity"]["pass"] is True

    def test_dtc_high_value_not_capped(self, si_report):
        rec = next(r for r in si_report["records"] if r["symbol"] == "ADEVF")
        assert abs(rec["daysToCoverQuantity"]["computed"] - 592.74) < 0.015
        assert "ADEVF" not in si_report["dtc_cap_symbols"]


# -- reconcile-venues tests -----------------------------------------------


class TestReconcileVenues:
    def test_output_has_required_keys(self, venue_report):
        for key in ["total_symbols", "venues", "multi_venue_count",
                     "single_venue_count", "symbols"]:
            assert key in venue_report, f"Missing key: {key}"

    def test_venues_identified(self, venue_report):
        venues = sorted(venue_report["venues"])
        assert venues == ["FNSQ", "FNYX"]

    def test_total_symbols_reasonable(self, venue_report):
        assert venue_report["total_symbols"] > 12000

    def test_multi_plus_single_equals_total(self, venue_report):
        assert (venue_report["multi_venue_count"] +
                venue_report["single_venue_count"]) == venue_report["total_symbols"]

    def test_symbol_a_aggregation(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "A")
        assert sym["short_volume"] == 581786
        assert sym["total_volume"] == 822671

    def test_symbol_a_short_exempt(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "A")
        assert sym["short_exempt_volume"] == 2210

    def test_symbol_a_short_ratio(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "A")
        expected = round(581786 / 822671, 6)
        assert abs(sym["short_ratio"] - expected) < 1e-5

    def test_symbol_a_venues(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "A")
        assert sorted(sym["venues"]) == ["FNSQ", "FNYX"]

    def test_symbol_a_venue_breakdown(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "A")
        fnsq = sym["venue_breakdown"]["FNSQ"]
        assert abs(fnsq["short_volume"] - 548037.250704) < 0.01
        assert abs(fnsq["total_volume"] - 778975.318823) < 0.01

    def test_truncation_not_rounding(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "AA")
        assert sym["short_volume"] == 1485766

    def test_single_venue_symbol(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "AAA")
        assert len(sym["venues"]) == 1
        assert sym["venues"][0] == "FNSQ"

    def test_single_venue_truncation(self, venue_report):
        sym = next(s for s in venue_report["symbols"] if s["symbol"] == "AAA")
        assert sym["total_volume"] == 8779


# -- threshold-monitor tests ----------------------------------------------


class TestThresholdMonitor:
    def test_output_has_required_keys(self, threshold_report):
        for key in ["date_range", "settlement_days", "securities_tracked",
                     "closeout_triggered", "rule4320_only", "per_symbol"]:
            assert key in threshold_report, f"Missing key: {key}"

    def test_date_range(self, threshold_report):
        assert threshold_report["date_range"] == ["2024-03-04", "2024-03-15"]

    def test_settlement_days(self, threshold_report):
        assert threshold_report["settlement_days"] == 10

    def test_securities_tracked(self, threshold_report):
        assert threshold_report["securities_tracked"] == 7

    def test_closeout_count(self, threshold_report):
        assert len(threshold_report["closeout_triggered"]) == 5

    def test_closeout_symbols(self, threshold_report):
        triggered = {c["symbol"] for c in threshold_report["closeout_triggered"]}
        assert triggered == {"ACMEX", "BRDGW", "DPQRT", "FKLMN", "GNPQV"}

    def test_acmex_trigger_date(self, threshold_report):
        acmex = next(c for c in threshold_report["closeout_triggered"]
                     if c["symbol"] == "ACMEX")
        assert acmex["trigger_date"] == "2024-03-08"
        assert acmex["consecutive_days_at_trigger"] == 5

    def test_dpqrt_gap_reset(self, threshold_report):
        dpqrt = next(c for c in threshold_report["closeout_triggered"]
                     if c["symbol"] == "DPQRT")
        assert dpqrt["trigger_date"] == "2024-03-15"
        assert dpqrt["consecutive_days_at_trigger"] == 5

    def test_dpqrt_per_symbol(self, threshold_report):
        dpqrt = threshold_report["per_symbol"]["DPQRT"]
        assert dpqrt["max_consecutive_days"] == 5
        assert dpqrt["closeout_required"] is True
        assert dpqrt["trigger_date"] == "2024-03-15"

    def test_cxlnr_no_trigger(self, threshold_report):
        cxlnr = threshold_report["per_symbol"]["CXLNR"]
        assert cxlnr["max_consecutive_days"] == 4
        assert cxlnr["closeout_required"] is False
        assert cxlnr["trigger_date"] is None

    def test_hjktw_no_trigger(self, threshold_report):
        hjktw = threshold_report["per_symbol"]["HJKTW"]
        assert hjktw["max_consecutive_days"] == 2
        assert hjktw["closeout_required"] is False

    def test_rule4320_only(self, threshold_report):
        assert "EMFGZ" in threshold_report["rule4320_only"]
        assert len(threshold_report["rule4320_only"]) == 1

    def test_gnpqv_not_in_rule4320_only(self, threshold_report):
        assert "GNPQV" not in threshold_report["rule4320_only"]

    def test_acmex_max_consecutive(self, threshold_report):
        acmex = threshold_report["per_symbol"]["ACMEX"]
        assert acmex["max_consecutive_days"] == 10

    def test_fklmn_trigger(self, threshold_report):
        fklmn = next(c for c in threshold_report["closeout_triggered"]
                     if c["symbol"] == "FKLMN")
        assert fklmn["trigger_date"] == "2024-03-08"


# -- pipeline summary (jq output) tests -----------------------------------


class TestPipelineSummary:
    def _load_summary(self):
        path = os.path.join(OUTPUT_DIR, "pipeline_summary.json")
        with open(path) as f:
            return json.load(f)

    def test_summary_exists(self, run_pipeline):
        path = os.path.join(OUTPUT_DIR, "pipeline_summary.json")
        assert os.path.exists(path), "pipeline_summary.json not created"

    def test_summary_has_required_keys(self, run_pipeline):
        summary = self._load_summary()
        for key in ["si_pass_rate", "si_total", "venue_total_symbols",
                     "venue_multi_pct", "threshold_securities",
                     "threshold_closeout_count", "closeout_symbols"]:
            assert key in summary, f"Missing key in pipeline_summary: {key}"

    def test_summary_si_total(self, run_pipeline):
        summary = self._load_summary()
        assert summary["si_total"] == 200

    def test_summary_si_pass_rate(self, run_pipeline):
        summary = self._load_summary()
        assert 0.9 < summary["si_pass_rate"] <= 1.0, \
            f"si_pass_rate out of range: {summary['si_pass_rate']}"

    def test_summary_venue_total(self, run_pipeline):
        summary = self._load_summary()
        assert summary["venue_total_symbols"] > 12000

    def test_summary_venue_multi_pct(self, run_pipeline):
        summary = self._load_summary()
        assert 0 < summary["venue_multi_pct"] < 100, \
            f"venue_multi_pct out of range: {summary['venue_multi_pct']}"

    def test_summary_threshold_securities(self, run_pipeline):
        summary = self._load_summary()
        assert summary["threshold_securities"] == 7

    def test_summary_closeout_count(self, run_pipeline):
        summary = self._load_summary()
        assert summary["threshold_closeout_count"] == 5

    def test_summary_closeout_symbols(self, run_pipeline):
        summary = self._load_summary()
        assert sorted(summary["closeout_symbols"]) == [
            "ACMEX", "BRDGW", "DPQRT", "FKLMN", "GNPQV"
        ]


# -- pipeline tool usage tests --------------------------------------------


class TestPipelineToolUsage:
    def test_uses_sqlite3_import(self, run_pipeline):
        with open("/app/pipeline.sh") as f:
            content = f.read()
        assert ".import" in content, \
            "pipeline.sh must load data via sqlite3 CLI .import directives"

    def test_uses_jq(self, run_pipeline):
        with open("/app/pipeline.sh") as f:
            content = f.read()
        assert "jq" in content, \
            "pipeline.sh must use jq to generate pipeline_summary.json"
