#!/usr/bin/env python3
"""Generate SQLite database, compressed JSONL files, simulator config, and
reference calibration for the MIB evaluation pipeline forensics task.

The database stores both raw circuit data and the output of the (buggy)
pipeline for all method-task pairs.  A separate reference calibration file
contains known-correct results for one method-task pair (eap_ig / ioi).

The simulator configuration is stored ONLY in the database — the agent
must reconstruct the JSON config file from the DB tables."""

import gzip
import json
import hashlib
import math
import os
import sqlite3
import sys

sys.path.insert(0, '/app')
from simulator import CircuitSimulator


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def det_hash(s):
    return int(hashlib.sha256(s.encode('utf-8')).hexdigest(), 16)


def seeded_float(seed_str, lo=0.0, hi=1.0):
    h = det_hash(seed_str)
    frac = (h % 10000000) / 10000000.0
    return lo + frac * (hi - lo)


# ---------------------------------------------------------------------------
# Graph structure: 4 layers, 3 attention heads + 1 MLP each, plus embed/output
# ---------------------------------------------------------------------------

node_layers = {"embed": -1, "output": 5}
for layer in range(4):
    for h in range(3):
        node_layers[f"L{layer}.H{h}"] = layer
    node_layers[f"L{layer}.MLP"] = layer

nodes = list(node_layers.keys())
all_edges = []
for src in nodes:
    if src == "output":
        continue
    for dst in nodes:
        if dst == "embed":
            continue
        if node_layers[src] < node_layers[dst]:
            all_edges.append(f"{src}->{dst}")
all_edges.sort()
N_EDGES = len(all_edges)

d_head = 64
d_mlp = 256
edge_metadata = {}
for e in all_edges:
    dst = e.split("->")[1]
    if ".H" in dst:
        edge_metadata[e] = {"type": "attn", "weight": d_head}
    elif ".MLP" in dst:
        edge_metadata[e] = {"type": "mlp", "weight": d_mlp}
    elif dst == "output":
        edge_metadata[e] = {"type": "output", "weight": 1}

# ---------------------------------------------------------------------------
# Ground truth circuits
# ---------------------------------------------------------------------------

tasks_config = {
    "ioi": {"baseline_score": 8.5, "corrupted_score": 0.3},
    "mcqa": {"baseline_score": 11.2, "corrupted_score": 1.8},
}

gt_data = {}
for task_name in tasks_config:
    n_gt = {"ioi": 35, "mcqa": 30}[task_name]
    edge_gt_scores = [(e, seeded_float(f"gt_{task_name}_{e}")) for e in all_edges]
    edge_gt_scores.sort(key=lambda x: x[1], reverse=True)
    gt_edges = set(e for e, _ in edge_gt_scores[:n_gt])
    gt_weights = {e: round(seeded_float(f"gtw_{task_name}_{e}", 0.3, 2.5), 6)
                  for e in gt_edges}
    gt_data[task_name] = {
        "gt_edges": sorted(gt_edges),
        "gt_weights": gt_weights,
    }

# ---------------------------------------------------------------------------
# Method importance scores — stored WITHOUT abs() so some may be negative
# ---------------------------------------------------------------------------

methods = ["eap", "eap_ig", "act_patch"]
quality_map = {
    ("eap", "ioi"): 0.58, ("eap", "mcqa"): 0.52,
    ("eap_ig", "ioi"): 0.72, ("eap_ig", "mcqa"): 0.68,
    ("act_patch", "ioi"): 0.38, ("act_patch", "mcqa"): 0.42,
}

method_scores = {}
for method in methods:
    method_scores[method] = {}
    for task_name in tasks_config:
        quality = quality_map[(method, task_name)]
        scores = {}
        for e in all_edges:
            is_gt = e in gt_data[task_name]["gt_edges"]
            seed = f"score_{method}_{task_name}_{e}"
            if is_gt:
                base = quality * 2.0
                noise_val = seeded_float(seed, -1.2, 1.2)
                scores[e] = round(base + noise_val, 6)
            else:
                base = (1 - quality) * 1.8
                noise_val = seeded_float(seed, -0.6, 0.6)
                scores[e] = round(base + noise_val, 6)
        method_scores[method][task_name] = scores

# ---------------------------------------------------------------------------
# Write simulator config to TEMP location (NOT shipped to /app/)
# ---------------------------------------------------------------------------

sim_config = {}
for task_name in tasks_config:
    sim_config[task_name] = {
        "baseline_score": tasks_config[task_name]["baseline_score"],
        "corrupted_score": tasks_config[task_name]["corrupted_score"],
        "ground_truth_weights": gt_data[task_name]["gt_weights"],
    }
with open("/tmp/sim_config.json", 'w') as f:
    json.dump(sim_config, f, indent=2)

simulator = CircuitSimulator("/tmp/sim_config.json")

# ---------------------------------------------------------------------------
# Evaluation helpers (parameterized for correct vs buggy)
# ---------------------------------------------------------------------------

PERCENTAGES = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]


def select_top_k(scores_dict, k, use_abs=True):
    if use_abs:
        ranked = sorted(scores_dict.items(), key=lambda x: (-abs(x[1]), x[0]))
    else:
        ranked = sorted(scores_dict.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, _ in ranked[:k]]


def compute_wec(edge_names):
    return sum(edge_metadata[e]["weight"] for e in edge_names)


def evaluate_at_sparsity(scores_dict, task_name, p,
                          use_abs=True, use_floor=True, invert_norm=False):
    baseline = tasks_config[task_name]["baseline_score"]
    corrupted = tasks_config[task_name]["corrupted_score"]
    denom = baseline - corrupted

    k = int(p * N_EDGES) if use_floor else round(p * N_EDGES)
    if k == 0:
        return k, 0.0, 0

    selected = select_top_k(scores_dict, k, use_abs)
    raw = simulator.evaluate(selected, task_name)

    if invert_norm:
        faith = (baseline - raw) / denom
    else:
        faith = (raw - corrupted) / denom

    wec = compute_wec(selected)
    return k, faith, wec


def trapezoidal(x_vals, y_vals):
    total = 0.0
    for i in range(len(x_vals) - 1):
        dx = x_vals[i + 1] - x_vals[i]
        total += dx * (y_vals[i] + y_vals[i + 1]) / 2
    return total


def compute_cpr_cmd(faithfulnesses, use_ln=True):
    cpr = trapezoidal(PERCENTAGES, faithfulnesses)
    cmd_vals = [abs(1 - f) for f in faithfulnesses]
    cmd = trapezoidal(PERCENTAGES, cmd_vals)
    log_fn = math.log if use_ln else math.log10
    log_x = [log_fn(p) for p in PERCENTAGES]
    cpr_log = trapezoidal(log_x, faithfulnesses)
    cmd_log = trapezoidal(log_x, cmd_vals)
    return cpr, cmd, cpr_log, cmd_log


def compute_auroc(scores_dict, gt_edges_set, use_abs=True):
    if use_abs:
        ranked = sorted(scores_dict.items(), key=lambda x: (-abs(x[1]), x[0]))
    else:
        ranked = sorted(scores_dict.items(), key=lambda x: (-x[1], x[0]))

    n_pos = len(gt_edges_set)
    n_neg = N_EDGES - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5

    tp, fp = 0, 0
    tpr_list = [0.0]
    fpr_list = [0.0]
    for name, _ in ranked:
        if name in gt_edges_set:
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
# Compute BUGGY evaluation results (matching pipeline.py's behavior)
# Bugs: no abs, round instead of floor, inverted norm, log10 instead of ln
# ---------------------------------------------------------------------------

buggy_eval_results = {}
buggy_agg_metrics = {}

for method in methods:
    for task_name in tasks_config:
        scores = method_scores[method][task_name]
        gt_set = set(gt_data[task_name]["gt_edges"])

        results = []
        faithfulnesses = []
        for idx, p in enumerate(PERCENTAGES):
            k, faith, wec = evaluate_at_sparsity(
                scores, task_name, p,
                use_abs=False, use_floor=False, invert_norm=True
            )
            results.append((idx, p, k, faith, wec))
            faithfulnesses.append(faith)

        cpr, cmd, cpr_log, cmd_log = compute_cpr_cmd(faithfulnesses, use_ln=False)
        auroc = compute_auroc(scores, gt_set, use_abs=False)

        buggy_eval_results[(method, task_name)] = results
        buggy_agg_metrics[(method, task_name)] = (cpr, cmd, cpr_log, cmd_log, auroc)


# ---------------------------------------------------------------------------
# Compute CORRECT results for reference calibration (eap_ig / ioi)
# ---------------------------------------------------------------------------

ref_method, ref_task = "eap_ig", "ioi"
ref_scores = method_scores[ref_method][ref_task]
ref_gt = set(gt_data[ref_task]["gt_edges"])

ref_faithfulnesses = []
ref_wecs = []
for p in PERCENTAGES:
    k, faith, wec = evaluate_at_sparsity(
        ref_scores, ref_task, p,
        use_abs=True, use_floor=True, invert_norm=False
    )
    ref_faithfulnesses.append(faith)
    ref_wecs.append(wec)

ref_cpr, ref_cmd, ref_cpr_log, ref_cmd_log = compute_cpr_cmd(
    ref_faithfulnesses, use_ln=True
)
ref_auroc = compute_auroc(ref_scores, ref_gt, use_abs=True)

ref_calibration = {
    "note": "Known-correct evaluation for eap_ig on ioi. "
            "Use to validate your corrected pipeline.",
    "method": "eap_ig",
    "task": "ioi",
    "faithfulnesses": ref_faithfulnesses,
    "weighted_edge_counts": ref_wecs,
    "cpr": ref_cpr,
    "cmd": ref_cmd,
    "cpr_log": ref_cpr_log,
    "cmd_log": ref_cmd_log,
    "auroc": ref_auroc,
}
with open("/app/reference_calibration.json", 'w') as f:
    json.dump(ref_calibration, f, indent=2)


# ---------------------------------------------------------------------------
# Create SQLite database
# ---------------------------------------------------------------------------

db_path = "/app/mib.db"
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""CREATE TABLE edges (
    edge_name TEXT PRIMARY KEY,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight INTEGER NOT NULL
)""")

c.execute("""CREATE TABLE importance_scores (
    method TEXT NOT NULL,
    task TEXT NOT NULL,
    edge_name TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (method, task, edge_name)
)""")

c.execute("""CREATE TABLE ground_truth (
    task TEXT NOT NULL,
    edge_name TEXT NOT NULL,
    in_circuit INTEGER NOT NULL,
    PRIMARY KEY (task, edge_name)
)""")

c.execute("""CREATE TABLE simulator_config (
    task TEXT PRIMARY KEY,
    baseline_score REAL NOT NULL,
    corrupted_score REAL NOT NULL
)""")

c.execute("""CREATE TABLE gt_weights (
    task TEXT NOT NULL,
    edge_name TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (task, edge_name)
)""")

c.execute("""CREATE TABLE pipeline_results (
    method TEXT NOT NULL,
    task TEXT NOT NULL,
    sparsity_level INTEGER NOT NULL,
    sparsity REAL NOT NULL,
    k INTEGER NOT NULL,
    faithfulness REAL NOT NULL,
    weighted_edge_count INTEGER NOT NULL,
    PRIMARY KEY (method, task, sparsity_level)
)""")

c.execute("""CREATE TABLE pipeline_metrics (
    method TEXT NOT NULL,
    task TEXT NOT NULL,
    cpr REAL NOT NULL,
    cmd REAL NOT NULL,
    cpr_log REAL NOT NULL,
    cmd_log REAL NOT NULL,
    auroc REAL NOT NULL,
    PRIMARY KEY (method, task)
)""")

# Populate edges
for e in all_edges:
    src, dst = e.split("->")
    meta = edge_metadata[e]
    c.execute("INSERT INTO edges VALUES (?, ?, ?, ?, ?)",
              (e, src, dst, meta["type"], meta["weight"]))

# Populate importance_scores
for method in methods:
    for task_name in tasks_config:
        for e, score in method_scores[method][task_name].items():
            c.execute("INSERT INTO importance_scores VALUES (?, ?, ?, ?)",
                      (method, task_name, e, score))

# Populate ground_truth
for task_name in tasks_config:
    gt_set = set(gt_data[task_name]["gt_edges"])
    for e in all_edges:
        c.execute("INSERT INTO ground_truth VALUES (?, ?, ?)",
                  (task_name, e, 1 if e in gt_set else 0))

# Populate simulator_config
for task_name in tasks_config:
    cfg = tasks_config[task_name]
    c.execute("INSERT INTO simulator_config VALUES (?, ?, ?)",
              (task_name, cfg["baseline_score"], cfg["corrupted_score"]))

# Populate gt_weights
for task_name in tasks_config:
    for e, w in gt_data[task_name]["gt_weights"].items():
        c.execute("INSERT INTO gt_weights VALUES (?, ?, ?)",
                  (task_name, e, w))

# Populate pipeline_results (buggy values from pipeline.py's behavior)
for (method, task_name), results in buggy_eval_results.items():
    for idx, p, k, faith, wec in results:
        c.execute("INSERT INTO pipeline_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (method, task_name, idx, p, k, faith, wec))

# Populate pipeline_metrics (buggy aggregate values)
for (method, task_name), metrics in buggy_agg_metrics.items():
    cpr, cmd, cpr_log, cmd_log, auroc = metrics
    c.execute("INSERT INTO pipeline_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
              (method, task_name, cpr, cmd, cpr_log, cmd_log, auroc))

conn.commit()
conn.close()

# ---------------------------------------------------------------------------
# Write gzip-compressed JSONL files
# ---------------------------------------------------------------------------

os.makedirs("/app/circuit_graphs", exist_ok=True)
for method in methods:
    for task_name in tasks_config:
        path = f"/app/circuit_graphs/{method}_{task_name}.jsonl.gz"
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            for e in all_edges:
                score = method_scores[method][task_name][e]
                obj = {"edge": e, "score": score}
                f.write(json.dumps(obj) + "\n")

# ---------------------------------------------------------------------------
# Generate execution trace (gzipped NDJSON)
# Re-runs the buggy computation with detailed intermediate value logging
# so the agent can diagnose bugs by analyzing the trace with jq/zcat.
# ---------------------------------------------------------------------------

trace_events = []
seq_counter = 0


def trace_append(event_data):
    global seq_counter
    event_data["seq"] = seq_counter
    trace_events.append(event_data)
    seq_counter += 1


trace_append({
    "event": "pipeline_start",
    "n_edges": N_EDGES,
    "methods": methods,
    "tasks": list(tasks_config.keys())
})

for method in methods:
    for task_name in tasks_config:
        scores = method_scores[method][task_name]
        baseline = tasks_config[task_name]["baseline_score"]
        corrupted = tasks_config[task_name]["corrupted_score"]
        denom = baseline - corrupted

        faith_values = []
        for p in PERCENTAGES:
            k_buggy = round(p * N_EDGES)

            event = {
                "event": "sparsity_eval",
                "method": method, "task": task_name,
                "sparsity": p, "k": k_buggy
            }

            if k_buggy == 0:
                event["raw_score"] = corrupted
                event["faithfulness"] = 0.0
                event["wec"] = 0
                faith_values.append(0.0)
            else:
                ranked_buggy = sorted(
                    scores.items(), key=lambda x: (-x[1], x[0])
                )
                selected = [name for name, _ in ranked_buggy[:k_buggy]]
                raw = simulator.evaluate(selected, task_name)
                faith = (baseline - raw) / denom
                wec = compute_wec(selected)

                event["top_edge"] = ranked_buggy[0][0]
                event["top_score"] = round(ranked_buggy[0][1], 6)
                event["raw_score"] = round(raw, 10)
                event["faithfulness"] = round(faith, 10)
                event["wec"] = wec
                faith_values.append(faith)

            trace_append(event)

        # Aggregate metrics (buggy: log10)
        cpr_t = trapezoidal(PERCENTAGES, faith_values)
        cmd_vals_t = [abs(1 - f) for f in faith_values]
        cmd_t = trapezoidal(PERCENTAGES, cmd_vals_t)
        log_x_buggy = [math.log10(pv) for pv in PERCENTAGES]
        cpr_log_t = trapezoidal(log_x_buggy, faith_values)
        cmd_log_t = trapezoidal(log_x_buggy, cmd_vals_t)

        trace_append({
            "event": "aggregate_metrics",
            "method": method, "task": task_name,
            "cpr": round(cpr_t, 10), "cmd": round(cmd_t, 10),
            "log_x_values": [round(v, 6) for v in log_x_buggy],
            "cpr_log": round(cpr_log_t, 10),
            "cmd_log": round(cmd_log_t, 10)
        })

with gzip.open("/app/pipeline_trace.ndjson.gz", 'wt', encoding='utf-8') as f:
    for event in trace_events:
        f.write(json.dumps(event) + "\n")

# ---------------------------------------------------------------------------
# Cleanup — do NOT ship the simulator config to /app/
# ---------------------------------------------------------------------------

os.remove("/tmp/sim_config.json")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"Generated {N_EDGES} edges, {len(methods)} methods, "
      f"{len(tasks_config)} tasks")
print(f"Database: {db_path}")
print(f"Reference calibration: /app/reference_calibration.json")
print(f"Execution trace: /app/pipeline_trace.ndjson.gz")
print(f"Pipeline results stored (all buggy) in pipeline_results/pipeline_metrics tables")
print(f"Simulator config NOT shipped — must be reconstructed from DB")
