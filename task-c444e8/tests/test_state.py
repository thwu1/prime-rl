"""
Tests for PostgreSQL Performance Optimization Challenge.
Verifies diagnosis correctness, fix effectiveness, and evaluation quality.
"""

import json
import os
import subprocess
import pytest


def psql(query, db="benchdb"):
    """Execute a psql query and return trimmed stdout."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", db, "-t", "-A", "-c", query],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip()


# ======================== DIAGNOSIS TESTS ========================

class TestDiagnosis:
    """Verify that diagnosis.json correctly identifies each query's root cause."""

    @pytest.fixture(autouse=True)
    def load_diagnosis(self):
        diag_path = "/app/diagnosis.json"
        assert os.path.exists(diag_path), \
            "diagnosis.json not found at /app/diagnosis.json"
        with open(diag_path) as f:
            self.diag = json.load(f)

    def _normalize(self, val):
        return val.upper().replace(" ", "_").replace("-", "_")

    def test_diagnosis_has_all_queries(self):
        assert set(self.diag.keys()) >= {"Q1", "Q2", "Q3", "Q4", "Q5"}, \
            f"diagnosis.json must contain keys Q1-Q5, got: {list(self.diag.keys())}"

    def test_q1_missing_index(self):
        cause = self._normalize(self.diag["Q1"])
        valid = {"MISSING_INDEX", "MISSING_COMPOSITE_INDEX", "NO_INDEX"}
        assert cause in valid, \
            f"Q1 root cause should be MISSING_INDEX, got: {self.diag['Q1']}"

    def test_q2_table_bloat(self):
        cause = self._normalize(self.diag["Q2"])
        valid = {"TABLE_BLOAT", "BLOAT", "DEAD_TUPLES", "VACUUM_NEEDED", "VACUUM"}
        assert cause in valid, \
            f"Q2 root cause should be TABLE_BLOAT, got: {self.diag['Q2']}"

    def test_q3_low_work_mem(self):
        cause = self._normalize(self.diag["Q3"])
        valid = {"LOW_WORK_MEM", "WORK_MEM", "INSUFFICIENT_MEMORY",
                 "DISK_SORT", "LOW_MEMORY", "MEMORY"}
        assert cause in valid, \
            f"Q3 root cause should be LOW_WORK_MEM, got: {self.diag['Q3']}"

    def test_q4_correlated_subquery(self):
        cause = self._normalize(self.diag["Q4"])
        valid = {"CORRELATED_SUBQUERY", "CORRELATED_SUBQUERIES", "SUBQUERY",
                 "VIEW_REWRITE", "SLOW_VIEW"}
        assert cause in valid, \
            f"Q4 root cause should be CORRELATED_SUBQUERY, got: {self.diag['Q4']}"

    def test_q5_missing_index(self):
        cause = self._normalize(self.diag["Q5"])
        valid = {"MISSING_INDEX", "MISSING_FK_INDEX", "NO_INDEX",
                 "MISSING_JOIN_INDEX", "MISSING_COMPOSITE_INDEX"}
        assert cause in valid, \
            f"Q5 root cause should be MISSING_INDEX, got: {self.diag['Q5']}"


# ======================== STRUCTURAL FIX TESTS ========================

class TestFixStructural:
    """Verify that structural database fixes have been applied."""

    def test_fix_sql_exists(self):
        assert os.path.exists("/app/fix.sql"), \
            "fix.sql not found at /app/fix.sql"

    def test_orders_composite_index_exists(self):
        """An index on orders must cover both customer_id and order_date."""
        count = psql("""
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'orders'
              AND indexdef LIKE '%customer_id%'
              AND indexdef LIKE '%order_date%';
        """)
        assert int(count) >= 1, \
            "Missing composite index on orders covering (customer_id, order_date)"

    def test_order_items_join_index_exists(self):
        """An index on order_items must cover order_id for efficient joins."""
        count = psql("""
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'order_items'
              AND indexname != 'order_items_pkey'
              AND indexdef LIKE '%order_id%';
        """)
        assert int(count) >= 1, \
            "Missing index on order_items covering order_id"

    def test_orders_bloat_resolved(self):
        """Dead tuple ratio on orders table must be below 10%."""
        result = psql("""
            SELECT CASE
                WHEN (n_live_tup + n_dead_tup) = 0 THEN 0
                ELSE ROUND(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
            END
            FROM pg_stat_user_tables
            WHERE relname = 'orders';
        """)
        dead_pct = float(result) if result else 0.0
        assert dead_pct < 10, \
            f"Orders table has {dead_pct}% dead tuples (must be < 10%)"

    def test_work_mem_adequate(self):
        """work_mem must be at least 32MB after fix."""
        val = psql("SHOW work_mem;")
        mem_kb = _parse_mem_to_kb(val)
        assert mem_kb >= 32 * 1024, \
            f"work_mem is {val} ({mem_kb} kB), must be >= 32MB"

    def test_view_no_subplan(self):
        """EXPLAIN of the product_summary view must not show SubPlan nodes."""
        explain = psql("""
            EXPLAIN (FORMAT TEXT)
            SELECT * FROM product_summary
            WHERE category = 'Electronics'
            ORDER BY avg_rating DESC NULLS LAST
            LIMIT 20;
        """)
        assert "SubPlan" not in explain, \
            "product_summary view still uses correlated subqueries " \
            "(SubPlan found in EXPLAIN output)"


# ======================== VIEW CORRECTNESS TESTS ========================

class TestViewCorrectness:
    """Verify the rewritten view produces semantically equivalent results."""

    def test_view_row_count(self):
        """View must have exactly one row per product."""
        view_count = int(psql("SELECT COUNT(*) FROM product_summary;"))
        product_count = int(psql("SELECT COUNT(*) FROM products;"))
        assert view_count == product_count, \
            f"product_summary has {view_count} rows, expected {product_count}"

    def test_view_total_review_count(self):
        """Sum of review_count across all products must equal total reviews."""
        view_total = int(psql(
            "SELECT COALESCE(SUM(review_count), 0)::bigint FROM product_summary;"
        ))
        actual_total = int(psql(
            "SELECT COUNT(*)::bigint FROM reviews;"
        ))
        assert view_total == actual_total, \
            f"View total review_count={view_total}, actual reviews={actual_total}. " \
            "Cross-join inflation is likely if view total is higher."

    def test_view_total_sold(self):
        """Sum of total_sold across all products must equal total order_items quantity."""
        view_total = int(psql(
            "SELECT COALESCE(SUM(total_sold), 0)::bigint FROM product_summary;"
        ))
        actual_total = int(psql(
            "SELECT COALESCE(SUM(quantity), 0)::bigint FROM order_items;"
        ))
        assert view_total == actual_total, \
            f"View total_sold={view_total}, actual quantity={actual_total}. " \
            "Cross-join inflation is likely if view total is higher."

    def test_view_avg_rating_spot_check(self):
        """Spot-check avg_rating for product id=1 against direct calculation."""
        view_avg = psql(
            "SELECT ROUND(avg_rating::numeric, 4) "
            "FROM product_summary WHERE id = 1;"
        )
        direct_avg = psql(
            "SELECT ROUND(AVG(rating)::numeric, 4) "
            "FROM reviews WHERE product_id = 1;"
        )
        assert view_avg == direct_avg, \
            f"avg_rating mismatch for product 1: view={view_avg}, direct={direct_avg}"

    def test_view_electronics_count(self):
        """Category filter must return correct number of Electronics products."""
        view_count = int(psql(
            "SELECT COUNT(*) FROM product_summary WHERE category = 'Electronics';"
        ))
        direct_count = int(psql(
            "SELECT COUNT(*) FROM products WHERE category = 'Electronics';"
        ))
        assert view_count == direct_count, \
            f"Electronics count: view={view_count}, direct={direct_count}"


# ======================== EVALUATION TESTS ========================

class TestEvaluation:
    """Verify that evaluation.json contains valid before/after cost analysis."""

    @pytest.fixture(autouse=True)
    def load_evaluation(self):
        eval_path = "/app/evaluation.json"
        assert os.path.exists(eval_path), \
            "evaluation.json not found at /app/evaluation.json"
        with open(eval_path) as f:
            self.evaluation = json.load(f)

    def test_evaluation_has_all_queries(self):
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            assert q in self.evaluation, \
                f"evaluation.json missing key {q}"

    def test_evaluation_structure(self):
        """Each query entry must have before_cost, after_cost, improvement_factor."""
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            entry = self.evaluation[q]
            assert "before_cost" in entry, f"{q} missing before_cost"
            assert "after_cost" in entry, f"{q} missing after_cost"
            assert "improvement_factor" in entry, f"{q} missing improvement_factor"

    def test_costs_are_positive(self):
        """All cost values must be positive numbers."""
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            entry = self.evaluation[q]
            assert float(entry["before_cost"]) > 0, \
                f"{q} before_cost must be positive"
            assert float(entry["after_cost"]) > 0, \
                f"{q} after_cost must be positive"

    def test_all_queries_improved(self):
        """Every query must show improvement (factor > 1.0)."""
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            entry = self.evaluation[q]
            factor = float(entry["improvement_factor"])
            assert factor > 1.0, \
                f"{q} improvement_factor={factor}, must be > 1.0"

    def test_improvement_factor_consistent(self):
        """Stated improvement factor must be roughly consistent with costs."""
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            entry = self.evaluation[q]
            before = float(entry["before_cost"])
            after = float(entry["after_cost"])
            stated = float(entry["improvement_factor"])
            computed = before / after
            # Allow generous tolerance since EXPLAIN costs can vary
            tolerance = max(1.0, computed * 0.3)
            assert abs(stated - computed) <= tolerance, \
                f"{q}: stated improvement {stated}x vs computed {computed:.1f}x"


# ======================== HELPERS ========================

def _parse_mem_to_kb(val):
    """Parse a PostgreSQL memory setting string to kilobytes."""
    val = val.strip()
    if val.endswith('kB'):
        return int(val[:-2])
    elif val.endswith('MB'):
        return int(val[:-2]) * 1024
    elif val.endswith('GB'):
        return int(val[:-2]) * 1024 * 1024
    elif val.endswith('TB'):
        return int(val[:-2]) * 1024 * 1024 * 1024
    else:
        try:
            return int(val) // 1024
        except ValueError:
            return 0
