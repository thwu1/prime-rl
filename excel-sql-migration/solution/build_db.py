#!/usr/bin/env python3

"""
Build the financial analysis SQLite database from CSV data files.

Translates Excel workbook formulas (XLOOKUP, SUMIFS, COUNTIFS, AVERAGEIFS,
MAXIFS, MINIFS, IFS, SWITCH, NETWORKDAYS) to equivalent SQL views,
applying the CORRECT business rules (not the buggy workbook spec).
"""

import sqlite3
import csv
import os

DB_PATH = '/app/financial_analysis.db'
DATA_DIR = '/app/data'


def load_csv(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return list(csv.DictReader(f))


def create_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys = ON')
    cur = conn.cursor()

    # ================================================================
    # Create base tables
    # ================================================================

    cur.execute('''
        CREATE TABLE products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            cost_price REAL NOT NULL,
            list_price REAL NOT NULL,
            reorder_level INTEGER NOT NULL,
            units_in_stock INTEGER NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE employees (
            employee_id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            department TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            base_salary REAL NOT NULL,
            commission_rate REAL NOT NULL,
            manager_id TEXT,
            FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE regions (
            region_id TEXT PRIMARY KEY,
            region_name TEXT NOT NULL,
            country TEXT NOT NULL,
            sales_target REAL NOT NULL,
            tax_rate REAL NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE transactions (
            transaction_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            region_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            discount_pct REAL NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (region_id) REFERENCES regions(region_id)
        )
    ''')

    # ================================================================
    # Load data from CSVs
    # ================================================================

    for row in load_csv('products.csv'):
        cur.execute(
            'INSERT INTO products VALUES (?,?,?,?,?,?,?,?)',
            (row['product_id'], row['product_name'], row['category'],
             row['subcategory'], float(row['cost_price']),
             float(row['list_price']), int(row['reorder_level']),
             int(row['units_in_stock']))
        )

    emp_rows = load_csv('employees.csv')
    emp_rows.sort(key=lambda r: (0 if not r['manager_id'] else 1))
    for row in emp_rows:
        mgr = row['manager_id'] if row['manager_id'] else None
        cur.execute(
            'INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)',
            (row['employee_id'], row['first_name'], row['last_name'],
             row['department'], row['hire_date'],
             float(row['base_salary']), float(row['commission_rate']), mgr)
        )

    for row in load_csv('regions.csv'):
        cur.execute(
            'INSERT INTO regions VALUES (?,?,?,?,?)',
            (row['region_id'], row['region_name'], row['country'],
             float(row['sales_target']), float(row['tax_rate']))
        )

    for row in load_csv('transactions.csv'):
        cur.execute(
            'INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?)',
            (row['transaction_id'], row['date'], row['employee_id'],
             row['product_id'], row['region_id'], int(row['quantity']),
             float(row['unit_price']), float(row['discount_pct']))
        )

    # ================================================================
    # Create views — CORRECT business logic
    # ================================================================

    # --- enriched_transactions ---
    cur.execute('''
        CREATE VIEW enriched_transactions AS
        SELECT
            t.transaction_id,
            t.date AS transaction_date,
            t.employee_id,
            t.product_id,
            t.region_id,
            t.quantity,
            t.unit_price,
            t.discount_pct,
            p.product_name,
            p.category,
            p.cost_price,
            e.first_name || ' ' || e.last_name AS employee_name,
            r.region_name,
            t.quantity * t.unit_price * (1.0 - t.discount_pct) AS revenue,
            t.quantity * p.cost_price AS cost,
            t.quantity * t.unit_price * (1.0 - t.discount_pct)
                - t.quantity * p.cost_price AS profit,
            r.tax_rate,
            t.quantity * t.unit_price * (1.0 - t.discount_pct) * r.tax_rate
                AS tax_amount,
            t.quantity * t.unit_price * (1.0 - t.discount_pct)
                - t.quantity * t.unit_price * (1.0 - t.discount_pct) * r.tax_rate
                AS net_revenue,
            CASE
                WHEN t.quantity * t.unit_price * (1.0 - t.discount_pct) = 0 THEN 0.0
                ELSE (t.quantity * t.unit_price * (1.0 - t.discount_pct)
                      - t.quantity * p.cost_price)
                     * 1.0
                     / (t.quantity * t.unit_price * (1.0 - t.discount_pct))
            END AS profit_margin,
            CASE
                WHEN t.quantity >= 15 THEN 'Large'
                WHEN t.quantity >= 8  THEN 'Medium'
                WHEN t.quantity >= 3  THEN 'Small'
                ELSE 'Micro'
            END AS order_size_tier
        FROM transactions t
        JOIN products p ON t.product_id = p.product_id
        JOIN employees e ON t.employee_id = e.employee_id
        JOIN regions r ON t.region_id = r.region_id
    ''')

    # --- region_category_summary ---
    # CORRECT: weighted_avg_discount uses revenue-weighted mean
    cur.execute('''
        CREATE VIEW region_category_summary AS
        SELECT
            region_name,
            category,
            SUM(revenue) AS total_revenue,
            SUM(cost) AS total_cost,
            SUM(revenue) - SUM(cost) AS total_profit,
            COUNT(*) AS transaction_count,
            AVG(revenue) AS avg_order_value,
            MAX(revenue) AS max_order_value,
            MIN(revenue) AS min_order_value,
            CASE
                WHEN SUM(revenue) = 0 THEN 0.0
                ELSE SUM(discount_pct * revenue) / SUM(revenue)
            END AS weighted_avg_discount,
            CASE
                WHEN SUM(revenue) = 0 THEN 0.0
                ELSE (SUM(revenue) - SUM(cost)) * 1.0 / SUM(revenue)
            END AS profit_margin
        FROM enriched_transactions
        GROUP BY region_name, category
    ''')

    # --- employee_performance ---
    # CORRECT: NETWORKDAYS inclusive both endpoints, Gold >= 200000
    cur.execute('''
        CREATE VIEW employee_performance AS
        WITH emp_stats AS (
            SELECT
                e.employee_id,
                e.first_name || ' ' || e.last_name AS employee_name,
                e.department,
                e.hire_date,
                e.base_salary,
                e.commission_rate,
                COALESCE(SUM(et.revenue), 0.0) AS total_revenue,
                COUNT(et.transaction_id) AS total_transactions,
                CASE
                    WHEN COUNT(et.transaction_id) = 0 THEN 0.0
                    ELSE SUM(et.revenue) * 1.0 / COUNT(et.transaction_id)
                END AS avg_order_value,
                (
                    (CAST(julianday('2024-12-31') AS INTEGER) + 1) / 7 * 5
                    + MIN((CAST(julianday('2024-12-31') AS INTEGER) + 1) % 7, 4)
                ) - (
                    CAST(julianday(e.hire_date) AS INTEGER) / 7 * 5
                    + MIN(CAST(julianday(e.hire_date) AS INTEGER) % 7, 4)
                ) AS days_employed
            FROM employees e
            LEFT JOIN enriched_transactions et
                ON e.employee_id = et.employee_id
            GROUP BY e.employee_id
        )
        SELECT
            employee_id,
            employee_name,
            department,
            hire_date,
            total_revenue,
            total_transactions,
            avg_order_value,
            commission_rate,
            total_revenue * commission_rate AS commission_earned,
            base_salary + total_revenue * commission_rate AS total_compensation,
            days_employed,
            CASE
                WHEN days_employed = 0 THEN 0.0
                ELSE total_revenue * 1.0 / days_employed
            END AS revenue_per_day,
            CASE
                WHEN total_revenue >= 500000 THEN 'Platinum'
                WHEN total_revenue >= 200000 THEN 'Gold'
                WHEN total_revenue >= 100000 THEN 'Silver'
                ELSE 'Bronze'
            END AS performance_tier
        FROM emp_stats
    ''')

    # --- inventory_status ---
    # CORRECT: needs_reorder uses strict <, stock_status uses 2x multiplier
    cur.execute('''
        CREATE VIEW inventory_status AS
        WITH product_sales AS (
            SELECT
                p.product_id,
                p.product_name,
                p.category,
                p.units_in_stock,
                p.reorder_level,
                COALESCE(SUM(et.quantity), 0) AS total_units_sold,
                COALESCE(SUM(et.revenue), 0.0) AS total_revenue
            FROM products p
            LEFT JOIN enriched_transactions et
                ON p.product_id = et.product_id
            GROUP BY p.product_id
        )
        SELECT
            product_id,
            product_name,
            category,
            units_in_stock,
            reorder_level,
            total_units_sold,
            units_in_stock - total_units_sold AS remaining_stock,
            CASE
                WHEN units_in_stock - total_units_sold < reorder_level THEN 'Yes'
                ELSE 'No'
            END AS needs_reorder,
            CASE
                WHEN units_in_stock - total_units_sold <= 0 THEN 'Out of Stock'
                WHEN units_in_stock - total_units_sold < reorder_level THEN 'Low Stock'
                WHEN units_in_stock - total_units_sold < reorder_level * 2 THEN 'Adequate'
                ELSE 'Well Stocked'
            END AS stock_status,
            total_revenue,
            CASE
                WHEN total_units_sold = 0 THEN 0.0
                ELSE total_revenue * 1.0 / total_units_sold
            END AS avg_selling_price
        FROM product_sales
    ''')

    # --- quarterly_revenue ---
    # CORRECT: top_category by SUM(revenue), qoq_growth_rate divides by LAG
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
                revenue,
                profit,
                category
            FROM enriched_transactions
        ),
        quarterly_agg AS (
            SELECT
                year,
                quarter,
                SUM(revenue) AS total_revenue,
                SUM(profit) AS total_profit,
                COUNT(*) AS transaction_count,
                AVG(revenue) AS avg_order_value
            FROM quarterly_data
            GROUP BY year, quarter
        ),
        quarterly_cat AS (
            SELECT
                year,
                quarter,
                category,
                SUM(revenue) AS cat_revenue,
                ROW_NUMBER() OVER (
                    PARTITION BY year, quarter
                    ORDER BY SUM(revenue) DESC
                ) AS rn
            FROM quarterly_data
            GROUP BY year, quarter, category
        )
        SELECT
            qa.year,
            qa.quarter,
            qa.total_revenue,
            qa.total_profit,
            qa.transaction_count,
            qa.avg_order_value,
            qc.category AS top_category,
            CASE
                WHEN LAG(qa.total_revenue) OVER (ORDER BY qa.year, qa.quarter) IS NULL THEN NULL
                ELSE (qa.total_revenue - LAG(qa.total_revenue) OVER (ORDER BY qa.year, qa.quarter))
                     * 100.0 / LAG(qa.total_revenue) OVER (ORDER BY qa.year, qa.quarter)
            END AS qoq_growth_rate
        FROM quarterly_agg qa
        JOIN quarterly_cat qc
            ON qa.year = qc.year
            AND qa.quarter = qc.quarter
            AND qc.rn = 1
    ''')

    conn.commit()
    conn.close()
    print('Database created successfully at', DB_PATH)


if __name__ == '__main__':
    create_database()
