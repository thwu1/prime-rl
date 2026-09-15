#!/usr/bin/env python3
"""Create the calibration database with scenario configurations."""
import sqlite3

db = sqlite3.connect('/app/calibration.db')
db.execute('''CREATE TABLE scenarios (
    id TEXT PRIMARY KEY,
    noise_type TEXT NOT NULL,
    ideal_value REAL NOT NULL,
    decay_rate REAL,
    asymptote REAL,
    poly_coefficients TEXT,
    scale_factors TEXT NOT NULL,
    shot_budget INTEGER NOT NULL
)''')

data = [
    ('S1', 'exponential', 0.9,  0.15, 0.0,  None,             '[1,2,3]',     10000),
    ('S2', 'exponential', -0.6, 0.2,  0.0,  None,             '[1,3,5]',     10000),
    ('S3', 'exponential', 0.7,  0.1,  0.15, None,             '[1,2,3,5]',   15000),
    ('S4', 'exponential', 0.85, 0.12, 0.0,  None,             '[1,3,5,7]',   20000),
    ('S5', 'polynomial',  0.8,  None, None, '[-0.05,-0.01]',  '[1,2,3]',     10000),
    ('S6', 'exponential', 0.95, 0.05, 0.0,  None,             '[1,2,3,4,5]', 25000),
]

db.executemany('INSERT INTO scenarios VALUES (?,?,?,?,?,?,?,?)', data)
db.commit()
db.close()
