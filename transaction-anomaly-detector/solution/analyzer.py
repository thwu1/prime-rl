#!/usr/bin/env python3

"""
Complete transaction history anomaly analyzer.
Handles JSON, EDN, and SQLite input formats.
Correctly detects G0, G1a, G1b, G1c, G-single, G2-item anomalies
and determines the strongest portable isolation level (PL-0..PL-3).
"""

import json
import os
import sqlite3
from collections import defaultdict


# ---------------------------------------------------------------------------
# EDN parser (handles the subset used by Jepsen Elle histories)
# ---------------------------------------------------------------------------

def _skip_ws_and_commas(text, pos):
    while pos < len(text) and text[pos] in " \t\n\r,":
        pos += 1
    return pos


def _parse_edn_value(text, pos):
    pos = _skip_ws_and_commas(text, pos)
    if pos >= len(text):
        return None, pos

    ch = text[pos]

    # nil
    if text[pos : pos + 3] == "nil" and (
        pos + 3 >= len(text) or text[pos + 3] in " \t\n\r,}])"
    ):
        return None, pos + 3

    # true / false
    if text[pos : pos + 4] == "true" and (
        pos + 4 >= len(text) or text[pos + 4] in " \t\n\r,}])"
    ):
        return True, pos + 4
    if text[pos : pos + 5] == "false" and (
        pos + 5 >= len(text) or text[pos + 5] in " \t\n\r,}])"
    ):
        return False, pos + 5

    # Keyword  :some-keyword
    if ch == ":":
        end = pos + 1
        while end < len(text) and text[end] not in " \t\n\r,}])":
            end += 1
        return text[pos:end], end

    # String
    if ch == '"':
        end = pos + 1
        while end < len(text) and text[end] != '"':
            if text[end] == "\\":
                end += 1
            end += 1
        return text[pos + 1 : end], end + 1

    # Number (integer)
    if ch.isdigit() or (ch == "-" and pos + 1 < len(text) and text[pos + 1].isdigit()):
        end = pos + 1
        while end < len(text) and text[end].isdigit():
            end += 1
        return int(text[pos:end]), end

    # Vector [ ... ]
    if ch == "[":
        pos += 1
        items = []
        while True:
            pos = _skip_ws_and_commas(text, pos)
            if pos < len(text) and text[pos] == "]":
                return items, pos + 1
            item, pos = _parse_edn_value(text, pos)
            items.append(item)

    # Map { ... }
    if ch == "{":
        pos += 1
        result = {}
        while True:
            pos = _skip_ws_and_commas(text, pos)
            if pos < len(text) and text[pos] == "}":
                return result, pos + 1
            key, pos = _parse_edn_value(text, pos)
            val, pos = _parse_edn_value(text, pos)
            result[key] = val

    raise ValueError(f"Unexpected char '{ch}' at position {pos}")


def parse_edn(text):
    # Strip comment lines
    lines = text.split("\n")
    lines = [l for l in lines if not l.strip().startswith(";")]
    cleaned = "\n".join(lines)
    value, _ = _parse_edn_value(cleaned, 0)
    return value


# ---------------------------------------------------------------------------
# History loaders
# ---------------------------------------------------------------------------

def load_json_histories(data_dir):
    histories = {}
    json_dir = os.path.join(data_dir, "json")
    if not os.path.isdir(json_dir):
        return histories
    for fname in os.listdir(json_dir):
        if fname.endswith(".json"):
            name = os.path.splitext(fname)[0]
            with open(os.path.join(json_dir, fname)) as f:
                data = json.load(f)
            histories[name] = data["transactions"]
    return histories


def load_edn_histories(data_dir):
    histories = {}
    edn_dir = os.path.join(data_dir, "edn")
    if not os.path.isdir(edn_dir):
        return histories
    for fname in os.listdir(edn_dir):
        if fname.endswith(".edn"):
            name = os.path.splitext(fname)[0]
            with open(os.path.join(edn_dir, fname)) as f:
                raw = parse_edn(f.read())
            txns = []
            for entry in raw:
                txn = {
                    "id": entry[":txn-id"],
                    "status": entry[":status"].lstrip(":"),
                    "ops": [],
                }
                for op in entry[":ops"]:
                    op_type = op[0].lstrip(":")
                    if op_type == "append":
                        txn["ops"].append(["append", op[1], op[2]])
                    elif op_type == "r":
                        read_val = op[2] if op[2] is not None else []
                        txn["ops"].append(["r", op[1], read_val])
                txns.append(txn)
            histories[name] = txns
    return histories


def load_sqlite_histories(data_dir):
    histories = {}
    db_path = os.path.join(data_dir, "workload.db")
    if not os.path.exists(db_path):
        return histories

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM workloads")
    workloads = cur.fetchall()

    for wl_id, wl_name in workloads:
        cur.execute(
            "SELECT id, txn_seq, outcome FROM txns WHERE workload_id = ? ORDER BY txn_seq",
            (wl_id,),
        )
        txn_rows = cur.fetchall()

        txns = []
        for txn_db_id, txn_seq, outcome in txn_rows:
            cur.execute(
                "SELECT op_idx, type, register, payload FROM ops "
                "WHERE txn_id = ? ORDER BY op_idx",
                (txn_db_id,),
            )
            ops_rows = cur.fetchall()

            ops = []
            for _, op_type, register, payload in ops_rows:
                if op_type == "append":
                    ops.append(["append", register, int(payload)])
                elif op_type == "read":
                    if payload is None:
                        read_val = []
                    else:
                        read_val = json.loads(payload)
                    ops.append(["r", register, read_val])
            txns.append({"id": txn_seq, "status": outcome, "ops": ops})

        histories[wl_name] = txns

    conn.close()
    return histories


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def build_append_index(transactions):
    index = {}
    for txn in transactions:
        for op in txn["ops"]:
            if op[0] == "append":
                index[(op[1], op[2])] = txn["id"]
    return index


def build_version_order(committed_txns):
    key_versions = {}
    for txn in committed_txns:
        for op in txn["ops"]:
            if op[0] == "r":
                key = op[1]
                observed = op[2] if op[2] else []
                if key not in key_versions or len(observed) > len(key_versions[key]):
                    key_versions[key] = list(observed)
    return key_versions


def check_g1a(transactions, append_index):
    """G1a: committed txn reads value written by an aborted txn."""
    aborted_ids = {t["id"] for t in transactions if t["status"] == "aborted"}
    if not aborted_ids:
        return False
    committed = [t for t in transactions if t["status"] == "committed"]
    for txn in committed:
        for op in txn["ops"]:
            if op[0] == "r" and op[2]:
                for val in op[2]:
                    writer = append_index.get((op[1], val))
                    if writer in aborted_ids:
                        return True
    return False


def check_g1b(committed_txns):
    """G1b: committed txn sees intermediate state of another committed txn."""
    txn_key_appends = defaultdict(lambda: defaultdict(list))
    for txn in committed_txns:
        for op in txn["ops"]:
            if op[0] == "append":
                txn_key_appends[txn["id"]][op[1]].append(op[2])

    for txn in committed_txns:
        for op in txn["ops"]:
            if op[0] == "r" and op[2]:
                key = op[1]
                read_vals = set(op[2])
                for other_id, key_appends in txn_key_appends.items():
                    if other_id == txn["id"]:
                        continue
                    if key not in key_appends:
                        continue
                    appended = key_appends[key]
                    if len(appended) < 2:
                        continue
                    seen = [v for v in appended if v in read_vals]
                    if seen and len(seen) < len(appended):
                        return True
    return False


def compute_edges(committed_txns, version_order, append_index):
    committed_ids = {t["id"] for t in committed_txns}
    edges = []

    for key, versions in version_order.items():
        # WW
        for i in range(len(versions) - 1):
            w1 = append_index.get((key, versions[i]))
            w2 = append_index.get((key, versions[i + 1]))
            if w1 and w2 and w1 != w2 and w1 in committed_ids and w2 in committed_ids:
                edges.append((w1, w2, "ww"))

        # WR
        for txn in committed_txns:
            for op in txn["ops"]:
                if op[0] == "r" and op[1] == key:
                    observed = op[2] if op[2] else []
                    for val in observed:
                        writer = append_index.get((key, val))
                        if writer and writer != txn["id"] and writer in committed_ids:
                            edges.append((writer, txn["id"], "wr"))

        # RW
        for txn in committed_txns:
            for op in txn["ops"]:
                if op[0] == "r" and op[1] == key:
                    observed = op[2] if op[2] else []
                    if not observed:
                        if versions:
                            first_w = append_index.get((key, versions[0]))
                            if (
                                first_w
                                and first_w != txn["id"]
                                and first_w in committed_ids
                            ):
                                edges.append((txn["id"], first_w, "rw"))
                    else:
                        last_val = observed[-1]
                        try:
                            idx = versions.index(last_val)
                        except ValueError:
                            continue
                        if idx + 1 < len(versions):
                            next_w = append_index.get((key, versions[idx + 1]))
                            if (
                                next_w
                                and next_w != txn["id"]
                                and next_w in committed_ids
                            ):
                                edges.append((txn["id"], next_w, "rw"))

    return edges


def find_cycles(edges, nodes):
    adj = defaultdict(set)
    for src, dst, _ in edges:
        adj[src].add(dst)

    cycles = []

    def dfs(start, current, path, blocked):
        for nb in adj[current]:
            if nb == start and len(path) > 1:
                cycles.append(list(path))
            elif nb not in blocked and nb > start:
                blocked.add(nb)
                path.append(nb)
                dfs(start, nb, path, blocked)
                path.pop()
                blocked.discard(nb)

    for s in sorted(nodes):
        dfs(s, s, [s], {s})

    return cycles


def classify_cycle(cycle, edge_map):
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
    if rw_count == 1:
        return "G-single"
    if rw_count >= 2:
        return "G2-item"
    return None


def strongest_level(anomalies):
    s = set(anomalies)
    if not s:
        return "PL-3"
    if "G0" in s:
        return "PL-0"
    if s & {"G1a", "G1b", "G1c"}:
        return "PL-1"
    return "PL-2"


def analyze_history(transactions):
    committed = [t for t in transactions if t["status"] == "committed"]
    append_index = build_append_index(transactions)
    version_order = build_version_order(committed)

    anomalies = set()

    if check_g1a(transactions, append_index):
        anomalies.add("G1a")
    if check_g1b(committed):
        anomalies.add("G1b")

    edges = compute_edges(committed, version_order, append_index)
    nodes = {t["id"] for t in committed}
    cycles = find_cycles(edges, nodes)

    edge_map = {}
    for src, dst, label in edges:
        edge_map.setdefault((src, dst), set()).add(label)

    for cyc in cycles:
        cls = classify_cycle(cyc, edge_map)
        if cls:
            anomalies.add(cls)

    return {"anomalies": sorted(anomalies), "strongest_level": strongest_level(anomalies)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data_dir = "/app/data"

    all_histories = {}
    all_histories.update(load_json_histories(data_dir))
    all_histories.update(load_edn_histories(data_dir))
    all_histories.update(load_sqlite_histories(data_dir))

    results = {}
    for name in sorted(all_histories):
        results[name] = analyze_history(all_histories[name])

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
