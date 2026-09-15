import duckdb
import pytest
import os
import json
from decimal import Decimal


WAREHOUSE_DB = "/app/warehouse.duckdb"
NUM_REPORTS = 5
BROKEN_REPORTS = {2, 4, 5}
CORRECT_REPORTS = {1, 3}

# Reference queries against canonical TPC-H tables.
# These produce the ground-truth results that each corrected report must match.
REFERENCE_QUERIES = {
    1: """
SELECT l_returnflag AS return_flag, l_linestatus AS line_status,
       SUM(l_quantity) AS total_qty,
       SUM(l_extendedprice) AS total_base_price,
       SUM(l_extendedprice * (1 - l_discount)) AS total_disc_price,
       SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS total_charge,
       AVG(l_quantity) AS avg_qty,
       AVG(l_extendedprice) AS avg_price,
       AVG(l_discount) AS avg_disc,
       COUNT(*) AS count_lines
FROM lineitem
WHERE l_shipdate <= DATE '1998-09-02'
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
""",
    2: """
SELECT r.r_name AS region_name,
       SUM(o.o_totalprice) AS total_revenue,
       COUNT(*) AS num_orders
FROM orders o
JOIN customer c ON o.o_custkey = c.c_custkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
WHERE EXTRACT(YEAR FROM o.o_orderdate) = 1995
GROUP BY r.r_name
ORDER BY total_revenue DESC
""",
    3: """
SELECT n.n_name AS nation_name,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
JOIN supplier s ON l.l_suppkey = s.s_suppkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
WHERE c.c_nationkey = s.s_nationkey
  AND r.r_name = 'ASIA'
  AND o.o_orderdate >= DATE '1994-01-01'
  AND o.o_orderdate < DATE '1995-01-01'
GROUP BY n.n_name
ORDER BY revenue DESC
""",
    4: """
SELECT n.n_name AS nation,
       EXTRACT(YEAR FROM o.o_orderdate)::INTEGER AS o_year,
       SUM(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity) AS total_profit
FROM part p
JOIN lineitem l ON p.p_partkey = l.l_partkey
JOIN supplier s ON l.l_suppkey = s.s_suppkey
JOIN partsupp ps ON l.l_suppkey = ps.ps_suppkey AND l.l_partkey = ps.ps_partkey
JOIN orders o ON l.l_orderkey = o.o_orderkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
WHERE p.p_name LIKE '%green%'
GROUP BY n.n_name, EXTRACT(YEAR FROM o.o_orderdate)
ORDER BY n.n_name, o_year DESC
""",
    5: """
SELECT EXTRACT(YEAR FROM o.o_orderdate)::INTEGER AS year,
       EXTRACT(QUARTER FROM o.o_orderdate)::INTEGER AS quarter,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS quarterly_revenue,
       COUNT(DISTINCT o.o_orderkey) AS num_orders
FROM lineitem l
JOIN orders o ON l.l_orderkey = o.o_orderkey
GROUP BY EXTRACT(YEAR FROM o.o_orderdate), EXTRACT(QUARTER FROM o.o_orderdate)
ORDER BY year, quarter
""",
}


def get_reference_results():
    """Generate fresh TPC-H SF=0.1 data and run reference queries."""
    con = duckdb.connect()
    con.execute("INSTALL tpch")
    con.execute("LOAD tpch")
    con.execute("CALL dbgen(sf=0.1)")

    results = {}
    for rid, sql in REFERENCE_QUERIES.items():
        results[rid] = con.execute(sql).fetchall()

    con.close()
    return results


def normalize_value(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, int):
        return float(v)
    if isinstance(v, float):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def values_equal(a, b, rtol=1e-4):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) and isinstance(b, float):
        if a == 0.0 and b == 0.0:
            return True
        if a == 0.0 or b == 0.0:
            return abs(a - b) < 1e-6
        return abs(a - b) / max(abs(a), abs(b)) < rtol
    return str(a) == str(b)


def compare_results(expected, actual, report_id):
    assert len(actual) == len(expected), (
        f"Report {report_id}: Row count mismatch. Expected {len(expected)}, got {len(actual)}"
    )
    for i, (exp_row, act_row) in enumerate(zip(expected, actual)):
        assert len(act_row) == len(exp_row), (
            f"Report {report_id}, row {i}: Column count mismatch. "
            f"Expected {len(exp_row)}, got {len(act_row)}"
        )
        for j, (exp_val, act_val) in enumerate(zip(exp_row, act_row)):
            exp_norm = normalize_value(exp_val)
            act_norm = normalize_value(act_val)
            assert values_equal(exp_norm, act_norm), (
                f"Report {report_id}, row {i}, col {j}: "
                f"Expected {exp_norm!r}, got {act_norm!r}"
            )


@pytest.fixture(scope="session")
def reference():
    """Generate reference results once per test session."""
    return get_reference_results()


@pytest.fixture(scope="session")
def warehouse_after_fix():
    """Apply fix.sql to the warehouse, then drop staging tables.

    Dropping staging tables forces corrected reports to query the
    analytical model (fact/dim tables) rather than bypassing it.
    """
    fix_path = "/app/fix.sql"
    assert os.path.exists(fix_path), "Missing /app/fix.sql"

    with open(fix_path) as f:
        fix_sql = f.read().strip()

    con = duckdb.connect(WAREHOUSE_DB)

    # Execute fix.sql statement by statement
    for stmt in fix_sql.split(';'):
        stmt = stmt.strip()
        # Skip fragments that are empty or contain only comments
        sql_lines = [l for l in stmt.split('\n')
                     if l.strip() and not l.strip().startswith('--')]
        if sql_lines:
            con.execute(stmt)

    # Drop staging tables so corrected reports cannot bypass the star schema
    for table in ['stg_lineitem', 'stg_orders', 'stg_customer', 'stg_supplier',
                  'stg_part', 'stg_partsupp', 'stg_nation', 'stg_region']:
        con.execute(f"DROP TABLE IF EXISTS {table}")

    con.close()
    return WAREHOUSE_DB


# ── Diagnosis tests ──────────────────────────────────────────

class TestDiagnosis:
    def test_file_exists(self):
        assert os.path.exists("/app/diagnosis.json"), "Missing /app/diagnosis.json"

    def test_identifies_broken_reports(self):
        with open("/app/diagnosis.json") as f:
            diag = json.load(f)
        for rid in BROKEN_REPORTS:
            key = f"report_{rid}"
            assert key in diag, f"Diagnosis missing {key}"
            status = diag[key].get("status", "").lower()
            assert status == "incorrect", (
                f"Report {rid} should be diagnosed as 'incorrect', got '{status}'"
            )

    def test_identifies_correct_reports(self):
        with open("/app/diagnosis.json") as f:
            diag = json.load(f)
        for rid in CORRECT_REPORTS:
            key = f"report_{rid}"
            assert key in diag, f"Diagnosis missing {key}"
            status = diag[key].get("status", "").lower()
            assert status == "correct", (
                f"Report {rid} should be diagnosed as 'correct', got '{status}'"
            )

    def test_has_explanations(self):
        with open("/app/diagnosis.json") as f:
            diag = json.load(f)
        for rid in range(1, NUM_REPORTS + 1):
            key = f"report_{rid}"
            assert key in diag, f"Diagnosis missing {key}"
            assert "explanation" in diag[key], f"Missing explanation for {key}"
            assert len(diag[key]["explanation"]) > 20, (
                f"Explanation for {key} is too short to be meaningful"
            )


# ── Fix SQL tests ────────────────────────────────────────────

class TestFixSQL:
    def test_fix_file_exists(self):
        assert os.path.exists("/app/fix.sql"), "Missing /app/fix.sql"
        with open("/app/fix.sql") as f:
            content = f.read().strip()
        assert len(content) > 20, "fix.sql appears empty or trivial"


# ── Corrected report tests ───────────────────────────────────

class TestCorrectedReports:
    @pytest.mark.parametrize("report_id", range(1, NUM_REPORTS + 1))
    def test_file_exists(self, report_id):
        path = f"/app/corrected_reports/report_{report_id}.sql"
        assert os.path.exists(path), f"Missing corrected report: {path}"
        with open(path) as f:
            content = f.read().strip()
        assert len(content) > 10, f"Report {path} appears empty"

    @pytest.mark.parametrize("report_id", range(1, NUM_REPORTS + 1))
    def test_no_staging_tables(self, report_id):
        """Corrected reports must query the analytical model, not staging."""
        path = f"/app/corrected_reports/report_{report_id}.sql"
        with open(path) as f:
            sql = f.read().lower()
        assert "stg_" not in sql, (
            f"Report {report_id} directly references staging tables (stg_*). "
            f"Reports must query the analytical model, not the raw staging layer."
        )

    @pytest.mark.parametrize("report_id", range(1, NUM_REPORTS + 1))
    def test_results_match_reference(self, reference, warehouse_after_fix, report_id):
        """Each corrected report must produce results matching the reference."""
        expected = reference[report_id]

        path = f"/app/corrected_reports/report_{report_id}.sql"
        with open(path) as f:
            sql = f.read().strip()

        con = duckdb.connect(warehouse_after_fix, read_only=True)
        try:
            actual = con.execute(sql).fetchall()
        except Exception as e:
            pytest.fail(f"Report {report_id} failed to execute after fix: {e}")
        finally:
            con.close()

        compare_results(expected, actual, report_id)
