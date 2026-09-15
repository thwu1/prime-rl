
import json
import os
import re
import shutil
import subprocess
import psycopg2
import pytest


# ── Ground-truth expected results (hardcoded, not read from any env file) ──

EXPECTED = {
    "alias_shadow": [
        (0,), (-1,), (-2,), (-3,),
    ],
    "quoted_alias_silent": [
        ("Valve", -45), ("Pipe", -30), ("Wrench", -25), ("Hammer", -18),
        ("Switch", -15), ("Wire", -10), ("Bolt", -2), ("Nail", -1),
    ],
    "group_order_clash": [
        (0, 2), (1, 3), (2, 1), (3, 1), (4, 1),
    ],
    "window_alias": [
        ("Switch", "electrical", -15, 1),
        ("Wire", "electrical", -10, 2),
        ("Bolt", "fasteners", -2, 1),
        ("Nail", "fasteners", -1, 2),
        ("Valve", "plumbing", -45, 1),
        ("Pipe", "plumbing", -30, 2),
        ("Wrench", "tools", -25, 1),
        ("Hammer", "tools", -18, 2),
    ],
    "collate_trap": [
        ("Bolt",), ("Hammer",), ("Nail",), ("Pipe",),
        ("Switch",), ("Valve",), ("Wire",), ("Wrench",),
    ],
    "unary_plus": [
        (-3,), (-2,), (-1,), (0,),
    ],
    "union_expression": [
        ("Wrench", 25), ("Hammer", 18), ("Bolt", 2), ("Nail", 1),
    ],
    "cast_scope": [
        ("Nail", 1), ("Bolt", 2), ("Wire", 10), ("Switch", 15),
        ("Hammer", 18), ("Wrench", 25), ("Pipe", 30), ("Valve", 45),
    ],
    "aggregate_window": [
        ("electrical", 25, 3), ("fasteners", 3, 4),
        ("plumbing", 75, 1), ("tools", 43, 2),
    ],
    "distinct_on_order": [
        ("Wire", "electrical", 10), ("Nail", "fasteners", 1),
        ("Pipe", "plumbing", 30), ("Hammer", "tools", 18),
    ],
}

REQUIRED_TABLE = {
    "alias_shadow": "nums",
    "quoted_alias_silent": "inventory",
    "group_order_clash": "inventory",
    "window_alias": "inventory",
    "collate_trap": "inventory",
    "unary_plus": "nums",
    "union_expression": "inventory",
    "cast_scope": "inventory",
    "aggregate_window": "inventory",
    "distinct_on_order": "inventory",
}

EXPECTED_BUG_TYPES = {
    "alias_shadow": "alias_resolution",
    "quoted_alias_silent": "identifier_mismatch",
    "group_order_clash": "scope_restriction",
    "window_alias": "scope_restriction",
    "collate_trap": "expression_promotion",
    "unary_plus": "expression_promotion",
    "union_expression": "scope_restriction",
    "cast_scope": "expression_promotion",
    "aggregate_window": "scope_restriction",
    "distinct_on_order": "ordering_constraint",
}

EXPECTED_FAILURE_MODES = {
    "alias_shadow": "wrong_results",
    "quoted_alias_silent": "wrong_results",
    "group_order_clash": "wrong_results",
    "window_alias": "error",
    "collate_trap": "error",
    "unary_plus": "wrong_results",
    "union_expression": "error",
    "cast_scope": "error",
    "aggregate_window": "error",
    "distinct_on_order": "error",
}

EXPECTED_RISK_LEVELS = {
    "alias_shadow": "high",
    "quoted_alias_silent": "high",
    "group_order_clash": "high",
    "window_alias": "low",
    "collate_trap": "low",
    "unary_plus": "high",
    "union_expression": "low",
    "cast_scope": "low",
    "aggregate_window": "low",
    "distinct_on_order": "low",
}

ALL_QUERY_NAMES = list(EXPECTED.keys())


# ── Helpers ──

def parse_queries(filepath):
    """Parse -- @name: tagged queries from a SQL file."""
    with open(filepath) as f:
        content = f.read()

    pattern = r"-- @name:\s*(\S+)\s*\n"
    parts = re.split(pattern, content)
    queries = {}
    for i in range(1, len(parts), 2):
        name = parts[i]
        block = parts[i + 1]
        sql_lines = []
        for line in block.strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("--") or stripped == "":
                continue
            sql_lines.append(line)
        sql = "\n".join(sql_lines).strip().rstrip(";")
        queries[name] = sql
    return queries


# ── Fixtures ──

@pytest.fixture(scope="session")
def tool_result():
    """Run query_doctor.py from scratch and capture the result."""
    # Remove any existing output files so we verify the tool generates them
    for path in ["/app/queries_fixed.sql", "/app/audit_report.json"]:
        if os.path.exists(path):
            os.unlink(path)

    # Restore original broken queries
    shutil.copy("/app/.queries_original.sql", "/app/queries.sql")

    result = subprocess.run(
        ["python3", "/app/query_doctor.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


@pytest.fixture(scope="session")
def db_conn():
    conn = psycopg2.connect(dbname="analytics", user="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def fixed_queries(tool_result):
    assert os.path.isfile("/app/queries_fixed.sql"), (
        "query_doctor.py did not produce /app/queries_fixed.sql"
    )
    return parse_queries("/app/queries_fixed.sql")


@pytest.fixture(scope="session")
def audit_report(tool_result):
    assert os.path.isfile("/app/audit_report.json"), (
        "query_doctor.py did not produce /app/audit_report.json"
    )
    with open("/app/audit_report.json") as f:
        return json.load(f)


# ── Test: tool runs successfully ──

class TestToolExecution:
    def test_query_doctor_exists(self):
        assert os.path.isfile("/app/query_doctor.py"), (
            "/app/query_doctor.py not found"
        )

    def test_query_doctor_is_valid_python(self):
        result = subprocess.run(
            ["python3", "-m", "py_compile", "/app/query_doctor.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"query_doctor.py has syntax errors: {result.stderr}"
        )

    def test_query_doctor_exits_zero(self, tool_result):
        assert tool_result.returncode == 0, (
            f"query_doctor.py exited with code {tool_result.returncode}.\n"
            f"stdout: {tool_result.stdout}\n"
            f"stderr: {tool_result.stderr}"
        )

    def test_produces_fixed_sql(self, tool_result):
        assert os.path.isfile("/app/queries_fixed.sql")

    def test_produces_audit_report(self, tool_result):
        assert os.path.isfile("/app/audit_report.json")

    def test_tool_has_substance(self):
        """Verify the tool is not trivially short (e.g. just echo/cat)."""
        with open("/app/query_doctor.py") as f:
            lines = [l for l in f.readlines() if l.strip() and not l.strip().startswith("#")]
        assert len(lines) >= 40, (
            f"query_doctor.py has only {len(lines)} non-empty non-comment lines; "
            "expected a substantial implementation"
        )


# ── Test: fixed queries produce correct results ──

class TestFixedQueries:
    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_query_exists(self, fixed_queries, query_name):
        assert query_name in fixed_queries, (
            f"Query '{query_name}' not found in /app/queries_fixed.sql"
        )

    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_query_uses_original_table(self, fixed_queries, query_name):
        sql = fixed_queries[query_name].lower()
        table = REQUIRED_TABLE[query_name]
        assert table in sql, (
            f"Query '{query_name}' must reference table '{table}'"
        )

    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_query_output(self, db_conn, fixed_queries, query_name):
        sql = fixed_queries[query_name]
        cur = db_conn.cursor()
        try:
            cur.execute(sql)
            rows = cur.fetchall()
        except Exception as e:
            pytest.fail(f"Query '{query_name}' raised error: {e}")
        finally:
            cur.close()

        actual = [tuple(int(v) if isinstance(v, (int,)) else v for v in row) for row in rows]
        expected = [tuple(r) for r in EXPECTED[query_name]]

        assert len(actual) == len(expected), (
            f"Query '{query_name}': expected {len(expected)} rows, got {len(actual)}"
        )
        assert actual == expected, (
            f"Query '{query_name}' produced wrong results.\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


# ── Test: audit report structure and content ──

class TestAuditReportStructure:
    def test_has_queries_key(self, audit_report):
        assert "queries" in audit_report

    def test_has_summary_key(self, audit_report):
        assert "summary" in audit_report

    def test_all_queries_present(self, audit_report):
        for name in ALL_QUERY_NAMES:
            assert name in audit_report["queries"], (
                f"Query '{name}' missing from audit report"
            )

    def test_query_entry_fields(self, audit_report):
        required_fields = {"status", "bug_type", "failure_mode", "risk_level", "fix_description"}
        for name in ALL_QUERY_NAMES:
            entry = audit_report["queries"][name]
            missing = required_fields - set(entry.keys())
            assert not missing, (
                f"Query '{name}' missing fields: {missing}"
            )

    def test_all_status_fixed(self, audit_report):
        for name in ALL_QUERY_NAMES:
            assert audit_report["queries"][name]["status"] == "fixed", (
                f"Query '{name}' status should be 'fixed'"
            )

    def test_summary_total(self, audit_report):
        assert audit_report["summary"]["total_queries"] == 10

    def test_summary_bugs_found(self, audit_report):
        assert audit_report["summary"]["bugs_found"] == 10

    def test_summary_has_by_type(self, audit_report):
        assert "by_type" in audit_report["summary"]

    def test_summary_has_by_failure_mode(self, audit_report):
        assert "by_failure_mode" in audit_report["summary"]

    def test_summary_has_high_risk_count(self, audit_report):
        assert "high_risk_count" in audit_report["summary"]


class TestAuditReportClassifications:
    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_bug_type(self, audit_report, query_name):
        actual = audit_report["queries"][query_name]["bug_type"]
        expected = EXPECTED_BUG_TYPES[query_name]
        assert actual == expected, (
            f"Query '{query_name}': expected bug_type '{expected}', got '{actual}'"
        )

    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_failure_mode(self, audit_report, query_name):
        actual = audit_report["queries"][query_name]["failure_mode"]
        expected = EXPECTED_FAILURE_MODES[query_name]
        assert actual == expected, (
            f"Query '{query_name}': expected failure_mode '{expected}', got '{actual}'"
        )

    @pytest.mark.parametrize("query_name", ALL_QUERY_NAMES)
    def test_risk_level(self, audit_report, query_name):
        actual = audit_report["queries"][query_name]["risk_level"]
        expected = EXPECTED_RISK_LEVELS[query_name]
        assert actual == expected, (
            f"Query '{query_name}': expected risk_level '{expected}', got '{actual}'"
        )


class TestAuditReportSummary:
    def test_by_type_counts(self, audit_report):
        by_type = audit_report["summary"]["by_type"]
        expected_counts = {}
        for bt in EXPECTED_BUG_TYPES.values():
            expected_counts[bt] = expected_counts.get(bt, 0) + 1
        for bt, count in expected_counts.items():
            assert by_type.get(bt) == count, (
                f"by_type['{bt}']: expected {count}, got {by_type.get(bt)}"
            )

    def test_by_failure_mode_counts(self, audit_report):
        by_fm = audit_report["summary"]["by_failure_mode"]
        expected_error = sum(1 for v in EXPECTED_FAILURE_MODES.values() if v == "error")
        expected_wrong = sum(1 for v in EXPECTED_FAILURE_MODES.values() if v == "wrong_results")
        assert by_fm.get("error") == expected_error, (
            f"by_failure_mode['error']: expected {expected_error}, got {by_fm.get('error')}"
        )
        assert by_fm.get("wrong_results") == expected_wrong, (
            f"by_failure_mode['wrong_results']: expected {expected_wrong}, got {by_fm.get('wrong_results')}"
        )

    def test_high_risk_count(self, audit_report):
        expected_high = sum(1 for v in EXPECTED_RISK_LEVELS.values() if v == "high")
        assert audit_report["summary"]["high_risk_count"] == expected_high, (
            f"high_risk_count: expected {expected_high}, got {audit_report['summary']['high_risk_count']}"
        )
