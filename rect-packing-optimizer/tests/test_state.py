"""

Verification tests for the Rectangle Ad Placement solver.
Checks that:
1. The solver is a compiled ELF binary (not a script)
2. The full evaluation pipeline produces valid JSON
3. Results are stored in the SQLite database
4. Average score meets the 400M threshold
"""
import json
import os
import sqlite3
import subprocess
import pytest

SOLVER = "/app/solver"
DB_PATH = "/app/results.db"
EVALUATE_SH = "/app/evaluate.sh"
SCORE_THRESHOLD = 400_000_000


class TestSolverBinary:
    """Verify the solver is a compiled C++ binary."""

    def test_solver_exists(self):
        assert os.path.exists(SOLVER), f"Solver binary not found at {SOLVER}"

    def test_solver_is_elf(self):
        """The solver must be a compiled ELF binary, not a script."""
        with open(SOLVER, "rb") as f:
            magic = f.read(4)
        assert magic == b"\x7fELF", (
            f"Solver at {SOLVER} is not a compiled ELF binary (got magic "
            f"{magic!r}). The solver must be compiled C++."
        )

    def test_solver_executable(self):
        assert os.access(SOLVER, os.X_OK), f"{SOLVER} is not executable"


class TestEvaluationPipeline:
    """Run evaluate.sh and verify JSON output and SQLite storage."""

    _eval_json = None
    _eval_output = ""

    @pytest.fixture(scope="class", autouse=True)
    def run_evaluation(self):
        """Run the full evaluation pipeline."""
        result = subprocess.run(
            ["bash", EVALUATE_SH],
            capture_output=True,
            text=True,
            timeout=600,
        )
        TestEvaluationPipeline._eval_output = result.stdout.strip()
        try:
            TestEvaluationPipeline._eval_json = json.loads(
                result.stdout.strip()
            )
        except (json.JSONDecodeError, ValueError):
            TestEvaluationPipeline._eval_json = None

    def test_json_output_valid(self):
        assert TestEvaluationPipeline._eval_json is not None, (
            f"evaluate.sh did not produce valid JSON. "
            f"Output: {TestEvaluationPipeline._eval_output[:500]}"
        )

    def test_json_has_cases(self):
        data = TestEvaluationPipeline._eval_json
        assert data is not None, "No JSON output"
        cases = data.get("cases", [])
        assert len(cases) == 5, f"Expected 5 cases in JSON, got {len(cases)}"

    def test_json_all_cases_ok(self):
        data = TestEvaluationPipeline._eval_json
        assert data is not None, "No JSON output"
        for c in data.get("cases", []):
            assert c["status"] == "OK", (
                f"Case {c['case']} failed with status: {c['status']}"
            )

    def test_json_summary_present(self):
        data = TestEvaluationPipeline._eval_json
        assert data is not None, "No JSON output"
        summary = data.get("summary", {})
        assert "avg_score" in summary, "JSON summary missing avg_score"
        assert "valid_cases" in summary, "JSON summary missing valid_cases"


class TestSQLiteResults:
    """Verify results are correctly stored in the SQLite database."""

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), (
            f"Results database not found at {DB_PATH}"
        )

    def test_results_table_populated(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM results")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 5, f"Expected 5 rows in results table, got {count}"

    def test_all_results_ok(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT case_name, status FROM results WHERE status != 'OK'"
        )
        failures = cursor.fetchall()
        conn.close()
        assert len(failures) == 0, (
            f"Failed cases in database: {failures}"
        )

    def test_summary_view_works(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT * FROM summary")
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "summary view returned no rows"
        num_cases, avg_score, min_score, max_score, valid_cases = row
        assert num_cases == 5
        assert valid_cases == 5


class TestScoreThreshold:
    """Verify the average score meets the 400M threshold."""

    def test_average_score(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT AVG(score) FROM results WHERE status = 'OK'"
        )
        avg = cursor.fetchone()[0]
        conn.close()
        assert avg is not None, "No valid scores in database"

        # Get per-case detail for error message
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT case_name, score FROM results ORDER BY case_name"
        )
        details = cursor.fetchall()
        conn.close()

        detail_str = ", ".join(
            f"{name}={score:,}" for name, score in details
        )
        assert avg >= SCORE_THRESHOLD, (
            f"Average score {avg:,.0f} < threshold {SCORE_THRESHOLD:,}. "
            f"Per-case: [{detail_str}]"
        )
