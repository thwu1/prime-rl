#!/usr/bin/env python3

"""
Generate the audit report by:
1. Building a buggy database using the workbook_spec.json formulas exactly
2. Comparing it against the correct financial_analysis.db
3. Identifying root-cause formula errors (not cascading symptoms)
4. Writing /app/audit_report.json
"""

import sqlite3
import csv
import json
import os
from datetime import date, timedelta

CORRECT_DB = '/app/financial_analysis.db'
BUGGY_DB = '/tmp/buggy_analysis.db'
DATA_DIR = '/app/data'
SPEC_PATH = '/app/workbook_spec.json'
RULES_PATH = '/app/business_rules.json'
AUDIT_PATH = '/app/audit_report.json'


def load_csv(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return list(csv.DictReader(f))


def build_buggy_database():
    """Build a database using the BUGGY workbook_spec.json formulas exactly."""
    if os.path.exists(BUGGY_DB):
        os.remove(BUGGY_DB)

    conn = sqlite3.connect(BUGGY_DB)
    conn.execute('PRAGMA foreign_keys = ON')
    cur = conn.cursor()

    # Same base tables
    cur.execute('''CREATE TABLE products (
        product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL,
        category TEXT NOT NULL, subcategory TEXT NOT NULL,
        cost_price REAL NOT NULL, list_price REAL NOT NULL,
        reorder_level INTEGER NOT NULL, units_in_stock INTEGER NOT NULL)''')

    cur.execute('''CREATE TABLE employees (
        employee_id TEXT PRIMARY KEY, first_name TEXT NOT NULL,
        last_name TEXT NOT NULL, department TEXT NOT NULL,
        hire_date TEXT NOT NULL, base_salary REAL NOT NULL,
        commission_rate REAL NOT NULL, manager_id TEXT)''')

    cur.execute('''CREATE TABLE regions (
        region_id TEXT PRIMARY KEY, region_name TEXT NOT NULL,
        country TEXT NOT NULL, sales_target REAL NOT NULL,
        tax_rate REAL NOT NULL)''')

    cur.execute('''CREATE TABLE transactions (
        transaction_id TEXT PRIMARY KEY, date TEXT NOT NULL,
        employee_id TEXT NOT NULL, product_id TEXT NOT NULL,
        region_id TEXT NOT NULL, quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL, discount_pct REAL NOT NULL)''')

    # Load same data
    for row in load_csv('products.csv'):
        cur.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?)',
            (row['product_id'], row['product_name'], row['category'],
             row['subcategory'], float(row['cost_price']),
             float(row['list_price']), int(row['reorder_level']),
             int(row['units_in_stock'])))

    emp_rows = load_csv('employees.csv')
    emp_rows.sort(key=lambda r: (0 if not r['manager_id'] else 1))
    for row in emp_rows:
        mgr = row['manager_id'] if row['manager_id'] else None
        cur.execute('INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)',
            (row['employee_id'], row['first_name'], row['last_name'],
             row['department'], row['hire_date'],
             float(row['base_salary']), float(row['commission_rate']), mgr))

    for row in load_csv('regions.csv'):
        cur.execute('INSERT INTO regions VALUES (?,?,?,?,?)',
            (row['region_id'], row['region_name'], row['country'],
             float(row['sales_target']), float(row['tax_rate'])))

    for row in load_csv('transactions.csv'):
        cur.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)',
            (row['transaction_id'], row['date'], row['employee_id'],
             row['product_id'], row['region_id'], int(row['quantity']),
             float(row['unit_price']), float(row['discount_pct'])))

    # BUGGY enriched_transactions: tax on pre-discount, profit/cost margin, wrong tiers
    cur.execute('''
        CREATE VIEW enriched_transactions AS
        SELECT
            t.transaction_id,
            t.date AS transaction_date,
            t.employee_id, t.product_id, t.region_id,
            t.quantity, t.unit_price, t.discount_pct,
            p.product_name, p.category, p.cost_price,
            e.first_name || ' ' || e.last_name AS employee_name,
            r.region_name,
            t.quantity * t.unit_price * (1.0 - t.discount_pct) AS revenue,
            t.quantity * p.cost_price AS cost,
            t.quantity * t.unit_price * (1.0 - t.discount_pct) - t.quantity * p.cost_price AS profit,
            r.tax_rate,
            t.quantity * t.unit_price * r.tax_rate AS tax_amount,
            t.quantity * t.unit_price * (1.0 - t.discount_pct)
                - t.quantity * t.unit_price * r.tax_rate AS net_revenue,
            CASE
                WHEN t.quantity * p.cost_price = 0 THEN 0.0
                ELSE (t.quantity * t.unit_price * (1.0 - t.discount_pct) - t.quantity * p.cost_price)
                     * 1.0 / (t.quantity * p.cost_price)
            END AS profit_margin,
            CASE
                WHEN t.quantity >= 20 THEN 'Large'
                WHEN t.quantity >= 10 THEN 'Medium'
                WHEN t.quantity >= 5 THEN 'Small'
                ELSE 'Micro'
            END AS order_size_tier
        FROM transactions t
        JOIN products p ON t.product_id = p.product_id
        JOIN employees e ON t.employee_id = e.employee_id
        JOIN regions r ON t.region_id = r.region_id
    ''')

    # BUGGY region_category_summary: uses simple AVG for weighted_avg_discount
    cur.execute('''
        CREATE VIEW region_category_summary AS
        SELECT region_name, category,
            SUM(revenue) AS total_revenue, SUM(cost) AS total_cost,
            SUM(revenue) - SUM(cost) AS total_profit,
            COUNT(*) AS transaction_count,
            AVG(revenue) AS avg_order_value,
            MAX(revenue) AS max_order_value,
            MIN(revenue) AS min_order_value,
            AVG(discount_pct) AS weighted_avg_discount,
            CASE WHEN SUM(revenue) = 0 THEN 0.0
                 ELSE (SUM(revenue) - SUM(cost)) * 1.0 / SUM(revenue)
            END AS profit_margin
        FROM enriched_transactions
        GROUP BY region_name, category
    ''')

    # BUGGY employee_performance: exclusive start NETWORKDAYS, wrong Gold threshold
    cur.execute('''
        CREATE VIEW employee_performance AS
        WITH emp_stats AS (
            SELECT e.employee_id,
                e.first_name || ' ' || e.last_name AS employee_name,
                e.department, e.hire_date, e.base_salary, e.commission_rate,
                COALESCE(SUM(et.revenue), 0.0) AS total_revenue,
                COUNT(et.transaction_id) AS total_transactions,
                CASE WHEN COUNT(et.transaction_id) = 0 THEN 0.0
                     ELSE SUM(et.revenue) * 1.0 / COUNT(et.transaction_id)
                END AS avg_order_value,
                (
                    (CAST(julianday('2024-12-31') AS INTEGER) + 1) / 7 * 5
                    + MIN((CAST(julianday('2024-12-31') AS INTEGER) + 1) % 7, 4)
                ) - (
                    (CAST(julianday(e.hire_date) AS INTEGER) + 1) / 7 * 5
                    + MIN((CAST(julianday(e.hire_date) AS INTEGER) + 1) % 7, 4)
                ) AS days_employed
            FROM employees e
            LEFT JOIN enriched_transactions et ON e.employee_id = et.employee_id
            GROUP BY e.employee_id
        )
        SELECT employee_id, employee_name, department, hire_date,
            total_revenue, total_transactions, avg_order_value,
            commission_rate,
            total_revenue * commission_rate AS commission_earned,
            base_salary + total_revenue * commission_rate AS total_compensation,
            days_employed,
            CASE WHEN days_employed = 0 THEN 0.0
                 ELSE total_revenue * 1.0 / days_employed
            END AS revenue_per_day,
            CASE
                WHEN total_revenue >= 500000 THEN 'Platinum'
                WHEN total_revenue >= 250000 THEN 'Gold'
                WHEN total_revenue >= 100000 THEN 'Silver'
                ELSE 'Bronze'
            END AS performance_tier
        FROM emp_stats
    ''')

    # BUGGY inventory_status: <= instead of <, *3 instead of *2
    cur.execute('''
        CREATE VIEW inventory_status AS
        WITH product_sales AS (
            SELECT p.product_id, p.product_name, p.category,
                p.units_in_stock, p.reorder_level,
                COALESCE(SUM(et.quantity), 0) AS total_units_sold,
                COALESCE(SUM(et.revenue), 0.0) AS total_revenue
            FROM products p
            LEFT JOIN enriched_transactions et ON p.product_id = et.product_id
            GROUP BY p.product_id
        )
        SELECT product_id, product_name, category,
            units_in_stock, reorder_level, total_units_sold,
            units_in_stock - total_units_sold AS remaining_stock,
            CASE WHEN units_in_stock - total_units_sold <= reorder_level THEN 'Yes'
                 ELSE 'No'
            END AS needs_reorder,
            CASE
                WHEN units_in_stock - total_units_sold <= 0 THEN 'Out of Stock'
                WHEN units_in_stock - total_units_sold < reorder_level THEN 'Low Stock'
                WHEN units_in_stock - total_units_sold < reorder_level * 3 THEN 'Adequate'
                ELSE 'Well Stocked'
            END AS stock_status,
            total_revenue,
            CASE WHEN total_units_sold = 0 THEN 0.0
                 ELSE total_revenue * 1.0 / total_units_sold
            END AS avg_selling_price
        FROM product_sales
    ''')

    # BUGGY quarterly_revenue: top_category by COUNT not SUM(revenue),
    # qoq_growth_rate divides by current quarter instead of prior quarter
    cur.execute('''
        CREATE VIEW quarterly_revenue AS
        WITH quarterly_data AS (
            SELECT
                CAST(strftime('%Y', transaction_date) AS INTEGER) AS year,
                CASE
                    WHEN CAST(strftime('%m', transaction_date) AS INTEGER) <= 3 THEN 1
                    WHEN CAST(strftime('%m', transaction_date) AS INTEGER) <= 6 THEN 2
                    WHEN CAST(strftime('%m', transaction_date) AS INTEGER) <= 9 THEN 3
                    ELSE 4
                END AS quarter,
                revenue, profit, category
            FROM enriched_transactions
        ),
        quarterly_agg AS (
            SELECT year, quarter,
                SUM(revenue) AS total_revenue,
                SUM(profit) AS total_profit,
                COUNT(*) AS transaction_count,
                AVG(revenue) AS avg_order_value
            FROM quarterly_data
            GROUP BY year, quarter
        ),
        quarterly_cat AS (
            SELECT year, quarter, category,
                COUNT(*) AS cat_metric,
                ROW_NUMBER() OVER (
                    PARTITION BY year, quarter
                    ORDER BY COUNT(*) DESC
                ) AS rn
            FROM quarterly_data
            GROUP BY year, quarter, category
        )
        SELECT qa.year, qa.quarter, qa.total_revenue, qa.total_profit,
            qa.transaction_count, qa.avg_order_value,
            qc.category AS top_category,
            CASE
                WHEN LAG(qa.total_revenue) OVER (ORDER BY qa.year, qa.quarter) IS NULL THEN NULL
                ELSE (qa.total_revenue - LAG(qa.total_revenue) OVER (ORDER BY qa.year, qa.quarter))
                     * 100.0 / qa.total_revenue
            END AS qoq_growth_rate
        FROM quarterly_agg qa
        JOIN quarterly_cat qc
            ON qa.year = qc.year AND qa.quarter = qc.quarter AND qc.rn = 1
    ''')

    conn.commit()
    conn.close()
    print(f'Buggy database built at {BUGGY_DB}')


def compare_databases():
    """Compare correct and buggy databases, trace root causes, generate audit report."""
    correct = sqlite3.connect(CORRECT_DB)
    correct.row_factory = sqlite3.Row
    buggy = sqlite3.connect(BUGGY_DB)
    buggy.row_factory = sqlite3.Row

    errors = []
    cascade_cols = set()  # Track cascading effects to exclude from root causes

    # ---- Compare enriched_transactions ----
    c_rows = correct.execute(
        'SELECT * FROM enriched_transactions ORDER BY transaction_id').fetchall()
    b_rows = buggy.execute(
        'SELECT * FROM enriched_transactions ORDER BY transaction_id').fetchall()

    et_diffs = {}
    for c, b in zip(c_rows, b_rows):
        for col in ['profit_margin', 'order_size_tier', 'tax_amount', 'net_revenue']:
            cv, bv = c[col], b[col]
            if isinstance(cv, float) and isinstance(bv, float):
                if abs(cv - bv) > 0.001:
                    et_diffs[col] = et_diffs.get(col, 0) + 1
            elif cv != bv:
                et_diffs[col] = et_diffs.get(col, 0) + 1

    # tax_amount is a root cause; net_revenue cascades from it
    if 'tax_amount' in et_diffs:
        errors.append({
            'view_name': 'enriched_transactions',
            'column_name': 'tax_amount',
            'error_description': (
                f'Spec applies tax to pre-discount amount (quantity * unit_price * tax_rate) '
                f'instead of post-discount revenue (revenue * tax_rate). '
                f'Affects {et_diffs["tax_amount"]} of 500 transactions. '
                f'This also causes net_revenue to be incorrect as a cascading effect.'
            )
        })
        cascade_cols.add(('enriched_transactions', 'net_revenue'))

    if 'profit_margin' in et_diffs:
        errors.append({
            'view_name': 'enriched_transactions',
            'column_name': 'profit_margin',
            'error_description': (
                f'Spec computes profit margin as profit/cost (markup ratio) instead of '
                f'the standard gross profit margin formula profit/revenue. '
                f'Affects {et_diffs["profit_margin"]} of 500 transactions.'
            )
        })

    if 'order_size_tier' in et_diffs:
        errors.append({
            'view_name': 'enriched_transactions',
            'column_name': 'order_size_tier',
            'error_description': (
                f'Spec uses thresholds (>=20 Large, >=10 Medium, >=5 Small) that differ '
                f'from the business rules (>=15 Large, >=8 Medium, >=3 Small). '
                f'Affects {et_diffs["order_size_tier"]} of 500 transactions.'
            )
        })

    # ---- Compare region_category_summary ----
    c_rows = correct.execute(
        'SELECT * FROM region_category_summary ORDER BY region_name, category').fetchall()
    b_rows = buggy.execute(
        'SELECT * FROM region_category_summary ORDER BY region_name, category').fetchall()

    rcs_diffs = {}
    for c, b in zip(c_rows, b_rows):
        for col in ['weighted_avg_discount']:
            cv, bv = c[col], b[col]
            if isinstance(cv, float) and isinstance(bv, float):
                if abs(cv - bv) > 0.0001:
                    rcs_diffs[col] = rcs_diffs.get(col, 0) + 1
            elif cv != bv:
                rcs_diffs[col] = rcs_diffs.get(col, 0) + 1

    if 'weighted_avg_discount' in rcs_diffs:
        errors.append({
            'view_name': 'region_category_summary',
            'column_name': 'weighted_avg_discount',
            'error_description': (
                f'Spec uses simple arithmetic mean of discount percentages (AVERAGEIFS) '
                f'instead of the revenue-weighted mean required by business rules. '
                f'The correct formula weights each transaction discount by its revenue '
                f'contribution: SUM(discount_pct * revenue) / SUM(revenue). '
                f'Affects {rcs_diffs["weighted_avg_discount"]} of {len(c_rows)} region-category groups.'
            )
        })

    # ---- Compare employee_performance ----
    c_rows = correct.execute(
        'SELECT * FROM employee_performance ORDER BY employee_id').fetchall()
    b_rows = buggy.execute(
        'SELECT * FROM employee_performance ORDER BY employee_id').fetchall()

    ep_diffs = {}
    for c, b in zip(c_rows, b_rows):
        for col in ['days_employed', 'performance_tier', 'revenue_per_day']:
            cv, bv = c[col], b[col]
            if isinstance(cv, float) and isinstance(bv, float):
                if abs(cv - bv) > 0.001:
                    ep_diffs[col] = ep_diffs.get(col, 0) + 1
            elif cv != bv:
                ep_diffs[col] = ep_diffs.get(col, 0) + 1

    # days_employed is root cause; revenue_per_day cascades
    if 'days_employed' in ep_diffs:
        errors.append({
            'view_name': 'employee_performance',
            'column_name': 'days_employed',
            'error_description': (
                f'Spec uses NETWORKDAYS(hire_date + 1, end_date) which excludes the '
                f'hire date itself. Business rules require inclusive counting on both '
                f'endpoints: NETWORKDAYS(hire_date, end_date). '
                f'Affects {ep_diffs["days_employed"]} of 10 employees.'
            )
        })
        cascade_cols.add(('employee_performance', 'revenue_per_day'))

    if 'performance_tier' in ep_diffs:
        errors.append({
            'view_name': 'employee_performance',
            'column_name': 'performance_tier',
            'error_description': (
                f'Spec uses Gold tier threshold >=250000 instead of >=200000 as '
                f'specified in the business rules compensation schedule. '
                f'Affects {ep_diffs["performance_tier"]} of 10 employees.'
            )
        })

    # ---- Compare inventory_status ----
    c_rows = correct.execute(
        'SELECT * FROM inventory_status ORDER BY product_id').fetchall()
    b_rows = buggy.execute(
        'SELECT * FROM inventory_status ORDER BY product_id').fetchall()

    is_diffs = {}
    for c, b in zip(c_rows, b_rows):
        for col in ['needs_reorder', 'stock_status']:
            if c[col] != b[col]:
                is_diffs[col] = is_diffs.get(col, 0) + 1

    if 'needs_reorder' in is_diffs:
        errors.append({
            'view_name': 'inventory_status',
            'column_name': 'needs_reorder',
            'error_description': (
                f'Spec uses <= reorder_level (inclusive) but business rules require '
                f'strictly < reorder_level (reorder triggers when stock drops BELOW '
                f'the threshold, not at it). '
                f'Affects {is_diffs["needs_reorder"]} of 20 products.'
            )
        })

    if 'stock_status' in is_diffs:
        errors.append({
            'view_name': 'inventory_status',
            'column_name': 'stock_status',
            'error_description': (
                f'Spec uses reorder_level * 3 for the Adequate/Well Stocked boundary '
                f'instead of reorder_level * 2 as specified in the business rules. '
                f'Affects {is_diffs["stock_status"]} of 20 products.'
            )
        })

    # ---- Compare quarterly_revenue ----
    c_rows = correct.execute(
        'SELECT * FROM quarterly_revenue ORDER BY year, quarter').fetchall()
    b_rows = buggy.execute(
        'SELECT * FROM quarterly_revenue ORDER BY year, quarter').fetchall()

    qr_diffs = {}
    for c, b in zip(c_rows, b_rows):
        if c['top_category'] != b['top_category']:
            qr_diffs['top_category'] = qr_diffs.get('top_category', 0) + 1
        # Compare qoq_growth_rate
        cv, bv = c['qoq_growth_rate'], b['qoq_growth_rate']
        if cv is None and bv is None:
            pass  # Both NULL — OK
        elif cv is None or bv is None:
            qr_diffs['qoq_growth_rate'] = qr_diffs.get('qoq_growth_rate', 0) + 1
        elif abs(cv - bv) > 0.01:
            qr_diffs['qoq_growth_rate'] = qr_diffs.get('qoq_growth_rate', 0) + 1

    if 'top_category' in qr_diffs:
        errors.append({
            'view_name': 'quarterly_revenue',
            'column_name': 'top_category',
            'error_description': (
                f'Spec determines top category by transaction COUNT (most frequent) '
                f'instead of highest total REVENUE as specified in business rules. '
                f'Affects {qr_diffs["top_category"]} of {len(c_rows)} quarters.'
            )
        })
    else:
        # Even if data happens to produce same results, the formula is still wrong
        with open(SPEC_PATH) as f:
            spec = json.load(f)
        tc_spec = spec['views']['quarterly_revenue']['formulas']['top_category']
        if 'COUNT' in tc_spec.upper() and 'revenue' not in tc_spec.lower():
            errors.append({
                'view_name': 'quarterly_revenue',
                'column_name': 'top_category',
                'error_description': (
                    'Spec determines top category by transaction COUNT instead of '
                    'highest total REVENUE as specified in business rules. '
                    'Current data may produce identical results, but the formula '
                    'semantics are incorrect.'
                )
            })

    if 'qoq_growth_rate' in qr_diffs:
        errors.append({
            'view_name': 'quarterly_revenue',
            'column_name': 'qoq_growth_rate',
            'error_description': (
                f'Spec computes QoQ growth rate by dividing the revenue change by '
                f'the CURRENT quarter revenue instead of the PRIOR quarter revenue. '
                f'The standard financial convention for percentage change is '
                f'(current - prior) / prior * 100, not (current - prior) / current * 100. '
                f'Affects {qr_diffs["qoq_growth_rate"]} of {len(c_rows)} quarters.'
            )
        })
    else:
        # Detect from spec text even if data doesn't diverge
        with open(SPEC_PATH) as f:
            spec = json.load(f)
        gr_spec = spec['views']['quarterly_revenue']['formulas'].get('qoq_growth_rate', '')
        if '/ total_revenue' in gr_spec and 'prior' not in gr_spec:
            errors.append({
                'view_name': 'quarterly_revenue',
                'column_name': 'qoq_growth_rate',
                'error_description': (
                    'Spec divides revenue change by current quarter revenue instead '
                    'of prior quarter revenue. The standard financial percentage '
                    'change formula uses the prior period as denominator.'
                )
            })

    report = {'formula_errors': errors}
    with open(AUDIT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    print(f'Audit complete: found {len(errors)} root-cause formula errors')
    for e in errors:
        print(f"  - {e['view_name']}.{e['column_name']}")

    correct.close()
    buggy.close()


if __name__ == '__main__':
    build_buggy_database()
    compare_databases()
