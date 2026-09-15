A KV cache block allocator at `/app/allocator.py` manages physical memory blocks for a PagedAttention-based LLM inference server. It reads model configuration from `/app/config.json` and workload operations from a SQLite database at `/app/workload.db`. Results are written to `/app/results.json`.

The workload database schema and operations can be inspected using `sqlite3 /app/workload.db`. The operations table stores the workload sequence; the block_hashes table stores per-block content hashes for cached prefill operations (joined on step_id).

The allocator has multiple correctness defects causing incorrect memory accounting. It also fails to handle `prefill_cached` operations (currently raises `NotImplementedError`) and does not perform eviction when the block pool is exhausted.

An architecture reference document at `/app/reference/architecture.md` is the authoritative specification for every aspect of this allocator's intended behavior — block management, fork semantics, copy-on-write, peak tracking, prefix caching, and eviction. Study it carefully; the allocator must conform to all design invariants described there.

A block pool invariant checker source is at `/app/tools/poolcheck.c` — compile it with `make -C /app/tools` and run it against your results for consistency validation.

**Diagnose and fix all defects, implement all missing functionality, and produce correct results.**

## Output

`/app/results.json` must be a JSON object with these integer fields:

- `per_token_kv_bytes` — KV cache bytes per token for the given model architecture
- `total_blocks_allocated` — cumulative physical block allocations (cache hits do not count)
- `total_cow_copies` — copy-on-write operations performed
- `peak_blocks_used` — maximum physical blocks simultaneously not on the free pool
- `final_blocks_used` — physical blocks not on free pool after all operations
- `wasted_slots_at_peak` — sum of unfilled token slots across all non-free blocks when `peak_blocks_used` is first reached
- `prefix_cache_hits` — blocks reused from content-address cache
- `prefix_cache_misses` — blocks freshly allocated during cached prefills
- `evictions_performed` — cached blocks evicted under memory pressure