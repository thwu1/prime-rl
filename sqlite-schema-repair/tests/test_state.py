#!/usr/bin/env python3
"""Pytest tests verifying the database repair script fixed all issues."""

import sqlite3
import pytest
import os
import subprocess


DB_PATH = '/app/analytics.db'
INITIAL_PATH = '/app/analytics.db.initial'
REPAIR_SQL = '/app/repair.sql'


@pytest.fixture(scope='session', autouse=True)
def apply_repair():
    """Restore DB from initial broken state and apply the repair script."""
    assert os.path.exists(INITIAL_PATH), \
        f"Initial state not found at {INITIAL_PATH}"
    assert os.path.exists(REPAIR_SQL), \
        f"Repair script not found at {REPAIR_SQL}"

    # Restore to initial broken state (original bugs + DBA damage)
    subprocess.run(['cp', INITIAL_PATH, DB_PATH], check=True)

    result = subprocess.run(
        ['sqlite3', DB_PATH],
        input=f'.read {REPAIR_SQL}\n',
        capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.fail(f"repair.sql failed:\n{result.stderr}")
    yield


@pytest.fixture
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


# ======================================================================
# Issue 1: monthly_revenue view
# ======================================================================

class TestMonthlyRevenue:

    def test_view_exists(self, db):
        """monthly_revenue must exist."""
        row = db.execute('''
            SELECT COUNT(*) FROM sqlite_master
            WHERE name = 'monthly_revenue'
        ''').fetchone()[0]
        assert row >= 1, "monthly_revenue does not exist"

    def test_revenue_per_product_matches_order_items(self, db):
        """Each (month, product_id) total_revenue must match actual
        SUM(quantity * unit_price) from order_items for that product/month."""
        rows = db.execute(
            "SELECT month, product_id, total_revenue FROM monthly_revenue"
        ).fetchall()
        assert len(rows) > 0, "monthly_revenue returned no rows"
        mismatches = []
        for month, pid, view_rev in rows:
            actual = db.execute('''
                SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0)
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                WHERE oi.product_id = ?
                  AND strftime('%Y-%m', o.order_date) = ?
            ''', (pid, month)).fetchone()[0]
            if abs(view_rev - actual) > 0.01:
                mismatches.append(
                    f"Month {month}, product {pid}: "
                    f"view={view_rev:.2f}, actual={actual:.2f}")
        assert len(mismatches) == 0, \
            f"{len(mismatches)} revenue mismatches:\n" + \
            "\n".join(mismatches[:5])

    def test_no_duplicate_month_product_pairs(self, db):
        """No duplicate (month, product_id) pairs."""
        dups = db.execute('''
            SELECT COUNT(*) FROM (
                SELECT month, product_id FROM monthly_revenue
                GROUP BY month, product_id HAVING COUNT(*) > 1
            )
        ''').fetchone()[0]
        assert dups == 0, f"Found {dups} duplicate (month, product) pairs"

    def test_multiple_products_per_month(self, db):
        """At least some months must show multiple products — confirms the
        view is grouped by (month, product) not just month."""
        multi = db.execute('''
            SELECT COUNT(*) FROM (
                SELECT month FROM monthly_revenue
                GROUP BY month HAVING COUNT(*) > 1
            )
        ''').fetchone()[0]
        assert multi > 0, \
            "Every month shows only 1 product — " \
            "view likely still has an aggregate grouping bug"

    def test_total_revenue_covers_all_items(self, db):
        """Sum of all view revenue should equal sum of all order_items."""
        view_total = db.execute(
            "SELECT COALESCE(SUM(total_revenue), 0) FROM monthly_revenue"
        ).fetchone()[0]
        actual_total = db.execute(
            "SELECT COALESCE(SUM(quantity * unit_price), 0) FROM order_items oi "
            "JOIN orders o ON oi.order_id = o.id "
            "JOIN products p ON oi.product_id = p.id"
        ).fetchone()[0]
        assert abs(view_total - actual_total) < 0.01, \
            f"View total={view_total:.2f}, actual={actual_total:.2f}"


# ======================================================================
# Issue 2: Category hierarchy
# ======================================================================

class TestCategoryHierarchy:

    def test_all_categories_reachable_from_roots(self, db):
        """Every category must be reachable via parent-child traversal
        from root nodes (parent_id IS NULL)."""
        reachable = db.execute('''
            WITH RECURSIVE r(id) AS (
                SELECT id FROM categories WHERE parent_id IS NULL
                UNION ALL
                SELECT c.id FROM categories c
                JOIN r ON c.parent_id = r.id
            )
            SELECT COUNT(DISTINCT id) FROM r
        ''').fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM categories').fetchone()[0]
        assert reachable == total, \
            f"Only {reachable}/{total} categories reachable from roots"

    def test_category_count_preserved(self, db):
        """All 20 categories must still exist."""
        count = db.execute('SELECT COUNT(*) FROM categories').fetchone()[0]
        assert count == 20, f"Expected 20 categories, found {count}"

    def test_no_self_referencing_categories(self, db):
        """No category should be its own parent."""
        bad = db.execute(
            'SELECT COUNT(*) FROM categories WHERE id = parent_id'
        ).fetchone()[0]
        assert bad == 0, f"{bad} categories are their own parent"

    def test_no_cycles_in_hierarchy(self, db):
        """Walk parent chain from each node — must reach a root (NULL)
        within 20 steps (depth of tree)."""
        cats = db.execute(
            "SELECT id, parent_id FROM categories"
        ).fetchall()
        cat_dict = {r[0]: r[1] for r in cats}
        for start_id in cat_dict:
            visited = set()
            node = start_id
            steps = 0
            while node is not None and steps < 25:
                if node in visited:
                    pytest.fail(
                        f"Cycle detected starting from category {start_id}: "
                        f"revisited {node}")
                visited.add(node)
                node = cat_dict.get(node)
                steps += 1
            assert steps < 25, \
                f"Category {start_id} parent chain exceeds 25 steps (likely cycle)"


# ======================================================================
# Issue 3: product_best_review view
# ======================================================================

class TestProductBestReview:

    def test_view_exists(self, db):
        """product_best_review must exist as a view."""
        row = db.execute('''
            SELECT COUNT(*) FROM sqlite_master
            WHERE name = 'product_best_review'
        ''').fetchone()[0]
        assert row >= 1, "product_best_review does not exist"

    def test_best_rating_is_actual_max(self, db):
        """best_rating must equal MAX(rating) for each product."""
        rows = db.execute('''
            SELECT v.product_id, v.best_rating,
                   (SELECT MAX(r.rating) FROM reviews r
                    WHERE r.product_id = v.product_id) AS actual_max
            FROM product_best_review v
        ''').fetchall()
        assert len(rows) > 0, "product_best_review returned no rows"
        for pid, view_max, actual_max in rows:
            assert view_max == actual_max, \
                f"Product {pid}: view best_rating={view_max}, " \
                f"actual MAX={actual_max}"

    def test_review_details_match_best_rating(self, db):
        """reviewer_id and review_date must correspond to a review whose
        rating equals best_rating for that product."""
        rows = db.execute('''
            SELECT product_id, best_rating, reviewer_id, review_date
            FROM product_best_review
        ''').fetchall()
        mismatches = []
        for pid, best_rating, reviewer_id, review_date in rows:
            actual = db.execute('''
                SELECT rating FROM reviews
                WHERE product_id = ? AND user_id = ? AND created_at = ?
            ''', (pid, reviewer_id, review_date)).fetchone()
            if actual is None or actual[0] != best_rating:
                actual_rating = actual[0] if actual else 'NOT FOUND'
                mismatches.append(
                    f"product {pid}: best_rating={best_rating}, "
                    f"reviewer {reviewer_id} at {review_date} "
                    f"actually gave {actual_rating}")
        assert len(mismatches) == 0, \
            f"{len(mismatches)} products have wrong review details:\n" + \
            "\n".join(mismatches[:5])

    def test_best_comment_matches_reviewer(self, db):
        """best_comment must be the comment from the same review row."""
        rows = db.execute('''
            SELECT product_id, best_comment, reviewer_id, review_date
            FROM product_best_review
        ''').fetchall()
        for pid, comment, reviewer_id, review_date in rows:
            actual = db.execute('''
                SELECT comment FROM reviews
                WHERE product_id = ? AND user_id = ? AND created_at = ?
            ''', (pid, reviewer_id, review_date)).fetchone()
            assert actual is not None, \
                f"Product {pid}: no review found for reviewer {reviewer_id}"
            assert actual[0] == comment, \
                f"Product {pid}: comment mismatch"

    def test_all_reviewed_products_present(self, db):
        """Every product with at least one review should appear."""
        expected = db.execute(
            'SELECT COUNT(DISTINCT product_id) FROM reviews'
        ).fetchone()[0]
        actual = db.execute(
            'SELECT COUNT(*) FROM product_best_review'
        ).fetchone()[0]
        assert actual == expected, \
            f"Expected {expected} products in view, found {actual}"


# ======================================================================
# Issue 4: Foreign key violations
# ======================================================================

class TestForeignKeys:

    def test_no_fk_violations_anywhere(self, db):
        """PRAGMA foreign_key_check should return zero rows."""
        violations = db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        assert len(violations) == 0, \
            f"Found {len(violations)} FK violations: " + \
            str(violations[:10])

    def test_all_orders_joinable_with_users(self, db):
        """Every order must join with a user."""
        total = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        joined = db.execute('''
            SELECT COUNT(*) FROM orders o
            JOIN users u ON o.user_id = u.id
        ''').fetchone()[0]
        assert total == joined, \
            f"Only {joined}/{total} orders joinable with users"

    def test_all_order_items_joinable(self, db):
        """Every order_item must join with orders and products."""
        total = db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
        joined = db.execute('''
            SELECT COUNT(*) FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN products p ON oi.product_id = p.id
        ''').fetchone()[0]
        assert total == joined, \
            f"Only {joined}/{total} order_items fully joinable"

    def test_no_products_with_invalid_category(self, db):
        """No product should reference a non-existent category."""
        bad = db.execute('''
            SELECT COUNT(*) FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE c.id IS NULL
        ''').fetchone()[0]
        assert bad == 0, \
            f"{bad} products have invalid category_id"

    def test_order_count_preserved(self, db):
        count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert count == 500, f"Expected 500 orders, found {count}"

    def test_order_items_count_preserved(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM order_items"
        ).fetchone()[0]
        assert count == 600, f"Expected 600 order_items, found {count}"


# ======================================================================
# Issue 5: Mixed date formats in events
# ======================================================================

class TestDateNormalization:

    def test_all_dates_iso8601(self, db):
        """Every occurred_at must match YYYY-MM-DD HH:MM:SS."""
        non_iso = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE occurred_at NOT LIKE '____-__-__ __:__:__'
        ''').fetchone()[0]
        assert non_iso == 0, \
            f"{non_iso} events have non-ISO-8601 dates"

    def test_dates_are_parseable(self, db):
        """date(occurred_at) must not return NULL for any event."""
        invalid = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE date(occurred_at) IS NULL
        ''').fetchone()[0]
        assert invalid == 0, f"{invalid} events have un-parseable dates"

    def test_date_range_query(self, db):
        """A BETWEEN query on 2023 dates should return only 2023 rows."""
        count = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE occurred_at BETWEEN '2023-01-01 00:00:00'
                                    AND '2023-12-31 23:59:59'
        ''').fetchone()[0]
        assert count > 0, "Date range query returned 0 rows for 2023"

        wrong = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE occurred_at BETWEEN '2023-01-01 00:00:00'
                                    AND '2023-12-31 23:59:59'
              AND substr(occurred_at, 1, 4) != '2023'
        ''').fetchone()[0]
        assert wrong == 0, \
            f"Date range query included {wrong} non-2023 events"

    def test_no_epoch_millisecond_dates(self, db):
        """No 13-digit epoch-millisecond strings should remain."""
        ms_dates = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE length(occurred_at) = 13
              AND occurred_at GLOB '[0-9]*'
        ''').fetchone()[0]
        assert ms_dates == 0, \
            f"{ms_dates} events still have epoch-millisecond format"

    def test_no_unix_timestamp_dates(self, db):
        """No 10-digit Unix timestamps should remain."""
        ts_dates = db.execute('''
            SELECT COUNT(*) FROM events
            WHERE length(occurred_at) = 10
              AND occurred_at GLOB '[0-9]*'
        ''').fetchone()[0]
        assert ts_dates == 0, \
            f"{ts_dates} events still have Unix timestamp format"

    def test_event_count_preserved(self, db):
        count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1000, f"Expected 1000 events, found {count}"


# ======================================================================
# Issue 6: Corrupted sqlite_stat1
# ======================================================================

class TestQueryPlannerStats:

    def test_statistics_not_corrupted(self, db):
        """sqlite_stat1 row counts must be consistent with actual data."""
        reviews_count = db.execute(
            "SELECT COUNT(*) FROM reviews"
        ).fetchone()[0]
        stat_rows = db.execute(
            "SELECT stat FROM sqlite_stat1 WHERE tbl = 'reviews'"
        ).fetchall()
        assert len(stat_rows) > 0, \
            "No statistics for reviews table"
        for (stat,) in stat_rows:
            first_num = int(stat.split()[0])
            assert first_num > 100, \
                f"sqlite_stat1 for reviews shows {first_num} rows " \
                f"(should be ~{reviews_count})"

    def test_order_items_stats_not_corrupted(self, db):
        """order_items stats must reflect actual table size."""
        actual = db.execute(
            "SELECT COUNT(*) FROM order_items"
        ).fetchone()[0]
        stat_rows = db.execute(
            "SELECT stat FROM sqlite_stat1 WHERE tbl = 'order_items'"
        ).fetchall()
        assert len(stat_rows) > 0, \
            "No statistics for order_items table"
        for (stat,) in stat_rows:
            first_num = int(stat.split()[0])
            assert first_num > 100, \
                f"sqlite_stat1 for order_items shows {first_num} " \
                f"(should be ~{actual})"

    def test_key_tables_have_stats(self, db):
        """All key tables must have statistics."""
        tables_with_stats = {r[0] for r in db.execute(
            "SELECT DISTINCT tbl FROM sqlite_stat1"
        ).fetchall()}
        for t in ['reviews', 'orders', 'order_items', 'events']:
            assert t in tables_with_stats, \
                f"Missing statistics for table {t}"


# ======================================================================
# General integrity
# ======================================================================

class TestIntegrity:

    def test_integrity_check(self, db):
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        assert result == 'ok', f"integrity_check: {result}"

    def test_all_tables_exist(self, db):
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        for t in ('users', 'categories', 'products',
                  'orders', 'order_items', 'reviews', 'events'):
            assert t in tables, f"Missing table: {t}"

    def test_idempotency(self, db):
        """Running the repair script a second time should not break anything."""
        result = subprocess.run(
            ['sqlite3', DB_PATH],
            input=f'.read {REPAIR_SQL}\n',
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"Second run of repair.sql failed:\n{result.stderr}"
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == 'ok', \
            f"integrity_check failed after second run: {integrity}"
