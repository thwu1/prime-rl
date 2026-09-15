"""
Tiled attention engine using the online softmax algorithm (Flash Attention).
"""
import numpy as np


def tiled_attention(q, k, v, mask_obj, lens=None, tile_q=32, tile_k=32):
    """
    Compute masked attention using tiled online softmax.

    Args:
        q: (B, H, T, D) query array
        k: (B, H, T, D) key array
        v: (B, H, T, D) value array
        mask_obj: AttentionMask instance
        lens: optional (B,) array of per-batch sequence lengths
        tile_q: tile size for query dimension
        tile_k: tile size for key dimension

    Returns:
        output: (B, H, T, D) attention output (float64)
        lse: (B, H, T) log-sum-exp values (-inf for masked/unused positions)
    """
    B, H, T, D = q.shape
    output = np.zeros((B, H, T, D), dtype=np.float64)
    lse_arr = np.full((B, H, T), -np.inf, dtype=np.float64)
    scale = 1.0 / np.sqrt(D)

    for b in range(B):
        seq_len = int(lens[b]) if lens is not None else T
        seq_len = min(max(seq_len, 0), T)
        if seq_len == 0:
            continue

        for h in range(H):
            for qi_start in range(0, seq_len, tile_q):
                qi_end = min(qi_start + tile_q, seq_len)
                actual_tq = qi_end - qi_start

                q_tile = q[b, h, qi_start:qi_end].astype(np.float64)
                q_pos = np.arange(qi_start, qi_end)

                # Online softmax running state
                m_i = np.full(actual_tq, -np.inf, dtype=np.float64)
                l_i = np.zeros(actual_tq, dtype=np.float64)
                acc = np.zeros((actual_tq, D), dtype=np.float64)

                # Get fully-unmasked K range for loop splitting
                k_full_start, k_full_end = mask_obj.k_full_range_for_q_tile(
                    qi_start, tile_q, seq_len
                )
                k_full_start = max(0, int(k_full_start))
                k_full_end = min(seq_len, int(k_full_end))

                for ki_start in range(0, seq_len, tile_k):
                    ki_end = min(ki_start + tile_k, seq_len)

                    k_tile = k[b, h, ki_start:ki_end].astype(np.float64)
                    v_tile = v[b, h, ki_start:ki_end].astype(np.float64)

                    # Compute QK^T scaled
                    qk = q_tile @ k_tile.T * scale

                    # Loop splitting: check if this K tile is fully unmasked
                    if ki_start >= k_full_start and ki_end <= k_full_end:
                        # Fully unmasked tile: skip mask computation
                        pass
                    else:
                        # Partially or fully masked: compute and apply mask
                        k_pos = np.arange(ki_start, ki_end)
                        tile_mask = mask_obj.mask(
                            q_pos, k_pos, seq_len
                        ).astype(bool)
                        qk = np.where(tile_mask, qk, -np.inf)

                        # Skip entirely if fully masked
                        if np.all(np.isinf(qk) & (qk < 0)):
                            continue

                    # Online softmax update
                    row_max = np.max(qk, axis=1)
                    m_ij = np.maximum(m_i, row_max)

                    # Rescaling factor for previous accumulations
                    with np.errstate(invalid='ignore'):
                        alpha = np.nan_to_num(
                            np.exp(m_i - m_ij), nan=0.0
                        )
                        p = np.nan_to_num(
                            np.exp(qk - m_ij[:, None]), nan=0.0
                        )

                    l_ij = np.sum(p, axis=1)

                    # Update running state
                    l_i = l_i * alpha + l_ij
                    acc = acc * alpha[:, None]
                    acc += p @ v_tile

                    # Update running max AFTER using old m_i for alpha
                    m_i = m_ij

                # Final normalization
                valid = l_i > 0
                result = np.zeros_like(acc)
                result[valid] = acc[valid] / l_i[valid, None]

                output[b, h, qi_start:qi_end] = result
                lse_arr[b, h, qi_start:qi_end] = np.where(
                    valid,
                    m_i + np.log(np.maximum(l_i, 1e-300)),
                    -np.inf
                )

    return output, lse_arr
