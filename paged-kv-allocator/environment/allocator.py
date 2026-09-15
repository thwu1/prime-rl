#!/usr/bin/env python3
"""KV cache block allocator for PagedAttention-based LLM serving.

Manages physical memory blocks for storing key-value cache during
autoregressive inference. Supports prefill, fork, decode, and free
operations with reference-counted block sharing.
"""

import json
import math
import sqlite3


def load_operations(db_path):
    """Load workload operations from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ops = []
    for row in conn.execute("SELECT * FROM operations ORDER BY step_id"):
        op = {
            "op": row["op_type"],
            "seq_id": row["seq_id"],
        }
        if row["prompt_length"] is not None:
            op["prompt_length"] = row["prompt_length"]
        if row["num_tokens"] is not None:
            op["num_tokens"] = row["num_tokens"]
        if row["source_seq_id"] is not None:
            op["source_seq_id"] = row["source_seq_id"]
        if row["new_seq_id"] is not None:
            op["new_seq_id"] = row["new_seq_id"]
        if row["op_type"] == "prefill_cached":
            hashes = conn.execute(
                "SELECT block_hash FROM block_hashes "
                "WHERE step_id = ? ORDER BY position",
                (row["step_id"],)
            ).fetchall()
            op["block_hashes"] = [h[0] for h in hashes]
        ops.append(op)
    conn.close()
    return ops


def run_simulation(config_path, db_path, results_path):
    with open(config_path) as f:
        cfg = json.load(f)
    ops = load_operations(db_path)

    block_size = cfg["block_size"]
    num_gpu_blocks = cfg["num_gpu_blocks"]
    per_token_kv = (
        2 * cfg["num_kv_heads"] * cfg["head_dim"]
        * cfg["num_layers"] * cfg["dtype_bytes"]
    )

    # Physical block state
    free_pool = list(range(num_gpu_blocks))  # stack: pop from end
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
    prefix_cache_hits = 0
    prefix_cache_misses = 0
    evictions_performed = 0

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

    def update_peak():
        nonlocal peak_used, wasted_at_peak
        if current_used > peak_used:
            peak_used = current_used
            wasted_at_peak = sum(
                block_size - fl for fl in fill_level.values()
            )

    for op in ops:
        kind = op["op"]

        if kind == "prefill":
            seq_id = op["seq_id"]
            prompt_len = op["prompt_length"]
            n_blocks = math.ceil(prompt_len / block_size)
            table = []
            for i in range(n_blocks):
                bid = allocate_block()
                fill_level[bid] = min(
                    block_size, prompt_len - i * block_size
                )
                table.append(bid)
            block_tables[seq_id] = table
            update_peak()

        elif kind == "fork":
            block_tables[op["new_seq_id"]] = block_tables[op["source_seq_id"]]
            for bid in block_tables[op["new_seq_id"]]:
                ref_count[bid] += 1

        elif kind == "decode":
            seq_id = op["seq_id"]
            n_tokens = op["num_tokens"]
            table = block_tables[seq_id]
            for _ in range(n_tokens):
                last = table[-1]
                if fill_level[last] >= block_size:
                    # Last block full -- allocate fresh block
                    bid = allocate_block()
                    fill_level[bid] = 1
                    table.append(bid)
                elif ref_count[last] > 1:
                    # Shared partial block -- copy-on-write
                    old_fill = fill_level[last]
                    ref_count[last] -= 1
                    bid = allocate_block()
                    fill_level[bid] = old_fill
                    table[-1] = bid
                    total_cow += 1
                else:
                    # Private partial block -- append in place
                    fill_level[last] += 1

        elif kind == "prefill_cached":
            raise NotImplementedError(
                "prefill_cached operation not yet supported"
            )

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
        "prefix_cache_hits": prefix_cache_hits,
        "prefix_cache_misses": prefix_cache_misses,
        "evictions_performed": evictions_performed,
    }
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_simulation(
        "/app/config.json", "/app/workload.db", "/app/results.json"
    )
