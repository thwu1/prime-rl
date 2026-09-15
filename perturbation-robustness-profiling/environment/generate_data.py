#!/usr/bin/env python3
"""Generate experiment SQLite database and real-world validation CSV files."""

import csv
import os
import random
import sqlite3

MODELS = ["pi0", "pi0_fast", "groot_n15"]
TASKS = [
    "put_green_block_in_bowl", "put_banana_into_box", "rotate_marker",
    "rotate_mug", "pick_spoon", "pick_water_bottle", "stack_cubes",
    "push_switch", "open_drawer", "close_drawer"
]
PERTURBATIONS = [
    "default", "v_aug", "v_view", "v_sc", "v_light",
    "s_prop", "s_lang", "s_mo", "s_aff", "s_int",
    "b_hobj", "sb_noun", "sb_vrb", "vb_pose", "vb_mobj", "vsb_nobj"
]
PERTURBATION_CATEGORY_MAP = {
    "default": "baseline",
    "v_aug": "visual", "v_view": "visual", "v_sc": "visual", "v_light": "visual",
    "s_prop": "semantic", "s_lang": "semantic", "s_mo": "semantic",
    "s_aff": "semantic", "s_int": "semantic",
    "b_hobj": "behavioral",
    "sb_noun": "combined", "sb_vrb": "combined", "vb_pose": "combined",
    "vb_mobj": "combined", "vsb_nobj": "combined"
}
COMBINED_COMPONENTS = {
    "sb_noun": ["semantic", "behavioral"],
    "sb_vrb": ["semantic", "behavioral"],
    "vb_pose": ["visual", "behavioral"],
    "vb_mobj": ["visual", "behavioral"],
    "vsb_nobj": ["visual", "semantic", "behavioral"]
}

MEAN_RATES = {
    "pi0": {
        "default": 0.44, "v_aug": 0.42, "v_view": 0.52, "v_sc": 0.43,
        "v_light": 0.37, "s_prop": 0.29, "s_lang": 0.36, "s_mo": 0.35,
        "s_aff": 0.30, "s_int": 0.29, "b_hobj": 0.32, "sb_noun": 0.28,
        "sb_vrb": 0.36, "vb_pose": 0.32, "vb_mobj": 0.38, "vsb_nobj": 0.16
    },
    "pi0_fast": {
        "default": 0.61, "v_aug": 0.64, "v_view": 0.70, "v_sc": 0.60,
        "v_light": 0.54, "s_prop": 0.53, "s_lang": 0.61, "s_mo": 0.55,
        "s_aff": 0.55, "s_int": 0.54, "b_hobj": 0.38, "sb_noun": 0.39,
        "sb_vrb": 0.57, "vb_pose": 0.49, "vb_mobj": 0.53, "vsb_nobj": 0.26
    },
    "groot_n15": {
        "default": 0.19, "v_aug": 0.19, "v_view": 0.19, "v_sc": 0.21,
        "v_light": 0.16, "s_prop": 0.21, "s_lang": 0.21, "s_mo": 0.20,
        "s_aff": 0.21, "s_int": 0.20, "b_hobj": 0.16, "sb_noun": 0.17,
        "sb_vrb": 0.21, "vb_pose": 0.07, "vb_mobj": 0.09, "vsb_nobj": 0.09
    }
}

TASK_FACTORS = {
    "put_green_block_in_bowl": 1.15,
    "put_banana_into_box": 1.05,
    "rotate_marker": 0.85,
    "rotate_mug": 0.90,
    "pick_spoon": 1.20,
    "pick_water_bottle": 1.10,
    "stack_cubes": 0.70,
    "push_switch": 0.95,
    "open_drawer": 1.00,
    "close_drawer": 1.10
}

N_SIM_ROLLOUTS = 25
N_REAL_ROLLOUTS = 10
REAL_TASKS = ["put_green_block_in_bowl", "put_banana_into_box", "pick_spoon"]
REAL_PERTS = ["default", "v_aug", "v_light", "s_prop", "b_hobj"]


def generate_rollouts(prob, n):
    return [1 if random.random() < prob else 0 for _ in range(n)]


def main():
    os.makedirs("/app/real_validation", exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)

    db_path = "/app/experiment.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create schema
    cur.executescript("""
        CREATE TABLE models (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            difficulty_factor REAL NOT NULL
        );

        CREATE TABLE perturbations (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL
        );

        CREATE TABLE combined_components (
            perturbation_id INTEGER REFERENCES perturbations(id),
            component_category TEXT NOT NULL,
            PRIMARY KEY (perturbation_id, component_category)
        );

        CREATE TABLE sim_rollouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES models(id),
            task_id INTEGER REFERENCES tasks(id),
            perturbation_id INTEGER REFERENCES perturbations(id),
            rollout_num INTEGER NOT NULL,
            success INTEGER NOT NULL CHECK(success IN (0, 1))
        );

        CREATE TABLE analysis_params (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT
        );
    """)

    # Insert models
    for i, model in enumerate(MODELS):
        cur.execute("INSERT INTO models VALUES (?, ?)", (i + 1, model))

    # Insert tasks
    for i, task in enumerate(TASKS):
        cur.execute("INSERT INTO tasks VALUES (?, ?, ?)",
                    (i + 1, task, TASK_FACTORS[task]))

    # Insert perturbations
    for i, pert in enumerate(PERTURBATIONS):
        cat = PERTURBATION_CATEGORY_MAP[pert]
        cur.execute("INSERT INTO perturbations VALUES (?, ?, ?)",
                    (i + 1, pert, cat))

    # Insert combined perturbation component mappings
    for pert_name, components in COMBINED_COMPONENTS.items():
        pert_id = PERTURBATIONS.index(pert_name) + 1
        for comp_cat in components:
            cur.execute("INSERT INTO combined_components VALUES (?, ?)",
                        (pert_id, comp_cat))

    # Insert analysis parameters (the correct specifications)
    params = [
        ("bootstrap_seed", "999",
         "Random seed for bootstrap resampling"),
        ("bootstrap_n_resamples", "1000",
         "Number of bootstrap resamples"),
        ("permutation_n", "1000",
         "Number of permutations for hypothesis tests"),
        ("confidence_level", "0.95",
         "Confidence level for all intervals"),
        ("ci_method", "wilson",
         "Method for binomial proportion CIs (wilson score interval)"),
        ("rank_correlation", "kendall_tau_b",
         "Rank correlation variant (tau-b handles ties correctly)"),
        ("permutation_test_type", "two_sided",
         "Permutation test sidedness for interaction analysis"),
        ("coalition_value_aggregation", "pool_perturbations",
         "Value function pools all perturbations in coalition categories, "
         "not per-category averaging"),
    ]
    for key, val, desc in params:
        cur.execute("INSERT INTO analysis_params VALUES (?, ?, ?)",
                    (key, val, desc))

    # Generate simulation rollout data
    random.seed(42)
    for model in MODELS:
        model_id = MODELS.index(model) + 1
        for task in TASKS:
            task_id = TASKS.index(task) + 1
            for pert in PERTURBATIONS:
                pert_id = PERTURBATIONS.index(pert) + 1
                p = min(0.99, max(0.01,
                        MEAN_RATES[model][pert] * TASK_FACTORS[task]))
                outcomes = generate_rollouts(p, N_SIM_ROLLOUTS)
                for rollout_num, success in enumerate(outcomes):
                    cur.execute(
                        "INSERT INTO sim_rollouts "
                        "(model_id, task_id, perturbation_id, rollout_num, success) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (model_id, task_id, pert_id, rollout_num, success))

    conn.commit()

    # Generate real-world validation data as CSV files (one per model)
    random.seed(123)
    for model in MODELS:
        csv_path = f"/app/real_validation/{model}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["task", "perturbation", "rollout_num", "success"])
            for task in REAL_TASKS:
                for pert in REAL_PERTS:
                    p_sim = min(0.99, max(0.01,
                                MEAN_RATES[model][pert] * TASK_FACTORS[task]))
                    p_real = min(0.99, max(0.01,
                                p_sim * 0.9 + random.gauss(0, 0.05)))
                    outcomes = generate_rollouts(p_real, N_REAL_ROLLOUTS)
                    for rollout_num, success in enumerate(outcomes):
                        writer.writerow([task, pert, rollout_num, success])

    conn.close()
    print(f"Created {db_path}")
    print(f"Created CSV files in /app/real_validation/")


if __name__ == "__main__":
    main()
