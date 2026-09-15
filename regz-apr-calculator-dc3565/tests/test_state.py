
"""
Tests for Regulation Z APR Compliance Pipeline.
Verifies the APR calculator, Make-orchestrated pipeline with sqlite3/jq
integration, intermediate NDJSON files, SQLite database, and JSON summary.
"""

import json
import os
import re
import sqlite3
import subprocess
import tempfile
import pytest

TOOL_PATH = "/app/regz_apr"
PIPELINE_PATH = "/app/compliance_pipeline"
LOANS_DIR = "/app/loans"
DB_PATH = "/app/results.db"
MAKEFILE_PATH = "/app/Makefile"
SCHEMA_PATH = "/app/schema.sql"
APOR_PATH = "/app/reference/apor_fixed.dat"
BUILD_DIR = "/app/build"

# Golden APR values from Regulation Z Appendix J and Section 1026.22 commentary
GOLDEN = {
    "single_payment_whole": {
        "computed_apr": 10.00,
        "transaction_type": "regular",
        "tolerance_pct": 0.125,
        "within_tolerance": True,
    },
    "single_payment_nonwhole": {
        "computed_apr": 16.22,
        "transaction_type": "regular",
        "tolerance_pct": 0.125,
        "within_tolerance": None,
    },
    "regular_monthly": {
        "computed_apr": 12.00,
        "transaction_type": "regular",
        "tolerance_pct": 0.125,
        "within_tolerance": False,
    },
    "step_rate": {
        "computed_apr": 10.75,
        "transaction_type": "irregular",
        "tolerance_pct": 0.25,
        "within_tolerance": True,
    },
    "student_loan": {
        "computed_apr": 32.04,
        "transaction_type": "irregular",
        "tolerance_pct": 0.25,
        "within_tolerance": True,
    },
}

# Golden database values for pipeline verification
GOLDEN_DB = {
    "single_payment_whole": {
        "term_years": 1, "apor_rate": 4.50,
        "rate_spread": 5.50, "high_cost": 0, "within_tolerance": 1,
    },
    "single_payment_nonwhole": {
        "term_years": 1, "apor_rate": 4.50,
        "rate_spread": 11.72, "high_cost": 1, "within_tolerance": None,
    },
    "regular_monthly": {
        "term_years": 3, "apor_rate": 5.00,
        "rate_spread": 7.00, "high_cost": 1, "within_tolerance": 0,
    },
    "step_rate": {
        "term_years": 5, "apor_rate": 5.50,
        "rate_spread": 5.25, "high_cost": 0, "within_tolerance": 1,
    },
    "student_loan": {
        "term_years": 4, "apor_rate": 5.00,
        "rate_spread": 27.04, "high_cost": 1, "within_tolerance": 1,
    },
}


@pytest.fixture(scope="module")
def pipeline_result():
    """Run the compliance pipeline once for all pipeline tests."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    result = subprocess.run(
        [PIPELINE_PATH],
        capture_output=True, text=True, timeout=300, cwd="/app",
    )
    return result


# =========================================================================
# Tool and pipeline file existence
# =========================================================================

class TestToolExists:
    def test_apr_tool_file_exists(self):
        assert os.path.isfile(TOOL_PATH), f"{TOOL_PATH} does not exist"

    def test_apr_tool_is_executable(self):
        assert os.access(TOOL_PATH, os.X_OK), f"{TOOL_PATH} is not executable"

    def test_pipeline_file_exists(self):
        assert os.path.isfile(PIPELINE_PATH), f"{PIPELINE_PATH} does not exist"

    def test_pipeline_is_executable(self):
        assert os.access(PIPELINE_PATH, os.X_OK), f"{PIPELINE_PATH} is not executable"


# =========================================================================
# Toolchain: Makefile, schema.sql, APOR data
# =========================================================================

class TestToolchain:
    def test_makefile_exists(self):
        assert os.path.isfile(MAKEFILE_PATH), "Makefile not found at /app/Makefile"

    def test_makefile_has_compute_target(self):
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert re.search(r'^compute\s*:', content, re.MULTILINE), \
            "Makefile missing 'compute' target"

    def test_makefile_has_enrich_target(self):
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert re.search(r'^enrich\s*:', content, re.MULTILINE), \
            "Makefile missing 'enrich' target"

    def test_makefile_has_store_target(self):
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert re.search(r'^store\s*:', content, re.MULTILINE), \
            "Makefile missing 'store' target"

    def test_makefile_has_report_target(self):
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert re.search(r'^report\s*:', content, re.MULTILINE), \
            "Makefile missing 'report' target"

    def test_makefile_has_all_target(self):
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert re.search(r'^all\s*:', content, re.MULTILINE), \
            "Makefile missing 'all' target"

    def test_makefile_store_uses_sqlite3_cli(self):
        """Verify store target invokes sqlite3 CLI for schema loading."""
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert "sqlite3" in content, \
            "Makefile does not reference sqlite3 CLI"

    def test_schema_sql_exists(self):
        assert os.path.isfile(SCHEMA_PATH), "schema.sql not found at /app/schema.sql"

    def test_schema_sql_loadable_by_sqlite3_cli(self):
        """Verify schema.sql can be independently loaded by sqlite3 CLI."""
        with tempfile.NamedTemporaryFile(
            suffix=".db", delete=False, dir="/tmp"
        ) as tmp:
            tmp_path = tmp.name
        try:
            with open(SCHEMA_PATH) as schema_file:
                result = subprocess.run(
                    ["sqlite3", tmp_path],
                    stdin=schema_file,
                    capture_output=True, text=True, timeout=30,
                )
            assert result.returncode == 0, \
                f"schema.sql load via sqlite3 CLI failed: {result.stderr}"
            result2 = subprocess.run(
                ["sqlite3", tmp_path,
                 "SELECT name FROM sqlite_master "
                 "WHERE type='table' AND name='loan_results'"],
                capture_output=True, text=True, timeout=10,
            )
            assert "loan_results" in result2.stdout, \
                "loan_results table not created from schema.sql"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_schema_sql_has_check_constraints(self):
        """Verify schema defines CHECK constraints."""
        with open(SCHEMA_PATH) as f:
            content = f.read().upper()
        assert "CHECK" in content, "schema.sql missing CHECK constraints"

    def test_apor_data_exists(self):
        assert os.path.isfile(APOR_PATH), \
            "APOR data not found at /app/reference/apor_fixed.dat"

    def test_apor_data_has_rates(self):
        """Verify APOR fixed-width file contains parseable rate data."""
        found = 0
        with open(APOR_PATH) as f:
            for line in f:
                if re.match(r"\s+\d+\s+[\d.]+", line):
                    found += 1
        assert found >= 5, \
            f"APOR file has only {found} data rows, expected >= 5"


# =========================================================================
# APR Tool: computation accuracy
# =========================================================================

class TestAPRComputation:
    @pytest.fixture(params=list(GOLDEN.keys()))
    def loan_case(self, request):
        return request.param

    def _run_tool(self, loan_id):
        loan_file = os.path.join(LOANS_DIR, f"{loan_id}.json")
        assert os.path.isfile(loan_file), f"Loan file {loan_file} not found"
        result = subprocess.run(
            [TOOL_PATH, loan_file],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"Tool failed for {loan_id} (exit {result.returncode}):\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
        try:
            output = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            pytest.fail(
                f"Invalid JSON output for {loan_id}:\n{result.stdout[:500]}"
            )
        return output

    def test_output_has_required_fields(self, loan_case):
        output = self._run_tool(loan_case)
        for field in ["id", "computed_apr", "transaction_type", "tolerance_pct",
                       "disclosed_apr", "within_tolerance"]:
            assert field in output, (
                f"Missing field '{field}' in output for {loan_case}"
            )

    def test_id_matches(self, loan_case):
        output = self._run_tool(loan_case)
        assert output["id"] == loan_case, (
            f"ID mismatch: expected '{loan_case}', got '{output['id']}'"
        )

    def test_computed_apr(self, loan_case):
        output = self._run_tool(loan_case)
        golden = GOLDEN[loan_case]
        diff = abs(output["computed_apr"] - golden["computed_apr"])
        assert diff <= 0.015, (
            f"APR mismatch for {loan_case}: "
            f"expected {golden['computed_apr']}, got {output['computed_apr']} "
            f"(diff={diff:.4f}, max=0.015)"
        )

    def test_transaction_type(self, loan_case):
        output = self._run_tool(loan_case)
        golden = GOLDEN[loan_case]
        assert output["transaction_type"] == golden["transaction_type"], (
            f"Transaction type mismatch for {loan_case}: "
            f"expected '{golden['transaction_type']}', "
            f"got '{output['transaction_type']}'"
        )

    def test_tolerance_pct(self, loan_case):
        output = self._run_tool(loan_case)
        golden = GOLDEN[loan_case]
        assert abs(output["tolerance_pct"] - golden["tolerance_pct"]) < 0.001, (
            f"Tolerance pct mismatch for {loan_case}: "
            f"expected {golden['tolerance_pct']}, got {output['tolerance_pct']}"
        )

    def test_within_tolerance(self, loan_case):
        output = self._run_tool(loan_case)
        golden = GOLDEN[loan_case]
        assert output["within_tolerance"] == golden["within_tolerance"], (
            f"Tolerance check mismatch for {loan_case}: "
            f"expected {golden['within_tolerance']}, "
            f"got {output['within_tolerance']}"
        )


# =========================================================================
# APR Tool: dynamic loan (anti-cheat)
# =========================================================================

class TestDynamicLoan:
    """Verify tool handles unseen loans rather than hardcoding results."""

    def test_dynamic_loan_computation(self):
        loan = {
            "id": "dynamic_test_4f9a",
            "consummation_date": "2024-06-01",
            "advances": [{"date": "2024-06-01", "amount": 2000.00}],
            "payment_groups": [
                {"first_date": "2024-07-01", "amount": 174.00,
                 "count": 12, "period_months": 1}
            ],
            "disclosed_apr": None,
            "is_mortgage": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir="/tmp"
        ) as f:
            json.dump(loan, f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [TOOL_PATH, tmp_path],
                capture_output=True, text=True, timeout=120,
            )
            assert result.returncode == 0, (
                f"Tool failed on dynamic loan: {result.stderr[:500]}"
            )
            output = json.loads(result.stdout.strip())
            assert output["id"] == "dynamic_test_4f9a"
            # $2000, 12 monthly payments of $174 -> APR ~ 8.0%
            assert 7.0 <= output["computed_apr"] <= 10.0, (
                f"Dynamic APR {output['computed_apr']} outside expected [7.0, 10.0]"
            )
            assert output["transaction_type"] == "regular"
            assert output["within_tolerance"] is None
        finally:
            os.unlink(tmp_path)

    def test_dynamic_single_payment_loan(self):
        loan = {
            "id": "dynamic_single_7b2e",
            "consummation_date": "2025-03-01",
            "advances": [{"date": "2025-03-01", "amount": 3000.00}],
            "payment_groups": [
                {"first_date": "2025-09-01", "amount": 3180.00,
                 "count": 1, "period_months": 1}
            ],
            "disclosed_apr": None,
            "is_mortgage": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir="/tmp"
        ) as f:
            json.dump(loan, f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [TOOL_PATH, tmp_path],
                capture_output=True, text=True, timeout=120,
            )
            assert result.returncode == 0
            output = json.loads(result.stdout.strip())
            assert output["id"] == "dynamic_single_7b2e"
            # $3000 -> $3180 in 6 months: APR ~ 12.00%
            assert 11.5 <= output["computed_apr"] <= 12.5, (
                f"Dynamic single-payment APR {output['computed_apr']} "
                f"outside expected [11.5, 12.5]"
            )
            assert output["transaction_type"] == "regular"
        finally:
            os.unlink(tmp_path)


# =========================================================================
# Compliance Pipeline: execution and database
# =========================================================================

class TestPipelineExecution:
    def test_pipeline_exits_zero(self, pipeline_result):
        assert pipeline_result.returncode == 0, (
            f"Pipeline failed:\nstdout: {pipeline_result.stdout[:500]}\n"
            f"stderr: {pipeline_result.stderr[:500]}"
        )

    def test_database_file_exists(self, pipeline_result):
        assert os.path.isfile(DB_PATH), f"Database {DB_PATH} not created"

    def test_database_table_exists(self, pipeline_result):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='loan_results'"
        )
        assert cursor.fetchone() is not None, "Table 'loan_results' missing"
        conn.close()

    def test_database_has_required_columns(self, pipeline_result):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("PRAGMA table_info(loan_results)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "id", "computed_apr", "transaction_type", "tolerance_pct",
            "disclosed_apr", "within_tolerance", "term_years", "apor_rate",
            "rate_spread", "high_cost",
        }
        assert expected.issubset(columns), (
            f"Missing columns: {expected - columns}"
        )
        conn.close()

    def test_database_row_count(self, pipeline_result):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM loan_results"
        ).fetchone()[0]
        conn.close()
        assert count == 5, f"Expected 5 rows, got {count}"


# =========================================================================
# Pipeline: intermediate NDJSON files
# =========================================================================

class TestIntermediateFiles:
    def test_build_directory_exists(self, pipeline_result):
        assert os.path.isdir(BUILD_DIR), "/app/build directory not created"

    def test_apr_results_ndjson_exists(self, pipeline_result):
        path = os.path.join(BUILD_DIR, "apr_results.ndjson")
        assert os.path.isfile(path), f"{path} not created by compute target"

    def test_apr_results_ndjson_valid(self, pipeline_result):
        """Verify each line is valid JSON with required APR fields."""
        path = os.path.join(BUILD_DIR, "apr_results.ndjson")
        count = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    assert "id" in obj, "NDJSON line missing 'id'"
                    assert "computed_apr" in obj, "NDJSON line missing 'computed_apr'"
                    assert "transaction_type" in obj
                    count += 1
        assert count == 5, f"Expected 5 NDJSON lines, got {count}"

    def test_enriched_ndjson_exists(self, pipeline_result):
        path = os.path.join(BUILD_DIR, "enriched.ndjson")
        assert os.path.isfile(path), f"{path} not created by enrich target"

    def test_enriched_ndjson_has_apor_fields(self, pipeline_result):
        """Verify enriched data includes APOR-derived fields."""
        path = os.path.join(BUILD_DIR, "enriched.ndjson")
        count = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    assert "term_years" in obj, "Enriched line missing 'term_years'"
                    assert "apor_rate" in obj, "Enriched line missing 'apor_rate'"
                    assert "rate_spread" in obj, "Enriched line missing 'rate_spread'"
                    assert "high_cost" in obj, "Enriched line missing 'high_cost'"
                    count += 1
        assert count == 5, f"Expected 5 enriched lines, got {count}"

    def test_summary_json_file_exists(self, pipeline_result):
        path = os.path.join(BUILD_DIR, "summary.json")
        assert os.path.isfile(path), f"{path} not created by report target"


# =========================================================================
# Compliance Pipeline: per-loan database verification
# =========================================================================

class TestDatabaseContents:
    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_computed_apr(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT computed_apr FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        expected = GOLDEN[loan_id]["computed_apr"]
        assert abs(row[0] - expected) <= 0.015, (
            f"DB computed_apr for {loan_id}: expected ~{expected}, got {row[0]}"
        )

    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_term_years(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT term_years FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        assert row[0] == GOLDEN_DB[loan_id]["term_years"], (
            f"term_years for {loan_id}: "
            f"expected {GOLDEN_DB[loan_id]['term_years']}, got {row[0]}"
        )

    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_apor_rate(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT apor_rate FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        assert abs(row[0] - GOLDEN_DB[loan_id]["apor_rate"]) < 0.01, (
            f"apor_rate for {loan_id}: "
            f"expected {GOLDEN_DB[loan_id]['apor_rate']}, got {row[0]}"
        )

    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_rate_spread(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT rate_spread FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        assert abs(row[0] - GOLDEN_DB[loan_id]["rate_spread"]) < 0.05, (
            f"rate_spread for {loan_id}: "
            f"expected {GOLDEN_DB[loan_id]['rate_spread']}, got {row[0]}"
        )

    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_high_cost(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT high_cost FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        assert row[0] == GOLDEN_DB[loan_id]["high_cost"], (
            f"high_cost for {loan_id}: "
            f"expected {GOLDEN_DB[loan_id]['high_cost']}, got {row[0]}"
        )

    @pytest.mark.parametrize("loan_id", list(GOLDEN_DB.keys()))
    def test_db_within_tolerance(self, pipeline_result, loan_id):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT within_tolerance FROM loan_results WHERE id=?", (loan_id,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Loan {loan_id} not in database"
        assert row[0] == GOLDEN_DB[loan_id]["within_tolerance"], (
            f"within_tolerance for {loan_id}: "
            f"expected {GOLDEN_DB[loan_id]['within_tolerance']}, got {row[0]}"
        )


# =========================================================================
# Compliance Pipeline: database constraints
# =========================================================================

class TestDatabaseConstraints:
    def test_transaction_type_check_constraint(self, pipeline_result):
        """Verify CHECK constraint rejects invalid transaction_type."""
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO loan_results VALUES "
                "(?,?,?,?,?,?,?,?,?,?)",
                ("_chk1", 5.0, "INVALID_TYPE", 0.125,
                 None, None, 1, 4.5, 0.5, 0),
            )
        conn.close()

    def test_high_cost_check_constraint(self, pipeline_result):
        """Verify CHECK constraint rejects invalid high_cost values."""
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO loan_results VALUES "
                "(?,?,?,?,?,?,?,?,?,?)",
                ("_chk2", 5.0, "regular", 0.125,
                 None, None, 1, 4.5, 0.5, 99),
            )
        conn.close()

    def test_primary_key_constraint(self, pipeline_result):
        """Verify PRIMARY KEY constraint on id column."""
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO loan_results VALUES "
                "(?,?,?,?,?,?,?,?,?,?)",
                ("regular_monthly", 5.0, "regular", 0.125,
                 None, None, 1, 4.5, 0.5, 0),
            )
        conn.close()


# =========================================================================
# Compliance Pipeline: summary output
# =========================================================================

class TestPipelineSummary:
    def test_summary_is_valid_json(self, pipeline_result):
        try:
            json.loads(pipeline_result.stdout.strip())
        except json.JSONDecodeError:
            pytest.fail(
                f"Pipeline stdout not valid JSON:\n"
                f"{pipeline_result.stdout[:500]}"
            )

    def test_summary_has_required_fields(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        for field in ["total_loans", "regular_count", "irregular_count",
                       "high_cost_count", "tolerance_failures",
                       "avg_rate_spread"]:
            assert field in summary, f"Missing summary field '{field}'"

    def test_summary_total_loans(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert summary["total_loans"] == 5

    def test_summary_regular_count(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert summary["regular_count"] == 3

    def test_summary_irregular_count(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert summary["irregular_count"] == 2

    def test_summary_high_cost_count(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert summary["high_cost_count"] == 3

    def test_summary_tolerance_failures(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert summary["tolerance_failures"] == ["regular_monthly"], (
            f"Expected ['regular_monthly'], got {summary['tolerance_failures']}"
        )

    def test_summary_avg_rate_spread(self, pipeline_result):
        summary = json.loads(pipeline_result.stdout.strip())
        assert abs(summary["avg_rate_spread"] - 11.30) < 0.15, (
            f"avg_rate_spread: expected ~11.30, got {summary['avg_rate_spread']}"
        )


# =========================================================================
# Cross-validation: DB contents match summary
# =========================================================================

class TestCrossValidation:
    """Verify database and summary are internally consistent."""

    def test_db_regular_count_matches_summary(self, pipeline_result):
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        db_count = conn.execute(
            "SELECT COUNT(*) FROM loan_results "
            "WHERE transaction_type='regular'"
        ).fetchone()[0]
        conn.close()
        summary = json.loads(pipeline_result.stdout.strip())
        assert db_count == summary["regular_count"], (
            f"DB regular count {db_count} != summary {summary['regular_count']}"
        )

    def test_db_high_cost_count_matches_summary(self, pipeline_result):
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        db_count = conn.execute(
            "SELECT COUNT(*) FROM loan_results WHERE high_cost=1"
        ).fetchone()[0]
        conn.close()
        summary = json.loads(pipeline_result.stdout.strip())
        assert db_count == summary["high_cost_count"], (
            f"DB high_cost count {db_count} != summary {summary['high_cost_count']}"
        )

    def test_db_tolerance_failures_match_summary(self, pipeline_result):
        if not os.path.isfile(DB_PATH):
            pytest.skip("Database not created")
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT id FROM loan_results WHERE within_tolerance=0 ORDER BY id"
        ).fetchall()
        conn.close()
        db_failures = [r[0] for r in rows]
        summary = json.loads(pipeline_result.stdout.strip())
        assert db_failures == summary["tolerance_failures"], (
            f"DB failures {db_failures} != summary {summary['tolerance_failures']}"
        )
