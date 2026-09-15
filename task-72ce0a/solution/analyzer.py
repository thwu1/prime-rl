#!/usr/bin/env python3

"""
Protocol fuzzing campaign audit analyzer.

Explores /opt/campaign/, validates data integrity, and produces /app/audit.json
with data quality, protocol model, effectiveness, and regression suite analyses.
"""

import json
import os
from collections import defaultdict, deque, Counter

import numpy as np
from scipy.stats import mannwhitneyu

DATA_DIR = "/opt/campaign"
COVERAGE_DIR = os.path.join(DATA_DIR, "coverage")
OUTPUT_FILE = "/app/audit.json"


def load_and_validate():
    """Load execution data and identify quality issues."""
    executions = []
    with open(os.path.join(DATA_DIR, "runs.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                executions.append(json.loads(line))

    # Determine expected bitmap size from mode of file sizes
    file_sizes = []
    for fname in os.listdir(COVERAGE_DIR):
        if fname.endswith(".bin"):
            file_sizes.append(os.path.getsize(os.path.join(COVERAGE_DIR, fname)))
    expected_size = Counter(file_sizes).most_common(1)[0][0]

    # Classify records as valid or corrupted
    valid_executions = []
    corrupted_ids = []
    valid_bitmaps = {}

    for ex in executions:
        path = os.path.join(DATA_DIR, ex["edges_file"])
        if not os.path.exists(path) or os.path.getsize(path) != expected_size:
            corrupted_ids.append(ex["test_id"])
        else:
            valid_executions.append(ex)
            with open(path, "rb") as f:
                raw = f.read()
            edges = set()
            for i in range(len(raw)):
                if raw[i] > 0:
                    edges.add(i)
            valid_bitmaps[ex["test_id"]] = edges

    # Find orphan coverage files
    referenced = set(os.path.basename(ex["edges_file"]) for ex in executions)
    all_files = set(fn for fn in os.listdir(COVERAGE_DIR) if fn.endswith(".bin"))
    orphans = sorted(all_files - referenced)

    return {
        "executions": executions,
        "valid_executions": valid_executions,
        "corrupted_ids": sorted(corrupted_ids),
        "orphans": orphans,
        "bitmaps": valid_bitmaps,
    }


def analyze_protocol(valid_execs):
    """Reconstruct protocol state machine from valid execution traces."""
    states = set()
    transitions = set()

    for ex in valid_execs:
        seq = ex["states"]
        for s in seq:
            states.add(s)
        for i in range(len(seq) - 1):
            transitions.add((seq[i], seq[i + 1]))

    # Infer initial state: appears first in every execution
    initial_counts = Counter(ex["states"][0] for ex in valid_execs)
    initial_state = initial_counts.most_common(1)[0][0]

    # BFS for max shortest-path depth from initial state
    adj = defaultdict(set)
    for a, b in transitions:
        adj[a].add(b)

    dist = {initial_state: 0}
    queue = deque([initial_state])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adj[node]):
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                queue.append(neighbor)

    max_depth = max(dist.values()) if dist else 0

    return {
        "num_states": len(states),
        "num_transitions": len(transitions),
        "initial_state": initial_state,
        "max_depth": max_depth,
    }


def analyze_effectiveness(valid_execs, bitmaps):
    """Compare coverage effectiveness between configurations."""
    all_edges = set()
    for edges in bitmaps.values():
        all_edges.update(edges)

    config_a = []
    config_b = []
    for ex in valid_execs:
        n = len(bitmaps[ex["test_id"]])
        if ex["config"] == "A":
            config_a.append(n)
        else:
            config_b.append(n)

    median_a = float(np.median(config_a))
    median_b = float(np.median(config_b))
    superior = "A" if median_a >= median_b else "B"

    _, p_val = mannwhitneyu(config_a, config_b, alternative="two-sided")

    return {
        "total_unique_edges": len(all_edges),
        "config_a_median_edges": median_a,
        "config_b_median_edges": median_b,
        "superior_config": superior,
        "p_value": float(p_val),
    }


def find_regression_suite(bitmaps):
    """Find minimum test suite covering all observed edges."""
    all_edges = set()
    for edges in bitmaps.values():
        all_edges.update(edges)

    uncovered = set(all_edges)
    corpus = []
    remaining = set(bitmaps.keys())

    while uncovered and remaining:
        best_id = None
        best_count = -1
        for tid in sorted(remaining):
            count = len(bitmaps[tid] & uncovered)
            if count > best_count:
                best_count = count
                best_id = tid
        if best_count == 0:
            break
        corpus.append(best_id)
        uncovered -= bitmaps[best_id]
        remaining.discard(best_id)

    return {
        "test_ids": sorted(corpus),
        "suite_size": len(corpus),
        "coverage_edges": len(all_edges),
    }


def main():
    data = load_and_validate()

    results = {
        "data_quality": {
            "total_records": len(data["executions"]),
            "valid_records": len(data["valid_executions"]),
            "corrupted_records": data["corrupted_ids"],
            "orphan_coverage_files": data["orphans"],
        },
        "protocol_model": analyze_protocol(data["valid_executions"]),
        "effectiveness": analyze_effectiveness(
            data["valid_executions"], data["bitmaps"]
        ),
        "regression_suite": find_regression_suite(data["bitmaps"]),
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
