#!/usr/bin/env python3
"""
Convert source data into heterogeneous formats for the task environment.
Some forecasts -> Parquet, one -> NDJSON, target data -> SQLite.
"""
import csv
import json
import os
import sqlite3
import subprocess

FORECASTS_TMP = "/tmp/forecasts"
FORECASTS_OUT = "/app/data/forecasts"
os.makedirs(FORECASTS_OUT, exist_ok=True)

# 1. Convert TeamB-Baseline to Parquet via DuckDB CLI
subprocess.run([
    "duckdb", "-c",
    "COPY (SELECT * FROM read_csv_auto('/tmp/forecasts/TeamB-Baseline.csv')) "
    "TO '/app/data/forecasts/TeamB-Baseline.parquet' (FORMAT PARQUET);"
], check=True)

# 2. Convert TeamE-Hybrid to Parquet via DuckDB CLI
subprocess.run([
    "duckdb", "-c",
    "COPY (SELECT * FROM read_csv_auto('/tmp/forecasts/TeamE-Hybrid.csv')) "
    "TO '/app/data/forecasts/TeamE-Hybrid.parquet' (FORMAT PARQUET);"
], check=True)

# 3. Convert TeamD-NarrowCI to NDJSON
with open(os.path.join(FORECASTS_TMP, "TeamD-NarrowCI.csv")) as f:
    reader = csv.DictReader(f)
    with open(os.path.join(FORECASTS_OUT, "TeamD-NarrowCI.ndjson"), "w") as out:
        for row in reader:
            out.write(json.dumps(row) + "\n")

# 4. Copy remaining CSVs as-is
for fname in ["TeamA-EpiModel.csv", "TeamC-Overpredict.csv", "TeamF-Corrupt.csv"]:
    subprocess.run(["cp", os.path.join(FORECASTS_TMP, fname), FORECASTS_OUT], check=True)

# 5. Create SQLite database for target observations
conn = sqlite3.connect("/app/data/observations.db")
conn.execute(
    "CREATE TABLE weekly_admissions ("
    "date TEXT NOT NULL, "
    "location TEXT NOT NULL, "
    "location_name TEXT NOT NULL, "
    "value REAL NOT NULL, "
    "PRIMARY KEY (date, location))"
)
with open("/tmp/target.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        conn.execute(
            "INSERT INTO weekly_admissions VALUES (?, ?, ?, ?)",
            (row["date"], row["location"], row["location_name"], float(row["value"]))
        )
conn.commit()
conn.close()

print("Data setup complete: Parquet, NDJSON, SQLite created.")
