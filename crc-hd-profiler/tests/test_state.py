
"""
Verify CRC polynomial Hamming Distance profiles against known reference data
from the Koopman CRC Polynomial Zoo (Carnegie Mellon University).
"""

import json
import os
import pytest


# Reference data: verified against Koopman CRC Zoo (crc8.html)
# Each entry: koopman_hex, generator_hex (explicit+1), hd_profile, has_odd_parity
EXPECTED = {
    "P1": {
        "koopman_hex": 0x97,
        "generator_hex": 0x12f,
        "hd_profile": [119, 119, 3, 3],
        "has_odd_parity": True,
    },
    "P2": {
        "koopman_hex": 0xe7,
        "generator_hex": 0x1cf,
        "hd_profile": [247, 19, 1, 1, 1],
        "has_odd_parity": False,
    },
    "P3": {
        "koopman_hex": 0x9b,
        "generator_hex": 0x137,
        "hd_profile": [118, 118, 4, 4],
        "has_odd_parity": True,
    },
    "P4": {
        "koopman_hex": 0xea,
        "generator_hex": 0x1d5,
        "hd_profile": [85, 85, 2, 2],
        "has_odd_parity": True,
    },
    "P5": {
        "koopman_hex": 0xa6,
        "generator_hex": 0x14d,
        "hd_profile": [247, 15, 6],
        "has_odd_parity": False,
    },
}

POLY_IDS = list(EXPECTED.keys())


@pytest.fixture(scope="session")
def results():
    results_path = "/app/results.json"
    assert os.path.isfile(results_path), f"Results file not found at {results_path}"
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


def test_all_polynomials_present(results):
    """All polynomial IDs must be present in results."""
    for pid in POLY_IDS:
        assert pid in results, f"Missing polynomial {pid} in results"


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_koopman_hex(results, poly_id):
    """Koopman (implicit+1) hex must match reference value."""
    entry = results[poly_id]
    assert "koopman_hex" in entry, f"Missing koopman_hex for {poly_id}"
    actual = int(entry["koopman_hex"], 16)
    expected = EXPECTED[poly_id]["koopman_hex"]
    assert actual == expected, (
        f"{poly_id}: koopman_hex {hex(actual)} != expected {hex(expected)}"
    )


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_generator_hex(results, poly_id):
    """Explicit+1 generator hex must match reference value."""
    entry = results[poly_id]
    assert "generator_hex" in entry, f"Missing generator_hex for {poly_id}"
    actual = int(entry["generator_hex"], 16)
    expected = EXPECTED[poly_id]["generator_hex"]
    assert actual == expected, (
        f"{poly_id}: generator_hex {hex(actual)} != expected {hex(expected)}"
    )


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_hd_profile_length(results, poly_id):
    """HD profile must have the correct number of entries."""
    entry = results[poly_id]
    assert "hd_profile" in entry, f"Missing hd_profile for {poly_id}"
    actual = entry["hd_profile"]
    expected = EXPECTED[poly_id]["hd_profile"]
    assert len(actual) == len(expected), (
        f"{poly_id}: hd_profile length {len(actual)} != expected {len(expected)}. "
        f"Got {actual}, expected {expected}"
    )


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_hd_profile_values(results, poly_id):
    """Each HD profile entry must exactly match the reference value."""
    actual = results[poly_id]["hd_profile"]
    expected = EXPECTED[poly_id]["hd_profile"]
    for i, (a, e) in enumerate(zip(actual, expected)):
        hd_level = 3 + i
        assert a == e, (
            f"{poly_id}: HD={hd_level} max dataword length {a} != expected {e}. "
            f"Full profile: got {actual}, expected {expected}"
        )


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_has_odd_parity(results, poly_id):
    """Odd parity flag must match reference (indicates x+1 factor)."""
    entry = results[poly_id]
    assert "has_odd_parity" in entry, f"Missing has_odd_parity for {poly_id}"
    actual = entry["has_odd_parity"]
    expected = EXPECTED[poly_id]["has_odd_parity"]
    assert actual == expected, (
        f"{poly_id}: has_odd_parity {actual} != expected {expected}"
    )


@pytest.mark.parametrize("poly_id", POLY_IDS)
def test_hd3_boundary_matches_period(results, poly_id):
    """
    Sanity check: for an 8-bit CRC, the HD=3 boundary plus CRC width
    should equal the period of x modulo g(x). Verify the period is
    consistent by checking x^period = 1 mod g(x).
    """
    entry = results[poly_id]
    hd3_max = entry["hd_profile"][0]
    gen = int(entry["generator_hex"], 16)
    n = 8
    period = hd3_max + n

    # Compute x^period mod g(x) using shift register
    mask = (1 << n) - 1
    r = 1
    for _ in range(period):
        r <<= 1
        if r & (1 << n):
            r ^= gen
        r &= mask

    # x^period should equal 1 (completing one full cycle)
    assert r == 1, (
        f"{poly_id}: x^{period} mod g(x) = {r}, expected 1. "
        f"HD=3 boundary {hd3_max} may be incorrect."
    )


def test_odd_parity_polynomials_have_paired_profiles(results):
    """
    Polynomials with (x+1) factor detect all odd-weight errors,
    so consecutive HD levels (odd,even) share the same boundary.
    """
    for pid in POLY_IDS:
        entry = results[pid]
        if not entry["has_odd_parity"]:
            continue
        profile = entry["hd_profile"]
        # Profile entries should come in pairs (same value repeated)
        for i in range(0, len(profile) - 1, 2):
            assert profile[i] == profile[i + 1], (
                f"{pid}: odd-parity polynomial should have paired profile entries. "
                f"profile[{i}]={profile[i]} != profile[{i+1}]={profile[i+1]}"
            )
