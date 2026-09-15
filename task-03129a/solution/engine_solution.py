"""
Tiled Flash Attention Engine with Sparse Mask Support — Full Solution.
"""

import numpy as np
from abc import ABC, abstractmethod


class AttentionMask(ABC):
    """Base class for attention mask patterns."""

    def __init__(self, args=None):
        self.args = args or ()

    @abstractmethod
    def mask(self, q_indices, k_indices, seq_len):
        pass

    @abstractmethod
    def k_range_for_q(self, q, seq_len):
        pass

    @abstractmethod
    def q_range_for_k(self, k, seq_len):
        pass

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        return (0, 0)


class FullMask(AttentionMask):
    """All queries attend to all keys."""

    def __init__(self):
        super().__init__()

    def mask(self, q_indices, k_indices, seq_len):
        return np.ones((len(q_indices), len(k_indices)), dtype=bool)

    def k_range_for_q(self, q, seq_len):
        return (0, seq_len - 1)

    def q_range_for_k(self, k, seq_len):
        return (0, seq_len - 1)

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        return (0, seq_len)


class CausalMask(AttentionMask):
    """Autoregressive mask: q >= k."""

    def __init__(self):
        super().__init__()

    def mask(self, q_indices, k_indices, seq_len):
        return q_indices[:, None] >= k_indices[None, :]

    def k_range_for_q(self, q, seq_len):
        return (0, min(q, seq_len - 1))

    def q_range_for_k(self, k, seq_len):
        return (k, seq_len - 1)

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        # All q in [qb, qb+tile_q) can attend to keys [0, qb].
        # The tightest constraint (smallest q) gives k_end = qb.
        # Exclusive: [0, qb + 1)
        return (0, min(qb + 1, seq_len))


class SlidingWindowMask(AttentionMask):
    """Sliding window: q - left_context <= k <= q + right_context."""

    def __init__(self, left_context, right_context):
        super().__init__((left_context, right_context))
        self.left_context = left_context
        self.right_context = right_context

    def mask(self, q_indices, k_indices, seq_len):
        diff = q_indices[:, None] - k_indices[None, :]
        return (diff >= -self.right_context) & (diff <= self.left_context)

    def k_range_for_q(self, q, seq_len):
        return (max(0, q - self.left_context),
                min(q + self.right_context, seq_len - 1))

    def q_range_for_k(self, k, seq_len):
        return (max(0, k - self.right_context),
                min(k + self.left_context, seq_len - 1))

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        # Intersection of k_ranges for q in [qb, qb+tile_q):
        #   q=qb       : k in [qb - left, qb + right]
        #   q=qb+tq-1  : k in [qb+tq-1-left, qb+tq-1+right]
        # Intersection: [max of starts, min of ends]
        start = max(0, qb + tile_q - 1 - self.left_context)
        end = min(seq_len, qb + self.right_context + 1)
        return (start, max(start, end))


class ChunkwiseMask(AttentionMask):
    """Chunkwise: attend to own chunk + back_chunks preceding chunks."""

    def __init__(self, chunk_size, back_chunks):
        super().__init__((chunk_size, back_chunks))
        self.chunk_size = chunk_size
        self.back_chunks = back_chunks

    def mask(self, q_indices, k_indices, seq_len):
        q_block = q_indices[:, None] // self.chunk_size
        k_block = k_indices[None, :] // self.chunk_size
        diff = q_block - k_block
        return (diff >= 0) & (diff <= self.back_chunks)

    def k_range_for_q(self, q, seq_len):
        q_chunk = q // self.chunk_size
        k_start = max(0, (q_chunk - self.back_chunks) * self.chunk_size)
        k_end = min((q_chunk + 1) * self.chunk_size - 1, seq_len - 1)
        return (k_start, k_end)

    def q_range_for_k(self, k, seq_len):
        k_chunk = k // self.chunk_size
        q_start = k_chunk * self.chunk_size
        q_end = min((k_chunk + self.back_chunks + 1) * self.chunk_size - 1,
                     seq_len - 1)
        return (q_start, q_end)

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        q_block_min = qb // self.chunk_size
        q_block_max = (qb + tile_q - 1) // self.chunk_size

        # k_end constrained by the query in the smallest chunk (tightest right bound)
        k_end = (q_block_min + 1) * self.chunk_size
        # k_start constrained by the query in the largest chunk (tightest left bound)
        k_start = max(0, (q_block_max - self.back_chunks) * self.chunk_size)

        start = max(0, k_start)
        end = min(seq_len, k_end)
        return (start, max(start, end))


class PrefixLMMask(AttentionMask):
    """Prefix LM: bidirectional in prefix, causal elsewhere."""

    def __init__(self, prefix_size):
        super().__init__((prefix_size,))
        self.prefix_size = prefix_size

    def mask(self, q_indices, k_indices, seq_len):
        prefix_mask = k_indices[None, :] < self.prefix_size
        causal_mask = q_indices[:, None] >= k_indices[None, :]
        return prefix_mask | causal_mask

    def k_range_for_q(self, q, seq_len):
        right = max(q, self.prefix_size - 1)
        return (0, min(right, seq_len - 1))

    def q_range_for_k(self, k, seq_len):
        left = 0 if k < self.prefix_size else k
        return (left, seq_len - 1)

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        # k_range_for_q(q) = [0, max(q, prefix_size - 1)]
        # Tightest right bound is from the smallest q (qb):
        #   end = max(qb, prefix_size - 1) + 1 = max(prefix_size, qb + 1)
        end = max(self.prefix_size, qb + 1)
        return (0, min(end, seq_len))


def naive_attention(Q, K, V, mask, lens=None):
    """Reference attention using full T x T score matrix materialization."""
    B, H, T, D = Q.shape
    scale = 1.0 / np.sqrt(D)
    result = np.zeros_like(Q)

    q_idx = np.arange(T)
    k_idx = np.arange(T)

    for b in range(B):
        seq_len = T if lens is None else min(int(lens[b]), T)

        # Compute combined mask: pattern + seq_len bounds
        m = mask.mask(q_idx, k_idx, seq_len)
        q_valid = q_idx[:, None] < seq_len
        k_valid = k_idx[None, :] < seq_len
        m = m & q_valid & k_valid

        for h in range(H):
            scores = (Q[b, h] @ K[b, h].T) * scale  # (T, T)
            scores = np.where(m, scores, -np.inf)

            # Numerically stable softmax
            max_s = np.max(scores, axis=-1, keepdims=True)
            # Handle fully-masked rows (max = -inf)
            max_s = np.where(np.isneginf(max_s), 0.0, max_s)
            exp_s = np.exp(scores - max_s)
            sum_exp = np.sum(exp_s, axis=-1, keepdims=True)
            sum_exp = np.where(sum_exp == 0.0, 1.0, sum_exp)
            attn = exp_s / sum_exp

            out = attn @ V[b, h]  # (T, D)

            # Zero out invalid query positions
            invalid = q_idx >= seq_len
            out[invalid] = 0.0

            result[b, h] = out

    return result


def tiled_attention(Q, K, V, mask, tile_q, tile_k, lens=None):
    """
    Tiled attention using online softmax (Flash Attention algorithm).
    Never materializes the full T x T matrix.
    Uses mask range functions for loop splitting.
    """
    B, H, T, D = Q.shape
    scale = 1.0 / np.sqrt(D)
    result = np.zeros_like(Q)

    for b in range(B):
        seq_len = T if lens is None else min(int(lens[b]), T)

        for h in range(H):
            for q_start in range(0, T, tile_q):
                q_end = min(q_start + tile_q, T)
                actual_tq = q_end - q_start

                if q_start >= seq_len:
                    continue

                q_tile = Q[b, h, q_start:q_end]  # (actual_tq, D)
                q_indices = np.arange(q_start, q_end)

                # --- Online softmax state ---
                m_i = np.full(actual_tq, -np.inf)  # running max
                l_i = np.zeros(actual_tq)            # running sum of exp
                acc = np.zeros((actual_tq, D))       # running weighted sum

                # --- Loop splitting: find bounding k range ---
                k_lo = seq_len
                k_hi = -1
                for qi in range(q_start, min(q_end, seq_len)):
                    ks, ke = mask.k_range_for_q(qi, seq_len)
                    k_lo = min(k_lo, ks)
                    k_hi = max(k_hi, ke)

                if k_hi < 0:
                    continue

                # Align to tile boundaries and iterate
                k_tile_start = (k_lo // tile_k) * tile_k
                k_tile_end_bound = min(k_hi + 1, seq_len)

                for k_start in range(k_tile_start, k_tile_end_bound, tile_k):
                    k_end = min(k_start + tile_k, T)
                    k_indices = np.arange(k_start, k_end)

                    kt_tile = K[b, h, k_start:k_end]  # (actual_tk, D)
                    v_tile = V[b, h, k_start:k_end]    # (actual_tk, D)

                    # QK^T for this tile pair
                    qk = (q_tile @ kt_tile.T) * scale  # (actual_tq, actual_tk)

                    # Apply combined mask
                    m_tile = mask.mask(q_indices, k_indices, seq_len)
                    q_valid = (q_indices[:, None] < seq_len)
                    k_valid = (k_indices[None, :] < seq_len)
                    m_tile = m_tile & q_valid & k_valid

                    qk = np.where(m_tile, qk, -np.inf)

                    # --- Online softmax update ---
                    m_ij = np.maximum(m_i, np.max(qk, axis=-1))

                    p = np.exp(qk - m_ij[:, None])
                    p = np.nan_to_num(p, nan=0.0)

                    l_ij = np.sum(p, axis=-1)

                    alpha = np.exp(m_i - m_ij)
                    alpha = np.nan_to_num(alpha, nan=0.0)

                    l_i = l_i * alpha + l_ij
                    acc = acc * alpha[:, None] + p @ v_tile

                    m_i = m_ij

                # Final normalization
                l_safe = np.where(l_i == 0.0, 1.0, l_i)
                acc = acc / l_safe[:, None]

                # Zero out invalid positions
                invalid = q_indices >= seq_len
                acc[invalid] = 0.0

                result[b, h, q_start:q_end] = acc

    return result


def verify_mask(mask, max_pos):
    """
    Validate consistency between mask() and analytical range functions.
    """
    q_idx = np.arange(max_pos)
    k_idx = np.arange(max_pos)
    full_mask = mask.mask(q_idx, k_idx, max_pos)

    # --- Check k_range_for_q tightness ---
    for q in range(max_pos):
        row = full_mask[q]
        if not np.any(row):
            continue

        true_pos = np.where(row)[0]
        actual_k_min = int(true_pos[0])
        actual_k_max = int(true_pos[-1])

        analytical_k_min, analytical_k_max = mask.k_range_for_q(q, max_pos)

        assert analytical_k_min == actual_k_min, (
            f"k_range_for_q({q}, {max_pos}): "
            f"analytical k_min={analytical_k_min}, actual={actual_k_min}"
        )
        assert analytical_k_max == actual_k_max, (
            f"k_range_for_q({q}, {max_pos}): "
            f"analytical k_max={analytical_k_max}, actual={actual_k_max}"
        )

    # --- Check q_range_for_k tightness ---
    for k in range(max_pos):
        col = full_mask[:, k]
        if not np.any(col):
            continue

        true_pos = np.where(col)[0]
        actual_q_min = int(true_pos[0])
        actual_q_max = int(true_pos[-1])

        analytical_q_min, analytical_q_max = mask.q_range_for_k(k, max_pos)

        assert analytical_q_min == actual_q_min, (
            f"q_range_for_k({k}, {max_pos}): "
            f"analytical q_min={analytical_q_min}, actual={actual_q_min}"
        )
        assert analytical_q_max == actual_q_max, (
            f"q_range_for_k({k}, {max_pos}): "
            f"analytical q_max={analytical_q_max}, actual={actual_q_max}"
        )

    # --- Check k_full_range_for_q_tile ---
    for tile_q in [4, 8, 16, 32]:
        for qb in range(0, max_pos, tile_q):
            q_end = min(qb + tile_q, max_pos)
            k_start, k_end = mask.k_full_range_for_q_tile(qb, tile_q, max_pos)

            if k_end <= k_start:
                continue

            k_end_clipped = min(k_end, max_pos)
            if k_end_clipped <= k_start:
                continue

            tile = full_mask[qb:q_end, k_start:k_end_clipped]
            assert np.all(tile), (
                f"k_full_range_for_q_tile(qb={qb}, tile_q={tile_q}, "
                f"seq_len={max_pos}): range [{k_start}, {k_end}) not fully "
                f"unmasked. False count: {np.sum(~tile)}"
            )
