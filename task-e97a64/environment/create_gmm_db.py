#!/usr/bin/env python3
"""Create the multi-period GMM SQLite database for the seismic hazard model."""
import sqlite3
import os

db_path = '/app/model/gmm.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)''')

c.execute('''CREATE TABLE periods (
    id INTEGER PRIMARY KEY,
    imt TEXT NOT NULL UNIQUE,
    period_sec REAL NOT NULL
)''')

c.execute('''CREATE TABLE branches (
    id TEXT NOT NULL,
    period_id INTEGER NOT NULL,
    weight REAL NOT NULL,
    sigma REAL NOT NULL,
    PRIMARY KEY (id, period_id),
    FOREIGN KEY (period_id) REFERENCES periods(id)
)''')

c.execute('''CREATE TABLE coefficients (
    branch_id TEXT NOT NULL,
    period_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (branch_id, period_id, name),
    FOREIGN KEY (branch_id, period_id) REFERENCES branches(id, period_id)
)''')

# Metadata
meta = [
    ('formula',
     'ln(SA_g) = c0 + c1*(M-Mref) + c2*(M-Mref)^2 + c3*ln(sqrt(R^2+h^2))'
     ' + c_site*ln(min(Vs30,Vref)/Vref) + c_basin*max(ln(z1p0/z1p0_ref),0)'),
    ('distance_metric', 'Rrup'),
    ('Mref', '6.0'),
    ('Vref', '760.0'),
    ('z1p0_ref', '0.05'),
    ('units_sa', 'g'),
    ('units_distance', 'km'),
]
for k, v in meta:
    c.execute("INSERT INTO metadata VALUES (?, ?)", (k, v))

# Periods
c.execute("INSERT INTO periods VALUES (1, 'PGA', 0.0)")
c.execute("INSERT INTO periods VALUES (2, 'SA0P2', 0.2)")
c.execute("INSERT INTO periods VALUES (3, 'SA1P0', 1.0)")

# Branches and coefficients per period
# PGA (period_id=1)
c.execute("INSERT INTO branches VALUES ('gmm-A', 1, 0.4, 0.55)")
c.execute("INSERT INTO branches VALUES ('gmm-B', 1, 0.6, 0.70)")
pga_A = {'c0': -0.50, 'c1': 0.80, 'c2': -0.10, 'c3': -1.30,
          'h': 5.0, 'c_site': -0.60, 'c_basin': 0.0}
pga_B = {'c0': -0.45, 'c1': 0.85, 'c2': -0.09, 'c3': -1.25,
          'h': 6.0, 'c_site': -0.55, 'c_basin': 0.0}

# SA(0.2s) (period_id=2)
c.execute("INSERT INTO branches VALUES ('gmm-A', 2, 0.4, 0.58)")
c.execute("INSERT INTO branches VALUES ('gmm-B', 2, 0.6, 0.72)")
sa02_A = {'c0': 0.10, 'c1': 0.90, 'c2': -0.08, 'c3': -1.20,
           'h': 5.0, 'c_site': -0.50, 'c_basin': 0.0}
sa02_B = {'c0': 0.15, 'c1': 0.95, 'c2': -0.07, 'c3': -1.15,
           'h': 6.0, 'c_site': -0.45, 'c_basin': 0.0}

# SA(1.0s) (period_id=3)
c.execute("INSERT INTO branches VALUES ('gmm-A', 3, 0.4, 0.60)")
c.execute("INSERT INTO branches VALUES ('gmm-B', 3, 0.6, 0.75)")
sa10_A = {'c0': -1.80, 'c1': 1.10, 'c2': -0.12, 'c3': -1.00,
           'h': 6.0, 'c_site': -0.80, 'c_basin': 0.40}
sa10_B = {'c0': -1.75, 'c1': 1.15, 'c2': -0.11, 'c3': -0.95,
           'h': 7.0, 'c_site': -0.75, 'c_basin': 0.35}

all_coeffs = [
    ('gmm-A', 1, pga_A), ('gmm-B', 1, pga_B),
    ('gmm-A', 2, sa02_A), ('gmm-B', 2, sa02_B),
    ('gmm-A', 3, sa10_A), ('gmm-B', 3, sa10_B),
]
for bid, pid, coeffs in all_coeffs:
    for name, val in coeffs.items():
        c.execute("INSERT INTO coefficients VALUES (?, ?, ?, ?)",
                  (bid, pid, name, val))

conn.commit()
conn.close()
print(f"Created {db_path}")
