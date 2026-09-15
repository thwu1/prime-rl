
import sys
import math
import random
import struct
import os
import zlib
import pytest

sys.path.insert(0, "/app")

from codec import (
    create_nf4_map,
    quantize_blockwise_nf4,
    dequantize_blockwise_nf4,
    double_quantize,
    double_dequantize,
    compute_memory_bits_per_param,
    load_nibble_lib,
    pack_nibbles,
    unpack_nibbles,
    read_checkpoint,
    write_checkpoint,
    find_optimal_blocksize,
)

# Reference NF4 values (QLoRA paper Appendix E / bitsandbytes source)
REFERENCE_NF4 = [
    -1.0,
    -0.6961928009986877,
    -0.5250730514526367,
    -0.39491748809814453,
    -0.28444138169288635,
    -0.18477343022823334,
    -0.09105003625154495,
    0.0,
    0.07958029955625534,
    0.16093020141124725,
    0.24611230194568634,
    0.33791524171829224,
    0.44070982933044434,
    0.5626170039176941,
    0.7229568362236023,
    1.0,
]

# Reference checkpoint data
CHECKPOINT_INDICES = [
    15, 0, 12, 2, 7, 14, 0, 10, 11, 3, 9, 5, 13, 1, 8, 6,
    4, 15, 10, 7, 2, 12, 5, 9, 0, 14, 3, 11, 8, 1, 6, 13,
]
CHECKPOINT_ABSMAX = [2.5, 1.8]
CHECKPOINT_BLOCKSIZE = 16


class TestNF4MapConstruction:
    """Verify the NF4 quantization map is correctly constructed from N(0,1) quantiles."""

    def test_map_length(self):
        nf4 = create_nf4_map()
        assert len(nf4) == 16, f"NF4 map must have exactly 16 values, got {len(nf4)}"

    def test_map_sorted(self):
        nf4 = create_nf4_map()
        for i in range(len(nf4) - 1):
            assert nf4[i] <= nf4[i + 1], (
                f"NF4 map not sorted at index {i}: {nf4[i]} > {nf4[i+1]}"
            )

    def test_map_range(self):
        nf4 = create_nf4_map()
        assert nf4[0] == pytest.approx(-1.0, abs=1e-6)
        assert nf4[-1] == pytest.approx(1.0, abs=1e-6)

    def test_map_contains_zero(self):
        nf4 = create_nf4_map()
        zero_vals = [v for v in nf4 if abs(v) < 1e-6]
        assert len(zero_vals) == 1

    def test_map_asymmetric_count(self):
        """NF4 has 7 negative, 8 positive, plus zero = 16 total."""
        nf4 = create_nf4_map()
        neg = sum(1 for v in nf4 if v < -1e-9)
        pos = sum(1 for v in nf4 if v > 1e-9)
        assert neg == 7
        assert pos == 8

    def test_map_values_match_reference(self):
        nf4 = create_nf4_map()
        for i, (computed, ref) in enumerate(zip(nf4, REFERENCE_NF4)):
            assert computed == pytest.approx(ref, abs=1e-3), (
                f"NF4[{i}]: computed={computed}, reference={ref}"
            )

    def test_map_no_duplicates(self):
        nf4 = create_nf4_map()
        assert len(set(round(v, 6) for v in nf4)) == 16


class TestBlockwiseQuantization:
    """Verify blockwise NF4 quantization and dequantization."""

    def test_basic_roundtrip(self):
        data = [0.5, -0.3, 0.8, -0.1, 0.0, 0.7, -0.9, 0.2]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        reconstructed = dequantize_blockwise_nf4(qstate)
        assert len(reconstructed) == len(data)
        for i, (orig, recon) in enumerate(zip(data, reconstructed)):
            assert recon == pytest.approx(orig, abs=0.25), (
                f"Index {i}: orig={orig}, recon={recon}"
            )

    def test_qstate_structure(self):
        data = [float(i) for i in range(64)]
        qstate = quantize_blockwise_nf4(data, blocksize=16)
        assert "indices" in qstate
        assert "absmax" in qstate
        assert "blocksize" in qstate
        assert "num_elements" in qstate
        assert len(qstate["indices"]) == 64
        assert len(qstate["absmax"]) == 4
        assert qstate["blocksize"] == 16
        assert qstate["num_elements"] == 64

    def test_indices_range(self):
        data = [math.sin(i * 0.1) for i in range(128)]
        qstate = quantize_blockwise_nf4(data, blocksize=32)
        for idx in qstate["indices"]:
            assert 0 <= idx <= 15

    def test_absmax_values(self):
        """Each block's absmax should be the max absolute value in that block."""
        data = [1.0, -2.0, 0.5, 0.3, 0.1, 0.2, -0.4, 0.0]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        assert qstate["absmax"][0] == pytest.approx(2.0, abs=1e-9)
        assert qstate["absmax"][1] == pytest.approx(0.4, abs=1e-9)

    def test_non_divisible_blocksize(self):
        data = [float(i) for i in range(10)]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        reconstructed = dequantize_blockwise_nf4(qstate)
        assert len(reconstructed) == 10
        assert len(qstate["absmax"]) == 3  # ceil(10/4) = 3

    def test_zero_block(self):
        data = [0.0] * 16
        qstate = quantize_blockwise_nf4(data, blocksize=8)
        reconstructed = dequantize_blockwise_nf4(qstate)
        for v in reconstructed:
            assert v == pytest.approx(0.0, abs=1e-9)

    def test_constant_block(self):
        data = [3.14] * 8
        qstate = quantize_blockwise_nf4(data, blocksize=8)
        reconstructed = dequantize_blockwise_nf4(qstate)
        for v in reconstructed:
            assert v == pytest.approx(3.14, abs=0.01)

    def test_negative_block(self):
        """Block with all negative values — tests symmetric normalization."""
        data = [-1.0, -2.0, -3.0, -4.0]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        reconstructed = dequantize_blockwise_nf4(qstate)
        for orig, recon in zip(data, reconstructed):
            assert recon < 0, f"Expected negative, got {recon}"
        assert qstate["absmax"][0] == pytest.approx(4.0, abs=1e-9)
        for orig, recon in zip(data, reconstructed):
            assert abs(orig - recon) < 1.0

    def test_negative_dominant_block(self):
        """Block where largest magnitude is negative."""
        data = [0.5, -0.3, 0.2, -0.9]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        assert qstate["absmax"][0] == pytest.approx(0.9, abs=1e-9)
        reconstructed = dequantize_blockwise_nf4(qstate)
        for orig, recon in zip(data, reconstructed):
            assert abs(orig - recon) < 0.25

    def test_large_tensor_error_bound(self):
        """On normally distributed data, NF4 quantization error should be bounded."""
        random.seed(42)
        data = [random.gauss(0, 1) for _ in range(4096)]
        qstate = quantize_blockwise_nf4(data, blocksize=64)
        reconstructed = dequantize_blockwise_nf4(qstate)
        rel_errs = []
        for o, r in zip(data, reconstructed):
            if abs(o) > 0.1:
                rel_errs.append(abs(o - r) / abs(o))
        mean_rel_err = sum(rel_errs) / len(rel_errs) if rel_errs else 0
        assert mean_rel_err < 0.15

    def test_single_element(self):
        data = [42.0]
        qstate = quantize_blockwise_nf4(data, blocksize=64)
        reconstructed = dequantize_blockwise_nf4(qstate)
        assert len(reconstructed) == 1
        assert reconstructed[0] == pytest.approx(42.0, abs=0.01)

    def test_preserves_sign(self):
        data = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5, 3.0, -3.0]
        qstate = quantize_blockwise_nf4(data, blocksize=8)
        reconstructed = dequantize_blockwise_nf4(qstate)
        for orig, recon in zip(data, reconstructed):
            if abs(orig) > 0.3:
                assert (orig > 0) == (recon > 0)


class TestDoubleQuantization:
    """Verify double quantization of scaling constants."""

    def test_basic_double_quant(self):
        absmax_values = [1.5, 2.3, 0.8, 1.1, 3.0, 0.5, 1.9, 2.7]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        assert "quantized_absmax" in dq_state
        assert "inner_absmax" in dq_state
        assert "offset" in dq_state
        assert "inner_blocksize" in dq_state

    def test_double_quant_length(self):
        absmax_values = [float(i + 1) for i in range(16)]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        assert len(dq_state["quantized_absmax"]) == 16
        assert len(dq_state["inner_absmax"]) == 4

    def test_double_quant_roundtrip(self):
        absmax_values = [1.5, 2.3, 0.8, 1.1, 3.0, 0.5, 1.9, 2.7]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        recovered = double_dequantize(dq_state)
        assert len(recovered) == len(absmax_values)
        for orig, rec in zip(absmax_values, recovered):
            assert rec == pytest.approx(orig, abs=0.15)

    def test_offset_is_mean(self):
        absmax_values = [1.0, 2.0, 3.0, 4.0]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        expected_mean = sum(absmax_values) / len(absmax_values)
        assert dq_state["offset"] == pytest.approx(expected_mean, abs=1e-6)

    def test_quantized_absmax_range(self):
        """8-bit quantized values should be in [-127, 127]."""
        absmax_values = [float(i) for i in range(256)]
        dq_state = double_quantize(absmax_values, inner_blocksize=64)
        for v in dq_state["quantized_absmax"]:
            assert -127 <= v <= 127

    def test_double_quant_no_systematic_shift(self):
        """The mean error should be near zero (no systematic bias)."""
        absmax_values = [1.5, 2.3, 0.8, 1.1, 3.0, 0.5, 1.9, 2.7]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        recovered = double_dequantize(dq_state)
        signed_errors = [r - o for o, r in zip(absmax_values, recovered)]
        mean_signed_err = sum(signed_errors) / len(signed_errors)
        assert abs(mean_signed_err) < 0.05


class TestMemoryBitsPerParam:
    """Verify memory footprint calculations."""

    def test_no_double_quant_blocksize_64(self):
        bpp = compute_memory_bits_per_param(blocksize=64, double_quant=False)
        assert bpp == pytest.approx(4.5, abs=1e-6)

    def test_no_double_quant_blocksize_32(self):
        bpp = compute_memory_bits_per_param(blocksize=32, double_quant=False)
        assert bpp == pytest.approx(5.0, abs=1e-6)

    def test_no_double_quant_blocksize_128(self):
        bpp = compute_memory_bits_per_param(blocksize=128, double_quant=False)
        assert bpp == pytest.approx(4.25, abs=1e-6)

    def test_double_quant_blocksize_64_inner_256(self):
        bpp = compute_memory_bits_per_param(
            blocksize=64, double_quant=True, inner_blocksize=256
        )
        expected = 4.0 + 8.0 / 64.0 + 32.0 / (64.0 * 256.0)
        assert bpp == pytest.approx(expected, abs=1e-6)

    def test_double_quant_saves_memory(self):
        for bs in [32, 64, 128, 256]:
            single = compute_memory_bits_per_param(blocksize=bs, double_quant=False)
            double = compute_memory_bits_per_param(
                blocksize=bs, double_quant=True, inner_blocksize=256
            )
            assert double < single


class TestCExtension:
    """Verify C extension compilation, loading, and nibble packing."""

    def test_shared_library_exists(self):
        """C extension must be compiled to libnibble.so."""
        load_nibble_lib()
        assert os.path.exists("/app/libnibble.so"), "libnibble.so not found"

    def test_lib_loads_and_has_functions(self):
        lib = load_nibble_lib()
        assert lib is not None
        assert hasattr(lib, 'bnb_pack_nibbles')
        assert hasattr(lib, 'bnb_unpack_nibbles')
        assert hasattr(lib, 'bnb_packed_size')

    def test_packed_size(self):
        lib = load_nibble_lib()
        assert lib.bnb_packed_size(0) == 0
        assert lib.bnb_packed_size(1) == 1
        assert lib.bnb_packed_size(2) == 1
        assert lib.bnb_packed_size(3) == 2
        assert lib.bnb_packed_size(10) == 5
        assert lib.bnb_packed_size(11) == 6

    def test_pack_unpack_roundtrip(self):
        indices = [0, 15, 7, 3, 12, 1, 8, 5]
        packed = pack_nibbles(indices)
        unpacked = unpack_nibbles(packed, len(indices))
        assert unpacked == indices

    def test_pack_full_range(self):
        """All 16 possible 4-bit values should roundtrip."""
        indices = list(range(16))
        packed = pack_nibbles(indices)
        unpacked = unpack_nibbles(packed, len(indices))
        assert unpacked == indices

    def test_pack_odd_count(self):
        indices = [3, 7, 11]
        packed = pack_nibbles(indices)
        unpacked = unpack_nibbles(packed, len(indices))
        assert unpacked == indices

    def test_packing_format(self):
        """Verify byte-level format: low nibble first, high nibble second."""
        indices = [5, 10]
        packed = pack_nibbles(indices)
        assert len(packed) == 1
        byte_val = packed[0]
        assert byte_val & 0xF == 5, "Low nibble should be first index"
        assert (byte_val >> 4) & 0xF == 10, "High nibble should be second index"

    def test_pack_large_roundtrip(self):
        random.seed(777)
        indices = [random.randint(0, 15) for _ in range(1000)]
        packed = pack_nibbles(indices)
        unpacked = unpack_nibbles(packed, len(indices))
        assert unpacked == indices


class TestCheckpointIO:
    """Verify NF4Q v2 checkpoint reading and writing with CRC32."""

    def test_reference_exists(self):
        assert os.path.exists("/app/reference.nf4"), "reference.nf4 not found"

    def test_reference_magic_and_version(self):
        with open("/app/reference.nf4", "rb") as f:
            magic = f.read(4)
            version = struct.unpack('<H', f.read(2))[0]
        assert magic == b"NF4Q"
        assert version == 2

    def test_reference_indices(self):
        qstate = read_checkpoint("/app/reference.nf4")
        assert qstate["indices"] == CHECKPOINT_INDICES

    def test_reference_absmax(self):
        qstate = read_checkpoint("/app/reference.nf4")
        for i, (expected, got) in enumerate(zip(CHECKPOINT_ABSMAX, qstate["absmax"])):
            assert got == pytest.approx(expected, abs=1e-5)

    def test_reference_metadata(self):
        qstate = read_checkpoint("/app/reference.nf4")
        assert qstate["blocksize"] == CHECKPOINT_BLOCKSIZE
        assert qstate["num_elements"] == len(CHECKPOINT_INDICES)

    def test_reference_dequantize(self):
        """Loading and dequantizing the reference checkpoint produces valid values."""
        qstate = read_checkpoint("/app/reference.nf4")
        reconstructed = dequantize_blockwise_nf4(qstate)
        assert len(reconstructed) == len(CHECKPOINT_INDICES)
        for v in reconstructed:
            assert math.isfinite(v)

    def test_write_read_roundtrip(self):
        """Write a checkpoint and read it back."""
        test_path = "/tmp/test_checkpoint.nf4"
        indices = [1, 2, 3, 4, 5, 6, 7, 8]
        absmax = [1.5, 2.0]
        write_checkpoint(test_path, indices, absmax, blocksize=4)
        qstate = read_checkpoint(test_path)
        assert qstate["indices"] == indices
        assert qstate["blocksize"] == 4
        assert qstate["num_elements"] == 8
        for i, (expected, got) in enumerate(zip(absmax, qstate["absmax"])):
            assert got == pytest.approx(expected, abs=1e-5)
        os.unlink(test_path)

    def test_crc32_present(self):
        """Checkpoint file must end with a CRC32 footer."""
        with open("/app/reference.nf4", "rb") as f:
            data = f.read()
        payload = data[:-4]
        stored_crc = struct.unpack('<I', data[-4:])[0]
        computed_crc = zlib.crc32(payload) & 0xFFFFFFFF
        assert stored_crc == computed_crc

    def test_crc32_detects_corruption(self):
        """Corrupted checkpoint should raise ValueError."""
        test_path = "/tmp/test_corrupt.nf4"
        write_checkpoint(test_path, [1, 2, 3, 4], [1.0], blocksize=4)
        with open(test_path, "rb") as f:
            data = bytearray(f.read())
        data[10] ^= 0xFF  # flip bits in data byte
        with open(test_path, "wb") as f:
            f.write(data)
        with pytest.raises(ValueError, match="[Cc][Rr][Cc]"):
            read_checkpoint(test_path)
        os.unlink(test_path)

    def test_write_odd_indices(self):
        """Odd number of indices should serialize correctly."""
        test_path = "/tmp/test_odd.nf4"
        indices = [3, 7, 11]
        absmax = [2.0]
        write_checkpoint(test_path, indices, absmax, blocksize=4)
        qstate = read_checkpoint(test_path)
        assert qstate["indices"] == indices
        assert qstate["num_elements"] == 3
        os.unlink(test_path)


class TestOptimalBlocksize:
    """Verify adaptive blocksize selection."""

    def test_generous_budget_picks_largest(self):
        """With a generous error budget, should pick the largest (most efficient) blocksize."""
        data = [0.5, -0.3, 0.8, -0.1, 0.0, 0.7, -0.9, 0.2] * 8
        candidates = [8, 16, 32, 64]
        result = find_optimal_blocksize(data, candidates, error_budget=0.5)
        assert result == 64

    def test_scale_variation_prefers_smaller(self):
        """Data with scale variation benefits from smaller blocksizes."""
        data = [10.0] * 32 + [0.01] * 32
        candidates = [32, 64]
        result = find_optimal_blocksize(data, candidates, error_budget=0.004)
        assert result == 32

    def test_impossible_budget_returns_smallest(self):
        """If no candidate meets budget, return smallest (lowest-error) candidate."""
        data = [0.5, -0.3, 0.8, -0.1, 0.0, 0.7, -0.9, 0.2]
        candidates = [4, 8]
        result = find_optimal_blocksize(data, candidates, error_budget=0.0)
        assert result == 4

    def test_exact_nf4_data_picks_largest(self):
        """Data at exact NF4 levels should have near-zero error for any blocksize."""
        nf4 = create_nf4_map()
        data = [nf4[i % 16] * 2.0 for i in range(64)]
        candidates = [8, 16, 32, 64]
        result = find_optimal_blocksize(data, candidates, error_budget=0.001)
        assert result == 64

    def test_monotonicity(self):
        """Larger error budget should yield larger-or-equal blocksize."""
        random.seed(42)
        data = [random.gauss(0, 1) for _ in range(256)]
        candidates = [16, 32, 64, 128]
        r_tight = find_optimal_blocksize(data, candidates, error_budget=0.01)
        r_loose = find_optimal_blocksize(data, candidates, error_budget=1.0)
        assert r_loose >= r_tight

    def test_returns_valid_candidate(self):
        data = [1.0, -1.0, 0.5, -0.5] * 16
        candidates = [8, 32, 128]
        result = find_optimal_blocksize(data, candidates, error_budget=0.3)
        assert result in candidates


class TestEndToEnd:
    """End-to-end tests combining all components."""

    def test_full_pipeline_with_double_quant(self):
        """Quantize, double-quantize absmax, then recover."""
        random.seed(99)
        data = [random.gauss(0, 2) for _ in range(256)]
        qstate = quantize_blockwise_nf4(data, blocksize=64)
        dq_state = double_quantize(qstate["absmax"], inner_blocksize=4)
        recovered_absmax = double_dequantize(dq_state)

        qstate_mod = dict(qstate)
        qstate_mod["absmax"] = recovered_absmax
        reconstructed = dequantize_blockwise_nf4(qstate_mod)

        assert len(reconstructed) == 256
        errors = [abs(o - r) for o, r in zip(data, reconstructed)]
        mean_err = sum(errors) / len(errors)
        assert mean_err < 1.5

    def test_checkpoint_roundtrip_end_to_end(self):
        """Quantize data, write checkpoint, read it back, dequantize."""
        data = [0.5, -0.3, 0.8, -0.1, 0.0, 0.7, -0.9, 0.2] * 4
        qstate = quantize_blockwise_nf4(data, blocksize=8)

        test_path = "/tmp/test_e2e.nf4"
        write_checkpoint(test_path, qstate["indices"], qstate["absmax"], qstate["blocksize"])
        loaded = read_checkpoint(test_path)

        assert loaded["indices"] == qstate["indices"]
        assert loaded["blocksize"] == qstate["blocksize"]
        assert loaded["num_elements"] == qstate["num_elements"]

        recon = dequantize_blockwise_nf4(loaded)
        for orig, r in zip(data, recon):
            assert abs(orig - r) < 0.25
        os.unlink(test_path)

    def test_benchmark_weights_optimal(self):
        """Load benchmark weights and verify optimal blocksize evaluation."""
        with open('/app/weights.bin', 'rb') as f:
            raw = f.read()
        n = len(raw) // 4
        weights = [struct.unpack_from('<f', raw, i * 4)[0] for i in range(n)]
        assert n == 1024

        candidates = [32, 64, 128, 256]
        result = find_optimal_blocksize(weights, candidates, error_budget=0.5)
        assert result in candidates
        # Budget is generous — largest candidate should suffice for N(0,1) data
        assert result == 256

    def test_quantize_then_scale_absmax(self):
        """Verify that absmax values directly affect dequantized output scale."""
        data = [1.0, -1.0, 0.5, -0.5]
        qstate = quantize_blockwise_nf4(data, blocksize=4)
        recon1 = dequantize_blockwise_nf4(qstate)

        qstate2 = dict(qstate)
        qstate2["absmax"] = [a * 2.0 for a in qstate["absmax"]]
        recon2 = dequantize_blockwise_nf4(qstate2)

        for r1, r2 in zip(recon1, recon2):
            if abs(r1) > 0.01:
                ratio = r2 / r1
                assert ratio == pytest.approx(2.0, abs=0.01)
