#!/usr/bin/env python3
"""
Jepsen-style consistency checker for distributed system operation histories.

Supports two history types:
  - register: checks linearizability of read/write/CAS operations
  - transactional: detects anomalies (G1a, G1c, G2, causal_reverse) and
    classifies serializability / strict serializability

"""

import json
import sys


# ── Register linearizability ────────────────────────────────────────


def _parse_register_ops(history):
    """Match invoke/response pairs into operations with time windows."""
    ops = []
    pending = {}
    for event in history["operations"]:
        etype = event["type"]
        if etype == "invoke":
            pending[event["process"]] = event
        elif etype in ("ok", "fail"):
            invoke = pending.pop(event["process"])
            ops.append(
                {
                    "f": event["f"],
                    "value": event["value"],
                    "start": invoke["time"],
                    "end": event["time"],
                    "result": etype,
                }
            )
    return ops


def check_linearizability(history):
    """Backtracking search for a valid linearization of register ops.

    An operation can be the next in the linearization only if no
    un-linearized operation must precede it (i.e., completed before it
    began).  For each candidate, we check consistency with the
    sequential register spec and recurse.
    """
    ops = _parse_register_ops(history)
    initial = history.get("initial_value")

    def _try(remaining, cur):
        if not remaining:
            return True
        for i, op in enumerate(remaining):
            # Real-time constraint: skip if some remaining op ended
            # before this one started (that op must come first).
            blocked = False
            for j, other in enumerate(remaining):
                if j != i and other["end"] < op["start"]:
                    blocked = True
                    break
            if blocked:
                continue

            nxt = cur
            f = op["f"]
            if f == "read":
                if op["value"] != cur:
                    continue
            elif f == "write":
                nxt = op["value"]
            elif f == "cas":
                exp, new = op["value"]
                if op["result"] == "ok":
                    if cur != exp:
                        continue
                    nxt = new
                else:  # fail
                    if cur == exp:
                        continue
            else:
                continue

            rest = remaining[:i] + remaining[i + 1 :]
            if _try(rest, nxt):
                return True
        return False

    return _try(ops, initial)


# ── Transaction dependency graph analysis ───────────────────────────


def _has_cycle(edges, nodes):
    """DFS cycle detection on a directed graph."""
    adj = {n: [] for n in nodes}
    for u, v in edges:
        if u in adj:
            adj[u].append(v)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(u):
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


def analyze_transactions(history):
    """Build dependency graph, detect anomalies, classify consistency."""
    txns = history["transactions"]
    initial = history["initial_state"]

    # ── G1a: read from aborted transaction ──────────────────────
    aborted_writes = {}  # key -> {value -> txn_id}
    for t in txns:
        if t["status"] == "aborted":
            for op in t["operations"]:
                if op["f"] == "write":
                    aborted_writes.setdefault(op["key"], {})[op["value"]] = t["id"]

    g1a = False
    for t in txns:
        if t["status"] != "committed":
            continue
        for op in t["operations"]:
            if op["f"] == "read":
                k, v = op["key"], op["value"]
                if k in aborted_writes and v in aborted_writes[k]:
                    if v != initial.get(k):
                        g1a = True

    # ── dependency edges (committed txns only) ──────────────────
    committed = [t for t in txns if t["status"] == "committed"]
    ids = [t["id"] for t in committed]

    # writes per key: key -> [(txn_id, value)]
    write_map = {}
    for t in committed:
        for op in t["operations"]:
            if op["f"] == "write":
                write_map.setdefault(op["key"], []).append((t["id"], op["value"]))

    wr_edges = set()  # write-read (read-from) dependencies
    rw_edges = set()  # read-write anti-dependencies

    for t in committed:
        for op in t["operations"]:
            if op["f"] != "read":
                continue
            k, v = op["key"], op["value"]
            for wid, wval in write_map.get(k, []):
                if wid == t["id"]:
                    continue
                if wval == v:
                    # T_wid wrote the value T read → wr dependency
                    wr_edges.add((wid, t["id"]))
                else:
                    # T read a different version than T_wid wrote →
                    # rw anti-dependency (T's read is "before" T_wid's write)
                    rw_edges.add((t["id"], wid))

    # ── cycle checks ────────────────────────────────────────────
    g1c = _has_cycle(wr_edges, ids)

    all_edges = wr_edges | rw_edges
    any_cycle = _has_cycle(all_edges, ids)
    g2 = any_cycle and not g1c

    serializable = not any_cycle and not g1a

    # ── strict serializability (add real-time constraints) ──────
    rt_edges = set()
    for a in committed:
        for b in committed:
            if a["id"] != b["id"] and a["end_time"] < b["start_time"]:
                rt_edges.add((a["id"], b["id"]))

    strict_serializable = serializable and not _has_cycle(
        all_edges | rt_edges, ids
    )

    # ── assemble anomalies ──────────────────────────────────────
    anomalies = []
    if g1a:
        anomalies.append("G1a")
    if g1c:
        anomalies.append("G1c")
    if g2:
        anomalies.append("G2")
    if serializable and not strict_serializable:
        anomalies.append("causal_reverse")

    return {
        "serializable": serializable,
        "strict_serializable": strict_serializable,
        "anomalies": sorted(anomalies),
    }


# ── main ────────────────────────────────────────────────────────────


def main():
    if len(sys.argv) != 2:
        print("Usage: checker.py <history.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        history = json.load(f)

    htype = history.get("type")
    if htype == "register":
        result = {"linearizable": check_linearizability(history)}
    elif htype == "transactional":
        result = analyze_transactions(history)
    else:
        print(f"Unknown history type: {htype}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
