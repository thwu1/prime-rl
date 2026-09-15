#!/usr/bin/env python3
"""Set up the pipeline environment: SQLite database and log files."""

import sqlite3
import os

# --- Create SQLite database ---
os.makedirs('/app/meta', exist_ok=True)
conn = sqlite3.connect('/app/meta/pipeline.db')
c = conn.cursor()

# Data generation parameters
c.execute('CREATE TABLE params (key TEXT PRIMARY KEY, value TEXT)')
c.executemany('INSERT INTO params VALUES (?, ?)', [
    ('seed', '42'),
    ('n_samples', '2000'),
    ('ar_coefficient', '0.99'),
    ('label_horizon', '50'),
    ('n_informative', '10'),
    ('n_redundant', '10'),
    ('n_noise', '20'),
])

# Historical runs
c.execute('''CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT, cv_score REAL, n_splits INTEGER,
    shuffle INTEGER, notes TEXT
)''')
c.executemany(
    'INSERT INTO runs (timestamp, cv_score, n_splits, shuffle, notes) VALUES (?,?,?,?,?)',
    [
        ('2024-01-10 09:15:22', -0.312, 5, 1, 'Initial run with default settings'),
        ('2024-01-12 14:32:45', -0.298, 5, 1, 'Increased n_estimators to 200'),
        ('2024-01-13 11:08:17', -0.285, 10, 1, 'More folds — score keeps improving'),
        ('2024-01-14 16:44:33', -0.301, 5, 1, 'Score still looks suspiciously good'),
        ('2024-01-15 10:22:11', -0.293, 5, 1, 'FLAGGED: scores appear inflated vs hold-out'),
    ]
)

# Researcher notes
c.execute('''CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT, timestamp TEXT, content TEXT
)''')
c.executemany('INSERT INTO notes (author, timestamp, content) VALUES (?,?,?)', [
    ('jchen', '2024-01-15 14:30:00',
     'CV scores around -0.3 seem too optimistic for this signal type. '
     'Hold-out evaluation on unseen data gives approximately -0.65. '
     'Possible evaluation methodology issue.'),
    ('mwang', '2024-01-15 16:45:00',
     'Labels use a multi-bar forward horizon creating significant temporal '
     'overlap between adjacent observations. Current CV setup may not '
     'account for this overlap structure.'),
    ('jchen', '2024-01-16 09:10:00',
     'The bootstrap sampling treats all samples as independent draws, but '
     'the label overlap means adjacent samples share information. '
     'Sample independence assumptions may be violated.'),
])

conn.commit()
conn.close()

# --- Create log file ---
os.makedirs('/app/logs', exist_ok=True)
with open('/app/logs/run_20240115_143022.log', 'w') as f:
    f.write(
        "2024-01-15 14:30:22 INFO  Pipeline v0.3.1 starting\n"
        "2024-01-15 14:30:22 INFO  Config: /app/config.toml + /app/meta/pipeline.db\n"
        "2024-01-15 14:30:22 INFO  Data generation: seed=42\n"
        "2024-01-15 14:30:23 INFO  Feature matrix: (2000, 40) "
        "[10 informative, 10 redundant, 20 noise]\n"
        "2024-01-15 14:30:23 WARN  High autocorrelation detected: "
        "lag-1 r=0.989 (Ljung-Box p<0.001)\n"
        "2024-01-15 14:30:23 WARN  Label overlap: mean 49.5 concurrent labels per bar\n"
        "2024-01-15 14:30:24 INFO  Cross-validation: 5-fold KFold(shuffle=True)\n"
        "2024-01-15 14:30:35 INFO  Fold 1: neg_log_loss = -0.287\n"
        "2024-01-15 14:30:46 INFO  Fold 2: neg_log_loss = -0.301\n"
        "2024-01-15 14:30:57 INFO  Fold 3: neg_log_loss = -0.295\n"
        "2024-01-15 14:31:08 INFO  Fold 4: neg_log_loss = -0.284\n"
        "2024-01-15 14:31:19 INFO  Fold 5: neg_log_loss = -0.308\n"
        "2024-01-15 14:31:19 INFO  Mean CV score: -0.295\n"
        "2024-01-15 14:31:19 WARN  Mean CV score appears unusually optimistic "
        "for this signal type\n"
        "2024-01-15 14:31:20 INFO  Bootstrap: 2000 random draws, "
        "mean uniqueness = 0.632\n"
        "2024-01-15 14:31:25 INFO  Top-5 features by MDI: "
        "I_0=0.081, I_1=0.074, R_0=0.062, I_2=0.058, R_1=0.055\n"
        "2024-01-15 14:31:25 INFO  Results written to /app/results.json\n"
    )

print("Environment setup complete.")
