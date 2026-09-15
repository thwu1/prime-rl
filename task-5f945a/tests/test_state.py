"""
Tests to verify the dbt revenue reconciliation pipeline produces correct results.

Expected mart_reconciled_revenue rows (5 total, $416.90 total):
  (2024-01-15, Electronics, $167.50, 2)
  (2024-01-16, Hardware,    $ 37.50, 1)
  (2024-01-17, Electronics, $108.00, 1)
  (2024-01-17, Hardware,    $ 15.00, 1)
  (2024-01-18, Electronics, $ 88.90, 1)
"""

import subprocess
import os
import json
import pytest
import duckdb


PROJECT_DIR = "/app/dbt_project"
DB_PATH = os.path.join(PROJECT_DIR, "dev.duckdb")


@pytest.fixture(scope="session")
def dbt_build_result():
    """Clean build: remove old database, run full dbt build."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    result = subprocess.run(
        ["dbt", "build"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=180
    )
    return result


@pytest.fixture
def db(dbt_build_result):
    """Connect to the DuckDB database after build completes."""
    assert dbt_build_result.returncode == 0, (
        f"dbt build must succeed before querying data.\n"
        f"STDOUT:\n{dbt_build_result.stdout[-2000:]}\n"
        f"STDERR:\n{dbt_build_result.stderr[-2000:]}"
    )
    conn = duckdb.connect(DB_PATH, read_only=True)
    yield conn
    conn.close()


def test_dbt_build_succeeds(dbt_build_result):
    """dbt build must exit with code 0 (all seeds, models, and tests pass)."""
    assert dbt_build_result.returncode == 0, (
        f"dbt build failed with exit code {dbt_build_result.returncode}.\n"
        f"STDOUT:\n{dbt_build_result.stdout[-3000:]}\n"
        f"STDERR:\n{dbt_build_result.stderr[-3000:]}"
    )


def test_mart_table_exists(db):
    """Verify mart_reconciled_revenue table exists in the database."""
    tables = db.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name = 'mart_reconciled_revenue'"
    ).fetchall()
    assert len(tables) == 1, "mart_reconciled_revenue table does not exist"


def test_row_count(db):
    """Mart should have exactly 5 rows (5 unique date-category combinations)."""
    count = db.execute(
        "SELECT COUNT(*) FROM mart_reconciled_revenue"
    ).fetchone()[0]
    assert count == 5, f"Expected 5 rows in mart_reconciled_revenue, got {count}"


def test_total_revenue(db):
    """Total revenue across all rows should be $416.90."""
    total = db.execute(
        "SELECT ROUND(SUM(total_revenue_usd), 2) FROM mart_reconciled_revenue"
    ).fetchone()[0]
    assert abs(total - 416.90) < 0.01, f"Expected total revenue ~416.90, got {total}"


def test_revenue_2024_01_15_electronics(db):
    """2024-01-15 Electronics: orders 1(USD)+2(EUR), deduped items, adj on item 1.
    item1: (2*2000-500)/100*1.00=$35.00, item2: 5000/100*1.00=$50.00,
    item3: 3*2500/100*1.10=$82.50 -> total=$167.50, 2 orders."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2), order_count "
        "FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-15' "
        "AND category = 'Electronics'"
    ).fetchone()
    assert row is not None, "Missing row for (2024-01-15, Electronics)"
    assert abs(row[0] - 167.50) < 0.01, f"Expected revenue 167.50, got {row[0]}"
    assert row[1] == 2, f"Expected order_count 2, got {row[1]}"


def test_revenue_2024_01_16_hardware(db):
    """2024-01-16 Hardware: order 3(GBP), adj on item 4.
    item4: (1*4000-1000)/100*1.25=$37.50 -> 1 order."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2), order_count "
        "FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-16' "
        "AND category = 'Hardware'"
    ).fetchone()
    assert row is not None, "Missing row for (2024-01-16, Hardware)"
    assert abs(row[0] - 37.50) < 0.01, f"Expected revenue 37.50, got {row[0]}"
    assert row[1] == 1, f"Expected order_count 1, got {row[1]}"


def test_revenue_2024_01_17_electronics(db):
    """2024-01-17 Electronics: order 5(EUR).
    item6: 2*5000/100*1.08=$108.00 -> 1 order."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2), order_count "
        "FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-17' "
        "AND category = 'Electronics'"
    ).fetchone()
    assert row is not None, "Missing row for (2024-01-17, Electronics)"
    assert abs(row[0] - 108.00) < 0.01, f"Expected revenue 108.00, got {row[0]}"
    assert row[1] == 1, f"Expected order_count 1, got {row[1]}"


def test_revenue_2024_01_17_hardware(db):
    """2024-01-17 Hardware: order 6(USD), adj on item 7.
    item7: (1*3000-1500)/100*1.00=$15.00 -> 1 order."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2), order_count "
        "FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-17' "
        "AND category = 'Hardware'"
    ).fetchone()
    assert row is not None, "Missing row for (2024-01-17, Hardware)"
    assert abs(row[0] - 15.00) < 0.01, f"Expected revenue 15.00, got {row[0]}"
    assert row[1] == 1, f"Expected order_count 1, got {row[1]}"


def test_revenue_2024_01_18_electronics(db):
    """2024-01-18 Electronics: order 7(GBP).
    item8: 2*3500/100*1.27=$88.90 -> 1 order."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2), order_count "
        "FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-18' "
        "AND category = 'Electronics'"
    ).fetchone()
    assert row is not None, "Missing row for (2024-01-18, Electronics)"
    assert abs(row[0] - 88.90) < 0.01, f"Expected revenue 88.90, got {row[0]}"
    assert row[1] == 1, f"Expected order_count 1, got {row[1]}"


def test_no_returned_orders(db):
    """Returned order 4 (2024-01-16, Electronics) must not appear."""
    rows = db.execute(
        "SELECT * FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-16' "
        "AND category = 'Electronics'"
    ).fetchall()
    assert len(rows) == 0, (
        "Returned orders should not appear in revenue summary"
    )


def test_no_pending_orders(db):
    """Pending order 8 (2024-01-18, Electronics) must not inflate revenue."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2) FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-18' "
        "AND category = 'Electronics'"
    ).fetchone()
    assert row is not None
    assert abs(row[0] - 88.90) < 0.01, (
        f"Expected 88.90 for 2024-01-18 Electronics (order 7 only), got {row[0]}. "
        "Pending order 8 may have been incorrectly included."
    )


def test_unique_date_category_combinations(db):
    """Each (order_date, category) combination should appear exactly once."""
    rows = db.execute(
        "SELECT CAST(order_date AS VARCHAR), category, COUNT(*) as cnt "
        "FROM mart_reconciled_revenue "
        "GROUP BY 1, 2 HAVING COUNT(*) > 1"
    ).fetchall()
    assert len(rows) == 0, f"Duplicate (date, category) combinations found: {rows}"


def test_reconciliation_test_ran(dbt_build_result):
    """Custom generic test 'reconciliation' must exist and pass in dbt build."""
    assert dbt_build_result.returncode == 0, "dbt build must succeed first"
    run_results_path = os.path.join(PROJECT_DIR, "target/run_results.json")
    assert os.path.exists(run_results_path), (
        "target/run_results.json not found -- dbt build may not have completed"
    )
    with open(run_results_path) as f:
        results = json.load(f)
    test_results = [
        r for r in results["results"]
        if "reconciliation" in r.get("unique_id", "").lower()
    ]
    assert len(test_results) > 0, (
        "No reconciliation test found in dbt build results. "
        "Create a custom generic dbt test named 'test_reconciliation'."
    )
    for tr in test_results:
        assert tr["status"] == "pass", (
            f"Reconciliation test failed: {tr.get('unique_id')}"
        )


def test_currency_conversion_applied(db):
    """Verify multi-currency conversion is correct by checking EUR and GBP rows.
    If all amounts were treated as USD (rate=1), totals would differ."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2) FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-15' "
        "AND category = 'Electronics'"
    ).fetchone()
    assert row is not None
    assert row[0] != 125.00, (
        "Revenue appears to not apply currency conversion (got 125.00)"
    )
    assert abs(row[0] - 167.50) < 0.01


def test_adjustments_applied(db):
    """Verify adjustments reduce revenue. Without adj, 2024-01-17 Hardware would be
    $30.00 (3000 cents / 100), but with -1500 cent refund it should be $15.00."""
    row = db.execute(
        "SELECT ROUND(total_revenue_usd, 2) FROM mart_reconciled_revenue "
        "WHERE CAST(order_date AS VARCHAR) = '2024-01-17' "
        "AND category = 'Hardware'"
    ).fetchone()
    assert row is not None
    assert row[0] != 30.00, (
        "Revenue appears to not apply adjustments (got 30.00 instead of 15.00)"
    )
    assert abs(row[0] - 15.00) < 0.01
