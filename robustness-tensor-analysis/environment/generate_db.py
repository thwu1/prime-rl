#!/usr/bin/env python3
"""Generate SQLite benchmark database from published REALM results."""
import sqlite3
import os

MODEL_NAMES = ["pi0", "pi0_fast", "groot_n15"]

PERTURBATION_INFO = [
    (0, "default"), (1, "v_aug"), (2, "v_view"), (3, "v_sc"), (4, "v_light"),
    (5, "s_prop"), (6, "s_lang"), (7, "s_mo"), (8, "s_aff"), (9, "s_int"),
    (10, "b_hobj"), (11, "sb_noun"), (12, "sb_vrb"), (13, "vb_pose"),
    (14, "vb_mobj"), (15, "vsb_nobj")
]

TASK_INFO = [
    (0, "put_green_block_in_bowl"), (1, "put_banana_into_box"),
    (2, "rotate_marker"), (3, "rotate_mug"), (4, "pick_spoon"),
    (5, "pick_water_bottle"), (6, "stack_cubes"), (7, "push_switch"),
    (8, "open_drawer"), (9, "close_drawer")
]

MEAN_RATES = {
    "pi0": [0.44, 0.42, 0.52, 0.43, 0.37, 0.29, 0.36, 0.35, 0.30, 0.29,
            0.32, 0.28, 0.36, 0.32, 0.38, 0.16],
    "pi0_fast": [0.61, 0.64, 0.70, 0.60, 0.54, 0.53, 0.61, 0.55, 0.55, 0.54,
                 0.38, 0.39, 0.57, 0.49, 0.53, 0.26],
    "groot_n15": [0.19, 0.19, 0.19, 0.21, 0.16, 0.21, 0.21, 0.20, 0.21, 0.20,
                  0.16, 0.17, 0.21, 0.07, 0.09, 0.09]
}

TASK_MULTIPLIERS = [1.15, 0.85, 1.05, 0.80, 1.25, 1.10, 0.70, 1.05, 0.95, 1.10]

TOTAL_ROLLOUTS = 25


def generate():
    os.makedirs("/app/data", exist_ok=True)
    conn = sqlite3.connect("/app/data/benchmark.db")
    conn.execute("""
        CREATE TABLE results (
            model TEXT NOT NULL,
            perturbation_id INTEGER NOT NULL,
            perturbation_name TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            successes INTEGER NOT NULL,
            total_rollouts INTEGER NOT NULL,
            PRIMARY KEY (model, perturbation_id, task_id)
        )
    """)

    for model in MODEL_NAMES:
        for p_id, p_name in PERTURBATION_INFO:
            base_rate = MEAN_RATES[model][p_id]
            for t_id, t_name in TASK_INFO:
                rate = base_rate * TASK_MULTIPLIERS[t_id]
                successes = max(0, min(TOTAL_ROLLOUTS, round(rate * TOTAL_ROLLOUTS)))
                conn.execute(
                    "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (model, p_id, p_name, t_id, t_name, successes, TOTAL_ROLLOUTS)
                )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    generate()
