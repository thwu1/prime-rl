#!/usr/bin/env python3
"""Create the baseline SQLite metrics database.

Stores naive "max-window" baseline results and performance targets
that the solver's congestion control must exceed.

Run at Docker build time; removed after execution.
"""

import sqlite3
import os

os.makedirs('/app/metrics', exist_ok=True)
conn = sqlite3.connect('/app/metrics/baseline.db')
c = conn.cursor()

c.execute('''CREATE TABLE baseline_results (
    scenario      TEXT PRIMARY KEY,
    avg_cwnd      REAL,
    max_cwnd      REAL,
    throughput_bps REAL,
    description   TEXT
)''')

c.executemany('INSERT INTO baseline_results VALUES (?,?,?,?,?)', [
    ('scenario_a', 65535.0, 65535.0, 800000000.0,
     'Datacenter: naive max-window CC, no loss adaptation'),
    ('scenario_b', 65535.0, 65535.0,  45000000.0,
     'WAN: naive max-window CC, severe loss amplification'),
    ('scenario_c', 65535.0, 65535.0,   5000000.0,
     'Satellite: naive max-window CC, collapse under sustained loss'),
])

c.execute('''CREATE TABLE performance_targets (
    scenario       TEXT PRIMARY KEY,
    min_avg_cwnd   INTEGER,
    description    TEXT
)''')

c.executemany('INSERT INTO performance_targets VALUES (?,?,?)', [
    ('scenario_a', 10000,
     'Must achieve high utilization with fast recovery'),
    ('scenario_b',  3000,
     'Must handle moderate loss without window collapse'),
    ('scenario_c',  2000,
     'Must maintain stability under high loss and latency'),
])

conn.commit()
conn.close()
print('Baseline database created at /app/metrics/baseline.db')
