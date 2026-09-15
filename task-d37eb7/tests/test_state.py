
import sys
import json

import numpy as np
import pytest

sys.path.insert(0, "/app")
from quantize import (
    create_nf4_map,
    create_dynamic_map,
    pack_4bit,
    unpack_4bit,
    quantize_nf4,
    dequantize_nf4,
    compute_memory_bytes,
)


# ---------------------------------------------------------------------------
# NF4 Map Tests
# ---------------------------------------------------------------------------
class TestNF4Map:
    def test_values_match_reference(self):
        with open("/app/reference_nf4.json") as f:
            reference = np.array(json.load(f), dtype=np.float32)
        nf4 = create_nf4_map()
        assert nf4.shape == (16,), f"Expected shape (16,), got {nf4.shape}"
        np.testing.assert_allclose(nf4, reference, atol=1e-4)

    def test_sorted_and_endpoints(self):
        nf4 = create_nf4_map()
        assert len(nf4) == 16
        assert np.all(nf4[:-1] <= nf4[1:]), "NF4 map must be sorted"
        assert nf4[0] == pytest.approx(-1.0, abs=1e-6)
        assert nf4[-1] == pytest.approx(1.0, abs=1e-6)

    def test_unique_values(self):
        nf4 = create_nf4_map()
        assert len(np.unique(nf4)) == 16, "NF4 map must have 16 unique values"

    def test_contains_exact_zero(self):
        nf4 = create_nf4_map()
        assert np.min(np.abs(nf4)) < 1e-8, "NF4 map must contain exact zero"

    def test_asymmetric_layout(self):
        nf4 = create_nf4_map()
        n_neg = int(np.sum(nf4 < -1e-10))
        n_pos = int(np.sum(nf4 > 1e-10))
        n_zero = int(np.sum(np.abs(nf4) < 1e-10))
        assert n_neg == 7, f"Expected 7 negative values, got {n_neg}"
        assert n_pos == 8, f"Expected 8 positive values, got {n_pos}"
        assert n_zero == 1, f"Expected 1 zero value, got {n_zero}"


# ---------------------------------------------------------------------------
# Dynamic Map Tests
# ---------------------------------------------------------------------------
class TestDynamicMap:
    def test_shape_and_sorted(self):
        dm = create_dynamic_map()
        assert dm.shape == (256,), f"Expected shape (256,), got {dm.shape}"
        assert np.all(dm[:-1] <= dm[1:]), "Dynamic map must be sorted"

    def test_unique_count(self):
        dm = create_dynamic_map()
        n_unique = len(np.unique(dm))
        assert n_unique in (255, 256), f"Expected 255-256 unique values, got {n_unique}"

    def test_contains_zero_and_one(self):
        dm = create_dynamic_map()
        assert np.min(np.abs(dm)) < 1e-10, "Dynamic map must contain zero"
        assert np.max(dm) == pytest.approx(1.0, abs=1e-6)

    def test_signed_symmetry(self):
        dm = create_dynamic_map(signed=True)
        n_pos = int(np.sum(dm > 1e-10))
        n_neg = int(np.sum(dm < -1e-10))
        assert n_pos == n_neg + 1, f"Expected pos == neg+1: {n_pos} vs {n_neg}"

    def test_unsigned_nonnegative(self):
        dm = create_dynamic_map(signed=False)
        assert dm.shape == (256,)
        assert np.all(dm >= -1e-10), "Unsigned map must be non-negative"

    def test_dynamic_range_coverage(self):
        """The signed dynamic map must cover values across multiple orders of magnitude."""
        dm = create_dynamic_map(signed=True)
        pos_vals = dm[dm > 1e-10]
        # The map should span at least 5 orders of magnitude
        dynamic_range = np.log10(pos_vals.max() / pos_vals.min())
        assert dynamic_range > 5.0, (
            f"Dynamic range is only {dynamic_range:.1f} decades, expected > 5"
        )


# ---------------------------------------------------------------------------
# Pack / Unpack Tests
# ---------------------------------------------------------------------------
class TestPacking:
    def test_roundtrip_random(self):
        np.random.seed(42)
        indices = np.random.randint(0, 16, size=1000).astype(np.uint8)
        packed = pack_4bit(indices)
        unpacked = unpack_4bit(packed, count=len(indices))
        np.testing.assert_array_equal(indices, unpacked)

    def test_specific_values(self):
        indices = np.array([0, 15, 7, 8, 1, 14], dtype=np.uint8)
        packed = pack_4bit(indices)
        assert len(packed) == 3
        assert packed[0] == (15 << 4) | 0   # 0xF0 = 240
        assert packed[1] == (8 << 4) | 7    # 0x87 = 135
        assert packed[2] == (14 << 4) | 1   # 0xE1 = 225
        unpacked = unpack_4bit(packed, count=6)
        np.testing.assert_array_equal(indices, unpacked)

    def test_odd_length(self):
        indices = np.array([3, 5, 9], dtype=np.uint8)
        packed = pack_4bit(indices)
        assert len(packed) == 2
        unpacked = unpack_4bit(packed, count=3)
        np.testing.assert_array_equal(indices, unpacked)

    def test_all_zeros(self):
        indices = np.zeros(128, dtype=np.uint8)
        packed = pack_4bit(indices)
        assert np.all(packed == 0)
        unpacked = unpack_4bit(packed, count=128)
        np.testing.assert_array_equal(indices, unpacked)

    def test_all_fifteens(self):
        indices = np.full(64, 15, dtype=np.uint8)
        packed = pack_4bit(indices)
        assert np.all(packed == 0xFF)
        unpacked = unpack_4bit(packed, count=64)
        np.testing.assert_array_equal(indices, unpacked)


# ---------------------------------------------------------------------------
# Quantize / Dequantize Tests
# ---------------------------------------------------------------------------
class TestQuantization:
    def test_normal_data_error_bounds(self):
        """NF4 roundtrip on N(0,1) data must meet error bounds."""
        np.random.seed(42)
        abserrs = []
        relerrs = []
        for _ in range(50):
            tensor = np.random.randn(4096).astype(np.float32)
            qs = quantize_nf4(tensor, blocksize=64)
            recovered = dequantize_nf4(qs)
            diff = np.abs(tensor - recovered)
            reldiff = diff / (np.abs(tensor) + 1e-6)
            abserrs.append(float(diff.mean()))
            relerrs.append(float(reldiff.mean()))

        mean_abserr = np.mean(abserrs)
        mean_relerr = np.mean(relerrs)
        assert mean_abserr < 0.08, f"Mean abs error {mean_abserr:.5f} >= 0.08"
        assert mean_relerr < 0.25, f"Mean rel error {mean_relerr:.5f} >= 0.25"

    def test_zeros(self):
        """Quantizing zeros must return zeros exactly."""
        zeros = np.zeros(256, dtype=np.float32)
        qs = quantize_nf4(zeros, blocksize=64)
        recovered = dequantize_nf4(qs)
        np.testing.assert_array_equal(recovered, zeros)

    def test_shape_preservation(self):
        np.random.seed(123)
        for shape in [(128,), (32, 64), (8, 16, 32)]:
            tensor = np.random.randn(*shape).astype(np.float32)
            qs = quantize_nf4(tensor, blocksize=64)
            recovered = dequantize_nf4(qs)
            assert recovered.shape == shape, f"Expected {shape}, got {recovered.shape}"

    def test_non_divisible_size(self):
        """Quantization must handle sizes not divisible by blocksize."""
        np.random.seed(77)
        tensor = np.random.randn(100).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64)
        recovered = dequantize_nf4(qs)
        assert recovered.shape == (100,)
        assert np.abs(tensor - recovered).mean() < 0.1

    def test_packed_data_size(self):
        tensor = np.random.randn(1024).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64)
        assert len(qs["packed_data"]) == 512

    def test_large_tensor(self):
        np.random.seed(42)
        tensor = np.random.randn(65536).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64)
        recovered = dequantize_nf4(qs)
        assert recovered.shape == tensor.shape
        assert np.abs(tensor - recovered).mean() < 0.08

    def test_different_blocksizes(self):
        np.random.seed(42)
        tensor = np.random.randn(4096).astype(np.float32)
        for bs in [32, 64, 128, 256]:
            qs = quantize_nf4(tensor, blocksize=bs)
            recovered = dequantize_nf4(qs)
            assert recovered.shape == tensor.shape
            assert np.abs(tensor - recovered).mean() < 0.15


# ---------------------------------------------------------------------------
# Double Quantization Tests
# ---------------------------------------------------------------------------
class TestDoubleQuantization:
    def test_roundtrip_error(self):
        """DQ should introduce only small additional error."""
        np.random.seed(42)
        abserrs_no_dq = []
        abserrs_dq = []
        for _ in range(50):
            tensor = np.random.randn(4096).astype(np.float32)

            qs = quantize_nf4(tensor, blocksize=64, compress_statistics=False)
            recovered = dequantize_nf4(qs)
            abserrs_no_dq.append(float(np.abs(tensor - recovered).mean()))

            qs_dq = quantize_nf4(tensor, blocksize=64, compress_statistics=True)
            recovered_dq = dequantize_nf4(qs_dq)
            abserrs_dq.append(float(np.abs(tensor - recovered_dq).mean()))

        err_no_dq = np.mean(abserrs_no_dq)
        err_dq = np.mean(abserrs_dq)
        assert err_dq < 0.085, f"DQ abs error {err_dq:.5f} too high"
        assert err_dq < err_no_dq * 1.5, (
            f"DQ error {err_dq:.5f} >> non-DQ error {err_no_dq:.5f}"
        )

    def test_state_dict_keys(self):
        np.random.seed(42)
        tensor = np.random.randn(4096).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64, compress_statistics=True)
        assert qs["compress_statistics"] is True
        assert "nested_absmax" in qs
        assert "nested_quant_map" in qs
        assert "offset" in qs

    def test_absmax_dtype_compressed(self):
        np.random.seed(42)
        tensor = np.random.randn(4096).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64, compress_statistics=True)
        assert qs["absmax"].dtype == np.uint8, (
            f"Compressed absmax dtype should be uint8, got {qs['absmax'].dtype}"
        )

    def test_absmax_dtype_uncompressed(self):
        np.random.seed(42)
        tensor = np.random.randn(4096).astype(np.float32)
        qs = quantize_nf4(tensor, blocksize=64, compress_statistics=False)
        assert qs["absmax"].dtype == np.float32


# ---------------------------------------------------------------------------
# Memory Footprint Tests
# ---------------------------------------------------------------------------
class TestMemoryFootprint:
    def test_no_double_quant(self):
        n = 1_000_000
        bs = 64
        expected_weight = (n + 1) // 2
        num_blocks = (n + bs - 1) // bs
        expected_absmax = num_blocks * 4
        expected = expected_weight + expected_absmax
        actual = compute_memory_bytes(n, blocksize=bs, double_quant=False)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_with_double_quant(self):
        n = 1_000_000
        bs = 64
        dq_bs = 256
        expected_weight = (n + 1) // 2
        num_blocks = (n + bs - 1) // bs
        dq_blocks = (num_blocks + dq_bs - 1) // dq_bs
        expected_absmax = num_blocks * 1 + dq_blocks * 4
        expected = expected_weight + expected_absmax
        actual = compute_memory_bytes(
            n, blocksize=bs, double_quant=True, dq_blocksize=dq_bs
        )
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_dq_saves_memory(self):
        for n in [65536, 1_000_000, 10_000_000]:
            mem_no_dq = compute_memory_bytes(n, double_quant=False)
            mem_dq = compute_memory_bytes(n, double_quant=True)
            assert mem_dq < mem_no_dq, f"DQ should save memory for n={n}"

    def test_bits_per_param_no_dq(self):
        n = 10_000_000
        mem = compute_memory_bytes(n, blocksize=64, double_quant=False)
        bits = mem * 8 / n
        assert 4.4 < bits < 4.6, f"Expected ~4.5 bits/param, got {bits:.3f}"

    def test_bits_per_param_with_dq(self):
        n = 10_000_000
        mem = compute_memory_bytes(
            n, blocksize=64, double_quant=True, dq_blocksize=256
        )
        bits = mem * 8 / n
        assert 4.0 < bits < 4.2, f"Expected ~4.13 bits/param, got {bits:.3f}"

    def test_odd_param_count(self):
        n = 999_999
        bs = 64
        expected_weight = (n + 1) // 2  # 500000
        num_blocks = (n + bs - 1) // bs  # 15625
        expected = expected_weight + num_blocks * 4
        actual = compute_memory_bytes(n, blocksize=bs, double_quant=False)
        assert actual == expected
