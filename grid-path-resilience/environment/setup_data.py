"""Generate DuckDB warehouse with TPC-H data and multiple source system exports
with distinct quality characteristics."""

import duckdb
import os

os.makedirs('/app/sources/fulfillment', exist_ok=True)
os.makedirs('/app/sources/finance', exist_ok=True)
os.makedirs('/app/sources/procurement', exist_ok=True)

con = duckdb.connect('/app/warehouse.duckdb')

# Generate TPC-H SF=0.1 data
con.execute("INSTALL tpch")
con.execute("LOAD tpch")
con.execute("CALL dbgen(sf=0.1)")

# === Export Source System Data (BEFORE corrupting warehouse) ===

# Source: Fulfillment System
# Has ALL lineitem rows, but l_extendedprice is inflated by 5%
# (simulates a tax-inclusive export bug in the fulfillment system)
con.execute("""
    COPY (
        SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_quantity,
               ROUND(l_extendedprice * 1.05, 2) as l_extendedprice,
               l_discount, l_tax, l_returnflag, l_linestatus,
               l_shipdate, l_commitdate, l_receiptdate,
               l_shipinstruct, l_shipmode, l_comment
        FROM lineitem
    ) TO '/app/sources/fulfillment/lineitem.parquet' (FORMAT PARQUET)
""")

# Source: Finance System
# Has lineitem with correct prices but EXCLUDES all returned items
con.execute("""
    COPY (
        SELECT * FROM lineitem WHERE l_returnflag != 'R'
    ) TO '/app/sources/finance/lineitem.csv' (HEADER, DELIMITER ',')
""")
# Has orders with correct (non-truncated) o_totalprice
con.execute("""
    COPY orders TO '/app/sources/finance/orders.csv' (HEADER, DELIMITER ',')
""")

# Source: Procurement System
# Has complete, correct partsupp data
con.execute("""
    COPY partsupp TO '/app/sources/procurement/partsupp.parquet' (FORMAT PARQUET)
""")

# === Create source manifest ===
with open('/app/sources/manifest.txt', 'w') as f:
    f.write("""Source System Exports
====================

fulfillment/ - Order fulfillment tracking system. Export date: 2024-11-15.
  lineitem.parquet - Line item records from fulfillment workflow

finance/ - Financial accounting system. Export date: 2024-11-14.
  lineitem.csv - Line item records from financial ledger
  orders.csv - Order records from billing system

procurement/ - Procurement and supply chain system. Export date: 2024-11-15.
  partsupp.parquet - Part-supplier relationships and inventory
""")

# === Corrupt the warehouse (simulating ETL pipeline issues) ===

# Issue 1: Remove returned+filled+high-quantity line items
# (simulates a bad WHERE filter during incremental load)
con.execute("""
    DELETE FROM lineitem
    WHERE l_returnflag = 'R' AND l_linestatus = 'F' AND l_quantity > 40
""")

# Issue 2: Truncate order prices to integers (wrong CAST during ETL)
con.execute("UPDATE orders SET o_totalprice = FLOOR(o_totalprice)")

# Issue 3: Drop partsupp table entirely (incomplete pipeline stage)
con.execute("DROP TABLE IF EXISTS partsupp")

con.close()
