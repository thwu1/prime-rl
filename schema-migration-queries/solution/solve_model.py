#!/usr/bin/env python3
"""
Diagnose flawed star schema, design fixes, and produce corrected reports.

Approach:
1. Inspect the analytical star schema to understand its structure and grain.
2. Run each report against the star schema AND compute reference results from
   staging tables to identify which reports produce incorrect results.
3. Diagnose root causes using dimensional modeling principles.
4. Create fix.sql to correct the schema (new tables, extended dimensions).
5. Write corrected report SQL that works against the fixed analytical model.
"""


import duckdb
import json
import os
from datetime import date, timedelta

DB = '/app/warehouse.duckdb'
con = duckdb.connect(DB)

# ============================================================
# Step 1: Schema discovery and analysis
# ============================================================

tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
print("Tables:", tables)

# Understand fact_sales grain
grain = con.execute("""
    SELECT COUNT(*) AS total_rows,
           COUNT(DISTINCT order_key) AS distinct_orders
    FROM fact_sales
""").fetchone()
print(f"\nfact_sales: {grain[0]} rows, {grain[1]} distinct orders")
print(f"Average lineitems per order: {grain[0]/grain[1]:.1f}")

# Check dim_date coverage
date_range = con.execute("SELECT MIN(full_date), MAX(full_date) FROM dim_date").fetchone()
print(f"\ndim_date range: {date_range[0]} to {date_range[1]}")

# Check actual order date range in fact_sales
order_range = con.execute("""
    SELECT MIN(order_date_key), MAX(order_date_key) FROM fact_sales
""").fetchone()
print(f"fact_sales order_date_key range: {order_range[0]} to {order_range[1]}")

# Check if supply cost exists anywhere in the model
supply_tables = [t for t in tables if 'supply' in t.lower() or 'partsupp' in t.lower()]
print(f"\nSupply-related tables in model: {supply_tables}")

# ============================================================
# Step 2: Run reports and compare with staging reference
# ============================================================

# Read original reports
reports = {}
for i in range(1, 6):
    with open(f'/app/reports/report_{i}.sql') as f:
        reports[i] = f.read().strip()

# Run star schema reports
star_results = {}
for i, sql in reports.items():
    try:
        star_results[i] = con.execute(sql).fetchall()
        print(f"\nReport {i}: {len(star_results[i])} rows from star schema")
    except Exception as e:
        print(f"\nReport {i}: ERROR - {e}")

# Reference queries against staging tables (operational truth)
ref_queries = {
    1: """
SELECT l_returnflag AS return_flag, l_linestatus AS line_status,
       SUM(l_quantity) AS total_qty,
       SUM(l_extendedprice) AS total_base_price,
       SUM(l_extendedprice * (1 - l_discount)) AS total_disc_price,
       SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS total_charge,
       AVG(l_quantity) AS avg_qty,
       AVG(l_extendedprice) AS avg_price,
       AVG(l_discount) AS avg_disc,
       COUNT(*) AS count_lines
FROM stg_lineitem
WHERE l_shipdate <= DATE '1998-09-02'
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
""",
    2: """
SELECT r.r_name AS region_name,
       SUM(o.o_totalprice) AS total_revenue,
       COUNT(*) AS num_orders
FROM stg_orders o
JOIN stg_customer c ON o.o_custkey = c.c_custkey
JOIN stg_nation n ON c.c_nationkey = n.n_nationkey
JOIN stg_region r ON n.n_regionkey = r.r_regionkey
WHERE EXTRACT(YEAR FROM o.o_orderdate) = 1995
GROUP BY r.r_name
ORDER BY total_revenue DESC
""",
    3: """
SELECT n.n_name AS nation_name,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM stg_customer c
JOIN stg_orders o ON c.c_custkey = o.o_custkey
JOIN stg_lineitem l ON o.o_orderkey = l.l_orderkey
JOIN stg_supplier s ON l.l_suppkey = s.s_suppkey
JOIN stg_nation n ON s.s_nationkey = n.n_nationkey
JOIN stg_region r ON n.n_regionkey = r.r_regionkey
WHERE c.c_nationkey = s.s_nationkey
  AND r.r_name = 'ASIA'
  AND o.o_orderdate >= DATE '1994-01-01'
  AND o.o_orderdate < DATE '1995-01-01'
GROUP BY n.n_name
ORDER BY revenue DESC
""",
    4: """
SELECT n.n_name AS nation,
       EXTRACT(YEAR FROM o.o_orderdate)::INTEGER AS o_year,
       SUM(l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity) AS total_profit
FROM stg_part p
JOIN stg_lineitem l ON p.p_partkey = l.l_partkey
JOIN stg_supplier s ON l.l_suppkey = s.s_suppkey
JOIN stg_partsupp ps ON l.l_suppkey = ps.ps_suppkey AND l.l_partkey = ps.ps_partkey
JOIN stg_orders o ON l.l_orderkey = o.o_orderkey
JOIN stg_nation n ON s.s_nationkey = n.n_nationkey
WHERE p.p_name LIKE '%green%'
GROUP BY n.n_name, EXTRACT(YEAR FROM o.o_orderdate)
ORDER BY n.n_name, o_year DESC
""",
    5: """
SELECT EXTRACT(YEAR FROM o.o_orderdate)::INTEGER AS year,
       EXTRACT(QUARTER FROM o.o_orderdate)::INTEGER AS quarter,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS quarterly_revenue,
       COUNT(DISTINCT o.o_orderkey) AS num_orders
FROM stg_lineitem l
JOIN stg_orders o ON l.l_orderkey = o.o_orderkey
GROUP BY EXTRACT(YEAR FROM o.o_orderdate), EXTRACT(QUARTER FROM o.o_orderdate)
ORDER BY year, quarter
""",
}

ref_results = {}
for i, sql in ref_queries.items():
    ref_results[i] = con.execute(sql).fetchall()
    print(f"Reference {i}: {len(ref_results[i])} rows from staging")

# Compare
for i in range(1, 6):
    star = star_results.get(i)
    ref = ref_results[i]
    if star is None:
        print(f"\nReport {i}: COULD NOT EXECUTE against star schema")
        continue

    match = True
    if len(star) != len(ref):
        match = False
        print(f"\nReport {i}: ROW COUNT MISMATCH (star={len(star)}, ref={len(ref)})")
    else:
        for row_idx, (s_row, r_row) in enumerate(zip(star, ref)):
            for col_idx in range(min(len(s_row), len(r_row))):
                sv = float(s_row[col_idx]) if isinstance(s_row[col_idx], (int, float)) else s_row[col_idx]
                rv = float(r_row[col_idx]) if isinstance(r_row[col_idx], (int, float)) else r_row[col_idx]
                if isinstance(sv, float) and isinstance(rv, float):
                    if abs(sv - rv) > 0.01 * max(abs(sv), abs(rv), 1):
                        match = False
                        break
                elif str(sv) != str(rv):
                    match = False
                    break
            if not match:
                break

    status = "MATCHES" if match else "DOES NOT MATCH"
    print(f"Report {i}: {status} reference")

# ============================================================
# Step 3: Write diagnosis
# ============================================================

diagnosis = {
    "report_1": {
        "status": "correct",
        "explanation": (
            "This report aggregates only lineitem-level measures (quantity, "
            "extended_price, discount, tax) from fact_sales. The fact table grain "
            "is lineitem (order_key, line_number), and all measures used here are "
            "at that grain, so aggregations are accurate with no fan-out."
        )
    },
    "report_2": {
        "status": "incorrect",
        "root_cause": "fan_out",
        "explanation": (
            "The order_total_price column is an order-level measure stored in a "
            "lineitem-grain fact table. Each order's total price is repeated for "
            "every lineitem in that order, so SUM(order_total_price) is inflated "
            "by a factor equal to the average number of lineitems per order (~4x). "
            "This is a classic fan-out trap from mixing aggregation grains in a "
            "single fact table. The COUNT(DISTINCT order_key) is correct, but the "
            "revenue figure is wildly overstated."
        )
    },
    "report_3": {
        "status": "correct",
        "explanation": (
            "This report computes lineitem-level revenue (extended_price * "
            "(1 - discount)) which matches the fact_sales grain. The joins to "
            "dim_customer and dim_supplier with the nation equality filter correctly "
            "implement the local supplier pattern. The dim_date filter for 1994 is "
            "valid because dim_date covers 1993-1997."
        )
    },
    "report_4": {
        "status": "incorrect",
        "root_cause": "missing_data",
        "explanation": (
            "The report attempts to compute profit using dim_part.retail_price as "
            "a proxy for supply cost, but retail_price is the catalog list price "
            "and bears no relation to the actual supply cost. The true cost is "
            "ps_supplycost from the part-supplier relationship (partsupp), which "
            "varies by specific part-supplier combination. This relationship is "
            "not modeled anywhere in the star schema, making accurate profit "
            "calculation impossible without schema changes."
        )
    },
    "report_5": {
        "status": "incorrect",
        "root_cause": "incomplete_dimension",
        "explanation": (
            "The dim_date table only covers 1993-01-01 to 1997-12-31, but "
            "TPC-H order dates span approximately 1992 to 1998. The INNER JOIN "
            "between fact_sales and dim_date silently drops all orders placed in "
            "1992 and 1998 because their order_date_key values have no matching "
            "date_key in dim_date. This causes the revenue trend to be incomplete, "
            "missing roughly 24% of the timeline."
        )
    }
}

with open('/app/diagnosis.json', 'w') as f:
    json.dump(diagnosis, f, indent=2)
print("\nDiagnosis written to /app/diagnosis.json")

# ============================================================
# Step 4: Write and execute fix.sql
# ============================================================

fix_sql = """\
-- ================================================================
-- Fix 1: Create order-grain fact table to eliminate fan-out trap.
-- fact_orders has one row per order with order-level measures only.
-- ================================================================
DROP TABLE IF EXISTS fact_orders;
CREATE TABLE fact_orders AS
SELECT DISTINCT
    order_key,
    customer_key,
    order_date_key,
    order_total_price,
    order_status,
    order_priority
FROM fact_sales;

-- ================================================================
-- Fix 2: Create part-supplier bridge with supply cost.
-- Models the (part_key, supplier_key) -> supply_cost relationship
-- that was missing from the original star schema.
-- ================================================================
DROP TABLE IF EXISTS dim_part_supplier;
CREATE TABLE dim_part_supplier AS
SELECT
    ps_partkey AS part_key,
    ps_suppkey AS supplier_key,
    ps_supplycost AS supply_cost,
    ps_availqty AS available_qty
FROM stg_partsupp;

-- ================================================================
-- Fix 3: Recreate dim_date with full coverage (1992-01-01 to 1998-12-31).
-- The original dim_date only covered 1993-1997, causing silent data
-- loss for orders outside that range via inner joins.
-- ================================================================
DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date (
    date_key INTEGER,
    full_date DATE,
    year INTEGER,
    quarter INTEGER,
    month INTEGER,
    month_name VARCHAR,
    day_of_week VARCHAR
)
"""

with open('/app/fix.sql', 'w') as f:
    f.write(fix_sql.strip() + '\n')
print("fix.sql written")

# Execute the SQL portion of the fix
for stmt in fix_sql.split(';'):
    stmt = stmt.strip()
    sql_lines = [l for l in stmt.split('\n')
                 if l.strip() and not l.strip().startswith('--')]
    if sql_lines:
        con.execute(stmt)

# Populate the extended dim_date using Python for reliability
d = date(1992, 1, 1)
end_d = date(1998, 12, 31)
rows = []
while d <= end_d:
    rows.append((
        d.year * 10000 + d.month * 100 + d.day,
        d,
        d.year,
        (d.month - 1) // 3 + 1,
        d.month,
        d.strftime('%B'),
        d.strftime('%A'),
    ))
    d += timedelta(days=1)

con.executemany("INSERT INTO dim_date VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
print(f"Extended dim_date: {len(rows)} rows (1992-01-01 to 1998-12-31)")

# Now rewrite fix.sql to be fully self-contained SQL (for test execution)
# Use a recursive CTE to generate dates purely in SQL
fix_sql_final = """\
-- ================================================================
-- Fix 1: Create order-grain fact table to eliminate fan-out trap.
-- ================================================================
DROP TABLE IF EXISTS fact_orders;
CREATE TABLE fact_orders AS
SELECT DISTINCT
    order_key,
    customer_key,
    order_date_key,
    order_total_price,
    order_status,
    order_priority
FROM fact_sales;

-- ================================================================
-- Fix 2: Create part-supplier bridge with supply cost.
-- ================================================================
DROP TABLE IF EXISTS dim_part_supplier;
CREATE TABLE dim_part_supplier AS
SELECT
    ps_partkey AS part_key,
    ps_suppkey AS supplier_key,
    ps_supplycost AS supply_cost,
    ps_availqty AS available_qty
FROM stg_partsupp;

-- ================================================================
-- Fix 3: Recreate dim_date with full date coverage (1992 to 1998).
-- ================================================================
DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date AS
WITH RECURSIVE dates(d) AS (
    SELECT DATE '1992-01-01'
    UNION ALL
    SELECT CAST(d + INTERVAL '1' DAY AS DATE) FROM dates WHERE d < DATE '1998-12-31'
)
SELECT
    (YEAR(d) * 10000 + MONTH(d) * 100 + DAY(d))::INTEGER AS date_key,
    d AS full_date,
    YEAR(d)::INTEGER AS year,
    QUARTER(d)::INTEGER AS quarter,
    MONTH(d)::INTEGER AS month,
    monthname(d) AS month_name,
    dayname(d) AS day_of_week
FROM dates
"""

with open('/app/fix.sql', 'w') as f:
    f.write(fix_sql_final.strip() + '\n')
print("fix.sql rewritten with self-contained SQL")

# ============================================================
# Step 5: Write corrected reports
# ============================================================

os.makedirs('/app/corrected_reports', exist_ok=True)

corrected = {
    1: """\
-- Report 1: Pricing Summary (unchanged — already correct)
SELECT
    f.return_flag,
    f.line_status,
    SUM(f.quantity) AS total_qty,
    SUM(f.extended_price) AS total_base_price,
    SUM(f.extended_price * (1 - f.discount)) AS total_disc_price,
    SUM(f.extended_price * (1 - f.discount) * (1 + f.tax)) AS total_charge,
    AVG(f.quantity) AS avg_qty,
    AVG(f.extended_price) AS avg_price,
    AVG(f.discount) AS avg_disc,
    COUNT(*) AS count_lines
FROM fact_sales f
WHERE f.ship_date <= DATE '1998-09-02'
GROUP BY f.return_flag, f.line_status
ORDER BY f.return_flag, f.line_status
""",
    2: """\
-- Report 2: Order Revenue by Customer Region (FIXED)
-- Uses fact_orders (order-grain) to avoid fan-out on order_total_price
SELECT
    dc.region_name,
    SUM(fo.order_total_price) AS total_revenue,
    COUNT(*) AS num_orders
FROM fact_orders fo
JOIN dim_customer dc ON fo.customer_key = dc.customer_key
JOIN dim_date dd ON fo.order_date_key = dd.date_key
WHERE dd.year = 1995
GROUP BY dc.region_name
ORDER BY total_revenue DESC
""",
    3: """\
-- Report 3: Local Supplier Revenue in ASIA (unchanged — already correct)
SELECT
    ds.nation_name,
    SUM(f.extended_price * (1 - f.discount)) AS revenue
FROM fact_sales f
JOIN dim_customer dc ON f.customer_key = dc.customer_key
JOIN dim_supplier ds ON f.supplier_key = ds.supplier_key
JOIN dim_date dd ON f.order_date_key = dd.date_key
WHERE dc.nation_name = ds.nation_name
  AND ds.region_name = 'ASIA'
  AND dd.year = 1994
GROUP BY ds.nation_name
ORDER BY revenue DESC
""",
    4: """\
-- Report 4: Profit by Supplier Nation (FIXED)
-- Uses dim_part_supplier for actual supply cost instead of retail_price
-- Joins extended dim_date for proper year grouping
SELECT
    ds.nation_name AS nation,
    dd.year AS o_year,
    SUM(f.extended_price * (1 - f.discount) - dps.supply_cost * f.quantity) AS total_profit
FROM fact_sales f
JOIN dim_supplier ds ON f.supplier_key = ds.supplier_key
JOIN dim_part dp ON f.part_key = dp.part_key
JOIN dim_part_supplier dps ON f.part_key = dps.part_key AND f.supplier_key = dps.supplier_key
JOIN dim_date dd ON f.order_date_key = dd.date_key
WHERE dp.name LIKE '%green%'
GROUP BY ds.nation_name, dd.year
ORDER BY ds.nation_name, o_year DESC
""",
    5: """\
-- Report 5: Annual Revenue Trend (FIXED)
-- Uses extended dim_date that covers the full 1992-1998 date range
SELECT
    dd.year,
    dd.quarter,
    SUM(f.extended_price * (1 - f.discount)) AS quarterly_revenue,
    COUNT(DISTINCT f.order_key) AS num_orders
FROM fact_sales f
JOIN dim_date dd ON f.order_date_key = dd.date_key
GROUP BY dd.year, dd.quarter
ORDER BY dd.year, dd.quarter
""",
}

for i, sql in corrected.items():
    path = f'/app/corrected_reports/report_{i}.sql'
    with open(path, 'w') as f:
        f.write(sql.strip() + '\n')

    # Verify against reference
    result = con.execute(sql).fetchall()
    ref = ref_results[i]
    match = len(result) == len(ref)
    if match:
        for s_row, r_row in zip(result, ref):
            for col_idx in range(min(len(s_row), len(r_row))):
                sv = float(s_row[col_idx]) if isinstance(s_row[col_idx], (int, float)) else s_row[col_idx]
                rv = float(r_row[col_idx]) if isinstance(r_row[col_idx], (int, float)) else r_row[col_idx]
                if isinstance(sv, float) and isinstance(rv, float):
                    if abs(sv - rv) > 0.001 * max(abs(sv), abs(rv), 1):
                        match = False
                        break
                elif str(sv) != str(rv):
                    match = False
                    break
            if not match:
                break
    print(f"Corrected report {i}: {'OK' if match else 'MISMATCH'} ({len(result)} rows)")

con.close()
print("\nAll corrected reports written to /app/corrected_reports/")
