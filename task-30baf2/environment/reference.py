"""Naive masked attention implementation for correctness reference."""
import numpy as np


def naive_masked_attention(q, k, v, mask_obj, lens=None):
    """
    Compute masked attention using the naive O(T^2) algorithm.

    Args:
        q: (B, H, T, D) query array
        k: (B, H, T, D) key array
        v: (B, H, T, D) value array
        mask_obj: AttentionMask instance
        lens: optional (B,) array of per-batch sequence lengths

    Returns:
        output: (B, H, T, D) attention output (float64)
        lse: (B, H, T) log-sum-exp values (float64, -inf for fully masked)
    """
    B, H, T, D = q.shape
    output = np.zeros((B, H, T, D), dtype=np.float64)
    lse = np.full((B, H, T), -np.inf, dtype=np.float64)
    scale = 1.0 / np.sqrt(D)

    for b in range(B):
        seq_len = int(lens[b]) if lens is not None else T
        seq_len = min(max(seq_len, 0), T)
        if seq_len == 0:
            continue

        q_pos = np.arange(seq_len)
        k_pos = np.arange(seq_len)
        full_mask = mask_obj.mask(q_pos, k_pos, seq_len).astype(bool)

        for h in range(H):
            q_slice = q[b, h, :seq_len].astype(np.float64)
            k_slice = k[b, h, :seq_len].astype(np.float64)
            v_slice = v[b, h, :seq_len].astype(np.float64)

            # Compute scaled dot-product scores
            scores = q_slice @ k_slice.T * scale

            # Apply mask: set masked positions to -inf
            scores = np.where(full_mask, scores, -np.inf)

            # Per-row softmax and weighted sum
            for qi in range(seq_len):
                row = scores[qi]
                max_val = np.max(row)
                if np.isinf(max_val) and max_val < 0:
                    # All positions masked for this query
                    continue
                exp_row = np.exp(row - max_val)
                sum_exp = np.sum(exp_row)
                lse[b, h, qi] = max_val + np.log(sum_exp)
                output[b, h, qi] = (exp_row / sum_exp) @ v_slice

    return output, lse
