
import subprocess
import json
import pytest
import os
import sqlite3


def run_cmd(args, expect_success=True, cwd="/app"):
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=120)
    if expect_success:
        assert result.returncode == 0, (
            f"Command {' '.join(args)} failed with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        return json.loads(result.stdout.strip())
    return result


class TestPipelineInfrastructure:
    """Verify pipeline components exist and work."""

    def test_xslt_nominal_exists(self):
        assert os.path.isfile("/app/xsl/nominal.xsl"), (
            "XSLT stylesheet for nominal yields missing"
        )

    def test_xslt_real_exists(self):
        assert os.path.isfile("/app/xsl/real.xsl"), (
            "XSLT stylesheet for real yields missing"
        )

    def test_schema_exists(self):
        assert os.path.isfile("/app/schema.sql"), "SQLite schema file missing"

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile missing"

    def test_tips_analytics_exists(self):
        assert os.path.isfile("/app/tips_analytics.py"), "Python CLI missing"

    def test_database_exists(self):
        assert os.path.isfile("/app/treasury.db"), "SQLite database missing"

    def test_xsltproc_nominal_produces_csv(self):
        """Verify xsltproc with nominal XSLT produces valid wide CSV."""
        result = subprocess.run(
            ["xsltproc", "/app/xsl/nominal.xsl", "/app/data/nominal_yields.xml"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"xsltproc failed: {result.stderr}"
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) > 200, f"Expected >200 rows, got {len(lines)}"
        parts = lines[0].split(",")
        assert len(parts) == 14, (
            f"Expected 14 columns (date + 13 tenors), got {len(parts)}"
        )
        assert parts[0][:4] == "2024", f"Expected date starting 2024, got {parts[0]}"
        for i in range(1, 14):
            float(parts[i])

    def test_xsltproc_real_produces_csv(self):
        """Verify xsltproc with real XSLT produces valid wide CSV."""
        result = subprocess.run(
            ["xsltproc", "/app/xsl/real.xsl", "/app/data/real_yields.xml"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"xsltproc failed: {result.stderr}"
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) > 200, f"Expected >200 rows, got {len(lines)}"
        parts = lines[0].split(",")
        assert len(parts) == 6, (
            f"Expected 6 columns (date + 5 tenors), got {len(parts)}"
        )

    def test_xslt_nominal_date_format(self):
        """Verify XSLT produces YYYY-MM-DD dates."""
        result = subprocess.run(
            ["xsltproc", "/app/xsl/nominal.xsl", "/app/data/nominal_yields.xml"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        date = lines[0].split(",")[0]
        assert len(date) == 10, f"Date '{date}' not in YYYY-MM-DD format"
        assert date[4] == "-" and date[7] == "-", f"Date '{date}' not YYYY-MM-DD"

    def test_xslt_data_consistency(self):
        """Verify XSLT nominal output matches known values from XML."""
        result = subprocess.run(
            ["xsltproc", "/app/xsl/nominal.xsl", "/app/data/nominal_yields.xml"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        first = lines[0].split(",")
        assert first[0] == "2024-01-02"
        assert abs(float(first[1]) - 5.55) < 0.001, "BC_1MONTH mismatch"
        assert abs(float(first[11]) - 3.95) < 0.001, "BC_10YEAR mismatch"
        assert abs(float(first[13]) - 4.08) < 0.001, "BC_30YEAR mismatch"


class TestDatabaseSchema:
    """Verify SQLite database structure and content."""

    @pytest.fixture
    def conn(self):
        c = sqlite3.connect("/app/treasury.db")
        yield c
        c.close()

    def test_nominal_yields_table(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM nominal_yields").fetchone()
        assert rows[0] > 2000, f"Expected >2000 nominal yield rows, got {rows[0]}"

    def test_real_yields_table(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM real_yields").fetchone()
        assert rows[0] > 1000, f"Expected >1000 real yield rows, got {rows[0]}"

    def test_h15_rates_table(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM h15_rates").fetchone()
        assert rows[0] > 2000, f"Expected >2000 H.15 rate rows, got {rows[0]}"

    def test_cpi_monthly_table(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM cpi_monthly").fetchone()
        assert rows[0] >= 48, f"Expected >=48 CPI rows, got {rows[0]}"

    def test_tips_securities_table(self, conn):
        rows = conn.execute("SELECT COUNT(*) FROM tips_securities").fetchone()
        assert rows[0] >= 50, f"Expected >=50 TIPS records, got {rows[0]}"

    def test_nominal_yields_sample(self, conn):
        row = conn.execute(
            "SELECT rate FROM nominal_yields "
            "WHERE date='2024-01-02' AND abs(tenor-10.0)<0.01"
        ).fetchone()
        assert row is not None, "Missing 2024-01-02 10yr nominal yield"
        assert abs(row[0] - 3.95) < 0.01, f"10yr yield mismatch: {row[0]} vs 3.95"

    def test_real_yields_sample(self, conn):
        row = conn.execute(
            "SELECT rate FROM real_yields "
            "WHERE date='2024-01-02' AND abs(tenor-10.0)<0.01"
        ).fetchone()
        assert row is not None, "Missing 2024-01-02 10yr real yield"
        assert abs(row[0] - 1.74) < 0.01, f"10yr real yield mismatch: {row[0]}"

    def test_cpi_sample(self, conn):
        row = conn.execute(
            "SELECT value FROM cpi_monthly WHERE year=2024 AND month=1"
        ).fetchone()
        assert row is not None, "Missing 2024-01 CPI"
        assert abs(row[0] - 308.417) < 0.01

    def test_h15_sample(self, conn):
        row = conn.execute(
            "SELECT rate FROM h15_rates "
            "WHERE date='2024-01-02' AND series_id='RIFLGFCY10_N.B'"
        ).fetchone()
        assert row is not None, "Missing 2024-01-02 10yr H.15 rate"
        assert abs(row[0] - 3.95) < 0.01

    def test_uniqueness_constraint(self, conn):
        """Verify UNIQUE constraints prevent duplicate rows."""
        count_before = conn.execute(
            "SELECT COUNT(*) FROM cpi_monthly"
        ).fetchone()[0]
        try:
            conn.execute(
                "INSERT INTO cpi_monthly(year, month, value) VALUES (2024, 1, 999.0)"
            )
        except sqlite3.IntegrityError:
            pass
        count_after = conn.execute(
            "SELECT COUNT(*) FROM cpi_monthly"
        ).fetchone()[0]
        assert count_after == count_before, "Duplicate row was inserted"

    def test_nominal_tenor_count_per_date(self, conn):
        """Verify 13 tenors per trading day in nominal yields."""
        row = conn.execute(
            "SELECT COUNT(*) FROM nominal_yields WHERE date='2024-01-02'"
        ).fetchone()
        assert row[0] == 13, f"Expected 13 tenors, got {row[0]}"

    def test_real_tenor_count_per_date(self, conn):
        """Verify 5 tenors per trading day in real yields."""
        row = conn.execute(
            "SELECT COUNT(*) FROM real_yields WHERE date='2024-01-02'"
        ).fetchone()
        assert row[0] == 5, f"Expected 5 tenors, got {row[0]}"


class TestRefCpi:
    """Verify Reference CPI computation against Treasury golden values."""

    def test_first_day_of_month(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-01-01"
        ])
        assert abs(out["ref_cpi"] - 307.671) < 0.001

    def test_mid_month(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-07-15"
        ])
        assert abs(out["ref_cpi"] - 313.783290) < 0.001

    def test_end_of_year(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-12-31"
        ])
        assert abs(out["ref_cpi"] - 315.652290) < 0.001

    def test_leap_year_feb29(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-02-29"
        ])
        assert abs(out["ref_cpi"] - 306.756520) < 0.001

    def test_declining_cpi_interpolation(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-01-31"
        ])
        assert abs(out["ref_cpi"] - 307.071) < 0.001

    def test_date_output_format(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-06-15"
        ])
        assert "date" in out
        assert "ref_cpi" in out
        assert isinstance(out["ref_cpi"], (int, float))

    def test_early_2021(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2021-04-30"
        ])
        assert abs(out["ref_cpi"] - 262.966270) < 0.001

    def test_insufficient_data_fails(self):
        result = run_cmd(
            ["python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2020-01-15"],
            expect_success=False,
        )
        assert result.returncode != 0


class TestIndexRatio:
    """Verify TIPS index ratio computation."""

    def test_ratio_above_one(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "index-ratio", "--date", "2024-12-31", "--cusip", "91282CLV1",
        ])
        assert abs(out["index_ratio"] - 1.003170) < 0.00010
        assert abs(out["floored_index_ratio"] - out["index_ratio"]) < 0.00001

    def test_ratio_different_cusip(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "index-ratio", "--date", "2024-11-29", "--cusip", "91282CLE9",
        ])
        assert abs(out["index_ratio"] - 1.004730) < 0.00010

    def test_deflation_floor_applied(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "index-ratio", "--date", "2024-01-31", "--cusip", "91282CJY8",
        ])
        assert out["index_ratio"] < 1.0
        assert abs(out["floored_index_ratio"] - 1.0) < 0.00001

    def test_output_fields(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "index-ratio", "--date", "2024-07-31", "--cusip", "91282CLE9",
        ])
        required_keys = [
            "date", "cusip", "ref_cpi_settlement",
            "ref_cpi_base", "index_ratio", "floored_index_ratio",
        ]
        for key in required_keys:
            assert key in out, f"Missing key: {key}"
        assert out["ref_cpi_base"] > 0
        assert out["ref_cpi_settlement"] > 0

    def test_large_index_ratio(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "index-ratio", "--date", "2022-08-31", "--cusip", "912810TE8",
        ])
        assert abs(out["index_ratio"] - 1.063970) < 0.0005


class TestBootstrap:
    """Verify zero-coupon yield curve bootstrap."""

    def test_nominal_basic_properties(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "bootstrap", "--date", "12/31/2024", "--curve", "nominal",
        ])
        assert out["curve_type"] == "nominal"
        assert len(out["tenors"]) == 13
        assert len(out["spot_rates"]) == 13
        assert len(out["discount_factors"]) == 13

        for sr in out["spot_rates"]:
            assert sr > 0, f"Spot rate should be positive, got {sr}"

        for i in range(1, len(out["discount_factors"])):
            assert out["discount_factors"][i] < out["discount_factors"][i - 1], (
                f"Discount factors not decreasing at index {i}"
            )

    def test_nominal_roundtrip(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "bootstrap", "--date", "12/31/2024", "--curve", "nominal",
        ])
        assert out["max_roundtrip_error_bps"] < 0.1, (
            f"Roundtrip error too large: {out['max_roundtrip_error_bps']} bps"
        )

    def test_real_basic_properties(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "bootstrap", "--date", "12/31/2024", "--curve", "real",
        ])
        assert out["curve_type"] == "real"
        assert len(out["tenors"]) == 5
        assert len(out["spot_rates"]) == 5
        for sr in out["spot_rates"]:
            assert sr > 0

    def test_real_roundtrip(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "bootstrap", "--date", "12/31/2024", "--curve", "real",
        ])
        assert out["max_roundtrip_error_bps"] < 0.1

    def test_different_date(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "bootstrap", "--date", "01/02/2024", "--curve", "nominal",
        ])
        assert out["max_roundtrip_error_bps"] < 0.1
        assert out["spot_rates"][4] > out["spot_rates"][-1]


class TestForwardBreakeven:
    """Verify breakeven inflation and forward rate computation."""

    def test_par_breakeven_dec31(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "12/31/2024",
        ])
        assert abs(out["par_breakeven"]["5"] - 2.38) < 0.02
        assert abs(out["par_breakeven"]["10"] - 2.34) < 0.02

    def test_par_breakeven_jan02(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "01/02/2024",
        ])
        assert abs(out["par_breakeven"]["5"] - 2.17) < 0.02
        assert abs(out["par_breakeven"]["10"] - 2.21) < 0.02

    def test_all_par_breakeven_tenors(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "12/31/2024",
        ])
        for tenor in ["5", "7", "10", "20", "30"]:
            assert tenor in out["par_breakeven"], f"Missing tenor {tenor}"
            val = out["par_breakeven"][tenor]
            assert 0.5 < val < 5.0, (
                f"Breakeven at {tenor}yr = {val}% out of range"
            )

    def test_forward_5y5y_reasonable(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "12/31/2024",
        ])
        assert 1.0 < out["forward_5y5y_breakeven"] < 4.0, (
            f"Forward 5y5y breakeven {out['forward_5y5y_breakeven']}% unreasonable"
        )

    def test_forward_internal_consistency(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "12/31/2024",
        ])
        diff = out["forward_5y5y_nominal"] - out["forward_5y5y_real"]
        assert abs(diff - out["forward_5y5y_breakeven"]) < 0.01, (
            f"Inconsistency: {out['forward_5y5y_nominal']} - "
            f"{out['forward_5y5y_real']} != {out['forward_5y5y_breakeven']}"
        )

    def test_forward_nominal_positive(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "forward-breakeven", "--date", "12/31/2024",
        ])
        assert out["forward_5y5y_nominal"] > 0
        assert out["forward_5y5y_real"] > 0


class TestValidate:
    """Verify cross-validation against Treasury golden values."""

    def test_validate_runs(self):
        out = run_cmd(["python3", "/app/tips_analytics.py", "validate"])
        assert "total_checked" in out
        assert "passed" in out
        assert "max_ref_cpi_error" in out
        assert "max_index_ratio_error" in out

    def test_sufficient_coverage(self):
        out = run_cmd(["python3", "/app/tips_analytics.py", "validate"])
        assert out["total_checked"] >= 50, (
            f"Only {out['total_checked']} records checked, expected >= 50"
        )

    def test_high_pass_rate(self):
        out = run_cmd(["python3", "/app/tips_analytics.py", "validate"])
        pass_rate = out["passed"] / out["total_checked"]
        assert pass_rate >= 0.95, f"Pass rate {pass_rate:.2%} below 95%"

    def test_error_tolerances(self):
        out = run_cmd(["python3", "/app/tips_analytics.py", "validate"])
        assert out["max_ref_cpi_error"] < 0.001, (
            f"Max RefCPI error {out['max_ref_cpi_error']} exceeds 0.001"
        )
        assert out["max_index_ratio_error"] < 0.00005, (
            f"Max index ratio error {out['max_index_ratio_error']} exceeds 0.00005"
        )


class TestReconcile:
    """Verify cross-source yield reconciliation."""

    def test_reconcile_trading_day(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "reconcile", "--date", "2024-01-02",
        ])
        assert out["matched_tenors"] == 11
        assert out["max_abs_diff"] < 0.01

    def test_reconcile_all_diffs_reported(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "reconcile", "--date", "2024-01-02",
        ])
        assert "diffs" in out
        assert isinstance(out["diffs"], dict)
        assert len(out["diffs"]) == 11

    def test_reconcile_end_of_year(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "reconcile", "--date", "2024-12-31",
        ])
        assert out["matched_tenors"] == 11
        assert out["max_abs_diff"] < 0.01

    def test_reconcile_non_trading_day(self):
        result = run_cmd(
            [
                "python3", "/app/tips_analytics.py",
                "reconcile", "--date", "2024-01-01",
            ],
            expect_success=False,
        )
        assert result.returncode != 0

    def test_reconcile_output_fields(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "reconcile", "--date", "2024-06-03",
        ])
        assert "date" in out
        assert "matched_tenors" in out
        assert "max_abs_diff" in out
        assert "diffs" in out
        assert out["date"] == "2024-06-03"
        assert out["matched_tenors"] >= 1

    def test_reconcile_mid_year(self):
        out = run_cmd([
            "python3", "/app/tips_analytics.py",
            "reconcile", "--date", "2024-07-01",
        ])
        assert out["matched_tenors"] == 11
        assert out["max_abs_diff"] < 0.01


class TestMakefileRebuild:
    """Verify Makefile clean and rebuild cycle (runs last)."""

    def test_make_clean_removes_artifacts(self):
        result = subprocess.run(
            ["make", "clean"],
            capture_output=True, text=True, cwd="/app", timeout=30,
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr}"
        assert not os.path.isfile("/app/treasury.db"), "DB not removed by make clean"

    def test_make_db_rebuilds_pipeline(self):
        """Rebuild after clean and verify everything works."""
        if os.path.isfile("/app/treasury.db"):
            subprocess.run(
                ["make", "clean"],
                capture_output=True, text=True, cwd="/app", timeout=30,
            )

        result = subprocess.run(
            ["make", "db"],
            capture_output=True, text=True, cwd="/app", timeout=120,
        )
        assert result.returncode == 0, (
            f"make db failed: {result.stderr}\nstdout: {result.stdout}"
        )
        assert os.path.isfile("/app/treasury.db"), "DB not created by make db"

        conn = sqlite3.connect("/app/treasury.db")
        nom = conn.execute("SELECT COUNT(*) FROM nominal_yields").fetchone()[0]
        conn.close()
        assert nom > 2000, f"DB has only {nom} nominal rows after rebuild"

    def test_post_rebuild_analytics_work(self):
        """Verify analytics still work after clean+rebuild."""
        if not os.path.isfile("/app/treasury.db"):
            subprocess.run(
                ["make", "db"],
                capture_output=True, text=True, cwd="/app", timeout=120,
            )

        out = run_cmd([
            "python3", "/app/tips_analytics.py", "ref-cpi", "--date", "2024-01-01"
        ])
        assert abs(out["ref_cpi"] - 307.671) < 0.001
