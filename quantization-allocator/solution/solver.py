#!/usr/bin/env python3

"""
Quantization DAG optimizer: reads SQLite + Parquet + TOML,
minimizes max effective error with recursive DAG propagation.
"""

import json
import sqlite3
import tomllib
import pyarrow.parquet as pq


def load_data():
    conn = sqlite3.connect("/app/model.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT value FROM architecture WHERE key='weight_budget'")
    weight_budget = int(cur.fetchone()["value"])

    cur.execute(
        "SELECT id, layer_idx, module_type, numel "
        "FROM modules ORDER BY id")
    modules = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT src_module_id, dst_module_id, propagation_coeff "
        "FROM dag_edges")
    edges = cur.fetchall()
    conn.close()

    predecessors = {m["id"]: [] for m in modules}
    dag_coeffs = {}
    for e in edges:
        s = e["src_module_id"]
        d = e["dst_module_id"]
        c = e["propagation_coeff"]
        predecessors[d].append(s)
        dag_coeffs[(s, d)] = c

    measurements = {}
    for grp in ("attention", "mlp", "router", "expert"):
        tbl = pq.read_table("/app/measurements/%s.parquet" % grp)
        d = tbl.to_pydict()
        for i in range(len(d["module_id"])):
            mid = d["module_id"][i]
            if mid not in measurements:
                measurements[mid] = []
            measurements[mid].append({
                "option_idx": d["option_idx"][i],
                "total_bits": d["total_bits"][i],
                "error": d["error"][i],
                "bpw": d["bpw"][i],
            })
    for mid in measurements:
        measurements[mid].sort(key=lambda x: x["option_idx"])

    with open("/app/constraints.toml", "rb") as f:
        constraints = tomllib.load(f)
    layer_groups = [
        lg for lg in constraints.get("layer_groups", [])
        if lg.get("min_bpw", 0) > 0]
    pinned = {}
    for pm in constraints.get("pinned_modules", []):
        pinned[pm["module_id"]] = pm["required_min_bpw"]

    return (modules, measurements, weight_budget,
            predecessors, dag_coeffs, layer_groups, pinned)


def get_eligible(modules, measurements, pinned, layer_groups):
    eligible = {}
    for mod in modules:
        mid = mod["id"]
        li = mod["layer_idx"]
        min_bpw = 0.0
        if mid in pinned:
            min_bpw = max(min_bpw, pinned[mid])
        for lg in layer_groups:
            if lg["start_layer"] <= li <= lg["end_layer"]:
                min_bpw = max(min_bpw, lg["min_bpw"])
        opts = []
        for m in measurements[mid]:
            if m["bpw"] >= min_bpw - 1e-9:
                opts.append((m["option_idx"], m["total_bits"], m["error"]))
        eligible[mid] = opts
    return eligible


def compute_eff_errors(module_ids, own_errors, predecessors, dag_coeffs):
    """Compute effective errors with recursive DAG propagation."""
    eff = {}
    for mid in module_ids:
        upstream = sum(
            dag_coeffs.get((p, mid), 0) * eff[p]
            for p in predecessors[mid] if p in eff)
        eff[mid] = own_errors[mid] + upstream
    return eff


def main():
    (modules, measurements, weight_budget,
     predecessors, dag_coeffs, layer_groups, pinned) = load_data()
    eligible = get_eligible(modules, measurements, pinned, layer_groups)
    module_ids = [m["id"] for m in modules]

    # Binary search for minimum max effective error threshold
    max_raw = max(
        err for mid in module_ids for _, _, err in eligible[mid])
    lo, hi = 0.0, max_raw * 1.5
    best_assignment = None

    for _ in range(200):
        T = (lo + hi) / 2.0
        assignment = {}
        eff_so_far = {}
        total = 0
        feasible = True

        for mid in module_ids:
            upstream = sum(
                dag_coeffs.get((p, mid), 0) * eff_so_far[p]
                for p in predecessors[mid] if p in eff_so_far)
            max_own = T - upstream
            best_opt = None
            best_bits = float("inf")
            for oidx, bits, err in eligible[mid]:
                if err <= max_own + 1e-15 and bits < best_bits:
                    best_opt = (oidx, bits, err)
                    best_bits = bits
            if best_opt is None:
                feasible = False
                break
            assignment[mid] = best_opt
            eff_so_far[mid] = best_opt[2] + upstream
            total += best_bits

        if feasible and total <= weight_budget:
            best_assignment = dict(assignment)
            hi = T
        else:
            lo = T

    if best_assignment is None:
        raise RuntimeError("No feasible solution within weight budget")

    # Greedy post-processing: spend remaining budget reducing errors
    total = sum(best_assignment[mid][1] for mid in module_ids)

    changed = True
    while changed:
        changed = False
        own_map = {mid: best_assignment[mid][2] for mid in module_ids}
        eff = compute_eff_errors(
            module_ids, own_map, predecessors, dag_coeffs)

        best_upgrade = None
        best_priority = None

        for mid in module_ids:
            curr_oidx, curr_bits, curr_err = best_assignment[mid]
            curr_eff = eff[mid]

            for oidx, bits, err in eligible[mid]:
                if oidx == curr_oidx:
                    continue
                delta = bits - curr_bits
                if delta <= 0 or total + delta > weight_budget:
                    continue
                if err >= curr_err - 1e-15:
                    continue

                priority = (curr_eff, curr_err - err, -mid)
                if best_priority is None or priority > best_priority:
                    best_priority = priority
                    best_upgrade = (mid, oidx, bits, err, delta)

        if best_upgrade:
            mid, oidx, bits, err, delta = best_upgrade
            best_assignment[mid] = (oidx, bits, err)
            total += delta
            changed = True

    # Build output
    own_map = {mid: best_assignment[mid][2] for mid in module_ids}
    eff = compute_eff_errors(
        module_ids, own_map, predecessors, dag_coeffs)
    total_bits = sum(best_assignment[mid][1] for mid in module_ids)
    max_eff = max(eff.values())
    max_raw = max(best_assignment[mid][2] for mid in module_ids)

    strategy = {
        "assignments": [
            {"module_id": mid, "option_idx": best_assignment[mid][0]}
            for mid in module_ids],
        "total_bits": total_bits,
        "weight_budget": weight_budget,
        "max_effective_error": max_eff,
        "max_raw_error": max_raw,
    }

    with open("/app/strategy.json", "w") as f:
        json.dump(strategy, f, indent=2)

    print("Saved strategy.json")
    print("  Modules: %d" % len(module_ids))
    print("  Total bits: %d / %d (%.4f%%)" % (
        total_bits, weight_budget,
        100.0 * total_bits / weight_budget))
    print("  Max effective error: %.12f" % max_eff)
    print("  Max raw error: %.12f" % max_raw)


if __name__ == "__main__":
    main()
