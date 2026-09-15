"""Verify the IEEE 802.11a OFDM PHY decoder: C shared library + Python ctypes pipeline.

Tests cover build infrastructure (Makefile, shared library compilation),
ctypes FFI usage, and decoding correctness across all 8 MCS modes.
"""

import os
import subprocess
import sys
import random

import pytest

sys.path.insert(0, "/app")

from encoder import encode_frame  # noqa: E402


# ── Build infrastructure tests ────────────────────────────────────────

class TestBuildInfrastructure:
    """Verify Makefile, C source, and shared library artifacts."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), \
            "Makefile not found at /app/Makefile"

    def test_viterbi_c_source_exists(self):
        assert os.path.isfile("/app/viterbi.c"), \
            "viterbi.c not found at /app/viterbi.c"

    def test_make_succeeds(self):
        """Running make in /app must exit 0."""
        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_shared_library_exists(self):
        assert os.path.isfile("/app/viterbi.so"), \
            "viterbi.so not found at /app/viterbi.so"

    def test_shared_library_is_elf(self):
        """viterbi.so must be a valid ELF shared object (check magic bytes)."""
        with open("/app/viterbi.so", "rb") as f:
            magic = f.read(4)
        assert magic == b"\x7fELF", \
            f"viterbi.so is not a valid ELF file (magic: {magic!r})"

    def test_clean_rebuild(self):
        """make clean && make must produce viterbi.so from scratch."""
        subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=10,
        )
        assert not os.path.isfile("/app/viterbi.so"), \
            "make clean did not remove viterbi.so"
        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"make rebuild failed:\nstderr: {result.stderr}"
        assert os.path.isfile("/app/viterbi.so"), \
            "viterbi.so not produced after clean rebuild"


# ── FFI usage tests ──────────────────────────────────────────────────

class TestFFIUsage:
    """Verify decoder.py uses ctypes to load the C shared library."""

    def test_decoder_py_exists(self):
        assert os.path.isfile("/app/decoder.py"), \
            "decoder.py not found at /app/decoder.py"

    def test_decoder_imports_ctypes(self):
        with open("/app/decoder.py", "r") as f:
            source = f.read()
        assert "ctypes" in source, \
            "decoder.py must use the ctypes module for FFI"

    def test_decoder_loads_shared_library(self):
        with open("/app/decoder.py", "r") as f:
            source = f.read()
        assert "CDLL" in source or "cdll" in source, \
            "decoder.py must load a shared library via ctypes.CDLL"

    def test_decoder_references_viterbi_lib(self):
        with open("/app/decoder.py", "r") as f:
            source = f.read()
        assert "viterbi" in source.lower(), \
            "decoder.py must reference the viterbi shared library"

    def test_decoder_importable(self):
        """decoder.py must be importable (which triggers ctypes load)."""
        try:
            if "decoder" in sys.modules:
                del sys.modules["decoder"]
            from decoder import decode_frame  # noqa: F401
        except Exception as exc:
            pytest.fail(
                f"Could not import decoder.py (ctypes load may have failed): {exc}"
            )


# ── Decoding correctness tests ───────────────────────────────────────

def _import_decoder():
    """Import the agent's decoder, raising a clear error if missing."""
    try:
        from decoder import decode_frame
        return decode_frame
    except ImportError as exc:
        pytest.fail(f"Could not import decode_frame from /app/decoder.py: {exc}")


@pytest.mark.parametrize("mcs_idx", range(8))
def test_decode_random_payloads(mcs_idx):
    """Round-trip encode/decode with random payloads for each MCS."""
    decode_frame = _import_decoder()
    rng = random.Random(58321 + mcs_idx)

    for trial in range(3):
        length = rng.randint(10, 80)
        payload = bytes(rng.randint(0, 255) for _ in range(length))
        seed = rng.randint(1, 127)

        frame_bits, _params = encode_frame(payload, mcs_idx, scrambler_seed=seed)
        signal_info, decoded = decode_frame(frame_bits, seed)

        assert signal_info["mcs"] == mcs_idx, (
            f"MCS {mcs_idx} trial {trial}: expected mcs={mcs_idx}, "
            f"got {signal_info['mcs']}"
        )
        assert signal_info["length"] == length, (
            f"MCS {mcs_idx} trial {trial}: expected length={length}, "
            f"got {signal_info['length']}"
        )
        assert decoded == payload, (
            f"MCS {mcs_idx} trial {trial}: payload mismatch "
            f"(first diff at byte "
            f"{next((i for i,(a,b) in enumerate(zip(decoded,payload)) if a!=b), '?')})"
        )


def test_single_byte_all_mcs():
    """Decode a single-byte payload across every MCS mode."""
    decode_frame = _import_decoder()
    payload = b"\x42"

    for mcs_idx in range(8):
        frame_bits, _ = encode_frame(payload, mcs_idx, scrambler_seed=1)
        signal_info, decoded = decode_frame(frame_bits, 1)

        assert signal_info["mcs"] == mcs_idx
        assert signal_info["length"] == 1
        assert decoded == payload, f"MCS {mcs_idx}: single byte mismatch"


def test_longer_payload():
    """Decode a 150-byte payload with selected MCS modes."""
    decode_frame = _import_decoder()
    rng = random.Random(77777)
    payload = bytes(rng.randint(0, 255) for _ in range(150))

    for mcs_idx in [0, 3, 6, 7]:
        frame_bits, _ = encode_frame(payload, mcs_idx, scrambler_seed=99)
        signal_info, decoded = decode_frame(frame_bits, 99)

        assert signal_info["length"] == 150
        assert decoded == payload, (
            f"MCS {mcs_idx}: 150-byte payload mismatch"
        )


def test_different_seeds():
    """Verify correct descrambling with various scrambler seeds."""
    decode_frame = _import_decoder()
    payload = b"seed-test-payload-1234567890"

    for seed in [1, 42, 63, 100, 127]:
        for mcs_idx in [0, 2, 5]:
            frame_bits, _ = encode_frame(payload, mcs_idx, scrambler_seed=seed)
            signal_info, decoded = decode_frame(frame_bits, seed)

            assert decoded == payload, (
                f"MCS {mcs_idx} seed {seed}: descramble mismatch"
            )
