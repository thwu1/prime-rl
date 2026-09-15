"""
Attention mask base class and full attention mask implementation.

Defines the abstract interface for structured attention masks
used in the tiled attention engine.
"""
import numpy as np
from abc import ABC, abstractmethod


class AttentionMask(ABC):
    """
    Abstract base class for structured attention mask patterns.

    Each mask defines which query-key pairs are allowed to attend.
    Subclasses must implement:
      - mask(q_pos, k_pos, seq_len) -> bool array (len(q_pos), len(k_pos))
      - q_range_for_k(k, seq_len) -> (q_min, q_max) tight inclusive range
      - k_range_for_q(q, seq_len) -> (k_min, k_max) tight inclusive range
      - k_full_range_for_q_tile(q_start, tile_q, seq_len) -> (k_start, k_end) half-open
    """

    def __init__(self, constargs=None):
        self.constargs = constargs or ()

    def __str__(self):
        if self.constargs:
            return f"{type(self).__name__}({', '.join(map(str, self.constargs))})"
        return type(self).__name__

    def __repr__(self):
        return str(self)

    @abstractmethod
    def mask(self, q_pos, k_pos, seq_len):
        """
        Compute boolean attention mask.

        Args:
            q_pos: 1D numpy array of query positions
            k_pos: 1D numpy array of key positions
            seq_len: int, total sequence length

        Returns:
            2D boolean array of shape (len(q_pos), len(k_pos)).
            True means the query can attend to the key.
        """
        ...

    @abstractmethod
    def q_range_for_k(self, k, seq_len):
        """
        Tight inclusive range [q_min, q_max] of query positions
        that can attend to key position k.

        Must match exactly the first and last True positions
        in mask[:, k] for a full mask matrix.
        """
        ...

    @abstractmethod
    def k_range_for_q(self, q, seq_len):
        """
        Tight inclusive range [k_min, k_max] of key positions
        that query position q can attend to.

        Must match exactly the first and last True positions
        in mask[q, :] for a full mask matrix.
        """
        ...

    @abstractmethod
    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        """
        Half-open range [k_start, k_end) of key indices that are FULLY
        unmasked for ALL query positions in [q_start, q_start + tile_q).

        This is the intersection of k_range_for_q(q) across all q in the
        tile, converted to half-open [inclusive_min, inclusive_max + 1).

        Used for loop-splitting optimization in the tiled engine:
        K tiles within this range need no mask computation.

        May return (x, x) for an empty range (no guaranteed unmasked keys).
        """
        ...

    def make_mask(self, seq_len):
        """Create full boolean mask matrix of shape (seq_len, seq_len)."""
        q_pos = np.arange(seq_len)
        k_pos = np.arange(seq_len)
        return self.mask(q_pos, k_pos, seq_len).astype(bool)

    def verify(self, seq_len):
        """
        Verify consistency between mask() and range functions.
        Raises AssertionError if any inconsistency is found.
        """
        mask = self.make_mask(seq_len)
        assert mask.dtype == bool, "mask must return boolean array"
        assert mask.shape == (seq_len, seq_len), (
            f"mask shape {mask.shape} != ({seq_len}, {seq_len})"
        )

        # Verify q_range_for_k is tight
        for k in range(seq_len):
            q_min, q_max = self.q_range_for_k(k, seq_len)
            q_min, q_max = int(q_min), int(q_max)
            true_qs = np.where(mask[:, k])[0]
            if len(true_qs) > 0:
                assert q_min == int(true_qs[0]), (
                    f"q_range_for_k({k}, {seq_len}): "
                    f"q_min={q_min}, expected {true_qs[0]}"
                )
                assert q_max == int(true_qs[-1]), (
                    f"q_range_for_k({k}, {seq_len}): "
                    f"q_max={q_max}, expected {true_qs[-1]}"
                )

        # Verify k_range_for_q is tight
        for q in range(seq_len):
            k_min, k_max = self.k_range_for_q(q, seq_len)
            k_min, k_max = int(k_min), int(k_max)
            true_ks = np.where(mask[q, :])[0]
            if len(true_ks) > 0:
                assert k_min == int(true_ks[0]), (
                    f"k_range_for_q({q}, {seq_len}): "
                    f"k_min={k_min}, expected {true_ks[0]}"
                )
                assert k_max == int(true_ks[-1]), (
                    f"k_range_for_q({q}, {seq_len}): "
                    f"k_max={k_max}, expected {true_ks[-1]}"
                )

        # Verify k_full_range_for_q_tile correctness
        for tile_q in [16, 32]:
            for q_start in range(0, seq_len, tile_q):
                q_end = min(q_start + tile_q, seq_len)
                ks, ke = self.k_full_range_for_q_tile(q_start, tile_q, seq_len)
                ks, ke = int(ks), int(ke)
                if ke > ks:
                    ke_clip = min(ke, seq_len)
                    if ke_clip > ks:
                        tile_mask = mask[q_start:q_end, ks:ke_clip]
                        assert np.all(tile_mask), (
                            f"k_full_range_for_q_tile({q_start}, {tile_q}, "
                            f"{seq_len}) returned [{ks}, {ke}) but some "
                            f"positions are masked:\n{tile_mask}"
                        )


class FullMask(AttentionMask):
    """Full attention: every query attends to every key."""

    def __init__(self):
        super().__init__()

    def mask(self, q_pos, k_pos, seq_len):
        return np.ones((len(q_pos), len(k_pos)), dtype=bool)

    def q_range_for_k(self, k, seq_len):
        return (0, seq_len - 1)

    def k_range_for_q(self, q, seq_len):
        return (0, seq_len - 1)

    def k_full_range_for_q_tile(self, q_start, tile_q, seq_len):
        return (0, seq_len)
