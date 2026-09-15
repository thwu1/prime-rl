#!/usr/bin/env python3
"""
Solver for GPU Fleet Profiling Forensics.

Reads telemetry from SQLite (normalized schema), hardware from nvidia-smi XML,
architecture candidates from YAML. Reconstructs SM parameters, detects corrupted
rows, identifies architectures, and computes optimal launch configs.
"""
import json
import sqlite3
import math
import os
import xml.etree.ElementTree as ET
import yaml


# ══════════════════════════════════════════════════════════════════
# Known NVIDIA architecture full specifications (domain knowledge)
# ══════════════════════════════════════════════════════════════════

NVIDIA_FULL_SPECS = {
    "sm_70": {
        "max_warps_per_sm": 64, "max_blocks_per_sm": 32,
        "total_shared_mem_per_sm": 98304,
        "shared_mem_alloc_granularity": 256, "register_alloc_granularity": 256,
    },
    "sm_75": {
        "max_warps_per_sm": 32, "max_blocks_per_sm": 16,
        "total_shared_mem_per_sm": 65536,
        "shared_mem_alloc_granularity": 256, "register_alloc_granularity": 256,
    },
    "sm_80": {
        "max_warps_per_sm": 64, "max_blocks_per_sm": 32,
        "total_shared_mem_per_sm": 167936,
        "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256,
    },
    "sm_86": {
        "max_warps_per_sm": 48, "max_blocks_per_sm": 16,
        "total_shared_mem_per_sm": 102400,
        "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256,
    },
    "sm_89": {
        "max_warps_per_sm": 48, "max_blocks_per_sm": 24,
        "total_shared_mem_per_sm": 102400,
        "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256,
    },
    "sm_90": {
        "max_warps_per_sm": 64, "max_blocks_per_sm": 32,
        "total_shared_mem_per_sm": 233472,
        "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256,
    },
}


# ══════════════════════════════════════════════════════════════════
# Data Reading: SQLite, XML, YAML
# ══════════════════════════════════════════════════════════════════

def read_traces_from_db(db_path):
    """Read profiling traces from normalized SQLite database with JOINs."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT lr.record_id, gs.gpu_id, kd.kernel_name,
               lr.block_size, lr.registers_per_thread,
               lr.shared_mem_bytes, lr.measured_active_blocks,
               lr.measured_occupancy
        FROM launch_records lr
        JOIN gpu_sessions gs ON lr.session_id = gs.session_id
        JOIN kernel_defs kd ON lr.kernel_id = kd.kernel_id
        ORDER BY lr.record_id
    """)
    rows = []
    for r in c.fetchall():
        rows.append({
            "row_id": r["record_id"],
            "gpu_id": r["gpu_id"],
            "kernel": r["kernel_name"],
            "block_size": r["block_size"],
            "registers_per_thread": r["registers_per_thread"],
            "shared_mem_per_block": r["shared_mem_bytes"],
            "active_blocks": r["measured_active_blocks"],
            "occupancy": r["measured_occupancy"],
        })
    conn.close()
    return rows


def read_hw_from_xml(xml_path):
    """Parse nvidia-smi XML discovery output for known hardware attributes."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    hw = {}
    for gpu_elem in root.findall("gpu"):
        label = gpu_elem.find("internal_label").text
        sm = gpu_elem.find("sm_resource_limits")
        entry = {}
        for child in sm:
            val = child.text.strip() if child.text else ""
            if val and val != "[DISCOVERY FAILED]":
                entry[child.tag] = int(val)
        hw[label] = entry
    return hw


def read_architectures_from_yaml(yaml_path):
    """Parse YAML architecture reference to get candidate constraints."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    archs = {}
    for arch in data["candidate_architectures"]:
        archs[arch["id"]] = {
            "max_warps_per_sm": arch.get("max_warps_per_sm"),
            "max_blocks_per_sm": arch.get("max_blocks_per_sm"),
        }
    common = data.get("common_sm_constants", {})
    return archs, common


# ══════════════════════════════════════════════════════════════════
# SM Occupancy Model
# ══════════════════════════════════════════════════════════════════

def predict_active_blocks(max_warps, max_blocks, total_regs, reg_gran,
                          total_smem, smem_gran, warp_size,
                          block_size, regs_per_thread, smem_per_block):
    wpb = math.ceil(block_size / warp_size)
    limit_warps = max_warps // wpb
    limit_blocks = max_blocks

    if regs_per_thread > 0:
        rpw = regs_per_thread * warp_size
        rpw_r = math.ceil(rpw / reg_gran) * reg_gran
        rpb = rpw_r * wpb
        limit_regs = total_regs // rpb if rpb > 0 else max_blocks
    else:
        limit_regs = max_blocks

    if smem_per_block > 0:
        smem_r = math.ceil(smem_per_block / smem_gran) * smem_gran
        if smem_r > total_smem:
            return 0
        limit_smem = total_smem // smem_r
    else:
        limit_smem = max_blocks

    return max(min(limit_warps, limit_blocks, limit_regs, limit_smem), 0)


# ══════════════════════════════════════════════════════════════════
# Phase 1: Determine max_warps and max_blocks from data
# ══════════════════════════════════════════════════════════════════

def estimate_max_warps(gpu_rows, warp_size):
    max_observed = 0
    for row in gpu_rows:
        if row["registers_per_thread"] <= 16 and row["shared_mem_per_block"] == 0:
            wpb = math.ceil(row["block_size"] / warp_size)
            max_observed = max(max_observed, row["active_blocks"] * wpb)
    return max_observed


def estimate_max_blocks(gpu_rows, warp_size):
    for row in gpu_rows:
        if (row["block_size"] == 32 and row["registers_per_thread"] <= 16
                and row["shared_mem_per_block"] == 0):
            return row["active_blocks"]
    return max(r["active_blocks"] for r in gpu_rows)


# ══════════════════════════════════════════════════════════════════
# Phase 2: Architecture identification via scoring
# ══════════════════════════════════════════════════════════════════

def score_arch(arch_params, gpu_rows, total_regs, warp_size):
    p = arch_params
    score = 0
    for row in gpu_rows:
        ab = predict_active_blocks(
            p["max_warps_per_sm"], p["max_blocks_per_sm"],
            total_regs, p["register_alloc_granularity"],
            p["total_shared_mem_per_sm"], p["shared_mem_alloc_granularity"],
            warp_size,
            row["block_size"], row["registers_per_thread"],
            row["shared_mem_per_block"])
        if ab == row["active_blocks"]:
            score += 1
    return score


def identify_architecture(gpu_rows, total_regs, warp_size, yaml_candidates):
    max_warps = estimate_max_warps(gpu_rows, warp_size)
    max_blocks = estimate_max_blocks(gpu_rows, warp_size)

    # Use YAML candidate constraints to narrow search
    possible_arch_ids = set()
    for arch_id, constraints in yaml_candidates.items():
        if (constraints["max_warps_per_sm"] == max_warps and
                constraints["max_blocks_per_sm"] == max_blocks):
            possible_arch_ids.add(arch_id)

    # Score each candidate using full specs from domain knowledge
    candidates = {aid: NVIDIA_FULL_SPECS[aid]
                  for aid in possible_arch_ids if aid in NVIDIA_FULL_SPECS}

    if not candidates:
        return None, None

    best_arch = None
    best_params = None
    best_score = -1
    for arch_id, params in candidates.items():
        s = score_arch(params, gpu_rows, total_regs, warp_size)
        if s > best_score:
            best_score = s
            best_arch = arch_id
            best_params = params

    return best_arch, best_params


# ══════════════════════════════════════════════════════════════════
# Phase 3: Corruption Detection
# ══════════════════════════════════════════════════════════════════

def detect_corrupted_rows(traces, hw_params, total_regs, warp_size):
    corrupted = []
    for row in traces:
        p = hw_params[row["gpu_id"]]
        predicted = predict_active_blocks(
            p["max_warps_per_sm"], p["max_blocks_per_sm"],
            total_regs, p["register_alloc_granularity"],
            p["total_shared_mem_per_sm"], p["shared_mem_alloc_granularity"],
            warp_size,
            row["block_size"], row["registers_per_thread"],
            row["shared_mem_per_block"])
        if predicted != row["active_blocks"]:
            corrupted.append(row["row_id"])
    return sorted(corrupted)


# ══════════════════════════════════════════════════════════════════
# Phase 4: Optimal Launch Configuration Search
# ══════════════════════════════════════════════════════════════════

def eval_smem(spec, block_size, warp_size):
    val = spec["shared_mem_per_block"]
    if isinstance(val, str):
        return eval(val, {"__builtins__": {}},
                    {"block_size": block_size, "warp_size": warp_size})
    return val


def find_optimal_config(kernel_spec, gpu_params, total_regs, warp_size, max_tpb):
    p = gpu_params
    regs = kernel_spec["registers_per_thread"]
    best_occ = -1.0
    best_bs = 0

    for mult in range(1, max_tpb // warp_size + 1):
        bs = mult * warp_size
        smem = eval_smem(kernel_spec, bs, warp_size)
        ab = predict_active_blocks(
            p["max_warps_per_sm"], p["max_blocks_per_sm"],
            total_regs, p["register_alloc_granularity"],
            p["total_shared_mem_per_sm"], p["shared_mem_alloc_granularity"],
            warp_size, bs, regs, smem)
        if ab == 0:
            continue
        wpb = math.ceil(bs / warp_size)
        occ = ab * wpb / p["max_warps_per_sm"]
        if occ > best_occ + 1e-9 or (abs(occ - best_occ) < 1e-9 and bs > best_bs):
            best_occ = occ
            best_bs = bs

    return best_bs, round(best_occ, 6)


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    # Read data from heterogeneous sources
    traces = read_traces_from_db("/app/data/profiling.db")
    hw_xml = read_hw_from_xml("/app/data/hw_discovery.xml")
    yaml_candidates, common_consts = read_architectures_from_yaml(
        "/app/data/architectures.yaml")

    with open("/app/data/target_kernels.json") as f:
        target_kernels = json.load(f)

    # Extract constants from XML / YAML
    warp_size = common_consts.get("warp_size", 32)
    max_tpb = 1024
    total_regs = 65536
    for gid, attrs in hw_xml.items():
        if "max_registers_per_sm" in attrs:
            total_regs = attrs["max_registers_per_sm"]
            break

    gpu_ids = sorted(hw_xml.keys())

    # Group rows by GPU
    gpu_rows = {gid: [] for gid in gpu_ids}
    for row in traces:
        gpu_rows[row["gpu_id"]].append(row)

    # Phase 1+2: Identify architecture and get full parameters
    hw_params = {}
    arch_map = {}
    for gid in gpu_ids:
        arch_id, params = identify_architecture(
            gpu_rows[gid], total_regs, warp_size, yaml_candidates)
        arch_map[gid] = arch_id
        hw_params[gid] = dict(params)

    # Phase 3: Detect corrupted rows
    corrupted = detect_corrupted_rows(traces, hw_params, total_regs, warp_size)

    # Phase 4: Optimal configs for target kernels
    optimal = {}
    for kname, kspec in target_kernels.items():
        optimal[kname] = {}
        for gid in gpu_ids:
            bs, occ = find_optimal_config(
                kspec, hw_params[gid], total_regs, warp_size, max_tpb)
            optimal[kname][gid] = {
                "optimal_block_size": bs,
                "predicted_occupancy": occ,
            }

    # Write results
    results = {
        "hardware_parameters": hw_params,
        "architecture_mapping": arch_map,
        "corrupted_row_ids": corrupted,
        "optimal_configs": optimal,
    }

    os.makedirs("/app", exist_ok=True)
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to /app/results.json")
    print(f"Detected {len(corrupted)} corrupted rows: {corrupted}")
    for gid in gpu_ids:
        print(f"  {gid} -> {arch_map[gid]}: {hw_params[gid]}")


if __name__ == "__main__":
    main()
