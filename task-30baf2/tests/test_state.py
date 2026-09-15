
import sys
sys.path.insert(0, '/app')

import json
import os
import sqlite3
import numpy as np
import pytest

from mask_base import FullMask
from masks import CausalMask, SlidingWindowMask, ChunkwiseMask, PrefixLMMask
from reference import naive_masked_attention
from engine import tiled_attention
from compound_masks import IntersectionMask, LocalGlobalMask


# ============================================================
# Base mask verification (sanity checks on given infrastructure)
# ============================================================

base_verify_masks = [
    FullMask(),
    CausalMask(),
    SlidingWindowMask(10, 4),
    SlidingWindowMask(1, 0),
    SlidingWindowMask(0, 0),
    ChunkwiseMask(8, 2),
    ChunkwiseMask(16, 0),
    ChunkwiseMask(1, 5),
    PrefixLMMask(10),
    PrefixLMMask(1),
]


@pytest.mark.parametrize("mask_obj", base_verify_masks, ids=str)
@pytest.mark.parametrize("seq_len", [1, 16, 32, 64, 128])
def test_base_mask_verify(mask_obj, seq_len):
    """Verify base mask range functions are consistent."""
    mask_obj.verify(seq_len)


# ============================================================
# Engine correctness tests
# ============================================================

engine_masks = [
    FullMask(),
    CausalMask(),
    SlidingWindowMask(10, 4),
    SlidingWindowMask(2, 0),
    ChunkwiseMask(8, 2),
    ChunkwiseMask(4, 0),
    PrefixLMMask(10),
    PrefixLMMask(3),
]


@pytest.mark.parametrize("mask_obj", engine_masks, ids=str)
@pytest.mark.parametrize("config", [
    (1, 1, 1, 8, 8, 8),
    (2, 2, 16, 16, 8, 8),
    (1, 1, 33, 16, 16, 16),
    (3, 2, 64, 8, 8, 16),
    (1, 1, 7, 32, 32, 32),
    (2, 1, 48, 16, 16, 8),
], ids=lambda c: f"B{c[0]}_H{c[1]}_T{c[2]}_D{c[3]}_tq{c[4]}_tk{c[5]}")
def test_tiled_vs_naive(mask_obj, config):
    """Verify tiled attention matches naive reference."""
    B, H, T, D, tile_q, tile_k = config
    np.random.seed(42)
    q = np.random.randn(B, H, T, D).astype(np.float64)
    k_arr = np.random.randn(B, H, T, D).astype(np.float64)
    v = np.random.randn(B, H, T, D).astype(np.float64)

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=tile_q, tile_k=tile_k
    )

    np.testing.assert_allclose(
        tiled_out, ref_out, atol=1e-10, rtol=1e-8,
        err_msg=f"Output mismatch for {mask_obj}"
    )

    valid = np.isfinite(ref_lse)
    if np.any(valid):
        np.testing.assert_allclose(
            tiled_lse[valid], ref_lse[valid], atol=1e-10, rtol=1e-8,
            err_msg=f"LSE mismatch for {mask_obj}"
        )

    inf_mask = np.isinf(ref_lse) & (ref_lse < 0)
    if np.any(inf_mask):
        assert np.all(np.isinf(tiled_lse[inf_mask]) & (tiled_lse[inf_mask] < 0)), (
            f"LSE should be -inf where reference is -inf for {mask_obj}"
        )


@pytest.mark.parametrize("mask_obj", [
    FullMask(),
    CausalMask(),
    SlidingWindowMask(5, 3),
    ChunkwiseMask(4, 1),
    PrefixLMMask(8),
], ids=str)
def test_tiled_variable_length(mask_obj):
    """Test with variable-length sequences."""
    np.random.seed(123)
    B, H, T, D = 4, 2, 32, 16
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    lens = np.array([5, 1, 32, 20])

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj, lens=lens)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, lens=lens, tile_q=8, tile_k=8
    )

    np.testing.assert_allclose(
        tiled_out, ref_out, atol=1e-10, rtol=1e-8,
        err_msg=f"Output mismatch for {mask_obj} with variable lengths"
    )

    valid = np.isfinite(ref_lse)
    if np.any(valid):
        np.testing.assert_allclose(
            tiled_lse[valid], ref_lse[valid], atol=1e-10, rtol=1e-8,
            err_msg=f"LSE mismatch for {mask_obj} with variable lengths"
        )

    for b in range(B):
        sl = min(int(lens[b]), T)
        if sl < T:
            np.testing.assert_array_equal(
                tiled_out[b, :, sl:, :], 0.0,
                err_msg=(
                    f"Non-zero output beyond seq_len for batch {b}, "
                    f"mask {mask_obj}"
                )
            )


@pytest.mark.parametrize("mask_obj", engine_masks[:4], ids=str)
def test_tiled_large_sequence(mask_obj):
    """Test with larger sequence to stress tile boundaries."""
    np.random.seed(99)
    B, H, T, D = 1, 1, 129, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=32, tile_k=16
    )

    np.testing.assert_allclose(tiled_out, ref_out, atol=1e-10, rtol=1e-8)

    valid = np.isfinite(ref_lse)
    if np.any(valid):
        np.testing.assert_allclose(
            tiled_lse[valid], ref_lse[valid], atol=1e-10, rtol=1e-8
        )


def test_engine_returns_tuple():
    """Verify engine returns (output, lse) tuple with correct shapes."""
    np.random.seed(42)
    q = np.random.randn(2, 3, 8, 16)
    k_arr = np.random.randn(2, 3, 8, 16)
    v = np.random.randn(2, 3, 8, 16)

    result = tiled_attention(q, k_arr, v, FullMask(), tile_q=4, tile_k=4)
    assert isinstance(result, tuple), "tiled_attention must return a tuple"
    assert len(result) == 2, "tiled_attention must return (output, lse)"
    output, lse = result
    assert output.shape == (2, 3, 8, 16), f"Output shape wrong: {output.shape}"
    assert lse.shape == (2, 3, 8), f"LSE shape wrong: {lse.shape}"


def test_engine_no_nan():
    """Verify engine output contains no NaN values."""
    np.random.seed(42)
    q = np.random.randn(2, 2, 16, 8).astype(np.float64)
    k_arr = np.random.randn(2, 2, 16, 8).astype(np.float64)
    v = np.random.randn(2, 2, 16, 8).astype(np.float64)

    for mask_obj in [FullMask(), CausalMask(), SlidingWindowMask(3, 1),
                     ChunkwiseMask(4, 1), PrefixLMMask(5)]:
        output, lse = tiled_attention(
            q, k_arr, v, mask_obj, tile_q=4, tile_k=4
        )
        assert not np.any(np.isnan(output)), (
            f"Output contains NaN for {mask_obj}"
        )
        assert not np.any(np.isnan(lse)), (
            f"LSE contains NaN for {mask_obj}"
        )


@pytest.mark.parametrize("tile_q,tile_k", [
    (4, 4), (8, 4), (4, 8), (16, 16), (7, 11)
])
def test_various_tile_sizes(tile_q, tile_k):
    """Test with various tile sizes including non-power-of-2."""
    np.random.seed(42)
    B, H, T, D = 2, 1, 20, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    mask_obj = CausalMask()

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=tile_q, tile_k=tile_k
    )

    np.testing.assert_allclose(tiled_out, ref_out, atol=1e-10, rtol=1e-8)

    valid = np.isfinite(ref_lse)
    if np.any(valid):
        np.testing.assert_allclose(
            tiled_lse[valid], ref_lse[valid], atol=1e-10, rtol=1e-8
        )


def test_sliding_window_self_attention_only():
    """SlidingWindowMask(0, 0) = each position only attends to itself."""
    np.random.seed(42)
    B, H, T, D = 1, 1, 8, 4
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    mask_obj = SlidingWindowMask(0, 0)

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=4, tile_k=4
    )

    np.testing.assert_allclose(tiled_out, ref_out, atol=1e-10, rtol=1e-8)

    for t in range(T):
        np.testing.assert_allclose(
            tiled_out[0, 0, t], v[0, 0, t], atol=1e-10
        )


def test_chunkwise_no_back_context():
    """ChunkwiseMask with back_chunks=0: block-diagonal pattern."""
    np.random.seed(42)
    B, H, T, D = 1, 1, 12, 4
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    mask_obj = ChunkwiseMask(4, 0)

    ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
    tiled_out, tiled_lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=8, tile_k=4
    )

    np.testing.assert_allclose(tiled_out, ref_out, atol=1e-10, rtol=1e-8)

    mask = mask_obj.make_mask(12)
    assert not mask[4, 0], "chunk 1 should not attend to chunk 0"
    assert mask[4, 4], "chunk 1 should attend to chunk 1"


# ============================================================
# Loop-splitting effectiveness tests
# ============================================================

def test_loop_splitting_reduces_mask_calls():
    """Verify loop-splitting skips mask computation for fully-unmasked tiles."""
    np.random.seed(42)
    B, H, T, D = 1, 1, 64, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    tile_q, tile_k = 16, 16

    n_q_tiles = (T + tile_q - 1) // tile_q
    n_k_tiles = (T + tile_k - 1) // tile_k
    total_pairs = n_q_tiles * n_k_tiles

    for mask_cls in [FullMask, CausalMask]:
        mask_obj = mask_cls()
        call_count = [0]
        original_mask = mask_obj.mask

        def counting_mask(*args, _orig=original_mask, _cnt=call_count, **kw):
            _cnt[0] += 1
            return _orig(*args, **kw)

        mask_obj.mask = counting_mask

        out, lse = tiled_attention(
            q, k_arr, v, mask_obj, tile_q=tile_q, tile_k=tile_k
        )

        ref_mask = mask_cls()
        ref_out, ref_lse = naive_masked_attention(q, k_arr, v, ref_mask)
        np.testing.assert_allclose(out, ref_out, atol=1e-10, rtol=1e-8)

        assert call_count[0] < total_pairs, (
            f"{mask_cls.__name__}: mask() called {call_count[0]} times, "
            f"expected fewer than {total_pairs} (loop splitting not effective)"
        )


def test_full_mask_zero_mask_calls():
    """FullMask should never call mask() since all tiles are fully unmasked."""
    np.random.seed(42)
    B, H, T, D = 1, 1, 32, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)

    mask_obj = FullMask()
    call_count = [0]
    original_mask = mask_obj.mask

    def counting_mask(*args, _orig=original_mask, _cnt=call_count, **kw):
        _cnt[0] += 1
        return _orig(*args, **kw)

    mask_obj.mask = counting_mask

    out, lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=8, tile_k=8
    )

    ref_out, _ = naive_masked_attention(q, k_arr, v, FullMask())
    np.testing.assert_allclose(out, ref_out, atol=1e-10, rtol=1e-8)

    assert call_count[0] == 0, (
        f"FullMask: mask() called {call_count[0]} times, expected 0"
    )


# ============================================================
# IntersectionMask tests
# ============================================================

intersection_masks = [
    IntersectionMask(CausalMask(), SlidingWindowMask(10, 0)),
    IntersectionMask(CausalMask(), SlidingWindowMask(5, 5)),
    IntersectionMask(CausalMask(), ChunkwiseMask(8, 2)),
    IntersectionMask(FullMask(), CausalMask()),
    IntersectionMask(SlidingWindowMask(10, 4), SlidingWindowMask(6, 2)),
    IntersectionMask(CausalMask(), PrefixLMMask(10)),
    IntersectionMask(ChunkwiseMask(8, 1), ChunkwiseMask(16, 0)),
    IntersectionMask(SlidingWindowMask(3, 3), ChunkwiseMask(4, 1)),
    IntersectionMask(PrefixLMMask(5), SlidingWindowMask(8, 8)),
    IntersectionMask(CausalMask(), FullMask()),
]


@pytest.mark.parametrize("mask_obj", intersection_masks, ids=str)
@pytest.mark.parametrize("seq_len", [1, 16, 32, 64, 128])
def test_intersection_mask_verify(mask_obj, seq_len):
    """Verify IntersectionMask range functions are consistent."""
    mask_obj.verify(seq_len)


def test_intersection_mask_pattern():
    """IntersectionMask(Causal, SlidingWindow(3,0)) = causal with lookback 3."""
    m = IntersectionMask(CausalMask(), SlidingWindowMask(3, 0))
    mask = m.make_mask(8)
    expected = np.zeros((8, 8), dtype=bool)
    for q in range(8):
        for k in range(8):
            expected[q, k] = (q >= k) and (k >= q - 3)
    np.testing.assert_array_equal(mask, expected)


def test_intersection_full_and_causal():
    """Intersection(Full, Causal) should equal Causal."""
    m_int = IntersectionMask(FullMask(), CausalMask())
    m_causal = CausalMask()
    for seq_len in [8, 32, 64]:
        np.testing.assert_array_equal(
            m_int.make_mask(seq_len),
            m_causal.make_mask(seq_len)
        )


def test_intersection_mask_k_full_range():
    """k_full_range for IntersectionMask is intersection of sub-ranges."""
    m = IntersectionMask(CausalMask(), SlidingWindowMask(10, 4))
    # CausalMask k_full_range for q_tile [32, 40): [0, 33)
    # SlidingWindowMask(10,4) k_full_range: [29, 37)
    # Intersection: [29, 33)
    ks, ke = m.k_full_range_for_q_tile(32, 8, 128)
    assert int(ks) == 29
    assert int(ke) == 33


def test_intersection_mask_k_full_range_empty():
    """k_full_range can be empty when sub-ranges don't overlap."""
    m = IntersectionMask(SlidingWindowMask(2, 0), SlidingWindowMask(0, 2))
    # SW(2,0): for q_tile [10, 18), k_full = [max(0,17-2), min(10+0+1,128)] = [15, 11) -> empty
    # SW(0,2): for q_tile [10, 18), k_full = [max(0,17-0), min(10+2+1,128)] = [17, 13) -> empty
    # Both are empty, intersection is empty
    ks, ke = m.k_full_range_for_q_tile(10, 8, 128)
    assert int(ke) <= int(ks), "Expected empty range"


def test_intersection_mask_with_engine():
    """Verify IntersectionMask works correctly with tiled engine."""
    np.random.seed(42)
    B, H, T, D = 2, 2, 32, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)

    for mask_obj in [
        IntersectionMask(CausalMask(), SlidingWindowMask(10, 0)),
        IntersectionMask(CausalMask(), ChunkwiseMask(8, 2)),
        IntersectionMask(SlidingWindowMask(5, 5), PrefixLMMask(4)),
    ]:
        ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
        tiled_out, tiled_lse = tiled_attention(
            q, k_arr, v, mask_obj, tile_q=8, tile_k=8
        )
        np.testing.assert_allclose(
            tiled_out, ref_out, atol=1e-10, rtol=1e-8,
            err_msg=f"Engine mismatch for {mask_obj}"
        )


# ============================================================
# LocalGlobalMask tests
# ============================================================

local_global_masks = [
    LocalGlobalMask(5, 3),
    LocalGlobalMask(10, 0),
    LocalGlobalMask(0, 5),
    LocalGlobalMask(3, 1),
    LocalGlobalMask(1, 1),
    LocalGlobalMask(8, 8),
    LocalGlobalMask(2, 10),
    LocalGlobalMask(15, 2),
]


@pytest.mark.parametrize("mask_obj", local_global_masks, ids=str)
@pytest.mark.parametrize("seq_len", [1, 16, 32, 64, 128])
def test_local_global_mask_verify(mask_obj, seq_len):
    """Verify LocalGlobalMask range functions are consistent."""
    mask_obj.verify(seq_len)


def test_local_global_mask_pattern():
    """LocalGlobalMask(2, 3) pattern check."""
    m = LocalGlobalMask(2, 3)
    mask = m.make_mask(8)
    expected = np.zeros((8, 8), dtype=bool)
    for q in range(8):
        for k in range(8):
            expected[q, k] = (abs(q - k) <= 2) or (k < 3)
    np.testing.assert_array_equal(mask, expected)


def test_local_global_mask_pattern_no_global():
    """LocalGlobalMask with n_global=0 is just a symmetric sliding window."""
    m = LocalGlobalMask(3, 0)
    mask = m.make_mask(10)
    sw = SlidingWindowMask(3, 3)
    sw_mask = sw.make_mask(10)
    np.testing.assert_array_equal(mask, sw_mask)


def test_local_global_mask_pattern_no_window():
    """LocalGlobalMask with window_size=0 attends only to global + self."""
    m = LocalGlobalMask(0, 4)
    mask = m.make_mask(8)
    expected = np.zeros((8, 8), dtype=bool)
    for q in range(8):
        for k in range(8):
            expected[q, k] = (q == k) or (k < 4)
    np.testing.assert_array_equal(mask, expected)


def test_local_global_k_range_for_q():
    """k_range_for_q must span from first global to end of local window."""
    m = LocalGlobalMask(2, 3)

    # q=0: local [0,2], global [0,2] -> tight [0, max(2,2)] = [0, 2]
    kmin, kmax = m.k_range_for_q(0, 100)
    assert int(kmin) == 0
    assert int(kmax) == 2

    # q=50: local [48,52], global [0,2] -> tight [0, 52]
    kmin, kmax = m.k_range_for_q(50, 100)
    assert int(kmin) == 0
    assert int(kmax) == 52

    # q=98: local [96,99], global [0,2] -> tight [0, 99]
    kmin, kmax = m.k_range_for_q(98, 100)
    assert int(kmin) == 0
    assert int(kmax) == 99


def test_local_global_k_range_no_global():
    """Without global tokens, k_range is just the local window."""
    m = LocalGlobalMask(5, 0)
    kmin, kmax = m.k_range_for_q(50, 100)
    assert int(kmin) == 45
    assert int(kmax) == 55


def test_local_global_q_range_for_k():
    """q_range_for_k: global tokens attended by all, others by local window."""
    m = LocalGlobalMask(3, 5)

    # k=2 (global): all queries attend -> (0, 99)
    qmin, qmax = m.q_range_for_k(2, 100)
    assert int(qmin) == 0
    assert int(qmax) == 99

    # k=50 (not global): local window only -> (47, 53)
    qmin, qmax = m.q_range_for_k(50, 100)
    assert int(qmin) == 47
    assert int(qmax) == 53


def test_local_global_k_full_range_merged():
    """k_full_range merges global and local when overlapping."""
    m = LocalGlobalMask(5, 3)
    # q_tile [0, 8), seq_len=100
    # local intersection: [max(0, 7-5), min(0+5+1, 100)] = [2, 6)
    # global: [0, 3)
    # Overlapping (3 >= 2): merge -> [0, max(3, 6)) = [0, 6)
    ks, ke = m.k_full_range_for_q_tile(0, 8, 100)
    assert int(ks) == 0
    assert int(ke) == 6


def test_local_global_k_full_range_disjoint():
    """k_full_range returns larger range when global and local are disjoint."""
    m = LocalGlobalMask(2, 3)
    # q_tile [50, 54), seq_len=100
    # local intersection: [max(0, 53-2), min(50+2+1, 100)] = [51, 53)  size=2
    # global: [0, 3)  size=3
    # Disjoint (3 < 51): return larger -> (0, 3)
    ks, ke = m.k_full_range_for_q_tile(50, 4, 100)
    assert int(ks) == 0
    assert int(ke) == 3


def test_local_global_k_full_range_no_global():
    """k_full_range with no global tokens returns local intersection."""
    m = LocalGlobalMask(5, 0)
    # q_tile [10, 18), seq_len=100
    # local: [max(0, 17-5), min(10+5+1, 100)] = [12, 16)
    ks, ke = m.k_full_range_for_q_tile(10, 8, 100)
    assert int(ks) == 12
    assert int(ke) == 16


def test_local_global_k_full_range_wide_tile():
    """k_full_range returns empty local intersection when tile > 2*window+1."""
    m = LocalGlobalMask(2, 0)
    # q_tile [0, 16), tile much wider than window
    # local: [max(0, 15-2), min(0+2+1, 100)] = [13, 3) -> empty
    ks, ke = m.k_full_range_for_q_tile(0, 16, 100)
    # With no global tokens and empty local, range should be empty
    assert int(ke) <= int(ks) or (int(ks) == 0 and int(ke) == 0)


def test_local_global_with_engine():
    """Verify LocalGlobalMask works correctly with tiled engine."""
    np.random.seed(42)
    B, H, T, D = 2, 2, 48, 16
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)

    for mask_obj in [
        LocalGlobalMask(5, 3),
        LocalGlobalMask(10, 0),
        LocalGlobalMask(0, 5),
        LocalGlobalMask(3, 8),
    ]:
        ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
        tiled_out, tiled_lse = tiled_attention(
            q, k_arr, v, mask_obj, tile_q=8, tile_k=8
        )
        np.testing.assert_allclose(
            tiled_out, ref_out, atol=1e-10, rtol=1e-8,
            err_msg=f"Engine mismatch for {mask_obj}"
        )

        valid = np.isfinite(ref_lse)
        if np.any(valid):
            np.testing.assert_allclose(
                tiled_lse[valid], ref_lse[valid], atol=1e-10, rtol=1e-8,
                err_msg=f"LSE mismatch for {mask_obj}"
            )


def test_local_global_loop_splitting():
    """Verify loop-splitting works with LocalGlobalMask."""
    np.random.seed(42)
    B, H, T, D = 1, 1, 64, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    tile_q, tile_k = 8, 8

    n_q_tiles = (T + tile_q - 1) // tile_q
    n_k_tiles = (T + tile_k - 1) // tile_k
    total_pairs = n_q_tiles * n_k_tiles

    mask_obj = LocalGlobalMask(10, 0)
    call_count = [0]
    original_mask = mask_obj.mask

    def counting_mask(*args, _orig=original_mask, _cnt=call_count, **kw):
        _cnt[0] += 1
        return _orig(*args, **kw)

    mask_obj.mask = counting_mask

    out, lse = tiled_attention(
        q, k_arr, v, mask_obj, tile_q=tile_q, tile_k=tile_k
    )

    ref_out, _ = naive_masked_attention(
        q, k_arr, v, LocalGlobalMask(10, 0)
    )
    np.testing.assert_allclose(out, ref_out, atol=1e-10, rtol=1e-8)

    assert call_count[0] < total_pairs, (
        f"LocalGlobalMask: mask() called {call_count[0]} times, "
        f"expected fewer than {total_pairs}"
    )


# ============================================================
# Compound masks with variable length
# ============================================================

def test_compound_masks_variable_length():
    """Compound masks work with variable-length sequences in the engine."""
    np.random.seed(77)
    B, H, T, D = 3, 1, 32, 8
    q = np.random.randn(B, H, T, D)
    k_arr = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)
    lens = np.array([8, 32, 15])

    for mask_obj in [
        IntersectionMask(CausalMask(), SlidingWindowMask(5, 0)),
        LocalGlobalMask(4, 2),
    ]:
        ref_out, ref_lse = naive_masked_attention(
            q, k_arr, v, mask_obj, lens=lens
        )
        tiled_out, tiled_lse = tiled_attention(
            q, k_arr, v, mask_obj, lens=lens, tile_q=8, tile_k=8
        )
        np.testing.assert_allclose(
            tiled_out, ref_out, atol=1e-10, rtol=1e-8,
            err_msg=f"Variable-length mismatch for {mask_obj}"
        )


# ============================================================
# Analysis JSON tests
# ============================================================

def test_analysis_json_exists():
    """analysis.json must exist."""
    assert os.path.exists('/app/analysis.json'), (
        "analysis.json not found"
    )


def test_analysis_json_validates_against_schema():
    """analysis.json must validate against the JSON Schema."""
    import jsonschema
    with open('/app/analysis.json') as f:
        data = json.load(f)
    with open('/app/analysis_schema.json') as f:
        schema = json.load(f)
    jsonschema.validate(data, schema)


def test_analysis_json_structure():
    """analysis.json must have required structure and plausible values."""
    with open('/app/analysis.json') as f:
        data = json.load(f)

    assert 'engine_profiling' in data, "Missing 'engine_profiling' key"
    assert 'memory_profiling' in data, "Missing 'memory_profiling' key"

    ep = data['engine_profiling']
    assert 'per_mask_stats' in ep, "Missing 'per_mask_stats' in engine_profiling"

    required_masks = ['FullMask', 'CausalMask']
    for mask_name in required_masks:
        assert mask_name in ep['per_mask_stats'], (
            f"Missing '{mask_name}' in per_mask_stats"
        )
        stats = ep['per_mask_stats'][mask_name]
        assert 'mask_calls' in stats, f"Missing 'mask_calls' for {mask_name}"
        assert 'time_sec' in stats, f"Missing 'time_sec' for {mask_name}"
        assert isinstance(stats['mask_calls'], int), (
            f"mask_calls must be int for {mask_name}"
        )
        assert isinstance(stats['time_sec'], (int, float)), (
            f"time_sec must be numeric for {mask_name}"
        )
        assert stats['time_sec'] >= 0, (
            f"time_sec must be non-negative for {mask_name}"
        )

    # Loop-splitting validation
    assert ep['per_mask_stats']['FullMask']['mask_calls'] == 0, (
        "FullMask should have 0 mask calls (loop splitting)"
    )
    assert ep['per_mask_stats']['CausalMask']['mask_calls'] > 0, (
        "CausalMask should have some mask calls"
    )

    mp = data['memory_profiling']
    assert 'peak_memory_bytes' in mp, "Missing 'peak_memory_bytes'"
    assert mp['peak_memory_bytes'] > 0, "peak_memory_bytes must be positive"


# ============================================================
# Benchmark database tests
# ============================================================

def test_benchmarks_db_exists():
    """benchmarks.db must exist."""
    assert os.path.exists('/app/benchmarks.db'), (
        "benchmarks.db not found — create it conforming to /app/db_schema.sql"
    )


def test_benchmarks_db_tables():
    """benchmarks.db must have the required tables with correct schema."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.cursor()

    # Check benchmark_runs table
    cursor.execute("PRAGMA table_info(benchmark_runs)")
    cols = {row[1]: row[2] for row in cursor.fetchall()}
    required_br = {
        'mask_type': 'TEXT', 'batch_size': 'INTEGER',
        'num_heads': 'INTEGER', 'seq_len': 'INTEGER',
        'head_dim': 'INTEGER', 'tile_q': 'INTEGER',
        'tile_k': 'INTEGER', 'naive_time_sec': 'REAL',
        'tiled_time_sec': 'REAL', 'speedup': 'REAL',
        'max_output_error': 'REAL', 'max_lse_error': 'REAL',
        'correct': 'INTEGER',
    }
    for col, dtype in required_br.items():
        assert col in cols, f"benchmark_runs missing column: {col}"
        assert cols[col] == dtype, (
            f"benchmark_runs.{col} type is {cols[col]}, expected {dtype}"
        )

    # Check mask_call_counts table
    cursor.execute("PRAGMA table_info(mask_call_counts)")
    cols = {row[1]: row[2] for row in cursor.fetchall()}
    required_mc = {
        'mask_type': 'TEXT', 'seq_len': 'INTEGER',
        'tile_q': 'INTEGER', 'tile_k': 'INTEGER',
        'total_tile_pairs': 'INTEGER',
        'actual_mask_calls': 'INTEGER',
        'calls_saved': 'INTEGER',
    }
    for col, dtype in required_mc.items():
        assert col in cols, f"mask_call_counts missing column: {col}"
        assert cols[col] == dtype, (
            f"mask_call_counts.{col} type is {cols[col]}, expected {dtype}"
        )

    conn.close()


def test_benchmarks_db_data_quantity():
    """Must have sufficient benchmark data."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM benchmark_runs")
    count = cursor.fetchone()[0]
    assert count >= 15, (
        f"benchmark_runs has {count} rows, need >= 15 (5+ masks x 3+ configs)"
    )

    cursor.execute("SELECT COUNT(DISTINCT mask_type) FROM benchmark_runs")
    n_masks = cursor.fetchone()[0]
    assert n_masks >= 5, (
        f"Only {n_masks} distinct mask types in benchmark_runs, need >= 5"
    )

    cursor.execute("SELECT COUNT(*) FROM mask_call_counts")
    count = cursor.fetchone()[0]
    assert count >= 5, (
        f"mask_call_counts has {count} rows, need >= 5"
    )

    conn.close()


def test_benchmarks_db_correctness():
    """All benchmark runs must be marked correct."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM benchmark_runs WHERE correct = 0")
    incorrect = cursor.fetchone()[0]
    assert incorrect == 0, f"{incorrect} benchmark runs are marked incorrect"

    cursor.execute("SELECT MAX(max_output_error) FROM benchmark_runs")
    max_err = cursor.fetchone()[0]
    assert max_err <= 1e-10, (
        f"Max output error across benchmarks is {max_err}, should be <= 1e-10"
    )

    conn.close()


def test_benchmarks_db_mask_call_efficiency():
    """FullMask must have 0 mask calls in the database."""
    conn = sqlite3.connect('/app/benchmarks.db')
    cursor = conn.cursor()

    cursor.execute(
        "SELECT actual_mask_calls FROM mask_call_counts "
        "WHERE mask_type = 'FullMask'"
    )
    rows = cursor.fetchall()
    assert len(rows) > 0, "No FullMask entries in mask_call_counts"
    for row in rows:
        assert row[0] == 0, (
            f"FullMask should have 0 mask calls, got {row[0]}"
        )

    # CausalMask should have saved some calls
    cursor.execute(
        "SELECT actual_mask_calls, total_tile_pairs FROM mask_call_counts "
        "WHERE mask_type = 'CausalMask'"
    )
    rows = cursor.fetchall()
    assert len(rows) > 0, "No CausalMask entries in mask_call_counts"
    for calls, total in rows:
        assert calls < total, (
            f"CausalMask: {calls} mask calls should be < {total} total pairs"
        )

    conn.close()
