
"""
Verification tests for the dbt e-commerce pipeline task.
Tests verify all bugs are fixed, missing components are created, and the
pipeline produces correct data across all mart models.
"""

import subprocess
import os
import duckdb
import pytest

PROJECT_DIR = '/app/dbt_project'
DB_PATH = os.path.join(PROJECT_DIR, 'dev.duckdb')


def run_dbt(*args, timeout=180):
    """Helper to run dbt commands and return the result."""
    result = subprocess.run(
        ['dbt'] + list(args),
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def query_db(sql):
    """Run a query against DuckDB. Opens and closes connection each call."""
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def query_columns(table):
    """Return column names for a table."""
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        return [
            c[0] for c in conn.execute(
                f"SELECT * FROM main.{table} LIMIT 0"
            ).description
        ]
    finally:
        conn.close()


class TestDbtProjectFixes:
    """Ordered tests verifying the dbt project builds and produces correct data."""

    def test_01_dbt_compile_no_cycles(self):
        """Project should compile without circular dependency errors."""
        result = run_dbt('compile')
        combined = result.stdout + result.stderr
        assert 'Found a cycle' not in combined, (
            "Circular dependency detected in the DAG"
        )
        assert result.returncode == 0, (
            f"dbt compile failed:\n{combined[-3000:]}"
        )

    def test_02_dbt_build_fresh(self):
        """Full dbt build with --full-refresh should succeed."""
        run_dbt('clean')
        result = run_dbt('build', '--full-refresh')
        assert result.returncode == 0, (
            f"dbt build --full-refresh failed:\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-1000:]}"
        )

    def test_03_dbt_build_incremental(self):
        """Second dbt build should succeed (validates incremental model)."""
        result = run_dbt('build')
        assert result.returncode == 0, (
            f"dbt build (incremental run) failed — check unique_key and "
            f"is_incremental filter:\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-1000:]}"
        )

    def test_04_dim_customers_row_count(self):
        """dim_customers should contain exactly 5 customers."""
        count = query_db("SELECT count(*) FROM main.dim_customers")[0][0]
        assert count == 5, f"Expected 5 customers, got {count}"

    def test_05_dim_customers_columns(self):
        """dim_customers should have all expected columns."""
        cols = query_columns('dim_customers')
        expected = [
            'customer_id', 'first_name', 'last_name', 'email',
            'first_order_date', 'most_recent_order_date',
            'number_of_orders', 'lifetime_value',
        ]
        for col in expected:
            assert col in cols, f"Column '{col}' missing from dim_customers"

    def test_06_dim_customers_lifetime_values(self):
        """All lifetime values should be positive (validates cents_to_dollars macro)."""
        bad = query_db(
            "SELECT count(*) FROM main.dim_customers WHERE lifetime_value <= 0"
        )[0][0]
        assert bad == 0, (
            f"{bad} customers have non-positive lifetime_value — "
            "cents_to_dollars macro may be broken"
        )

    def test_07_dim_customers_amounts_in_dollars(self):
        """Lifetime values should be in dollars, not cents."""
        max_val = query_db(
            "SELECT max(lifetime_value) FROM main.dim_customers"
        )[0][0]
        assert max_val < 500, (
            f"Max lifetime_value is {max_val} — "
            "amounts appear to still be in cents"
        )

    def test_08_fct_orders_row_count(self):
        """fct_orders should contain exactly 10 orders."""
        count = query_db("SELECT count(*) FROM main.fct_orders")[0][0]
        assert count == 10, f"Expected 10 orders, got {count}"

    def test_09_fct_orders_payment_columns(self):
        """fct_orders should have per-method payment columns (validates var)."""
        cols = query_columns('fct_orders')
        for method in ['credit_card_amount', 'bank_transfer_amount', 'coupon_amount']:
            assert method in cols, (
                f"Column '{method}' missing from fct_orders — "
                "payment_methods var may be misconfigured"
            )

    def test_10_revenue_daily_row_count(self):
        """revenue_daily should have rows (one per unique order date)."""
        count = query_db("SELECT count(*) FROM main.revenue_daily")[0][0]
        assert count == 10, f"Expected 10 date rows in revenue_daily, got {count}"

    def test_11_revenue_daily_positive_revenue(self):
        """All daily revenues should be positive (validates is_positive test)."""
        bad = query_db(
            "SELECT count(*) FROM main.revenue_daily WHERE total_revenue <= 0"
        )[0][0]
        assert bad == 0, (
            f"{bad} rows have non-positive total_revenue — "
            "is_positive test logic may still be inverted"
        )

    def test_12_source_schema_correct(self):
        """Raw source tables should be accessible in the main schema."""
        conn = duckdb.connect(DB_PATH, read_only=False)
        try:
            for tbl in ['raw_customers', 'raw_orders', 'raw_payments']:
                count = conn.execute(
                    f"SELECT count(*) FROM main.{tbl}"
                ).fetchone()[0]
                assert count > 0, f"Source table main.{tbl} is empty or missing"
        finally:
            conn.close()

    def test_13_customer_lifetime_tiers_row_count(self):
        """customer_lifetime_tiers should contain exactly 5 rows (one per customer)."""
        count = query_db("SELECT count(*) FROM main.customer_lifetime_tiers")[0][0]
        assert count == 5, f"Expected 5 rows in customer_lifetime_tiers, got {count}"

    def test_14_customer_lifetime_tiers_columns(self):
        """customer_lifetime_tiers should have all required columns."""
        cols = query_columns('customer_lifetime_tiers')
        for col in ['customer_id', 'tier', 'value_quartile', 'lifetime_value']:
            assert col in cols, (
                f"Column '{col}' missing from customer_lifetime_tiers"
            )

    def test_15_customer_lifetime_tiers_tier_distribution(self):
        """Tier distribution must match tier_thresholds var applied to actual data.
        Expected: 2 bronze (<$20), 1 silver (>=$20), 2 gold (>=$50), 0 platinum (>=$100)."""
        tiers = query_db(
            "SELECT tier, count(*) FROM main.customer_lifetime_tiers "
            "GROUP BY tier ORDER BY tier"
        )
        tier_dict = {row[0]: row[1] for row in tiers}
        assert tier_dict.get('bronze', 0) == 2, (
            f"Expected 2 bronze customers, got tier distribution: {tier_dict}"
        )
        assert tier_dict.get('silver', 0) == 1, (
            f"Expected 1 silver customer, got tier distribution: {tier_dict}"
        )
        assert tier_dict.get('gold', 0) == 2, (
            f"Expected 2 gold customers, got tier distribution: {tier_dict}"
        )
        assert tier_dict.get('platinum', 0) == 0, (
            f"Expected 0 platinum customers, got tier distribution: {tier_dict}"
        )

    def test_16_customer_lifetime_tiers_quartiles_valid(self):
        """All value_quartile values should be between 1 and 4."""
        bad = query_db(
            "SELECT count(*) FROM main.customer_lifetime_tiers "
            "WHERE value_quartile < 1 OR value_quartile > 4"
        )[0][0]
        assert bad == 0, (
            f"{bad} rows have value_quartile outside [1,4] range"
        )

    def test_17_within_range_macro_created(self):
        """Custom generic test 'within_range' should exist in macros directory."""
        macro_dir = os.path.join(PROJECT_DIR, 'macros')
        macros = os.listdir(macro_dir) if os.path.isdir(macro_dir) else []
        assert any('within_range' in f for f in macros), (
            "Custom test macro 'within_range' not found in macros/ — "
            "it is required by customer_lifetime_tiers schema in _marts.yml"
        )
