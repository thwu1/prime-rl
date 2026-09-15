
"""
Tests for MAGMA canary instrumentation of the IMGP parser.

Verifies that parser.c has been correctly instrumented with MAGMA_LOG
canary calls and MAGMA_ENABLE_FIXES guards for all five documented bugs,
and that the canary runtime detects bug triggers from crafted inputs.
"""

import os
import re
import struct
import subprocess
import tempfile

import pytest

APP_DIR = "/app"
CANARY_PATH = "/tmp/magma_canary.raw"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build(canaries=True, fixes=False):
    """Clean-build the project with the given flag combination."""
    subprocess.run(["make", "clean"], cwd=APP_DIR, capture_output=True)
    args = ["make"]
    if canaries:
        args.append("CANARIES=1")
    if fixes:
        args.append("FIXES=1")
    return subprocess.run(args, cwd=APP_DIR, capture_output=True, text=True)


def _reset_canary():
    """Delete the canary storage file so a fresh one is created."""
    if os.path.exists(CANARY_PATH):
        os.remove(CANARY_PATH)


def _run_imgparse(input_bytes):
    """Run the imgparse binary on the given raw bytes."""
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
        f.write(input_bytes)
        f.flush()
        fpath = f.name
    try:
        subprocess.run(
            [os.path.join(APP_DIR, "imgparse"), fpath],
            cwd=APP_DIR,
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        pass
    finally:
        os.unlink(fpath)


def _read_canary():
    """Read canary CSV via the monitor binary and return a dict."""
    result = subprocess.run(
        [os.path.join(APP_DIR, "monitor")],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    bugs = {}
    lines = result.stdout.strip().split("\n")
    for line in lines[1:]:  # skip CSV header
        parts = line.split(",")
        if len(parts) == 3:
            bugs[parts[0]] = {
                "reached": int(parts[1]),
                "triggered": int(parts[2]),
            }
    return bugs


def _make_header(width, height, channels, num_chunks):
    """Build a 14-byte IMGP file header."""
    return (
        struct.pack("<I", 0x50474D49)
        + struct.pack("<I", width)
        + struct.pack("<I", height)
        + struct.pack("B", channels)
        + struct.pack("B", num_chunks)
    )


def _make_chunk(chunk_type, data):
    """Build a chunk: type(1) + length(2) + data."""
    return struct.pack("B", chunk_type) + struct.pack("<H", len(data)) + data


def _read_parser_source():
    with open(os.path.join(APP_DIR, "src/parser.c")) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Static analysis tests
# ---------------------------------------------------------------------------

class TestStaticInstrumentation:
    """Verify source-level instrumentation without building."""

    def test_magma_header_included(self):
        src = _read_parser_source()
        assert "magma.h" in src, (
            "parser.c must #include magma.h for canary macros"
        )

    @pytest.mark.parametrize("bug_id", ["IMG001", "IMG002", "IMG003", "IMG004", "IMG005"])
    def test_magma_log_present(self, bug_id):
        src = _read_parser_source()
        assert f"MAGMA_LOG({bug_id}" in src, (
            f"Missing MAGMA_LOG instrumentation for {bug_id}"
        )

    def test_magma_fixes_guards(self):
        src = _read_parser_source()
        count = src.count("MAGMA_ENABLE_FIXES")
        assert count >= 5, (
            f"Expected >= 5 MAGMA_ENABLE_FIXES references (one per bug), "
            f"found {count}"
        )

    def test_no_short_circuit_in_canary(self):
        """MAGMA_LOG conditions must use MAGMA_AND/MAGMA_OR, not && / ||."""
        src = _read_parser_source()
        for m in re.finditer(r"MAGMA_LOG\s*\(", src):
            start = m.start()
            depth = 0
            end = start
            for i in range(m.end() - 1, len(src)):
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            call = src[start:end]
            cleaned = call.replace("MAGMA_AND", "").replace("MAGMA_OR", "")
            assert "&&" not in cleaned, (
                f"Short-circuit && found in MAGMA_LOG (use MAGMA_AND): {call}"
            )
            assert "||" not in cleaned, (
                f"Short-circuit || found in MAGMA_LOG (use MAGMA_OR): {call}"
            )


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------

class TestBuild:

    def test_compiles_with_canaries(self):
        result = _build(canaries=True, fixes=False)
        assert result.returncode == 0, (
            f"Compilation with CANARIES=1 failed:\n{result.stderr}"
        )
        assert os.path.exists(os.path.join(APP_DIR, "imgparse"))

    def test_compiles_with_canaries_and_fixes(self):
        result = _build(canaries=True, fixes=True)
        assert result.returncode == 0, (
            f"Compilation with CANARIES=1 FIXES=1 failed:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Runtime tests — trigger each bug and verify canary output
# ---------------------------------------------------------------------------

class TestBugTriggers:
    """Craft binary inputs that trigger each bug and check canary data."""

    @pytest.fixture(autouse=True)
    def _build_canaries(self):
        """Build with canaries before each test in this class."""
        result = _build(canaries=True, fixes=False)
        assert result.returncode == 0, f"Build failed: {result.stderr}"

    def test_img001_integer_overflow(self):
        _reset_canary()
        # width=65536, height=65536, channels=4 -> product = 2^34 > UINT32_MAX
        img = _make_header(65536, 65536, 4, 0)
        _run_imgparse(img)

        bugs = _read_canary()
        assert "IMG001" in bugs, "No canary data for IMG001"
        assert bugs["IMG001"]["reached"] > 0, "IMG001 not reached"
        assert bugs["IMG001"]["triggered"] > 0, "IMG001 not triggered"

    def test_img002_off_by_one(self):
        _reset_canary()
        # palette_count=3, pixel index 3 == palette_count -> OOB
        header = _make_header(2, 2, 3, 2)
        palette_data = struct.pack("B", 3) + bytes([100, 100, 100] * 3)
        palette_chunk = _make_chunk(0x01, palette_data)
        pixel_data = bytes([0, 1, 2, 3])
        pixel_chunk = _make_chunk(0x02, pixel_data)
        _run_imgparse(header + palette_chunk + pixel_chunk)

        bugs = _read_canary()
        assert "IMG002" in bugs, "No canary data for IMG002"
        assert bugs["IMG002"]["reached"] > 0, "IMG002 not reached"
        assert bugs["IMG002"]["triggered"] > 0, "IMG002 not triggered"

    def test_img003_signed_comparison(self):
        _reset_canary()
        # offset = -1 (int32_t), pixel_count = 16 (uint16_t)
        # signed comparison: -1 < 16 -> true -> writes before buffer
        header = _make_header(4, 4, 1, 1)
        offsets_data = struct.pack("<H", 1) + struct.pack("<i", -1)
        offsets_chunk = _make_chunk(0x04, offsets_data)
        _run_imgparse(header + offsets_chunk)

        bugs = _read_canary()
        assert "IMG003" in bugs, "No canary data for IMG003"
        assert bugs["IMG003"]["reached"] > 0, "IMG003 not reached"
        assert bugs["IMG003"]["triggered"] > 0, "IMG003 not triggered"

    def test_img004_missing_bounds(self):
        _reset_canary()
        # count=10 but chunk only has 6 bytes (2 + 4 for 1 entry)
        # 2 + 10*4 = 42 > 6 -> reads past chunk boundary
        header = _make_header(4, 4, 1, 2)
        offsets_data = struct.pack("<H", 10) + struct.pack("<i", 1)
        offsets_chunk = _make_chunk(0x04, offsets_data)
        comment_chunk = _make_chunk(0x03, b"P" * 200)
        _run_imgparse(header + offsets_chunk + comment_chunk)

        bugs = _read_canary()
        assert "IMG004" in bugs, "No canary data for IMG004"
        assert bugs["IMG004"]["reached"] > 0, "IMG004 not reached"
        assert bugs["IMG004"]["triggered"] > 0, "IMG004 not triggered"

    def test_img005_rle_overflow(self):
        _reset_canary()
        # 4x4 image, 1 channel -> pixel buffer = 16 bytes
        # RLE chunk: start writing at offset 10, run of 20 bytes
        # 10 + 20 = 30 > 16 -> heap buffer overflow
        header = _make_header(4, 4, 1, 1)
        rle_data = struct.pack("<I", 10)         # write_offset = 10
        rle_data += struct.pack("BB", 20, 0xFF)  # run_len=20, value=0xFF
        rle_chunk = _make_chunk(0x05, rle_data)
        _run_imgparse(header + rle_chunk)

        bugs = _read_canary()
        assert "IMG005" in bugs, "No canary data for IMG005"
        assert bugs["IMG005"]["reached"] > 0, "IMG005 not reached"
        assert bugs["IMG005"]["triggered"] > 0, "IMG005 not triggered"

    def test_no_false_positives(self):
        """A valid image must not trigger any bugs."""
        _reset_canary()
        # 4x4 image, 3 channels, palette with 4 colors, indices 0-3
        header = _make_header(4, 4, 3, 2)
        palette_data = struct.pack("B", 4)
        for _ in range(4):
            palette_data += bytes([80, 80, 80])
        palette_chunk = _make_chunk(0x01, palette_data)
        pixel_data = bytes([0, 1, 2, 3] * 4)  # 16 pixels, valid indices
        pixel_chunk = _make_chunk(0x02, pixel_data)
        _run_imgparse(header + palette_chunk + pixel_chunk)

        bugs = _read_canary()
        for bug_id in ["IMG001", "IMG002", "IMG003", "IMG004", "IMG005"]:
            if bug_id in bugs:
                assert bugs[bug_id]["triggered"] == 0, (
                    f"{bug_id} false positive: triggered on valid image"
                )
