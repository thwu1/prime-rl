#!/usr/bin/env python3
"""CUDA Kernel Performance Analyzer — Reference Solution.

Reads GPU architecture specs and kernel configurations, computes
occupancy, memory coalescing, bank conflicts, and optimal launch config.
"""

import json
import math
import os


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_occupancy(gpu, kernel):
    warp_size = gpu["warp_size"]
    max_warps = gpu["max_warps_per_sm"]
    max_threads = gpu["max_threads_per_sm"]
    max_blocks = gpu["max_blocks_per_sm"]
    regs_per_sm = gpu["registers_per_sm"]
    reg_granularity = gpu["register_alloc_granularity"]
    shmem_per_sm = gpu["shared_memory_per_sm_bytes"]
    shmem_reserved = gpu["shared_memory_reserved_per_block_bytes"]

    block_dim = kernel["block_dim"]
    threads_per_block = block_dim[0] * block_dim[1] * block_dim[2]
    warps_per_block = math.ceil(threads_per_block / warp_size)
    regs_per_thread = kernel["registers_per_thread"]
    total_shmem = kernel.get("static_shared_memory_bytes", 0) + kernel.get(
        "dynamic_shared_memory_bytes", 0
    )

    # --- Register limiter ---
    if regs_per_thread > 0:
        regs_per_warp = (
            math.ceil(regs_per_thread * warp_size / reg_granularity) * reg_granularity
        )
        max_warps_by_regs = regs_per_sm // regs_per_warp
        blocks_by_regs = max_warps_by_regs // warps_per_block
    else:
        blocks_by_regs = max_blocks

    # --- Shared memory limiter ---
    shmem_per_block = total_shmem + shmem_reserved
    if shmem_per_block > 0:
        blocks_by_shmem = min(shmem_per_sm // shmem_per_block, max_blocks)
    else:
        blocks_by_shmem = max_blocks

    # --- Block size limiter ---
    blocks_by_size = min(max_blocks, max_threads // threads_per_block)

    # --- Compute result ---
    active_blocks = min(blocks_by_regs, blocks_by_shmem, blocks_by_size)
    active_warps = min(active_blocks * warps_per_block, max_warps)
    occupancy_pct = active_warps / max_warps * 100.0

    # Determine limiting factor (alphabetically first when tied)
    limits = {
        "block_size": blocks_by_size,
        "registers": blocks_by_regs,
        "shared_memory": blocks_by_shmem,
    }
    min_blocks = min(limits.values())
    limiting_factor = next(k for k in sorted(limits) if limits[k] == min_blocks)

    return {
        "occupancy_pct": occupancy_pct,
        "active_warps_per_sm": active_warps,
        "active_blocks_per_sm": active_blocks,
        "limiting_factor": limiting_factor,
    }


def compute_sectors(gpu, access):
    sector_size = gpu["global_memory_sector_size_bytes"]
    warp_size = gpu["warp_size"]
    elem_size = access["element_size_bytes"]
    stride = access["stride_elements"]

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


def compute_bank_conflicts(gpu, access):
    num_banks = gpu["shared_memory_banks"]
    bank_width = gpu["shared_memory_bank_width_bytes"]
    elem_size = access["element_size_bytes"]
    warp_size = gpu["warp_size"]

    expr = access["index_expression"]
    coeff = expr["coefficient"]
    const = expr["constant"]

    bank_counts = [0] * num_banks
    for tid in range(warp_size):
        elem_index = coeff * tid + const
        # Map element index to bank: byte_offset = elem_index * elem_size
        # bank = (byte_offset // bank_width) % num_banks
        bank = (elem_index * elem_size // bank_width) % num_banks
        bank_counts[bank] += 1

    return {"bank_conflict_degree": max(bank_counts)}


def find_optimal_block_size(gpu, kernel):
    warp_size = gpu["warp_size"]
    max_tpb = gpu["max_threads_per_block"]

    best_occ = -1.0
    best_block_size = warp_size

    for num_warps in range(1, max_tpb // warp_size + 1):
        block_size = num_warps * warp_size
        test_kernel = {
            "block_dim": [block_size, 1, 1],
            "registers_per_thread": kernel["registers_per_thread"],
            "static_shared_memory_bytes": kernel.get("static_shared_memory_bytes", 0),
            "dynamic_shared_memory_bytes": kernel.get(
                "dynamic_shared_memory_bytes", 0
            ),
        }
        result = compute_occupancy(gpu, test_kernel)
        if result["occupancy_pct"] > best_occ:
            best_occ = result["occupancy_pct"]
            best_block_size = block_size

    return {
        "optimal_block_size": best_block_size,
        "maximum_occupancy_pct": best_occ,
    }


def analyze_kernel(gpu, kernel):
    # Handle the optimization kernel specially
    if kernel.get("type") == "optimization":
        return find_optimal_block_size(gpu, kernel)

    result = {}

    # Occupancy analysis
    result["occupancy"] = compute_occupancy(gpu, kernel)

    # Global memory coalescing analysis
    if "global_memory_accesses" in kernel:
        result["global_memory"] = {}
        for access in kernel["global_memory_accesses"]:
            result["global_memory"][access["name"]] = compute_sectors(gpu, access)

    # Shared memory bank conflict analysis
    if "shared_memory_accesses" in kernel:
        result["shared_memory"] = {}
        for access in kernel["shared_memory_accesses"]:
            result["shared_memory"][access["name"]] = compute_bank_conflicts(
                gpu, access
            )

    return result


def main():
    gpu = load_json("/app/gpu_arch.json")

    results = {}
    kernels_dir = "/app/kernels"
    for filename in sorted(os.listdir(kernels_dir)):
        if filename.endswith(".json"):
            kernel = load_json(os.path.join(kernels_dir, filename))
            name = kernel["name"]
            results[name] = analyze_kernel(gpu, kernel)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
