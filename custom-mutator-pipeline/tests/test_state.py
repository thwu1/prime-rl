"""
Tests for AFL++ XPROTO custom mutator pipeline.

Verifies:
  - Custom mutator API completeness and correctness
  - Generated messages pass reference validator
  - CRC32 fixup in post_process
  - Structure-aware trimming
  - Havoc mutation safety
  - Build artifacts (instrumented + CmpLog binaries)
  - Seed corpus validity and diversity
"""


import importlib
import os
import struct
import subprocess
import sys
import zlib

import pytest

# Make task modules importable
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/validator")

MAGIC = b"XPR\x01"
HEADER_LEN = 12
CRC_LEN = 4
REQUIRED_FUNCTIONS = [
    "init",
    "fuzz",
    "post_process",
    "init_trim",
    "trim",
    "post_trim",
    "havoc_mutation",
    "havoc_mutation_probability",
]


# ── Mutator API tests ──────────────────────────────────────────────


class TestMutatorAPI:
    """Verify the custom mutator exports the correct AFL++ API."""

    def test_module_exists(self):
        assert os.path.exists("/app/mutator.py"), "mutator.py not found at /app/"

    def test_has_required_functions(self):
        mutator = importlib.import_module("mutator")
        for func_name in REQUIRED_FUNCTIONS:
            assert hasattr(mutator, func_name), f"Missing function: {func_name}"
            assert callable(
                getattr(mutator, func_name)
            ), f"Not callable: {func_name}"

    def test_init_does_not_crash(self):
        mutator = importlib.import_module("mutator")
        mutator.init(12345)

    def test_havoc_mutation_probability_range(self):
        mutator = importlib.import_module("mutator")
        prob = mutator.havoc_mutation_probability()
        assert isinstance(prob, int), "havoc_mutation_probability must return int"
        assert 0 <= prob <= 100, f"Probability out of range: {prob}"


# ── Mutation quality tests ──────────────────────────────────────────


class TestMutationQuality:
    """Verify fuzz() generates valid XPROTO messages."""

    def test_fuzz_produces_valid_messages(self):
        mutator = importlib.import_module("mutator")
        validate_mod = importlib.import_module("validate")
        mutator.init(42)

        for i in range(20):
            result = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
            assert isinstance(result, (bytes, bytearray)), "fuzz must return bytes"
            assert len(result) > 0, "fuzz returned empty output"
            assert len(result) <= 4096, "fuzz exceeded max_size"

            valid, info = validate_mod.validate(bytes(result))
            assert valid, f"Iteration {i}: {info}"

    def test_fuzz_respects_max_size(self):
        mutator = importlib.import_module("mutator")
        mutator.init(999)

        for _ in range(30):
            result = mutator.fuzz(bytearray(b"\x00" * 16), bytearray(b""), 128)
            assert len(result) <= 128, "Output exceeds max_size"

    def test_fuzz_with_different_seeds(self):
        """Different seeds should produce different outputs."""
        mutator = importlib.import_module("mutator")
        outputs = set()
        for seed in range(10):
            mutator.init(seed)
            result = bytes(
                mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
            )
            outputs.add(result)
        assert len(outputs) > 1, "All seeds produced identical output"


# ── Post-process tests ──────────────────────────────────────────────


class TestPostProcess:
    """Verify post_process correctly recomputes CRC32."""

    def test_fixes_corrupted_crc(self):
        mutator = importlib.import_module("mutator")
        mutator.init(99)

        msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)

        # Corrupt the last 2 bytes of the CRC
        corrupted = bytearray(msg)
        corrupted[-1] ^= 0xFF
        corrupted[-2] ^= 0xFF

        fixed = mutator.post_process(corrupted)
        fixed = bytes(fixed)

        # Verify CRC is now correct
        pre_crc = fixed[:-CRC_LEN]
        stored_crc = struct.unpack_from("<I", fixed, len(fixed) - CRC_LEN)[0]
        computed_crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
        assert stored_crc == computed_crc, (
            f"CRC mismatch after post_process: "
            f"stored={stored_crc:#010x}, computed={computed_crc:#010x}"
        )

    def test_post_process_preserves_valid_message(self):
        mutator = importlib.import_module("mutator")
        validate_mod = importlib.import_module("validate")
        mutator.init(77)

        msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
        processed = mutator.post_process(bytearray(msg))

        valid, info = validate_mod.validate(bytes(processed))
        assert valid, f"post_process broke valid message: {info}"


# ── Trimming tests ──────────────────────────────────────────────────


class TestTrimming:
    """Verify structure-aware trimming removes TLV entries correctly."""

    def test_trimming_produces_shorter_valid_message(self):
        mutator = importlib.import_module("mutator")
        validate_mod = importlib.import_module("validate")
        mutator.init(55)

        found_trimmable = False
        for _ in range(50):
            msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
            flags = struct.unpack_from("<H", msg, 6)[0]
            # Skip compressed messages (can't trim them structurally)
            if flags & 0x0001:
                continue

            payload_len = struct.unpack_from("<I", msg, 8)[0]
            if payload_len < 10:
                continue

            steps = mutator.init_trim(bytearray(msg))
            if steps > 0:
                trimmed = mutator.trim()
                trimmed = bytes(trimmed)
                assert len(trimmed) < len(msg), (
                    f"Trimmed ({len(trimmed)}) not shorter than original ({len(msg)})"
                )
                valid, info = validate_mod.validate(trimmed)
                assert valid, f"Trimmed message invalid: {info}"
                found_trimmable = True
                break

        assert found_trimmable, "No trimmable message found in 50 attempts"

    def test_post_trim_returns_valid_index(self):
        mutator = importlib.import_module("mutator")
        mutator.init(66)

        for _ in range(50):
            msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
            flags = struct.unpack_from("<H", msg, 6)[0]
            if flags & 0x0001:
                continue
            steps = mutator.init_trim(bytearray(msg))
            if steps > 0:
                mutator.trim()
                idx = mutator.post_trim(True)
                assert isinstance(idx, int), "post_trim must return int"
                assert idx >= 0, "post_trim returned negative index"
                return

        pytest.skip("Could not generate a trimmable message")


# ── Havoc mutation tests ────────────────────────────────────────────


class TestHavocMutation:
    """Verify havoc_mutation doesn't crash and returns valid buffers."""

    def test_havoc_does_not_crash(self):
        mutator = importlib.import_module("mutator")
        mutator.init(123)

        msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 4096)
        for _ in range(20):
            result = mutator.havoc_mutation(bytearray(msg), 4096)
            assert isinstance(result, (bytes, bytearray))
            assert len(result) > 0

    def test_havoc_respects_max_size(self):
        mutator = importlib.import_module("mutator")
        mutator.init(456)

        msg = mutator.fuzz(bytearray(b"\x00" * 32), bytearray(b""), 256)
        for _ in range(20):
            result = mutator.havoc_mutation(bytearray(msg), 256)
            assert len(result) <= 256


# ── Build artifact tests ───────────────────────────────────────────


class TestBuildArtifacts:
    """Verify AFL++ instrumented binaries exist and work."""

    def test_target_afl_exists(self):
        assert os.path.exists("/app/build/target_afl"), "target_afl not found"
        assert os.access(
            "/app/build/target_afl", os.X_OK
        ), "target_afl not executable"

    def test_target_afl_instrumented(self):
        result = subprocess.run(
            ["strings", "/app/build/target_afl"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        markers = ["__afl", "afl_area", "AFL_SHM", "afl_shm", "__sanitizer_cov"]
        found = any(m in result.stdout for m in markers)
        assert found, "target_afl does not appear to be AFL++ instrumented"

    def test_target_cmplog_exists(self):
        assert os.path.exists("/app/build/target_cmplog"), "target_cmplog not found"
        assert os.access(
            "/app/build/target_cmplog", os.X_OK
        ), "target_cmplog not executable"

    def test_target_cmplog_differs_from_standard(self):
        with open("/app/build/target_afl", "rb") as f:
            afl_data = f.read()
        with open("/app/build/target_cmplog", "rb") as f:
            cmplog_data = f.read()
        assert afl_data != cmplog_data, (
            "CmpLog binary is identical to standard instrumented binary"
        )

    def test_target_accepts_valid_input(self):
        # Craft a minimal valid XPROTO message
        payload = struct.pack("<BH", 0x02, 4) + struct.pack("<I", 42)
        header = MAGIC + struct.pack("<HHI", 1, 0, len(payload))
        pre_crc = header + payload
        crc = zlib.crc32(pre_crc) & 0xFFFFFFFF
        msg = pre_crc + struct.pack("<I", crc)

        result = subprocess.run(
            ["/app/build/target_afl"],
            input=msg,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"target_afl rejected valid input: {result.stderr.decode(errors='replace')}"
        )


# ── Seed corpus tests ──────────────────────────────────────────────


class TestSeedCorpus:
    """Verify seed corpus validity and diversity."""

    def test_corpus_directory_exists(self):
        assert os.path.isdir("/app/corpus"), "/app/corpus directory not found"

    def test_corpus_has_enough_seeds(self):
        files = [
            f
            for f in os.listdir("/app/corpus")
            if os.path.isfile(os.path.join("/app/corpus", f))
        ]
        assert len(files) >= 5, f"Need >= 5 seed files, found {len(files)}"

    def test_all_seeds_are_valid(self):
        validate_mod = importlib.import_module("validate")
        corpus_dir = "/app/corpus"
        for fname in sorted(os.listdir(corpus_dir)):
            fpath = os.path.join(corpus_dir, fname)
            if not os.path.isfile(fpath):
                continue
            with open(fpath, "rb") as f:
                data = f.read()
            valid, info = validate_mod.validate(data)
            assert valid, f"Seed {fname} invalid: {info}"

    def test_corpus_covers_multiple_versions(self):
        corpus_dir = "/app/corpus"
        versions = set()
        for fname in os.listdir(corpus_dir):
            fpath = os.path.join(corpus_dir, fname)
            if not os.path.isfile(fpath):
                continue
            with open(fpath, "rb") as f:
                data = f.read()
            if len(data) >= 6:
                version = struct.unpack_from("<H", data, 4)[0]
                versions.add(version)
        assert len(versions) >= 2, (
            f"Corpus should cover >= 2 protocol versions, found {versions}"
        )

    def test_corpus_covers_multiple_tlv_types(self):
        validate_mod = importlib.import_module("validate")
        corpus_dir = "/app/corpus"
        types_seen = set()
        for fname in os.listdir(corpus_dir):
            fpath = os.path.join(corpus_dir, fname)
            if not os.path.isfile(fpath):
                continue
            with open(fpath, "rb") as f:
                data = f.read()
            valid, entries = validate_mod.validate(data)
            if valid and isinstance(entries, list):
                for entry in entries:
                    types_seen.add(entry[0])
        assert len(types_seen) >= 3, (
            f"Corpus should cover >= 3 TLV types, found {types_seen}"
        )
