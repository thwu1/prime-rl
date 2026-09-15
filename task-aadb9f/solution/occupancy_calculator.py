#!/usr/bin/env python3

"""
CUDA GPU Occupancy Calculator

Computes occupancy metrics for NVIDIA GPU architectures given kernel
resource specifications. Handles three query types:
  - occupancy: fixed block size occupancy analysis
  - optimal_block_size: search for block size maximizing occupancy
  - concurrent_max_blocks: concurrent kernel co-residency analysis
"""

import json
import math
import os
import glob


def ceil_to_granularity(value, granularity):
    """Round value up to the nearest multiple of granularity."""
    return ((value + granularity - 1) // granularity) * granularity


def load_json_dir(directory):
    """Load all JSON files from a directory, keyed by stem name."""
    result = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            result[stem] = json.load(f)
    return result


def get_shared_memory_bytes(kernel, block_size, warp_size):
    """Get shared memory bytes for a kernel at a given block size."""
    if "shared_memory_bytes_formula" in kernel:
        warps_per_block = block_size // warp_size
        return eval(
            kernel["shared_memory_bytes_formula"],
            {"__builtins__": {}},
            {"warps_per_block": warps_per_block},
        )
    return kernel.get("shared_memory_bytes", 0)


def compute_block_resources(arch, kernel, block_size):
    """Compute per-block resource consumption."""
    ws = arch["warp_size"]
    warps = (block_size + ws - 1) // ws
    rpt = kernel["registers_per_thread"]
    regs_per_warp = ceil_to_granularity(rpt * ws, arch["register_alloc_unit_size"])
    total_regs = warps * regs_per_warp

    smem_raw = get_shared_memory_bytes(kernel, block_size, ws)
    if smem_raw > 0:
        smem_alloc = ceil_to_granularity(smem_raw, arch["shared_memory_alloc_unit_size"])
    else:
        smem_alloc = 0

    return {
        "warps": warps,
        "threads": block_size,
        "regs": total_regs,
        "smem_raw": smem_raw,
        "smem_alloc": smem_alloc,
    }


RESOURCE_PRIORITY = ["registers", "shared_memory", "warps", "threads", "max_blocks"]


def compute_occupancy(arch, kernel, block_size):
    """Compute occupancy for a given architecture, kernel, and block size."""
    ws = arch["warp_size"]

    # Validate block size
    if block_size > arch["max_threads_per_block"] or block_size <= 0:
        return {"error": "invalid_configuration", "reason": "threads_per_block_exceeded"}

    smem_raw = get_shared_memory_bytes(kernel, block_size, ws)
    if smem_raw > arch["max_shared_memory_per_block"]:
        return {"error": "invalid_configuration", "reason": "shared_memory_per_block_exceeded"}

    res = compute_block_resources(arch, kernel, block_size)

    # Compute per-resource limits (max blocks per SM)
    if res["regs"] > 0:
        limit_regs = arch["max_registers_per_multiprocessor"] // res["regs"]
    else:
        limit_regs = arch["max_thread_blocks_per_multiprocessor"]

    if res["smem_alloc"] > 0:
        limit_smem = arch["max_shared_memory_per_multiprocessor"] // res["smem_alloc"]
    else:
        limit_smem = arch["max_thread_blocks_per_multiprocessor"]

    limit_warps = arch["max_warps_per_multiprocessor"] // res["warps"]
    limit_threads = arch["max_threads_per_multiprocessor"] // block_size
    limit_max_blocks = arch["max_thread_blocks_per_multiprocessor"]

    limits = {
        "registers": limit_regs,
        "shared_memory": limit_smem,
        "warps": limit_warps,
        "threads": limit_threads,
        "max_blocks": limit_max_blocks,
    }

    active_blocks = min(limits.values())

    # Find limiting resource by priority
    limiting = None
    for name in RESOURCE_PRIORITY:
        if limits[name] == active_blocks:
            limiting = name
            break

    active_warps = active_blocks * res["warps"]
    occupancy = active_warps / arch["max_warps_per_multiprocessor"]

    return {
        "active_blocks_per_sm": active_blocks,
        "active_warps_per_sm": active_warps,
        "occupancy": occupancy,
        "limiting_resource": limiting,
    }


def find_optimal_block_size(arch, kernel):
    """Find block size that maximizes occupancy (smallest wins ties)."""
    ws = arch["warp_size"]
    best_occ = -1.0
    best_bs = None

    for bs in range(ws, arch["max_threads_per_block"] + 1, ws):
        result = compute_occupancy(arch, kernel, bs)
        if "error" in result:
            continue
        occ = result["occupancy"]
        if occ > best_occ or (occ == best_occ and (best_bs is None or bs < best_bs)):
            best_occ = occ
            best_bs = bs

    return {"optimal_block_size": best_bs, "max_occupancy": best_occ}


def compute_concurrent_max_blocks(arch, k1, bs1, nb1, k2, bs2):
    """Max blocks of k2 that can co-reside with nb1 blocks of k1 on one SM."""
    r1 = compute_block_resources(arch, k1, bs1)
    r2 = compute_block_resources(arch, k2, bs2)

    remaining = {
        "warps": arch["max_warps_per_multiprocessor"] - nb1 * r1["warps"],
        "threads": arch["max_threads_per_multiprocessor"] - nb1 * r1["threads"],
        "regs": arch["max_registers_per_multiprocessor"] - nb1 * r1["regs"],
        "smem": arch["max_shared_memory_per_multiprocessor"] - nb1 * r1["smem_alloc"],
        "blocks": arch["max_thread_blocks_per_multiprocessor"] - nb1,
    }

    per_block_limits = []
    if r2["warps"] > 0:
        per_block_limits.append(remaining["warps"] // r2["warps"])
    if r2["threads"] > 0:
        per_block_limits.append(remaining["threads"] // r2["threads"])
    if r2["regs"] > 0:
        per_block_limits.append(remaining["regs"] // r2["regs"])
    if r2["smem_alloc"] > 0:
        per_block_limits.append(remaining["smem"] // r2["smem_alloc"])
    else:
        per_block_limits.append(remaining["blocks"])
    per_block_limits.append(remaining["blocks"])

    return max(0, min(per_block_limits))


def process_query(query, architectures, kernels):
    """Process a single query and return the result dict."""
    qtype = query["type"]
    result = {"query_id": query["id"]}

    if qtype == "occupancy":
        arch = architectures[query["architecture"]]
        kernel = kernels[query["kernel"]]
        occ = compute_occupancy(arch, kernel, query["block_size"])
        result.update(occ)

    elif qtype == "optimal_block_size":
        arch = architectures[query["architecture"]]
        kernel = kernels[query["kernel"]]
        opt = find_optimal_block_size(arch, kernel)
        result.update(opt)

    elif qtype == "concurrent_max_blocks":
        arch = architectures[query["architecture"]]
        k1 = kernels[query["kernel1"]]
        k2 = kernels[query["kernel2"]]
        mb = compute_concurrent_max_blocks(
            arch, k1, query["block_size1"], query["num_blocks1"], k2, query["block_size2"]
        )
        result["max_blocks_kernel2"] = mb

    return result


def main():
    base_dir = "/app"
    architectures = load_json_dir(os.path.join(base_dir, "architectures"))
    kernels = load_json_dir(os.path.join(base_dir, "kernels"))

    with open(os.path.join(base_dir, "queries.json")) as f:
        queries_data = json.load(f)

    results = []
    for q in queries_data["queries"]:
        r = process_query(q, architectures, kernels)
        results.append(r)

    output = {"results": results}
    with open(os.path.join(base_dir, "results.json"), "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(results)} results to {os.path.join(base_dir, 'results.json')}")


if __name__ == "__main__":
    main()
