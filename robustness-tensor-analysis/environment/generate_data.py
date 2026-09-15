#!/usr/bin/env python3
"""Generate deterministic REALM benchmark data files from published results."""
import csv
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

# Mean success rates from REALM paper (averaged across 10 tasks, 25 rollouts each)
MEAN_RATES = {
    "pi0": [0.44, 0.42, 0.52, 0.43, 0.37, 0.29, 0.36, 0.35, 0.30, 0.29,
            0.32, 0.28, 0.36, 0.32, 0.38, 0.16],
    "pi0_fast": [0.61, 0.64, 0.70, 0.60, 0.54, 0.53, 0.61, 0.55, 0.55, 0.54,
                 0.38, 0.39, 0.57, 0.49, 0.53, 0.26],
    "groot_n15": [0.19, 0.19, 0.19, 0.21, 0.16, 0.21, 0.21, 0.20, 0.21, 0.20,
                  0.16, 0.17, 0.21, 0.07, 0.09, 0.09]
}

# Deterministic per-task difficulty multipliers (average = 1.0)
TASK_MULTIPLIERS = [1.15, 0.85, 1.05, 0.80, 1.25, 1.10, 0.70, 1.05, 0.95, 1.10]

TOTAL_ROLLOUTS = 25


def generate():
    os.makedirs("/app/data/results", exist_ok=True)
    for model in MODEL_NAMES:
        rows = []
        for p_id, p_name in PERTURBATION_INFO:
            base_rate = MEAN_RATES[model][p_id]
            for t_id, t_name in TASK_INFO:
                rate = base_rate * TASK_MULTIPLIERS[t_id]
                successes = max(0, min(TOTAL_ROLLOUTS, round(rate * TOTAL_ROLLOUTS)))
                rows.append([p_id, p_name, t_id, t_name, successes, TOTAL_ROLLOUTS])

        with open(f"/app/data/results/{model}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["perturbation_id", "perturbation_name", "task_id",
                        "task_name", "successes", "total_rollouts"])
            w.writerows(rows)


if __name__ == "__main__":
    generate()
