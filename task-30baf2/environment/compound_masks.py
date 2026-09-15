"""
Compound attention mask implementations.

Implement IntersectionMask and LocalGlobalMask classes extending
the AttentionMask base class from mask_base.py. Each must implement
mask(), q_range_for_k(), k_range_for_q(), and k_full_range_for_q_tile().

Use mask.verify(seq_len) to check consistency of your range functions.
"""
import numpy as np
from mask_base import AttentionMask


class IntersectionMask(AttentionMask):
    """
    Intersection of two attention masks: q attends to k iff
    mask_a(q, k) AND mask_b(q, k).

    Range functions must return tight bounds for the intersection.
    k_full_range_for_q_tile must return a range fully unmasked
    under BOTH sub-masks.
    """

    def __init__(self, mask_a, mask_b):
        super().__init__()
        self.mask_a = mask_a
        self.mask_b = mask_b

    def __str__(self):
        return f"Intersection({self.mask_a}, {self.mask_b})"

    def mask(self, q_pos, k_pos, seq_len):
        raise NotImplementedError

    def q_range_for_k(self, k, seq_len):
        raise NotImplementedError

    def k_range_for_q(self, q, seq_len):
        raise NotImplementedError

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        raise NotImplementedError


class LocalGlobalMask(AttentionMask):
    """
    Local-global attention mask (Longformer-style).

    Query q attends to key k iff:
      - |q - k| <= window_size  (local window), OR
      - k < n_global            (global tokens)

    Range functions must account for both the local window and the
    global token region. k_full_range_for_q_tile must return the
    largest correct contiguous range that is guaranteed fully unmasked
    for all queries in the tile.

    Args:
        window_size: radius of the symmetric local attention window
        n_global: number of global tokens at the start of the sequence
    """

    def __init__(self, window_size, n_global):
        super().__init__((window_size, n_global))
        self.window_size = window_size
        self.n_global = n_global

    def mask(self, q_pos, k_pos, seq_len):
        raise NotImplementedError

    def q_range_for_k(self, k, seq_len):
        raise NotImplementedError

    def k_range_for_q(self, q, seq_len):
        raise NotImplementedError

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        raise NotImplementedError
