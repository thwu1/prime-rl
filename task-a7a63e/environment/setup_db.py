#!/usr/bin/env python3
"""Create the sim-to-real evaluation SQLite database."""
import sqlite3
import os

DB_PATH = '/app/eval.db'
os.makedirs('/app', exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript('''
CREATE TABLE experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    robot TEXT NOT NULL,
    eval_date TEXT NOT NULL,
    status TEXT NOT NULL,
    n_trials_per_eval INTEGER
);

CREATE TABLE policies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT
);

CREATE TABLE approaches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL
);

CREATE TABLE variants (
    id INTEGER PRIMARY KEY,
    approach_id INTEGER NOT NULL REFERENCES approaches(id),
    name TEXT NOT NULL,
    weight REAL NOT NULL,
    condition_desc TEXT
);

CREATE TABLE sim_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    approach_id INTEGER NOT NULL REFERENCES approaches(id),
    variant_id INTEGER REFERENCES variants(id),
    policy_id INTEGER NOT NULL REFERENCES policies(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    success_rate REAL,
    n_trials INTEGER
);

CREATE TABLE real_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    policy_id INTEGER NOT NULL REFERENCES policies(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    success_rate REAL NOT NULL,
    n_trials INTEGER
);

CREATE TABLE analysis_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE experiment_notes (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_sim_results_lookup ON sim_results(experiment_id, approach_id, variant_id, task_id, policy_id);
CREATE INDEX idx_real_results_lookup ON real_results(experiment_id, task_id, policy_id);
''')

# -- Experiments --
c.execute("INSERT INTO experiments VALUES (1, 'eval_april_2024', 'Google Robot', '2024-04-15', 'production', 20)")
c.execute("INSERT INTO experiments VALUES (2, 'calibration_march_2024', 'Google Robot', '2024-03-01', 'calibration', 10)")

# -- Policies (alphabetical) --
for i, name in enumerate(['Octo-Base', 'Octo-Small', 'PolicyX', 'RT-1', 'RT-1-X'], 1):
    c.execute("INSERT INTO policies VALUES (?, ?)", (i, name))

# -- Tasks (alphabetical) --
tasks_data = [
    (1, 'close_drawer', 'manipulation'),
    (2, 'move_near', 'navigation'),
    (3, 'open_drawer', 'manipulation'),
    (4, 'pick_apple', 'grasping'),
    (5, 'pick_coke_can', 'grasping'),
    (6, 'push_buttons', 'contact'),
    (7, 'stack_blocks', 'stacking'),
]
for tid, name, cat in tasks_data:
    c.execute("INSERT INTO tasks VALUES (?, ?, ?)", (tid, name, cat))

# -- Approaches --
c.execute("INSERT INTO approaches VALUES (1, 'visual_matching', 'direct')")
c.execute("INSERT INTO approaches VALUES (2, 'variant_aggregation', 'aggregated')")

# -- Variants (for variant_aggregation approach) --
c.execute("INSERT INTO variants VALUES (1, 2, 'default_environment', 0.5, 'Default visual matching environment')")
c.execute("INSERT INTO variants VALUES (2, 2, 'green_table', 0.3, 'Green table background texture')")
c.execute("INSERT INTO variants VALUES (3, 2, 'dark_lighting', 0.2, 'Reduced ambient lighting to 40 percent')")

# -- Analysis configuration --
c.execute("INSERT INTO analysis_config VALUES ('bootstrap_seed', '42')")
c.execute("INSERT INTO analysis_config VALUES ('bootstrap_iterations', '1000')")

# -- Experiment notes --
c.execute("""INSERT INTO experiment_notes VALUES (1, 2, 'Dr. Chen',
    'Calibration run only - camera alignment and gripper offset testing. Do NOT include in production analysis. Several sensors were miscalibrated during this session.',
    '2024-03-02')""")
c.execute("""INSERT INTO experiment_notes VALUES (2, 1, 'Dr. Martinez',
    'Production evaluation complete. All sensors verified and calibrated. Results approved for publication.',
    '2024-04-16')""")
c.execute("""INSERT INTO experiment_notes VALUES (3, 2, 'Dr. Chen',
    'Follow-up: confirmed gripper offset was 2.3mm off-center during calibration session. All data from this experiment should be considered unreliable.',
    '2024-03-05')""")

# ====================================================================
# Helper to insert result rows
# ====================================================================
# Policy IDs: Octo-Base=1, Octo-Small=2, PolicyX=3, RT-1=4, RT-1-X=5
# Task IDs:   close_drawer=1, move_near=2, open_drawer=3, pick_apple=4,
#              pick_coke_can=5, push_buttons=6, stack_blocks=7

def insert_real(exp_id, data, n_trials):
    for task_id, policy_id, sr in data:
        c.execute(
            "INSERT INTO real_results (experiment_id, policy_id, task_id, success_rate, n_trials) "
            "VALUES (?, ?, ?, ?, ?)",
            (exp_id, policy_id, task_id, sr, n_trials))

def insert_sim(exp_id, approach_id, variant_id, data, n_trials):
    for task_id, policy_id, sr in data:
        c.execute(
            "INSERT INTO sim_results (experiment_id, approach_id, variant_id, policy_id, task_id, success_rate, n_trials) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (exp_id, approach_id, variant_id, policy_id, task_id, sr, n_trials))

# ====================================================================
# PRODUCTION real-world results (experiment 1)
# ====================================================================
real_prod = [
    # close_drawer (task 1)
    (1, 1, 0.60), (1, 2, 0.40), (1, 3, 0.48), (1, 4, 0.82), (1, 5, 0.75),
    # move_near (task 2)
    (2, 1, 0.35), (2, 2, 0.28), (2, 3, 0.45), (2, 4, 0.55), (2, 5, 0.62),
    # open_drawer (task 3)
    (3, 1, 0.30), (3, 2, 0.22), (3, 3, 0.38), (3, 4, 0.45), (3, 5, 0.52),
    # pick_apple (task 4)
    (4, 1, 0.48), (4, 2, 0.30), (4, 3, 0.40), (4, 4, 0.65), (4, 5, 0.58),
    # pick_coke_can (task 5)
    (5, 1, 0.41), (5, 2, 0.33), (5, 3, 0.52), (5, 4, 0.78), (5, 5, 0.72),
    # push_buttons (task 6)
    (6, 1, 0.38), (6, 2, 0.55), (6, 3, 0.42), (6, 4, 0.50), (6, 5, 0.45),
    # stack_blocks (task 7)
    (7, 1, 0.42), (7, 2, 0.18), (7, 3, 0.25), (7, 4, 0.38), (7, 5, 0.35),
]
insert_real(1, real_prod, 20)

# ====================================================================
# CALIBRATION real-world results (experiment 2) - biased/unreliable
# ====================================================================
real_cal = [
    (1, 1, 0.55), (1, 2, 0.35), (1, 3, 0.42), (1, 4, 0.75), (1, 5, 0.70),
    (2, 1, 0.40), (2, 2, 0.32), (2, 3, 0.50), (2, 4, 0.60), (2, 5, 0.58),
    (3, 1, 0.25), (3, 2, 0.18), (3, 3, 0.33), (3, 4, 0.40), (3, 5, 0.48),
    (4, 1, 0.52), (4, 2, 0.35), (4, 3, 0.45), (4, 4, 0.70), (4, 5, 0.62),
    (5, 1, 0.38), (5, 2, 0.30), (5, 3, 0.48), (5, 4, 0.72), (5, 5, 0.68),
    (6, 1, 0.42), (6, 2, 0.50), (6, 3, 0.45), (6, 4, 0.55), (6, 5, 0.48),
    (7, 1, 0.38), (7, 2, 0.15), (7, 3, 0.22), (7, 4, 0.35), (7, 5, 0.30),
]
insert_real(2, real_cal, 10)

# ====================================================================
# PRODUCTION visual_matching sim results (experiment 1, approach 1, no variant)
# ====================================================================
vm_prod = [
    # close_drawer
    (1, 1, 0.50), (1, 2, 0.42), (1, 3, 0.58), (1, 4, 0.85), (1, 5, 0.78),
    # move_near
    (2, 1, 0.32), (2, 2, 0.25), (2, 3, 0.48), (2, 4, 0.62), (2, 5, 0.55),
    # open_drawer
    (3, 1, 0.28), (3, 2, 0.20), (3, 3, 0.35), (3, 4, 0.42), (3, 5, 0.48),
    # pick_apple
    (4, 1, 0.42), (4, 2, 0.42), (4, 3, 0.48), (4, 4, 0.70), (4, 5, 0.55),
    # pick_coke_can
    (5, 1, 0.50), (5, 2, 0.30), (5, 3, 0.38), (5, 4, 0.80), (5, 5, 0.74),
    # push_buttons -- ALL IDENTICAL (degenerate: zero-variance sim predictions)
    (6, 1, 0.40), (6, 2, 0.40), (6, 3, 0.40), (6, 4, 0.40), (6, 5, 0.40),
    # stack_blocks
    (7, 1, 0.45), (7, 2, 0.15), (7, 3, 0.22), (7, 4, 0.35), (7, 5, 0.32),
]
insert_sim(1, 1, None, vm_prod, 20)

# ====================================================================
# CALIBRATION visual_matching sim results (experiment 2, approach 1)
# ====================================================================
vm_cal = [
    (1, 1, 0.48), (1, 2, 0.38), (1, 3, 0.52), (1, 4, 0.80), (1, 5, 0.72),
    (2, 1, 0.30), (2, 2, 0.22), (2, 3, 0.45), (2, 4, 0.58), (2, 5, 0.52),
    (3, 1, 0.25), (3, 2, 0.18), (3, 3, 0.32), (3, 4, 0.38), (3, 5, 0.45),
    (4, 1, 0.40), (4, 2, 0.38), (4, 3, 0.42), (4, 4, 0.65), (4, 5, 0.52),
    (5, 1, 0.45), (5, 2, 0.28), (5, 3, 0.35), (5, 4, 0.75), (5, 5, 0.70),
    (6, 1, 0.38), (6, 2, 0.38), (6, 3, 0.38), (6, 4, 0.38), (6, 5, 0.38),
    (7, 1, 0.42), (7, 2, 0.12), (7, 3, 0.20), (7, 4, 0.32), (7, 5, 0.28),
]
insert_sim(2, 1, None, vm_cal, 10)

# ====================================================================
# PRODUCTION variant 1 sim results (experiment 1, approach 2, variant 1)
# ====================================================================
v1_prod = [
    (1, 1, 0.50), (1, 2, 0.42), (1, 3, 0.58), (1, 4, 0.85), (1, 5, 0.78),
    (2, 1, 0.32), (2, 2, 0.25), (2, 3, 0.48), (2, 4, 0.62), (2, 5, 0.55),
    (3, 1, 0.28), (3, 2, 0.20), (3, 3, 0.35), (3, 4, 0.42), (3, 5, 0.48),
    (4, 1, 0.42), (4, 2, 0.42), (4, 3, 0.48), (4, 4, 0.70), (4, 5, 0.55),
    (5, 1, 0.50), (5, 2, 0.30), (5, 3, 0.38), (5, 4, 0.80), (5, 5, 0.74),
    (6, 1, 0.38), (6, 2, 0.55), (6, 3, 0.42), (6, 4, 0.52), (6, 5, 0.48),
    (7, 1, 0.45), (7, 2, 0.15), (7, 3, 0.22), (7, 4, 0.35), (7, 5, 0.32),
]
insert_sim(1, 2, 1, v1_prod, 20)

# ====================================================================
# PRODUCTION variant 2 sim results (experiment 1, approach 2, variant 2)
# NOTE: some entries are NULL (missing measurements)
# ====================================================================
v2_prod = [
    # close_drawer -- Octo-Small (policy 2) is NULL
    (1, 1, 0.55), (1, 2, None), (1, 3, 0.50), (1, 4, 0.70), (1, 5, 0.75),
    # move_near
    (2, 1, 0.38), (2, 2, 0.30), (2, 3, 0.42), (2, 4, 0.50), (2, 5, 0.58),
    # open_drawer
    (3, 1, 0.32), (3, 2, 0.28), (3, 3, 0.30), (3, 4, 0.35), (3, 5, 0.40),
    # pick_apple
    (4, 1, 0.40), (4, 2, 0.38), (4, 3, 0.44), (4, 4, 0.62), (4, 5, 0.52),
    # pick_coke_can
    (5, 1, 0.45), (5, 2, 0.35), (5, 3, 0.40), (5, 4, 0.68), (5, 5, 0.72),
    # push_buttons
    (6, 1, 0.35), (6, 2, 0.48), (6, 3, 0.38), (6, 4, 0.45), (6, 5, 0.42),
    # stack_blocks
    (7, 1, 0.40), (7, 2, 0.18), (7, 3, 0.20), (7, 4, 0.30), (7, 5, 0.28),
]
insert_sim(1, 2, 2, v2_prod, 20)

# ====================================================================
# PRODUCTION variant 3 sim results (experiment 1, approach 2, variant 3)
# NOTE: some entries are NULL (missing measurements)
# ====================================================================
v3_prod = [
    # close_drawer
    (1, 1, 0.52), (1, 2, 0.42), (1, 3, 0.45), (1, 4, 0.65), (1, 5, 0.70),
    # move_near
    (2, 1, 0.35), (2, 2, 0.28), (2, 3, 0.38), (2, 4, 0.45), (2, 5, 0.52),
    # open_drawer
    (3, 1, 0.28), (3, 2, 0.25), (3, 3, 0.26), (3, 4, 0.30), (3, 5, 0.38),
    # pick_apple -- Octo-Small (policy 2) is NULL
    (4, 1, 0.35), (4, 2, None), (4, 3, 0.40), (4, 4, 0.55), (4, 5, 0.48),
    # pick_coke_can
    (5, 1, 0.42), (5, 2, 0.32), (5, 3, 0.35), (5, 4, 0.60), (5, 5, 0.65),
    # push_buttons
    (6, 1, 0.30), (6, 2, 0.45), (6, 3, 0.35), (6, 4, 0.40), (6, 5, 0.38),
    # stack_blocks
    (7, 1, 0.38), (7, 2, 0.12), (7, 3, 0.15), (7, 4, 0.25), (7, 5, 0.22),
]
insert_sim(1, 2, 3, v3_prod, 20)

# ====================================================================
# CALIBRATION variant sim results (experiment 2, approach 2)
# Only variant 1 was tested during calibration
# ====================================================================
v1_cal = [
    (1, 1, 0.45), (1, 2, 0.35), (1, 3, 0.52), (1, 4, 0.78), (1, 5, 0.72),
    (2, 1, 0.28), (2, 2, 0.20), (2, 3, 0.42), (2, 4, 0.55), (2, 5, 0.50),
    (3, 1, 0.22), (3, 2, 0.15), (3, 3, 0.30), (3, 4, 0.38), (3, 5, 0.42),
    (4, 1, 0.38), (4, 2, 0.35), (4, 3, 0.42), (4, 4, 0.62), (4, 5, 0.50),
    (5, 1, 0.42), (5, 2, 0.25), (5, 3, 0.32), (5, 4, 0.70), (5, 5, 0.65),
    (6, 1, 0.32), (6, 2, 0.48), (6, 3, 0.38), (6, 4, 0.48), (6, 5, 0.42),
    (7, 1, 0.40), (7, 2, 0.10), (7, 3, 0.18), (7, 4, 0.30), (7, 5, 0.25),
]
insert_sim(2, 2, 1, v1_cal, 10)

conn.commit()
conn.close()
print(f"Database created at {DB_PATH}")
