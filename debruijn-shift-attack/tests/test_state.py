"""
Test suite for SIGMA-7 facility access control penetration test.

Verifies:
1. Correct cracked codes for all five zones (independently derived)
2. Valid De Bruijn sequence properties (length, uniqueness of all windows)
3. Physical encoding correctness (OOK for Zone C, tri-state for Zone D)
4. Multi-length coverage (Zone E: all 2^m windows for m in 8..11)
"""


import json
import hashlib
import os
import pytest


SEED = "b7e9a12f4d5c8031"

# OOK encoding (Zone C): logical bit -> 4 physical bits
OOK_ENCODING = {"0": "1000", "1": "1110"}

# Tri-state encoding (Zone D): logical symbol -> 18 physical bits
TRISTATE_ENCODING = {
    "0": "100000000100000000",
    "1": "111111110100000000",
    "2": "111111110111111110",
}


def derive_code(zone_label, k, n):
    """Independently derive the secret code for a zone."""
    material = "{}:{}:{}:{}".format(SEED, zone_label, k, n)
    digest = hashlib.sha256(material.encode()).digest()
    return [digest[i % len(digest)] % k for i in range(n)]


def verify_debruijn(sequence, k, n):
    """Verify a valid linear De Bruijn sequence B(k,n)."""
    expected_len = k ** n + n - 1
    assert len(sequence) == expected_len, \
        "Sequence length {} != expected {}".format(len(sequence), expected_len)
    for i, s in enumerate(sequence):
        assert 0 <= s < k, \
            "Symbol {} at position {} not in [0, {})".format(s, i, k)
    seen = set()
    num_windows = k ** n
    for i in range(num_windows):
        window = tuple(sequence[i:i + n])
        assert len(window) == n, \
            "Window at position {} too short".format(i)
        assert window not in seen, \
            "Duplicate window {} at position {}".format(window, i)
        seen.add(window)
    assert len(seen) == num_windows, \
        "Only {}/{} unique windows found".format(len(seen), num_windows)


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def load_sequence(zone_id):
    path = "/app/sequences/{}.txt".format(zone_id)
    with open(path) as f:
        return list(map(int, f.read().split()))


# ---- structural checks ----

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_sequences_dir_exists(self):
        assert os.path.isdir("/app/sequences"), "sequences/ directory not found"


# ---- Zone A: Binary k=2, n=10 ----

class TestZoneA:
    def test_code_correct(self):
        r = load_results()
        expected = "".join(map(str, derive_code("A", 2, 10)))
        assert r["A"]["code"] == expected

    def test_sequence_valid_debruijn(self):
        verify_debruijn(load_sequence("A"), 2, 10)

    def test_sequence_length(self):
        assert load_results()["A"]["sequence_length"] == 2 ** 10 + 9


# ---- Zone B: Trinary k=3, n=7 ----

class TestZoneB:
    def test_code_correct(self):
        r = load_results()
        expected = "".join(map(str, derive_code("B", 3, 7)))
        assert r["B"]["code"] == expected

    def test_sequence_valid_debruijn(self):
        verify_debruijn(load_sequence("B"), 3, 7)

    def test_sequence_length(self):
        assert load_results()["B"]["sequence_length"] == 3 ** 7 + 6


# ---- Zone C: OOK-encoded binary k=2, n=12 ----

class TestZoneC:
    def test_code_correct(self):
        r = load_results()
        expected = "".join(map(str, derive_code("C", 2, 12)))
        assert r["C"]["code"] == expected

    def test_logical_sequence_valid_debruijn(self):
        verify_debruijn(load_sequence("C"), 2, 12)

    def test_sequence_length(self):
        assert load_results()["C"]["sequence_length"] == 2 ** 12 + 11

    def test_physical_file_exists(self):
        assert os.path.isfile("/app/sequences/C_physical.txt")

    def test_physical_encoding_correct(self):
        logical = load_sequence("C")
        with open("/app/sequences/C_physical.txt") as f:
            physical = list(map(int, f.read().split()))
        expected = []
        for sym in logical:
            expected.extend(int(b) for b in OOK_ENCODING[str(sym)])
        assert physical == expected

    def test_physical_length(self):
        assert load_results()["C"]["physical_length"] == (2 ** 12 + 11) * 4


# ---- Zone D: Tri-state encoded trinary k=3, n=6 ----

class TestZoneD:
    def test_code_correct(self):
        r = load_results()
        expected = "".join(map(str, derive_code("D", 3, 6)))
        assert r["D"]["code"] == expected

    def test_logical_sequence_valid_debruijn(self):
        verify_debruijn(load_sequence("D"), 3, 6)

    def test_sequence_length(self):
        assert load_results()["D"]["sequence_length"] == 3 ** 6 + 5

    def test_physical_file_exists(self):
        assert os.path.isfile("/app/sequences/D_physical.txt")

    def test_physical_encoding_correct(self):
        logical = load_sequence("D")
        with open("/app/sequences/D_physical.txt") as f:
            physical = list(map(int, f.read().split()))
        expected = []
        for sym in logical:
            expected.extend(int(b) for b in TRISTATE_ENCODING[str(sym)])
        assert physical == expected

    def test_physical_length(self):
        assert load_results()["D"]["physical_length"] == (3 ** 6 + 5) * 18


# ---- Zone E: Multi-length binary k=2, n=8..12 ----

class TestZoneE:
    def test_all_subcodes_correct(self):
        r = load_results()
        for n in range(8, 13):
            expected = "".join(map(str, derive_code("E_{}".format(n), 2, n)))
            actual = r["E"][str(n)]["code"]
            assert actual == expected, \
                "Zone E n={}: got {}, expected {}".format(n, actual, expected)

    def test_sequence_is_debruijn_12(self):
        verify_debruijn(load_sequence("E"), 2, 12)

    def test_sequence_length(self):
        assert load_results()["E"]["sequence_length"] == 2 ** 12 + 11

    def test_shorter_lengths_covered(self):
        seq = load_sequence("E")
        for n in range(8, 12):
            expected_count = 2 ** n
            seen = set()
            for i in range(len(seq) - n + 1):
                seen.add(tuple(seq[i:i + n]))
            assert len(seen) == expected_count, \
                "B(2,12) has only {}/{} unique {}-length windows".format(
                    len(seen), expected_count, n)

    def test_codes_found_in_sequence(self):
        seq = load_sequence("E")
        for n in range(8, 13):
            code = derive_code("E_{}".format(n), 2, n)
            code_tuple = tuple(code)
            found = any(
                tuple(seq[i:i + n]) == code_tuple
                for i in range(len(seq) - n + 1))
            assert found, \
                "Code for n={} not found as window in sequence".format(n)
