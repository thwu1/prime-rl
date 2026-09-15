#!/usr/bin/env python3
"""Create calibration database for comparison loss experiment."""
import sqlite3
import os

os.makedirs('/app/input', exist_ok=True)
conn = sqlite3.connect('/app/input/calibration.db')
c = conn.cursor()

c.execute('''CREATE TABLE calibration_cases (
    case_id INTEGER PRIMARY KEY,
    x1 REAL NOT NULL,
    x2 REAL NOT NULL,
    u1 REAL NOT NULL,
    u2 REAL NOT NULL,
    r REAL NOT NULL
)''')

cases = [
    (1, 0.000, 0.0, 0.005, 0.005, 0.0),
    (2, 0.010, 0.0, 0.005, 0.005, 0.0),
    (3, 0.050, 0.0, 0.005, 0.005, 0.0),
    (4, 0.000, 0.0, 0.005, 0.005, 0.9),
    (5, 0.010, 0.0, 0.005, 0.005, 0.9),
    (6, 0.050, 0.0, 0.005, 0.005, 0.9),
]

c.executemany('INSERT INTO calibration_cases VALUES (?, ?, ?, ?, ?, ?)', cases)

c.execute('''CREATE TABLE analysis_config (
    key TEXT PRIMARY KEY,
    value_real REAL NOT NULL
)''')

config = [
    ('coverage_probability', 0.95),
    ('ndig', 1.0),
]

c.executemany('INSERT INTO analysis_config VALUES (?, ?)', config)

conn.commit()
conn.close()
