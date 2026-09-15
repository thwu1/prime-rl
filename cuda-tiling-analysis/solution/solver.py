#!/usr/bin/env python3
"""
Solver for the GPU kernel configuration audit task.

"""

import json
import math
import csv
import sqlite3
import itertools

WARPSIZE = 32


def load_gpu_specs(db_path="/app/gpu_specs.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT gpu_name FROM gpu_specs ORDER BY gpu_name")
    gpu_names = [row[0] for row in cursor.fetchall()]
    gpus = {}
    for name in gpu_names:
        cursor.execute(
            "SELECT spec_key, spec_value FROM gpu_specs WHERE gpu_name = ?",
            (name,),
        )
        specs = {}
        for key, value in cursor.fetchall():
            try:
                specs[key] = int(value)
            except ValueError:
                specs[key] = value
        gpus[name] = specs
    conn.close()
    return gpus


def load_param_ranges(csv_path="/app/param_ranges.csv"):
    ranges = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            ranges[row["parameter"]] = [int(v) for v in row["values"].split("|")]
    return ranges


def is_valid(p):
    BM, BN, BK = p["BM"], p["BN"], p["BK"]
    WM, WN, WNITER = p["WM"], p["WN"], p["WNITER"]
    TM, TN, NT = p["TM"], p["TN"], p["NUM_THREADS"]
    NW = NT // WARPSIZE

    # Explicit static_assert constraints from runner_constraints.cu
    if BN % WN != 0:
        return False
    if BM % WM != 0:
        return False
    if (BN // WN) * (BM // WM) != NW:
        return False
    if (WM * WN) % (WARPSIZE * TM * TN * WNITER) != 0:
        return False
    WMI = (WM * WN) // (WARPSIZE * TM * TN * WNITER)
    if WMI < 1:
        return False
    if WM % WMI != 0:
        return False
    if WN % WNITER != 0:
        return False
    if (NT * 4) % BK != 0:
        return False
    if (NT * 4) % BN != 0:
        return False
    if BN % (16 * TN) != 0:
        return False
    if BM % (16 * TM) != 0:
        return False
    if (BM * BK) % (4 * NT) != 0:
        return False
    if (BN * BK) % (4 * NT) != 0:
        return False

    # Implicit constraints from kernel code patterns
    if TN % 4 != 0:
        return False
    WSUBN = WN // WNITER
    if WSUBN % TN != 0:
        return False
    WSUBM = WM // WMI
    if WSUBM % TM != 0:
        return False

    # Physical resource limits
    smem_bytes = (BM + BN) * BK * 4
    if smem_bytes > 49152:
        return False
    if NT > 1024:
        return False

    return True


def compute_smem(p):
    return (p["BM"] + p["BN"]) * p["BK"] * 4


def compute_regs(p):
    WMI = (p["WM"] * p["WN"]) // (WARPSIZE * p["TM"] * p["TN"] * p["WNITER"])
    r = WMI * p["TM"] * p["WNITER"] * p["TN"] + WMI * p["TM"] + p["WNITER"] * p["TN"] + 20
    return min(r, 255)


def compute_occupancy_and_bottleneck(nt, smem, regs, gpu):
    ws = gpu["warp_size"]
    wpb = nt // ws
    sa = gpu["smem_alloc_granularity_bytes"]
    es = math.ceil(smem / sa) * sa if smem > 0 else 0

    if es > gpu["max_smem_per_block_bytes"]:
        return 0.0, "smem"

    bs = gpu["smem_per_sm_bytes"] // es if es > 0 else gpu["max_blocks_per_sm"]
    ra = gpu["reg_alloc_granularity"]
    rpw = math.ceil(regs * ws / ra) * ra
    rpb = rpw * wpb
    br = gpu["max_regs_per_sm"] // rpb if rpb > 0 else gpu["max_blocks_per_sm"]
    bw = gpu["max_warps_per_sm"] // wpb
    bl = gpu["max_blocks_per_sm"]

    resource_blocks = {"blocks": bl, "regs": br, "smem": bs, "warps": bw}
    min_val = min(resource_blocks.values())
    bottleneck = sorted(k for k, v in resource_blocks.items() if v == min_val)[0]

    ab = max(min(bs, br, bw, bl), 0)
    occ = (ab * wpb) / gpu["max_warps_per_sm"]
    return round(occ, 6), bottleneck


def main():
    gpus = load_gpu_specs()
    ranges = load_param_ranges()
    gpu_names = sorted(gpus.keys())

    with open("/app/team_analysis.json") as f:
        team = json.load(f)

    # ── Audit each team config ──────────────────────────────
    config_audits = {}
    total_errors = 0

    for name, cfg in team["configs"].items():
        p = cfg["params"]
        actually_valid = is_valid(p)
        validity_error = cfg["claimed_valid"] != actually_valid

        if actually_valid:
            s = compute_smem(p)
            r = compute_regs(p)
            correct_occ = {}
            correct_bneck = {}
            for gn, gs in gpus.items():
                o, b = compute_occupancy_and_bottleneck(p["NUM_THREADS"], s, r, gs)
                correct_occ[gn] = o
                correct_bneck[gn] = b

            occ_errors = sorted([
                gn for gn in gpu_names
                if abs(cfg["claimed_occupancy"][gn] - correct_occ[gn]) > 1e-4
            ])
            bneck_errors = sorted([
                gn for gn in gpu_names
                if cfg["claimed_bottleneck"][gn] != correct_bneck[gn]
            ])
        else:
            correct_occ = None
            correct_bneck = None
            occ_errors = []
            bneck_errors = []

        err_count = (1 if validity_error else 0) + len(occ_errors) + len(bneck_errors)
        total_errors += err_count

        config_audits[name] = {
            "actually_valid": actually_valid,
            "validity_error": validity_error,
            "correct_occupancy": correct_occ,
            "correct_bottleneck": correct_bneck,
            "occupancy_errors": occ_errors,
            "bottleneck_errors": bneck_errors
        }

    print(f"Config audits complete. Total errors found: {total_errors}")

    # ── Enumerate full parameter space ──────────────────────
    param_names = ["BM", "BN", "BK", "WM", "WN", "WNITER", "TM", "TN", "NUM_THREADS"]
    param_values = [ranges[n] for n in param_names]

    valid_configs = []
    for combo in itertools.product(*param_values):
        params = dict(zip(param_names, combo))
        if not is_valid(params):
            continue
        s = compute_smem(params)
        r = compute_regs(params)
        occ = {}
        bneck = {}
        for gn, gs in gpus.items():
            o, b = compute_occupancy_and_bottleneck(params["NUM_THREADS"], s, r, gs)
            occ[gn] = o
            bneck[gn] = b
        valid_configs.append({
            "params": params, "smem": s, "regs": r,
            "occ": occ, "bottleneck": bneck
        })

    total_valid = len(valid_configs)
    print(f"Total valid configs: {total_valid}")

    # ── Best config per GPU ─────────────────────────────────
    best_pick_audit = {}
    for gn in gpu_names:
        sorted_cfgs = sorted(
            valid_configs,
            key=lambda c: (-c["occ"][gn], c["smem"], c["params"]["NUM_THREADS"],
                           c["params"]["BM"], c["params"]["BN"])
        )
        best = sorted_cfgs[0]

        pick_name = team["team_best_picks"][gn]
        pick_audit = config_audits[pick_name]
        pick_valid = pick_audit["actually_valid"]
        if pick_valid:
            pick_occ = pick_audit["correct_occupancy"][gn]
            pick_optimal = abs(pick_occ - best["occ"][gn]) < 1e-6
        else:
            pick_optimal = False

        best_pick_audit[gn] = {
            "team_pick_valid": pick_valid,
            "team_pick_optimal": pick_optimal,
            "actual_best_occupancy": best["occ"][gn],
            "actual_best_config": best["params"]
        }
        print(f"  Best {gn}: occ={best['occ'][gn]:.6f}, team pick optimal: {pick_optimal}")

    # ── Pareto frontier ─────────────────────────────────────
    pareto_count = 0
    for i, v in enumerate(valid_configs):
        dominated = False
        for j, u in enumerate(valid_configs):
            if i == j:
                continue
            if (all(u["occ"][g] >= v["occ"][g] for g in gpu_names) and
                    any(u["occ"][g] > v["occ"][g] for g in gpu_names)):
                dominated = True
                break
        if not dominated:
            pareto_count += 1
    print(f"Pareto-optimal configs: {pareto_count}")

    # ── Portability scores ──────────────────────────────────
    portability_scores = {}
    for name, audit in config_audits.items():
        if not audit["actually_valid"]:
            portability_scores[name] = None
        else:
            occ_vals = list(audit["correct_occupancy"].values())
            portability_scores[name] = round(min(occ_vals) / max(occ_vals), 6)

    # ── Write output ────────────────────────────────────────
    output = {
        "config_audits": config_audits,
        "best_pick_audit": best_pick_audit,
        "total_valid_configs": total_valid,
        "pareto_optimal_count": pareto_count,
        "portability_scores": portability_scores,
        "total_errors_found": total_errors
    }

    with open("/app/audit_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to /app/audit_results.json")


if __name__ == "__main__":
    main()
