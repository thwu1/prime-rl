#!/usr/bin/env python3
"""Create the experiment SQLite database."""
import sqlite3

conn = sqlite3.connect("/app/data/experiment.db")
c = conn.cursor()

c.execute("CREATE TABLE trial_counts (source TEXT PRIMARY KEY, n_episodes INTEGER NOT NULL)")
c.execute("INSERT INTO trial_counts VALUES ('simulation', 100)")
c.execute("INSERT INTO trial_counts VALUES ('real_world', 50)")

c.execute("CREATE TABLE analysis_params (param_name TEXT PRIMARY KEY, param_value REAL NOT NULL)")
c.execute("INSERT INTO analysis_params VALUES ('permutation_seed', 99)")
c.execute("INSERT INTO analysis_params VALUES ('n_permutations', 50000)")
c.execute("INSERT INTO analysis_params VALUES ('confidence_level', 0.90)")

c.execute("""CREATE TABLE variant_info (
    variant_id INTEGER PRIMARY KEY,
    variant_name TEXT NOT NULL UNIQUE,
    description TEXT
)""")
c.execute("INSERT INTO variant_info VALUES (1, 'visual_match_standard', 'Standard visual matching conditions')")
c.execute("INSERT INTO variant_info VALUES (2, 'visual_match_alt_lighting', 'Alternative lighting conditions')")
c.execute("INSERT INTO variant_info VALUES (3, 'visual_match_alt_texture', 'Alternative object textures')")
c.execute("INSERT INTO variant_info VALUES (4, 'background_change', 'Changed background environment')")

conn.commit()
conn.close()
print("Created /app/data/experiment.db")
