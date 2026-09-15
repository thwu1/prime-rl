# PagedAttention KV Cache Block Manager — Specification

## Overview

This document specifies a KV cache block manager inspired by the PagedAttention
algorithm for high-throughput LLM serving.  The implementation uses a **hybrid
C/Python architecture**:

1. A **C shared library** (`libblockpool.so`, built from `blockpool.c` /
   `blockpool.h`) handles the performance-critical block pool: allocation,
   deallocation, reference counting, and per-block token storage.
2. A **Python layer** (`block_manager.py`) wraps the C library via `ctypes`
   and adds higher-level features: block tables, prefix caching, GPU/CPU
   swapping, and preemption scheduling.

## C Library — `libblockpool`

The C library manages an opaque `BlockPool *` handle.  All functions receive
this handle as their first argument.  **Important**: because `blockpool_create`
returns a heap-allocated pointer, the ctypes `restype` for this function must
be `ctypes.c_void_p` (not a 32-bit integer type) to avoid pointer truncation
on 64-bit platforms.

### Pool lifecycle

| Function | Signature | Notes |
|----------|-----------|-------|
| `blockpool_create`  | `(int num_blocks, int block_size) → BlockPool*` | Allocates pool, blocks, and per-block token arrays |
| `blockpool_destroy` | `(BlockPool*) → void` | Must free **all** memory: per-block token arrays, block array, free stack, and pool struct |

### Allocation

| Function | Signature | Notes |
|----------|-----------|-------|
| `blockpool_allocate` | `(BlockPool*) → int` | Pops from free stack, sets ref_count=1, clears tokens. Returns -1 if empty |
| `blockpool_free`     | `(BlockPool*, int block_id) → void` | Decrements ref_count; reclaims (clears tokens, pushes to free stack) when it reaches 0 |

### Reference counting

| Function | Signature |
|----------|-----------|
| `blockpool_incref`       | `(BlockPool*, int block_id) → void` |
| `blockpool_get_refcount` | `(BlockPool*, int block_id) → int`  |

### Token operations

Each block stores up to `block_size` integer token IDs and a count of how
many tokens are currently stored.

| Function | Signature |
|----------|-----------|
| `blockpool_set_token`      | `(BlockPool*, int block_id, int index, int token) → void` |
| `blockpool_get_token`      | `(BlockPool*, int block_id, int index) → int` |
| `blockpool_get_num_tokens` | `(BlockPool*, int block_id) → int` |
| `blockpool_set_num_tokens` | `(BlockPool*, int block_id, int count) → void` |
| `blockpool_clear_tokens`   | `(BlockPool*, int block_id) → void` |
| `blockpool_copy_tokens`    | `(BlockPool*, int dst_id, int src_id) → void` |
| `blockpool_append_token`   | `(BlockPool*, int block_id, int token) → void` |

## Python Layer — `CBlockView`

`CBlockView` provides attribute-compatible access to a C-backed block so that
higher-level Python code can read/write `block.token_ids` and `block.ref_count`
transparently.

- **`ref_count`** (property): getter reads from C; setter is a no-op because
  the C library owns ref-count state.  To decrement a ref count, call
  `BlockAllocator.free(block_id)` (which delegates to `blockpool_free`).
- **`token_ids`** (property): getter/setter read from / write to C.
- **`content_hash`**: stored in Python only (not in C).

## Python Layer — `BlockAllocator`

Each device (GPU, CPU) has its own `BlockAllocator` wrapping an independent
`BlockPool *`.

- **`allocate()`** → int: delegates to `blockpool_allocate`.
- **`free(block_id)`**: delegates to `blockpool_free`.  When ref_count reaches
  0, must also **remove any prefix-cache entry** (`hash_to_block`) for the
  block and clear `content_hash`.
- **`increment_ref(block_id)`**: delegates to `blockpool_incref`.
- **`lookup_cache(token_ids)`** → int | None: look up hash in `hash_to_block`.
  Must **validate** that the referenced block has `ref_count > 0` and its
  stored `token_ids` match the query.  Return None if invalid.
- **`cache_full_block(block_id)`**: compute content hash, store in
  `hash_to_block`.
- **`compute_hash(token_ids)`** → str: SHA-256, truncated to 16 hex chars.

## Python Layer — `BlockManager`

Coordinates two `BlockAllocator`s (GPU and CPU).

### State

- `block_tables`: seq_id → list of GPU physical block IDs
- `swapped_block_tables`: seq_id → list of CPU block IDs
- `seq_tokens`: seq_id → list of token IDs
- `seq_to_group`: seq_id → group_id
- `group_seqs`: group_id → set of seq_ids
- `group_arrival`: group_id → monotonically increasing arrival index

### Number of Blocks Needed

```
blocks_needed(0) = 0
blocks_needed(n) = ceil(n / B) = (n + B - 1) // B    for n > 0
```

### Allocate Sequence

`allocate_sequence(seq_id, group_id, token_ids) → bool`

1. Reject if seq_id exists.
2. Compute blocks needed; reject if insufficient GPU free blocks.
3. For each block-sized chunk: on prefix-cache hit, increment ref and reuse;
   otherwise allocate fresh and optionally cache.
4. Record block table, tokens, and group membership.

### Append Token

`append_token(seq_id, token_id) → bool`

1. If current tokens fill all blocks exactly, allocate a new block.
2. **Copy-on-write**: if last block's ref_count > 1, allocate a new block,
   copy tokens, and **decrement the old block's ref_count via
   `BlockAllocator.free()`** (do NOT use the `CBlockView.ref_count` setter,
   which is a no-op).
3. Invalidate any stale content hash.
4. Append the token.
5. If prefix caching is enabled and the block is now full, cache it.

### Fork Sequence

`fork_sequence(parent_seq_id, child_seq_id) → bool`

1. Increment ref_count on each parent block; copy the block table.
2. Copy token list and group membership.
3. **Add the child to `group_seqs[group_id]`.**

### Free Sequence

`free_sequence(seq_id) → bool`

Free each block; remove from all data structures; clean up empty groups.

### Swap Out / Swap In

- `swap_out(group_id)`: copy blocks GPU→CPU; free GPU blocks.
- `swap_in(group_id)`: copy blocks CPU→GPU; **free CPU blocks**.

### Prefix Cache Hit Count

`get_num_prefix_cache_hits(token_ids) → int`

If caching disabled, return 0.  Otherwise count consecutive full-block cache
hits from the beginning of the token sequence.

### Select Victim Group

`select_victim_group() → int | None`

LIFO: return group_id with highest arrival index among groups that have at
least one active (non-swapped) sequence.

### Utilization Statistics

`get_utilization_stats() → dict`

Return: `gpu_total_blocks`, `gpu_used_blocks`, `gpu_free_blocks`,
`gpu_utilization`, `cpu_total_blocks`, `cpu_used_blocks`, `cpu_free_blocks`,
`cpu_utilization`, `num_active_sequences`, `num_swapped_sequences`,
`num_groups`, `prefix_cache_size`, `total_shared_blocks`.
