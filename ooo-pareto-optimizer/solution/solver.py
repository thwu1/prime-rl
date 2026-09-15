#!/usr/bin/env python3
"""
Solver for heterogeneous multi-core chip design optimization.

Strategy:
1. Run archsim with representative configs across all workloads
2. Load results into SQLite experiments table
3. Identify top configs per workload
4. Run paired simulations for candidate workload pairings
5. Search over workload-to-cluster assignments with constraint checking
6. Output optimal chip layout
"""

import json
import math
import sqlite3
import subprocess
import sys
import tomllib
from itertools import permutations


# --- Load constraints ---
with open("/app/chip_constraints.toml", "rb") as f:
    constraints = tomllib.load(f)

AREA_BUDGET = constraints["chip"]["total_area_budget"]
POWER_BUDGET = constraints["chip"]["total_power_budget_watts"]
HOT_THRESHOLD = constraints["thermal"]["hot_threshold_area"]
ADJACENT_PAIRS = [tuple(p) for p in constraints["thermal"]["adjacent_pairs"]]
WORKLOAD_NAMES = sorted(constraints["workload_assignment"]["workloads"])

# --- Load workload weights from SQLite ---
conn = sqlite3.connect("/app/workloads.db")
weights = dict(conn.execute("SELECT name, priority_weight FROM workloads").fetchall())

experiments_run = 0


def run_archsim(width, rob_size, int_regs, fp_regs, workload, paired=None):
    """Run archsim --json and return parsed result."""
    global experiments_run
    cmd = [
        "/app/bin/archsim", "--json",
        "--width", str(width),
        "--rob-size", str(rob_size),
        "--int-regs", str(int_regs),
        "--fp-regs", str(fp_regs),
        "--workload", workload,
    ]
    if paired:
        cmd.extend(["--paired", paired])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        print(f"archsim error: {result.stderr}", file=sys.stderr)
        return None
    data = json.loads(result.stdout)
    experiments_run += 1

    # Record in database
    if paired:
        conn.execute(
            "INSERT INTO experiments "
            "(width, rob_size, num_int_regs, num_fp_regs, workload, "
            "paired_workload, ipc, area, power_watts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (width, rob_size, int_regs, fp_regs,
             workload, paired, data["paired_ipc1"], data["area"], data["power_watts"]),
        )
        conn.execute(
            "INSERT INTO experiments "
            "(width, rob_size, num_int_regs, num_fp_regs, workload, "
            "paired_workload, ipc, area, power_watts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (width, rob_size, int_regs, fp_regs,
             paired, workload, data["paired_ipc2"], data["area"], data["power_watts"]),
        )
    else:
        conn.execute(
            "INSERT INTO experiments "
            "(width, rob_size, num_int_regs, num_fp_regs, workload, "
            "paired_workload, ipc, area, power_watts) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)",
            (width, rob_size, int_regs, fp_regs,
             workload, data["ipc"], data["area"], data["power_watts"]),
        )
    conn.commit()
    return data


# --- Phase 1: Strategic design space exploration ---
# Representative configs spanning small/medium/large cores with different
# integer/FP register allocations
CONFIGS = [
    # (width, rob_size, int_regs, fp_regs)
    (1, 16, 33, 33),      # Minimum
    (2, 32, 48, 48),       # Tiny
    (4, 48, 64, 48),       # Small int-leaning
    (4, 64, 96, 33),       # Small int-heavy
    (4, 64, 96, 64),       # Medium-small
    (4, 96, 128, 64),      # Medium
    (6, 48, 80, 64),       # Medium-wide
    (6, 64, 80, 64),       # Medium-wide balanced
    (6, 96, 128, 96),      # Medium-large
    (6, 96, 128, 33),      # Medium int-focused
    (6, 128, 128, 160),    # Large FP-heavy
    (8, 96, 80, 33),       # Wide int-only
    (8, 96, 128, 33),      # Wide with more int regs
    (8, 128, 64, 128),     # Wide FP-balanced
    (8, 128, 64, 160),     # Wide FP-heavy
    (8, 128, 128, 160),    # Wide balanced
    (10, 128, 128, 128),   # Very wide
    (10, 192, 160, 192),   # Very wide large
    (12, 192, 160, 192),   # Extra wide
    (16, 384, 384, 384),   # Maximum
]

print("Phase 1: Running solo simulations...", file=sys.stderr)
solo_results = {}  # (config_tuple, workload) -> archsim result
for config in CONFIGS:
    for wl in WORKLOAD_NAMES:
        result = run_archsim(*config, wl)
        if result:
            solo_results[(config, wl)] = result

print(f"  Ran {experiments_run} solo experiments", file=sys.stderr)

# --- Phase 2: Identify best configs per workload ---
best_per_workload = {}
for wl in WORKLOAD_NAMES:
    candidates = []
    for config in CONFIGS:
        key = (config, wl)
        if key in solo_results:
            r = solo_results[key]
            candidates.append((config, r["ipc"], r["area"], r["power_watts"]))
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_per_workload[wl] = candidates[:8]

# --- Phase 3: Run paired simulations for candidate workload pairings ---
print("Phase 2: Evaluating workload pairings...", file=sys.stderr)

# For each workload pair, evaluate top candidate configs
pair_configs = {}  # (wl_a, wl_b) -> list of (config, adj_ipc_a, adj_ipc_b, area, power, weighted)

for i in range(len(WORKLOAD_NAMES)):
    for j in range(i + 1, len(WORKLOAD_NAMES)):
        wl_a, wl_b = WORKLOAD_NAMES[i], WORKLOAD_NAMES[j]
        pair_key = (wl_a, wl_b)
        pair_configs[pair_key] = []

        # Union of top configs for both workloads
        candidate_configs = set()
        for c, _, _, _ in best_per_workload[wl_a][:5]:
            candidate_configs.add(c)
        for c, _, _, _ in best_per_workload[wl_b][:5]:
            candidate_configs.add(c)

        for config in candidate_configs:
            result = run_archsim(*config, wl_a, paired=wl_b)
            if result is None:
                continue
            adj_a = result["paired_ipc1"]
            adj_b = result["paired_ipc2"]
            area = result["area"]
            power = result["power_watts"]
            weighted = weights[wl_a] * adj_a + weights[wl_b] * adj_b
            pair_configs[pair_key].append(
                (config, adj_a, adj_b, area, power, weighted)
            )

        pair_configs[pair_key].sort(key=lambda x: x[5], reverse=True)

print(f"  Ran {experiments_run} total experiments", file=sys.stderr)


# --- Phase 4: Search over cluster assignments ---
print("Phase 3: Searching cluster assignments...", file=sys.stderr)


def generate_partitions(items):
    """Generate all ways to partition items into len(items)/2 unordered pairs."""
    if len(items) == 0:
        yield []
        return
    if len(items) == 2:
        yield [(items[0], items[1])]
        return
    first = items[0]
    rest = items[1:]
    for i, partner in enumerate(rest):
        remaining = rest[:i] + rest[i + 1:]
        for sub_partition in generate_partitions(remaining):
            yield [(first, partner)] + sub_partition


best_solution = None
best_throughput = -1.0

partitions = list(generate_partitions(WORKLOAD_NAMES))
print(f"  Generated {len(partitions)} unordered partitions", file=sys.stderr)

for partition in partitions:
    # For each partition, get top 3 configs per pair
    pair_options = []
    skip = False
    for pair in partition:
        key = tuple(sorted(pair))
        if key not in pair_configs or len(pair_configs[key]) == 0:
            skip = True
            break
        pair_options.append(pair_configs[key][:3])
    if skip:
        continue

    # Try all config combos for this partition
    for c0 in pair_options[0]:
        for c1 in pair_options[1]:
            for c2 in pair_options[2]:
                for c3 in pair_options[3]:
                    chosen = [c0, c1, c2, c3]
                    total_area = sum(c[3] * 2 for c in chosen)
                    if total_area > AREA_BUDGET:
                        continue
                    total_power = sum(c[4] * 2 for c in chosen)
                    if total_power > POWER_BUDGET:
                        continue
                    total_wt = sum(c[5] for c in chosen)

                    # Try all 24 permutations for cluster placement
                    # (thermal constraint depends on position)
                    for perm in permutations(range(4)):
                        areas = [chosen[perm[k]][3] for k in range(4)]
                        thermal_ok = True
                        for a, b in ADJACENT_PAIRS:
                            if areas[a] > HOT_THRESHOLD and areas[b] > HOT_THRESHOLD:
                                thermal_ok = False
                                break
                        if not thermal_ok:
                            continue

                        if total_wt > best_throughput:
                            best_throughput = total_wt
                            # Build solution: cluster k gets partition[perm[k]]
                            best_solution = []
                            for k in range(4):
                                src_idx = perm[k]
                                pair = partition[src_idx]
                                conf = chosen[src_idx]
                                best_solution.append((k, pair, conf))
                            break  # One valid thermal placement is enough

if best_solution is None:
    print("ERROR: No feasible solution found!", file=sys.stderr)
    sys.exit(1)


# --- Phase 5: Build output ---
print("Phase 4: Building output...", file=sys.stderr)

clusters = []
for cluster_id, pair, conf in best_solution:
    config_tuple, adj_a, adj_b, area, power, _ = conf
    wl_a, wl_b = sorted(pair)

    # Get solo IPC values
    solo_a = solo_results[(config_tuple, wl_a)]["ipc"]
    solo_b = solo_results[(config_tuple, wl_b)]["ipc"]

    clusters.append({
        "cluster_id": cluster_id,
        "core_config": {
            "width": config_tuple[0],
            "rob_size": config_tuple[1],
            "num_int_regs": config_tuple[2],
            "num_fp_regs": config_tuple[3],
        },
        "area_per_core": area,
        "power_per_core_watts": power,
        "assigned_workloads": [wl_a, wl_b],
        "solo_ipc": {wl_a: solo_a, wl_b: solo_b},
        "interference_adjusted_ipc": {wl_a: adj_a, wl_b: adj_b},
    })

clusters.sort(key=lambda c: c["cluster_id"])

total_area = sum(c["area_per_core"] * 2 for c in clusters)
total_power = sum(c["power_per_core_watts"] * 2 for c in clusters)
total_wt = sum(
    weights[wl] * c["interference_adjusted_ipc"][wl]
    for c in clusters
    for wl in c["assigned_workloads"]
)

output = {
    "clusters": clusters,
    "total_area": total_area,
    "total_power_watts": round(total_power, 6),
    "weighted_throughput": round(total_wt, 6),
    "experiments_run": experiments_run,
}

with open("/app/results.json", "w") as f:
    json.dump(output, f, indent=2)

conn.close()

print(f"Solution written to /app/results.json", file=sys.stderr)
print(f"  Weighted throughput: {total_wt:.4f}", file=sys.stderr)
print(f"  Total area: {total_area}", file=sys.stderr)
print(f"  Total power: {total_power:.3f}W", file=sys.stderr)
print(f"  Experiments run: {experiments_run}", file=sys.stderr)
