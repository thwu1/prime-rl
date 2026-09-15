#!/usr/bin/env python3

"""
Solution: Audit MIB evaluation pipeline, identify all bugs, produce
corrected results and a detailed bug report.

Step 1: Reconstruct simulator_config.json from the database (it was not shipped).
Step 2: Analyze pipeline trace with diagnostic queries to identify anomalies.
Step 3: Cross-validate importance scores between DB and JSONL files.
Step 4: Identify and fix all pipeline bugs.
Step 5: Compute correct results and validate against reference calibration.

Pipeline bugs found by analyzing the trace + methodology draft + domain knowledge:
1. _rank_edges: sorts by -x[1] (raw score) instead of -abs(x[1]) (magnitude)
   Trace clue: all top_score values are positive; edges with large negative scores
   are never selected even though they have high magnitude.
2. _faithfulness: uses (baseline - raw)/(baseline - corrupted) instead of
   (raw - corrupted)/(baseline - corrupted) — inverted normalization
   Trace clue: faithfulness ≈ 0 at sparsity 1.0 (full circuit) instead of ≈ 1.
3. evaluate_pair: uses round(p * n_edges) instead of int(p * n_edges) — floor
   Trace clue: k=1 at sparsity 0.005 (round(0.645)=1) but floor gives 0.
4. evaluate_pair: uses math.log10 instead of math.log (natural log)
   Trace clue: log_x_values[0] = -3.0 (log10(0.001)) instead of -6.9 (ln(0.001)).
"""

import gzip
import json
import math
import os
import sqlite3
import sys

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Step 1: Reconstruct simulator_config.json from database
# ---------------------------------------------------------------------------

DB_PATH = "/app/mib.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Read baseline/corrupted scores from simulator_config table
sim_config = {}
for row in conn.execute(
    "SELECT task, baseline_score, corrupted_score FROM simulator_config"
):
    sim_config[row["task"]] = {
        "baseline_score": row["baseline_score"],
        "corrupted_score": row["corrupted_score"],
        "ground_truth_weights": {}
    }

# Read ground truth weights from gt_weights table
for row in conn.execute("SELECT task, edge_name, weight FROM gt_weights"):
    sim_config[row["task"]]["ground_truth_weights"][row["edge_name"]] = row["weight"]

# Write the reconstructed config
with open("/app/simulator_config.json", 'w') as f:
    json.dump(sim_config, f, indent=2)

print("Reconstructed simulator_config.json from database")

# Now import the simulator (needs config file to exist)
from simulator import CircuitSimulator

# ---------------------------------------------------------------------------
# Step 2: Read all data from SQLite
# ---------------------------------------------------------------------------

edges_data = {}
for row in conn.execute("SELECT edge_name, src, dst, edge_type, weight FROM edges"):
    edges_data[row["edge_name"]] = {
        "type": row["edge_type"],
        "weight": row["weight"],
    }
all_edge_names = sorted(edges_data.keys())
N_EDGES = len(all_edge_names)

importance_scores = {}
for row in conn.execute("SELECT method, task, edge_name, score FROM importance_scores"):
    key = (row["method"], row["task"])
    if key not in importance_scores:
        importance_scores[key] = {}
    importance_scores[key][row["edge_name"]] = row["score"]

ground_truth = {}
for row in conn.execute("SELECT task, edge_name FROM ground_truth WHERE in_circuit = 1"):
    ground_truth.setdefault(row["task"], set()).add(row["edge_name"])

sim_config_db = {}
for row in conn.execute("SELECT task, baseline_score, corrupted_score FROM simulator_config"):
    sim_config_db[row["task"]] = {
        "baseline": row["baseline_score"],
        "corrupted": row["corrupted_score"],
    }

conn.close()


# ---------------------------------------------------------------------------
# Step 3: Cross-validate importance scores against JSONL files
# ---------------------------------------------------------------------------

for method_task_key, db_scores in importance_scores.items():
    method, task = method_task_key
    jsonl_path = f"/app/circuit_graphs/{method}_{task}.jsonl.gz"
    if os.path.exists(jsonl_path):
        jsonl_scores = {}
        with gzip.open(jsonl_path, 'rt', encoding='utf-8') as f:
            for line in f:
                obj = json.loads(line.strip())
                jsonl_scores[obj["edge"]] = obj["score"]
        for edge, score in db_scores.items():
            assert abs(jsonl_scores.get(edge, 0) - score) < 1e-10, \
                f"Score mismatch for {method}/{task}/{edge}"

print("Cross-validated importance scores: DB matches JSONL files")


# ---------------------------------------------------------------------------
# Step 4: CORRECT evaluation helpers (all bugs fixed)
# ---------------------------------------------------------------------------

PERCENTAGES = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
simulator = CircuitSimulator("/app/simulator_config.json")


def select_top_k(scores_dict, k):
    """Select top-k edges by abs(score) descending, ties by name ascending."""
    ranked = sorted(scores_dict.items(), key=lambda x: (-abs(x[1]), x[0]))
    return [name for name, _ in ranked[:k]]


def trapezoidal(x_vals, y_vals):
    total = 0.0
    for i in range(len(x_vals) - 1):
        dx = x_vals[i + 1] - x_vals[i]
        total += dx * (y_vals[i] + y_vals[i + 1]) / 2
    return total


def compute_correct_evaluation(method, task):
    """Compute fully correct evaluation for a method-task pair."""
    scores = importance_scores[(method, task)]
    baseline = sim_config_db[task]["baseline"]
    corrupted = sim_config_db[task]["corrupted"]
    denom = baseline - corrupted

    faithfulnesses = []
    wecs = []

    for pct in PERCENTAGES:
        k = int(pct * N_EDGES)  # floor, not round
        if k == 0:
            faithfulnesses.append(0.0)
            wecs.append(0)
        else:
            selected = select_top_k(scores, k)
            raw = simulator.evaluate(selected, task)
            faith = (raw - corrupted) / denom  # correct normalization
            faithfulnesses.append(faith)
            wec = sum(edges_data[e]["weight"] for e in selected)
            wecs.append(wec)

    cpr = trapezoidal(PERCENTAGES, faithfulnesses)
    cmd_vals = [abs(1 - f) for f in faithfulnesses]
    cmd = trapezoidal(PERCENTAGES, cmd_vals)
    log_x = [math.log(p) for p in PERCENTAGES]  # natural log
    cpr_log = trapezoidal(log_x, faithfulnesses)
    cmd_log = trapezoidal(log_x, cmd_vals)

    return {
        "faithfulnesses": faithfulnesses,
        "weighted_edge_counts": wecs,
        "cpr": cpr,
        "cmd": cmd,
        "cpr_log": cpr_log,
        "cmd_log": cmd_log,
    }


def compute_auroc(method, task):
    """Compute AUROC using correct abs-value ranking."""
    scores = importance_scores[(method, task)]
    gt_set = ground_truth[task]
    ranked = sorted(scores.items(), key=lambda x: (-abs(x[1]), x[0]))

    n_pos = len(gt_set)
    n_neg = N_EDGES - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5

    tp, fp = 0, 0
    tpr_list = [0.0]
    fpr_list = [0.0]
    for name, _ in ranked:
        if name in gt_set:
            tp += 1
        else:
            fp += 1
        tpr_list.append(tp / n_pos)
        fpr_list.append(fp / n_neg)

    auroc = 0.0
    for i in range(len(tpr_list) - 1):
        auroc += (fpr_list[i + 1] - fpr_list[i]) * \
                 (tpr_list[i] + tpr_list[i + 1]) / 2
    return auroc


# ---------------------------------------------------------------------------
# Step 5: Validate against reference calibration
# ---------------------------------------------------------------------------

with open("/app/reference_calibration.json", 'r') as f:
    ref = json.load(f)

ref_result = compute_correct_evaluation("eap_ig", "ioi")
ref_auroc = compute_auroc("eap_ig", "ioi")

for i, (a, e) in enumerate(zip(ref_result["faithfulnesses"], ref["faithfulnesses"])):
    assert abs(a - e) < 1e-8, f"Reference calibration mismatch at faithfulness[{i}]"
assert abs(ref_result["cpr"] - ref["cpr"]) < 1e-8
assert abs(ref_auroc - ref["auroc"]) < 1e-8
print("Reference calibration validated successfully")


# ---------------------------------------------------------------------------
# Step 6: Compute correct evaluations for all method-task pairs
# ---------------------------------------------------------------------------

methods = ["eap", "eap_ig", "act_patch"]
tasks = ["ioi", "mcqa"]

correct_evals = {}
correct_aurocs = {}

for method in methods:
    for task in tasks:
        correct_evals[(method, task)] = compute_correct_evaluation(method, task)
        correct_aurocs[(method, task)] = compute_auroc(method, task)


# ---------------------------------------------------------------------------
# Step 7: Write bug_report.json
# ---------------------------------------------------------------------------

bug_report = {
    "bugs": [
        {
            "location": "_rank_edges method (line with sorted(..., key=lambda x: (-x[1], x[0])))",
            "description": "Edge ranking sorts by raw score (-x[1]) instead of absolute importance magnitude (-abs(x[1])). In circuit analysis, both positive and negative attribution scores indicate functionally important edges. Negative scores represent suppressive contributions that are equally significant. Without abs(), edges with large negative importance scores are incorrectly ranked last, altering edge selection at all sparsity levels. This same bug propagates to compute_auroc which uses the same ranking.",
            "fix": "Change sort key from (-x[1], x[0]) to (-abs(x[1]), x[0]) in both _rank_edges and compute_auroc"
        },
        {
            "location": "_faithfulness method (return statement)",
            "description": "Faithfulness normalization formula is inverted. The pipeline computes (baseline - raw) / (baseline - corrupted), which measures distance FROM clean behavior instead of recovery from corrupted baseline. This produces faithfulness values near 1 at low sparsity (circuit mostly ablated) and near 0 at full sparsity (full circuit), the opposite of the correct behavior where f=0 at empty circuit and f=1 at full recovery.",
            "fix": "Change numerator from (baseline - raw) to (raw - corrupted): return (raw - corrupted) / (baseline - corrupted)"
        },
        {
            "location": "evaluate_pair method (k computation)",
            "description": "Edge count k is computed using round(p * self.n_edges) instead of floor (int). The MIB protocol uses floor to ensure the sub-circuit never exceeds the specified sparsity fraction. Using round() can include extra edges at certain sparsity levels, changing both faithfulness values and weighted edge counts. Observable in trace: k=1 at sparsity 0.005 where floor gives 0.",
            "fix": "Change round(p * self.n_edges) to int(p * self.n_edges) for floor semantics"
        },
        {
            "location": "evaluate_pair method (log-scale computation)",
            "description": "Log-scale metrics use math.log10 (base-10 logarithm) instead of math.log (natural logarithm). The methodology specifies natural logarithm for the log-scale CPR and CMD variants. Observable in trace: log_x_values[0] = -3.0 (log10) instead of approximately -6.9 (ln).",
            "fix": "Change math.log10(p) to math.log(p) for natural logarithm"
        }
    ]
}

with open("/app/bug_report.json", 'w') as f:
    json.dump(bug_report, f, indent=2)

print(f"Bug report: {len(bug_report['bugs'])} bugs identified")


# ---------------------------------------------------------------------------
# Step 8: Write corrected_results.json
# ---------------------------------------------------------------------------

results = {"methods": {}, "auroc": {}, "ranking": {}}

for method in methods:
    results["methods"][method] = {}
    results["auroc"][method] = {}
    for task in tasks:
        results["methods"][method][task] = correct_evals[(method, task)]
        results["auroc"][method][task] = correct_aurocs[(method, task)]

# Rankings
avg_cpr = {}
avg_cmd = {}
for method in methods:
    cprs = [correct_evals[(method, t)]["cpr"] for t in tasks]
    cmds = [correct_evals[(method, t)]["cmd"] for t in tasks]
    avg_cpr[method] = sum(cprs) / len(cprs)
    avg_cmd[method] = sum(cmds) / len(cmds)

results["ranking"]["by_cpr"] = sorted(methods, key=lambda m: avg_cpr[m], reverse=True)
results["ranking"]["by_cmd"] = sorted(methods, key=lambda m: avg_cmd[m])

with open("/app/corrected_results.json", 'w') as f:
    json.dump(results, f, indent=2)

print("Corrected results written to /app/corrected_results.json")
