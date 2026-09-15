#!/usr/bin/env python3
"""Create the demand forecast SQLite database."""
import sqlite3
import os

DB_PATH = "/app/data/forecasts/demand_scenarios.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""CREATE TABLE scenario_info (
    scenario_id TEXT PRIMARY KEY,
    probability REAL NOT NULL,
    label TEXT
)""")

c.execute("""CREATE TABLE zone_demands (
    scenario_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    projected_demand INTEGER NOT NULL,
    FOREIGN KEY (scenario_id) REFERENCES scenario_info(scenario_id),
    PRIMARY KEY (scenario_id, zone_id)
)""")

scenarios = [
    ("S1", 0.05, "low_demand"),
    ("S2", 0.10, "below_average"),
    ("S3", 0.20, "baseline"),
    ("S4", 0.25, "moderate_growth"),
    ("S5", 0.20, "above_average"),
    ("S6", 0.10, "high_demand"),
    ("S7", 0.05, "surge"),
    ("S8", 0.05, "peak"),
]

demands = {
    "S1": [12, 18, 15, 20, 10, 14, 16, 22, 11, 19, 13, 17, 14, 16, 13],
    "S2": [18, 24, 20, 28, 15, 20, 22, 30, 16, 25, 19, 23, 20, 22, 18],
    "S3": [25, 32, 28, 38, 22, 28, 30, 40, 23, 34, 26, 31, 27, 30, 25],
    "S4": [32, 40, 35, 48, 28, 36, 38, 50, 30, 42, 33, 39, 34, 38, 32],
    "S5": [40, 50, 43, 58, 35, 45, 48, 62, 37, 52, 41, 48, 42, 47, 40],
    "S6": [48, 58, 52, 70, 42, 54, 56, 74, 45, 62, 50, 58, 50, 56, 48],
    "S7": [55, 68, 60, 80, 50, 62, 65, 85, 52, 72, 58, 67, 58, 65, 55],
    "S8": [65, 78, 70, 92, 58, 72, 75, 98, 60, 82, 68, 77, 68, 75, 65],
}

for sid, prob, label in scenarios:
    c.execute("INSERT INTO scenario_info VALUES (?, ?, ?)", (sid, prob, label))

for sid, dvals in demands.items():
    for i, d in enumerate(dvals):
        zone_id = "Z{:02d}".format(i)
        c.execute("INSERT INTO zone_demands VALUES (?, ?, ?)", (sid, zone_id, d))

conn.commit()
conn.close()
print("Created demand forecast database at", DB_PATH)
