A disaggregated KVCache serving system pools token blocks across a cluster of prefill and decode nodes for LLM inference. Blocks are tracked via prefix hash chains for deduplication. The system uses a two-phase write protocol (PutStart/PutEnd) with configurable soft and hard pinning for eviction control. The full system state—node topology, cached blocks, prefix chain metadata, and recent operations—is captured in a SQLite database.

The system is not meeting its performance targets. Analyze the state, diagnose root causes, and produce an optimization plan.

## Files

- `/app/cache_state.db` — SQLite database with current cluster state
- `/app/upcoming_requests.json` — Batch of upcoming inference requests with prefix hash requirements
- `/app/config.json` — System parameters, timeouts, and performance targets

## Deliverable

Write `/app/results.json` containing:

- **`diagnostic`**: `zombie_blocks` (block IDs stuck in `init` past timeout), `expired_soft_pins` (block IDs with soft pins past TTL), `orphaned_chains` (hash IDs whose parent doesn't exist in prefix_chains), `overloaded_nodes` and `underloaded_nodes` (node IDs violating utilization thresholds).
- **`cleanup_actions`**: List of `{action, block_id}` entries for zombies and expired pins.
- **`rebalance_plan`**: List of `{action, block_id, ...}` entries — `"move"` (with `from_node`/`to_node`) or `"evict"` — to address capacity imbalance and redundant replicas.
- **`schedule`**: One entry per request: `{request_id, prefill_node, decode_node, cache_hits, cache_misses}`. Route each request to maximize prefix cache reuse.
- **`metrics`**: `total_requests`, `cache_hit_rate`, `zombie_blocks_cleaned`, `soft_pins_cleared`.

The plan must achieve the performance targets in the config without violating node capacity constraints or evicting hard-pinned blocks.