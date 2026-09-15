
"""
Tests for PRNG forensic analysis and security evaluation task.
Verifies stream-to-generator matching, output predictions, security assessment,
and automated PRNG classifier.
"""

import json
import os
import struct
import subprocess
import tempfile
import pytest

# ========== Modified MT19937 Implementation ==========

N_MT = 624
M_MT = 397
MATRIX_A = 0x9908B0DF
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7FFFFFFF

_TEMPER_U = 13
_TEMPER_S = 9
_TEMPER_B = 0xB5A7C4E0
_TEMPER_T = 17
_TEMPER_C = 0xD3E40000
_TEMPER_L = 15


class ModifiedMT:
    def __init__(self):
        self.mt = [0] * N_MT
        self.index = N_MT + 1

    def _init_genrand(self, s):
        self.mt[0] = s & 0xFFFFFFFF
        for i in range(1, N_MT):
            self.mt[i] = (
                1812433253 * (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) + i
            ) & 0xFFFFFFFF
        self.index = N_MT

    def init_by_array(self, key):
        key_length = len(key)
        self._init_genrand(19650218)
        i, j = 1, 0
        k = max(N_MT, key_length)
        while k > 0:
            self.mt[i] = (
                (self.mt[i] ^ ((self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) * 1664525))
                + key[j] + j
            ) & 0xFFFFFFFF
            i += 1
            j += 1
            if i >= N_MT:
                self.mt[0] = self.mt[N_MT - 1]
                i = 1
            if j >= key_length:
                j = 0
            k -= 1
        k = N_MT - 1
        while k > 0:
            self.mt[i] = (
                (self.mt[i] ^ ((self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) * 1566083941))
                - i
            ) & 0xFFFFFFFF
            i += 1
            if i >= N_MT:
                self.mt[0] = self.mt[N_MT - 1]
                i = 1
            k -= 1
        self.mt[0] = 0x80000000

    def _twist(self):
        for i in range(N_MT):
            y = (self.mt[i] & UPPER_MASK) | (self.mt[(i + 1) % N_MT] & LOWER_MASK)
            self.mt[i] = self.mt[(i + M_MT) % N_MT] ^ (y >> 1)
            if y & 1:
                self.mt[i] ^= MATRIX_A
        self.index = 0

    def extract(self):
        if self.index >= N_MT:
            self._twist()
        y = self.mt[self.index]
        self.index += 1
        y ^= (y >> _TEMPER_U)
        y ^= (y << _TEMPER_S) & _TEMPER_B
        y ^= (y << _TEMPER_T) & _TEMPER_C
        y ^= (y >> _TEMPER_L)
        return y & 0xFFFFFFFF


# ========== xorshift128 Implementation ==========

class XorShift128:
    def __init__(self, a, b, c, d):
        self.a = a & 0xFFFFFFFF
        self.b = b & 0xFFFFFFFF
        self.c = c & 0xFFFFFFFF
        self.d = d & 0xFFFFFFFF

    def next(self):
        t = self.d
        s = self.a
        self.d = self.c
        self.c = self.b
        self.b = self.a
        t ^= (t << 11) & 0xFFFFFFFF
        t ^= (t >> 8)
        s ^= (s >> 19)
        self.a = (t ^ s) & 0xFFFFFFFF
        return self.a


# ========== LCG64 Implementation ==========

LCG_MULT = 6364136223846793005
LCG_INC = 1442695040888963407
MASK64 = (1 << 64) - 1


class LCG64:
    def __init__(self, seed):
        self.state = seed & MASK64

    def next(self):
        self.state = (self.state * LCG_MULT + LCG_INC) & MASK64
        return (self.state >> 32) & 0xFFFFFFFF


# ========== Reference generation ==========

MT_SEED_KEY = [0xA1B2C3D4, 0xE5F6A7B8, 0xC9D0E1F2, 0xA3B4C5D6]
XS_SEED = (0x12345678, 0x9ABCDEF0, 0xFEDCBA98, 0x76543210)
LCG_SEED = 0xDEADBEEFCAFEBABE

STREAM_COUNT = 800
PREDICT_COUNT = 5
TOTAL_COUNT = STREAM_COUNT + PREDICT_COUNT

# Correct mapping (stream_1=gen_beta, stream_2=gen_gamma, stream_3=gen_alpha)
CORRECT_MATCHING = {
    "stream_1": "gen_beta",
    "stream_2": "gen_gamma",
    "stream_3": "gen_alpha",
}

WEAKEST_GEN = "gen_beta"


def gen_mt_outputs():
    rng = ModifiedMT()
    rng.init_by_array(MT_SEED_KEY)
    return [rng.extract() for _ in range(TOTAL_COUNT)]


def gen_xs_outputs():
    rng = XorShift128(*XS_SEED)
    return [rng.next() for _ in range(TOTAL_COUNT)]


def gen_lcg_outputs():
    rng = LCG64(LCG_SEED)
    return [rng.next() for _ in range(TOTAL_COUNT)]


# ========== Forensic Analysis Tests ==========


class TestForensicAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mt_outputs = gen_mt_outputs()
        self.xs_outputs = gen_xs_outputs()
        self.lcg_outputs = gen_lcg_outputs()

        self.gen_outputs = {
            "gen_alpha": self.mt_outputs,
            "gen_beta": self.xs_outputs,
            "gen_gamma": self.lcg_outputs,
        }

    def _read_matching(self):
        path = "/app/matching.txt"
        if not os.path.exists(path):
            pytest.fail(f"Matching file not found at {path}")
        matching = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                stream, gen = line.split("=", 1)
                matching[stream.strip()] = gen.strip()
        return matching

    def _read_predictions(self, stream_num):
        path = f"/app/predictions_{stream_num}.txt"
        if not os.path.exists(path):
            pytest.fail(f"Prediction file not found at {path}")
        preds = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    preds.append(int(line, 16))
                except ValueError:
                    pytest.fail(f"Invalid hex value in {path}: '{line}'")
        return preds

    def test_matching_file_exists(self):
        """matching.txt must exist."""
        assert os.path.exists("/app/matching.txt"), "matching.txt not found"

    def test_matching_correctness(self):
        """Each stream must be correctly mapped to its generator."""
        matching = self._read_matching()
        for stream_name in ["stream_1", "stream_2", "stream_3"]:
            assert stream_name in matching, (
                f"{stream_name} missing from matching.txt"
            )
            assert matching[stream_name] == CORRECT_MATCHING[stream_name], (
                f"Wrong match for {stream_name}: "
                f"got {matching[stream_name]}, expected {CORRECT_MATCHING[stream_name]}"
            )

    def test_matching_is_bijection(self):
        """All three generators must appear exactly once."""
        matching = self._read_matching()
        gens = set(matching.values())
        assert gens == {"gen_alpha", "gen_beta", "gen_gamma"}, (
            f"Matching must use each generator exactly once. Got: {gens}"
        )

    def test_predictions_1_count(self):
        """Stream 1 must have exactly 5 predictions."""
        preds = self._read_predictions(1)
        assert len(preds) == PREDICT_COUNT, (
            f"Expected {PREDICT_COUNT} predictions for stream 1, got {len(preds)}"
        )

    def test_predictions_1_values(self):
        """Stream 1 predictions must match reference outputs."""
        preds = self._read_predictions(1)
        gen_name = CORRECT_MATCHING["stream_1"]
        expected = self.gen_outputs[gen_name][STREAM_COUNT:TOTAL_COUNT]
        assert len(preds) == PREDICT_COUNT
        for i, (p, e) in enumerate(zip(preds, expected)):
            assert p == e, (
                f"stream_1 prediction {i} (pos {STREAM_COUNT + i}) wrong: "
                f"got 0x{p:08x}, expected 0x{e:08x}"
            )

    def test_predictions_2_count(self):
        """Stream 2 must have exactly 5 predictions."""
        preds = self._read_predictions(2)
        assert len(preds) == PREDICT_COUNT, (
            f"Expected {PREDICT_COUNT} predictions for stream 2, got {len(preds)}"
        )

    def test_predictions_2_values(self):
        """Stream 2 predictions must match reference outputs."""
        preds = self._read_predictions(2)
        gen_name = CORRECT_MATCHING["stream_2"]
        expected = self.gen_outputs[gen_name][STREAM_COUNT:TOTAL_COUNT]
        assert len(preds) == PREDICT_COUNT
        for i, (p, e) in enumerate(zip(preds, expected)):
            assert p == e, (
                f"stream_2 prediction {i} (pos {STREAM_COUNT + i}) wrong: "
                f"got 0x{p:08x}, expected 0x{e:08x}"
            )

    def test_predictions_3_count(self):
        """Stream 3 must have exactly 5 predictions."""
        preds = self._read_predictions(3)
        assert len(preds) == PREDICT_COUNT, (
            f"Expected {PREDICT_COUNT} predictions for stream 3, got {len(preds)}"
        )

    def test_predictions_3_values(self):
        """Stream 3 predictions must match reference outputs."""
        preds = self._read_predictions(3)
        gen_name = CORRECT_MATCHING["stream_3"]
        expected = self.gen_outputs[gen_name][STREAM_COUNT:TOTAL_COUNT]
        assert len(preds) == PREDICT_COUNT
        for i, (p, e) in enumerate(zip(preds, expected)):
            assert p == e, (
                f"stream_3 prediction {i} (pos {STREAM_COUNT + i}) wrong: "
                f"got 0x{p:08x}, expected 0x{e:08x}"
            )

    def test_weakest_assessment(self):
        """The weakest generator must be correctly identified."""
        path = "/app/weakest.txt"
        if not os.path.exists(path):
            pytest.fail(f"Weakest assessment file not found at {path}")
        with open(path) as f:
            answer = f.read().strip().lower()
        valid_answers = ("gen_beta", "xorshift128", "xorshift")
        assert answer in valid_answers, (
            f"Weakest generator wrong: got '{answer}', expected 'gen_beta' "
            f"(xorshift128 — state is directly exposed in output)"
        )

    def test_stream_1_consistency(self):
        """Verify stream_1.bin matches xorshift128 reference."""
        with open("/app/stream_1.bin", "rb") as f:
            data = f.read()
        assert len(data) == STREAM_COUNT * 4, (
            f"stream_1.bin: expected {STREAM_COUNT * 4} bytes, got {len(data)}"
        )
        vals = list(struct.unpack(f"<{STREAM_COUNT}I", data))
        for i in range(min(10, STREAM_COUNT)):
            assert vals[i] == self.xs_outputs[i], (
                f"stream_1 consistency at {i}: "
                f"got 0x{vals[i]:08x}, expected 0x{self.xs_outputs[i]:08x}"
            )

    def test_stream_2_consistency(self):
        """Verify stream_2.bin matches LCG reference."""
        with open("/app/stream_2.bin", "rb") as f:
            data = f.read()
        assert len(data) == STREAM_COUNT * 4
        vals = list(struct.unpack(f"<{STREAM_COUNT}I", data))
        for i in range(min(10, STREAM_COUNT)):
            assert vals[i] == self.lcg_outputs[i], (
                f"stream_2 consistency at {i}: "
                f"got 0x{vals[i]:08x}, expected 0x{self.lcg_outputs[i]:08x}"
            )

    def test_stream_3_consistency(self):
        """Verify stream_3.bin matches MT reference."""
        with open("/app/stream_3.bin", "rb") as f:
            data = f.read()
        assert len(data) == STREAM_COUNT * 4
        vals = list(struct.unpack(f"<{STREAM_COUNT}I", data))
        for i in range(min(10, STREAM_COUNT)):
            assert vals[i] == self.mt_outputs[i], (
                f"stream_3 consistency at {i}: "
                f"got 0x{vals[i]:08x}, expected 0x{self.mt_outputs[i]:08x}"
            )


# ========== Classifier Tests ==========

# Test seeds — deliberately different from the seeds used to generate stream_1/2/3
_CLASSIFIER_XS_SEEDS = [
    (0xAABBCCDD, 0x11223344, 0x55667788, 0x99001122),
    (0xDEAD1234, 0xBEEF5678, 0xCAFE9ABC, 0xBABEDEF0),
]
_CLASSIFIER_LCG_SEEDS = [
    0x1234ABCD5678EF01,
    0xABCDEF0123456789,
]
_CLASSIFIER_MT_KEYS = [
    [0xF1F2F3F4, 0xA5A6A7A8, 0xB9BACBDC, 0xE1E2E3E4],
    [0x01020304, 0x05060708, 0x090A0B0C, 0x0D0E0F10],
]


def _write_stream_to_file(values, path):
    with open(path, "wb") as f:
        for v in values:
            f.write(struct.pack("<I", v))


def _run_classifier(stream_path):
    result = subprocess.run(
        ["python3", "/app/classifier.py", stream_path],
        capture_output=True, text=True, timeout=180,
    )
    return result.stdout.strip().lower()


class TestClassifier:
    """Verify the PRNG classifier correctly identifies streams from novel seeds."""

    def test_classifier_exists(self):
        assert os.path.exists("/app/classifier.py"), "classifier.py not found"

    def test_classify_xorshift128_seed_a(self):
        rng = XorShift128(*_CLASSIFIER_XS_SEEDS[0])
        vals = [rng.next() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "xorshift128", (
            f"Classifier should identify xorshift128, got '{result}'"
        )

    def test_classify_xorshift128_seed_b(self):
        rng = XorShift128(*_CLASSIFIER_XS_SEEDS[1])
        vals = [rng.next() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "xorshift128", (
            f"Classifier should identify xorshift128, got '{result}'"
        )

    def test_classify_lcg64_seed_a(self):
        rng = LCG64(_CLASSIFIER_LCG_SEEDS[0])
        vals = [rng.next() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "lcg64", (
            f"Classifier should identify lcg64, got '{result}'"
        )

    def test_classify_lcg64_seed_b(self):
        rng = LCG64(_CLASSIFIER_LCG_SEEDS[1])
        vals = [rng.next() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "lcg64", (
            f"Classifier should identify lcg64, got '{result}'"
        )

    def test_classify_mt19937_seed_a(self):
        rng = ModifiedMT()
        rng.init_by_array(_CLASSIFIER_MT_KEYS[0])
        vals = [rng.extract() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "mt19937", (
            f"Classifier should identify mt19937, got '{result}'"
        )

    def test_classify_mt19937_seed_b(self):
        rng = ModifiedMT()
        rng.init_by_array(_CLASSIFIER_MT_KEYS[1])
        vals = [rng.extract() for _ in range(800)]
        fd, path = tempfile.mkstemp(suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                for v in vals:
                    f.write(struct.pack("<I", v))
            result = _run_classifier(path)
        finally:
            os.unlink(path)
        assert result == "mt19937", (
            f"Classifier should identify mt19937, got '{result}'"
        )


# ========== Assessment Tests ==========


class TestAssessment:
    """Verify quantitative vulnerability assessment."""

    ASSESSMENT_PATH = "/app/assessment.json"

    def _load(self):
        with open(self.ASSESSMENT_PATH) as f:
            return json.load(f)

    def test_assessment_exists(self):
        assert os.path.exists(self.ASSESSMENT_PATH), "assessment.json not found"

    def test_assessment_valid_json(self):
        try:
            self._load()
        except json.JSONDecodeError as e:
            pytest.fail(f"assessment.json is not valid JSON: {e}")

    def test_assessment_all_generators_present(self):
        data = self._load()
        assert "generators" in data, "Missing 'generators' key"
        for g in ["gen_alpha", "gen_beta", "gen_gamma"]:
            assert g in data["generators"], f"Missing generator entry: {g}"

    def test_assessment_has_required_fields(self):
        data = self._load()
        for gen_name, gen_data in data["generators"].items():
            assert "min_outputs_for_recovery" in gen_data, (
                f"{gen_name} missing 'min_outputs_for_recovery'"
            )
            assert "attack_complexity" in gen_data, (
                f"{gen_name} missing 'attack_complexity'"
            )

    def test_assessment_min_outputs_xorshift128(self):
        """gen_beta (xorshift128): state = 4 consecutive outputs."""
        data = self._load()
        val = data["generators"]["gen_beta"]["min_outputs_for_recovery"]
        assert isinstance(val, int), f"min_outputs must be int, got {type(val)}"
        assert 4 <= val <= 8, (
            f"xorshift128 min_outputs should be 4-8 (state is 4 words), got {val}"
        )

    def test_assessment_min_outputs_lcg64(self):
        """gen_gamma (LCG64): 2 truncated outputs to brute-force 64-bit state."""
        data = self._load()
        val = data["generators"]["gen_gamma"]["min_outputs_for_recovery"]
        assert isinstance(val, int), f"min_outputs must be int, got {type(val)}"
        assert 2 <= val <= 4, (
            f"LCG64 min_outputs should be 2-4, got {val}"
        )

    def test_assessment_min_outputs_mt19937(self):
        """gen_alpha (MT19937): need 624 outputs for full state recovery."""
        data = self._load()
        val = data["generators"]["gen_alpha"]["min_outputs_for_recovery"]
        assert isinstance(val, int), f"min_outputs must be int, got {type(val)}"
        assert 624 <= val <= 700, (
            f"MT19937 min_outputs should be 624-700, got {val}"
        )

    def test_assessment_ranking_order(self):
        """Ranking must go: gen_beta (weakest) -> gen_gamma -> gen_alpha (strongest)."""
        data = self._load()
        assert "ranking_weakest_to_strongest" in data, "Missing ranking"
        ranking = data["ranking_weakest_to_strongest"]
        assert isinstance(ranking, list), "Ranking must be a list"
        assert len(ranking) == 3, f"Ranking must have 3 entries, got {len(ranking)}"
        assert ranking[0] == "gen_beta", (
            f"Weakest should be gen_beta (xorshift128), got {ranking[0]}"
        )
        assert ranking[-1] == "gen_alpha", (
            f"Strongest should be gen_alpha (MT19937), got {ranking[-1]}"
        )
