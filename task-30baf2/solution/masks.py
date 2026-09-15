"""
Attention mask implementations for causal, sliding window,
chunkwise, and prefix-LM patterns.
"""
import numpy as np
from mask_base import AttentionMask


class CausalMask(AttentionMask):
    """Causal (autoregressive) mask: query q attends to key k iff q >= k."""

    def __init__(self):
        super().__init__()

    def mask(self, q_pos, k_pos, seq_len):
        return q_pos[:, None] >= k_pos[None, :]

    def q_range_for_k(self, k, seq_len):
        return (k, seq_len - 1)

    def k_range_for_q(self, q, seq_len):
        return (0, q)

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        # All q in [q_start, q_start+tile_q) attend to k in [0, q].
        # Intersection: [0, q_start]. Half-open: [0, q_start + 1).
        return (0, min(q_start + 1, seq_len))


class SlidingWindowMask(AttentionMask):
    """
    Sliding window mask: q attends to k iff q - left <= k <= q + right.

    Args:
        left_context: number of preceding positions in the window
        right_context: number of following positions in the window
    """

    def __init__(self, left_context, right_context):
        super().__init__((left_context, right_context))
        self.left_context = left_context
        self.right_context = right_context

    def mask(self, q_pos, k_pos, seq_len):
        return ((k_pos[None, :] >= q_pos[:, None] - self.left_context) &
                (k_pos[None, :] <= q_pos[:, None] + self.right_context))

    def q_range_for_k(self, k, seq_len):
        # q attends to k iff q - left <= k <= q + right
        # iff k - right <= q <= k + left
        return (max(0, k - self.right_context),
                min(k + self.left_context, seq_len - 1))

    def k_range_for_q(self, q, seq_len):
        return (max(0, q - self.left_context),
                min(q + self.right_context, seq_len - 1))

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        # k_range_for_q(q) = [q - left, q + right]
        # Intersection over q in [q_start, q_start+tile_q-1]:
        #   k_start = max(q - left) = q_start + tile_q - 1 - left
        #   k_end = min(q + right) = q_start + right
        # Half-open: [k_start, k_end + 1)
        k_start = max(0, q_start + tile_q - 1 - self.left_context)
        k_end = min(q_start + self.right_context + 1, seq_len)
        return (k_start, max(k_start, k_end))


class ChunkwiseMask(AttentionMask):
    """
    Chunkwise mask: q attends to k iff 0 <= floor(q/cs) - floor(k/cs) <= bc.

    Divides the sequence into fixed-size chunks. Each query can attend to
    its own chunk and a specified number of preceding chunks.

    Args:
        chunk_size: size of each chunk
        back_chunks: number of preceding chunks to attend to
    """

    def __init__(self, chunk_size, back_chunks):
        super().__init__((chunk_size, back_chunks))
        self.chunk_size = chunk_size
        self.back_chunks = back_chunks

    def mask(self, q_pos, k_pos, seq_len):
        q_block = q_pos[:, None] // self.chunk_size
        k_block = k_pos[None, :] // self.chunk_size
        diff = q_block - k_block
        return (diff >= 0) & (diff <= self.back_chunks)

    def q_range_for_k(self, k, seq_len):
        k_block = k // self.chunk_size
        q_start = k_block * self.chunk_size
        q_end = min((k_block + self.back_chunks + 1) * self.chunk_size - 1,
                     seq_len - 1)
        return (q_start, q_end)

    def k_range_for_q(self, q, seq_len):
        q_block = q // self.chunk_size
        k_start = max(0, (q_block - self.back_chunks) * self.chunk_size)
        k_end = min((q_block + 1) * self.chunk_size - 1, seq_len - 1)
        return (k_start, k_end)

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        # k_range_for_q(q) = [(q//cs - bc)*cs, (q//cs + 1)*cs - 1]
        # For tile [q_start, q_start+tile_q):
        #   q_block_min = q_start // cs
        #   q_block_max = (q_start + tile_q - 1) // cs
        # Intersection:
        #   k_start = (q_block_max - bc) * cs  (largest lower bound)
        #   k_end = (q_block_min + 1) * cs      (smallest upper bound, half-open)
        q_block_min = q_start // self.chunk_size
        q_block_max = (q_start + tile_q - 1) // self.chunk_size
        k_start = max(0, (q_block_max - self.back_chunks) * self.chunk_size)
        k_end = min((q_block_min + 1) * self.chunk_size, seq_len)
        return (k_start, max(k_start, k_end))


class PrefixLMMask(AttentionMask):
    """
    Prefix Language Model mask: bidirectional in prefix, causal elsewhere.

    q attends to k iff k < prefix_size OR q >= k.

    Args:
        prefix_size: size of the bidirectional prefix region
    """

    def __init__(self, prefix_size):
        super().__init__((prefix_size,))
        self.prefix_size = prefix_size

    def mask(self, q_pos, k_pos, seq_len):
        prefix_mask = k_pos[None, :] < self.prefix_size
        causal_mask = q_pos[:, None] >= k_pos[None, :]
        return prefix_mask | causal_mask

    def q_range_for_k(self, k, seq_len):
        if k < self.prefix_size:
            return (0, seq_len - 1)
        else:
            return (k, seq_len - 1)

    def k_range_for_q(self, q, seq_len):
        right = max(q, self.prefix_size - 1)
        return (0, min(right, seq_len - 1))

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        # k_range_for_q(q) = [0, max(q, prefix-1)]
        # Intersection for q in [q_start, q_start+tile_q):
        #   min of max(q, prefix-1) = max(q_start, prefix-1)
        # Half-open: [0, max(q_start, prefix-1) + 1)
        #          = [0, max(q_start + 1, prefix))
        end = max(self.prefix_size, q_start + 1)
        return (0, min(end, seq_len))
