
import sys
import json

import pytest
import torch
import numpy as np

sys.path.insert(0, "/app")


class TestNF4MapConstruction:
    """Tests for the NF4 quantization map."""

    def test_nf4_map_structure(self):
        """NF4 map must have correct tensor structure."""
        from nf4_quant.quantization import create_nf4_map

        nf4_map = create_nf4_map()

        assert nf4_map.numel() == 256, f"Expected 256 elements, got {nf4_map.numel()}"
        assert torch.all(
            nf4_map[:-1] <= nf4_map[1:]
        ), "Map must be sorted in ascending order"
        assert abs(nf4_map.max().item() - 1.0) < 1e-6, "Max must be 1.0"
        assert abs(nf4_map.min().item() - (-1.0)) < 1e-6, "Min must be -1.0"

        unique = torch.unique(nf4_map)
        assert len(unique) == 16, f"Expected 16 unique values, got {len(unique)}"

        has_zero = any(abs(v) < 1e-8 for v in unique.tolist())
        assert has_zero, "Map must contain a zero value"

    def test_nf4_map_asymmetry(self):
        """NF4 map must have asymmetric positive/negative layout (7/8 split)."""
        from nf4_quant.quantization import create_nf4_map

        nf4_map = create_nf4_map()
        unique = torch.unique(nf4_map)

        neg_count = (unique < -1e-8).sum().item()
        pos_count = (unique > 1e-8).sum().item()

        assert {neg_count, pos_count} == {
            7,
            8,
        }, f"Expected {{7, 8}} asymmetry, got ({neg_count}, {pos_count})"

    def test_nf4_map_reference_values(self):
        """NF4 map values must match quantiles of N(0,1) computed with scipy."""
        from scipy.stats import norm

        from nf4_quant.quantization import create_nf4_map

        nf4_map = create_nf4_map()
        actual_levels = sorted(torch.unique(nf4_map).tolist())

        offset = 0.9677083
        v_pos = norm.ppf(np.linspace(offset, 0.5, 9)[:-1]).tolist()
        v_neg = (-norm.ppf(np.linspace(offset, 0.5, 8)[:-1])).tolist()
        ref = sorted(v_pos + [0.0] + v_neg)
        ref_max = max(abs(v) for v in ref)
        ref_normalized = [v / ref_max for v in ref]

        assert len(actual_levels) == len(ref_normalized) == 16

        for actual, expected in zip(actual_levels, ref_normalized):
            assert abs(actual - expected) < 0.015, (
                f"NF4 level {actual:.6f} differs from reference {expected:.6f}"
            )


class TestBlockwiseQuantization:
    """Tests for block-wise NF4 quantization and dequantization."""

    def test_roundtrip_accuracy(self):
        """Quantize/dequantize roundtrip on normal data must be within error bounds."""
        from nf4_quant.quantization import dequantize_nf4, quantize_nf4

        torch.manual_seed(42)
        diffs = []
        reldiffs = []

        for _ in range(20):
            tensor = torch.randn(1024, 1024)
            quantized, state = quantize_nf4(tensor, blocksize=64)
            reconstructed = dequantize_nf4(quantized, state)

            diff = torch.abs(tensor - reconstructed).float()
            reldiff = diff / (torch.abs(tensor.float()) + 1e-8)
            diffs.append(diff.mean().item())
            reldiffs.append(reldiff.mean().item())

        abserr = sum(diffs) / len(diffs)
        relerr = sum(reldiffs) / len(reldiffs)

        assert abserr < 0.10, (
            f"Mean absolute error {abserr:.6f} exceeds threshold 0.10"
        )
        assert relerr < 0.30, (
            f"Mean relative error {relerr:.6f} exceeds threshold 0.30"
        )

    def test_shape_preservation(self):
        """Dequantized tensor must have the same shape as the input."""
        from nf4_quant.quantization import dequantize_nf4, quantize_nf4

        torch.manual_seed(42)
        for shape in [(256, 256), (1024, 512), (4096,), (32, 64, 128)]:
            tensor = torch.randn(*shape)
            quantized, state = quantize_nf4(tensor, blocksize=64)
            reconstructed = dequantize_nf4(quantized, state)
            assert reconstructed.shape == tensor.shape, (
                f"Shape mismatch for input {shape}: got {reconstructed.shape}"
            )

    def test_quantized_dtype(self):
        """Quantized output must be uint8."""
        from nf4_quant.quantization import quantize_nf4

        torch.manual_seed(42)
        tensor = torch.randn(256, 256)
        quantized, _ = quantize_nf4(tensor, blocksize=64)
        assert quantized.dtype == torch.uint8, (
            f"Expected uint8, got {quantized.dtype}"
        )


class TestDoubleQuantization:
    """Tests for secondary compression of scaling factors."""

    def test_double_quantize_roundtrip(self):
        """Compressed scaling factors must be recoverable within tolerance."""
        from nf4_quant.quantization import (
            double_dequantize,
            double_quantize,
            quantize_nf4,
        )

        torch.manual_seed(42)
        tensor = torch.randn(1024, 1024)
        _, state = quantize_nf4(tensor, blocksize=64)
        absmax = state["absmax"]

        dq_absmax, dq_state = double_quantize(absmax, blocksize=256)
        recovered = double_dequantize(dq_absmax, dq_state)

        error = torch.abs(absmax - recovered)
        mean_error = error.mean().item()
        absmax_range = (absmax.max() - absmax.min()).item()

        assert mean_error / absmax_range < 0.004, (
            f"Secondary compression relative error {mean_error / absmax_range:.6f} "
            f"too high (mean_error={mean_error:.6f}, range={absmax_range:.4f})"
        )
        assert dq_absmax.dtype == torch.uint8

    def test_double_quantize_shape(self):
        """Recovered scaling factors must match original shape."""
        from nf4_quant.quantization import double_dequantize, double_quantize

        absmax = torch.rand(1024) * 2 + 0.1
        dq_absmax, dq_state = double_quantize(absmax, blocksize=256)
        recovered = double_dequantize(dq_absmax, dq_state)
        assert recovered.shape == absmax.shape, (
            f"Shape mismatch: {recovered.shape} vs {absmax.shape}"
        )


class TestMemoryCalculations:
    """Tests for memory footprint computations."""

    @staticmethod
    def _load_config():
        with open("/app/config.json") as f:
            return json.load(f)

    def test_bits_per_parameter(self):
        """Bits-per-parameter formula must produce exact values."""
        from nf4_quant.memory import bits_per_parameter

        # Without DQ: 4 + 32/64 = 4.5
        bpp = bits_per_parameter(quant_bits=4, blocksize=64, double_quant=False)
        assert bpp == pytest.approx(4.5, abs=1e-6)

        # With DQ: 4 + 8/64 + 32/(64*256) = 4.126953125
        bpp_dq = bits_per_parameter(
            quant_bits=4, blocksize=64, double_quant=True, dq_blocksize=256
        )
        assert bpp_dq == pytest.approx(4.126953125, abs=1e-6)

        # Overhead values
        assert (bpp - 4.0) == pytest.approx(0.5, abs=1e-6)
        assert (bpp_dq - 4.0) == pytest.approx(0.126953125, abs=1e-6)

    def test_total_params(self):
        """Total parameter counts must be exact for known LLaMA architectures."""
        from nf4_quant.memory import compute_total_params

        config = self._load_config()
        assert compute_total_params(config["models"]["7B"]) == 6738149376
        assert compute_total_params(config["models"]["13B"]) == 13015449600
        assert compute_total_params(config["models"]["65B"]) == 65284341760

    def test_model_memory_ratios(self):
        """Memory ratios between precisions must be exact."""
        from nf4_quant.memory import compute_model_memory

        config = self._load_config()
        m = config["models"]["7B"]

        fp32 = compute_model_memory(m, precision="fp32")
        fp16 = compute_model_memory(m, precision="fp16")
        nf4 = compute_model_memory(m, precision="nf4", blocksize=64)
        nf4_dq = compute_model_memory(
            m, precision="nf4", blocksize=64, double_quant=True, dq_blocksize=256
        )

        assert fp32 / fp16 == pytest.approx(2.0, abs=1e-6)
        assert nf4 / fp16 == pytest.approx(4.5 / 16, abs=1e-6)
        assert nf4_dq / nf4 == pytest.approx(4.126953125 / 4.5, abs=1e-4)

    def test_dq_savings_65b(self):
        """Secondary compression must save ~3 GiB for 65B model."""
        from nf4_quant.memory import compute_dq_savings

        config = self._load_config()
        m = config["models"]["65B"]

        savings = compute_dq_savings(m, blocksize=64, dq_blocksize=256)
        savings_gib = savings / (1024**3)

        assert 2.5 < savings_gib < 3.5, (
            f"Savings {savings_gib:.2f} GiB outside expected range [2.5, 3.5]"
        )
