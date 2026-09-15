#!/usr/bin/env python3
"""KV cache block allocator -- fixed with prefix caching and LRU eviction.

Fixes applied:
  1. Fork creates a list copy, not a reference alias
  2. CoW sets new block fill to old_fill + 1 (counts the appended token)
  3. release_block reclaims blocks when ref_count reaches zero
     (cached blocks retained; non-cached returned to free pool)
  4. update_peak called after every allocation in decode
  5. prefill_cached implemented with hash-based block deduplication
  6. LRU eviction when free pool is exhausted
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
    free_pool = list(range(num_gpu_blocks))
    ref_count = {}
    fill_level = {}

    # Per-sequence logical state
    block_tables = {}

    # Prefix caching state
    hash_to_block = {}   # content_hash -> block_id
    block_to_hash = {}   # block_id -> content_hash
    last_accessed = {}   # block_id -> monotonic counter (for LRU)
    access_counter = 0

    # Metrics
    total_alloc = 0
    total_cow = 0
    current_used = 0
    peak_used = 0
    wasted_at_peak = 0
    prefix_cache_hits = 0
    prefix_cache_misses = 0
    evictions_performed = 0

    def evict_lru():
        nonlocal current_used, evictions_performed
        best_bid = None
        best_time = float('inf')
        for bid in list(block_to_hash.keys()):
            if ref_count.get(bid, 0) == 0:
                t = last_accessed.get(bid, float('inf'))
                if t < best_time:
                    best_time = t
                    best_bid = bid
        if best_bid is None:
            raise RuntimeError("Out of memory: no evictable cached blocks")
        h = block_to_hash[best_bid]
        del hash_to_block[h]
        del block_to_hash[best_bid]
        del last_accessed[best_bid]
        del ref_count[best_bid]
        del fill_level[best_bid]
        free_pool.append(best_bid)
        current_used -= 1
        evictions_performed += 1

    def allocate_block():
        nonlocal total_alloc, current_used
        if not free_pool:
            evict_lru()
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
            if bid in block_to_hash:
                pass  # Cached block -- keep for future reuse
            else:
                del ref_count[bid]
                del fill_level[bid]
                free_pool.append(bid)
                current_used -= 1

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

        elif kind == "prefill_cached":
            seq_id = op["seq_id"]
            prompt_len = op["prompt_length"]
            block_hashes = op["block_hashes"]
            n_blocks = math.ceil(prompt_len / block_size)
            assert len(block_hashes) == n_blocks
            table = []
            for i in range(n_blocks):
                h = block_hashes[i]
                if h in hash_to_block:
                    bid = hash_to_block[h]
                    ref_count[bid] += 1
                    last_accessed[bid] = access_counter
                    access_counter += 1
                    prefix_cache_hits += 1
                else:
                    bid = allocate_block()
                    fill_level[bid] = min(
                        block_size, prompt_len - i * block_size
                    )
                    hash_to_block[h] = bid
                    block_to_hash[bid] = h
                    last_accessed[bid] = access_counter
                    access_counter += 1
                    prefix_cache_misses += 1
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
                    bid = allocate_block()
                    fill_level[bid] = 1
                    table.append(bid)
                elif ref_count[last] > 1:
                    old_fill = fill_level[last]
                    ref_count[last] -= 1
                    bid = allocate_block()
                    fill_level[bid] = old_fill + 1
                    table[-1] = bid
                    total_cow += 1
                else:
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
