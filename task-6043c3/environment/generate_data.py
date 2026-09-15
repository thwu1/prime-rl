#!/usr/bin/env python3
"""Generate deterministic benchmark rollout data for robustness analysis."""

import random
import csv
import os
from collections import defaultdict

random.seed(42)

models = ["pi0", "pi0_fast", "groot"]

perturbations = [
    (0, "default", "none"),
    (1, "v_aug", "V"),
    (2, "v_view", "V"),
    (3, "v_sc", "V"),
    (4, "v_light", "V"),
    (5, "s_prop", "S"),
    (6, "s_lang", "S"),
    (7, "s_mo", "S"),
    (8, "s_aff", "S"),
    (9, "s_int", "S"),
    (10, "b_hobj", "B"),
    (11, "sb_noun", "SB"),
    (12, "sb_vrb", "SB"),
    (13, "vb_pose", "VB"),
    (14, "vb_mobj", "VB"),
    (15, "vsb_nobj", "VSB"),
]

# Mean success rates per (model, perturbation) derived from empirical VLA evaluations
base_rates = {
    "pi0": {
        0: 0.44, 1: 0.42, 2: 0.52, 3: 0.43, 4: 0.37,
        5: 0.29, 6: 0.36, 7: 0.35, 8: 0.30, 9: 0.29,
        10: 0.32, 11: 0.28, 12: 0.36, 13: 0.32, 14: 0.38, 15: 0.16,
    },
    "pi0_fast": {
        0: 0.61, 1: 0.64, 2: 0.70, 3: 0.60, 4: 0.54,
        5: 0.53, 6: 0.61, 7: 0.55, 8: 0.55, 9: 0.54,
        10: 0.38, 11: 0.39, 12: 0.57, 13: 0.49, 14: 0.53, 15: 0.26,
    },
    "groot": {
        0: 0.19, 1: 0.19, 2: 0.19, 3: 0.21, 4: 0.16,
        5: 0.21, 6: 0.21, 7: 0.20, 8: 0.21, 9: 0.20,
        10: 0.16, 11: 0.17, 12: 0.21, 13: 0.07, 14: 0.09, 15: 0.09,
    },
}

N_TASKS = 10
N_ROLLOUTS = 25

os.makedirs("/app/data", exist_ok=True)

rollout_rows = []

for model in models:
    for pid, pname, pcat in perturbations:
        mean_rate = base_rates[model][pid]
        for task_id in range(N_TASKS):
            kappa = 20.0
            a = max(mean_rate * kappa, 0.1)
            b = max((1.0 - mean_rate) * kappa, 0.1)
            task_rate = min(max(random.betavariate(a, b), 0.01), 0.99)
            for rollout_id in range(N_ROLLOUTS):
                success = 1 if random.random() < task_rate else 0
                rollout_rows.append([model, task_id, pid, pname, pcat, rollout_id, success])

with open("/app/data/rollouts.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model", "task_id", "perturbation_id", "perturbation_name",
                      "perturbation_categories", "rollout_id", "success"])
    writer.writerows(rollout_rows)

# Compute aggregate sim success rates from generated rollouts
counts = defaultdict(lambda: [0, 0])
for row in rollout_rows:
    model_name, _, p_id, _, _, _, succ = row
    key = (model_name, p_id)
    counts[key][0] += succ
    counts[key][1] += 1

# Generate paired real-world scores with correlated noise
random.seed(123)
with open("/app/data/sim_real_scores.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model", "perturbation_id", "perturbation_name",
                      "sim_success_rate", "real_success_rate"])
    for model in models:
        for pid, pname, pcat in perturbations:
            key = (model, pid)
            sim_rate = counts[key][0] / counts[key][1]
            noise = random.gauss(0, 0.05)
            real_rate = min(max(sim_rate + noise, 0.0), 1.0)
            writer.writerow([model, pid, pname, f"{sim_rate:.6f}", f"{real_rate:.6f}"])

print(f"Generated {len(rollout_rows)} rollout records")
print(f"Generated {len(models) * len(perturbations)} sim-real score pairs")
