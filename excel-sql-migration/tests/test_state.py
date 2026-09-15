
"""
Pytest tests verifying:
1. The corrected financial analysis SQLite database against CSV ground truth
2. The audit report correctly identifies all 10 formula errors in the buggy spec
"""

import pytest
import sqlite3
import csv
import json
import os
from datetime import date, timedelta


DB_PATH = '/app/financial_analysis.db'
DATA_DIR = '/app/data'
AUDIT_PATH = '/app/audit_report.json'


def networkdays(start_str, end_str):
    """Count weekdays (Mon-Fri) in [start, end] inclusive. No holiday exclusions."""
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def load_csv(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope='session')
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope='session')
def csv_data():
    return {
        'transactions': load_csv('transactions.csv'),
        'products': load_csv('products.csv'),
        'employees': load_csv('employees.csv'),
        'regions': load_csv('regions.csv'),
    }


@pytest.fixture(scope='session')
def audit_data():
    with open(AUDIT_PATH) as f:
        return json.load(f)


# ============================================================
# Base table structure
# ============================================================

class TestDatabaseExists:
    def test_db_file_exists(self):
        assert os.path.exists(DB_PATH), f'Database not found at {DB_PATH}'


class TestBaseTables:
    def test_transactions_count(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM transactions')
        assert cur.fetchone()['c'] == 500

    def test_products_count(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM products')
        assert cur.fetchone()['c'] == 20

    def test_employees_count(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM employees')
        assert cur.fetchone()['c'] == 10

    def test_regions_count(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM regions')
        assert cur.fetchone()['c'] == 6

    def test_transactions_columns(self, db):
        cur = db.execute('PRAGMA table_info(transactions)')
        cols = {row['name'] for row in cur.fetchall()}
        for c in ['transaction_id', 'date', 'employee_id', 'product_id',
                   'region_id', 'quantity', 'unit_price', 'discount_pct']:
            assert c in cols, f'Missing column {c} in transactions'

    def test_products_columns(self, db):
        cur = db.execute('PRAGMA table_info(products)')
        cols = {row['name'] for row in cur.fetchall()}
        for c in ['product_id', 'product_name', 'category', 'subcategory',
                   'cost_price', 'list_price', 'reorder_level', 'units_in_stock']:
            assert c in cols, f'Missing column {c} in products'


# ============================================================
# enriched_transactions view — CORRECT formulas
# ============================================================

class TestEnrichedTransactions:
    def test_row_count(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM enriched_transactions')
        assert cur.fetchone()['c'] == 500

    def test_product_name_lookup(self, db, csv_data):
        """Verify XLOOKUP for product_name against CSV data."""
        products = {p['product_id']: p for p in csv_data['products']}
        cur = db.execute('SELECT transaction_id, product_id, product_name '
                         'FROM enriched_transactions ORDER BY transaction_id LIMIT 20')
        for row in cur.fetchall():
            expected = products[row['product_id']]['product_name']
            assert row['product_name'] == expected, (
                f"T={row['transaction_id']}: expected product_name={expected}, "
                f"got {row['product_name']}")

    def test_employee_name_lookup(self, db, csv_data):
        """Verify XLOOKUP for employee_name (first + last)."""
        employees = {e['employee_id']: e for e in csv_data['employees']}
        cur = db.execute('SELECT employee_id, employee_name '
                         'FROM enriched_transactions LIMIT 20')
        for row in cur.fetchall():
            e = employees[row['employee_id']]
            expected = e['first_name'] + ' ' + e['last_name']
            assert row['employee_name'] == expected

    def test_region_name_lookup(self, db, csv_data):
        """Verify XLOOKUP for region_name."""
        regions = {r['region_id']: r for r in csv_data['regions']}
        cur = db.execute('SELECT region_id, region_name '
                         'FROM enriched_transactions LIMIT 20')
        for row in cur.fetchall():
            expected = regions[row['region_id']]['region_name']
            assert row['region_name'] == expected

    def test_revenue_calculation(self, db):
        """revenue = quantity * unit_price * (1 - discount_pct)"""
        cur = db.execute('SELECT quantity, unit_price, discount_pct, revenue '
                         'FROM enriched_transactions')
        for row in cur.fetchall():
            expected = row['quantity'] * row['unit_price'] * (1 - row['discount_pct'])
            assert abs(row['revenue'] - expected) < 0.01, (
                f"Revenue mismatch: {row['revenue']} != {expected}")

    def test_cost_calculation(self, db, csv_data):
        """cost = quantity * cost_price (looked up from products)"""
        products = {p['product_id']: p for p in csv_data['products']}
        cur = db.execute('SELECT product_id, quantity, cost '
                         'FROM enriched_transactions')
        for row in cur.fetchall():
            cp = float(products[row['product_id']]['cost_price'])
            expected = row['quantity'] * cp
            assert abs(row['cost'] - expected) < 0.01

    def test_profit_calculation(self, db):
        """profit = revenue - cost"""
        cur = db.execute('SELECT revenue, cost, profit FROM enriched_transactions')
        for row in cur.fetchall():
            assert abs(row['profit'] - (row['revenue'] - row['cost'])) < 0.01

    def test_tax_amount_uses_discounted_revenue(self, db, csv_data):
        """CORRECT: tax_amount = revenue * tax_rate (post-discount, NOT pre-discount)"""
        regions = {r['region_id']: r for r in csv_data['regions']}
        cur = db.execute('SELECT region_id, revenue, tax_amount '
                         'FROM enriched_transactions')
        for row in cur.fetchall():
            rate = float(regions[row['region_id']]['tax_rate'])
            expected = row['revenue'] * rate
            assert abs(row['tax_amount'] - expected) < 0.01, (
                f"tax_amount should be revenue*rate={expected}, got {row['tax_amount']}")

    def test_net_revenue(self, db):
        """net_revenue = revenue - tax_amount"""
        cur = db.execute('SELECT revenue, tax_amount, net_revenue '
                         'FROM enriched_transactions')
        for row in cur.fetchall():
            expected = row['revenue'] - row['tax_amount']
            assert abs(row['net_revenue'] - expected) < 0.01

    def test_profit_margin_uses_revenue_denominator(self, db):
        """CORRECT: profit_margin = profit / revenue (NOT profit / cost)"""
        cur = db.execute('SELECT revenue, profit, profit_margin '
                         'FROM enriched_transactions')
        for row in cur.fetchall():
            if row['revenue'] == 0:
                assert row['profit_margin'] == 0
            else:
                expected = row['profit'] / row['revenue']
                assert abs(row['profit_margin'] - expected) < 0.0001, (
                    f"profit_margin should be profit/revenue={expected:.4f}, "
                    f"got {row['profit_margin']:.4f}")

    def test_order_size_tier_correct_thresholds(self, db):
        """CORRECT: >=15 Large, >=8 Medium, >=3 Small, else Micro (NOT 20/10/5)"""
        cur = db.execute('SELECT quantity, order_size_tier FROM enriched_transactions')
        for row in cur.fetchall():
            q = row['quantity']
            tier = row['order_size_tier']
            if q >= 15:
                assert tier == 'Large', f'qty={q} should be Large, got {tier}'
            elif q >= 8:
                assert tier == 'Medium', f'qty={q} should be Medium, got {tier}'
            elif q >= 3:
                assert tier == 'Small', f'qty={q} should be Small, got {tier}'
            else:
                assert tier == 'Micro', f'qty={q} should be Micro, got {tier}'


# ============================================================
# region_category_summary view
# ============================================================

class TestRegionCategorySummary:
    def test_view_exists_and_nonempty(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM region_category_summary')
        assert cur.fetchone()['c'] > 0

    def test_total_revenue_matches_enriched(self, db):
        s1 = db.execute('SELECT SUM(total_revenue) AS s FROM region_category_summary').fetchone()['s']
        s2 = db.execute('SELECT SUM(revenue) AS s FROM enriched_transactions').fetchone()['s']
        assert abs(s1 - s2) < 0.01

    def test_total_cost_matches_enriched(self, db):
        s1 = db.execute('SELECT SUM(total_cost) AS s FROM region_category_summary').fetchone()['s']
        s2 = db.execute('SELECT SUM(cost) AS s FROM enriched_transactions').fetchone()['s']
        assert abs(s1 - s2) < 0.01

    def test_transaction_count_matches(self, db):
        s1 = db.execute('SELECT SUM(transaction_count) AS s FROM region_category_summary').fetchone()['s']
        assert s1 == 500

    def test_specific_aggregation(self, db, csv_data):
        """Verify SUMIFS/COUNTIFS for a specific (region, category) pair."""
        products = {p['product_id']: p for p in csv_data['products']}
        regions = {r['region_id']: r for r in csv_data['regions']}
        target_region = 'Northeast'
        target_category = 'Electronics'
        revenues = []
        for t in csv_data['transactions']:
            p = products[t['product_id']]
            r = regions[t['region_id']]
            if r['region_name'] == target_region and p['category'] == target_category:
                rev = int(t['quantity']) * float(t['unit_price']) * (1 - float(t['discount_pct']))
                revenues.append(rev)
        if not revenues:
            pytest.skip('No matching transactions for Northeast+Electronics')
        expected_total = sum(revenues)
        expected_count = len(revenues)
        row = db.execute(
            'SELECT total_revenue, transaction_count FROM region_category_summary '
            "WHERE region_name = ? AND category = ?",
            (target_region, target_category)
        ).fetchone()
        assert row is not None, f'No row for {target_region}+{target_category}'
        assert abs(row['total_revenue'] - expected_total) < 0.01
        assert row['transaction_count'] == expected_count

    def test_max_min_order(self, db):
        cur = db.execute('SELECT region_name, category, max_order_value, '
                         'avg_order_value, min_order_value '
                         'FROM region_category_summary')
        for row in cur.fetchall():
            assert row['max_order_value'] >= row['avg_order_value'] - 0.01
            assert row['avg_order_value'] >= row['min_order_value'] - 0.01

    def test_profit_margin(self, db):
        cur = db.execute('SELECT total_revenue, total_profit, profit_margin '
                         'FROM region_category_summary')
        for row in cur.fetchall():
            if row['total_revenue'] > 0:
                expected = row['total_profit'] / row['total_revenue']
                assert abs(row['profit_margin'] - expected) < 0.0001

    def test_weighted_avg_discount_is_revenue_weighted(self, db, csv_data):
        """CORRECT: weighted_avg_discount = SUM(discount_pct * revenue) / SUM(revenue),
        NOT simple AVG(discount_pct)."""
        products = {p['product_id']: p for p in csv_data['products']}
        regions = {r['region_id']: r for r in csv_data['regions']}

        groups = {}  # (region_name, category) -> list of (revenue, discount_pct)
        for t in csv_data['transactions']:
            p = products[t['product_id']]
            r = regions[t['region_id']]
            key = (r['region_name'], p['category'])
            rev = int(t['quantity']) * float(t['unit_price']) * (1 - float(t['discount_pct']))
            disc = float(t['discount_pct'])
            if key not in groups:
                groups[key] = []
            groups[key].append((rev, disc))

        cur = db.execute('SELECT region_name, category, weighted_avg_discount '
                         'FROM region_category_summary')
        for row in cur.fetchall():
            key = (row['region_name'], row['category'])
            entries = groups.get(key, [])
            total_rev = sum(r for r, d in entries)
            if total_rev == 0:
                expected = 0.0
            else:
                expected = sum(r * d for r, d in entries) / total_rev
            assert abs(row['weighted_avg_discount'] - expected) < 0.0001, (
                f"{key}: weighted_avg_discount should be {expected:.6f}, "
                f"got {row['weighted_avg_discount']:.6f}")

    def test_weighted_avg_discount_differs_from_simple_avg(self, db):
        """Verify the weighted average is not identical to simple average for at least
        some groups — this ensures the test catches the common error."""
        cur = db.execute(
            'SELECT region_name, category, weighted_avg_discount '
            'FROM region_category_summary')
        db_vals = {(r['region_name'], r['category']): r['weighted_avg_discount']
                   for r in cur.fetchall()}

        # Compute simple averages from enriched_transactions
        cur2 = db.execute(
            'SELECT region_name, category, AVG(discount_pct) AS simple_avg '
            'FROM enriched_transactions GROUP BY region_name, category')
        differs = 0
        for r in cur2.fetchall():
            key = (r['region_name'], r['category'])
            if key in db_vals and abs(db_vals[key] - r['simple_avg']) > 0.0001:
                differs += 1
        assert differs > 0, (
            'weighted_avg_discount appears identical to simple AVG in all groups — '
            'likely using wrong formula')


# ============================================================
# employee_performance view
# ============================================================

class TestEmployeePerformance:
    def test_row_count(self, db):
        """All 10 employees must appear (LEFT JOIN semantics)."""
        cur = db.execute('SELECT COUNT(*) AS c FROM employee_performance')
        assert cur.fetchone()['c'] == 10

    def test_employee_names(self, db, csv_data):
        for e in csv_data['employees']:
            expected_name = e['first_name'] + ' ' + e['last_name']
            row = db.execute(
                'SELECT employee_name FROM employee_performance WHERE employee_id = ?',
                (e['employee_id'],)
            ).fetchone()
            assert row is not None, f"Employee {e['employee_id']} missing"
            assert row['employee_name'] == expected_name

    def test_networkdays_inclusive_both_endpoints(self, db):
        """CORRECT: NETWORKDAYS(hire_date, '2024-12-31') inclusive on BOTH ends."""
        cur = db.execute('SELECT employee_id, hire_date, days_employed '
                         'FROM employee_performance')
        for row in cur.fetchall():
            expected = networkdays(row['hire_date'], '2024-12-31')
            assert row['days_employed'] == expected, (
                f"Employee {row['employee_id']}: NETWORKDAYS expected {expected}, "
                f"got {row['days_employed']} (hire_date={row['hire_date']})")

    def test_total_revenue_per_employee(self, db, csv_data):
        emp_revenue = {}
        for t in csv_data['transactions']:
            eid = t['employee_id']
            rev = int(t['quantity']) * float(t['unit_price']) * (1 - float(t['discount_pct']))
            emp_revenue[eid] = emp_revenue.get(eid, 0.0) + rev
        cur = db.execute('SELECT employee_id, total_revenue FROM employee_performance')
        for row in cur.fetchall():
            expected = emp_revenue.get(row['employee_id'], 0.0)
            assert abs(row['total_revenue'] - expected) < 0.01

    def test_commission_earned(self, db, csv_data):
        employees = {e['employee_id']: e for e in csv_data['employees']}
        cur = db.execute('SELECT employee_id, total_revenue, commission_rate, '
                         'commission_earned FROM employee_performance')
        for row in cur.fetchall():
            assert abs(row['commission_rate'] - float(
                employees[row['employee_id']]['commission_rate'])) < 0.001
            expected = row['total_revenue'] * row['commission_rate']
            assert abs(row['commission_earned'] - expected) < 0.01

    def test_total_compensation(self, db, csv_data):
        employees = {e['employee_id']: e for e in csv_data['employees']}
        cur = db.execute('SELECT employee_id, commission_earned, total_compensation '
                         'FROM employee_performance')
        for row in cur.fetchall():
            base = float(employees[row['employee_id']]['base_salary'])
            expected = base + row['commission_earned']
            assert abs(row['total_compensation'] - expected) < 0.01

    def test_performance_tier_correct_thresholds(self, db):
        """CORRECT: Gold >= 200000 (NOT 250000)"""
        cur = db.execute('SELECT total_revenue, performance_tier '
                         'FROM employee_performance')
        for row in cur.fetchall():
            rev = row['total_revenue']
            tier = row['performance_tier']
            if rev >= 500000:
                assert tier == 'Platinum', f'rev={rev} should be Platinum'
            elif rev >= 200000:
                assert tier == 'Gold', f'rev={rev} should be Gold'
            elif rev >= 100000:
                assert tier == 'Silver', f'rev={rev} should be Silver'
            else:
                assert tier == 'Bronze', f'rev={rev} should be Bronze'

    def test_revenue_per_day(self, db):
        cur = db.execute('SELECT total_revenue, days_employed, revenue_per_day '
                         'FROM employee_performance')
        for row in cur.fetchall():
            if row['days_employed'] > 0:
                expected = row['total_revenue'] / row['days_employed']
                assert abs(row['revenue_per_day'] - expected) < 0.01

    def test_total_revenue_matches_enriched(self, db):
        s1 = db.execute('SELECT SUM(total_revenue) AS s '
                        'FROM employee_performance').fetchone()['s']
        s2 = db.execute('SELECT SUM(revenue) AS s '
                        'FROM enriched_transactions').fetchone()['s']
        assert abs(s1 - s2) < 0.01


# ============================================================
# inventory_status view
# ============================================================

class TestInventoryStatus:
    def test_row_count(self, db):
        """All 20 products must appear (LEFT JOIN semantics)."""
        cur = db.execute('SELECT COUNT(*) AS c FROM inventory_status')
        assert cur.fetchone()['c'] == 20

    def test_total_units_sold(self, db, csv_data):
        sold = {}
        for t in csv_data['transactions']:
            pid = t['product_id']
            sold[pid] = sold.get(pid, 0) + int(t['quantity'])
        cur = db.execute('SELECT product_id, total_units_sold FROM inventory_status')
        for row in cur.fetchall():
            expected = sold.get(row['product_id'], 0)
            assert row['total_units_sold'] == expected

    def test_remaining_stock(self, db, csv_data):
        products = {p['product_id']: p for p in csv_data['products']}
        sold = {}
        for t in csv_data['transactions']:
            pid = t['product_id']
            sold[pid] = sold.get(pid, 0) + int(t['quantity'])
        cur = db.execute('SELECT product_id, remaining_stock FROM inventory_status')
        for row in cur.fetchall():
            stock = int(products[row['product_id']]['units_in_stock'])
            expected = stock - sold.get(row['product_id'], 0)
            assert row['remaining_stock'] == expected

    def test_needs_reorder_strict_less_than(self, db):
        """CORRECT: IF(remaining_stock < reorder_level, 'Yes', 'No') — strict <, NOT <="""
        cur = db.execute('SELECT remaining_stock, reorder_level, needs_reorder '
                         'FROM inventory_status')
        for row in cur.fetchall():
            expected = 'Yes' if row['remaining_stock'] < row['reorder_level'] else 'No'
            assert row['needs_reorder'] == expected, (
                f"remaining={row['remaining_stock']}, reorder={row['reorder_level']}: "
                f"expected {expected}, got {row['needs_reorder']}")

    def test_stock_status_correct_multiplier(self, db):
        """CORRECT: Adequate when < reorder_level * 2 (NOT * 3)"""
        cur = db.execute('SELECT product_id, remaining_stock, reorder_level, '
                         'stock_status FROM inventory_status')
        for row in cur.fetchall():
            r = row['remaining_stock']
            rl = row['reorder_level']
            if r <= 0:
                expected = 'Out of Stock'
            elif r < rl:
                expected = 'Low Stock'
            elif r < rl * 2:
                expected = 'Adequate'
            else:
                expected = 'Well Stocked'
            assert row['stock_status'] == expected, (
                f"Product {row['product_id']}: remaining={r}, reorder={rl}, "
                f"expected '{expected}', got '{row['stock_status']}'")

    def test_total_revenue_per_product(self, db, csv_data):
        rev = {}
        for t in csv_data['transactions']:
            pid = t['product_id']
            r = int(t['quantity']) * float(t['unit_price']) * (1 - float(t['discount_pct']))
            rev[pid] = rev.get(pid, 0.0) + r
        cur = db.execute('SELECT product_id, total_revenue FROM inventory_status')
        for row in cur.fetchall():
            expected = rev.get(row['product_id'], 0.0)
            assert abs(row['total_revenue'] - expected) < 0.01


# ============================================================
# quarterly_revenue view
# ============================================================

class TestQuarterlyRevenue:
    def test_view_nonempty(self, db):
        cur = db.execute('SELECT COUNT(*) AS c FROM quarterly_revenue')
        assert cur.fetchone()['c'] > 0

    def test_valid_quarters(self, db):
        cur = db.execute('SELECT DISTINCT quarter FROM quarterly_revenue')
        for row in cur.fetchall():
            assert row['quarter'] in (1, 2, 3, 4), f"Invalid quarter: {row['quarter']}"

    def test_valid_years(self, db):
        cur = db.execute('SELECT DISTINCT year FROM quarterly_revenue')
        for row in cur.fetchall():
            assert row['year'] in (2023, 2024), f"Unexpected year: {row['year']}"

    def test_revenue_totals_match_enriched(self, db):
        s1 = db.execute('SELECT SUM(total_revenue) AS s FROM quarterly_revenue').fetchone()['s']
        s2 = db.execute('SELECT SUM(revenue) AS s FROM enriched_transactions').fetchone()['s']
        assert abs(s1 - s2) < 0.01

    def test_profit_totals_match_enriched(self, db):
        s1 = db.execute('SELECT SUM(total_profit) AS s FROM quarterly_revenue').fetchone()['s']
        s2 = db.execute('SELECT SUM(profit) AS s FROM enriched_transactions').fetchone()['s']
        assert abs(s1 - s2) < 0.01

    def test_transaction_count_total(self, db):
        s = db.execute('SELECT SUM(transaction_count) AS s FROM quarterly_revenue').fetchone()['s']
        assert s == 500

    def test_top_category_valid(self, db):
        valid = {'Electronics', 'Office Supplies', 'Furniture', 'Software'}
        cur = db.execute('SELECT top_category FROM quarterly_revenue')
        for row in cur.fetchall():
            assert row['top_category'] in valid, f"Invalid category: {row['top_category']}"

    def test_top_category_is_max_revenue(self, db):
        """CORRECT: top_category by highest SUM(revenue), NOT COUNT."""
        cur = db.execute(
            'SELECT year, quarter, top_category FROM quarterly_revenue')
        for row in cur.fetchall():
            cats = db.execute(
                'SELECT category, SUM(revenue) AS cat_rev '
                'FROM enriched_transactions '
                'WHERE CAST(strftime(\'%Y\', transaction_date) AS INTEGER) = ? '
                'AND CASE '
                '  WHEN CAST(strftime(\'%m\', transaction_date) AS INTEGER) <= 3 THEN 1 '
                '  WHEN CAST(strftime(\'%m\', transaction_date) AS INTEGER) <= 6 THEN 2 '
                '  WHEN CAST(strftime(\'%m\', transaction_date) AS INTEGER) <= 9 THEN 3 '
                '  ELSE 4 END = ? '
                'GROUP BY category ORDER BY cat_rev DESC',
                (row['year'], row['quarter'])
            ).fetchall()
            max_rev = cats[0]['cat_rev']
            top_cats = {c['category'] for c in cats if abs(c['cat_rev'] - max_rev) < 0.01}
            assert row['top_category'] in top_cats, (
                f"Q{row['quarter']}/{row['year']}: top_category={row['top_category']} "
                f"not in {top_cats}")

    def test_qoq_growth_rate_first_quarter_is_null(self, db):
        """First quarter in dataset should have NULL growth rate."""
        row = db.execute(
            'SELECT qoq_growth_rate FROM quarterly_revenue '
            'ORDER BY year, quarter LIMIT 1'
        ).fetchone()
        assert row['qoq_growth_rate'] is None, (
            f"First quarter should have NULL growth rate, got {row['qoq_growth_rate']}")

    def test_qoq_growth_rate_uses_prior_denominator(self, db):
        """CORRECT: growth = (current - prior) / prior * 100 (NOT / current * 100)"""
        rows = db.execute(
            'SELECT year, quarter, total_revenue, qoq_growth_rate '
            'FROM quarterly_revenue ORDER BY year, quarter'
        ).fetchall()
        for i in range(1, len(rows)):
            prev_rev = rows[i - 1]['total_revenue']
            curr_rev = rows[i]['total_revenue']
            expected = (curr_rev - prev_rev) * 100.0 / prev_rev
            actual = rows[i]['qoq_growth_rate']
            assert actual is not None, (
                f"Q{rows[i]['quarter']}/{rows[i]['year']}: growth rate should not be NULL")
            assert abs(actual - expected) < 0.01, (
                f"Q{rows[i]['quarter']}/{rows[i]['year']}: qoq_growth_rate should be "
                f"{expected:.2f} (using prior as denominator), got {actual:.2f}")

    def test_qoq_growth_rate_not_using_current_denominator(self, db):
        """Verify growth rate is NOT computed as (current - prior) / current * 100."""
        rows = db.execute(
            'SELECT year, quarter, total_revenue, qoq_growth_rate '
            'FROM quarterly_revenue ORDER BY year, quarter'
        ).fetchall()
        wrong_count = 0
        correct_count = 0
        for i in range(1, len(rows)):
            prev_rev = rows[i - 1]['total_revenue']
            curr_rev = rows[i]['total_revenue']
            if abs(prev_rev - curr_rev) < 0.01:
                continue  # Skip when equal — both formulas give same result
            wrong_val = (curr_rev - prev_rev) * 100.0 / curr_rev
            correct_val = (curr_rev - prev_rev) * 100.0 / prev_rev
            actual = rows[i]['qoq_growth_rate']
            if actual is not None:
                if abs(actual - wrong_val) < 0.01:
                    wrong_count += 1
                if abs(actual - correct_val) < 0.01:
                    correct_count += 1
        assert wrong_count == 0 or correct_count > wrong_count, (
            'qoq_growth_rate appears to use current quarter as denominator '
            'instead of prior quarter')


# ============================================================
# Cross-view consistency
# ============================================================

class TestCrossViewConsistency:
    def test_revenue_all_views(self, db):
        enriched = db.execute(
            'SELECT SUM(revenue) AS s FROM enriched_transactions').fetchone()['s']
        rcs = db.execute(
            'SELECT SUM(total_revenue) AS s FROM region_category_summary').fetchone()['s']
        emp = db.execute(
            'SELECT SUM(total_revenue) AS s FROM employee_performance').fetchone()['s']
        qtr = db.execute(
            'SELECT SUM(total_revenue) AS s FROM quarterly_revenue').fetchone()['s']
        inv = db.execute(
            'SELECT SUM(total_revenue) AS s FROM inventory_status').fetchone()['s']
        assert abs(enriched - rcs) < 0.01, f'enriched({enriched}) != rcs({rcs})'
        assert abs(enriched - emp) < 0.01, f'enriched({enriched}) != emp({emp})'
        assert abs(enriched - qtr) < 0.01, f'enriched({enriched}) != qtr({qtr})'
        assert abs(enriched - inv) < 0.01, f'enriched({enriched}) != inv({inv})'

    def test_cost_consistency(self, db):
        enriched = db.execute(
            'SELECT SUM(cost) AS s FROM enriched_transactions').fetchone()['s']
        rcs = db.execute(
            'SELECT SUM(total_cost) AS s FROM region_category_summary').fetchone()['s']
        assert abs(enriched - rcs) < 0.01

    def test_transaction_count_consistency(self, db):
        rcs = db.execute(
            'SELECT SUM(transaction_count) AS s FROM region_category_summary').fetchone()['s']
        emp = db.execute(
            'SELECT SUM(total_transactions) AS s FROM employee_performance').fetchone()['s']
        qtr = db.execute(
            'SELECT SUM(transaction_count) AS s FROM quarterly_revenue').fetchone()['s']
        assert rcs == 500
        assert emp == 500
        assert qtr == 500


# ============================================================
# Audit report — must identify all 10 root-cause formula errors
# ============================================================

class TestAuditReport:
    EXPECTED_ERRORS = [
        ('enriched_transactions', 'profit_margin'),
        ('enriched_transactions', 'order_size_tier'),
        ('enriched_transactions', 'tax_amount'),
        ('inventory_status', 'needs_reorder'),
        ('employee_performance', 'days_employed'),
        ('employee_performance', 'performance_tier'),
        ('inventory_status', 'stock_status'),
        ('quarterly_revenue', 'top_category'),
        ('region_category_summary', 'weighted_avg_discount'),
        ('quarterly_revenue', 'qoq_growth_rate'),
    ]

    def test_file_exists(self):
        assert os.path.exists(AUDIT_PATH), f'Audit report not found at {AUDIT_PATH}'

    def test_valid_json_structure(self, audit_data):
        assert 'formula_errors' in audit_data, 'Missing formula_errors key'
        assert isinstance(audit_data['formula_errors'], list)

    def test_minimum_error_count(self, audit_data):
        assert len(audit_data['formula_errors']) >= 10, (
            f"Expected at least 10 errors, found {len(audit_data['formula_errors'])}")

    def test_entries_have_required_fields(self, audit_data):
        for entry in audit_data['formula_errors']:
            assert 'view_name' in entry, f'Missing view_name in entry: {entry}'
            assert 'column_name' in entry, f'Missing column_name in entry: {entry}'
            assert 'error_description' in entry, f'Missing error_description in entry: {entry}'
            assert len(entry['error_description']) > 0, 'error_description must not be empty'

    @pytest.mark.parametrize('view_name,column_name', EXPECTED_ERRORS)
    def test_identifies_error(self, audit_data, view_name, column_name):
        """Each of the 10 root-cause formula errors must be identified."""
        found = any(
            e.get('view_name') == view_name and e.get('column_name') == column_name
            for e in audit_data['formula_errors']
        )
        assert found, (
            f"Audit report must identify error in {view_name}.{column_name}")
