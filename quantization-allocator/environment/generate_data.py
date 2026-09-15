#!/usr/bin/env python3
"""
Generate multi-format quantization profiling data for a mixed MoE transformer.

Creates:
  /app/model.db          - SQLite: architecture, modules, dag_edges
  /app/measurements/     - Parquet: per-type measurement options
  /app/constraints.toml  - TOML: budget and precision constraints
"""
import json
import math
import os
import random
import sqlite3

random.seed(20240619)

HIDDEN_SIZE = 5120
NUM_HEADS = 40
NUM_KV_HEADS = 8
INTERMEDIATE_SIZE = 13824
NUM_LAYERS = 32
MOE_LAYERS = list(range(8, 16))
NUM_EXPERTS = 4

NUMEL_Q = HIDDEN_SIZE * HIDDEN_SIZE
NUMEL_KV = HIDDEN_SIZE * (HIDDEN_SIZE * NUM_KV_HEADS // NUM_HEADS)
NUMEL_O = HIDDEN_SIZE * HIDDEN_SIZE
NUMEL_ATTN = NUMEL_Q + 2 * NUMEL_KV + NUMEL_O
NUMEL_MLP = HIDDEN_SIZE * INTERMEDIATE_SIZE * 3
NUMEL_EXPERT = NUMEL_MLP
NUMEL_ROUTER = HIDDEN_SIZE * NUM_EXPERTS

CONFIGS = [
    (2.10, "2b_aggressive"), (2.50, "2b3b_mixed_low"), (3.00, "3b_standard"),
    (3.50, "3b4b_mixed"), (4.00, "4b_standard"), (4.25, "4b_fine_groups"),
    (4.50, "4b5b_mixed"), (5.00, "5b_standard"), (5.50, "5b6b_mixed"),
    (6.00, "6b_standard"), (6.50, "6b8b_mixed"), (8.00, "8b_full"),
]
TARGET_BPW = 3.8


def compute_error(bpw, layer_idx, module_type, rng):
    base_error = 0.08 * math.exp(-0.45 * (bpw - 2.0))
    x = (layer_idx - (NUM_LAYERS - 1) / 2) / ((NUM_LAYERS - 1) / 2)
    sensitivity = 1.0 + 0.6 * x * x
    if module_type == "mlp":
        sensitivity *= 0.85
    elif module_type.startswith("expert"):
        sensitivity *= 0.78
    elif module_type == "router":
        sensitivity *= 2.5
    variation = 1.0 + rng.gauss(0, 0.08)
    variation = max(0.5, min(1.8, variation))
    return max(base_error * sensitivity * variation, 1e-9)


def compute_prop_coeff(src_type, dst_type, layer_idx, rng):
    if src_type == "attn":
        base = 0.06 if dst_type in ("mlp", "router") else 0.04
    elif src_type == "router":
        base = 0.08
    elif src_type.startswith("expert") or src_type == "mlp":
        base = 0.035
    else:
        base = 0.03
    if layer_idx in (0, 1, 30, 31):
        base *= 1.3
    base *= (1.0 + rng.gauss(0, 0.08))
    return max(0.01, min(0.12, round(base, 6)))


def main():
    os.makedirs("/app/measurements", exist_ok=True)
    db_path = "/app/model.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("CREATE TABLE architecture (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("""CREATE TABLE modules (
        id INTEGER PRIMARY KEY, layer_idx INTEGER,
        module_type TEXT, numel INTEGER, measurement_group TEXT)""")
    cur.execute("""CREATE TABLE dag_edges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        src_module_id INTEGER, dst_module_id INTEGER,
        propagation_coeff REAL,
        FOREIGN KEY (src_module_id) REFERENCES modules(id),
        FOREIGN KEY (dst_module_id) REFERENCES modules(id))""")

    for k, v in [
        ("model_name", "CustomMoE-32L"), ("hidden_size", str(HIDDEN_SIZE)),
        ("num_heads", str(NUM_HEADS)), ("num_kv_heads", str(NUM_KV_HEADS)),
        ("intermediate_size", str(INTERMEDIATE_SIZE)),
        ("num_layers", str(NUM_LAYERS)),
        ("moe_layers", json.dumps(MOE_LAYERS)),
        ("num_experts", str(NUM_EXPERTS)),
    ]:
        cur.execute("INSERT INTO architecture VALUES (?,?)", (k, v))

    mid = 0
    total_numel = 0
    layer_map = {}
    pinned_mods = []
    meas = {"attention": [], "mlp": [], "router": [], "expert": []}

    for li in range(NUM_LAYERS):
        is_moe = li in MOE_LAYERS
        layer_map[li] = {}

        cur.execute("INSERT INTO modules VALUES (?,?,?,?,?)",
                    (mid, li, "attn", NUMEL_ATTN, "attention"))
        layer_map[li]["attn"] = mid
        total_numel += NUMEL_ATTN
        rng = random.Random(li * 10000 + 42)
        for oi, (nb, desc) in enumerate(CONFIGS):
            tb = int(NUMEL_ATTN * nb) + int(NUMEL_ATTN * 0.03)
            bpw = tb / NUMEL_ATTN
            err = compute_error(nb, li, "attn", rng)
            if 1 < oi < len(CONFIGS) - 1 and rng.random() < 0.15:
                err *= (1.0 + rng.uniform(0.03, 0.15))
            meas["attention"].append({
                "module_id": mid, "option_idx": oi, "total_bits": tb,
                "error": round(err, 12), "bpw": round(bpw, 6),
                "config_desc": desc})
        mid += 1

        if is_moe:
            cur.execute("INSERT INTO modules VALUES (?,?,?,?,?)",
                        (mid, li, "router", NUMEL_ROUTER, "router"))
            layer_map[li]["router"] = mid
            total_numel += NUMEL_ROUTER
            pinned_mods.append((mid, 6.0, "MoE routing layer %d" % li))
            rng = random.Random(li * 10000 + 999)
            for oi, (nb, desc) in enumerate(CONFIGS):
                tb = int(NUMEL_ROUTER * nb) + int(NUMEL_ROUTER * 0.05)
                bpw = tb / NUMEL_ROUTER
                err = compute_error(nb, li, "router", rng)
                meas["router"].append({
                    "module_id": mid, "option_idx": oi, "total_bits": tb,
                    "error": round(err, 12), "bpw": round(bpw, 6),
                    "config_desc": desc})
            mid += 1

            for ei in range(NUM_EXPERTS):
                mt = "expert_%d" % ei
                cur.execute("INSERT INTO modules VALUES (?,?,?,?,?)",
                            (mid, li, mt, NUMEL_EXPERT, "expert"))
                layer_map[li][mt] = mid
                total_numel += NUMEL_EXPERT
                rng = random.Random(li * 10000 + ei * 1000 + 77)
                for oi, (nb, desc) in enumerate(CONFIGS):
                    tb = int(NUMEL_EXPERT * nb) + int(NUMEL_EXPERT * 0.03)
                    bpw = tb / NUMEL_EXPERT
                    err = compute_error(nb, li, mt, rng)
                    if 1 < oi < len(CONFIGS) - 1 and rng.random() < 0.15:
                        err *= (1.0 + rng.uniform(0.03, 0.15))
                    meas["expert"].append({
                        "module_id": mid, "option_idx": oi, "total_bits": tb,
                        "error": round(err, 12), "bpw": round(bpw, 6),
                        "config_desc": desc})
                mid += 1
        else:
            cur.execute("INSERT INTO modules VALUES (?,?,?,?,?)",
                        (mid, li, "mlp", NUMEL_MLP, "mlp"))
            layer_map[li]["mlp"] = mid
            total_numel += NUMEL_MLP
            rng = random.Random(li * 10000 + 500)
            for oi, (nb, desc) in enumerate(CONFIGS):
                tb = int(NUMEL_MLP * nb) + int(NUMEL_MLP * 0.03)
                bpw = tb / NUMEL_MLP
                err = compute_error(nb, li, "mlp", rng)
                if 1 < oi < len(CONFIGS) - 1 and rng.random() < 0.15:
                    err *= (1.0 + rng.uniform(0.03, 0.15))
                meas["mlp"].append({
                    "module_id": mid, "option_idx": oi, "total_bits": tb,
                    "error": round(err, 12), "bpw": round(bpw, 6),
                    "config_desc": desc})
            mid += 1

    # DAG edges
    dag_rng = random.Random(42424242)
    for li in range(NUM_LAYERS):
        is_moe = li in MOE_LAYERS
        lm = layer_map[li]
        if is_moe:
            c = compute_prop_coeff("attn", "router", li, dag_rng)
            cur.execute(
                "INSERT INTO dag_edges (src_module_id, dst_module_id, propagation_coeff) VALUES (?,?,?)",
                (lm["attn"], lm["router"], c))
            for ei in range(NUM_EXPERTS):
                c = compute_prop_coeff("router", "expert", li, dag_rng)
                cur.execute(
                    "INSERT INTO dag_edges (src_module_id, dst_module_id, propagation_coeff) VALUES (?,?,?)",
                    (lm["router"], lm["expert_%d" % ei], c))
        else:
            c = compute_prop_coeff("attn", "mlp", li, dag_rng)
            cur.execute(
                "INSERT INTO dag_edges (src_module_id, dst_module_id, propagation_coeff) VALUES (?,?,?)",
                (lm["attn"], lm["mlp"], c))
        if li < NUM_LAYERS - 1:
            na = layer_map[li + 1]["attn"]
            if is_moe:
                for ei in range(NUM_EXPERTS):
                    c = compute_prop_coeff("expert", "attn", li, dag_rng)
                    cur.execute(
                        "INSERT INTO dag_edges (src_module_id, dst_module_id, propagation_coeff) VALUES (?,?,?)",
                        (lm["expert_%d" % ei], na, c))
            else:
                c = compute_prop_coeff("mlp", "attn", li, dag_rng)
                cur.execute(
                    "INSERT INTO dag_edges (src_module_id, dst_module_id, propagation_coeff) VALUES (?,?,?)",
                    (lm["mlp"], na, c))

    weight_budget = int(total_numel * TARGET_BPW)
    for k, v in [("total_numel", str(total_numel)),
                 ("weight_budget", str(weight_budget)),
                 ("target_bpw", str(TARGET_BPW))]:
        cur.execute("INSERT INTO architecture VALUES (?,?)", (k, v))
    conn.commit()

    # Write Parquet measurement files
    import pyarrow as pa
    import pyarrow.parquet as pq
    for gn, rows in meas.items():
        if not rows:
            continue
        tbl = pa.table({
            "module_id": pa.array([r["module_id"] for r in rows], type=pa.int64()),
            "option_idx": pa.array([r["option_idx"] for r in rows], type=pa.int32()),
            "total_bits": pa.array([r["total_bits"] for r in rows], type=pa.int64()),
            "error": pa.array([r["error"] for r in rows], type=pa.float64()),
            "bpw": pa.array([r["bpw"] for r in rows], type=pa.float64()),
            "config_desc": pa.array([r["config_desc"] for r in rows], type=pa.string()),
        })
        pq.write_table(tbl, "/app/measurements/%s.parquet" % gn)

    # Write TOML constraints
    lines = [
        "# Quantization deployment constraints",
        "",
        "[budget]",
        "weight_budget = %d" % weight_budget,
        "target_bpw = %.1f" % TARGET_BPW,
        "",
    ]
    for gn, sl, el, mb, desc in [
        ("edge_start", 0, 1, 6.0,
         "First 2 layers require high precision for embedding stability"),
        ("edge_end", 30, 31, 6.0,
         "Last 2 layers require high precision for output quality"),
        ("moe_block", 8, 15, 0.0,
         "MoE layers - routers pinned separately"),
        ("standard_pre", 2, 7, 0.0,
         "Standard layers before MoE"),
        ("standard_post", 16, 29, 0.0,
         "Standard layers after MoE"),
    ]:
        lines += [
            "[[layer_groups]]",
            'group_name = "%s"' % gn,
            "start_layer = %d" % sl,
            "end_layer = %d" % el,
            "min_bpw = %.1f" % mb,
            'description = "%s"' % desc,
            "",
        ]
    for pmid, mbpw, reason in pinned_mods:
        lines += [
            "[[pinned_modules]]",
            "module_id = %d" % pmid,
            "required_min_bpw = %.1f" % mbpw,
            'reason = "%s"' % reason,
            "",
        ]
    with open("/app/constraints.toml", "w") as f:
        f.write("\n".join(lines))

    cur2 = conn.cursor()
    cur2.execute("SELECT COUNT(*) FROM modules")
    nm = cur2.fetchone()[0]
    cur2.execute("SELECT COUNT(*) FROM dag_edges")
    ne = cur2.fetchone()[0]
    conn.close()
    print("Generated: %d modules, %d DAG edges, budget=%d" % (nm, ne, weight_budget))


if __name__ == "__main__":
    main()
