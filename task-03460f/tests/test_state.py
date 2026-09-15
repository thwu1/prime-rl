"""
Verification tests for the SQLMesh analytics pipeline.
Checks that all bugs have been fixed and the pipeline produces correct results.
"""


import subprocess
import os
import pytest
import yaml


def run_cmd(args, timeout=120):
    """Run a command in /app and return the result."""
    return subprocess.run(
        args, cwd='/app', capture_output=True, text=True, timeout=timeout
    )


# ---------------------------------------------------------------------------
# Static checks: verify that each specific bug was fixed in the source files
# ---------------------------------------------------------------------------

class TestStaticFixes:

    def test_config_dialect_is_duckdb(self):
        """Bug 1: model_defaults.dialect must be 'duckdb', not 'postgres'."""
        with open('/app/config.yaml') as f:
            config = yaml.safe_load(f)
        dialect = config.get('model_defaults', {}).get('dialect', '')
        assert dialect == 'duckdb', (
            f"model_defaults.dialect is '{dialect}' but must be 'duckdb'"
        )

    def test_stg_orders_time_column_matches_output(self):
        """Bug 2: time_column must reference a column that exists in the SELECT output."""
        with open('/app/models/staging/stg_orders.sql') as f:
            content = f.read()
        assert 'ordered_at' not in content, (
            "stg_orders still references non-existent column 'ordered_at' as time_column"
        )

    def test_daily_revenue_has_time_range_filter(self):
        """Bug 3: INCREMENTAL_BY_TIME_RANGE models must filter by time range macros."""
        with open('/app/models/analytics/daily_revenue.sql') as f:
            content = f.read()
        has_filter = (
            '@start_ds' in content
            or '@start_date' in content
            or '@start_dt' in content
        )
        assert has_filter, (
            "daily_revenue is INCREMENTAL_BY_TIME_RANGE but missing required "
            "time range macro filter (@start_ds/@end_ds) in WHERE clause"
        )

    def test_top_products_correct_upstream_reference(self):
        """Bug 4: top_products must reference 'intermediate.int_order_products'."""
        with open('/app/models/analytics/top_products.sql') as f:
            content = f.read()
        assert 'int_order_products' in content, (
            "top_products references wrong upstream model name"
        )
        assert 'intermediate.order_products' not in content, (
            "top_products still references non-existent 'intermediate.order_products'"
        )

    def test_audit_checks_for_violations(self):
        """Bug 5: Audit must return violating rows (negative revenue), not passing rows."""
        audit_found = False
        for root, dirs, files in os.walk('/app/audits'):
            for fname in files:
                if not fname.endswith('.sql'):
                    continue
                path = os.path.join(root, fname)
                with open(path) as fh:
                    content = fh.read()
                if 'assert_positive_revenue' in content:
                    audit_found = True
                    # Normalize whitespace for checking
                    normalized = ' '.join(content.split())
                    assert 'total_revenue >= 0' not in normalized, (
                        "Audit logic is inverted: 'WHERE total_revenue >= 0' returns "
                        "good rows. Should be 'WHERE total_revenue < 0' to find violations."
                    )
        assert audit_found, "assert_positive_revenue audit definition not found"

    def test_unit_test_column_names(self):
        """Bug 6: Test expected output column names must match model output columns."""
        with open('/app/tests/test_daily_revenue.yaml') as f:
            content = f.read()
        # The model outputs: revenue_date, category, total_revenue, order_count
        # Buggy test used: date, category, revenue, num_orders
        assert 'revenue_date' in content, (
            "Test expected output should use 'revenue_date' not 'date'"
        )
        assert 'total_revenue' in content, (
            "Test expected output should use 'total_revenue' not 'revenue'"
        )
        assert 'order_count' in content, (
            "Test expected output should use 'order_count' not 'num_orders'"
        )


# ---------------------------------------------------------------------------
# Dynamic checks: run SQLMesh commands and verify pipeline execution
# ---------------------------------------------------------------------------

class TestPipelineExecution:

    def test_sqlmesh_unit_tests_pass(self):
        """All SQLMesh YAML-fixture unit tests must pass."""
        result = run_cmd(['sqlmesh', 'test'], timeout=120)
        assert result.returncode == 0, (
            f"'sqlmesh test' failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout[-2000:]}\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )

    def test_sqlmesh_plan_succeeds(self):
        """Full pipeline (plan + apply + audits) must complete without errors."""
        result = run_cmd(
            ['sqlmesh', 'plan', '--auto-apply', '--no-prompts'],
            timeout=300
        )
        assert result.returncode == 0, (
            f"'sqlmesh plan --auto-apply --no-prompts' failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout[-2000:]}\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )

    def test_daily_revenue_has_data(self):
        """analytics.daily_revenue must contain data after pipeline run."""
        result = run_cmd([
            'sqlmesh', 'fetchdf',
            "SELECT COUNT(*) AS cnt FROM analytics.daily_revenue"
        ], timeout=60)
        assert result.returncode == 0, (
            f"Failed to query analytics.daily_revenue:\n{result.stderr}"
        )
        # The output is a pandas DataFrame string; verify count > 0
        assert 'cnt' in result.stdout, "Missing cnt column in output"
        output_lines = result.stdout.strip().split('\n')
        # Find the data line (after header)
        found_positive = False
        for line in output_lines:
            line = line.strip()
            if line and line[0].isdigit():
                parts = line.split()
                if len(parts) >= 2:
                    count_val = int(parts[-1])
                    if count_val > 0:
                        found_positive = True
        assert found_positive, (
            f"analytics.daily_revenue has no data. Output:\n{result.stdout}"
        )

    def test_top_products_has_data(self):
        """analytics.top_products must contain data after pipeline run."""
        result = run_cmd([
            'sqlmesh', 'fetchdf',
            "SELECT COUNT(*) AS cnt FROM analytics.top_products"
        ], timeout=60)
        assert result.returncode == 0, (
            f"Failed to query analytics.top_products:\n{result.stderr}"
        )
        assert 'cnt' in result.stdout, "Missing cnt column in output"
        output_lines = result.stdout.strip().split('\n')
        found_positive = False
        for line in output_lines:
            line = line.strip()
            if line and line[0].isdigit():
                parts = line.split()
                if len(parts) >= 2:
                    count_val = int(parts[-1])
                    if count_val > 0:
                        found_positive = True
        assert found_positive, (
            f"analytics.top_products has no data. Output:\n{result.stdout}"
        )

    def test_daily_revenue_columns(self):
        """analytics.daily_revenue must have the correct column structure."""
        result = run_cmd([
            'sqlmesh', 'fetchdf',
            "SELECT * FROM analytics.daily_revenue LIMIT 1"
        ], timeout=60)
        assert result.returncode == 0, (
            f"Failed to query analytics.daily_revenue:\n{result.stderr}"
        )
        assert 'revenue_date' in result.stdout, "Missing 'revenue_date' column"
        assert 'total_revenue' in result.stdout, "Missing 'total_revenue' column"
        assert 'order_count' in result.stdout, "Missing 'order_count' column"
        assert 'category' in result.stdout, "Missing 'category' column"
