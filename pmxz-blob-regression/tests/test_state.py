
"""Tests for PMXZ process map serialization: v2 bug fix, cross-module version
consistency (get_format_info, validate_serialized_data), v3 format with
zlib/lzma/zstd, CRC32 integrity, migration tool, and sha256sum manifest.
"""

import struct
import zlib
import os
import sys
import json
import subprocess
import hashlib
import tempfile
import pytest

sys.path.insert(0, '/app')

from procmap.generator import generate_procmap, parse_procmap
from procmap.serialize import deserialize_procmap, get_format_info

try:
    from procmap.serialize import serialize_procmap_v3
except (ImportError, AttributeError, SyntaxError):
    serialize_procmap_v3 = None

from procmap.validate import validate_serialized_data


# ---------------------------------------------------------------------------
# v2 bug fix tests
# ---------------------------------------------------------------------------
class TestV2BugFix:
    """Verify that v2 format deserialization works after the fix."""

    @staticmethod
    def _make_v2_blob(procmap_str):
        """Manually construct a v2 blob: magic(4) + version(1) + len(4) + zlib."""
        raw = procmap_str.encode('utf-8')
        compressed = zlib.compress(raw, 6)
        return b"PMXZ" + bytes([2]) + struct.pack(">I", len(raw)) + compressed

    def test_v2_1500_procs(self):
        pm = generate_procmap(1500, 10)
        blob = self._make_v2_blob(pm)
        assert deserialize_procmap(blob) == pm

    def test_v2_5000_procs(self):
        pm = generate_procmap(5000, 32)
        blob = self._make_v2_blob(pm)
        assert deserialize_procmap(blob) == pm

    def test_v2_10000_procs(self):
        pm = generate_procmap(10000, 64)
        blob = self._make_v2_blob(pm)
        assert deserialize_procmap(blob) == pm

    def test_v2_boundary_1042_procs(self):
        """The exact process count from the original regression."""
        pm = generate_procmap(1042, 9)
        blob = self._make_v2_blob(pm)
        assert deserialize_procmap(blob) == pm


# ---------------------------------------------------------------------------
# v1 backward compatibility tests
# ---------------------------------------------------------------------------
class TestV1BackwardCompat:
    """Verify that v1 format (no version byte) still deserializes."""

    @staticmethod
    def _make_v1_blob(procmap_str):
        """Manually construct a v1 blob: magic(4) + len(4) + zlib."""
        raw = procmap_str.encode('utf-8')
        compressed = zlib.compress(raw, 6)
        return b"PMXZ" + struct.pack(">I", len(raw)) + compressed

    def test_v1_2000_procs(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        assert deserialize_procmap(blob) == pm

    def test_v1_8000_procs(self):
        pm = generate_procmap(8000, 50)
        blob = self._make_v1_blob(pm)
        assert deserialize_procmap(blob) == pm

    def test_v1_data_integrity(self):
        pm = generate_procmap(3000, 20)
        blob = self._make_v1_blob(pm)
        result = deserialize_procmap(blob)
        parsed = parse_procmap(result)
        all_ranks = []
        for ranks in parsed.values():
            all_ranks.extend(ranks)
        assert sorted(all_ranks) == list(range(3000))
        assert len(parsed) == 20


# ---------------------------------------------------------------------------
# Existing API preservation
# ---------------------------------------------------------------------------
class TestExistingApiPreserved:
    """Verify the original serialize_procmap/deserialize_procmap still works."""

    @pytest.mark.parametrize("nprocs,nnodes", [
        (100, 4),
        (500, 8),
        (2000, 16),
        (5000, 32),
    ])
    def test_original_roundtrip(self, nprocs, nnodes):
        from procmap.serialize import serialize_procmap
        pm = generate_procmap(nprocs, nnodes)
        assert deserialize_procmap(serialize_procmap(pm)) == pm


# ---------------------------------------------------------------------------
# get_format_info cross-version correctness
# ---------------------------------------------------------------------------
class TestGetFormatInfo:
    """Verify get_format_info returns correct metadata for all versions.

    The function must use the version-detection heuristic from REQUIREMENTS_V3.md
    consistently, not hardcode v2 offsets for all blob formats.
    """

    @staticmethod
    def _make_v1_blob(procmap_str):
        raw = procmap_str.encode('utf-8')
        compressed = zlib.compress(raw, 6)
        return b"PMXZ" + struct.pack(">I", len(raw)) + compressed

    @staticmethod
    def _make_v2_blob(procmap_str):
        raw = procmap_str.encode('utf-8')
        compressed = zlib.compress(raw, 6)
        return b"PMXZ" + bytes([2]) + struct.pack(">I", len(raw)) + compressed

    def test_raw_format(self):
        pm = generate_procmap(50, 2)
        data = b"raw:" + pm.encode('utf-8')
        info = get_format_info(data)
        assert info["format"] == "raw"
        assert info["payload_size"] == len(pm.encode('utf-8'))

    def test_v1_version_is_1(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        info = get_format_info(blob)
        assert info["version"] == 1, \
            f"v1 blob: expected version=1, got {info['version']}"

    def test_v1_header_size_is_8(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        info = get_format_info(blob)
        assert info["header_size"] == 8, \
            f"v1 blob: expected header_size=8, got {info['header_size']}"

    def test_v1_uncompressed_size(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        info = get_format_info(blob)
        expected = len(pm.encode('utf-8'))
        assert info["uncompressed_size"] == expected, \
            f"v1 blob: expected uncompressed_size={expected}, got {info['uncompressed_size']}"

    def test_v1_payload_size(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        info = get_format_info(blob)
        assert info["payload_size"] == len(blob) - 8, \
            f"v1 blob: expected payload_size={len(blob) - 8}, got {info['payload_size']}"

    def test_v2_version_is_2(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v2_blob(pm)
        info = get_format_info(blob)
        assert info["version"] == 2

    def test_v2_header_size_is_9(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v2_blob(pm)
        info = get_format_info(blob)
        assert info["header_size"] == 9

    def test_v2_uncompressed_size(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v2_blob(pm)
        info = get_format_info(blob)
        expected = len(pm.encode('utf-8'))
        assert info["uncompressed_size"] == expected

    def test_v3_version_is_3(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        info = get_format_info(blob)
        assert info["version"] == 3, \
            f"v3 blob: expected version=3, got {info['version']}"

    def test_v3_header_size_is_18(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        info = get_format_info(blob)
        assert info["header_size"] == 18, \
            f"v3 blob: expected header_size=18, got {info['header_size']}"

    def test_v3_uncompressed_size(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        info = get_format_info(blob)
        expected = len(pm.encode('utf-8'))
        assert info["uncompressed_size"] == expected, \
            f"v3 blob: expected uncompressed_size={expected}, got {info['uncompressed_size']}"

    def test_v3_payload_size(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        info = get_format_info(blob)
        assert info["payload_size"] == len(blob) - 18, \
            f"v3 blob: expected payload_size={len(blob) - 18}, got {info['payload_size']}"


# ---------------------------------------------------------------------------
# validate_serialized_data cross-version correctness
# ---------------------------------------------------------------------------
class TestValidateSerializedData:
    """Verify validate_serialized_data accepts all valid format versions
    and returns correct per-version metadata.
    """

    @staticmethod
    def _make_v1_blob(procmap_str):
        raw = procmap_str.encode('utf-8')
        compressed = zlib.compress(raw, 6)
        return b"PMXZ" + struct.pack(">I", len(raw)) + compressed

    def test_accepts_raw(self):
        pm = generate_procmap(50, 2)
        data = b"raw:" + pm.encode('utf-8')
        result = validate_serialized_data(data)
        assert result["format"] == "raw"

    def test_accepts_v1_with_correct_version(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        result = validate_serialized_data(blob)
        assert result["format"] == "blob"
        assert result["version"] == 1, \
            f"v1 blob: expected version=1, got {result['version']}"

    def test_v1_payload_size(self):
        pm = generate_procmap(2000, 16)
        blob = self._make_v1_blob(pm)
        result = validate_serialized_data(blob)
        assert result["payload_size"] == len(blob) - 8, \
            f"v1 blob: expected payload_size={len(blob) - 8}, got {result['payload_size']}"

    def test_accepts_v2(self):
        pm = generate_procmap(2000, 16)
        raw = pm.encode('utf-8')
        blob = b"PMXZ" + bytes([2]) + struct.pack(">I", len(raw)) + zlib.compress(raw, 6)
        result = validate_serialized_data(blob)
        assert result["format"] == "blob"
        assert result["version"] == 2

    def test_accepts_v3(self):
        """v3 blobs must not be rejected by validation."""
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        result = validate_serialized_data(blob)
        assert result["format"] == "blob"
        assert result["version"] == 3

    def test_v3_payload_size(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(2000, 16)
        blob = serialize_procmap_v3(pm)
        result = validate_serialized_data(blob)
        assert result["payload_size"] == len(blob) - 18, \
            f"v3 blob: expected payload_size={len(blob) - 18}, got {result['payload_size']}"


# ---------------------------------------------------------------------------
# v3 format existence
# ---------------------------------------------------------------------------
class TestV3Exists:
    """Verify serialize_procmap_v3 is implemented."""

    def test_function_exists(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented in procmap.serialize"

    def test_callable(self):
        assert serialize_procmap_v3 is not None
        assert callable(serialize_procmap_v3)

    def test_accepts_algorithm_param(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(10, 2)
        serialize_procmap_v3(pm, algorithm='zlib')

    def test_accepts_zstd_algorithm(self):
        assert serialize_procmap_v3 is not None
        pm = generate_procmap(10, 2)
        serialize_procmap_v3(pm, algorithm='zstd')


# ---------------------------------------------------------------------------
# v3 header structure tests
# ---------------------------------------------------------------------------
class TestV3HeaderStructure:
    """Verify v3 format header follows the specification."""

    def _require_v3(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"

    def test_magic_bytes(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8))
        assert data[:4] == b"PMXZ"

    def test_version_is_3(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8))
        assert data[4] == 3, f"Expected version 3, got {data[4]}"

    def test_flags_checksum_bit_set(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8))
        flags = data[5]
        assert flags & 0x04, "Checksum bit (bit 2) must be set in v3 flags"

    def test_flags_zlib_algorithm(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8), algorithm='zlib')
        flags = data[5]
        assert (flags & 0x03) == 0, \
            f"Algorithm bits (0-1) should be 0b00 for zlib, got {flags & 0x03:#04b}"

    def test_flags_lzma_algorithm(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8), algorithm='lzma')
        flags = data[5]
        assert (flags & 0x03) == 1, \
            f"Algorithm bits (0-1) should be 0b01 for lzma, got {flags & 0x03:#04b}"

    def test_flags_zstd_algorithm(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8), algorithm='zstd')
        flags = data[5]
        assert (flags & 0x03) == 2, \
            f"Algorithm bits (0-1) should be 0b10 for zstd, got {flags & 0x03:#04b}"

    def test_flags_reserved_bits_zero(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8))
        flags = data[5]
        assert flags & 0xF8 == 0, "Reserved bits (3-7) must be zero"

    def test_uncompressed_length_field(self):
        self._require_v3()
        pm = generate_procmap(500, 8)
        data = serialize_procmap_v3(pm)
        raw = pm.encode('utf-8')
        stored_len = struct.unpack(">I", data[6:10])[0]
        assert stored_len == len(raw), \
            f"Uncompressed length: stored {stored_len} != actual {len(raw)}"

    def test_crc32_field(self):
        self._require_v3()
        pm = generate_procmap(500, 8)
        data = serialize_procmap_v3(pm)
        raw = pm.encode('utf-8')
        stored_crc = struct.unpack(">I", data[10:14])[0]
        expected_crc = zlib.crc32(raw) & 0xFFFFFFFF
        assert stored_crc == expected_crc, \
            f"CRC32: stored {stored_crc:#010x} != expected {expected_crc:#010x}"

    def test_compressed_length_field(self):
        self._require_v3()
        pm = generate_procmap(500, 8)
        data = serialize_procmap_v3(pm)
        comp_len = struct.unpack(">I", data[14:18])[0]
        actual_payload_len = len(data) - 18
        assert comp_len == actual_payload_len, \
            f"Compressed length: stored {comp_len} != actual payload {actual_payload_len}"

    def test_total_blob_size(self):
        self._require_v3()
        data = serialize_procmap_v3(generate_procmap(500, 8))
        comp_len = struct.unpack(">I", data[14:18])[0]
        assert len(data) == 18 + comp_len, \
            f"Total size {len(data)} != 18 + {comp_len}"


# ---------------------------------------------------------------------------
# v3 round-trip tests
# ---------------------------------------------------------------------------
class TestV3Roundtrip:
    """Verify v3 serialize/deserialize round-trips."""

    def _require_v3(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"

    @pytest.mark.parametrize("nprocs,nnodes", [
        (10, 2),
        (100, 4),
        (500, 8),
        (1000, 10),
        (2000, 16),
        (5000, 32),
        (10000, 64),
    ])
    def test_zlib_roundtrip(self, nprocs, nnodes):
        self._require_v3()
        pm = generate_procmap(nprocs, nnodes)
        data = serialize_procmap_v3(pm, algorithm='zlib')
        assert deserialize_procmap(data) == pm

    @pytest.mark.parametrize("nprocs,nnodes", [
        (10, 2),
        (100, 4),
        (1000, 10),
        (5000, 32),
    ])
    def test_lzma_roundtrip(self, nprocs, nnodes):
        self._require_v3()
        pm = generate_procmap(nprocs, nnodes)
        data = serialize_procmap_v3(pm, algorithm='lzma')
        assert deserialize_procmap(data) == pm

    @pytest.mark.parametrize("nprocs,nnodes", [
        (10, 2),
        (100, 4),
        (1000, 10),
        (5000, 32),
        (10000, 64),
    ])
    def test_zstd_roundtrip(self, nprocs, nnodes):
        self._require_v3()
        pm = generate_procmap(nprocs, nnodes)
        data = serialize_procmap_v3(pm, algorithm='zstd')
        assert deserialize_procmap(data) == pm

    def test_v3_data_integrity_zlib(self):
        self._require_v3()
        pm = generate_procmap(5000, 32)
        data = serialize_procmap_v3(pm)
        result = deserialize_procmap(data)
        parsed = parse_procmap(result)
        all_ranks = []
        for ranks in parsed.values():
            all_ranks.extend(ranks)
        assert sorted(all_ranks) == list(range(5000))
        assert len(parsed) == 32

    def test_v3_data_integrity_zstd(self):
        self._require_v3()
        pm = generate_procmap(5000, 32)
        data = serialize_procmap_v3(pm, algorithm='zstd')
        result = deserialize_procmap(data)
        parsed = parse_procmap(result)
        all_ranks = []
        for ranks in parsed.values():
            all_ranks.extend(ranks)
        assert sorted(all_ranks) == list(range(5000))
        assert len(parsed) == 32


# ---------------------------------------------------------------------------
# v3 zstd CLI interop: verify payload is decompressable by zstd tool
# ---------------------------------------------------------------------------
class TestV3ZstdCliInterop:
    """Verify v3 zstd blobs produce payloads decompressable by external zstd tool."""

    def _require_v3(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"

    def test_zstd_payload_cli_decompress(self):
        """Extract compressed payload from v3 blob, decompress with zstd CLI."""
        self._require_v3()
        pm = generate_procmap(2000, 16)
        data = serialize_procmap_v3(pm, algorithm='zstd')
        comp_len = struct.unpack(">I", data[14:18])[0]
        payload = data[18:18 + comp_len]

        with tempfile.NamedTemporaryFile(suffix='.zst', delete=False) as tf:
            tf.write(payload)
            tf_path = tf.name

        out_path = tf_path + '.raw'
        try:
            result = subprocess.run(
                ['zstd', '-d', tf_path, '-o', out_path, '--force'],
                capture_output=True, timeout=10
            )
            assert result.returncode == 0, \
                f"zstd CLI decompression failed: {result.stderr.decode()}"

            with open(out_path, 'rb') as f:
                decompressed = f.read()

            assert decompressed.decode('utf-8') == pm, \
                "zstd CLI decompressed data doesn't match original procmap"
        finally:
            for p in [tf_path, out_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_zstd_payload_cli_large(self):
        """Same interop test with a larger process map."""
        self._require_v3()
        pm = generate_procmap(8000, 50)
        data = serialize_procmap_v3(pm, algorithm='zstd')
        comp_len = struct.unpack(">I", data[14:18])[0]
        payload = data[18:18 + comp_len]

        with tempfile.NamedTemporaryFile(suffix='.zst', delete=False) as tf:
            tf.write(payload)
            tf_path = tf.name

        out_path = tf_path + '.raw'
        try:
            result = subprocess.run(
                ['zstd', '-d', tf_path, '-o', out_path, '--force'],
                capture_output=True, timeout=10
            )
            assert result.returncode == 0, \
                f"zstd CLI decompression failed: {result.stderr.decode()}"

            with open(out_path, 'rb') as f:
                decompressed = f.read()

            assert decompressed.decode('utf-8') == pm
        finally:
            for p in [tf_path, out_path]:
                if os.path.exists(p):
                    os.unlink(p)


# ---------------------------------------------------------------------------
# v3 CRC32 integrity tests
# ---------------------------------------------------------------------------
class TestV3Integrity:
    """Verify CRC32 integrity checking in v3 format."""

    def _require_v3(self):
        assert serialize_procmap_v3 is not None, \
            "serialize_procmap_v3 must be implemented"

    def test_crc_field_tamper_detected(self):
        self._require_v3()
        pm = generate_procmap(1000, 10)
        data = serialize_procmap_v3(pm)
        tampered = bytearray(data)
        tampered[12] ^= 0xFF
        with pytest.raises(ValueError, match="(?i)crc"):
            deserialize_procmap(bytes(tampered))

    def test_tampered_payload_raises(self):
        self._require_v3()
        pm = generate_procmap(1000, 10)
        data = serialize_procmap_v3(pm)
        tampered = bytearray(data)
        if len(tampered) > 20:
            tampered[20] ^= 0xFF
        with pytest.raises(Exception):
            deserialize_procmap(bytes(tampered))

    def test_untampered_succeeds(self):
        self._require_v3()
        pm = generate_procmap(1000, 10)
        data = serialize_procmap_v3(pm)
        assert deserialize_procmap(data) == pm

    def test_crc_tamper_zstd(self):
        """CRC32 tamper detection for zstd-compressed v3 blob."""
        self._require_v3()
        pm = generate_procmap(1000, 10)
        data = serialize_procmap_v3(pm, algorithm='zstd')
        tampered = bytearray(data)
        tampered[12] ^= 0xFF
        with pytest.raises(ValueError, match="(?i)crc"):
            deserialize_procmap(bytes(tampered))

    def test_crc_tamper_lzma(self):
        """CRC32 tamper detection for lzma-compressed v3 blob."""
        self._require_v3()
        pm = generate_procmap(1000, 10)
        data = serialize_procmap_v3(pm, algorithm='lzma')
        tampered = bytearray(data)
        tampered[12] ^= 0xFF
        with pytest.raises(ValueError, match="(?i)crc"):
            deserialize_procmap(bytes(tampered))


# ---------------------------------------------------------------------------
# Migration tool tests
# ---------------------------------------------------------------------------
LEGACY_DIR = "/app/data/legacy"
REPORT_PATH = os.path.join(LEGACY_DIR, "migration_report.json")
CHECKSUMS_PATH = os.path.join(LEGACY_DIR, "migration_checksums.sha256")

EXPECTED_FILES = {
    "small_50.pmx": (50, 2),
    "medium_200.pmx": (200, 4),
    "medium_500.pmx": (500, 8),
    "v1_1200.pmx": (1200, 10),
    "v1_3000.pmx": (3000, 20),
    "v1_6000.pmx": (6000, 40),
    "v2_1500.pmx": (1500, 12),
    "v2_4000.pmx": (4000, 25),
    "v2_8000.pmx": (8000, 50),
}


class TestMigrationTool:
    """Verify the migration tool exists, runs, and produces correct results."""

    @classmethod
    def setup_class(cls):
        """Regenerate legacy data and run migration before all tests."""
        if os.path.isfile("/app/gen_legacy_data.py"):
            subprocess.run(
                ["python3", "/app/gen_legacy_data.py"],
                capture_output=True, timeout=30
            )

        cls.migration_ran = False
        cls.migration_result = None
        if os.path.isfile("/app/migrate.py"):
            cls.migration_result = subprocess.run(
                ["python3", "/app/migrate.py", LEGACY_DIR],
                capture_output=True, text=True, timeout=60
            )
            cls.migration_ran = (cls.migration_result.returncode == 0)

    def test_migrate_py_exists(self):
        assert os.path.isfile("/app/migrate.py"), \
            "/app/migrate.py must be created"

    def test_migration_exit_code(self):
        assert self.migration_result is not None, "Migration did not run"
        assert self.migration_result.returncode == 0, \
            f"Migration failed (rc={self.migration_result.returncode}): " \
            f"{self.migration_result.stderr}"

    def test_report_file_exists(self):
        assert self.migration_ran, "Migration did not complete"
        assert os.path.isfile(REPORT_PATH), \
            f"Migration report not found at {REPORT_PATH}"

    def test_report_has_required_fields(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        for field in ["total_files", "migrated", "errors",
                       "by_source_format", "error_files"]:
            assert field in report, f"Report missing field: {field}"

    def test_report_total_files(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert report["total_files"] == 10, \
            f"Expected 10 total files, got {report['total_files']}"

    def test_report_migrated_count(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert report["migrated"] == 9, \
            f"Expected 9 migrated, got {report['migrated']}"

    def test_report_error_count(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert report["errors"] == 1, \
            f"Expected 1 error, got {report['errors']}"

    def test_report_corrupted_file_in_errors(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert "corrupted_job.pmx" in report["error_files"], \
            f"corrupted_job.pmx not in error_files: {report['error_files']}"

    def test_report_source_format_raw_count(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        fmt = report["by_source_format"]
        assert fmt.get("raw", 0) == 3, \
            f"Expected 3 raw files, got {fmt.get('raw', 0)}"

    def test_report_source_format_v1_count(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        fmt = report["by_source_format"]
        assert fmt.get("v1", 0) == 3, \
            f"Expected 3 v1 files, got {fmt.get('v1', 0)}"

    def test_report_source_format_v2_count(self):
        assert self.migration_ran, "Migration did not complete"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        fmt = report["by_source_format"]
        assert fmt.get("v2", 0) == 3, \
            f"Expected 3 v2 files, got {fmt.get('v2', 0)}"

    def test_migrated_files_are_v3_format(self):
        """All successfully migrated files should now be in v3 format."""
        assert self.migration_ran, "Migration did not complete"
        for fname in EXPECTED_FILES:
            path = os.path.join(LEGACY_DIR, fname)
            assert os.path.isfile(path), f"{fname} missing after migration"
            with open(path, 'rb') as f:
                header = f.read(5)
            assert header[:4] == b"PMXZ", \
                f"{fname}: expected PMXZ magic, got {header[:4]}"
            assert header[4] == 3, \
                f"{fname}: expected version 3, got {header[4]}"

    def test_migrated_data_integrity(self):
        """Deserialized migrated data must have correct ranks and nodes."""
        assert self.migration_ran, "Migration did not complete"
        for fname, (nprocs, nnodes) in EXPECTED_FILES.items():
            path = os.path.join(LEGACY_DIR, fname)
            with open(path, 'rb') as f:
                data = f.read()
            pm_str = deserialize_procmap(data)
            parsed = parse_procmap(pm_str)

            assert len(parsed) == nnodes, \
                f"{fname}: expected {nnodes} nodes, got {len(parsed)}"
            all_ranks = []
            for ranks in parsed.values():
                all_ranks.extend(ranks)
            assert sorted(all_ranks) == list(range(nprocs)), \
                f"{fname}: rank mismatch for {nprocs} procs"


# ---------------------------------------------------------------------------
# SHA-256 checksum manifest tests
# ---------------------------------------------------------------------------
class TestMigrationChecksums:
    """Verify the migration tool produces a valid sha256sum-compatible manifest."""

    @classmethod
    def setup_class(cls):
        cls.migration_ran = os.path.isfile(REPORT_PATH)

    def test_checksums_file_exists(self):
        assert self.migration_ran, "Migration did not complete"
        assert os.path.isfile(CHECKSUMS_PATH), \
            f"SHA-256 checksums file not found at {CHECKSUMS_PATH}"

    def test_checksums_file_has_correct_line_count(self):
        assert self.migration_ran, "Migration did not complete"
        if not os.path.isfile(CHECKSUMS_PATH):
            pytest.skip("Checksums file not found")
        with open(CHECKSUMS_PATH) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 9, \
            f"Expected 9 checksum lines (one per migrated file), got {len(lines)}"

    def test_checksums_format_valid(self):
        """Each line should be '<64-hex-chars>  <filename>'."""
        assert self.migration_ran, "Migration did not complete"
        if not os.path.isfile(CHECKSUMS_PATH):
            pytest.skip("Checksums file not found")
        with open(CHECKSUMS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("  ", 1)
                assert len(parts) == 2, \
                    f"Invalid checksum line format: {line!r}"
                sha_hex, fname = parts
                assert len(sha_hex) == 64, \
                    f"SHA-256 hash wrong length ({len(sha_hex)}): {line!r}"
                assert all(c in '0123456789abcdef' for c in sha_hex), \
                    f"Invalid hex in hash: {line!r}"

    def test_sha256sum_check_passes(self):
        """Run sha256sum --check and verify all lines pass."""
        assert self.migration_ran, "Migration did not complete"
        if not os.path.isfile(CHECKSUMS_PATH):
            pytest.skip("Checksums file not found")
        result = subprocess.run(
            ['sha256sum', '--check', CHECKSUMS_PATH],
            capture_output=True, text=True, timeout=30,
            cwd=LEGACY_DIR
        )
        assert result.returncode == 0, \
            f"sha256sum --check failed:\n{result.stdout}\n{result.stderr}"

    def test_checksums_match_migrated_files(self):
        """Verify checksums in the manifest match actual file hashes."""
        assert self.migration_ran, "Migration did not complete"
        if not os.path.isfile(CHECKSUMS_PATH):
            pytest.skip("Checksums file not found")
        with open(CHECKSUMS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                sha_hex, fname = line.split("  ", 1)
                fpath = os.path.join(LEGACY_DIR, fname)
                assert os.path.isfile(fpath), f"File {fname} not found"
                with open(fpath, 'rb') as fh:
                    actual_hash = hashlib.sha256(fh.read()).hexdigest()
                assert actual_hash == sha_hex, \
                    f"Hash mismatch for {fname}: manifest={sha_hex}, actual={actual_hash}"
