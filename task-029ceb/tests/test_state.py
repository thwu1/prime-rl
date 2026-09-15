
"""
Tests for tcgen05 shared memory layout and descriptor encoding library.
Tests include cases beyond those in /app/reference_data.json.
"""

import sys
sys.path.insert(0, "/app")

from tcgen05_layout import (
    SWIZZLE_NONE,
    SWIZZLE_32B,
    SWIZZLE_64B,
    SWIZZLE_128B,
    compute_physical_offset,
    compute_logical_coords,
    encode_smem_descriptor,
    encode_instruction_descriptor,
    compute_tma_params,
    rearrange_tile,
)


# ======================================================================
# 1. Physical offset — cases NOT in reference_data.json
# ======================================================================

class TestPhysicalOffsetExtended:
    """Extended address mapping tests beyond reference examples."""

    def test_none_last_row(self):
        assert compute_physical_offset(127, 0, 128, SWIZZLE_NONE) == 2032

    def test_none_small_tile(self):
        assert compute_physical_offset(15, 31, 32, SWIZZLE_NONE) == 767

    def test_128b_row3_col48(self):
        assert compute_physical_offset(3, 48, 128, SWIZZLE_128B) == 384

    def test_128b_row5_col112(self):
        assert compute_physical_offset(5, 112, 128, SWIZZLE_128B) == 672

    def test_128b_row6_col80_h64(self):
        assert compute_physical_offset(6, 80, 64, SWIZZLE_128B) == 816

    def test_128b_row2_col48(self):
        assert compute_physical_offset(2, 48, 128, SWIZZLE_128B) == 272

    def test_32b_row3_col0(self):
        assert compute_physical_offset(3, 0, 128, SWIZZLE_32B) == 112

    def test_32b_col48(self):
        assert compute_physical_offset(0, 48, 128, SWIZZLE_32B) == 4112

    def test_64b_row1_col48(self):
        assert compute_physical_offset(1, 48, 128, SWIZZLE_64B) == 96

    def test_64b_row7_col32_h64(self):
        assert compute_physical_offset(7, 32, 64, SWIZZLE_64B) == 464


# ======================================================================
# 2. Inverse mapping — extended tests
# ======================================================================

class TestLogicalCoordsExtended:
    """Inverse mapping tests beyond reference examples."""

    def test_32b_roundtrip(self):
        p = compute_physical_offset(5, 20, 64, SWIZZLE_32B)
        assert p == 164
        assert compute_logical_coords(p, 64, 32, SWIZZLE_32B) == (5, 20)

    def test_64b_roundtrip(self):
        p = compute_physical_offset(11, 50, 32, SWIZZLE_64B)
        assert p == 706
        assert compute_logical_coords(p, 32, 64, SWIZZLE_64B) == (11, 50)

    def test_128b_roundtrip_row3_col48(self):
        p = compute_physical_offset(3, 48, 128, SWIZZLE_128B)
        assert compute_logical_coords(p, 128, 128, SWIZZLE_128B) == (3, 48)

    def test_none_roundtrip_col32(self):
        p = compute_physical_offset(10, 32, 64, SWIZZLE_NONE)
        assert compute_logical_coords(p, 64, 48, SWIZZLE_NONE) == (10, 32)


# ======================================================================
# 3. Bijectivity — full permutation checks
# ======================================================================

class TestBijectivity:
    """Full bijectivity over every byte position in the tile."""

    def _check(self, H, W, mode):
        seen = set()
        for r in range(H):
            for c in range(W):
                p = compute_physical_offset(r, c, H, mode)
                assert 0 <= p < H * W, f"OOB ({r},{c})->{p}"
                assert p not in seen, f"Dup ({r},{c})->{p}"
                seen.add(p)
                r2, c2 = compute_logical_coords(p, H, W, mode)
                assert (r2, c2) == (r, c), f"RT ({r},{c})->{p}->({r2},{c2})"
        assert len(seen) == H * W

    def test_none_128x128(self):
        self._check(128, 128, SWIZZLE_NONE)

    def test_128b_128x128(self):
        self._check(128, 128, SWIZZLE_128B)

    def test_32b_16x64(self):
        self._check(16, 64, SWIZZLE_32B)

    def test_64b_32x128(self):
        self._check(32, 128, SWIZZLE_64B)

    def test_none_64x32(self):
        self._check(64, 32, SWIZZLE_NONE)

    def test_128b_64x256(self):
        self._check(64, 256, SWIZZLE_128B)

    def test_32b_32x32(self):
        self._check(32, 32, SWIZZLE_32B)

    def test_64b_16x64(self):
        self._check(16, 64, SWIZZLE_64B)


# ======================================================================
# 4. Shared memory descriptor — extended tests
# ======================================================================

class TestSmemDescriptorExtended:
    """64-bit descriptor tests beyond reference examples."""

    def test_none_h64(self):
        desc = encode_smem_descriptor(0, 64, SWIZZLE_NONE)
        assert desc == 70403108110336

    def test_128b_base512(self):
        desc = encode_smem_descriptor(512, 128, SWIZZLE_128B)
        assert desc == 4611756662049472544

    def test_none_h32(self):
        desc = encode_smem_descriptor(0, 32, SWIZZLE_NONE)
        assert desc == 70403106013184

    def test_addr_field_isolation(self):
        d0 = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        d48 = encode_smem_descriptor(48, 128, SWIZZLE_NONE)
        assert (d48 & 0x3FFF) == 3
        assert (d0 & ~0x3FFF) == (d48 & ~0x3FFF)

    def test_lbo_field_none(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        lbo_enc = (desc >> 16) & 0x3FFF
        assert lbo_enc == 128

    def test_lbo_field_128b_is_zero(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_128B)
        assert ((desc >> 16) & 0x3FFF) == 0

    def test_sbo_field_none(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        sbo_enc = (desc >> 32) & 0x3FFF
        assert sbo_enc == 8

    def test_sbo_field_128b(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_128B)
        sbo_enc = (desc >> 32) & 0x3FFF
        assert sbo_enc == 64

    def test_flag_bit_set(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        assert (desc >> 46) & 1 == 1

    def test_swizzle_bits_none(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        assert (desc >> 61) & 0x7 == 0

    def test_swizzle_bits_128b(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_128B)
        assert (desc >> 61) & 0x7 == 2

    def test_none_lbo_vs_sbo_consistency(self):
        for h in [32, 64, 128]:
            desc = encode_smem_descriptor(0, h, SWIZZLE_NONE)
            lbo_bytes = ((desc >> 16) & 0x3FFF) * 16
            sbo_bytes = ((desc >> 32) & 0x3FFF) * 16
            assert lbo_bytes == h * 16
            assert sbo_bytes == 128


# ======================================================================
# 5. Instruction descriptor — extended tests
# ======================================================================

class TestInstructionDescriptorExtended:
    """32-bit instruction descriptor tests beyond reference examples."""

    def test_bf16_256x256(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 256, 256)
        assert idesc == 272630928

    def test_mixed_dtypes(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "FP16", 128, 64)
        assert idesc == 135266448

    def test_fp8_e4m3(self):
        idesc = encode_instruction_descriptor("FP32", "FP8_E4M3", "FP8_E4M3", 128, 128)
        assert idesc == 136318352

    def test_acc_dtype_field(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 128, 64)
        assert (idesc >> 4) & 0x7 == 1

    def test_a_dtype_field(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 128, 64)
        assert (idesc >> 7) & 0x7 == 1

    def test_b_dtype_field(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "FP16", 128, 64)
        assert (idesc >> 10) & 0x7 == 0

    def test_mma_n_encoding(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 128, 64)
        assert (idesc >> 17) & 0x7F == 8

    def test_mma_m_encoding(self):
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 128, 64)
        assert (idesc >> 24) & 0xFF == 8

    def test_reserved_bits_zero(self):
        """Low 4 bits and bits 16:13 should be zero."""
        idesc = encode_instruction_descriptor("FP32", "BF16", "BF16", 128, 64)
        assert (idesc & 0xF) == 0      # bits 3:0
        assert (idesc >> 13) & 0xF == 0  # bits 16:13


# ======================================================================
# 6. TMA parameters — extended tests
# ======================================================================

class TestTmaParamsExtended:
    """TMA parameter tests beyond reference examples."""

    def test_bf16_128b_large_k(self):
        p = compute_tma_params(8192, 8192, 128, 128, 2, SWIZZLE_128B)
        assert p["globalDim"] == [64, 8192, 128]
        assert p["globalStrides"] == [16384, 128]
        assert p["boxDim"] == [64, 128, 2]

    def test_bf16_32b(self):
        p = compute_tma_params(4096, 4096, 128, 64, 2, SWIZZLE_32B)
        assert p["globalDim"] == [16, 4096, 256]
        assert p["globalStrides"] == [8192, 32]
        assert p["boxDim"] == [16, 128, 4]

    def test_bf16_64b(self):
        p = compute_tma_params(2048, 4096, 128, 64, 2, SWIZZLE_64B)
        assert p["globalDim"] == [32, 2048, 128]
        assert p["globalStrides"] == [8192, 64]
        assert p["boxDim"] == [32, 128, 2]

    def test_fp32_none_small(self):
        p = compute_tma_params(1024, 512, 32, 16, 4, SWIZZLE_NONE)
        assert p["globalDim"] == [4, 1024, 128]
        assert p["globalStrides"] == [2048, 16]
        assert p["boxDim"] == [4, 32, 4]

    def test_inner_dim_equals_chunk_elems(self):
        for mode, chunk in [("NONE", 16), ("32B", 32), ("64B", 64), ("128B", 128)]:
            p = compute_tma_params(4096, 4096, 128, 64, 2, mode)
            assert p["globalDim"][0] == chunk // 2

    def test_output_structure(self):
        p = compute_tma_params(4096, 4096, 128, 64, 2, SWIZZLE_NONE)
        assert set(p.keys()) >= {"globalDim", "globalStrides", "boxDim"}
        assert len(p["globalDim"]) == 3
        assert len(p["globalStrides"]) == 2
        assert len(p["boxDim"]) == 3


# ======================================================================
# 7. Tile rearrangement
# ======================================================================

class TestRearrangeTile:
    """Full tile rearrangement to physical layout."""

    def test_none_single_slice_identity(self):
        H, W = 8, 16
        data = bytes(range(H * W))
        assert rearrange_tile(data, H, W, SWIZZLE_NONE) == data

    def test_none_two_slices(self):
        H, W = 8, 32
        data = bytes(range(H * W))
        result = rearrange_tile(data, H, W, SWIZZLE_NONE)
        assert result[0] == data[0]
        assert result[128] == data[16]
        assert result[127] == data[7 * 32 + 15]

    def test_128b_row0_unchanged(self):
        H, W = 8, 128
        data = bytes(i % 256 for i in range(H * W))
        result = rearrange_tile(data, H, W, SWIZZLE_128B)
        assert result[0:16] == data[0:16]

    def test_128b_row1_swap(self):
        H, W = 8, 128
        data = bytes(i % 256 for i in range(H * W))
        result = rearrange_tile(data, H, W, SWIZZLE_128B)
        assert result[144:160] == data[128:144]
        assert result[128:144] == data[144:160]

    def test_roundtrip_via_offsets(self):
        """rearrange_tile must agree with compute_physical_offset."""
        H, W = 16, 128
        data = bytes(i % 256 for i in range(H * W))
        for mode in [SWIZZLE_NONE, SWIZZLE_32B, SWIZZLE_64B, SWIZZLE_128B]:
            result = rearrange_tile(data, H, W, mode)
            for r in range(H):
                for c in range(W):
                    p = compute_physical_offset(r, c, H, mode)
                    assert result[p] == data[r * W + c], \
                        f"({r},{c}) mode={mode}"

    def test_preserves_length(self):
        H, W = 128, 128
        data = bytes(i % 256 for i in range(H * W))
        for mode in [SWIZZLE_NONE, SWIZZLE_128B]:
            assert len(rearrange_tile(data, H, W, mode)) == H * W


# ======================================================================
# 8. Cross-validation: descriptor vs layout consistency
# ======================================================================

class TestDescriptorLayoutConsistency:
    """Verify descriptor fields are consistent with layout geometry."""

    def test_none_lbo_equals_strip_stride(self):
        for H in [32, 64, 128]:
            desc = encode_smem_descriptor(0, H, SWIZZLE_NONE)
            lbo_bytes = ((desc >> 16) & 0x3FFF) * 16
            assert lbo_bytes == H * 16

    def test_none_sbo_equals_core_matrix_block(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_NONE)
        sbo_bytes = ((desc >> 32) & 0x3FFF) * 16
        assert sbo_bytes == 128

    def test_128b_sbo_equals_core_matrix_block(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_128B)
        sbo_bytes = ((desc >> 32) & 0x3FFF) * 16
        assert sbo_bytes == 1024

    def test_128b_no_lbo_needed(self):
        desc = encode_smem_descriptor(0, 128, SWIZZLE_128B)
        assert ((desc >> 16) & 0x3FFF) == 0

    def test_addr_roundtrip(self):
        """Encoded ADDR field should roundtrip through >>4 and <<4."""
        for addr in [0, 16, 48, 256, 1024, 4096]:
            desc = encode_smem_descriptor(addr, 128, SWIZZLE_NONE)
            recovered = (desc & 0x3FFF) << 4
            assert recovered == addr
