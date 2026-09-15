# Multi-Latent Attention with Dynamic Sparse Attention (MLA+DSA) Specification

## Overview

MLA compresses query and key-value representations through low-rank projection
bottlenecks, dramatically reducing KV cache memory. DSA adds a lightweight
indexer that dynamically selects a sparse subset of key positions per query,
reducing attention complexity for long sequences.

## 1. MLA Query Path

Given input hidden states **H** in R^{B x S x d_model}:

1. **Compress**: q_c = H @ W_qa^T, where W_qa in R^{r_q x d_model}
   Result: q_c in R^{B x S x r_q}

2. **Normalize**: q_c = RMSNorm(q_c)

3. **Expand**: Q_raw = q_c @ W_qb^T, where W_qb in R^{(n_h * d_qk) x r_q}
   Result: Q_raw in R^{B x S x (n_h * d_qk)}

4. **Reshape** to per-head: Q in R^{B x S x n_h x d_qk}

5. **Split** along head dim:
   - Q_nope in R^{... x d_nope} (first d_nope dims)
   - Q_rope in R^{... x d_rope} (last d_rope dims)

6. **Apply RoPE** to rope portion only: Q_rope = RotaryEmb(Q_rope, positions)

7. **Recombine**: Q = concat(Q_nope, Q_rope) along last dim

8. **Transpose** to attention layout: Q in R^{B x n_h x S x d_qk}


## 2. MLA Key-Value Path

Given **H** in R^{B x S x d_model}:

1. **Joint projection**: C = H @ W_kva^T, where W_kva in R^{(r_kv + d_rope) x d_model}
   Result: C in R^{B x S x (r_kv + d_rope)}

2. **Split** along last dim:
   - C_kv in R^{B x S x r_kv} (first r_kv dims)
   - K_pe_raw in R^{B x S x d_rope} (last d_rope dims)

3. **Normalize**: C_kv = RMSNorm(C_kv)

4. **Expand**: E = C_kv @ W_kvb^T, where W_kvb in R^{(n_h * (d_nope + d_v)) x r_kv}
   Result: E in R^{B x S x (n_h * (d_nope + d_v))}

5. **Reshape** to per-head: E in R^{B x S x n_h x (d_nope + d_v)}

6. **Split** per head:
   - K_nope in R^{B x S x n_h x d_nope} (first d_nope dims)
   - V in R^{B x S x n_h x d_v} (last d_v dims)

7. **Expand K_pe_raw** across all heads by broadcasting:
   K_pe = K_pe_raw.unsqueeze(2).expand(B, S, n_h, d_rope)
   Apply RoPE: K_pe = RotaryEmb(K_pe, positions)

8. **Recombine keys**: K = concat(K_nope, K_pe) in R^{B x S x n_h x d_qk}

9. **Transpose**: K -> R^{B x n_h x S x d_qk}, V -> R^{B x n_h x S x d_v}


## 3. DSA Indexer

The indexer uses lightweight scoring heads to select the most relevant key
positions for each query.

### 3.1 Indexer Query (from q_c, the normalized compressed query)

1. **Project**: I_q = q_c @ W_iq^T, where W_iq in R^{(n_idx * d_idx) x r_q}
2. **Reshape**: I_q in R^{B x S x n_idx x d_idx}
3. **Split**:
   - I_q_pe in R^{... x d_rope} (first d_rope dims)
   - I_q_nope in R^{... x (d_idx - d_rope)} (remaining dims)
4. **Apply RoPE**: I_q_pe = RotaryEmb(I_q_pe, positions)
5. **Recombine**: I_q = concat(I_q_pe, I_q_nope)

### 3.2 Indexer Key (from hidden states H)

1. **Project + normalize**: I_k = RMSNorm(H @ W_ik^T), where W_ik in R^{d_idx x d_model}
   Result: I_k in R^{B x S x d_idx}
2. **Split**:
   - I_k_pe in R^{B x S x d_rope} (first d_rope dims)
   - I_k_nope in R^{B x S x (d_idx - d_rope)}
3. **Apply RoPE**: Add temporary head dim for compatibility with RotaryEmb:
   I_k_pe = RotaryEmb(I_k_pe.unsqueeze(2), positions).squeeze(2)
4. **Recombine**: I_k = concat(I_k_pe, I_k_nope)

### 3.3 Scoring

1. **Per-head dot products** (in float32):
   scores[b,s,h,t] = sum_d I_q[b,s,h,d] * I_k[b,t,d] / sqrt(d_idx)
   Equivalently: scores = einsum("bshd,btd->bsht", I_q.float(), I_k_full.float()) * d_idx^{-0.5}
2. **ReLU**: scores = max(0, scores)
3. **Head weighting**: w = (H @ W_iw^T) * n_idx^{-0.5}, where W_iw in R^{n_idx x d_model}
   Result: w in R^{B x S x n_idx}, cast to float32 for einsum
4. **Weighted sum**: sigma[b,s,t] = sum_h scores[b,s,h,t] * w[b,s,h]
   Equivalently: sigma = einsum("bsht,bsh->bst", scores, w.float())

### 3.4 Sparse Selection

1. **Causal masking on scores**: if causal mask is provided, add it to sigma
   (squeeze head dim from [B,1,S,T] to [B,S,T] using attention_mask[:, 0, :, :T])
2. **Top-k selection**: indices = topk(sigma, min(k, T)) along last dim
3. **Build sparse mask** M_sparse in R^{B x 1 x S x T}:
   - Initialize to -inf everywhere
   - Set M_sparse[b, 0, s, indices[b,s,:]] = 0
   - (scatter 0.0 at selected positions)


## 4. Attention Computation

1. **Combined mask**: M = M_causal + M_sparse
2. **Attention weights**: A = softmax(Q @ K^T / sqrt(d_qk) + M, dim=-1)
   (softmax in float32 for numerical stability, then cast back)
3. **Weighted values**: O = A @ V in R^{B x n_h x S x d_v}
4. **Reshape**: O -> R^{B x S x (n_h * d_v)}
5. **Output projection**: Y = O @ W_o^T, where W_o in R^{d_model x (n_h * d_v)}


## 5. KV Cache

During autoregressive decoding, the `past_key_values` dictionary stores:

| Key       | Shape                  | Description                  |
|-----------|------------------------|------------------------------|
| "key"     | [B, n_h, T, d_qk]     | Cached attention keys        |
| "value"   | [B, n_h, T, d_v]      | Cached attention values      |
| "idx_key" | [B, T, d_idx]          | Cached DSA indexer keys      |

When `use_cache=True`:
- Concatenate new states with any existing cached states along the time dimension
- Update and return `past_key_values`

When computing attention, use the full (cached + new) K, V, and I_k tensors.


## Notation Reference

| Symbol  | Config Key              | Value |
|---------|------------------------|-------|
| d_model | hidden_size            | 256   |
| n_h     | num_attention_heads    | 4     |
| r_q     | q_lora_rank            | 128   |
| r_kv    | kv_lora_rank           | 64    |
| d_rope  | qk_rope_head_dim       | 16    |
| d_nope  | qk_nope_head_dim       | 48    |
| d_qk    | qk_head_dim            | 64    |
| d_v     | v_head_dim             | 64    |
| n_idx   | index_n_heads          | 2     |
| d_idx   | index_head_dim         | 32    |
| k       | index_topk             | 8     |
