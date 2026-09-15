"""
Tiled Flash Attention Engine with Sparse Mask Support.

Implement all classes and functions in this file.
All tensor operations use numpy. Inputs/outputs are numpy float64 arrays.
"""

import numpy as np
from abc import ABC, abstractmethod


class AttentionMask(ABC):
    """Base class for attention mask patterns."""

    def __init__(self, args=None):
        self.args = args or ()

    @abstractmethod
    def mask(self, q_indices, k_indices, seq_len):
        """
        Compute the boolean attention mask for given query and key positions.

        The returned mask represents the attention PATTERN only and does NOT
        include sequence-length bounds (q < seq_len, k < seq_len). Those
        bounds are applied externally by the caller.

        Args:
            q_indices: 1D numpy int array of query positions.
            k_indices: 1D numpy int array of key positions.
            seq_len:   int, the effective sequence length.

        Returns:
            2D bool numpy array of shape (len(q_indices), len(k_indices)).
            Entry [i, j] is True if query q_indices[i] may attend to key k_indices[j].
        """
        pass

    @abstractmethod
    def k_range_for_q(self, q, seq_len):
        """
        Tight inclusive bounds on the key indices that query position q attends to.

        "Tight" means there exist actual True mask entries at both the returned
        minimum and maximum.  The bounds MUST account for seq_len (clip to
        [0, seq_len-1]).

        Args:
            q:        int, query position.
            seq_len:  int, effective sequence length.

        Returns:
            (k_min, k_max): ints, inclusive on both ends.
        """
        pass

    @abstractmethod
    def q_range_for_k(self, k, seq_len):
        """
        Tight inclusive bounds on the query indices that attend to key position k.

        Same tightness and seq_len semantics as k_range_for_q.

        Args:
            k:        int, key position.
            seq_len:  int, effective sequence length.

        Returns:
            (q_min, q_max): ints, inclusive on both ends.
        """
        pass

    def k_full_range_for_q_tile(self, qb, tile_q, seq_len):
        """
        Exclusive range of key indices that are FULLY UNMASKED for every query
        in the tile [qb, qb + tile_q).

        For all q in [qb, min(qb + tile_q, seq_len)) and all k in
        [k_start, k_end), mask(q, k) is guaranteed True (ignoring seq_len
        bounds on individual positions, which are handled separately).

        This is the intersection of k_range_for_q(q, seq_len) across all
        queries in the tile, converted to an exclusive end.

        Args:
            qb:       int, start of the query tile.
            tile_q:   int, tile size.
            seq_len:  int, effective sequence length.

        Returns:
            (k_start, k_end): ints, half-open interval [k_start, k_end).
            Return (0, 0) if no fully unmasked range exists.
        """
        return (0, 0)


class FullMask(AttentionMask):
    """All queries attend to all keys (unrestricted attention)."""

    def __init__(self):
        super().__init__()


class CausalMask(AttentionMask):
    """Autoregressive mask: query at position q attends to keys at positions <= q."""

    def __init__(self):
        super().__init__()


class SlidingWindowMask(AttentionMask):
    """
    Sliding window attention.

    Query q attends to keys k where q - left_context <= k <= q + right_context.
    """

    def __init__(self, left_context, right_context):
        super().__init__((left_context, right_context))
        self.left_context = left_context
        self.right_context = right_context


class ChunkwiseMask(AttentionMask):
    """
    Chunkwise attention.

    The sequence is divided into non-overlapping chunks of chunk_size tokens.
    Query q (in chunk c_q) attends to keys in chunks c_q, c_q-1, ..., c_q-back_chunks.
    """

    def __init__(self, chunk_size, back_chunks):
        super().__init__((chunk_size, back_chunks))
        self.chunk_size = chunk_size
        self.back_chunks = back_chunks


class PrefixLMMask(AttentionMask):
    """
    Prefix Language Model mask.

    Positions within the prefix (k < prefix_size) use bidirectional attention
    (visible to all queries). Positions outside the prefix use causal attention
    (query q attends to key k only if q >= k).
    """

    def __init__(self, prefix_size):
        super().__init__((prefix_size,))
        self.prefix_size = prefix_size


def naive_attention(Q, K, V, mask, lens=None):
    """
    Reference attention implementation using full T x T score matrix.

    Computes: softmax(Q @ K^T / sqrt(D)) @ V with the given mask applied.

    Args:
        Q: numpy array of shape (B, H, T, D), float64.
        K: numpy array of shape (B, H, T, D), float64.
        V: numpy array of shape (B, H, T, D), float64.
        mask: AttentionMask instance.
        lens: optional numpy int array of shape (B,). If provided, positions
              >= lens[b] in batch element b are masked out and output as zero.

    Returns:
        numpy array of shape (B, H, T, D), float64.
    """
    pass


def tiled_attention(Q, K, V, mask, tile_q, tile_k, lens=None):
    """
    Tiled attention using the online softmax algorithm (Flash Attention).

    Must NOT allocate or compute the full T x T attention score matrix.
    Must use the mask's analytical range functions (k_range_for_q) to
    determine which key tiles to visit, skipping tiles entirely outside
    any attending query's range.

    Same args and return type as naive_attention, plus:
        tile_q: int, query tile size.
        tile_k: int, key tile size.
    """
    pass


def verify_mask(mask, max_pos):
    """
    Validate consistency between mask() and analytical range functions.

    Checks performed:
      1. k_range_for_q(q, max_pos) returns tight (exact) bounds for every q.
      2. q_range_for_k(k, max_pos) returns tight (exact) bounds for every k.
      3. k_full_range_for_q_tile(qb, tile_q, max_pos) returns a range that
         is fully unmasked (all True) for every tested tile size.

    Raises:
        AssertionError with a descriptive message on any inconsistency.
    """
    pass
