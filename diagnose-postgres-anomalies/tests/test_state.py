
"""
Tests for PostgreSQL production performance audit task.
Verifies that performance issues have been diagnosed, fixed,
evaluated, and documented with justification.
"""

import json
import os
import re

import psycopg2
import pytest


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(dbname="benchmark", user="postgres")
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture(scope="module")
def cur(conn):
    return conn.cursor()


# ================================================================
# 1. Index Coverage
# ================================================================

class TestMissingIndexes:
    """Verify that indexes have been created on heavily queried columns."""

    @pytest.mark.parametrize("table,column", [
        ("orders", "o_customer_id"),
        ("orders", "o_status"),
        ("order_items", "oi_order_id"),
        ("order_items", "oi_product_id"),
    ])
    def test_index_exists(self, cur, table, column):
        """An index covering this column (single or leading composite) must exist."""
        cur.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
              AND (indexdef LIKE %s OR indexdef LIKE %s)
        """, (table, f'%({column})%', f'%({column},%'))
        count = cur.fetchone()[0]
        assert count > 0, (
            f"No index found on {table}.{column}. "
            f"The workload shows heavy query traffic on this column."
        )


# ================================================================
# 2. Index Efficiency
# ================================================================

class TestRedundantIndexes:
    """Verify that prefix-redundant indexes have been removed."""

    def test_no_single_column_region_index(self, cur):
        """Single-column index on customers(c_region) is redundant and should be dropped."""
        cur.execute("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'customers'
              AND indexname NOT LIKE '%%_pkey'
        """)
        for name, defn in cur.fetchall():
            match = re.search(r'\(([^)]+)\)\s*$', defn.strip())
            if match:
                cols = [c.strip().split()[0] for c in match.group(1).split(',')]
                if cols == ['c_region']:
                    pytest.fail(
                        f"Redundant index {name} on customers(c_region) still exists. "
                        f"It is a strict prefix of composite indexes on the same table."
                    )

    def test_composite_indexes_preserved(self, cur):
        """Useful composite indexes on customers should NOT be dropped."""
        cur.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'customers'
              AND indexname NOT LIKE '%%_pkey'
        """)
        count = cur.fetchone()[0]
        assert count >= 2, (
            f"Expected at least 2 non-PK indexes on customers "
            f"(composite indexes should be preserved), found {count}"
        )


# ================================================================
# 3. Storage Health
# ================================================================

class TestTableBloat:
    """Verify that table bloat has been addressed via VACUUM."""

    def test_audit_log_dead_tuples_low(self, cur):
        """After VACUUM, audit_log should have minimal dead tuples."""
        cur.execute("""
            SELECT n_dead_tup FROM pg_stat_user_tables
            WHERE relname = 'audit_log'
        """)
        row = cur.fetchone()
        assert row is not None, "audit_log not found in pg_stat_user_tables"
        n_dead = row[0]
        assert n_dead < 1000, (
            f"audit_log has {n_dead} dead tuples. "
            f"VACUUM should have been performed to reclaim bloated space."
        )


# ================================================================
# 4. Server Tuning
# ================================================================

class TestKnobConfiguration:
    """Verify PostgreSQL configuration has been tuned to reasonable values."""

    def _get_setting_bytes(self, cur, name):
        cur.execute(
            "SELECT setting, unit FROM pg_settings WHERE name = %s", (name,)
        )
        row = cur.fetchone()
        val = int(row[0])
        unit = row[1]
        multipliers = {
            '8kB': 8192, 'kB': 1024, 'MB': 1048576, 'GB': 1073741824
        }
        return val * multipliers.get(unit, 1)

    def test_shared_buffers(self, cur):
        val = self._get_setting_bytes(cur, 'shared_buffers')
        assert val >= 128 * 1024 * 1024, (
            f"shared_buffers = {val // (1024*1024)}MB, should be >= 128MB"
        )

    def test_work_mem(self, cur):
        val = self._get_setting_bytes(cur, 'work_mem')
        assert val >= 4 * 1024 * 1024, (
            f"work_mem = {val // 1024}kB, should be >= 4MB"
        )

    def test_maintenance_work_mem(self, cur):
        val = self._get_setting_bytes(cur, 'maintenance_work_mem')
        assert val >= 64 * 1024 * 1024, (
            f"maintenance_work_mem = {val // (1024*1024)}MB, should be >= 64MB"
        )

    def test_effective_cache_size(self, cur):
        val = self._get_setting_bytes(cur, 'effective_cache_size')
        assert val >= 512 * 1024 * 1024, (
            f"effective_cache_size = {val // (1024*1024)}MB, should be >= 512MB"
        )

    def test_random_page_cost(self, cur):
        cur.execute(
            "SELECT setting FROM pg_settings WHERE name = 'random_page_cost'"
        )
        val = float(cur.fetchone()[0])
        assert val <= 2.0, (
            f"random_page_cost = {val}, should be <= 2.0 for modern storage"
        )


# ================================================================
# 5. View Optimization
# ================================================================

class TestSlowQueryRewrite:
    """Verify that the correlated subquery view has been rewritten."""

    def test_view_exists(self, cur):
        cur.execute("""
            SELECT COUNT(*) FROM pg_views
            WHERE viewname = 'v_customer_order_summary'
        """)
        assert cur.fetchone()[0] == 1, "View v_customer_order_summary not found"

    def test_view_no_correlated_subqueries(self, cur):
        """View definition should not contain multiple correlated subqueries."""
        cur.execute("""
            SELECT definition FROM pg_views
            WHERE viewname = 'v_customer_order_summary'
        """)
        defn = cur.fetchone()[0].lower()
        select_count = defn.count('select')
        assert select_count <= 2, (
            f"View definition contains {select_count} SELECT keywords, "
            f"indicating correlated subqueries remain. "
            f"Expected <= 2 after rewrite (outer query + optional FROM subquery)."
        )

    def test_view_produces_correct_results(self, cur):
        """Rewritten view must produce identical results to the original logic."""
        cur.execute("""
            SELECT c_id, order_count, total_spent
            FROM v_customer_order_summary
            WHERE c_id IN (1, 100, 500)
            ORDER BY c_id
        """)
        view_results = cur.fetchall()

        cur.execute("""
            SELECT c.c_id,
                   COALESCE(agg.cnt, 0) AS order_count,
                   COALESCE(agg.total, 0.00) AS total_spent
            FROM customers c
            LEFT JOIN (
                SELECT o_customer_id,
                       COUNT(*) AS cnt,
                       SUM(o_total) AS total
                FROM orders
                GROUP BY o_customer_id
            ) agg ON c.c_id = agg.o_customer_id
            WHERE c.c_id IN (1, 100, 500)
            ORDER BY c.c_id
        """)
        expected = cur.fetchall()

        assert len(view_results) == len(expected), (
            f"View returned {len(view_results)} rows, expected {len(expected)}"
        )
        for v_row, e_row in zip(view_results, expected):
            assert v_row[0] == e_row[0], (
                f"Customer ID mismatch: {v_row[0]} vs {e_row[0]}"
            )
            assert int(v_row[1]) == int(e_row[1]), (
                f"Order count mismatch for c_id={v_row[0]}: "
                f"{v_row[1]} vs {e_row[1]}"
            )
            assert abs(float(v_row[2]) - float(e_row[2])) < 0.01, (
                f"Total spent mismatch for c_id={v_row[0]}: "
                f"{v_row[2]} vs {e_row[2]}"
            )


# ================================================================
# 6. Performance Evaluation
# ================================================================

class TestPerformanceEvaluation:
    """Verify the before/after performance comparison."""

    def test_eval_exists(self):
        assert os.path.exists('/app/performance_eval.json'), (
            "Performance evaluation not found at /app/performance_eval.json"
        )

    def test_eval_valid_structure(self):
        with open('/app/performance_eval.json') as f:
            data = json.load(f)
        assert 'evaluations' in data, "Missing 'evaluations' key"
        assert isinstance(data['evaluations'], list), "'evaluations' must be a list"
        assert len(data['evaluations']) >= 3, (
            f"Expected at least 3 query evaluations, found {len(data['evaluations'])}"
        )

    def test_eval_has_required_fields(self):
        with open('/app/performance_eval.json') as f:
            data = json.load(f)
        required = {'query_id', 'query_sql', 'before_total_cost',
                     'after_total_cost', 'improvement_pct'}
        for i, ev in enumerate(data['evaluations']):
            missing = required - set(ev.keys())
            assert not missing, (
                f"Evaluation #{i} missing fields: {missing}. "
                f"Each evaluation must have: {required}"
            )

    def test_eval_shows_improvement(self):
        with open('/app/performance_eval.json') as f:
            data = json.load(f)
        improved = sum(
            1 for ev in data['evaluations']
            if float(ev.get('improvement_pct', 0)) > 0
        )
        assert improved >= 2, (
            f"Only {improved} queries showed positive improvement, expected >= 2"
        )


# ================================================================
# 7. Diagnosis Report
# ================================================================

class TestDiagnosisReport:
    """Verify the structured diagnosis report."""

    def test_report_exists(self):
        assert os.path.exists('/app/diagnosis.json'), (
            "Diagnosis report not found at /app/diagnosis.json"
        )

    def test_report_valid_json(self):
        with open('/app/diagnosis.json') as f:
            report = json.load(f)
        assert 'findings' in report, "Report missing 'findings' key"
        assert isinstance(report['findings'], list), "'findings' must be a list"

    def test_report_has_sufficient_findings(self):
        with open('/app/diagnosis.json') as f:
            report = json.load(f)
        assert len(report['findings']) >= 5, (
            f"Report has {len(report['findings'])} findings, expected >= 5. "
            f"A thorough audit should uncover issues across multiple categories."
        )

    def test_report_findings_have_required_fields(self):
        with open('/app/diagnosis.json') as f:
            report = json.load(f)

        required_fields = {
            'anomaly_type', 'affected_object', 'description',
            'fix_applied', 'justification'
        }
        for i, finding in enumerate(report['findings']):
            missing = required_fields - set(finding.keys())
            assert not missing, (
                f"Finding #{i} missing fields: {missing}. "
                f"Each finding must have: {required_fields}"
            )
