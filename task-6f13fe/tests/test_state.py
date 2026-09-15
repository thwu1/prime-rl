"""
Tests for LZ4 block format compressor/decompressor and block analyzer.

Verifies self-roundtrip correctness, reference interoperability,
compression ratio, edge-case handling, and block analysis output.
"""


import subprocess
import os
import struct
import tempfile
import random
import json
import pytest
import lz4.block

BINARY = "/app/lz4c"


@pytest.fixture(scope="session", autouse=True)
def build_binary():
    """Build the lz4c binary before running tests."""
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True)
    result = subprocess.run(["make", "-C", "/app"],
                            capture_output=True)
    assert result.returncode == 0, \
        f"Build failed:\nstdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"


def _compress_with_tool(data):
    """Compress using our lz4c tool. Returns (compressed_block, orig_size)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(data)
        inpath = f.name
    outpath = inpath + ".lz4b"
    try:
        r = subprocess.run([BINARY, "compress", inpath, outpath],
                           capture_output=True, timeout=30)
        assert r.returncode == 0, \
            f"Compress failed: {r.stderr.decode()}"
        with open(outpath, "rb") as f:
            content = f.read()
        orig_size = struct.unpack("<I", content[:4])[0]
        return content[4:], orig_size
    finally:
        if os.path.exists(inpath):
            os.unlink(inpath)
        if os.path.exists(outpath):
            os.unlink(outpath)


def _decompress_with_tool(compressed_block, orig_size):
    """Decompress using our lz4c tool. Returns decompressed bytes."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".lz4b") as f:
        f.write(struct.pack("<I", orig_size))
        f.write(compressed_block)
        inpath = f.name
    outpath = inpath + ".dec"
    try:
        r = subprocess.run([BINARY, "decompress", inpath, outpath],
                           capture_output=True, timeout=30)
        assert r.returncode == 0, \
            f"Decompress failed: {r.stderr.decode()}"
        with open(outpath, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(inpath):
            os.unlink(inpath)
        if os.path.exists(outpath):
            os.unlink(outpath)


def _roundtrip_with_tool(data):
    """Self-roundtrip test using lz4c CLI. Returns True if successful."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(data)
        inpath = f.name
    try:
        r = subprocess.run([BINARY, "roundtrip", inpath],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    finally:
        if os.path.exists(inpath):
            os.unlink(inpath)


def _write_compressed_file(block_data, orig_size):
    """Write a compressed file with 4-byte LE header + raw block data."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".lz4b") as f:
        f.write(struct.pack("<I", orig_size))
        f.write(block_data)
        return f.name


def _run_analyze(filepath):
    """Run lz4c analyze and return the subprocess result."""
    return subprocess.run([BINARY, "analyze", filepath],
                          capture_output=True, timeout=30)


# ================================================================
#  Self-roundtrip tests
# ================================================================

class TestSelfRoundtrip:
    """Compress then decompress with our tool must reproduce original."""

    def test_empty(self):
        assert _roundtrip_with_tool(b"")

    def test_one_byte(self):
        assert _roundtrip_with_tool(b"X")

    def test_tiny_3_bytes(self):
        assert _roundtrip_with_tool(b"abc")

    def test_small_under_mflimit(self):
        assert _roundtrip_with_tool(b"hello world!")  # 12 bytes

    def test_exactly_13_bytes(self):
        assert _roundtrip_with_tool(b"0123456789abc")

    def test_english_text(self):
        text = (b"The quick brown fox jumps over the lazy dog. "
                b"Pack my box with five dozen liquor jugs. "
                b"How vexingly quick daft zebras jump. ") * 10
        assert _roundtrip_with_tool(text)

    def test_repetitive_single_byte(self):
        """Tests overlap match: offset=1, match extends far."""
        data = bytes([0x42]) * 500
        assert _roundtrip_with_tool(data)

    def test_repetitive_short_pattern(self):
        """Tests overlap match: offset=4, match extends far."""
        data = b"ABCD" * 200
        assert _roundtrip_with_tool(data)

    def test_repetitive_2byte_pattern(self):
        """Tests overlap match: offset=2."""
        data = b"XY" * 300
        assert _roundtrip_with_tool(data)

    def test_all_zeros(self):
        data = bytes(4096)
        assert _roundtrip_with_tool(data)

    def test_binary_sequence(self):
        data = bytes(range(256)) * 4
        assert _roundtrip_with_tool(data)

    def test_mixed_compressible_random(self):
        random.seed(42)
        compressible = b"hello world test data " * 50
        rand_data = bytes(random.randint(0, 255) for _ in range(200))
        data = compressible + rand_data + compressible
        assert _roundtrip_with_tool(data)

    def test_large_text(self):
        """~16 KB of structured text."""
        lines = []
        for i in range(400):
            lines.append(f"Line {i:04d}: the quick brown fox jumped over the lazy dog\n".encode())
        data = b"".join(lines)
        assert _roundtrip_with_tool(data)

    def test_long_run_single_byte(self):
        """Very long single-byte run (~64KB) tests continuation byte encoding."""
        data = bytes([0xFF]) * 65000
        assert _roundtrip_with_tool(data)


# ================================================================
#  Cross-verification with reference LZ4
# ================================================================

class TestCrossVerification:
    """Interoperability with Python lz4 reference library."""

    def test_our_compress_ref_decompress_text(self):
        """Our compressor output must be decodable by reference."""
        text = b"The quick brown fox jumps over the lazy dog. " * 50
        compressed, orig_size = _compress_with_tool(text)
        decompressed = lz4.block.decompress(compressed,
                                            uncompressed_size=orig_size)
        assert decompressed == text

    def test_our_compress_ref_decompress_repetitive(self):
        """Repetitive data: our compress -> ref decompress."""
        data = b"ABCDEFGH" * 200
        compressed, orig_size = _compress_with_tool(data)
        decompressed = lz4.block.decompress(compressed,
                                            uncompressed_size=orig_size)
        assert decompressed == data

    def test_our_compress_ref_decompress_single_byte_run(self):
        """Single byte run: our compress -> ref decompress."""
        data = bytes([0xAA]) * 1000
        compressed, orig_size = _compress_with_tool(data)
        decompressed = lz4.block.decompress(compressed,
                                            uncompressed_size=orig_size)
        assert decompressed == data

    def test_ref_compress_our_decompress_text(self):
        """Reference compressed data must be decodable by us."""
        text = b"Pack my box with five dozen liquor jugs. " * 50
        compressed = lz4.block.compress(text, store_size=False)
        decompressed = _decompress_with_tool(compressed, len(text))
        assert decompressed == text

    def test_ref_compress_our_decompress_repetitive(self):
        """Repetitive data: ref compress -> our decompress."""
        data = bytes([0xBB]) * 1000
        compressed = lz4.block.compress(data, store_size=False)
        decompressed = _decompress_with_tool(compressed, len(data))
        assert decompressed == data

    def test_ref_compress_our_decompress_binary(self):
        """Binary data: ref compress -> our decompress."""
        data = bytes(range(256)) * 8
        compressed = lz4.block.compress(data, store_size=False)
        decompressed = _decompress_with_tool(compressed, len(data))
        assert decompressed == data

    def test_bidirectional_various_sizes(self):
        """Cross-verify at multiple input sizes in both directions."""
        for size in [20, 50, 100, 500, 1000, 5000]:
            data = (b"test data for compression ") * (size // 25 + 1)
            data = data[:size]

            # Our compress -> ref decompress
            compressed, orig_size = _compress_with_tool(data)
            dec = lz4.block.decompress(compressed,
                                       uncompressed_size=orig_size)
            assert dec == data, f"our->ref failed at size {size}"

            # Ref compress -> our decompress
            ref_comp = lz4.block.compress(data, store_size=False)
            dec2 = _decompress_with_tool(ref_comp, len(data))
            assert dec2 == data, f"ref->our failed at size {size}"

    def test_cross_long_literal_runs(self):
        """Data with long non-compressible sections."""
        random.seed(77777)
        data = bytes(random.randint(0, 255) for _ in range(300))
        # Ref compress -> our decompress (literal-heavy)
        ref_comp = lz4.block.compress(data, store_size=False)
        dec = _decompress_with_tool(ref_comp, len(data))
        assert dec == data


# ================================================================
#  Compression ratio tests
# ================================================================

class TestCompressionRatio:
    """Verify that compression achieves reasonable ratios."""

    def test_english_text_ratio(self):
        """English text should compress >= 2x."""
        text = (b"The quick brown fox jumps over the lazy dog. "
                b"Pack my box with five dozen liquor jugs. ") * 100
        compressed, _ = _compress_with_tool(text)
        ratio = len(text) / len(compressed)
        assert ratio >= 2.0, f"Ratio {ratio:.2f} < 2.0 on English text"

    def test_repetitive_pattern_ratio(self):
        """Repeated 4-byte pattern should compress >= 5x."""
        data = b"ABCD" * 1000
        compressed, _ = _compress_with_tool(data)
        ratio = len(data) / len(compressed)
        assert ratio >= 5.0, f"Ratio {ratio:.2f} < 5.0 on repetitive data"

    def test_single_byte_ratio(self):
        """Single repeated byte should compress very well (>= 10x)."""
        data = bytes([0x00]) * 4000
        compressed, _ = _compress_with_tool(data)
        ratio = len(data) / len(compressed)
        assert ratio >= 10.0, f"Ratio {ratio:.2f} < 10.0 on single-byte data"


# ================================================================
#  Edge case tests
# ================================================================

class TestEdgeCases:
    """Test boundary conditions and special scenarios."""

    def test_just_under_compress_threshold(self):
        """12 bytes: below compression threshold, literal-only."""
        data = b"hello world!"
        assert _roundtrip_with_tool(data)

    def test_at_compress_threshold(self):
        """13 bytes: minimum for independent block compression."""
        data = b"AAAA123456AAA"
        assert _roundtrip_with_tool(data)

    def test_incompressible_random(self):
        """Pure random data: no useful matches expected."""
        random.seed(12345)
        data = bytes(random.randint(0, 255) for _ in range(200))
        assert _roundtrip_with_tool(data)

    def test_long_match_continuation(self):
        """Match length > 18 requires continuation bytes."""
        # 300 identical bytes -> very long match
        data = b"ABCD" + bytes([0x58]) * 300 + b"EFGH"
        assert _roundtrip_with_tool(data)

    def test_large_offset_match(self):
        """Test match with offset near MAX_DISTANCE (65535)."""
        pattern = b"UNIQUE_PATTERN!!"
        # 60000 bytes of filler, then the pattern again
        filler = bytes(range(256)) * 235
        data = pattern + filler[:60000] + pattern
        assert _roundtrip_with_tool(data)

    def test_overlap_offset_1(self):
        """Offset=1 overlap: last byte repeated many times."""
        # This creates a single match with offset=1
        data = b"X" + b"X" * 499
        compressed, orig_size = _compress_with_tool(data)
        # Cross-verify too
        dec = lz4.block.decompress(compressed, uncompressed_size=orig_size)
        assert dec == data

    def test_overlap_offset_2(self):
        """Offset=2 overlap: two-byte pattern repeated."""
        data = b"AB" * 250
        compressed, orig_size = _compress_with_tool(data)
        dec = lz4.block.decompress(compressed, uncompressed_size=orig_size)
        assert dec == data

    def test_overlap_offset_3(self):
        """Offset=3 overlap: three-byte pattern repeated."""
        data = b"XYZ" * 200
        compressed, orig_size = _compress_with_tool(data)
        dec = lz4.block.decompress(compressed, uncompressed_size=orig_size)
        assert dec == data

    def test_long_literal_then_match(self):
        """Long literal run (>270 bytes) followed by a match."""
        random.seed(99999)
        unique = bytes(random.randint(0, 255) for _ in range(300))
        repeated = b"MATCH_THIS_PATTERN!!" * 20
        data = unique + repeated
        assert _roundtrip_with_tool(data)
        compressed, orig_size = _compress_with_tool(data)
        dec = lz4.block.decompress(compressed, uncompressed_size=orig_size)
        assert dec == data


# ================================================================
#  Block analysis tests
# ================================================================

class TestAnalyze:
    """Tests for the lz4c analyze command."""

    def test_analyze_empty_block_no_data(self):
        """File with 4-byte header only (original_size=0, no block data)."""
        filepath = _write_compressed_file(b"", 0)
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["original_size"] == 0
            assert result["compressed_size"] == 0
            assert result["num_sequences"] == 0
            assert result["total_literal_bytes"] == 0
            assert result["total_match_bytes"] == 0
            assert result["max_offset"] == 0
            assert result["max_match_length"] == 0
            assert result["num_overlap_matches"] == 0
        finally:
            os.unlink(filepath)

    def test_analyze_empty_token(self):
        """Block with just a 0x00 token (empty input representation per spec)."""
        filepath = _write_compressed_file(b"\x00", 0)
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["original_size"] == 0
            assert result["compressed_size"] == 1
            assert result["num_sequences"] == 1
            assert result["total_literal_bytes"] == 0
            assert result["total_match_bytes"] == 0
        finally:
            os.unlink(filepath)

    def test_analyze_literal_only_small(self):
        """Small input that can only be encoded as literals."""
        data = b"Hello"
        compressed = lz4.block.compress(data, store_size=False)
        filepath = _write_compressed_file(compressed, len(data))
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["original_size"] == 5
            assert result["total_literal_bytes"] == 5
            assert result["total_match_bytes"] == 0
            assert result["max_offset"] == 0
            assert result["max_match_length"] == 0
            assert result["num_overlap_matches"] == 0
            assert result["num_sequences"] >= 1
        finally:
            os.unlink(filepath)

    def test_analyze_compressible_consistency(self):
        """Compressible data: literal + match bytes must equal original size."""
        data = b"ABCDEFGH" * 100
        compressed = lz4.block.compress(data, store_size=False)
        filepath = _write_compressed_file(compressed, len(data))
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["original_size"] == 800
            assert result["compressed_size"] == len(compressed)
            lits = result["total_literal_bytes"]
            matches = result["total_match_bytes"]
            assert lits + matches == 800, \
                f"literal({lits}) + match({matches}) != 800"
            assert matches > 0, "Expected matches for repetitive data"
            assert result["max_offset"] > 0
            assert result["max_match_length"] >= 4
            assert result["num_sequences"] >= 2
        finally:
            os.unlink(filepath)

    def test_analyze_overlap_detection(self):
        """Single-byte run creates overlap matches (offset < match_length)."""
        data = bytes([0xAA]) * 500
        compressed = lz4.block.compress(data, store_size=False)
        filepath = _write_compressed_file(compressed, len(data))
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["num_overlap_matches"] > 0, \
                "Expected overlap matches for single-byte run"
            lits = result["total_literal_bytes"]
            matches = result["total_match_bytes"]
            assert lits + matches == 500
        finally:
            os.unlink(filepath)

    def test_analyze_long_match_lengths(self):
        """Very long single-byte run requires continuation bytes in match."""
        data = bytes([0x42]) * 5000
        compressed = lz4.block.compress(data, store_size=False)
        filepath = _write_compressed_file(compressed, len(data))
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            lits = result["total_literal_bytes"]
            matches = result["total_match_bytes"]
            assert lits + matches == 5000
            assert result["max_match_length"] > 100, \
                "Expected large max_match_length for long single-byte run"
            assert result["num_overlap_matches"] > 0
        finally:
            os.unlink(filepath)

    def test_analyze_json_has_all_keys(self):
        """Output JSON must contain all required keys."""
        data = b"test data for analysis " * 20
        compressed = lz4.block.compress(data, store_size=False)
        filepath = _write_compressed_file(compressed, len(data))
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            required_keys = [
                "original_size", "compressed_size", "num_sequences",
                "total_literal_bytes", "total_match_bytes",
                "max_offset", "max_match_length", "num_overlap_matches"
            ]
            for key in required_keys:
                assert key in result, f"Missing key: {key}"
                assert isinstance(result[key], int), \
                    f"Key {key} must be integer, got {type(result[key])}"
        finally:
            os.unlink(filepath)

    def test_analyze_invalid_zero_offset(self):
        """Block with offset=0 must be rejected."""
        # Token: 0x10 (1 literal, match nibble=0 -> match_len=4)
        # Literal: 'A'
        # Offset: 0x00 0x00 (invalid zero offset)
        block = bytes([0x10, 0x41, 0x00, 0x00])
        filepath = _write_compressed_file(block, 5)
        try:
            r = _run_analyze(filepath)
            assert r.returncode != 0, \
                "analyze should reject block with zero offset"
        finally:
            os.unlink(filepath)

    def test_analyze_truncated_literals(self):
        """Block where literal data is truncated must be rejected."""
        # Token: 0x50 (5 literals expected) but no literal bytes follow
        block = bytes([0x50])
        filepath = _write_compressed_file(block, 5)
        try:
            r = _run_analyze(filepath)
            assert r.returncode != 0, \
                "analyze should reject truncated literal data"
        finally:
            os.unlink(filepath)

    def test_analyze_truncated_offset(self):
        """Block where offset bytes are truncated must be rejected."""
        # Token: 0x11 (1 literal, match nibble=1)
        # Literal: 'A'
        # Only 1 byte of offset (need 2)
        block = bytes([0x11, 0x41, 0x01])
        filepath = _write_compressed_file(block, 6)
        try:
            r = _run_analyze(filepath)
            assert r.returncode != 0, \
                "analyze should reject truncated offset"
        finally:
            os.unlink(filepath)

    def test_analyze_self_compressed_text(self):
        """Analyze data compressed by our own (fixed) compressor."""
        data = b"The quick brown fox jumps over the lazy dog. " * 50
        compressed, orig_size = _compress_with_tool(data)
        filepath = _write_compressed_file(compressed, orig_size)
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            assert result["original_size"] == orig_size
            assert result["compressed_size"] == len(compressed)
            lits = result["total_literal_bytes"]
            matches = result["total_match_bytes"]
            assert lits + matches == orig_size, \
                f"literal({lits}) + match({matches}) != {orig_size}"
        finally:
            os.unlink(filepath)

    def test_analyze_self_compressed_repetitive(self):
        """Analyze repetitive data compressed by our own compressor."""
        data = b"XY" * 300
        compressed, orig_size = _compress_with_tool(data)
        filepath = _write_compressed_file(compressed, orig_size)
        try:
            r = _run_analyze(filepath)
            assert r.returncode == 0, f"analyze failed: {r.stderr.decode()}"
            result = json.loads(r.stdout.decode())
            lits = result["total_literal_bytes"]
            matches = result["total_match_bytes"]
            assert lits + matches == orig_size
            assert result["num_overlap_matches"] > 0, \
                "Expected overlap matches for 2-byte repeating pattern"
        finally:
            os.unlink(filepath)
