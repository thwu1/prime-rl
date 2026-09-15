#!/usr/bin/env python3
"""PagedAttention KV Cache Block Allocator Simulator — Reference Implementation.

Simulates vLLM's PagedAttention block-level KV cache memory management:
  - Physical block pool with free-list allocation
  - Per-block reference counting
  - Per-block fill-level tracking (tokens stored)
  - Copy-on-write when appending to a shared, partially-filled block
  - Peak usage and internal fragmentation tracking
"""

import json
import math


def run_simulation(config_path, workload_path, results_path):
    with open(config_path) as f:
        cfg = json.load(f)
    with open(workload_path) as f:
        ops = json.load(f)

    block_size = cfg["block_size"]
    num_gpu_blocks = cfg["num_gpu_blocks"]
    per_token_kv = (
        2 * cfg["num_kv_heads"] * cfg["head_dim"] * cfg["num_layers"] * cfg["dtype_bytes"]
    )

    # Physical block state
    free_pool = list(range(num_gpu_blocks))  # stack; pop() from end
    ref_count = {}   # block_id -> int
    fill_level = {}  # block_id -> tokens stored (0..block_size)

    # Per-sequence logical state
    block_tables = {}  # seq_id -> [physical_block_id, ...]

    # Metrics
    total_alloc = 0
    total_cow = 0
    current_used = 0
    peak_used = 0
    wasted_at_peak = 0

    def allocate_block():
        nonlocal total_alloc, current_used
        bid = free_pool.pop()
        ref_count[bid] = 1
        fill_level[bid] = 0
        total_alloc += 1
        current_used += 1
        return bid

    def release_block(bid):
        nonlocal current_used
        ref_count[bid] -= 1
        if ref_count[bid] == 0:
            del ref_count[bid]
            del fill_level[bid]
            free_pool.append(bid)
            current_used -= 1

    def update_peak():
        nonlocal peak_used, wasted_at_peak
        if current_used > peak_used:
            peak_used = current_used
            wasted_at_peak = sum(block_size - fl for fl in fill_level.values())

    for op in ops:
        kind = op["op"]

        if kind == "prefill":
            seq_id = op["seq_id"]
            prompt_len = op["prompt_length"]
            n_blocks = math.ceil(prompt_len / block_size)
            table = []
            for i in range(n_blocks):
                bid = allocate_block()
                fill_level[bid] = min(block_size, prompt_len - i * block_size)
                table.append(bid)
            block_tables[seq_id] = table
            update_peak()

        elif kind == "fork":
            src_table = block_tables[op["source_seq_id"]]
            new_table = list(src_table)
            for bid in new_table:
                ref_count[bid] += 1
            block_tables[op["new_seq_id"]] = new_table

        elif kind == "decode":
            seq_id = op["seq_id"]
            n_tokens = op["num_tokens"]
            table = block_tables[seq_id]
            for _ in range(n_tokens):
                last = table[-1]
                if fill_level[last] >= block_size:
                    # Last block is full — allocate a fresh block
                    bid = allocate_block()
                    fill_level[bid] = 1
                    table.append(bid)
                elif ref_count[last] > 1:
                    # Shared partial block — copy-on-write
                    old_fill = fill_level[last]
                    ref_count[last] -= 1  # detach from old block (ref stays >= 1)
                    bid = allocate_block()
                    fill_level[bid] = old_fill + 1
                    table[-1] = bid
                    total_cow += 1
                else:
                    # Private partial block — append in place
                    fill_level[last] += 1
                update_peak()

        elif kind == "free":
            seq_id = op["seq_id"]
            for bid in block_tables[seq_id]:
                release_block(bid)
            del block_tables[seq_id]

    results = {
        "per_token_kv_bytes": per_token_kv,
        "total_blocks_allocated": total_alloc,
        "total_cow_copies": total_cow,
        "peak_blocks_used": peak_used,
        "final_blocks_used": current_used,
        "wasted_slots_at_peak": wasted_at_peak,
    }
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_simulation("/app/config.json", "/app/workload.json", "/app/results.json")
