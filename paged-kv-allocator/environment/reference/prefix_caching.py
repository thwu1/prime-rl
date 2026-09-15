"""
Reference prefix caching design from vLLM.

Prefix caching enables sharing of KV cache blocks between requests
that have common prompt prefixes. Blocks are identified by a content
hash of the tokens they contain. When two requests produce the same
tokens in a given block position, they can share a single physical
block.

See also:
  - vLLM CacheConfig.enable_prefix_caching
  - vLLM CacheConfig.prefix_caching_hash_algo
  - https://docs.vllm.ai/en/latest/design/prefix_caching.html

Key design principles:

  1. Content addressing: each block's content is identified by a hash
     computed from the tokens it stores. The hash is provided
     externally (by the tokenizer/scheduler) for each block position
     during a cached prefill.

  2. Hash-to-block lookup: a mapping from content hashes to physical
     block IDs enables O(1) lookup of previously computed blocks.

  3. Cache hit: when a cached prefill encounters a block hash that is
     already in the lookup table, the existing physical block is
     reused — its reference count is incremented, and no new physical
     block is allocated.

  4. Cache miss: when no matching hash exists, a fresh physical block
     is allocated from the free pool and registered in the lookup
     table.

  5. Retention at ref-zero: when a cached block's reference count
     drops to zero (all sequences using it have been freed), the
     block is NOT returned to the free pool. It remains registered
     in the hash lookup so future requests with the same prefix can
     reuse it without recomputation.

  6. Non-cached blocks: blocks allocated during decode (token-by-token
     generation) are not entered into the hash lookup. When their
     reference count reaches zero, they ARE returned to the free pool
     normally.

  7. Metrics: track the number of cache hits (block reuses) and cache
     misses (new allocations during cached prefills) to measure
     prefix caching effectiveness.
"""
