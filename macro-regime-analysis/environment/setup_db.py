#!/usr/bin/env python3
"""Import select FRED CSV files into a SQLite database, then remove the CSVs."""
import csv
import sqlite3
import os

DB_PATH = "/app/data/macro.db"
DATA_DIR = "/app/data"
SERIES_TO_IMPORT = ["FEDFUNDS", "UNRATE", "M2SL"]

METADATA = {
    "FEDFUNDS": ("Effective Federal Funds Rate", "Monthly", "Percent", "Averages of daily figures"),
    "UNRATE": ("Unemployment Rate", "Monthly", "Percent", "Seasonally Adjusted"),
    "M2SL": ("M2 Money Stock", "Monthly", "Billions of Dollars", "Seasonally Adjusted"),
}

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""CREATE TABLE observations (
    observation_date TEXT NOT NULL,
    series_id TEXT NOT NULL,
    value TEXT
)""")
cur.execute("CREATE INDEX idx_obs_series ON observations(series_id)")
cur.execute("CREATE INDEX idx_obs_date ON observations(observation_date)")

cur.execute("""CREATE TABLE series_metadata (
    series_id TEXT PRIMARY KEY,
    title TEXT,
    frequency TEXT,
    units TEXT,
    notes TEXT
)""")

for series_id in SERIES_TO_IMPORT:
    csv_path = os.path.join(DATA_DIR, f"{series_id}.csv")
    with open(csv_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            date = row[0]
            val = row[1].strip() if len(row) > 1 else ""
            cur.execute("INSERT INTO observations VALUES (?, ?, ?)", (date, series_id, val))

    title, freq, units, notes = METADATA[series_id]
    cur.execute("INSERT INTO series_metadata VALUES (?, ?, ?, ?, ?)",
                (series_id, title, freq, units, notes))

conn.commit()
conn.close()

# Remove imported CSVs
for series_id in SERIES_TO_IMPORT:
    os.remove(os.path.join(DATA_DIR, f"{series_id}.csv"))
