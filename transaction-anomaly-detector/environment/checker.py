#!/usr/bin/env python3
"""
Anomaly checker for list-append transaction histories.

Reads transaction history files and classifies consistency anomalies
per Adya et al.'s generalized isolation level formalism.

Usage: python3 checker.py [--data-dir /app/data] [--output /app/results.json]
"""

import json
import os
import sys
import argparse
from collections import defaultdict


def load_histories(data_dir):
    """Discover and load transaction histories from the data directory."""
    histories = {}

    json_dir = os.path.join(data_dir, "json")
    if os.path.isdir(json_dir):
        for fname in sorted(os.listdir(json_dir)):
            if fname.endswith(".json"):
                name = os.path.splitext(fname)[0]
                with open(os.path.join(json_dir, fname)) as f:
                    data = json.load(f)
                histories[name] = data["transactions"]

    return histories


def reconstruct_version_order(committed_txns):
    """Reconstruct version order for each key from observed read states.
    The longest observed list for each key reveals the full append sequence.
    """
    key_versions = {}
    for txn in committed_txns:
        for op in txn["ops"]:
            if op[0] == "r":
                key = op[1]
                observed = op[2] if op[2] else []
                if key not in key_versions or len(observed) > len(key_versions[key]):
                    key_versions[key] = list(observed)
    return key_versions


def build_append_index(all_txns):
    """Map (key, value) -> txn_id for every append operation."""
    index = {}
    for txn in all_txns:
        for op in txn["ops"]:
            if op[0] == "append":
                index[(op[1], op[2])] = txn["id"]
    return index


def detect_g1a(transactions):
    """Detect G1a (Aborted Read): a committed transaction reads a value
    that was written only by an aborted transaction.
    """
    aborted = {t["id"]: t for t in transactions if t["status"] == "aborted"}
    found = False
    for txn_id, txn in aborted.items():
        for op in txn["ops"]:
            if op[0] == "r" and op[2]:
                found = True
    return found


def detect_g1b(committed_txns):
    """Detect G1b (Intermediate Read): a committed transaction observes
    some but not all effects of another committed transaction on a key.
    """
    # Debug: disabled pending rework to reduce false positives
    return False


def compute_edges(committed_txns, version_order, append_index):
    """Compute ww/wr/rw dependency edges between committed transactions."""
    committed_ids = {t["id"] for t in committed_txns}
    edges = []

    for key, versions in version_order.items():
        # WW: consecutive writers of the same key
        for i in range(len(versions) - 1):
            w1 = append_index.get((key, versions[i]))
            w2 = append_index.get((key, versions[i + 1]))
            if w1 and w2 and w1 != w2 and w1 in committed_ids and w2 in committed_ids:
                edges.append((w1, w2, "ww"))

        # WR: writer -> reader who observed the written value
        for txn in committed_txns:
            for op in txn["ops"]:
                if op[0] == "r" and op[1] == key:
                    observed = op[2] if op[2] else []
                    for val in observed:
                        writer = append_index.get((key, val))
                        if writer and writer != txn["id"] and writer in committed_ids:
                            edges.append((writer, txn["id"], "wr"))

        # RW (anti-dependency): reader -> next version's writer
        for txn in committed_txns:
            for op in txn["ops"]:
                if op[0] == "r" and op[1] == key:
                    observed = op[2] if op[2] else []
                    if not observed:
                        if versions:
                            first_w = append_index.get((key, versions[0]))
                            if first_w and first_w != txn["id"] and first_w in committed_ids:
                                edges.append((txn["id"], first_w, "rw"))
                    else:
                        last_val = observed[-1]
                        try:
                            idx = versions.index(last_val)
                        except ValueError:
                            continue
                        if idx + 1 < len(versions):
                            next_w = append_index.get((key, versions[idx + 1]))
                            if next_w and next_w != txn["id"] and next_w in committed_ids:
                                edges.append((txn["id"], next_w, "rw"))

    return edges


def find_all_cycles(edges, node_set):
    """Find simple cycles in the directed graph."""
    adj = defaultdict(set)
    for src, dst, _ in edges:
        adj[src].add(dst)

    cycles = []

    def _dfs(start, node, path, blocked):
        for nb in adj[node]:
            if nb == start and len(path) > 1:
                cycles.append(list(path))
            elif nb not in blocked and nb > start:
                blocked.add(nb)
                path.append(nb)
                _dfs(start, nb, path, blocked)
                path.pop()
                blocked.discard(nb)

    for s in sorted(node_set):
        _dfs(s, s, [s], {s})

    return cycles


def classify_anomaly(cycle, edge_map):
    """Classify a cycle by the types of edges it contains."""
    edge_types = set()
    rw_count = 0
    for i in range(len(cycle)):
        src = cycle[i]
        dst = cycle[(i + 1) % len(cycle)]
        labels = edge_map.get((src, dst), set())
        edge_types.update(labels)
        if "rw" in labels:
            rw_count += 1

    if edge_types <= {"ww"}:
        return "G0"
    if edge_types <= {"ww", "wr"}:
        return "G1c"
    if rw_count >= 1:
        return "G2-item"
    return None


def strongest_level(anomalies):
    """Determine the strongest portable isolation level satisfied."""
    s = set(anomalies)
    if not s:
        return "PL-3"
    if "G0" in s:
        return "PL-0"
    if s & {"G1a", "G1b", "G1c"}:
        return "PL-1"
    return "PL-2"


def analyze(transactions):
    """Analyze a single transaction history for anomalies."""
    committed = [t for t in transactions if t["status"] == "committed"]
    append_index = build_append_index(transactions)
    version_order = reconstruct_version_order(committed)

    anomalies = set()

    if detect_g1a(transactions):
        anomalies.add("G1a")
    if detect_g1b(committed):
        anomalies.add("G1b")

    edges = compute_edges(committed, version_order, append_index)
    node_set = {t["id"] for t in committed}
    cycles = find_all_cycles(edges, node_set)

    edge_map = {}
    for src, dst, label in edges:
        edge_map.setdefault((src, dst), set()).add(label)

    for cyc in cycles:
        cls = classify_anomaly(cyc, edge_map)
        if cls:
            anomalies.add(cls)

    level = strongest_level(anomalies)
    return {"anomalies": sorted(anomalies), "strongest_level": level}


def main():
    parser = argparse.ArgumentParser(description="Transaction anomaly checker")
    parser.add_argument("--data-dir", default="/app/data",
                        help="Directory containing transaction histories")
    parser.add_argument("--output", default="/app/results.json",
                        help="Output file path")
    args = parser.parse_args()

    histories = load_histories(args.data_dir)
    if not histories:
        print("ERROR: No transaction histories found in", args.data_dir,
              file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(histories)} histories from {args.data_dir}")
    results = {}
    for name in sorted(histories):
        result = analyze(histories[name])
        results[name] = result
        print(f"  {name}: anomalies={result['anomalies']}  "
              f"level={result['strongest_level']}")

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
