import sqlite3
import json

conn = sqlite3.connect('/app/analysis.db')
c = conn.cursor()

c.executescript('''
CREATE TABLE grids (
    id INTEGER PRIMARY KEY,
    grid_text TEXT NOT NULL,
    source TEXT
);

CREATE TABLE ua_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_id INTEGER,
    cells TEXT NOT NULL,
    size INTEGER NOT NULL,
    is_verified BOOLEAN DEFAULT 0
);

CREATE TABLE clique_analysis (
    grid_id INTEGER,
    mcn INTEGER,
    max_clique_indices TEXT,
    clique_counts TEXT,
    is_valid BOOLEAN DEFAULT 0
);

CREATE TABLE run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_id INTEGER,
    timestamp TEXT DEFAULT (datetime('now')),
    stage TEXT,
    status TEXT,
    message TEXT
);
''')

grid = '534678912672195348198342567859761423426853791713924856961537284287419635345286179'
c.execute("INSERT INTO grids VALUES (1, ?, 'McGuire catalog')", (grid,))

c.execute("INSERT INTO clique_analysis VALUES (1, 3, '[14, 67, 188]', '{}', 0)")

logs = [
    (1, 'ua_finder', 'completed', 'Found 202 2-digit UA sets (sizes 4-12)'),
    (1, 'ua_finder', 'warning', 'Count lower than expected for typical grid (~250-350 2-digit sets)'),
    (1, 'clique_finder', 'completed', 'MCN=3'),
    (1, 'validation', 'failed', 'Clique members at indices 14 and 67 share cells — not disjoint'),
    (1, 'validation', 'failed', 'MCN result unreliable, stored with is_valid=0'),
]
for grid_id, stage, status, msg in logs:
    c.execute("INSERT INTO run_log (grid_id, stage, status, message) VALUES (?, ?, ?, ?)",
              (grid_id, stage, status, msg))

conn.commit()
conn.close()
