"""Create the coefficients SQLite database for the polar decomposition library."""
import sqlite3
import json

conn = sqlite3.connect("/app/coefficients.db")
c = conn.cursor()

c.execute("""CREATE TABLE coefficient_sets (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
)""")

c.execute("""CREATE TABLE coefficients (
    set_id INTEGER NOT NULL,
    iteration INTEGER NOT NULL,
    a REAL NOT NULL,
    b REAL NOT NULL,
    c REAL NOT NULL,
    PRIMARY KEY (set_id, iteration),
    FOREIGN KEY (set_id) REFERENCES coefficient_sets(id)
)""")

c.execute("""CREATE TABLE parameters (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
)""")

c.execute("INSERT INTO coefficient_sets VALUES (1, 'polar_express', 'Optimized coefficients for fast convergence')")
c.execute("INSERT INTO coefficient_sets VALUES (2, 'uniform', 'Uniform coefficients (15/8, -10/8, 3/8)')")

polar_express = [
    (4.0848, -6.8946, 2.9270),
    (3.9505, -6.3029, 2.6377),
    (3.7418, -5.5913, 2.3037),
    (2.8769, -3.1427, 1.2046),
    (2.8366, -3.0525, 1.2012),
]
for i, (a, b, cc) in enumerate(polar_express):
    c.execute("INSERT INTO coefficients VALUES (1, ?, ?, ?, ?)", (i, a, b, cc))

for i in range(5):
    c.execute("INSERT INTO coefficients VALUES (2, ?, ?, ?, ?)", (i, 1.875, -1.25, 0.375))

c.execute("INSERT INTO parameters VALUES ('test_perturbation', ?)", (json.dumps(-4e-4),))
c.execute("INSERT INTO parameters VALUES ('test_eigenvalues', ?)",
          (json.dumps([0.95, 0.8, 0.6, 0.4, 0.2, 0.05, 0.01, 0.001]),))

conn.commit()
conn.close()
print("Created /app/coefficients.db")
