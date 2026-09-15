"""
Compound attention mask implementations.
"""
import numpy as np
from mask_base import AttentionMask


class IntersectionMask(AttentionMask):
    """
    Intersection of two attention masks: q attends to k iff
    mask_a(q, k) AND mask_b(q, k).
    """

    def __init__(self, mask_a, mask_b):
        super().__init__()
        self.mask_a = mask_a
        self.mask_b = mask_b

    def __str__(self):
        return f"Intersection({self.mask_a}, {self.mask_b})"

    def mask(self, q_pos, k_pos, seq_len):
        return (self.mask_a.mask(q_pos, k_pos, seq_len) &
                self.mask_b.mask(q_pos, k_pos, seq_len))

    def q_range_for_k(self, k, seq_len):
        a_min, a_max = self.mask_a.q_range_for_k(k, seq_len)
        b_min, b_max = self.mask_b.q_range_for_k(k, seq_len)
        return (max(int(a_min), int(b_min)), min(int(a_max), int(b_max)))

    def k_range_for_q(self, q, seq_len):
        a_min, a_max = self.mask_a.k_range_for_q(q, seq_len)
        b_min, b_max = self.mask_b.k_range_for_q(q, seq_len)
        return (max(int(a_min), int(b_min)), min(int(a_max), int(b_max)))

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        a_s, a_e = self.mask_a.k_full_range_for_q_tile(q_start, tile_q, seq_len)
        b_s, b_e = self.mask_b.k_full_range_for_q_tile(q_start, tile_q, seq_len)
        start = max(int(a_s), int(b_s))
        end = min(int(a_e), int(b_e))
        return (start, max(start, end))


class LocalGlobalMask(AttentionMask):
    """
    Local-global attention mask (Longformer-style).

    Query q attends to key k iff:
      - |q - k| <= window_size  (local window), OR
      - k < n_global            (global tokens)

    Args:
        window_size: radius of the symmetric local attention window
        n_global: number of global tokens at the start of the sequence
    """

    def __init__(self, window_size, n_global):
        super().__init__((window_size, n_global))
        self.window_size = window_size
        self.n_global = n_global

    def mask(self, q_pos, k_pos, seq_len):
        local = np.abs(q_pos[:, None] - k_pos[None, :]) <= self.window_size
        global_mask = k_pos[None, :] < self.n_global
        return local | global_mask

    def q_range_for_k(self, k, seq_len):
        if k < self.n_global:
            return (0, seq_len - 1)
        return (max(0, k - self.window_size),
                min(k + self.window_size, seq_len - 1))

    def k_range_for_q(self, q, seq_len):
        local_start = max(0, q - self.window_size)
        local_end = min(q + self.window_size, seq_len - 1)
        if self.n_global > 0:
            # Tight range spans from first global token to end of local window
            global_end = min(self.n_global - 1, seq_len - 1)
            return (0, max(global_end, local_end))
        return (local_start, local_end)

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        # Local window intersection across all queries in tile
        local_start = q_start + tile_q - 1 - self.window_size
        local_end = q_start + self.window_size + 1
        local_start = max(0, local_start)
        local_end = min(local_end, seq_len)
        local_valid = local_end > local_start

        # Global range: always fully unmasked
        global_end = min(self.n_global, seq_len)
        global_valid = global_end > 0

        if not local_valid and not global_valid:
            return (0, 0)
        elif not local_valid:
            return (0, global_end)
        elif not global_valid:
            return (local_start, local_end)
        else:
            # Both valid - merge if overlapping or adjacent
            if global_end >= local_start:
                return (0, max(global_end, local_end))
            else:
                # Disjoint: return the larger range
                global_size = global_end
                local_size = local_end - local_start
                if global_size >= local_size:
                    return (0, global_end)
                else:
                    return (local_start, local_end)
