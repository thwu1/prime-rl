
import struct
import math
import sys
import random

sys.path.insert(0, "/app")
from alp import alp_compress, alp_decompress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bitwise_eq(a, b):
    """Compare two values for bitwise equality, handling None and NaN."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return struct.pack("<d", a) == struct.pack("<d", b)


def assert_roundtrip(values):
    """Assert compress→decompress roundtrip preserves every value bitwise."""
    compressed = alp_compress(values)
    assert isinstance(compressed, bytes), "alp_compress must return bytes"
    decompressed = alp_decompress(compressed)
    assert len(decompressed) == len(values), (
        f"Length mismatch: got {len(decompressed)}, expected {len(values)}"
    )
    for i, (orig, dec) in enumerate(zip(values, decompressed)):
        assert bitwise_eq(orig, dec), (
            f"Mismatch at index {i}: orig={orig!r} dec={dec!r}"
        )


def parse_header(data):
    """Parse the 32-byte ALP binary header."""
    assert len(data) >= 32, f"Data too short: {len(data)} bytes"
    return {
        "magic": data[0:4],
        "num_values": struct.unpack("<Q", data[4:12])[0],
        "e": data[12],
        "f": data[13],
        "bit_width": data[14],
        "for_base": struct.unpack("<q", data[15:23])[0],
        "num_patches": struct.unpack("<I", data[23:27])[0],
        "num_chunks": struct.unpack("<H", data[27:29])[0],
        "has_nulls": bool(data[29] & 1),
    }


def extract_chunk_offsets(compressed, header):
    """Extract the chunk offset array from the end of compressed data."""
    num_entries = header["num_chunks"] + 1
    offset_bytes = num_entries * 4
    raw = compressed[-offset_bytes:]
    return [struct.unpack("<I", raw[i * 4 : (i + 1) * 4])[0] for i in range(num_entries)]


# ===========================================================================
# Roundtrip correctness
# ===========================================================================


class TestRoundtripBasic:
    def test_integers(self):
        assert_roundtrip([float(i) for i in range(100)])

    def test_negative_integers(self):
        assert_roundtrip([float(i) for i in range(-50, 50)])

    def test_simple_fractions(self):
        assert_roundtrip([1.5, 2.25, 3.125, 4.0625, 8.5])

    def test_two_decimal_places(self):
        assert_roundtrip([i / 100.0 for i in range(1, 201)])

    def test_three_decimal_places(self):
        assert_roundtrip([i / 1000.0 for i in range(1, 101)])

    def test_mixed_precision(self):
        values = [1.0, 2.5, 3.0, 4.75, 5.0, 6.125, 7.0, 8.5]
        assert_roundtrip(values)


# ===========================================================================
# IEEE 754 special values
# ===========================================================================


class TestSpecialValues:
    def test_nan_roundtrip(self):
        values = [1.0, float("nan"), 3.0]
        compressed = alp_compress(values)
        decompressed = alp_decompress(compressed)
        assert decompressed[0] == 1.0
        assert math.isnan(decompressed[1])
        assert decompressed[2] == 3.0

    def test_nan_is_patched(self):
        values = [1.0, float("nan"), 3.0]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_patches"] >= 1

    def test_positive_inf(self):
        values = [1.0, float("inf"), 3.0]
        compressed = alp_compress(values)
        decompressed = alp_decompress(compressed)
        assert decompressed[1] == float("inf")

    def test_negative_inf(self):
        values = [1.0, float("-inf"), 3.0]
        compressed = alp_compress(values)
        decompressed = alp_decompress(compressed)
        assert decompressed[1] == float("-inf")

    def test_negative_zero_preserved(self):
        """Negative zero must be bitwise distinct from positive zero."""
        values = [0.0, -0.0, 1.0]
        compressed = alp_compress(values)
        decompressed = alp_decompress(compressed)
        assert struct.pack("<d", decompressed[0]) == struct.pack("<d", 0.0)
        assert struct.pack("<d", decompressed[1]) == struct.pack("<d", -0.0)
        assert decompressed[2] == 1.0

    def test_all_special_roundtrip(self):
        assert_roundtrip([float("nan"), float("inf"), float("-inf"), -0.0])

    def test_special_mixed_with_normal(self):
        values = [1.0, float("nan"), 3.0, float("inf"), 5.0, float("-inf"), -0.0, 8.0]
        assert_roundtrip(values)


# ===========================================================================
# Null handling
# ===========================================================================


class TestNullHandling:
    def test_basic_nulls(self):
        assert_roundtrip([1.0, None, 3.0, None, 5.0])

    def test_all_nulls(self):
        assert_roundtrip([None, None, None])

    def test_nulls_with_specials(self):
        assert_roundtrip([1.0, None, float("nan"), None, 5.0])

    def test_leading_trailing_nulls(self):
        assert_roundtrip([None, 1.0, 2.0, 3.0, None])

    def test_single_null(self):
        assert_roundtrip([None])


# ===========================================================================
# Binary format validation
# ===========================================================================


class TestBinaryFormat:
    def test_magic_bytes(self):
        compressed = alp_compress([1.0, 2.0, 3.0])
        assert compressed[:4] == b"ALP1"

    def test_header_num_values(self):
        values = [float(i) for i in range(50)]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_values"] == 50

    def test_empty_array(self):
        compressed = alp_compress([])
        decompressed = alp_decompress(compressed)
        assert decompressed == []

    def test_single_value(self):
        assert_roundtrip([42.0])

    def test_exponents_for_integers(self):
        """Integer-valued floats should produce e=0, f=0."""
        values = [float(i) for i in range(1000)]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["e"] == 0, f"Expected e=0, got {header['e']}"
        assert header["f"] == 0, f"Expected f=0, got {header['f']}"
        assert header["num_patches"] == 0

    def test_has_nulls_flag_absent(self):
        compressed = alp_compress([1.0, 2.0, 3.0])
        header = parse_header(compressed)
        assert not header["has_nulls"]

    def test_has_nulls_flag_present(self):
        compressed = alp_compress([1.0, None, 3.0])
        header = parse_header(compressed)
        assert header["has_nulls"]

    def test_for_base_and_bitwidth(self):
        """FOR base and bit width for a small integer sequence."""
        values = [100.0, 101.0, 102.0, 103.0]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["for_base"] == 100, f"Expected for_base=100, got {header['for_base']}"
        assert header["bit_width"] == 2, f"Expected bit_width=2, got {header['bit_width']}"

    def test_negative_for_base(self):
        """Negative encoded values should produce a negative FOR base."""
        values = [-10.0, -5.0, 0.0, 5.0, 10.0]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["for_base"] == -10
        assert_roundtrip(values)

    def test_patches_counted_for_specials(self):
        """NaN and Inf must always be counted as patches."""
        values = [1.0, float("nan"), float("inf")]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_patches"] == 2


# ===========================================================================
# Chunk offsets
# ===========================================================================


class TestChunkOffsets:
    def test_single_chunk_no_patches(self):
        values = [1.0] * 100
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_chunks"] == 1
        offsets = extract_chunk_offsets(compressed, header)
        assert offsets == [0, 0]

    def test_single_chunk_with_patches(self):
        values = [1.0] * 100
        values[50] = float("nan")
        values[75] = float("inf")
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_chunks"] == 1
        offsets = extract_chunk_offsets(compressed, header)
        assert offsets == [0, 2]

    def test_multi_chunk_distributed_patches(self):
        """3 chunks with patches spread across all of them."""
        values = [1.0] * 3072
        values[100] = float("nan")       # chunk 0
        values[500] = float("inf")       # chunk 0
        values[1500] = float("-inf")     # chunk 1
        values[2100] = float("nan")      # chunk 2
        values[2500] = float("inf")      # chunk 2

        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_chunks"] == 3
        assert header["num_patches"] == 5
        offsets = extract_chunk_offsets(compressed, header)
        assert offsets == [0, 2, 3, 5]

    def test_empty_middle_chunk(self):
        """Patches only in first and last chunks."""
        values = [1.0] * 3072
        values[100] = float("nan")       # chunk 0
        values[2500] = float("inf")      # chunk 2

        compressed = alp_compress(values)
        header = parse_header(compressed)
        offsets = extract_chunk_offsets(compressed, header)
        assert offsets == [0, 1, 1, 2]

    def test_multi_chunk_roundtrip(self):
        """Verify roundtrip with patches across multiple chunks."""
        values = [1.0] * 3072
        values[100] = float("nan")
        values[500] = float("inf")
        values[1500] = float("-inf")
        values[2100] = float("nan")
        values[2500] = float("inf")
        assert_roundtrip(values)


# ===========================================================================
# Large arrays
# ===========================================================================


class TestLargeArray:
    def test_large_integer_roundtrip(self):
        assert_roundtrip([float(i) for i in range(10000)])

    def test_large_mixed_roundtrip(self):
        """10000 values: decimals, nulls, and specials mixed together."""
        rng = random.Random(42)
        values = []
        for _ in range(10000):
            r = rng.random()
            if r < 0.02:
                values.append(None)
            elif r < 0.03:
                values.append(float("nan"))
            elif r < 0.04:
                values.append(float("inf"))
            elif r < 0.05:
                values.append(float("-inf"))
            elif r < 0.06:
                values.append(-0.0)
            else:
                values.append(round(rng.uniform(-1000, 1000), rng.randint(0, 4)))
        assert_roundtrip(values)

    def test_many_chunks(self):
        """Array spanning 10 chunks with scattered exceptions."""
        values = [float(i % 100) for i in range(10240)]
        for i in range(0, 10240, 500):
            values[i] = float("nan")
        assert_roundtrip(values)


# ===========================================================================
# Compression properties
# ===========================================================================


class TestCompressionProperties:
    def test_integer_compression_ratio(self):
        """Clean integer data should compress to < 50% of raw size."""
        values = [float(i) for i in range(1000)]
        compressed = alp_compress(values)
        raw_size = len(values) * 8
        assert len(compressed) < raw_size * 0.5, (
            f"Compressed={len(compressed)} should be < {raw_size * 0.5}"
        )

    def test_all_patches_still_roundtrips(self):
        """Even when every value is a patch, the roundtrip must succeed."""
        values = [float("nan")] * 50 + [float("inf")] * 50
        assert_roundtrip(values)

    def test_constant_values_minimal_size(self):
        """A constant column should have bit_width=0 and tiny output."""
        values = [42.0] * 10000
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["bit_width"] == 0
        # Header (32) + no bitmap + 0 packed bytes + 0 patches
        # + chunk_offsets (ceil(10000/1024)+1)*4 = 11*4 = 44
        assert len(compressed) < 100

    def test_negative_zero_is_patched(self):
        """-0.0 must be an exception (encoding loses the sign)."""
        values = [1.0, -0.0, 2.0]
        compressed = alp_compress(values)
        header = parse_header(compressed)
        assert header["num_patches"] >= 1
