
import json
import struct
import subprocess
import os
import glob
import re
import io
import time

import pytest

# Known SFNNv10 architecture constants (from nnue_architecture.h)
KNOWN_FT_OUTPUT_DIM = 1024
KNOWN_FT_BIAS_COUNT = 1024
KNOWN_LAYER_STACKS = 8
KNOWN_PSQT_BUCKETS = 8

LEB128_MAGIC = b"COMPRESSED_LEB128"
LEB128_MAGIC_SIZE = len(LEB128_MAGIC)  # 17


def get_nnue_path():
    """Find the original NNUE network file in /app/."""
    candidates = sorted(glob.glob("/app/nn-*.nnue"))
    assert len(candidates) >= 1, "No original NNUE file (nn-*.nnue) found in /app/"
    return candidates[0]


def read_signed_leb128(stream):
    """Decode a single signed LEB128 value from a binary stream."""
    result = 0
    shift = 0
    byte = 0
    while True:
        byte_data = stream.read(1)
        if not byte_data:
            raise EOFError("Unexpected end of stream in LEB128 decoding")
        byte = byte_data[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    if byte & 0x40:
        result |= -(1 << shift)
    return result


def parse_nnue_header(path):
    """Parse the NNUE file header and return (version, hash, desc_size, description)."""
    with open(path, "rb") as f:
        version = struct.unpack("<I", f.read(4))[0]
        hash_val = struct.unpack("<I", f.read(4))[0]
        desc_size = struct.unpack("<I", f.read(4))[0]
        description = f.read(desc_size).decode("ascii")
    return version, hash_val, desc_size, description


def decode_ft_biases(path):
    """Parse past the header, FT hash, and COMPRESSED_LEB128 header,
    then decode 1024 LEB128 int16 biases.

    Stockfish wraps each LEB128-encoded parameter block with:
      "COMPRESSED_LEB128" (17 bytes magic) + byte_count (u32 LE) + data
    See nnue_common.h read_leb_128() for details.
    """
    with open(path, "rb") as f:
        # Skip file header
        f.read(4)  # version
        f.read(4)  # hash
        desc_size = struct.unpack("<I", f.read(4))[0]
        f.read(desc_size)  # description
        # Skip FT section hash
        f.read(4)
        # Read COMPRESSED_LEB128 block header
        magic = f.read(LEB128_MAGIC_SIZE)
        assert magic == LEB128_MAGIC, \
            f"Expected COMPRESSED_LEB128 magic, got {magic!r}"
        leb_byte_count = struct.unpack("<I", f.read(4))[0]
        # Read and decode the LEB128 data
        leb_data = f.read(leb_byte_count)
        stream = io.BytesIO(leb_data)
        biases = []
        for _ in range(KNOWN_FT_BIAS_COUNT):
            biases.append(read_signed_leb128(stream))
    return biases


def run_stockfish_eval(extra_commands=""):
    """Run Stockfish and extract depth-1 eval score using Popen.

    Uses isready synchronization to ensure the network is fully loaded
    before starting the search. Waits for readyok before issuing go.
    """
    proc = subprocess.Popen(
        ['/app/stockfish'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Phase 1: send any setup commands and synchronize
    phase1 = ""
    if extra_commands:
        phase1 += extra_commands.rstrip('\n') + '\n'
    phase1 += "isready\n"
    proc.stdin.write(phase1)
    proc.stdin.flush()

    # Wait for readyok (ensures network is loaded)
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if "readyok" in line:
            break

    # Phase 2: clear state and synchronize
    proc.stdin.write("ucinewgame\nisready\n")
    proc.stdin.flush()

    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if "readyok" in line:
            break

    # Phase 3: search
    proc.stdin.write("position startpos moves e2e4\ngo depth 1\n")
    proc.stdin.flush()

    score = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        m = re.search(r"score cp (-?\d+)", line)
        if m:
            score = int(m.group(1))
        if "bestmove" in line:
            break

    try:
        proc.stdin.write("quit\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    return score


# ============================================================
# Test Suite
# ============================================================

class TestAnalysisJsonStructure:
    """Verify analysis.json exists and has the correct structure."""

    def test_file_exists(self):
        assert os.path.exists("/app/analysis.json"), "analysis.json not found at /app/"

    def test_valid_json_with_required_fields(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        required = [
            "description", "hash", "version", "ft_output_dim",
            "ft_bias_count", "ft_bias_sum", "layer_stacks", "psqt_buckets",
        ]
        for field in required:
            assert field in data, f"Missing required field: {field}"

    def test_hash_format(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        h = data["hash"]
        assert isinstance(h, str), "hash must be a string"
        assert h.startswith("0x") or h.startswith("0X"), "hash must start with 0x"
        assert len(h) == 10, f"hash should be 10 chars (0x + 8 hex digits), got {len(h)}"


class TestArchitectureConstants:
    """Verify architecture constants match known SFNNv10 values."""

    def test_ft_output_dim(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["ft_output_dim"] == KNOWN_FT_OUTPUT_DIM, \
            f"Expected ft_output_dim={KNOWN_FT_OUTPUT_DIM}, got {data['ft_output_dim']}"

    def test_ft_bias_count(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["ft_bias_count"] == KNOWN_FT_BIAS_COUNT, \
            f"Expected ft_bias_count={KNOWN_FT_BIAS_COUNT}, got {data['ft_bias_count']}"

    def test_layer_stacks(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["layer_stacks"] == KNOWN_LAYER_STACKS, \
            f"Expected layer_stacks={KNOWN_LAYER_STACKS}, got {data['layer_stacks']}"

    def test_psqt_buckets(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["psqt_buckets"] == KNOWN_PSQT_BUCKETS, \
            f"Expected psqt_buckets={KNOWN_PSQT_BUCKETS}, got {data['psqt_buckets']}"


class TestHeaderParsing:
    """Cross-validate analysis.json header fields against independent binary parsing."""

    def test_version_matches_binary(self):
        nnue_path = get_nnue_path()
        version, _, _, _ = parse_nnue_header(nnue_path)
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["version"] == version, \
            f"Version mismatch: binary={version}, analysis={data['version']}"

    def test_hash_matches_binary(self):
        nnue_path = get_nnue_path()
        _, hash_val, _, _ = parse_nnue_header(nnue_path)
        with open("/app/analysis.json") as f:
            data = json.load(f)
        expected = f"0x{hash_val:08X}"
        assert data["hash"].upper() == expected.upper(), \
            f"Hash mismatch: binary={expected}, analysis={data['hash']}"

    def test_description_matches_binary(self):
        nnue_path = get_nnue_path()
        _, _, _, description = parse_nnue_header(nnue_path)
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["description"] == description, \
            f"Description mismatch: binary={description!r}, analysis={data['description']!r}"


class TestBiasSum:
    """Cross-validate bias sum via independent LEB128 decoding."""

    def test_ft_bias_sum_matches_independent_decode(self):
        nnue_path = get_nnue_path()
        biases = decode_ft_biases(nnue_path)
        expected_sum = sum(biases)
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert data["ft_bias_sum"] == expected_sum, \
            f"Bias sum mismatch: expected {expected_sum}, got {data['ft_bias_sum']}"


class TestModifiedNetwork:
    """Verify the modified NNUE network file."""

    def test_file_exists(self):
        assert os.path.exists("/app/modified.nnue"), "modified.nnue not found at /app/"

    def test_header_preserved(self):
        """Modified file must have identical header to original."""
        nnue_path = get_nnue_path()
        _, _, desc_size, _ = parse_nnue_header(nnue_path)
        header_size = 12 + desc_size
        with open(nnue_path, "rb") as f:
            orig_header = f.read(header_size)
        with open("/app/modified.nnue", "rb") as f:
            mod_header = f.read(header_size)
        assert orig_header == mod_header, "Modified file header differs from original"

    def test_ft_hash_preserved(self):
        """Feature transformer section hash must be preserved."""
        nnue_path = get_nnue_path()
        _, _, desc_size, _ = parse_nnue_header(nnue_path)
        ft_hash_offset = 12 + desc_size
        with open(nnue_path, "rb") as f:
            f.seek(ft_hash_offset)
            orig_ft_hash = f.read(4)
        with open("/app/modified.nnue", "rb") as f:
            f.seek(ft_hash_offset)
            mod_ft_hash = f.read(4)
        assert orig_ft_hash == mod_ft_hash, "FT section hash differs in modified file"

    def test_leb128_magic_preserved(self):
        """COMPRESSED_LEB128 magic string must be present in modified file."""
        nnue_path = get_nnue_path()
        _, _, desc_size, _ = parse_nnue_header(nnue_path)
        magic_offset = 12 + desc_size + 4  # after header + FT hash
        with open("/app/modified.nnue", "rb") as f:
            f.seek(magic_offset)
            magic = f.read(LEB128_MAGIC_SIZE)
        assert magic == LEB128_MAGIC, \
            f"COMPRESSED_LEB128 magic missing at offset {magic_offset}"

    def test_file_not_identical_to_original(self):
        """Modified file must differ from original (biases changed)."""
        nnue_path = get_nnue_path()
        with open(nnue_path, "rb") as f:
            orig_data = f.read()
        with open("/app/modified.nnue", "rb") as f:
            mod_data = f.read()
        assert orig_data != mod_data, "Modified file is identical to original"

    def test_loads_in_stockfish(self):
        """Stockfish must load the modified network and complete a search."""
        score = run_stockfish_eval(
            "setoption name EvalFile value /app/modified.nnue"
        )
        assert score is not None, \
            "Stockfish could not produce a valid evaluation with modified network " \
            "(network may have failed to load or search crashed)"

    def test_eval_differs_from_original(self):
        """Position evaluations must differ between original and modified networks."""
        orig_score = run_stockfish_eval()
        mod_score = run_stockfish_eval(
            "setoption name EvalFile value /app/modified.nnue"
        )

        assert orig_score is not None, \
            "Could not extract original score from Stockfish output"
        assert mod_score is not None, \
            "Could not extract modified score from Stockfish output"
        assert orig_score != mod_score, \
            f"Original and modified scores are identical ({orig_score}); " \
            f"bias modification had no effect"


class TestParserScript:
    """Verify the parser script exists."""

    def test_nnue_parser_exists(self):
        assert os.path.exists("/app/nnue_parser.py"), "nnue_parser.py not found at /app/"
