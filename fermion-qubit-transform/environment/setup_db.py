"""Create SQLite database with molecular integral data."""
import sqlite3
import os

os.makedirs("/app", exist_ok=True)

conn = sqlite3.connect("/app/molecules.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE molecular_systems (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    n_spatial_orbitals INTEGER NOT NULL,
    n_electrons INTEGER NOT NULL,
    nuclear_repulsion REAL NOT NULL,
    integral_notation TEXT DEFAULT 'physicist'
)
""")

cursor.execute("""
CREATE TABLE one_body (
    system_id INTEGER NOT NULL,
    p INTEGER NOT NULL,
    q INTEGER NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (system_id) REFERENCES molecular_systems(id)
)
""")

cursor.execute("""
CREATE TABLE two_body (
    system_id INTEGER NOT NULL,
    p INTEGER NOT NULL,
    q INTEGER NOT NULL,
    r INTEGER NOT NULL,
    s INTEGER NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (system_id) REFERENCES molecular_systems(id)
)
""")

cursor.execute("""
CREATE INDEX idx_one_body_system ON one_body(system_id)
""")
cursor.execute("""
CREATE INDEX idx_two_body_system ON two_body(system_id)
""")

# System 1: 2-site Hubbard model (t=0.85, U=2.3)
cursor.execute("""
INSERT INTO molecular_systems (name, description, n_spatial_orbitals, n_electrons, nuclear_repulsion, integral_notation)
VALUES ('hubbard_2site', '2-site Hubbard model, open boundary, t=0.85, U=2.3', 2, 2, 0.37, 'physicist')
""")
s1 = cursor.lastrowid

for p, q, v in [(0, 1, -0.85), (1, 0, -0.85)]:
    cursor.execute("INSERT INTO one_body VALUES (?, ?, ?, ?)", (s1, p, q, v))

for p, q, r, s, v in [(0, 0, 0, 0, 2.3), (1, 1, 1, 1, 2.3)]:
    cursor.execute("INSERT INTO two_body VALUES (?, ?, ?, ?, ?, ?)", (s1, p, q, r, s, v))

# System 2: 3-site Hubbard model (t=1.0, U=3.7)
cursor.execute("""
INSERT INTO molecular_systems (name, description, n_spatial_orbitals, n_electrons, nuclear_repulsion, integral_notation)
VALUES ('hubbard_3site', '3-site Hubbard model, open boundary, t=1.0, U=3.7', 3, 3, 0.0, 'physicist')
""")
s2 = cursor.lastrowid

for p, q, v in [(0, 1, -1.0), (1, 0, -1.0), (1, 2, -1.0), (2, 1, -1.0)]:
    cursor.execute("INSERT INTO one_body VALUES (?, ?, ?, ?)", (s2, p, q, v))

for p, q, r, s, v in [(0, 0, 0, 0, 3.7), (1, 1, 1, 1, 3.7), (2, 2, 2, 2, 3.7)]:
    cursor.execute("INSERT INTO two_body VALUES (?, ?, ?, ?, ?, ?)", (s2, p, q, r, s, v))

conn.commit()
conn.close()
