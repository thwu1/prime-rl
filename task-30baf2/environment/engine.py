"""
Tiled attention engine.

Implement tiled_attention() to compute masked attention equivalent to
reference.py, but processing Q and K in tiles rather than materializing
the full T*T score matrix. The implementation must use
mask_obj.k_full_range_for_q_tile() to identify key tiles that need
no masking and skip mask computation for those tiles.
"""
import numpy as np


def tiled_attention(q, k, v, mask_obj, lens=None, tile_q=32, tile_k=32):
    """
    Compute masked attention using tiled processing.

    Args:
        q: (B, H, T, D) query array
        k: (B, H, T, D) key array
        v: (B, H, T, D) value array
        mask_obj: AttentionMask instance providing mask() and range functions
        lens: optional (B,) array of per-batch sequence lengths
        tile_q: query tile size
        tile_k: key tile size

    Returns:
        output: (B, H, T, D) attention output (float64)
        lse: (B, H, T) log-sum-exp per query position (-inf if fully masked)
    """
    raise NotImplementedError("Implement the tiled attention engine")
