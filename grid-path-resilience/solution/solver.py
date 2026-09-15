"""
Reference solver for DuckDB Multi-Source Data Reconciliation.

Strategy:
1. Explore the warehouse schema and identify what's present/missing
2. Explore all source system exports and compare against the warehouse
3. Discover systematic discrepancies (price inflation, missing rows, etc.)
4. Evaluate which source to trust for each data element
5. Build a reconciled dataset from the most trustworthy sources
6. Compute all analytical results from the reconciled data
"""

import json
import os

import duckdb


def solve():
    # === Phase 1: Explore the warehouse ===
    wh = duckdb.connect('/app/warehouse.duckdb', read_only=True)
    tables = [t[0] for t in wh.execute("SHOW TABLES").fetchall()]
    print(f"Warehouse tables: {tables}")

    for table in tables:
        cnt = wh.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {cnt} rows")

    # Note: partsupp is missing from the warehouse
    wh.close()

    # === Phase 2: Explore source systems and compare ===
    work = duckdb.connect()
    work.execute("ATTACH '/app/warehouse.duckdb' AS wh (READ_ONLY)")

    # --- Fulfillment lineitem ---
    ful_count = work.execute(
        "SELECT COUNT(*) FROM read_parquet('/app/sources/fulfillment/lineitem.parquet')"
    ).fetchone()[0]
    wh_li_count = work.execute("SELECT COUNT(*) FROM wh.lineitem").fetchone()[0]
    print(f"\nFulfillment lineitem: {ful_count} rows")
    print(f"Warehouse lineitem:  {wh_li_count} rows")
    print(f"  Difference: {ful_count - wh_li_count} rows missing from warehouse")

    # Discover: what's missing from the warehouse?
    missing_profile = work.execute("""
        SELECT f.l_returnflag, f.l_linestatus, COUNT(*) as cnt,
               MIN(f.l_quantity) as min_qty, MAX(f.l_quantity) as max_qty
        FROM read_parquet('/app/sources/fulfillment/lineitem.parquet') f
        WHERE NOT EXISTS (
            SELECT 1 FROM wh.lineitem w
            WHERE w.l_orderkey = f.l_orderkey AND w.l_linenumber = f.l_linenumber
        )
        GROUP BY f.l_returnflag, f.l_linestatus
    """).fetchall()
    print(f"  Missing rows profile: {missing_profile}")
    # Discovery: only R/F rows with high quantity are missing

    # Discover: price discrepancy between fulfillment and warehouse
    price_ratio = work.execute("""
        SELECT ROUND(AVG(f.l_extendedprice / w.l_extendedprice), 6)
        FROM wh.lineitem w
        JOIN read_parquet('/app/sources/fulfillment/lineitem.parquet') f
          ON w.l_orderkey = f.l_orderkey AND w.l_linenumber = f.l_linenumber
        WHERE w.l_extendedprice > 0
    """).fetchone()[0]
    print(f"\n  Fulfillment/Warehouse price ratio: {price_ratio}")
    # Discovery: ratio is ~1.05 → fulfillment prices are systematically 5% higher

    # Verify the ratio is consistent (not random noise)
    ratio_stddev = work.execute("""
        SELECT ROUND(STDDEV(f.l_extendedprice / w.l_extendedprice), 8)
        FROM wh.lineitem w
        JOIN read_parquet('/app/sources/fulfillment/lineitem.parquet') f
          ON w.l_orderkey = f.l_orderkey AND w.l_linenumber = f.l_linenumber
        WHERE w.l_extendedprice > 0
    """).fetchone()[0]
    print(f"  Price ratio stddev: {ratio_stddev}")
    # Near-zero stddev confirms systematic bias, not noise

    # --- Finance lineitem ---
    fin_li_count = work.execute(
        "SELECT COUNT(*) FROM read_csv_auto('/app/sources/finance/lineitem.csv')"
    ).fetchone()[0]
    print(f"\nFinance lineitem: {fin_li_count} rows")

    fin_flags = work.execute("""
        SELECT l_returnflag, COUNT(*)
        FROM read_csv_auto('/app/sources/finance/lineitem.csv')
        GROUP BY l_returnflag ORDER BY l_returnflag
    """).fetchall()
    print(f"  Finance flags: {fin_flags}")
    # Discovery: no 'R' flag → finance system excludes returns

    # Finance prices match warehouse (both correct for existing rows)
    fin_price_check = work.execute("""
        SELECT COUNT(*), SUM(ABS(f.l_extendedprice - w.l_extendedprice))
        FROM wh.lineitem w
        JOIN read_csv_auto('/app/sources/finance/lineitem.csv') f
          ON w.l_orderkey = f.l_orderkey AND w.l_linenumber = f.l_linenumber
    """).fetchone()
    print(f"  Finance vs warehouse price diff: {fin_price_check}")

    # --- Finance orders ---
    fin_order_sample = work.execute("""
        SELECT w.o_totalprice as wh_price, f.o_totalprice as fin_price,
               f.o_totalprice - w.o_totalprice as diff
        FROM wh.orders w
        JOIN read_csv_auto('/app/sources/finance/orders.csv') f
          ON w.o_orderkey = f.o_orderkey
        WHERE ABS(f.o_totalprice - w.o_totalprice) > 0.001
        LIMIT 5
    """).fetchall()
    print(f"\nOrder price discrepancies (sample): {fin_order_sample}")
    # Discovery: warehouse prices are truncated to integers

    # --- Procurement partsupp ---
    proc_ps_count = work.execute(
        "SELECT COUNT(*) FROM read_parquet('/app/sources/procurement/partsupp.parquet')"
    ).fetchone()[0]
    print(f"\nProcurement partsupp: {proc_ps_count} rows")
    # Discovery: this is the only source for partsupp data

    work.execute("DETACH wh")

    # === Phase 3: Reconciliation Strategy ===
    print("\n=== Reconciliation Strategy ===")
    print("1. Lineitem: Use fulfillment (all rows), correct prices by dividing by 1.05")
    print("2. Orders: Use finance system (correct decimal prices)")
    print("3. Partsupp: Use procurement system (only available source)")
    print("4. Reference tables (customer/nation/region/supplier): Use warehouse")

    # === Phase 4: Build reconciled dataset ===
    work.execute("ATTACH '/app/warehouse.duckdb' AS wh (READ_ONLY)")

    # Load intact reference tables from warehouse
    for table in ['customer', 'nation', 'region', 'supplier']:
        work.execute(f"CREATE TABLE {table} AS SELECT * FROM wh.{table}")
    work.execute("DETACH wh")

    # Corrected lineitem: all rows from fulfillment, prices divided by 1.05
    work.execute("""
        CREATE TABLE lineitem AS
        SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_quantity,
               ROUND(l_extendedprice / 1.05, 2) as l_extendedprice,
               l_discount, l_tax, l_returnflag, l_linestatus,
               l_shipdate, l_commitdate, l_receiptdate,
               l_shipinstruct, l_shipmode, l_comment
        FROM read_parquet('/app/sources/fulfillment/lineitem.parquet')
    """)

    # Correct orders from finance system
    work.execute("""
        CREATE TABLE orders AS
        SELECT * FROM read_csv_auto('/app/sources/finance/orders.csv')
    """)

    # Partsupp from procurement system
    work.execute("""
        CREATE TABLE partsupp AS
        SELECT * FROM read_parquet('/app/sources/procurement/partsupp.parquet')
    """)

    # === Phase 5: Compute analytical results ===
    results = {}

    # Q1: revenue_by_region
    rev = work.execute("""
        SELECT r_name, ROUND(SUM(l_extendedprice * (1 - l_discount)), 2) as revenue
        FROM lineitem
        JOIN orders ON l_orderkey = o_orderkey
        JOIN customer ON o_custkey = c_custkey
        JOIN nation ON c_nationkey = n_nationkey
        JOIN region ON n_regionkey = r_regionkey
        GROUP BY r_name
    """).fetchall()
    results['revenue_by_region'] = {str(r): float(v) for r, v in rev}

    # Q2: top_supplier_by_availability
    sup = work.execute("""
        SELECT s_name
        FROM partsupp
        JOIN supplier ON ps_suppkey = s_suppkey
        GROUP BY s_name
        ORDER BY SUM(ps_availqty) DESC, s_name ASC
        LIMIT 1
    """).fetchone()
    results['top_supplier_by_availability'] = str(sup[0]).strip()

    # Q3: returned_revenue_fraction
    frac = work.execute("""
        SELECT ROUND(
            SUM(CASE WHEN l_returnflag = 'R'
                THEN l_extendedprice * (1 - l_discount) ELSE 0 END) /
            SUM(l_extendedprice * (1 - l_discount)),
            6
        )
        FROM lineitem
    """).fetchone()
    results['returned_revenue_fraction'] = float(frac[0])

    # Q4: urgent_order_revenue_1995
    urg = work.execute("""
        SELECT ROUND(SUM(o_totalprice), 2)
        FROM orders
        WHERE o_orderpriority = '1-URGENT'
          AND o_orderdate >= DATE '1995-01-01'
          AND o_orderdate < DATE '1996-01-01'
    """).fetchone()
    results['urgent_order_revenue_1995'] = float(urg[0])

    # Q5: avg_supplycost_europe
    avg_sc = work.execute("""
        SELECT ROUND(AVG(ps_supplycost), 2)
        FROM partsupp
        JOIN supplier ON ps_suppkey = s_suppkey
        JOIN nation ON s_nationkey = n_nationkey
        JOIN region ON n_regionkey = r_regionkey
        WHERE r_name = 'EUROPE'
    """).fetchone()
    results['avg_supplycost_europe'] = float(avg_sc[0])

    # Q6: priority_fulfillment_rate (1995 orders)
    rates = work.execute("""
        SELECT o_orderpriority,
               ROUND(
                   SUM(CASE WHEN l_receiptdate <= l_commitdate THEN 1 ELSE 0 END)::DOUBLE /
                   COUNT(*)::DOUBLE,
                   4
               ) as fulfillment_rate
        FROM lineitem
        JOIN orders ON l_orderkey = o_orderkey
        WHERE o_orderdate >= DATE '1995-01-01' AND o_orderdate < DATE '1996-01-01'
        GROUP BY o_orderpriority
        ORDER BY o_orderpriority
    """).fetchall()
    results['priority_fulfillment_rate'] = {str(p): float(r) for p, r in rates}

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    work.close()
    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    solve()
