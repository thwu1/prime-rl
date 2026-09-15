"""
FlashMLA FP8 KV Cache Quantization and Sparse MLA Attention Engine

Complete implementation of the core numerical routines from DeepSeek's FlashMLA library.
"""
import numpy as np
from typing import Tuple


def fp8_e4m3_representable_values() -> np.ndarray:
    """Return a sorted array of ALL unique finite values representable in FP8 E4M3FN format."""
    values = set()
    values.add(0.0)
    # Subnormals: e=0, m=1..7 -> value = m * 2^(1 - bias - mantissa_bits) = m * 2^(-9)
    for m in range(1, 8):
        values.add(m * 2.0 ** (-9))
    # Normals: e=1..14, m=0..7 -> value = (1 + m/8) * 2^(e - bias) = (8+m) * 2^(e-10)
    for e in range(1, 15):
        for m in range(8):
            values.add((8 + m) * 2.0 ** (e - 10))
    # Max exponent normals: e=15, m=0..6 (m=7 is NaN in E4M3FN)
    for m in range(7):
        values.add((8 + m) * 2.0 ** 5)
    # Add negative counterparts
    neg_values = {-v for v in values if v != 0.0}
    all_values = sorted(values | neg_values)
    return np.array(all_values)


def fp8_e4m3_quantize(x: np.ndarray) -> np.ndarray:
    """Quantize float values to nearest FP8 E4M3FN representable value."""
    rep = fp8_e4m3_representable_values()
    x_clamped = np.clip(x, -448.0, 448.0)
    x_flat = x_clamped.ravel()
    # Use binary search for efficient nearest-value lookup
    idx_right = np.searchsorted(rep, x_flat)
    idx_right = np.clip(idx_right, 0, len(rep) - 1)
    idx_left = np.clip(idx_right - 1, 0, len(rep) - 1)
    diff_left = np.abs(x_flat - rep[idx_left])
    diff_right = np.abs(x_flat - rep[idx_right])
    best_idx = np.where(diff_left <= diff_right, idx_left, idx_right)
    return rep[best_idx].reshape(x.shape)


def quantize_kv_cache(
    kv: np.ndarray,
    d_nope: int,
    tile_size: int = 128,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Quantize KV cache using FlashMLA's tiled FP8 format with UE8M0 scale factors."""
    num_tokens, d_total = kv.shape
    d_rope = d_total - d_nope
    nope = kv[:, :d_nope]
    rope = kv[:, d_nope:].copy()

    num_tiles = d_nope // tile_size
    scale_factors = np.zeros((num_tokens, num_tiles))
    quantized_nope = np.zeros((num_tokens, d_nope))

    for t in range(num_tokens):
        for ti in range(num_tiles):
            s = ti * tile_size
            e = s + tile_size
            tile = nope[t, s:e]

            abs_max = np.max(np.abs(tile))
            # FlashMLA convention: scale_inv = max(abs_max / 448.0, 1e-4)
            # then round to power of 2 via 2^ceil(log2(scale_inv))
            raw_scale_inv = abs_max / 448.0
            raw_scale_inv = max(raw_scale_inv, 1e-4)
            log2_scale = np.ceil(np.log2(raw_scale_inv))
            scale = 2.0 ** log2_scale

            scale_factors[t, ti] = scale
            quantized_nope[t, s:e] = fp8_e4m3_quantize(tile / scale)

    return quantized_nope, scale_factors, rope


def dequantize_kv_cache(
    quantized_nope: np.ndarray,
    scale_factors: np.ndarray,
    rope: np.ndarray,
    tile_size: int = 128,
) -> np.ndarray:
    """Dequantize KV cache from FP8 format back to full precision."""
    num_tokens, d_nope = quantized_nope.shape
    num_tiles = d_nope // tile_size
    deq = np.zeros_like(quantized_nope)

    for t in range(num_tokens):
        for ti in range(num_tiles):
            s = ti * tile_size
            e = s + tile_size
            deq[t, s:e] = quantized_nope[t, s:e] * scale_factors[t, ti]

    return np.concatenate([deq, rope], axis=-1)


def build_block_table(
    seq_lens: np.ndarray,
    block_size: int,
) -> Tuple[np.ndarray, int]:
    """Build a block table for paged KV cache."""
    batch = len(seq_lens)
    blocks_per_seq = np.ceil(
        np.asarray(seq_lens, dtype=np.float64) / block_size
    ).astype(int)
    max_blocks = int(np.max(blocks_per_seq))
    block_table = np.full((batch, max_blocks), -1, dtype=np.int64)

    phys_block = 0
    for b in range(batch):
        for i in range(blocks_per_seq[b]):
            block_table[b, i] = phys_block
            phys_block += 1

    return block_table, phys_block


def sparse_mla_attention(
    q: np.ndarray,
    blocked_kv: np.ndarray,
    block_table: np.ndarray,
    sparse_indices: np.ndarray,
    seq_lens: np.ndarray,
    sm_scale: float,
    d_v: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute sparse MLA attention using block-indexed KV cache."""
    batch, num_heads, d_qk = q.shape
    topk = sparse_indices.shape[1]
    block_size = blocked_kv.shape[1]

    output = np.zeros((batch, num_heads, d_v))
    lse = np.full((batch, num_heads), -np.inf)

    for b in range(batch):
        # Gather KV tokens from paged cache
        gathered = np.zeros((topk, d_qk))
        valid = np.ones(topk, dtype=bool)

        for k in range(topk):
            abs_idx = int(sparse_indices[b, k])
            if abs_idx < 0:
                valid[k] = False
                continue
            block_id = abs_idx // block_size
            offset = abs_idx % block_size
            phys_block = int(block_table[b, block_id])
            gathered[k] = blocked_kv[phys_block, offset]

        # Compute attention scores: [num_heads, topk]
        scores = np.einsum("hd,kd->hk", q[b], gathered) * sm_scale

        # Mask invalid positions
        scores[:, ~valid] = -np.inf

        # Numerically stable softmax via log-sum-exp trick
        max_s = np.max(scores, axis=-1, keepdims=True)  # [num_heads, 1]
        # Guard against all-masked case (max = -inf)
        max_s = np.where(np.isinf(max_s) & (max_s < 0), 0.0, max_s)

        exp_s = np.exp(scores - max_s)  # [num_heads, topk]
        exp_s[:, ~valid] = 0.0
        sum_exp = np.sum(exp_s, axis=-1, keepdims=True)  # [num_heads, 1]

        # LSE = log(sum(exp(scores))) = max + log(sum(exp(scores - max)))
        lse[b] = max_s.squeeze(-1) + np.log(
            np.maximum(sum_exp.squeeze(-1), 1e-300)
        )

        # Attention weights and output
        attn_weights = exp_s / np.maximum(sum_exp, 1e-300)  # [num_heads, topk]
        output[b] = np.einsum(
            "hk,kd->hd", attn_weights, gathered[:, :d_v]
        )  # [num_heads, d_v]

    return output, lse


def merge_attention_outputs(
    out1: np.ndarray,
    lse1: np.ndarray,
    out2: np.ndarray,
    lse2: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Merge two attention outputs using the log-sum-exp trick."""
    max_lse = np.maximum(lse1, lse2)

    # Compute weights with numerical stability; handle -inf LSE (empty scope)
    exp1 = np.where(
        np.isinf(lse1) & (lse1 < 0), 0.0, np.exp(lse1 - max_lse)
    )
    exp2 = np.where(
        np.isinf(lse2) & (lse2 < 0), 0.0, np.exp(lse2 - max_lse)
    )

    sum_exp = np.maximum(exp1 + exp2, 1e-300)

    w1 = (exp1 / sum_exp)[..., np.newaxis]  # [..., 1] for broadcasting over d_v
    w2 = (exp2 / sum_exp)[..., np.newaxis]

    merged_out = w1 * out1 + w2 * out2
    merged_lse = max_lse + np.log(np.maximum(exp1 + exp2, 1e-300))

    return merged_out, merged_lse
