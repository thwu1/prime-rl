# Architecture Design Notes

## Multi-Latent Attention (MLA)

MLA compresses attention projections through low-rank bottlenecks, reducing KV cache memory while maintaining model quality.

**Query compression**: The query path uses a two-stage factorization through a low-rank bottleneck with intermediate RMSNorm normalization. The expanded multi-head representation is partitioned into non-positional and positional components; rotary encoding is applied to the positional subset only.

**Key-value compression**: A single projection produces a compressed KV bottleneck concatenated with a shared positional key stream. After normalization, the bottleneck is expanded to per-head key and value representations. The positional key stream is a single-head vector shared across all attention heads via broadcast, encoded with RoPE independently.

**Attention**: Scaled dot-product with causal masking and optional DSA sparse masking. Values are gathered, reshaped to the sequence layout, and projected to the output dimension.

**Caching**: Standard key-value cache concatenation along the sequence dimension for autoregressive generation.

## Dynamic Sparse Attention (DSA)

DSA activates when total sequence length exceeds `index_topk`. Otherwise, all causally-valid positions receive attention without restriction.

The indexer uses the compressed query intermediate representation and raw hidden states to produce relevance scores. Both indexer queries and keys use a positional/non-positional split with a dedicated rotary embedding. Per-head scores are computed with ReLU gating, combined via learned weights, and the top-k positions form an additive sparse mask.

The indexer maintains its own key cache separate from the MLA key-value cache. This cache resets on prefill and appends on decode.
