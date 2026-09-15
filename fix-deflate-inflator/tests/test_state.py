"""
Verification tests for the zinflate DEFLATE/zlib decompressor.

Compresses data with Python's zlib, decompresses with the Rust binary,
and verifies byte-identical output.
"""


import hashlib
import os
import subprocess
import tempfile
import zlib

import pytest

BINARY = "/app/target/release/zinflate"


def decompress_with_zinflate(compressed_data: bytes, raw: bool = False) -> bytes:
    """Run the zinflate binary and return decompressed output."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as inf:
        inf.write(compressed_data)
        inf_path = inf.name

    out_path = inf_path + ".out"
    try:
        cmd = [BINARY]
        if raw:
            cmd.append("--raw")
        cmd.extend([inf_path, out_path])

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(
                f"zinflate exited with code {result.returncode}: "
                f"{result.stderr.decode(errors='replace')}"
            )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in (inf_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


def compress_raw(data: bytes, level: int = 6) -> bytes:
    """Compress to raw DEFLATE (no zlib wrapper)."""
    obj = zlib.compressobj(level, zlib.DEFLATED, -15)
    return obj.compress(data) + obj.flush()


class TestStoredBlocks:
    """Tests for BTYPE=00 (no compression / stored blocks)."""

    def test_200_bytes_stored(self):
        data = bytes(range(200))
        compressed = zlib.compress(data, 0)
        assert decompress_with_zinflate(compressed) == data

    def test_1kb_all_byte_values(self):
        data = bytes(range(256)) * 4  # 1024 bytes
        compressed = zlib.compress(data, 0)
        assert decompress_with_zinflate(compressed) == data

    def test_4kb_stored_multiblock(self):
        data = bytes([i % 256 for i in range(4096)])
        compressed = zlib.compress(data, 0)
        assert decompress_with_zinflate(compressed) == data


class TestFixedHuffman:
    """Tests for BTYPE=01 (fixed Huffman codes)."""

    def test_short_string_level1(self):
        data = b"Hello, DEFLATE world! This is a test of fixed Huffman coding."
        compressed = zlib.compress(data, 1)
        assert decompress_with_zinflate(compressed) == data

    def test_repetitive_short(self):
        data = b"ABCABC" * 50
        compressed = zlib.compress(data, 1)
        assert decompress_with_zinflate(compressed) == data


class TestDynamicHuffman:
    """Tests for BTYPE=10 (dynamic Huffman codes)."""

    def test_highly_repetitive_data(self):
        """Long runs trigger large back-references with dynamic trees."""
        data = (b"The quick brown fox jumps over the lazy dog. " * 200)
        compressed = zlib.compress(data, 6)
        assert decompress_with_zinflate(compressed) == data

    def test_many_md5_digests(self):
        """500 hex MD5 digests: diverse byte distribution, dynamic Huffman."""
        parts = []
        for i in range(500):
            h = hashlib.md5(f"seed-{i}".encode()).hexdigest()
            parts.append(h.encode() + b"\n")
        data = b"".join(parts)
        compressed = zlib.compress(data, 6)
        assert decompress_with_zinflate(compressed) == data

    def test_10k_zeros(self):
        """10 KB of zeros: extreme RLE via distance-1 back-references."""
        data = b"\x00" * 10240
        compressed = zlib.compress(data, 9)
        assert decompress_with_zinflate(compressed) == data

    def test_5k_same_nonzero_byte(self):
        data = b"\xAA" * 5120
        compressed = zlib.compress(data, 9)
        assert decompress_with_zinflate(compressed) == data

    def test_natural_language_max_compression(self):
        """Natural language text at level 9 (maximum compression)."""
        text = (
            "In computer science, Huffman coding is a particular type of "
            "optimal prefix code that is commonly used for lossless data "
            "compression. The process of finding or using such a code is "
            "called Huffman coding, an algorithm developed by David A. "
            "Huffman while he was a Sc.D. student at MIT, and published "
            "in the 1952 paper 'A Method for the Construction of Minimum-"
            "Redundancy Codes'. "
        )
        data = (text * 20).encode()
        compressed = zlib.compress(data, 9)
        assert decompress_with_zinflate(compressed) == data

    def test_mixed_entropy_data(self):
        """Data with alternating high-entropy and low-entropy regions."""
        parts = []
        for i in range(100):
            h = hashlib.sha256(f"block-{i}".encode()).digest()
            parts.append(h)
            parts.append(bytes([i % 256]) * 64)
        data = b"".join(parts)
        compressed = zlib.compress(data, 6)
        assert decompress_with_zinflate(compressed) == data


class TestRawDeflate:
    """Tests with --raw flag (no zlib wrapper)."""

    def test_raw_stored_blocks(self):
        data = bytes(range(128))
        compressed = compress_raw(data, 0)
        assert decompress_with_zinflate(compressed, raw=True) == data

    def test_raw_compressed_level6(self):
        data = b"Raw DEFLATE test data with some repetition. " * 100
        compressed = compress_raw(data, 6)
        assert decompress_with_zinflate(compressed, raw=True) == data

    def test_sha256_digests_raw(self):
        """200 SHA-256 digests as raw DEFLATE (exercises large distance codes)."""
        parts = []
        for i in range(200):
            h = hashlib.sha256(f"raw-{i}".encode()).hexdigest()
            parts.append(h.encode() + b"\n")
        data = b"".join(parts)
        compressed = compress_raw(data, 6)
        assert decompress_with_zinflate(compressed, raw=True) == data

    def test_raw_large_distances(self):
        """Data producing back-references with many distance extra bits."""
        base_parts = []
        for i in range(640):
            h = hashlib.sha256(f"dist-{i}".encode()).digest()
            base_parts.append(h)
        base_data = b"".join(base_parts)  # 20480 bytes
        # Repeat first 2KB at end: distance ~20KB needs ~11 extra bits
        data = base_data + base_data[:2048]
        compressed = compress_raw(data, 6)
        assert decompress_with_zinflate(compressed, raw=True) == data


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_input(self):
        data = b""
        compressed = zlib.compress(data)
        assert decompress_with_zinflate(compressed) == data

    def test_single_byte(self):
        data = b"\x42"
        compressed = zlib.compress(data)
        assert decompress_with_zinflate(compressed) == data

    def test_large_varied_data(self):
        """~51 KB of varied byte patterns exercising diverse distance codes."""
        data = bytes([((i * 131 + 17) ^ (i >> 3)) & 0xFF for i in range(52000)])
        compressed = zlib.compress(data, 6)
        assert decompress_with_zinflate(compressed) == data

    def test_full_byte_range_repeated(self):
        """All 256 byte values repeated many times — diverse Huffman codes."""
        data = bytes(range(256)) * 128  # 32768 bytes
        compressed = zlib.compress(data, 6)
        assert decompress_with_zinflate(compressed) == data

    def test_stdin_stdout_mode(self):
        """Verify stdin/stdout mode works (no file arguments)."""
        data = b"Testing stdin/stdout decompression mode.\n" * 10
        compressed = zlib.compress(data, 6)
        result = subprocess.run(
            [BINARY],
            input=compressed,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert result.stdout == data
