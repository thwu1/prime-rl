Complete the implementation of the tiled attention engine at `/app/engine.py`. The file provides the `AttentionMask` abstract base class and signatures for all required classes and functions.

## Masks

Implement five mask classes inheriting from `AttentionMask`: `FullMask`, `CausalMask`, `SlidingWindowMask(left_context, right_context)`, `ChunkwiseMask(chunk_size, back_chunks)`, and `PrefixLMMask(prefix_size)`. Each must implement:

- `mask(q_indices, k_indices, seq_len)` — boolean attention pattern. Does NOT include sequence-length bounds; those are applied externally.
- `k_range_for_q(q, seq_len)` — tight inclusive `(k_min, k_max)` bounds on attended keys, clipped to `[0, seq_len-1]`.
- `q_range_for_k(k, seq_len)` — tight inclusive `(q_min, q_max)` bounds on attending queries, clipped to `[0, seq_len-1]`.
- `k_full_range_for_q_tile(qb, tile_q, seq_len)` — exclusive `(k_start, k_end)` range of keys fully unmasked for ALL queries in `[qb, qb+tile_q)`. This is the intersection of per-query k_ranges converted to a half-open interval.

"Tight" means the analytical bounds exactly match the first and last True entries in the actual mask row/column — no unnecessary slack.

Mask semantics: CausalMask allows `q >= k`. SlidingWindowMask allows `q - left_context <= k <= q + right_context`. ChunkwiseMask groups positions into chunks of `chunk_size`; a query in chunk `c` attends to chunks `c, c-1, ..., c-back_chunks`. PrefixLMMask allows bidirectional attention to keys with index `< prefix_size`, and causal attention (`q >= k`) elsewhere.

## Attention Functions

- `naive_attention(Q, K, V, mask, lens=None)` — reference: materialize full T×T score matrix, apply numerically stable softmax with masking, multiply by V.
- `tiled_attention(Q, K, V, mask, tile_q, tile_k, lens=None)` — compute attention using the online softmax algorithm over tiles (the core of Flash Attention). Must not allocate the full T×T matrix. Must use analytical range functions to determine which key tiles to visit, skipping tiles that fall entirely outside any query's attending range. Must correctly handle all-masked tiles (avoiding NaN propagation) and numerical edge cases.
- `verify_mask(mask, max_pos)` — validate consistency between `mask()` and analytical range functions. Check that `k_range_for_q` and `q_range_for_k` are tight for every position, and that `k_full_range_for_q_tile` ranges are fully unmasked. Raise `AssertionError` on inconsistency.

## Data Format

All inputs/outputs are numpy float64 arrays. Q, K, V have shape `(B, H, T, D)`. Optional `lens` is a `(B,)` int array; positions `>= lens[b]` in batch element `b` are masked out with zero output. The attention formula is `softmax(Q @ K^T / sqrt(D)) @ V`.