#!/usr/bin/env python3
"""
Build a flawed analytical star schema from TPC-H SF=0.1 data.

Flaws intentionally introduced:
1. fact_sales contains order_total_price (order-level measure) at lineitem grain -> fan-out
2. No supply cost (ps_supplycost) modeled anywhere in the star schema -> profit impossible
3. dim_date covers only 1993-01-01 to 1997-12-31, but TPC-H dates span 1992-1998 -> silent data loss
"""

import duckdb
from datetime import date, timedelta

con = duckdb.connect('/app/warehouse.duckdb')

# Generate TPC-H SF=0.1 data
con.execute("INSTALL tpch")
con.execute("LOAD tpch")
con.execute("CALL dbgen(sf=0.1)")

# Create staging copies (raw operational source of truth)
for table in ['lineitem', 'orders', 'customer', 'supplier', 'part', 'partsupp', 'nation', 'region']:
    con.execute(f"CREATE TABLE stg_{table} AS SELECT * FROM {table}")

# ============================================================
# Analytical Star Schema (with intentional design flaws)
# ============================================================

# dim_customer — properly denormalized, no issues
con.execute("""
CREATE TABLE dim_customer AS
SELECT c.c_custkey AS customer_key,
       c.c_name AS name,
       c.c_address AS address,
       c.c_phone AS phone,
       c.c_acctbal AS acctbal,
       c.c_mktsegment AS mktsegment,
       n.n_name AS nation_name,
       r.r_name AS region_name
FROM customer c
JOIN nation n ON c.c_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
""")

# dim_supplier — properly denormalized, no issues
con.execute("""
CREATE TABLE dim_supplier AS
SELECT s.s_suppkey AS supplier_key,
       s.s_name AS name,
       s.s_address AS address,
       s.s_phone AS phone,
       s.s_acctbal AS acctbal,
       n.n_name AS nation_name,
       r.r_name AS region_name
FROM supplier s
JOIN nation n ON s.s_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
""")

# dim_part — no issues
con.execute("""
CREATE TABLE dim_part AS
SELECT p_partkey AS part_key,
       p_name AS name,
       p_mfgr AS mfgr,
       p_brand AS brand,
       p_type AS type,
       p_size AS size,
       p_container AS container,
       p_retailprice AS retail_price
FROM part
""")

# dim_date — FLAW: only covers 1993-01-01 to 1997-12-31
# TPC-H order dates span ~1992-01-02 to 1998-08-02
con.execute("""
CREATE TABLE dim_date (
    date_key INTEGER,
    full_date DATE,
    year INTEGER,
    quarter INTEGER,
    month INTEGER,
    month_name VARCHAR,
    day_of_week VARCHAR
)
""")

d = date(1993, 1, 1)
end_d = date(1997, 12, 31)
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
print(f"dim_date: {len(rows)} rows (1993-01-01 to 1997-12-31)")

# fact_sales — FLAWS:
#  1) order_total_price is an order-level measure stored at lineitem grain (fan-out trap)
#  2) No supply cost (ps_supplycost) available in any table (missing cost data)
con.execute("""
CREATE TABLE fact_sales AS
SELECT l.l_orderkey AS order_key,
       l.l_linenumber AS line_number,
       o.o_custkey AS customer_key,
       l.l_partkey AS part_key,
       l.l_suppkey AS supplier_key,
       CAST(REPLACE(CAST(o.o_orderdate AS VARCHAR), '-', '') AS INTEGER) AS order_date_key,
       o.o_totalprice AS order_total_price,
       o.o_orderstatus AS order_status,
       o.o_orderpriority AS order_priority,
       l.l_quantity AS quantity,
       l.l_extendedprice AS extended_price,
       l.l_discount AS discount,
       l.l_tax AS tax,
       l.l_shipdate AS ship_date,
       l.l_commitdate AS commit_date,
       l.l_receiptdate AS receipt_date,
       l.l_returnflag AS return_flag,
       l.l_linestatus AS line_status,
       l.l_shipmode AS ship_mode
FROM lineitem l
JOIN orders o ON l.l_orderkey = o.o_orderkey
""")

row_count = con.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
order_count = con.execute("SELECT COUNT(DISTINCT order_key) FROM fact_sales").fetchone()[0]
print(f"fact_sales: {row_count} rows, {order_count} distinct orders")

# Drop original TPC-H tables (keep stg_* and analytical tables)
for t in ['lineitem', 'orders', 'customer', 'supplier', 'part', 'partsupp', 'nation', 'region']:
    con.execute(f"DROP TABLE IF EXISTS {t}")

con.close()
print("Database setup complete: /app/warehouse.duckdb")
