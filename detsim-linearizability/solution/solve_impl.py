#!/usr/bin/env python3
"""
Solution: Analysis pipeline for deterministic simulation traces.

1. Writes a working /app/pipeline.py that replaces the stub.
2. Runs that pipeline to produce /app/results.json.
3. Creates fault injection configs that trigger specific failures.
"""

import json
import os
import sqlite3
import subprocess
import sys

# ── Step 1: Write the full pipeline.py into /app ─────────────────────────

PIPELINE_SRC = r'''#!/usr/bin/env python3
"""
Analysis pipeline: connects to /app/traces.db, checks linearizability
of each simulation run, detects split-brain, and writes results.json.
"""

import json
import sqlite3
from itertools import combinations


def get_operations(conn, run_id):
    rows = conn.execute(
        "SELECT op_type, arg, invoke_time, response_time, "
        "response_value, target_node FROM operations "
        "WHERE run_id=? ORDER BY invoke_time",
        (run_id,),
    ).fetchall()
    ops = []
    for r in rows:
        rval = r[4]
        if rval is not None:
            rval = json.loads(rval)
        ops.append({
            "op_type": r[0], "arg": r[1], "invoke_time": r[2],
            "response_time": r[3], "response_value": rval, "target_node": r[5],
        })
    return ops


def _apply_op(op, state):
    if op["op_type"] == "write":
        return op["arg"], True
    elif op["op_type"] == "read":
        rval = op["response_value"]
        if rval is None:
            return state, True
        return state, rval == state
    return state, False


def _dfs(ops, state, done, count, total):
    if count == total:
        return True
    for i in range(total):
        if done[i]:
            continue
        op = ops[i]
        can_go = True
        for j in range(total):
            if done[j] or j == i:
                continue
            other = ops[j]
            other_resp = (other["response_time"]
                          if other["response_time"] is not None
                          else float("inf"))
            if other_resp < op["invoke_time"]:
                can_go = False
                break
        if not can_go:
            continue
        ns, m = _apply_op(op, state)
        if m:
            done[i] = True
            if _dfs(ops, ns, done, count + 1, total):
                return True
            done[i] = False
    return False


def is_linearizable(ops):
    completed = [o for o in ops if o["response_time"] is not None]
    crashed = [o for o in ops if o["response_time"] is None]
    for r in range(len(crashed) + 1):
        for subset in combinations(crashed, r):
            all_ops = completed + list(subset)
            if not all_ops:
                return True
            n = len(all_ops)
            if _dfs(all_ops, 0, [False] * n, 0, n):
                return True
    return False


def has_multi_primary(conn, run_id):
    row = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT time FROM node_states WHERE run_id=? AND role='primary'"
        "  GROUP BY time HAVING COUNT(DISTINCT node_id) > 1"
        ")",
        (run_id,),
    ).fetchone()
    return row[0] > 0


def main():
    db_path = "/app/traces.db"
    conn = sqlite3.connect(db_path)
    run_ids = [r[0] for r in conn.execute(
        "SELECT run_id FROM runs ORDER BY run_id"
    ).fetchall()]

    results = {}
    for rid in run_ids:
        ops = get_operations(conn, rid)
        lin = is_linearizable(ops)
        multi = has_multi_primary(conn, rid)
        violation = "none" if lin else "split_brain"
        results[str(rid)] = {
            "linearizable": lin,
            "violation": violation,
            "has_multi_primary": multi,
        }

    conn.close()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
'''

def write_pipeline():
    with open("/app/pipeline.py", "w") as f:
        f.write(PIPELINE_SRC)
    print("Wrote /app/pipeline.py")


# ── Step 2: Run the pipeline ─────────────────────────────────────────────

def run_pipeline():
    result = subprocess.run(
        [sys.executable, "/app/pipeline.py"],
        capture_output=True, text=True, cwd="/app",
    )
    if result.returncode != 0:
        print(f"pipeline.py failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    with open("/app/results.json") as f:
        data = json.load(f)
    for rid in sorted(data.keys(), key=int):
        r = data[rid]
        status = "OK" if r["linearizable"] else f"VIOLATION: {r['violation']}"
        print(f"Run {rid}: {status} (multi_primary={r['has_multi_primary']})")
    print(f"\nWrote /app/results.json with {len(data)} entries")


# ── Step 3: Write fault injection configs ────────────────────────────────

def write_fault_configs():
    os.makedirs("/app/fault_configs", exist_ok=True)

    # Config 1: Trigger split-brain with seed 7777
    # Partition isolating node 0 (initial primary) from majority.
    # Majority elects new primary -> dual primaries -> non-linearizable.
    with open("/app/fault_configs/trigger_split_brain.toml", "w") as f:
        f.write("""[simulation]
seed = 7777
node_count = 5
duration = 800
election_timeout = 60.0

[clients]
count = 5
request_interval = 30.0
write_ratio = 0.5

[[faults.schedule]]
type = "partition"
set_a = [0]
set_b = [1, 2, 3, 4]
time = 150
heal_after = 400
""")

    # Config 2: Extended split with >= 5 ops on each primary (seed 8888)
    # Long partition + high client rate ensures many ops on both sides.
    with open("/app/fault_configs/trigger_extended_split.toml", "w") as f:
        f.write("""[simulation]
seed = 8888
node_count = 5
duration = 1200
election_timeout = 50.0

[clients]
count = 5
request_interval = 20.0
write_ratio = 0.5

[[faults.schedule]]
type = "partition"
set_a = [0]
set_b = [1, 2, 3, 4]
time = 100
heal_after = 800
""")

    print("Wrote fault injection configs to /app/fault_configs/")


def main():
    write_pipeline()
    run_pipeline()
    write_fault_configs()


if __name__ == "__main__":
    main()
