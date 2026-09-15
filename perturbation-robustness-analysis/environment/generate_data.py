#!/usr/bin/env python3
"""Generate SQLite benchmark database with rollout-level evaluation data.

Creates a realistic evaluation database with data quality issues:
- Duplicate rollout entries from a pipeline restart (specific model/task/perturbation combos)
- Calibration trials (trial_id < 0) that are not valid evaluation data
- A convenience view (rollout_summary) that does NOT handle deduplication
"""
import sqlite3
import math
import os


def main():
    os.makedirs('/app/data', exist_ok=True)

    db_path = '/app/data/benchmark.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ---- Schema ----
    c.execute('''CREATE TABLE rollouts (
        model TEXT NOT NULL,
        task_id INTEGER NOT NULL,
        perturbation_id INTEGER NOT NULL,
        rollout_id INTEGER NOT NULL,
        success INTEGER NOT NULL CHECK(success IN (0, 1))
    )''')

    c.execute('''CREATE TABLE real_trials (
        model TEXT NOT NULL,
        task_id INTEGER NOT NULL,
        trial_id INTEGER NOT NULL,
        success INTEGER NOT NULL CHECK(success IN (0, 1))
    )''')

    c.execute('''CREATE TABLE task_meta (
        task_id INTEGER PRIMARY KEY,
        task_name TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE perturbation_meta (
        perturbation_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE collection_notes (
        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL
    )''')

    # ---- Convenience view (pre-QA — does NOT deduplicate!) ----
    c.execute('''CREATE VIEW rollout_summary AS
        SELECT model, task_id, perturbation_id,
               COUNT(*) as n_rollouts,
               SUM(success) as n_successes,
               CAST(SUM(success) AS REAL) / COUNT(*) as success_rate
        FROM rollouts
        GROUP BY model, task_id, perturbation_id
    ''')

    # ---- Task metadata ----
    tasks = [
        (0, 'put_block_in_bowl'),
        (1, 'put_banana_into_box'),
        (2, 'rotate_marker'),
        (3, 'rotate_mug'),
        (4, 'pick_spoon'),
        (5, 'pick_bottle'),
        (6, 'stack_cubes'),
        (7, 'push_switch'),
    ]
    for tid, tname in tasks:
        c.execute('INSERT INTO task_meta VALUES (?, ?)', (tid, tname))

    # ---- Perturbation metadata ----
    perturbations = [
        (0, 'Default', 'Baseline'),
        (1, 'V-AUG', 'Visual'),
        (2, 'V-VIEW', 'Visual'),
        (3, 'V-SC', 'Visual'),
        (4, 'V-LIGHT', 'Visual'),
        (5, 'S-PROP', 'Semantic'),
        (6, 'S-LANG', 'Semantic'),
        (7, 'S-MO', 'Semantic'),
        (8, 'S-AFF', 'Semantic'),
        (9, 'S-INT', 'Semantic'),
        (10, 'B-HOBJ', 'Behavioral'),
        (11, 'SB-NOUN', 'Cross-SB'),
        (12, 'SB-VRB', 'Cross-SB'),
        (13, 'VB-POSE', 'Cross-VB'),
        (14, 'VB-MOBJ', 'Cross-VB'),
        (15, 'VSB-NOBJ', 'Cross-VSB'),
    ]
    for pid, pname, pcat in perturbations:
        c.execute('INSERT INTO perturbation_meta VALUES (?, ?, ?)',
                  (pid, pname, pcat))

    # ---- Model parameters ----
    models = ['ModelA', 'ModelB', 'ModelC']
    model_idx = {'ModelA': 0, 'ModelB': 1, 'ModelC': 2}

    base_rates = {0: 0.44, 1: 0.61, 2: 0.22}
    task_offsets = {
        0: -0.10, 1: -0.06, 2: -0.03, 3: 0.00,
        4: 0.02, 5: 0.05, 6: 0.08, 7: 0.12,
    }
    pert_effects = {
        0: {0: 0.0, 1: -0.02, 2: 0.06, 3: -0.01, 4: -0.08,
            5: -0.14, 6: -0.07, 7: -0.10, 8: -0.13, 9: -0.14,
            10: -0.11, 11: -0.15, 12: -0.07, 13: -0.11,
            14: -0.05, 15: -0.26},
        1: {0: 0.0, 1: 0.02, 2: 0.08, 3: -0.01, 4: -0.06,
            5: -0.07, 6: -0.01, 7: -0.05, 8: -0.05, 9: -0.06,
            10: -0.21, 11: -0.20, 12: -0.03, 13: -0.11,
            14: -0.08, 15: -0.33},
        2: {0: 0.0, 1: -0.03, 2: 0.05, 3: 0.03, 4: -0.05,
            5: -0.04, 6: 0.03, 7: -0.03, 8: 0.02, 9: -0.04,
            10: -0.06, 11: -0.05, 12: 0.03, 13: -0.11,
            14: -0.09, 15: -0.12},
    }

    n_rollouts = 25

    # (model, perturbation_id, task_id) combos double-ingested during restart
    dup_combos = {
        ('ModelB', 10, 2),
        ('ModelB', 10, 5),
        ('ModelA', 7, 3),
    }

    # ---- Populate rollouts ----
    for mname in models:
        mi = model_idx[mname]
        for ti, _ in tasks:
            for pi, _, _ in perturbations:
                mean_rate = (base_rates[mi] + task_offsets[ti]
                             + pert_effects[mi][pi])
                interaction = 0.025 * math.sin(mi * 7 + ti * 13 + pi * 19)
                rate = max(0.04, min(0.96, mean_rate + interaction))
                n_succ = max(1, min(24, round(rate * n_rollouts)))

                for rid in range(n_rollouts):
                    success = 1 if rid < n_succ else 0
                    c.execute(
                        'INSERT INTO rollouts VALUES (?, ?, ?, ?, ?)',
                        (mname, ti, pi, rid, success))

                # Insert duplicates for affected combos
                if (mname, pi, ti) in dup_combos:
                    for rid in range(5):
                        success = 1 if rid < n_succ else 0
                        c.execute(
                            'INSERT INTO rollouts VALUES (?, ?, ?, ?, ?)',
                            (mname, ti, pi, rid, success))

    # ---- Populate real_trials ----
    for mname in models:
        mi = model_idx[mname]
        for ti, _ in tasks:
            sim_default = base_rates[mi] + task_offsets[ti]
            noise = 0.03 * math.cos(mi * 11 + ti * 17)
            real_rate = max(0.05, min(0.95,
                                      sim_default * 0.88 + 0.06 + noise))
            n_trials = 10
            n_succ = max(0, min(10, round(real_rate * n_trials)))

            # Valid evaluation trials (trial_id 0..9)
            for trid in range(n_trials):
                success = 1 if trid < n_succ else 0
                c.execute('INSERT INTO real_trials VALUES (?, ?, ?, ?)',
                          (mname, ti, trid, success))

            # Calibration / warm-up trials (NOT valid evaluation data)
            for cal_id in [-1, -2]:
                cal_success = 1 if ti % 2 == 0 else 0
                c.execute('INSERT INTO real_trials VALUES (?, ?, ?, ?)',
                          (mname, ti, cal_id, cal_success))

    # ---- Collection notes ----
    notes = [
        ('2025-01-15 09:30:00', 'data_eng',
         'Initial data load complete. 384 rollout batches '
         '(3 models x 8 tasks x 16 conditions) ingested from cluster '
         'evaluation logs. Each batch = 25 rollouts.'),
        ('2025-01-15 10:15:00', 'data_eng',
         'Created rollout_summary view for quick aggregate queries. '
         'Reminder: this was set up before QA review of the raw data.'),
        ('2025-01-15 14:22:00', 'data_eng',
         'Real-world trial data loaded. Note: calibration trials '
         '(trial_id < 0) are retained for audit purposes — these are '
         'equipment warm-up runs, not valid evaluation trials.'),
        ('2025-01-16 11:05:00', 'qa_analyst',
         'ALERT: The ingestion pipeline restarted on 01/14 due to a '
         'cluster failover. Some rollout batches may have been partially '
         're-ingested, resulting in duplicate entries sharing the same '
         '(model, task, perturbation, rollout_id). A few spot checks '
         'confirm duplicates exist but the full scope is unknown. '
         'The rollout_summary view does NOT account for this. '
         'Recommend deduplication before any analysis.'),
    ]
    for ts, author, content in notes:
        c.execute(
            'INSERT INTO collection_notes '
            '(timestamp, author, content) VALUES (?, ?, ?)',
            (ts, author, content))

    conn.commit()
    conn.close()
    print(f"Database created at {db_path}")


if __name__ == '__main__':
    main()
