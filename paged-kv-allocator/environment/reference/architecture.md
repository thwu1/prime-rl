# KV Cache Block Allocator — Architecture Reference


This document describes the design principles for the PagedAttention
KV cache block allocator used in high-throughput LLM inference serving.

## Physical Block Pool

A fixed pool of N physical blocks resides in GPU memory. Each block
stores KV vectors for up to `block_size` tokens across all attention
layers. Blocks are managed via a free list (LIFO stack) and individually
track their reference count and fill level (number of tokens stored).

### Per-token KV cache size

Each token requires storage for both key and value tensors across all
attention layers:

    bytes_per_token = 2 * num_kv_heads * head_dim * num_layers * dtype_bytes

The factor of 2 accounts for the separate key and value projections.

## Reference Counting

Blocks can be shared between multiple sequences (e.g., parallel
sampling, beam search). A block's reference count tracks how many
sequences currently hold a reference to it. When a block's reference
count drops to zero, it is eligible for reclamation — except for
cached blocks (see Prefix Caching below).

**Reclamation rule:** when ref_count reaches zero for a non-cached
block, the block must be returned to the free pool immediately.
For cached blocks (those registered in the hash lookup), the block
is retained even at ref_count=0.

## Fork Semantics

Forking creates a new sequence that shares all physical blocks with
the source sequence. The new sequence receives an **independent copy**
of the source's block table — not an alias. Aliasing the block table
would cause modifications to one sequence's table to corrupt the
other's. Reference counts are incremented for each shared block.

## Copy-on-Write (CoW)

When a decode step appends a token to a sequence whose last block
is shared (ref_count > 1) and partially filled:

1. Detach from the old block by decrementing its ref_count.
2. Allocate a fresh block from the free pool.
3. The new block's fill level equals the old block's fill level
   **plus one** (accounting for the newly appended token).
4. Replace the old block ID in the sequence's block table.

When the last block is **full** and shared, CoW does not apply —
a new empty block is simply allocated and appended to the table.
The shared full block remains untouched.

## Peak Tracking

The allocator must track peak memory usage (maximum number of blocks
simultaneously not on the free pool) and the internal fragmentation
(wasted token slots) at the moment peak usage is first reached.

Peak tracking must occur after **every allocation event**, including
allocations that happen during decode operations (not just during
prefill). Missing peak updates during decode can cause the peak to
be underreported.

Wasted slots at peak = sum of (block_size - fill_level) across all
blocks that are not on the free pool at the moment peak is reached.

## Prefix Caching

Prefix caching enables sharing of KV cache blocks between requests
that have common prompt prefixes.

### Content Addressing

Each block's content is identified by a hash provided externally
(by the tokenizer/scheduler) for each block position during a
cached prefill operation. A mapping from content hashes to physical
block IDs enables O(1) lookup.

### Cache Hit

When a cached prefill encounters a block hash that already exists
in the lookup table, the existing physical block is reused — its
reference count is incremented and no new allocation occurs.

### Cache Miss

When no matching hash exists, a fresh block is allocated from the
free pool, filled, and registered in both the hash-to-block and
block-to-hash mappings.

### Retention at ref=0

When a cached block's reference count drops to zero (all sequences
using it have been freed), the block is **not** returned to the
free pool. It remains registered in the hash lookup so future
requests with the same prefix can reuse it without recomputation.

Non-cached blocks (those allocated during regular prefill or decode)
are returned to the free pool normally when their ref_count hits zero.

### Metrics

Track the number of cache hits (block reuses) and cache misses
(new allocations during cached prefills) separately.

## LRU Eviction

When the free pool is exhausted and a new block must be allocated,
the allocator evicts a cached block to reclaim memory.

### Eviction Candidates

Only cached blocks with ref_count=0 are eligible for eviction.
If no such blocks exist, the allocation fails with an error.

### LRU Ordering

A monotonic access counter tracks recency. The counter is
incremented and assigned to a cached block each time it is:

- Initially allocated during a cache miss
- Reused during a cache hit

The cached block with the **lowest** (oldest) access counter value
among those with ref_count=0 is selected for eviction.

### Eviction Procedure

1. Remove the block from the hash-to-block and block-to-hash maps
2. Remove its access counter entry
3. Clear its ref_count and fill_level tracking
4. Return it to the free pool
5. Decrement current_used
6. Increment the evictions counter

After eviction, the normal allocation path proceeds: pop from the
(now non-empty) free pool.
