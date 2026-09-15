#!/usr/bin/env python3
"""GPU Kernel Fleet Performance Audit Tool — Reference Solution.

Reads GPU architecture specs from JSON, kernel data from SQLite,
profiling metrics from CSV, and produces a comprehensive audit report.
"""

import csv
import json
import math
import os
import sqlite3


def load_architectures(arch_dir):
    archs = {}
    for fname in sorted(os.listdir(arch_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(arch_dir, fname)) as f:
                arch = json.load(f)
                archs[arch["arch_id"]] = arch
    return archs


def load_profiling_csv(csv_path):
    data = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["kernel_name"]] = {
                "smem_carveout_bytes": int(row["smem_carveout_bytes"]),
                "measured_occupancy_pct": float(row["measured_occupancy_pct"]),
            }
    return data


def compute_occupancy(arch, threads_per_block, regs_per_thread, smem_bytes, carveout):
    warp_size = arch["warp_size"]
    max_warps = arch["max_warps_per_sm"]
    max_threads = arch["max_threads_per_sm"]
    max_blocks = arch["max_blocks_per_sm"]
    regs_per_sm = arch["registers_per_sm"]
    reg_gran = arch["register_alloc_granularity"]
    reserved = arch["shared_memory_reserved_per_block_bytes"]

    warps_per_block = math.ceil(threads_per_block / warp_size)

    # Register limiter
    if regs_per_thread > 0:
        regs_per_warp = (
            math.ceil(regs_per_thread * warp_size / reg_gran) * reg_gran
        )
        max_warps_by_regs = regs_per_sm // regs_per_warp
        blocks_by_regs = max_warps_by_regs // warps_per_block
    else:
        blocks_by_regs = max_blocks

    # Shared memory limiter
    smem_per_block = smem_bytes + reserved
    if smem_per_block > 0 and carveout > 0:
        blocks_by_smem = min(carveout // smem_per_block, max_blocks)
    elif smem_per_block == 0:
        blocks_by_smem = max_blocks
    else:
        blocks_by_smem = 0

    # Block size limiter
    blocks_by_size = min(max_blocks, max_threads // threads_per_block)

    active_blocks = min(blocks_by_regs, blocks_by_smem, blocks_by_size)
    if active_blocks <= 0:
        return None

    active_warps = min(active_blocks * warps_per_block, max_warps)
    occupancy_pct = active_warps / max_warps * 100.0

    # Determine limiting factor (alphabetically first when tied)
    limits = {
        "block_size": blocks_by_size,
        "registers": blocks_by_regs,
        "shared_memory": blocks_by_smem,
    }
    min_val = min(limits.values())
    limiter = next(k for k in sorted(limits) if limits[k] == min_val)

    return {
        "occupancy_pct": occupancy_pct,
        "active_blocks_per_sm": active_blocks,
        "active_warps_per_sm": active_warps,
        "occupancy_limiter": limiter,
    }


def find_optimal_carveout(arch, threads_per_block, regs_per_thread, smem_bytes):
    carveouts = arch["shared_memory_carveouts_bytes"]
    reserved = arch["shared_memory_reserved_per_block_bytes"]
    best_occ = -1.0
    best_result = None
    best_carveout = 0

    for co in sorted(carveouts):
        if co == 0:
            if smem_bytes + reserved > 0:
                continue
        result = compute_occupancy(arch, threads_per_block, regs_per_thread, smem_bytes, co)
        if result is None:
            continue
        if result["occupancy_pct"] > best_occ:
            best_occ = result["occupancy_pct"]
            best_result = result
            best_carveout = co

    return best_carveout, best_result


def compute_sectors(arch, elem_size, stride):
    sector_size = arch["global_memory_sector_size_bytes"]
    warp_size = arch["warp_size"]

    sectors = set()
    for tid in range(warp_size):
        byte_offset = tid * stride * elem_size
        first_sector = byte_offset // sector_size
        last_sector = (byte_offset + elem_size - 1) // sector_size
        for s in range(first_sector, last_sector + 1):
            sectors.add(s)

    num_sectors = len(sectors)
    useful_bytes = warp_size * elem_size
    loaded_bytes = num_sectors * sector_size
    efficiency = useful_bytes / loaded_bytes * 100.0

    return {
        "sectors_per_request": num_sectors,
        "coalescing_efficiency_pct": efficiency,
    }


def compute_bank_conflicts(arch, elem_size, coefficient, constant):
    num_banks = arch["shared_memory_banks"]
    bank_width = arch["shared_memory_bank_width_bytes"]
    warp_size = arch["warp_size"]

    bank_counts = [0] * num_banks
    for tid in range(warp_size):
        elem_index = coefficient * tid + constant
        bank = (elem_index * elem_size // bank_width) % num_banks
        bank_counts[bank] += 1

    return {"bank_conflict_degree": max(bank_counts)}


def main():
    # Load architecture specifications
    archs = load_architectures("/app/architectures")

    # Load profiling CSV data per architecture
    profiling = {}
    for arch_id in archs:
        csv_path = f"/app/profiling/ncu_{arch_id}.csv"
        if os.path.exists(csv_path):
            profiling[arch_id] = load_profiling_csv(csv_path)

    # Query kernel data from SQLite database
    conn = sqlite3.connect("/app/profiling.db")
    conn.row_factory = sqlite3.Row

    kernels = {}
    for row in conn.execute("SELECT * FROM kernels"):
        kernels[row["kernel_name"]] = dict(row)

    global_accesses = {}
    for row in conn.execute("SELECT * FROM global_memory_accesses"):
        global_accesses.setdefault(row["kernel_name"], []).append(dict(row))

    shared_accesses = {}
    for row in conn.execute("SELECT * FROM shared_memory_accesses"):
        shared_accesses.setdefault(row["kernel_name"], []).append(dict(row))

    pipeline_edges = []
    for row in conn.execute("SELECT * FROM pipeline_edges"):
        pipeline_edges.append(dict(row))

    conn.close()

    report = {"kernel_analyses": {}, "fusion_analyses": {}}

    # === Per-kernel per-architecture analysis ===
    for kname in sorted(kernels):
        kernel = kernels[kname]
        report["kernel_analyses"][kname] = {}
        threads = kernel["block_dim_x"] * kernel["block_dim_y"] * kernel["block_dim_z"]
        regs = kernel["registers_per_thread"]
        smem = kernel["static_smem_bytes"] + kernel["dynamic_smem_bytes"]

        for arch_id in sorted(archs):
            arch = archs[arch_id]
            carveout, occ_result = find_optimal_carveout(arch, threads, regs, smem)

            entry = {
                "optimal_smem_carveout_bytes": carveout,
                **occ_result,
            }

            # Global memory coalescing analysis
            if kname in global_accesses:
                entry["global_memory"] = {}
                for acc in global_accesses[kname]:
                    entry["global_memory"][acc["access_name"]] = compute_sectors(
                        arch, acc["element_size_bytes"], acc["stride_elements"]
                    )

            # Shared memory bank conflict analysis
            if kname in shared_accesses:
                entry["shared_memory"] = {}
                for acc in shared_accesses[kname]:
                    entry["shared_memory"][acc["access_name"]] = compute_bank_conflicts(
                        arch,
                        acc["element_size_bytes"],
                        acc["index_coefficient"],
                        acc["index_constant"],
                    )

            # Diagnosis: compare measured vs theoretical
            measured = profiling.get(arch_id, {}).get(kname)
            if measured:
                entry["diagnosis"] = {
                    "measured_occupancy_pct": measured["measured_occupancy_pct"],
                    "theoretical_occupancy_pct": occ_result["occupancy_pct"],
                    "has_discrepancy": measured["measured_occupancy_pct"]
                    < occ_result["occupancy_pct"],
                    "measured_carveout_bytes": measured["smem_carveout_bytes"],
                    "recommended_carveout_bytes": carveout,
                }

            report["kernel_analyses"][kname][arch_id] = entry

    # === Fusion analysis for each pipeline edge ===
    for edge in pipeline_edges:
        src = edge["source_kernel"]
        dst = edge["dest_kernel"]
        k1 = kernels[src]
        k2 = kernels[dst]

        fused_regs = k1["registers_per_thread"] + k2["registers_per_thread"]
        fused_smem = (
            k1["static_smem_bytes"]
            + k1["dynamic_smem_bytes"]
            + k2["static_smem_bytes"]
            + k2["dynamic_smem_bytes"]
        )
        t1 = k1["block_dim_x"] * k1["block_dim_y"] * k1["block_dim_z"]
        t2 = k2["block_dim_x"] * k2["block_dim_y"] * k2["block_dim_z"]
        fused_threads = max(t1, t2)

        fusion_entry = {
            "fused_registers_per_thread": fused_regs,
            "fused_smem_bytes": fused_smem,
            "fused_threads_per_block": fused_threads,
            "architectures": {},
        }

        feasible_any = False
        for arch_id in sorted(archs):
            arch = archs[arch_id]
            co, result = find_optimal_carveout(
                arch, fused_threads, fused_regs, fused_smem
            )
            if result is not None:
                feasible_any = True
                fusion_entry["architectures"][arch_id] = {
                    "optimal_smem_carveout_bytes": co,
                    "occupancy_pct": result["occupancy_pct"],
                    "active_blocks_per_sm": result["active_blocks_per_sm"],
                    "active_warps_per_sm": result["active_warps_per_sm"],
                }
            else:
                fusion_entry["architectures"][arch_id] = {
                    "optimal_smem_carveout_bytes": 0,
                    "occupancy_pct": 0.0,
                    "active_blocks_per_sm": 0,
                    "active_warps_per_sm": 0,
                }

        fusion_entry["feasible"] = feasible_any
        report["fusion_analyses"][f"{src}+{dst}"] = fusion_entry

    # Write the audit report
    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
