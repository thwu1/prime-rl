"""Setup script to create TPC-H database for the distributed query decomposer task."""

import duckdb

con = duckdb.connect("/app/warehouse.duckdb")
con.execute("CALL dbgen(sf=0.1)")
con.close()
print("Database created successfully at /app/warehouse.duckdb")
