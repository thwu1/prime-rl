#!/usr/bin/env python3
"""
CUDA GPU Occupancy Calculator — reference solution.

Reads GPU architecture specs and kernel resource descriptions, computes
occupancy for each (kernel, GPU) pair at the kernel's default block size,
finds optimal block sizes, and writes results to /app/results.json.
"""

import json
import math


def load_json(path):
    with open(path) as f:
        return json.load(f)


def eval_shared_mem(kernel, block_size, warp_size):
    """Compute shared memory bytes for a kernel at a given block size."""
    if kernel["shared_mem_type"] == "fixed":
        return kernel["shared_mem_bytes"]
    else:
        return eval(
            kernel["shared_mem_formula"],
            {"__builtins__": {}},
            {"block_size": block_size, "warp_size": warp_size},
        )


def compute_occupancy(gpu, block_size, regs_per_thread, smem_bytes):
    """
    Compute occupancy for a given kernel configuration on a given GPU.

    Returns dict with active_blocks_per_sm, active_warps_per_sm,
    occupancy (float 0-1), and limiting_resource.
    """
    W = gpu["warp_size"]
    MAX_W = gpu["max_warps_per_sm"]
    MAX_B = gpu["max_blocks_per_sm"]
    TOTAL_R = gpu["total_registers_per_sm"]
    R_GRAN = gpu["register_alloc_granularity"]
    TOTAL_S = gpu["total_shared_mem_per_sm_bytes"]
    S_GRAN = gpu["shared_mem_alloc_granularity"]

    warps_per_block = math.ceil(block_size / W)

    # Limit by warps (threads per SM)
    blocks_by_warps = MAX_W // warps_per_block

    # Limit by architecture max blocks per SM
    blocks_by_max = MAX_B

    # Limit by registers
    if regs_per_thread > 0:
        regs_per_warp = math.ceil(regs_per_thread * W / R_GRAN) * R_GRAN
        regs_per_block = regs_per_warp * warps_per_block
        blocks_by_regs = TOTAL_R // regs_per_block if regs_per_block > 0 else None
    else:
        blocks_by_regs = None  # Not applicable

    # Limit by shared memory
    if smem_bytes > 0:
        smem_per_block = math.ceil(smem_bytes / S_GRAN) * S_GRAN
        blocks_by_smem = TOTAL_S // smem_per_block
    else:
        blocks_by_smem = None  # Not applicable

    # Compute active blocks as min of all applicable limits
    limits = [blocks_by_warps, blocks_by_max]
    if blocks_by_regs is not None:
        limits.append(blocks_by_regs)
    if blocks_by_smem is not None:
        limits.append(blocks_by_smem)

    active_blocks = min(limits)
    active_blocks = max(active_blocks, 0)

    active_warps = active_blocks * warps_per_block
    occupancy = active_warps / MAX_W if MAX_W > 0 else 0.0

    # Determine limiting resource (priority: registers > shared_memory > warps > blocks)
    limiting = None
    resource_map = [
        ("registers", blocks_by_regs),
        ("shared_memory", blocks_by_smem),
        ("warps", blocks_by_warps),
        ("blocks", blocks_by_max),
    ]
    for name, val in resource_map:
        if val is not None and val == active_blocks:
            limiting = name
            break

    return {
        "active_blocks_per_sm": active_blocks,
        "active_warps_per_sm": active_warps,
        "occupancy": occupancy,
        "limiting_resource": limiting,
    }


def find_optimal_block_size(gpu, kernel):
    """
    Search all valid block sizes (multiples of warp_size) to find
    the one that maximizes occupancy. Ties broken by largest block size.
    """
    W = gpu["warp_size"]
    max_tpb = gpu["max_threads_per_block"]
    regs = kernel["registers_per_thread"]

    best_occ = -1.0
    best_bs = 0

    for bs in range(W, max_tpb + 1, W):
        smem = eval_shared_mem(kernel, bs, W)
        result = compute_occupancy(gpu, bs, regs, smem)
        occ = result["occupancy"]
        if occ > best_occ or (occ == best_occ and bs > best_bs):
            best_occ = occ
            best_bs = bs

    return best_bs, best_occ


def main():
    gpu_specs = load_json("/app/gpu_specs.json")
    kernels = load_json("/app/kernels.json")

    analysis = {}
    optimal = {}

    for kid, kernel in kernels.items():
        analysis[kid] = {}
        optimal[kid] = {}

        for gid, gpu in gpu_specs.items():
            # Analysis at default block size
            bs = kernel["default_block_size"]
            smem = eval_shared_mem(kernel, bs, gpu["warp_size"])
            result = compute_occupancy(gpu, bs, kernel["registers_per_thread"], smem)
            result["block_size"] = bs
            analysis[kid][gid] = result

            # Optimal block size search
            opt_bs, opt_occ = find_optimal_block_size(gpu, kernel)
            optimal[kid][gid] = {
                "optimal_block_size": opt_bs,
                "optimal_occupancy": opt_occ,
            }

    output = {"analysis": analysis, "optimal": optimal}
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
