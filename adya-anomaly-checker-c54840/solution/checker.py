#!/usr/bin/env python3

"""
Transaction history anomaly checker based on Adya, Liskov & O'Neil's
Generalized Isolation Level Definitions, for Jepsen-style EDN
list-append histories with Graphviz dependency graph output.
"""

import json
import sys
import argparse
from collections import defaultdict

import edn_format


def kw_str(k):
    """Convert an EDN keyword to a plain string."""
    s = str(k)
    return s[1:] if s.startswith(":") else s


def parse_edn_history(path):
    """Parse a Jepsen-style EDN history file into internal format."""
    with open(path) as f:
        raw = f.read()
    data = edn_format.loads(raw)

    history_key = edn_format.Keyword("history")
    index_key = edn_format.Keyword("index")
    type_key = edn_format.Keyword("type")
    value_key = edn_format.Keyword("value")

    transactions = []
    for entry in data[history_key]:
        txn_id = entry[index_key]
        txn_type = kw_str(entry[type_key])

        ops = []
        for op_vec in entry[value_key]:
            op_type = kw_str(op_vec[0])
            key = kw_str(op_vec[1])

            if op_type == "append":
                ops.append({"op": "append", "key": key, "val": op_vec[2]})
            elif op_type == "r":
                val_list = list(op_vec[2]) if len(op_vec) > 2 and op_vec[2] is not None else []
                ops.append({"op": "r", "key": key, "val": val_list})

        transactions.append({"id": txn_id, "type": txn_type, "ops": ops})

    return {"transactions": transactions}


def analyze(history):
    """Analyze transaction history for Adya anomalies."""
    txns = history["transactions"]

    # --- Index construction ---
    txn_status = {t["id"]: t["type"] for t in txns}
    committed = {tid for tid, s in txn_status.items() if s == "ok"}
    aborted = {tid for tid, s in txn_status.items() if s == "fail"}

    # val -> (txn_id, key): which transaction appended each unique value
    val_origin = {}
    for t in txns:
        for op in t["ops"]:
            if op["op"] == "append":
                val_origin[op["val"]] = (t["id"], op["key"])

    # (txn_id, key) -> [vals appended in operation order]
    txn_key_appends = defaultdict(list)
    for t in txns:
        for op in t["ops"]:
            if op["op"] == "append":
                txn_key_appends[(t["id"], op["key"])].append(op["val"])

    # key -> [(reader_txn_id, [observed_vals])]
    key_reads = defaultdict(list)
    for t in txns:
        for op in t["ops"]:
            if op["op"] == "r":
                key_reads[op["key"]].append((t["id"], op["val"]))

    # --- Version order inference ---
    version_orders = {}
    for key, reads in key_reads.items():
        longest = max(reads, key=lambda r: len(r[1]))[1]
        version_orders[key] = list(longest)

    committed_vals_per_key = defaultdict(set)
    for val, (tid, key) in val_origin.items():
        if tid in committed:
            committed_vals_per_key[key].add(val)

    for key, cvals in committed_vals_per_key.items():
        if key not in version_orders:
            version_orders[key] = []
        observed = set(version_orders[key])
        unobserved = cvals - observed
        if len(unobserved) == 1:
            version_orders[key] = version_orders[key] + list(unobserved)

    # --- Dependency graph construction (committed txns only) ---
    # edges now include key for DOT labeling: (from_txn, to_txn, edge_type, key)
    edges = set()

    # ww edges: consecutive values in version order written by different txns
    for key, order in version_orders.items():
        for i in range(len(order) - 1):
            v1, v2 = order[i], order[i + 1]
            if v1 in val_origin and v2 in val_origin:
                t1 = val_origin[v1][0]
                t2 = val_origin[v2][0]
                if t1 != t2 and t1 in committed and t2 in committed:
                    edges.add((t1, t2, "ww", key))

    # wr edges: reader observed a value the writer committed
    for key, reads in key_reads.items():
        for txn_r, vals in reads:
            if txn_r not in committed:
                continue
            for val in vals:
                if val in val_origin:
                    txn_w = val_origin[val][0]
                    if txn_w != txn_r and txn_w in committed:
                        edges.add((txn_w, txn_r, "wr", key))

    # rw edges (anti-dependencies)
    for key, reads in key_reads.items():
        order = version_orders.get(key, [])
        for txn_r, vals in reads:
            if txn_r not in committed:
                continue
            if not vals:
                if order:
                    first_val = order[0]
                    if first_val in val_origin:
                        txn_w = val_origin[first_val][0]
                        if txn_w != txn_r and txn_w in committed:
                            edges.add((txn_r, txn_w, "rw", key))
            else:
                last_val = vals[-1]
                try:
                    idx = order.index(last_val)
                except ValueError:
                    continue
                if idx + 1 < len(order):
                    next_val = order[idx + 1]
                    if next_val in val_origin:
                        txn_w = val_origin[next_val][0]
                        if txn_w != txn_r and txn_w in committed:
                            edges.add((txn_r, txn_w, "rw", key))

    # --- Build adjacency structures ---
    adj = defaultdict(set)
    pair_types = defaultdict(set)  # (from, to) -> {edge_types}
    for f, t, et, k in edges:
        adj[f].add(t)
        pair_types[(f, t)].add(et)

    # --- Find all simple cycles ---
    all_nodes = sorted(
        set(adj.keys()) | {n for ns in adj.values() for n in ns}
    )
    cycles = []

    def _find_cycles(start):
        def dfs(node, path, visited):
            for nb in sorted(adj.get(node, set())):
                if nb == start and len(path) >= 2:
                    cycles.append(tuple(path))
                elif nb not in visited and nb > start:
                    visited.add(nb)
                    path.append(nb)
                    dfs(nb, path, visited)
                    path.pop()
                    visited.discard(nb)

        dfs(start, [start], {start})

    for node in all_nodes:
        _find_cycles(node)

    # --- Anomaly classification ---
    anomalies = set()
    cycle_edge_pairs = set()  # (from, to) pairs in any cycle

    # G1a: committed transaction reads value from aborted transaction
    for key, reads in key_reads.items():
        for txn_r, vals in reads:
            if txn_r not in committed:
                continue
            for val in vals:
                if val in val_origin:
                    txn_w = val_origin[val][0]
                    if txn_w in aborted:
                        anomalies.add("G1a")

    # G1b: committed transaction sees partial writes of another committed txn
    for key, reads in key_reads.items():
        for txn_r, vals in reads:
            if txn_r not in committed:
                continue
            vals_set = set(vals)
            for (tw_id, tw_key), tw_vals in txn_key_appends.items():
                if tw_key != key or tw_id == txn_r or tw_id not in committed:
                    continue
                tw_set = set(tw_vals)
                observed = vals_set & tw_set
                if observed and observed < tw_set:
                    anomalies.add("G1b")

    # Cycle-based anomalies
    for cycle in cycles:
        n = len(cycle)
        pairs = [(cycle[i], cycle[(i + 1) % n]) for i in range(n)]
        ptypes = [pair_types.get(p, set()) for p in pairs]

        # Mark cycle edges
        for p in pairs:
            cycle_edge_pairs.add(p)

        # G0: every pair has a ww edge available
        if all("ww" in pt for pt in ptypes):
            anomalies.add("G0")
            anomalies.add("G1c")

        # G1c: every pair has ww or wr (no rw forced)
        if all(pt & {"ww", "wr"} for pt in ptypes):
            anomalies.add("G1c")

        # Anti-dependency classification
        forced_rw = sum(1 for pt in ptypes if not (pt & {"ww", "wr"}))
        has_rw = any("rw" in pt for pt in ptypes)

        if forced_rw >= 1:
            anomalies.add("G2-item")
            if forced_rw == 1:
                anomalies.add("G-single")
        elif has_rw:
            anomalies.add("G2-item")
            anomalies.add("G-single")

    # Ensure implication closure
    if "G0" in anomalies:
        anomalies.add("G1c")
    if "G-single" in anomalies:
        anomalies.add("G2-item")

    # --- Max isolation level ---
    if "G0" in anomalies:
        max_level = "none"
    elif anomalies & {"G1a", "G1b", "G1c"}:
        max_level = "read-uncommitted"
    elif anomalies & {"G-single", "G2-item"}:
        max_level = "read-committed"
    else:
        max_level = "serializable"

    return {
        "anomalies": sorted(anomalies),
        "max_isolation_level": max_level,
        "_edges": edges,
        "_cycle_edge_pairs": cycle_edge_pairs,
    }


def generate_dot(result, output_path):
    """Generate a Graphviz DOT file for the dependency graph."""
    edges = result["_edges"]
    cycle_edge_pairs = result["_cycle_edge_pairs"]

    nodes = set()
    for f, t, et, k in edges:
        nodes.add(f)
        nodes.add(t)

    color_map = {"ww": "blue", "wr": "green", "rw": "red"}

    lines = ["digraph dependencies {"]
    for n in sorted(nodes):
        lines.append(f'  T{n} [label="T{n}"];')

    for f, t, et, k in sorted(edges):
        color = color_map.get(et, "black")
        bold = ' style="bold"' if (f, t) in cycle_edge_pairs else ""
        lines.append(f'  T{f} -> T{t} [label="{et}:{k}" color="{color}"{bold}];')

    lines.append("}")

    with open(output_path, "w") as fout:
        fout.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Transaction history anomaly checker"
    )
    parser.add_argument("history", help="Path to EDN history file")
    parser.add_argument("--dot", help="Path to write DOT dependency graph")
    args = parser.parse_args()

    history = parse_edn_history(args.history)
    result = analyze(history)

    if args.dot:
        generate_dot(result, args.dot)

    output = {
        "anomalies": result["anomalies"],
        "max_isolation_level": result["max_isolation_level"],
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
