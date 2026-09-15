#!/usr/bin/env python3
"""Generate the SQLite database, NDJSON prediction files, and audit file."""

import json
import os
import random
import sqlite3

PATIENTS = [f"P{i:03d}" for i in range(1, 16)]
TEAMS = ["alpha", "beta", "gamma", "delta"]
T_CLASSES = [1, 2, 3, 4]
N_CLASSES = [0, 1, 2, 3]

# --- Ground truth ---

stage_seq_T = [2, 3, 1, 4, 2, 3, 1, 2, 4, 3, 1, 2, 3, 4, 2]
stage_seq_N = [1, 0, 2, 1, 3, 0, 1, 2, 0, 3, 1, 0, 2, 1, 3]
true_stages = {}
for i, p in enumerate(PATIENTS):
    true_stages[p] = {"T": stage_seq_T[i], "N": stage_seq_N[i]}

surv_times = [12.3, 45.6, 8.9, 23.4, 56.7, 34.5, 15.6, 48.9, 9.2, 31.4,
              22.1, 41.3, 18.7, 52.8, 27.6]
surv_events = [1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1]
true_survival = {}
for i, p in enumerate(PATIENTS):
    true_survival[p] = {"event_time": surv_times[i],
                        "event_observed": surv_events[i]}

gt_vols_c1 = [1200, 2500, 800, 3200, 1500, 4100, 600, 2800, 950, 3500,
              1800, 2200, 1100, 3800, 1400]
gt_vols_c2 = [800, 1500, 0, 2100, 900, 0, 400, 1800, 600, 2500,
              1200, 0, 700, 2000, 1100]
true_seg = {}
for i, p in enumerate(PATIENTS):
    true_seg[p] = {1: float(gt_vols_c1[i]), 2: float(gt_vols_c2[i])}

quality = {"alpha": 0.85, "beta": 0.72, "gamma": 0.90, "delta": 0.78}

# --- Generate segmentation data ---

random.seed(123)
seg_data = []
for team in TEAMS:
    q = quality[team]
    for p in PATIENTS:
        for c in [1, 2]:
            gt = true_seg[p][c]
            if gt == 0:
                if random.random() < 0.7:
                    pred = 0.0
                    inter = 0.0
                else:
                    pred = round(random.uniform(50, 300), 1)
                    inter = 0.0
            else:
                noise = random.uniform(-0.3, 0.3)
                pred = round(gt * (q + noise), 1)
                pred = max(0.0, pred)
                max_inter = min(gt, pred)
                inter_factor = q * random.uniform(0.8, 1.0)
                inter = round(max_inter * inter_factor, 1)
                inter = min(inter, min(gt, pred))
            seg_data.append((team, p, c, gt, pred, inter))

# --- Generate staging data ---

random.seed(456)
staging_data = []
for team in TEAMS:
    q = quality[team]
    for p in PATIENTS:
        tt = true_stages[p]["T"]
        nt = true_stages[p]["N"]
        tp = tt if random.random() < q else random.choice(
            [x for x in T_CLASSES if x != tt])
        np_ = nt if random.random() < q else random.choice(
            [x for x in N_CLASSES if x != nt])
        staging_data.append((team, p, tt, tp, nt, np_))

# --- Generate survival data ---

random.seed(789)
survival_records = {}  # team -> list of records
for team in TEAMS:
    survival_records[team] = []
    q = quality[team]
    for p in PATIENTS:
        et = true_survival[p]["event_time"]
        eo = true_survival[p]["event_observed"]
        noise_scale = (1.0 - q) * 30
        risk = round(-et + random.gauss(0, noise_scale), 2)
        missing = False
        if team == "beta" and p in ["P003", "P007"]:
            missing = True
        if team == "delta" and p == "P012":
            missing = True
        survival_records[team].append({
            "patient_id": p,
            "event_time": et,
            "event_observed": eo,
            "risk_score": None if missing else risk,
        })

# --- Write SQLite database (segmentation + staging only) ---

db_path = "/app/submissions.db"
conn = sqlite3.connect(db_path)

conn.execute("""CREATE TABLE segmentation_stats (
    team TEXT, patient_id TEXT, class INTEGER,
    gt_volume_mm3 REAL, pred_volume_mm3 REAL, intersection_volume_mm3 REAL
)""")
conn.executemany(
    "INSERT INTO segmentation_stats VALUES (?,?,?,?,?,?)", seg_data)

conn.execute("""CREATE TABLE staging (
    team TEXT, patient_id TEXT,
    T_true INTEGER, T_pred INTEGER, N_true INTEGER, N_pred INTEGER
)""")
conn.executemany("INSERT INTO staging VALUES (?,?,?,?,?,?)", staging_data)

# Create survival table schema (empty — data must be ingested from NDJSON)
conn.execute("""CREATE TABLE survival (
    team TEXT, patient_id TEXT,
    event_time REAL, event_observed INTEGER, risk_score TEXT
)""")

conn.commit()
conn.close()

# --- Write NDJSON prediction files ---

os.makedirs("/app/raw_predictions", exist_ok=True)
for team in TEAMS:
    fpath = f"/app/raw_predictions/{team}_survival.jsonl"
    with open(fpath, "w") as f:
        for rec in survival_records[team]:
            f.write(json.dumps(rec) + "\n")

# --- Write audit.json ---

audit = {
    "description": (
        "Spot-check values from the validated reference implementation. "
        "Use these to verify your metric computations and resolve any "
        "methodological ambiguities in the specification. "
        "Tolerances: 0.001 for point estimates, 0.02 for CI bounds."
    ),
    "reference_values": {
        "gamma_segmentation_mean_agg_dsc": 0.7462,
        "alpha_segmentation_class_1_agg_dsc": 0.6906,
        "alpha_prognosis_c_index": 0.9518,
        "beta_prognosis_c_index": 0.7771,
        "gamma_staging_mean_balanced_accuracy": 0.9083,
        "alpha_staging_balanced_accuracy_T": 0.9167,
        "alpha_overall_weighted_score": 0.8284,
        "gamma_overall_rank": 1,
        "beta_overall_rank": 4,
        "gamma_bootstrap_ci_weighted_lower": 0.8415,
        "gamma_bootstrap_ci_weighted_upper": 0.9385,
    },
}

with open("/app/audit.json", "w") as f:
    json.dump(audit, f, indent=2)

print("Data generation complete.")
print(f"  Database: {db_path} (survival table empty — ingest from NDJSON)")
print(f"  NDJSON predictions: /app/raw_predictions/")
print(f"  Audit: /app/audit.json")
