"""
Tests for the Tiled Flash Attention Engine.
"""

import sys
sys.path.insert(0, "/app")

import numpy as np
import pytest

from engine import (
    FullMask,
    CausalMask,
    SlidingWindowMask,
    ChunkwiseMask,
    PrefixLMMask,
    naive_attention,
    tiled_attention,
    verify_mask,
)


# =====================================================================
# Mask pattern correctness tests
# =====================================================================

class TestMaskPatterns:

    def test_full_mask(self):
        mask = FullMask()
        q = np.arange(4)
        k = np.arange(4)
        m = mask.mask(q, k, 4)
        assert m.shape == (4, 4)
        assert np.all(m)

    def test_causal_mask(self):
        mask = CausalMask()
        q = np.arange(4)
        k = np.arange(4)
        m = mask.mask(q, k, 4)
        expected = np.array([
            [True, False, False, False],
            [True, True, False, False],
            [True, True, True, False],
            [True, True, True, True],
        ])
        np.testing.assert_array_equal(m, expected)

    def test_sliding_window_mask(self):
        mask = SlidingWindowMask(2, 1)
        q = np.arange(6)
        k = np.arange(6)
        m = mask.mask(q, k, 6)
        expected = np.zeros((6, 6), dtype=bool)
        for i in range(6):
            for j in range(6):
                d = i - j
                expected[i, j] = (-1 <= d <= 2)
        np.testing.assert_array_equal(m, expected)

    def test_chunkwise_mask(self):
        mask = ChunkwiseMask(3, 1)
        q = np.arange(9)
        k = np.arange(9)
        m = mask.mask(q, k, 9)
        expected = np.zeros((9, 9), dtype=bool)
        for i in range(9):
            for j in range(9):
                qi_c, kj_c = i // 3, j // 3
                diff = qi_c - kj_c
                expected[i, j] = (0 <= diff <= 1)
        np.testing.assert_array_equal(m, expected)

    def test_prefix_lm_mask(self):
        mask = PrefixLMMask(3)
        q = np.arange(6)
        k = np.arange(6)
        m = mask.mask(q, k, 6)
        expected = np.zeros((6, 6), dtype=bool)
        for i in range(6):
            for j in range(6):
                expected[i, j] = (j < 3) or (i >= j)
        np.testing.assert_array_equal(m, expected)

    def test_sliding_window_symmetric(self):
        """Symmetric window: left == right."""
        mask = SlidingWindowMask(5, 5)
        q = np.arange(20)
        k = np.arange(20)
        m = mask.mask(q, k, 20)
        # Symmetric about diagonal
        np.testing.assert_array_equal(m, m.T)

    def test_chunkwise_no_back(self):
        """back_chunks=0: each chunk is isolated."""
        mask = ChunkwiseMask(4, 0)
        q = np.arange(12)
        k = np.arange(12)
        m = mask.mask(q, k, 12)
        for i in range(12):
            for j in range(12):
                assert m[i, j] == (i // 4 == j // 4), \
                    f"Mismatch at ({i},{j})"


# =====================================================================
# verify_mask tests
# =====================================================================

@pytest.mark.parametrize("mask_obj,max_pos", [
    (FullMask(), 64),
    (FullMask(), 100),
    (CausalMask(), 64),
    (CausalMask(), 100),
    (SlidingWindowMask(3, 2), 64),
    (SlidingWindowMask(10, 5), 100),
    (SlidingWindowMask(1, 0), 50),
    (SlidingWindowMask(0, 0), 32),
    (ChunkwiseMask(8, 2), 64),
    (ChunkwiseMask(5, 1), 50),
    (ChunkwiseMask(16, 0), 64),
    (ChunkwiseMask(3, 3), 48),
    (PrefixLMMask(10), 64),
    (PrefixLMMask(1), 50),
    (PrefixLMMask(32), 64),
    (PrefixLMMask(100), 100),
], ids=lambda x: str(x) if not isinstance(x, int) else f"pos={x}")
def test_verify_mask(mask_obj, max_pos):
    verify_mask(mask_obj, max_pos)


# =====================================================================
# Tiled vs Naive attention correctness
# =====================================================================

MASKS_FOR_ATTN = [
    FullMask(),
    CausalMask(),
    SlidingWindowMask(5, 3),
    ChunkwiseMask(4, 1),
    PrefixLMMask(8),
]


@pytest.mark.parametrize("mask_obj", MASKS_FOR_ATTN,
                         ids=lambda m: type(m).__name__)
@pytest.mark.parametrize("B,H,T,D", [
    (1, 1, 1, 16),
    (1, 1, 4, 16),
    (1, 1, 16, 32),
    (2, 2, 32, 16),
    (1, 1, 33, 16),
    (2, 4, 64, 32),
], ids=lambda x: f"shape{x}")
@pytest.mark.parametrize("tile_q,tile_k", [
    (4, 4),
    (8, 16),
    (16, 8),
    (32, 32),
], ids=lambda x: f"tile{x}")
def test_tiled_vs_naive(mask_obj, B, H, T, D, tile_q, tile_k):
    np.random.seed(42)
    Q = np.random.randn(B, H, T, D).astype(np.float64)
    K = np.random.randn(B, H, T, D).astype(np.float64)
    V = np.random.randn(B, H, T, D).astype(np.float64)

    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, tile_q, tile_k)

    np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8,
                               err_msg=f"Mismatch for {type(mask_obj).__name__}")


# =====================================================================
# Variable-length sequence tests
# =====================================================================

@pytest.mark.parametrize("mask_obj", MASKS_FOR_ATTN,
                         ids=lambda m: type(m).__name__)
def test_variable_length(mask_obj):
    np.random.seed(123)
    B, H, T, D = 3, 2, 20, 16
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)
    lens = np.array([5, 15, 20])

    ref = naive_attention(Q, K, V, mask_obj, lens=lens)
    tiled = tiled_attention(Q, K, V, mask_obj, 8, 8, lens=lens)

    np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8)


@pytest.mark.parametrize("mask_obj", MASKS_FOR_ATTN,
                         ids=lambda m: type(m).__name__)
def test_variable_length_tricky(mask_obj):
    """lens=1 (single token visible) and lens > T."""
    np.random.seed(99)
    B, H, T, D = 2, 1, 10, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)
    lens = np.array([1, T + 5])

    ref = naive_attention(Q, K, V, mask_obj, lens=lens)
    tiled = tiled_attention(Q, K, V, mask_obj, 4, 4, lens=lens)

    np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8)


def test_zeros_at_masked_positions():
    """Output must be exactly zero at positions beyond sequence length."""
    np.random.seed(55)
    B, H, T, D = 2, 1, 10, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)
    lens = np.array([3, 7])

    for mask_obj in MASKS_FOR_ATTN:
        result = tiled_attention(Q, K, V, mask_obj, 4, 4, lens=lens)
        for b in range(B):
            sl = int(lens[b])
            assert np.allclose(result[b, :, sl:, :], 0.0), (
                f"{type(mask_obj).__name__}: non-zero output at "
                f"positions >= seq_len={sl} in batch {b}"
            )


def test_variable_length_minimal():
    """All batches have lens=1."""
    np.random.seed(88)
    B, H, T, D = 2, 1, 10, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)
    lens = np.array([1, 1])

    for mask_obj in MASKS_FOR_ATTN:
        ref = naive_attention(Q, K, V, mask_obj, lens=lens)
        tiled = tiled_attention(Q, K, V, mask_obj, 4, 4, lens=lens)
        np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8)
        # Only position 0 should have non-zero output
        for b in range(B):
            assert np.allclose(ref[b, :, 1:, :], 0.0)


# =====================================================================
# Edge cases
# =====================================================================

def test_single_token():
    """T=1: minimal sequence length."""
    np.random.seed(0)
    Q = np.random.randn(1, 1, 1, 16)
    K = np.random.randn(1, 1, 1, 16)
    V = np.random.randn(1, 1, 1, 16)

    for mask_obj in MASKS_FOR_ATTN:
        ref = naive_attention(Q, K, V, mask_obj)
        tiled = tiled_attention(Q, K, V, mask_obj, 4, 4)
        np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8,
                                   err_msg=type(mask_obj).__name__)


def test_tile_larger_than_seq():
    """Tile sizes exceed sequence length."""
    np.random.seed(7)
    Q = np.random.randn(1, 1, 5, 16)
    K = np.random.randn(1, 1, 5, 16)
    V = np.random.randn(1, 1, 5, 16)

    for mask_obj in MASKS_FOR_ATTN:
        ref = naive_attention(Q, K, V, mask_obj)
        tiled = tiled_attention(Q, K, V, mask_obj, 32, 32)
        np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8,
                                   err_msg=type(mask_obj).__name__)


def test_non_square_tiles():
    """tile_q != tile_k with non-divisible T."""
    np.random.seed(11)
    B, H, T, D = 1, 2, 37, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)

    for mask_obj in MASKS_FOR_ATTN:
        ref = naive_attention(Q, K, V, mask_obj)
        tiled = tiled_attention(Q, K, V, mask_obj, 7, 13)
        np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8,
                                   err_msg=type(mask_obj).__name__)


# =====================================================================
# Numerical stability
# =====================================================================

def test_numerical_stability_large_values():
    """Large Q/K values that could cause overflow without stable softmax."""
    np.random.seed(33)
    B, H, T, D = 1, 1, 8, 4
    Q = np.random.randn(B, H, T, D) * 100
    K = np.random.randn(B, H, T, D) * 100
    V = np.random.randn(B, H, T, D)

    mask_obj = FullMask()
    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, 4, 4)

    assert np.all(np.isfinite(tiled)), "Tiled attention produced non-finite values"
    assert np.all(np.isfinite(ref)), "Naive attention produced non-finite values"
    np.testing.assert_allclose(tiled, ref, atol=1e-8, rtol=1e-6)


def test_numerical_stability_causal_large():
    """Large values with causal mask."""
    np.random.seed(44)
    B, H, T, D = 1, 1, 12, 4
    Q = np.random.randn(B, H, T, D) * 50
    K = np.random.randn(B, H, T, D) * 50
    V = np.random.randn(B, H, T, D)

    mask_obj = CausalMask()
    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, 4, 4)

    assert np.all(np.isfinite(tiled))
    np.testing.assert_allclose(tiled, ref, atol=1e-8, rtol=1e-6)


# =====================================================================
# Identity mask test (analytical verification)
# =====================================================================

def test_identity_mask():
    """
    SlidingWindow(0,0) is an identity mask: each query only attends to itself.
    The softmax is trivially 1, so the output must equal V.
    """
    np.random.seed(42)
    B, H, T, D = 2, 2, 100, 16
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)

    mask_obj = SlidingWindowMask(0, 0)
    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, 16, 16)

    np.testing.assert_allclose(tiled, V, atol=1e-12, rtol=1e-10)
    np.testing.assert_allclose(ref, V, atol=1e-12, rtol=1e-10)


# =====================================================================
# Full mask with uniform V: output should be mean of V
# =====================================================================

def test_full_mask_uniform_q_k():
    """
    When Q and K produce uniform scores and FullMask is used,
    softmax weights are uniform, so output is mean of V rows.
    """
    np.random.seed(77)
    B, H, T, D = 1, 1, 8, 4
    Q = np.ones((B, H, T, D))
    K = np.ones((B, H, T, D))
    V = np.random.randn(B, H, T, D)

    mask_obj = FullMask()
    result = tiled_attention(Q, K, V, mask_obj, 4, 4)

    # All scores are equal, so softmax gives uniform 1/T weights
    expected = np.mean(V, axis=2, keepdims=True).repeat(T, axis=2)
    np.testing.assert_allclose(result, expected, atol=1e-10, rtol=1e-8)


# =====================================================================
# Cross-mask tiled vs naive with larger sequences and variable tiles
# =====================================================================

@pytest.mark.parametrize("mask_obj", [
    SlidingWindowMask(3, 3),
    SlidingWindowMask(10, 0),
    SlidingWindowMask(0, 10),
    ChunkwiseMask(7, 2),
    ChunkwiseMask(16, 0),
    PrefixLMMask(5),
    PrefixLMMask(50),
], ids=lambda m: str(m.__class__.__name__) + str(m.args))
def test_tiled_vs_naive_varied_masks(mask_obj):
    np.random.seed(200)
    B, H, T, D = 2, 2, 50, 16
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)

    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, 8, 8)

    np.testing.assert_allclose(tiled, ref, atol=1e-10, rtol=1e-8)


# =====================================================================
# Verify analytical k_full_range matches brute-force
# =====================================================================

@pytest.mark.parametrize("mask_obj", [
    FullMask(),
    CausalMask(),
    SlidingWindowMask(4, 2),
    ChunkwiseMask(5, 1),
    PrefixLMMask(8),
], ids=lambda m: type(m).__name__)
@pytest.mark.parametrize("tile_q", [4, 8, 16])
def test_k_full_range_is_subset_of_intersection(mask_obj, tile_q):
    """k_full_range_for_q_tile must return a range that is fully unmasked
    AND is a subset of the intersection of per-query k_ranges."""
    max_pos = 48
    q_idx = np.arange(max_pos)
    k_idx = np.arange(max_pos)
    full_mask = mask_obj.mask(q_idx, k_idx, max_pos)

    for qb in range(0, max_pos, tile_q):
        q_end = min(qb + tile_q, max_pos)
        k_start, k_end = mask_obj.k_full_range_for_q_tile(qb, tile_q, max_pos)

        if k_end <= k_start:
            continue

        k_end_clipped = min(k_end, max_pos)
        if k_end_clipped <= k_start:
            continue

        tile = full_mask[qb:q_end, k_start:k_end_clipped]
        assert np.all(tile), (
            f"{type(mask_obj).__name__}: k_full_range [{k_start},{k_end}) "
            f"for q tile [{qb},{q_end}) has masked entries"
        )


# =====================================================================
# Output shape and type checks
# =====================================================================

def test_output_shape_and_type():
    np.random.seed(0)
    B, H, T, D = 2, 3, 10, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)

    mask_obj = CausalMask()
    ref = naive_attention(Q, K, V, mask_obj)
    tiled = tiled_attention(Q, K, V, mask_obj, 4, 4)

    assert ref.shape == (B, H, T, D), f"Naive shape: {ref.shape}"
    assert tiled.shape == (B, H, T, D), f"Tiled shape: {tiled.shape}"
    assert ref.dtype == np.float64, f"Naive dtype: {ref.dtype}"
    assert tiled.dtype == np.float64, f"Tiled dtype: {tiled.dtype}"


# =====================================================================
# Batch independence
# =====================================================================

def test_batch_independence():
    """Each batch element should be independent: result[b] depends only on input[b]."""
    np.random.seed(22)
    B, H, T, D = 3, 1, 12, 8
    Q = np.random.randn(B, H, T, D)
    K = np.random.randn(B, H, T, D)
    V = np.random.randn(B, H, T, D)
    lens = np.array([5, 10, 12])

    mask_obj = CausalMask()
    full_result = tiled_attention(Q, K, V, mask_obj, 4, 4, lens=lens)

    for b in range(B):
        single_q = Q[b:b+1]
        single_k = K[b:b+1]
        single_v = V[b:b+1]
        single_lens = lens[b:b+1]

        single_result = tiled_attention(single_q, single_k, single_v,
                                        mask_obj, 4, 4, lens=single_lens)
        np.testing.assert_allclose(
            full_result[b:b+1], single_result, atol=1e-12,
            err_msg=f"Batch {b} not independent"
        )
