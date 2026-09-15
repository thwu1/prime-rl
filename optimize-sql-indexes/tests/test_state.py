"""
PostgreSQL index optimization verification tests.
Validates migration, query plans, result correctness, and index budget.
"""

import subprocess
import json
import os
import re
import pytest

DB_NAME = "benchdb"
DB_USER = "bench"


def run_sql(sql, db=DB_NAME, user=DB_USER):
    """Execute SQL via psql and return (stdout, returncode)."""
    result = subprocess.run(
        ["psql", "-U", user, "-d", db, "-t", "-A", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip(), result.returncode


def run_sql_file(filepath, db=DB_NAME, user=DB_USER):
    """Execute SQL file via psql and return (stdout, returncode, stderr)."""
    result = subprocess.run(
        ["psql", "-U", user, "-d", db, "-f", filepath],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip(), result.returncode, result.stderr


def get_explain_json(sql, db=DB_NAME, user=DB_USER):
    """Run EXPLAIN (FORMAT JSON) and return parsed plan."""
    result = subprocess.run(
        ["psql", "-U", user, "-d", db, "-t", "-A", "-c",
         f"EXPLAIN (FORMAT JSON) {sql}"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def has_seq_scan_on(plan, table_name):
    """Recursively check if EXPLAIN plan contains a Seq Scan on the given table."""
    if isinstance(plan, dict):
        if (plan.get("Node Type") == "Seq Scan"
                and plan.get("Relation Name") == table_name):
            return True
        for v in plan.values():
            if has_seq_scan_on(v, table_name):
                return True
    elif isinstance(plan, list):
        for item in plan:
            if has_seq_scan_on(item, table_name):
                return True
    return False


def find_node_types(plan):
    """Recursively collect all Node Type values from an EXPLAIN plan."""
    types = []
    if isinstance(plan, dict):
        if "Node Type" in plan:
            types.append(plan["Node Type"])
        for v in plan.values():
            types.extend(find_node_types(v))
    elif isinstance(plan, list):
        for item in plan:
            types.extend(find_node_types(item))
    return types


def read_optimized_query(n):
    """Read and return the content of /app/optimized/q{n}.sql, stripped."""
    path = f"/app/optimized/q{n}.sql"
    with open(path) as f:
        return f.read()


def strip_sql(sql_text):
    """Remove comments, strip, and remove trailing semicolons for EXPLAIN."""
    lines = []
    for line in sql_text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("--"):
            lines.append(line)
    return "\n".join(lines).strip().rstrip(";")


def compare_result_rows(orig_result, opt_result):
    """Compare query result rows as sets, ignoring non-deterministic tie ordering."""
    orig_rows = sorted(orig_result.split("\n")) if orig_result else []
    opt_rows = sorted(opt_result.split("\n")) if opt_result else []
    return orig_rows == opt_rows


# ============================================================
# Session-scoped fixture: apply migration once before all tests
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def apply_migration():
    """Apply migration.sql and VACUUM ANALYZE before running tests."""
    migration_path = "/app/migration.sql"
    if os.path.exists(migration_path):
        result = subprocess.run(
            ["psql", "-U", DB_USER, "-d", DB_NAME, "-f", migration_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"Migration stderr: {result.stderr}")
    # VACUUM ANALYZE to enable Index Only Scans (set visibility map bits)
    subprocess.run(
        ["psql", "-U", DB_USER, "-d", DB_NAME, "-c", "VACUUM ANALYZE;"],
        capture_output=True, text=True, timeout=300
    )


# ============================================================
# Migration tests
# ============================================================

class TestMigration:
    def test_migration_exists(self):
        assert os.path.exists("/app/migration.sql"), \
            "migration.sql must exist at /app/migration.sql"

    def test_migration_contains_ddl(self):
        with open("/app/migration.sql") as f:
            content = f.read().lower()
        assert "create index" in content or "drop index" in content, \
            "migration.sql should contain index DDL statements"


# ============================================================
# Q1: Employee lookup with date arithmetic obfuscation
# ============================================================

class TestQ1:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q1.sql")

    def test_no_seq_scan(self):
        sql = strip_sql(read_optimized_query(1))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q1"
        assert not has_seq_scan_on(plan, "employees"), \
            "Q1 must not use Seq Scan on employees"

    def test_no_date_arithmetic_on_column(self):
        """The obfuscation (date_of_birth + INTERVAL) must be removed."""
        content = read_optimized_query(1).lower()
        assert "date_of_birth + interval" not in content and \
               "date_of_birth +interval" not in content, \
            "Optimized Q1 should not add INTERVAL to date_of_birth column"

    def test_correct_results(self):
        original = """
            SELECT employee_id, subsidiary_id, first_name, last_name, date_of_birth
            FROM employees
            WHERE subsidiary_id = 5
              AND date_of_birth + INTERVAL '30 years' < CURRENT_DATE
            ORDER BY last_name, first_name
        """
        optimized = strip_sql(read_optimized_query(1))
        orig_result, _ = run_sql(original)
        opt_result, rc = run_sql(optimized)
        assert rc == 0, "Optimized Q1 failed to execute"
        assert orig_result == opt_result, \
            "Q1 optimized results differ from original"


# ============================================================
# Q2: Date obfuscation with EXTRACT
# ============================================================

class TestQ2:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q2.sql")

    def test_no_extract(self):
        content = read_optimized_query(2).lower()
        assert "extract" not in content, \
            "Optimized Q2 must not use EXTRACT function"

    def test_no_seq_scan(self):
        sql = strip_sql(read_optimized_query(2))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q2"
        assert not has_seq_scan_on(plan, "sales"), \
            "Q2 must not use Seq Scan on sales"

    def test_correct_results(self):
        original = """
            SELECT employee_id, subsidiary_id, SUM(eur_value) as total,
                   COUNT(*) as num_sales
            FROM sales
            WHERE EXTRACT(YEAR FROM sale_date) = 2024
              AND EXTRACT(QUARTER FROM sale_date) = 2
            GROUP BY employee_id, subsidiary_id
            ORDER BY total DESC
        """
        optimized = strip_sql(read_optimized_query(2))
        orig_result, _ = run_sql(original)
        opt_result, rc = run_sql(optimized)
        assert rc == 0, "Optimized Q2 failed to execute"
        # Use set comparison: ORDER BY total DESC has ties among groups
        # with equal totals, and different plans may order ties differently
        assert compare_result_rows(orig_result, opt_result), \
            "Q2 optimized results differ from original"


# ============================================================
# Q3: Aggregation requiring Index Only Scan (covering index)
# ============================================================

class TestQ3:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q3.sql")

    def test_uses_index_only_scan(self):
        sql = strip_sql(read_optimized_query(3))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q3"
        assert not has_seq_scan_on(plan, "sales"), \
            "Q3 must not use Seq Scan on sales"
        node_types = find_node_types(plan)
        assert "Index Only Scan" in node_types, \
            f"Q3 must use Index Only Scan (covering index). Got node types: {node_types}"

    def test_correct_results(self):
        original = """
            SELECT subsidiary_id, SUM(eur_value) as total_revenue,
                   COUNT(*) as sale_count
            FROM sales
            WHERE subsidiary_id IN (1, 2, 3, 4, 5)
            GROUP BY subsidiary_id
            ORDER BY total_revenue DESC
        """
        optimized = strip_sql(read_optimized_query(3))
        orig_result, _ = run_sql(original)
        opt_result, rc = run_sql(optimized)
        assert rc == 0, "Optimized Q3 failed to execute"
        assert orig_result == opt_result, \
            "Q3 optimized results differ from original"


# ============================================================
# Q4: Join optimization with missing indexes
# ============================================================

class TestQ4:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q4.sql")

    def test_no_seq_scan_employees(self):
        sql = strip_sql(read_optimized_query(4))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q4"
        assert not has_seq_scan_on(plan, "employees"), \
            "Q4 must not use Seq Scan on employees"

    def test_no_seq_scan_sales(self):
        sql = strip_sql(read_optimized_query(4))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q4"
        assert not has_seq_scan_on(plan, "sales"), \
            "Q4 must not use Seq Scan on sales"

    def test_correct_results(self):
        original = """
            SELECT e.first_name, e.last_name, s.sale_date, s.eur_value
            FROM employees e
            JOIN sales s ON e.employee_id = s.employee_id
                        AND e.subsidiary_id = s.subsidiary_id
            WHERE e.subsidiary_id = 10
              AND e.last_name = 'Smith'
            ORDER BY s.sale_date DESC
            LIMIT 50
        """
        optimized = strip_sql(read_optimized_query(4))
        orig_result, _ = run_sql(original)
        opt_result, rc = run_sql(optimized)
        assert rc == 0, "Optimized Q4 failed to execute"
        assert orig_result == opt_result, \
            "Q4 optimized results differ from original"


# ============================================================
# Q5: Seek method pagination (no OFFSET)
# ============================================================

class TestQ5:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q5.sql")

    def test_no_offset(self):
        content = read_optimized_query(5).lower()
        assert "offset" not in content, \
            "Optimized Q5 must not use OFFSET keyword"

    def test_uses_row_value_comparison(self):
        content = read_optimized_query(5)
        has_pattern = bool(
            re.search(r'\(\s*sale_date\s*,\s*sale_id\s*\)\s*<',
                       content, re.IGNORECASE)
            or re.search(r'ROW\s*\(\s*sale_date\s*,\s*sale_id\s*\)\s*<',
                          content, re.IGNORECASE)
        )
        assert has_pattern, \
            "Q5 must use row value comparison: (sale_date, sale_id) < (...)"

    def test_executes_and_returns_rows(self):
        sql = strip_sql(read_optimized_query(5))
        result, rc = run_sql(sql)
        assert rc == 0, "Optimized Q5 failed to execute"
        rows = [r for r in result.split("\n") if r.strip()]
        assert 1 <= len(rows) <= 10, \
            f"Q5 should return 1-10 rows, got {len(rows)}"

    def test_no_seq_scan(self):
        sql = strip_sql(read_optimized_query(5))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q5"
        assert not has_seq_scan_on(plan, "sales"), \
            "Q5 must not use Seq Scan on sales"

    def test_has_supporting_index(self):
        """Index on (sale_date, sale_id) must exist for seek method."""
        result, _ = run_sql("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'sales'
              AND indexdef LIKE '%sale_date%'
              AND indexdef LIKE '%sale_id%'
        """)
        assert int(result) > 0, \
            "Need index containing both sale_date and sale_id for seek method"

    def test_seek_concept_correct(self):
        """Verify seek method returns same rows as equivalent OFFSET."""
        # Use a small offset for speed
        cursor_result, rc = run_sql("""
            SELECT sale_date, sale_id FROM sales
            ORDER BY sale_date DESC, sale_id DESC
            OFFSET 999 LIMIT 1
        """)
        assert rc == 0 and cursor_result, "Failed to get cursor position"
        parts = cursor_result.split("|")
        cursor_date = parts[0].strip()
        cursor_id = parts[1].strip()

        expected, _ = run_sql("""
            SELECT sale_id, sale_date, eur_value, product_id FROM sales
            ORDER BY sale_date DESC, sale_id DESC
            LIMIT 10 OFFSET 1000
        """)

        actual, rc = run_sql(f"""
            SELECT sale_id, sale_date, eur_value, product_id FROM sales
            WHERE (sale_date, sale_id) < ('{cursor_date}'::timestamp, {cursor_id})
            ORDER BY sale_date DESC, sale_id DESC
            FETCH FIRST 10 ROWS ONLY
        """)
        assert rc == 0, "Seek query failed to execute"
        assert actual == expected, \
            "Seek method must produce same results as equivalent OFFSET"


# ============================================================
# Q6: Partial index for message queue
# ============================================================

class TestQ6:
    def test_file_exists(self):
        assert os.path.exists("/app/optimized/q6.sql")

    def test_no_seq_scan(self):
        sql = strip_sql(read_optimized_query(6))
        plan = get_explain_json(sql)
        assert plan is not None, "EXPLAIN failed on optimized Q6"
        assert not has_seq_scan_on(plan, "messages"), \
            "Q6 must not use Seq Scan on messages"

    def test_has_partial_index(self):
        """A partial (filtered) index must exist on messages."""
        result, _ = run_sql("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'messages'
              AND indexdef LIKE '%WHERE%'
        """)
        assert int(result) > 0, \
            "Messages table should have a partial index (with WHERE clause)"

    def test_correct_results(self):
        original = """
            SELECT message_id, sender, subject, message_text, created_at
            FROM messages
            WHERE processed = 'N'
              AND receiver = 'user_42'
            ORDER BY created_at ASC
            LIMIT 50
        """
        optimized = strip_sql(read_optimized_query(6))
        orig_result, _ = run_sql(original)
        opt_result, rc = run_sql(optimized)
        assert rc == 0, "Optimized Q6 failed to execute"
        assert orig_result == opt_result, \
            "Q6 optimized results differ from original"


# ============================================================
# Index budget and redundancy tests
# ============================================================

class TestIndexBudget:
    def test_max_non_pk_indexes(self):
        """Total non-primary-key indexes must not exceed 8."""
        result, _ = run_sql("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname NOT IN (
                  'subsidiaries_pkey', 'employees_pk',
                  'sales_pkey', 'messages_pkey'
              )
        """)
        count = int(result)
        assert count <= 8, \
            f"Too many non-PK indexes: {count} (maximum allowed: 8)"

    def test_idx_sales_value_dropped(self):
        """idx_sales_value (on eur_value alone) is useless and must be dropped."""
        result, _ = run_sql("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE indexname = 'idx_sales_value'
        """)
        assert int(result) == 0, \
            "idx_sales_value is redundant and should be dropped"

    def test_idx_messages_processed_dropped(self):
        """idx_messages_processed has terrible selectivity and must be dropped."""
        result, _ = run_sql("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE indexname = 'idx_messages_processed'
        """)
        assert int(result) == 0, \
            "idx_messages_processed is redundant (only 2 distinct values) " \
            "and should be dropped"
