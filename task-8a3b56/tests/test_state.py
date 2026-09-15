
"""Tests for the NF4 quantization library."""

import sys
import math

sys.path.insert(0, "/app")

import pytest
import torch

from quantlib.core import (
    QuantState,
    create_nf4_map,
    create_fp4_map,
    quantize_4bit,
    dequantize_4bit,
    compute_memory_bits_per_param,
)


# ---------------------------------------------------------------------------
# NF4 Map Tests
# ---------------------------------------------------------------------------

class TestNF4Map:
    def test_length(self):
        """NF4 codebook must have exactly 16 entries (4 bits)."""
        m = create_nf4_map()
        assert m.shape == (16,), f"Expected shape (16,), got {m.shape}"

    def test_is_tensor(self):
        m = create_nf4_map()
        assert isinstance(m, torch.Tensor)

    def test_sorted(self):
        """Codebook values must be in ascending order."""
        m = create_nf4_map()
        for i in range(len(m) - 1):
            assert m[i].item() <= m[i + 1].item(), (
                f"Not sorted at index {i}: {m[i].item()} > {m[i+1].item()}"
            )

    def test_range_min(self):
        m = create_nf4_map()
        assert abs(m.min().item() - (-1.0)) < 1e-6, (
            f"Min should be -1.0, got {m.min().item()}"
        )

    def test_range_max(self):
        m = create_nf4_map()
        assert abs(m.max().item() - 1.0) < 1e-6, (
            f"Max should be 1.0, got {m.max().item()}"
        )

    def test_unique_count(self):
        """All 16 NF4 values must be distinct."""
        m = create_nf4_map()
        unique = torch.unique(m)
        assert len(unique) == 16, f"Expected 16 unique values, got {len(unique)}"

    def test_has_exact_zero(self):
        """NF4 must contain an exact zero for lossless padding quantization."""
        m = create_nf4_map()
        assert any(abs(v) < 1e-10 for v in m.tolist()), "No exact zero found"

    def test_asymmetry_positive_count(self):
        """NF4 should have 8 positive values."""
        m = create_nf4_map()
        n_pos = (m > 1e-10).sum().item()
        assert n_pos == 8, f"Expected 8 positive values, got {n_pos}"

    def test_asymmetry_negative_count(self):
        """NF4 should have 7 negative values."""
        m = create_nf4_map()
        n_neg = (m < -1e-10).sum().item()
        assert n_neg == 7, f"Expected 7 negative values, got {n_neg}"

    def test_asymmetry_zero_count(self):
        """NF4 should have exactly 1 zero."""
        m = create_nf4_map()
        n_zero = (m.abs() < 1e-10).sum().item()
        assert n_zero == 1, f"Expected 1 zero, got {n_zero}"

    def test_deterministic(self):
        """Repeated calls must return identical results."""
        m1 = create_nf4_map()
        m2 = create_nf4_map()
        assert torch.allclose(m1, m2), "create_nf4_map is not deterministic"

    def test_values_derived_from_normal_quantiles(self):
        """NF4 values should be derived from N(0,1) quantiles.
        Verify the positive values are consistent with norm.ppf applied to
        evenly-spaced quantile points, normalized by the maximum."""
        from scipy.stats import norm

        m = create_nf4_map()
        positive_vals = m[m > 1e-10].sort()[0]
        assert len(positive_vals) == 8

        # The largest positive value should correspond to norm.ppf(0.9677083)
        # After normalization, it should be 1.0
        assert abs(positive_vals[-1].item() - 1.0) < 1e-6

        # The second-largest should be norm.ppf(second_quantile) / norm.ppf(0.9677083)
        # Verify monotonically increasing and within expected range
        for i in range(len(positive_vals) - 1):
            assert positive_vals[i].item() < positive_vals[i + 1].item()
        assert positive_vals[0].item() > 0.0
        assert positive_vals[0].item() < 0.15  # smallest positive should be small


# ---------------------------------------------------------------------------
# FP4 Map Tests
# ---------------------------------------------------------------------------

class TestFP4Map:
    def test_length(self):
        """FP4 codebook must have 16 entries."""
        m = create_fp4_map()
        assert m.shape == (16,), f"Expected shape (16,), got {m.shape}"

    def test_sorted(self):
        m = create_fp4_map()
        for i in range(len(m) - 1):
            assert m[i].item() <= m[i + 1].item()

    def test_range_min(self):
        m = create_fp4_map()
        assert abs(m.min().item() - (-1.0)) < 1e-6

    def test_range_max(self):
        m = create_fp4_map()
        assert abs(m.max().item() - 1.0) < 1e-6

    def test_has_zero(self):
        m = create_fp4_map()
        assert any(abs(v) < 1e-10 for v in m.tolist())

    def test_symmetry(self):
        """FP4 should be symmetric: same number of positive and negative values."""
        m = create_fp4_map()
        n_pos = (m > 1e-10).sum().item()
        n_neg = (m < -1e-10).sum().item()
        assert n_pos == n_neg, f"FP4 asymmetric: {n_pos} positive, {n_neg} negative"

    def test_unique_count(self):
        """FP4 has 15 unique values (two zeros from +0 and -0 in subnormal)."""
        m = create_fp4_map()
        unique = torch.unique(m)
        assert len(unique) == 15, f"Expected 15 unique FP4 values, got {len(unique)}"

    def test_deterministic(self):
        m1 = create_fp4_map()
        m2 = create_fp4_map()
        assert torch.allclose(m1, m2)


# ---------------------------------------------------------------------------
# Quantize / Dequantize Roundtrip Tests
# ---------------------------------------------------------------------------

class TestQuantizeRoundtrip:
    def test_nf4_roundtrip_accuracy(self):
        """NF4 quantize-dequantize roundtrip on normal data must have bounded error."""
        torch.manual_seed(42)
        A = torch.randn(1024, 1024)
        packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")
        A_hat = dequantize_4bit(packed, state)

        assert A_hat.shape == A.shape, f"Shape mismatch: {A_hat.shape} vs {A.shape}"
        abs_err = (A - A_hat).abs().mean().item()
        assert abs_err < 0.10, f"NF4 mean absolute error too high: {abs_err}"

    def test_fp4_roundtrip_accuracy(self):
        """FP4 quantize-dequantize roundtrip on normal data must have bounded error."""
        torch.manual_seed(42)
        A = torch.randn(1024, 1024)
        packed, state = quantize_4bit(A, blocksize=64, quant_type="fp4")
        A_hat = dequantize_4bit(packed, state)

        assert A_hat.shape == A.shape
        abs_err = (A - A_hat).abs().mean().item()
        assert abs_err < 0.12, f"FP4 mean absolute error too high: {abs_err}"

    def test_nf4_beats_fp4_on_normal_data(self):
        """NF4 should achieve lower quantization error than FP4 on normal data,
        because NF4 is information-theoretically optimal for normal distributions."""
        torch.manual_seed(123)
        A = torch.randn(2048, 2048)

        packed_nf4, state_nf4 = quantize_4bit(A, blocksize=64, quant_type="nf4")
        A_nf4 = dequantize_4bit(packed_nf4, state_nf4)
        err_nf4 = (A - A_nf4).abs().mean().item()

        packed_fp4, state_fp4 = quantize_4bit(A, blocksize=64, quant_type="fp4")
        A_fp4 = dequantize_4bit(packed_fp4, state_fp4)
        err_fp4 = (A - A_fp4).abs().mean().item()

        assert err_nf4 < err_fp4, (
            f"NF4 error ({err_nf4:.6f}) should be less than FP4 ({err_fp4:.6f}) "
            f"on normally-distributed data"
        )

    def test_packed_tensor_shape(self):
        """Packed output should have half the number of elements (two per byte)."""
        torch.manual_seed(0)
        A = torch.randn(512, 512)
        packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")

        n_elements = A.numel()
        expected_packed = math.ceil(n_elements / 2)
        assert packed.numel() == expected_packed, (
            f"Packed size {packed.numel()} != expected {expected_packed}"
        )

    def test_packed_dtype(self):
        """Packed tensor must be uint8."""
        torch.manual_seed(0)
        A = torch.randn(256, 256)
        packed, _ = quantize_4bit(A, blocksize=64, quant_type="nf4")
        assert packed.dtype == torch.uint8, f"Expected uint8, got {packed.dtype}"

    def test_output_dtype_preserved(self):
        """Dequantized tensor should match the original dtype."""
        for dt in [torch.float32, torch.float16, torch.bfloat16]:
            torch.manual_seed(0)
            A = torch.randn(256, 256).to(dt)
            packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")
            A_hat = dequantize_4bit(packed, state)
            assert A_hat.dtype == dt, f"Expected dtype {dt}, got {A_hat.dtype}"

    def test_zero_tensor(self):
        """Quantizing an all-zero tensor should dequantize back to zeros."""
        A = torch.zeros(128, 128)
        packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")
        A_hat = dequantize_4bit(packed, state)
        assert A_hat.abs().max().item() < 1e-6, "Zero tensor not recovered"

    def test_quant_state_fields(self):
        """QuantState should store correct metadata."""
        torch.manual_seed(0)
        A = torch.randn(256, 256)
        packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")

        assert state.shape == (256, 256)
        assert state.blocksize == 64
        assert state.quant_type == "nf4"
        assert state.dtype == torch.float32
        assert isinstance(state.code, torch.Tensor)
        assert not state.nested

    def test_different_blocksizes(self):
        """Quantization should work with various block sizes."""
        torch.manual_seed(42)
        A = torch.randn(512, 512)
        for bs in [32, 64, 128, 256]:
            packed, state = quantize_4bit(A, blocksize=bs, quant_type="nf4")
            A_hat = dequantize_4bit(packed, state)
            assert A_hat.shape == A.shape
            abs_err = (A - A_hat).abs().mean().item()
            assert abs_err < 0.12, f"Error too high for blocksize {bs}: {abs_err}"


# ---------------------------------------------------------------------------
# Double Quantization Tests
# ---------------------------------------------------------------------------

class TestDoubleQuantization:
    def test_roundtrip_accuracy(self):
        """Double quantization should still produce bounded roundtrip error."""
        torch.manual_seed(42)
        A = torch.randn(1024, 1024)
        packed, state = quantize_4bit(
            A, blocksize=64, quant_type="nf4", compress_statistics=True
        )
        A_hat = dequantize_4bit(packed, state)

        assert A_hat.shape == A.shape
        abs_err = (A - A_hat).abs().mean().item()
        assert abs_err < 0.10, (
            f"Double-quant mean absolute error too high: {abs_err}"
        )

    def test_nested_state(self):
        """With compress_statistics=True, QuantState should be nested."""
        torch.manual_seed(0)
        A = torch.randn(512, 512)
        _, state = quantize_4bit(
            A, blocksize=64, quant_type="nf4", compress_statistics=True
        )
        assert state.nested, "QuantState.nested should be True with compress_statistics"
        assert state.state2 is not None
        assert state.offset is not None

    def test_absmax_is_uint8(self):
        """With double quantization, first-level absmax should be uint8."""
        torch.manual_seed(0)
        A = torch.randn(512, 512)
        _, state = quantize_4bit(
            A, blocksize=64, quant_type="nf4", compress_statistics=True
        )
        assert state.absmax.dtype == torch.uint8, (
            f"Expected uint8 absmax, got {state.absmax.dtype}"
        )

    def test_double_quant_vs_standard(self):
        """Double quantization should have only slightly higher error than standard."""
        torch.manual_seed(42)
        A = torch.randn(1024, 1024)

        packed_std, state_std = quantize_4bit(
            A, blocksize=64, quant_type="nf4", compress_statistics=False
        )
        A_std = dequantize_4bit(packed_std, state_std)
        err_std = (A - A_std).abs().mean().item()

        packed_dq, state_dq = quantize_4bit(
            A, blocksize=64, quant_type="nf4", compress_statistics=True
        )
        A_dq = dequantize_4bit(packed_dq, state_dq)
        err_dq = (A - A_dq).abs().mean().item()

        # Double quant error should be close to standard (within 50% overhead)
        assert err_dq < err_std * 1.5, (
            f"DQ error {err_dq:.6f} much larger than standard {err_std:.6f}"
        )


# ---------------------------------------------------------------------------
# Memory Footprint Tests
# ---------------------------------------------------------------------------

class TestMemoryFootprint:
    def test_no_double_quant_blocksize_64(self):
        """Without DQ: 4 + 32/64 = 4.5 bits per param."""
        result = compute_memory_bits_per_param(blocksize=64, double_quant=False)
        assert abs(result - 4.5) < 1e-6, f"Expected 4.5, got {result}"

    def test_no_double_quant_blocksize_128(self):
        """Without DQ: 4 + 32/128 = 4.25 bits per param."""
        result = compute_memory_bits_per_param(blocksize=128, double_quant=False)
        assert abs(result - 4.25) < 1e-6, f"Expected 4.25, got {result}"

    def test_with_double_quant_blocksize_64(self):
        """With DQ (bs=64, dq_bs=256): 4 + 8/64 + 32/(64*256)."""
        expected = 4.0 + 8.0 / 64 + 32.0 / (64 * 256)
        result = compute_memory_bits_per_param(
            blocksize=64, double_quant=True, dq_blocksize=256
        )
        assert abs(result - expected) < 1e-6, f"Expected {expected}, got {result}"

    def test_double_quant_saves_memory(self):
        """Double quantization should always use fewer bits than standard."""
        for bs in [32, 64, 128, 256]:
            bits_std = compute_memory_bits_per_param(blocksize=bs, double_quant=False)
            bits_dq = compute_memory_bits_per_param(
                blocksize=bs, double_quant=True, dq_blocksize=256
            )
            assert bits_dq < bits_std, (
                f"DQ ({bits_dq}) should use fewer bits than standard ({bits_std}) "
                f"at blocksize {bs}"
            )

    def test_savings_match_qlora_paper(self):
        """QLoRA paper states: overhead drops from 0.5 to ~0.127 bits at bs=64, dq_bs=256.
        Savings should be approximately 0.373 bits per parameter."""
        overhead_std = compute_memory_bits_per_param(64, False) - 4.0
        overhead_dq = compute_memory_bits_per_param(64, True, 256) - 4.0
        savings = overhead_std - overhead_dq
        assert abs(savings - 0.373046875) < 0.001, (
            f"Expected savings ~0.373, got {savings}"
        )
