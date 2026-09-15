#!/usr/bin/env python3
"""Create DuckDB database with table data for optimizer exploration."""
import duckdb

con = duckdb.connect('/app/catalog.duckdb')

# Table R: 1000 rows, r_id unique 1-1000, r_val cycles 0-99
con.execute("""
CREATE TABLE R AS SELECT
    CAST(range + 1 AS INTEGER) AS r_id,
    CAST(range % 100 AS INTEGER) AS r_val
FROM range(1000)
""")

# Table S: 10000 rows, s_id unique 1-10000, s_r_id FK->R 1-1000, s_val 500 distinct
con.execute("""
CREATE TABLE S AS SELECT
    CAST(range + 1 AS INTEGER) AS s_id,
    CAST((range % 1000) + 1 AS INTEGER) AS s_r_id,
    CAST((range % 500) * 2 AS INTEGER) AS s_val
FROM range(10000)
""")

# Table T: 100000 rows, t_id unique, t_s_id FK->S 1-10000, t_val cycles 0-999
con.execute("""
CREATE TABLE T AS SELECT
    CAST(range + 1 AS INTEGER) AS t_id,
    CAST((range % 10000) + 1 AS INTEGER) AS t_s_id,
    CAST(range % 1000 AS INTEGER) AS t_val
FROM range(100000)
""")

# Table U: 500 rows, u_id unique 1-500, u_r_id 400 distinct values, u_val 50 distinct
con.execute("""
CREATE TABLE U AS SELECT
    CAST(range + 1 AS INTEGER) AS u_id,
    CAST((range % 400) * 2 + 1 AS INTEGER) AS u_r_id,
    CAST((range % 50) * 2 AS INTEGER) AS u_val
FROM range(500)
""")

con.close()
print("Created /app/catalog.duckdb with tables R, S, T, U")
