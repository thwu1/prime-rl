
"""
Tests for CRC-8 Polynomial Error Detection Analysis.
Independently computes all expected values and verifies the agent's results.json.
Uses sympy for GF(2) polynomial factorization verification.
"""

import json
import os
import struct
import subprocess
import pytest

from sympy import symbols, Poly, GF

x = symbols('x')


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------

def koopman_to_standard(koopman_int):
    return (koopman_int << 1) | 1


def ref_crc8(data_bytes, poly_std):
    gen = poly_std & 0xFF
    crc = 0
    for byte in data_bytes:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) & 0xFF) ^ gen
            else:
                crc = (crc << 1) & 0xFF
    return crc


def ref_period(poly_std):
    state = 1
    for k in range(1, 1024):
        state <<= 1
        if state & 0x100:
            state ^= poly_std
        state &= 0xFF
        if state == 1:
            return k
    return -1


def ref_remainders(poly_std, n):
    result = [1]
    state = 1
    for _ in range(1, n):
        state <<= 1
        if state & 0x100:
            state ^= poly_std
        state &= 0xFF
        result.append(state)
    return result


def ref_max_dw_hd3(poly_std):
    max_cw = 512
    r = ref_remainders(poly_std, max_cw)
    seen = {}
    for i in range(max_cw):
        if r[i] in seen:
            return i - 8
        seen[r[i]] = i
    return max_cw - 1 - 8


def ref_max_dw_hd4(poly_std):
    mcw3 = ref_max_dw_hd3(poly_std) + 8
    r = ref_remainders(poly_std, mcw3 + 1)
    seen = set()
    pairwise = set()
    for i in range(mcw3 + 1):
        if r[i] in seen:
            return max(0, i - 8)
        if r[i] in pairwise:
            return max(0, i - 8)
        for j in range(i):
            pairwise.add(r[i] ^ r[j])
        seen.add(r[i])
    return max(0, mcw3 - 8)


def int_to_gf2_poly(val):
    terms = []
    i = 0
    v = val
    while v:
        if v & 1:
            terms.append(x ** i)
        v >>= 1
        i += 1
    return Poly(sum(terms), x, domain=GF(2))


def ref_factor_info(poly_std):
    p = int_to_gf2_poly(poly_std)
    _, factors = p.factor_list()
    is_irred = len(factors) == 1 and factors[0][1] == 1
    degrees = sorted(
        [f.degree() for f, mult in factors for _ in range(mult)]
    )
    has_x_plus_1 = 1 in degrees
    return {
        "is_irreducible": is_irred,
        "factor_degrees": degrees,
        "has_x_plus_1_factor": has_x_plus_1,
    }


# ---------------------------------------------------------------------------
# Test data — matches what gen_test_data.py encodes into test_data.bin
# ---------------------------------------------------------------------------

POLYS_KOOPMAN = [0x97, 0xA6, 0x98, 0xE7, 0x9B]
ALPHA_DATA = [0x48]
BRAVO_DATA = [0x54, 0x45, 0x53, 0x54]
CHARLIE_DATA = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    exp = {}
    for k in POLYS_KOOPMAN:
        s = koopman_to_standard(k)
        key = hex(k)
        per = ref_period(s)
        finfo = ref_factor_info(s)
        exp[key] = {
            "standard_hex": hex(s),
            "is_irreducible": finfo["is_irreducible"],
            "is_primitive": finfo["is_irreducible"] and per == 255,
            "has_x_plus_1_factor": finfo["has_x_plus_1_factor"],
            "factor_degrees": finfo["factor_degrees"],
            "period": per,
            "max_dataword_hd3": ref_max_dw_hd3(s),
            "max_dataword_hd4": ref_max_dw_hd4(s),
            "crc_alpha": ref_crc8(ALPHA_DATA, s),
            "crc_bravo": ref_crc8(BRAVO_DATA, s),
            "crc_charlie": ref_crc8(CHARLIE_DATA, s),
        }
    return exp


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "results.json not found"


def test_results_has_polynomials_key(results):
    assert "polynomials" in results


def test_results_has_best_hd4_key(results):
    assert "best_hd4_polynomial" in results


def test_all_polynomials_present(results):
    for k in POLYS_KOOPMAN:
        assert hex(k) in results["polynomials"], f"Missing {hex(k)}"


def test_all_fields_present(results):
    required = [
        "standard_hex", "is_irreducible", "is_primitive",
        "has_x_plus_1_factor", "factor_degrees", "period",
        "max_dataword_hd3", "max_dataword_hd4",
        "crc_alpha", "crc_bravo", "crc_charlie", "crc_c_validated",
    ]
    for k in POLYS_KOOPMAN:
        key = hex(k)
        for field in required:
            assert field in results["polynomials"][key], \
                f"{key} missing '{field}'"


# ---------------------------------------------------------------------------
# Value correctness tests
# ---------------------------------------------------------------------------

def test_standard_hex(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["standard_hex"] == \
            expected[key]["standard_hex"], f"{key}: standard_hex"


def test_crc_alpha(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["crc_alpha"] == \
            expected[key]["crc_alpha"], f"{key}: crc_alpha"


def test_crc_bravo(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["crc_bravo"] == \
            expected[key]["crc_bravo"], f"{key}: crc_bravo"


def test_crc_charlie(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["crc_charlie"] == \
            expected[key]["crc_charlie"], f"{key}: crc_charlie"


def test_period_values(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["period"] == \
            expected[key]["period"], f"{key}: period"


def test_max_dw_hd3(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["max_dataword_hd3"] == \
            expected[key]["max_dataword_hd3"], f"{key}: max_dataword_hd3"


def test_max_dw_hd4(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["max_dataword_hd4"] == \
            expected[key]["max_dataword_hd4"], f"{key}: max_dataword_hd4"


# ---------------------------------------------------------------------------
# GF(2) factorization tests
# ---------------------------------------------------------------------------

def test_is_irreducible(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["is_irreducible"] == \
            expected[key]["is_irreducible"], f"{key}: is_irreducible"


def test_is_primitive(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["is_primitive"] == \
            expected[key]["is_primitive"], f"{key}: is_primitive"


def test_has_x_plus_1_factor(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["has_x_plus_1_factor"] == \
            expected[key]["has_x_plus_1_factor"], \
            f"{key}: has_x_plus_1_factor"


def test_factor_degrees(results, expected):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert sorted(results["polynomials"][key]["factor_degrees"]) == \
            expected[key]["factor_degrees"], f"{key}: factor_degrees"


# ---------------------------------------------------------------------------
# C engine cross-validation tests
# ---------------------------------------------------------------------------

def test_c_engine_compiles():
    """Verify the C engine can be compiled."""
    result = subprocess.run(
        ["make", "-C", "/app"], capture_output=True, text=True
    )
    assert result.returncode == 0, f"make failed: {result.stderr}"
    assert os.path.exists("/app/crc_engine"), "crc_engine binary not found"


def test_c_engine_correct_crc_alpha():
    """Run C engine independently on alpha vector and verify CRC values."""
    subprocess.run(
        ["make", "-C", "/app"], capture_output=True, check=True
    )
    with open("/tmp/test_alpha.bin", "wb") as f:
        f.write(bytes(ALPHA_DATA))

    for k in POLYS_KOOPMAN:
        std = koopman_to_standard(k)
        expected_crc = ref_crc8(ALPHA_DATA, std)
        result = subprocess.run(
            ["/app/crc_engine", hex(std), "/tmp/test_alpha.bin"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"C engine failed for {hex(k)}"
        actual = int(result.stdout.strip())
        assert actual == expected_crc, \
            f"C engine CRC mismatch for {hex(k)}: {actual} != {expected_crc}"


def test_c_engine_correct_crc_bravo():
    """Run C engine independently on bravo vector."""
    subprocess.run(
        ["make", "-C", "/app"], capture_output=True, check=True
    )
    with open("/tmp/test_bravo.bin", "wb") as f:
        f.write(bytes(BRAVO_DATA))

    for k in POLYS_KOOPMAN:
        std = koopman_to_standard(k)
        expected_crc = ref_crc8(BRAVO_DATA, std)
        result = subprocess.run(
            ["/app/crc_engine", hex(std), "/tmp/test_bravo.bin"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        actual = int(result.stdout.strip())
        assert actual == expected_crc, \
            f"C engine bravo mismatch for {hex(k)}: {actual} != {expected_crc}"


def test_crc_c_validated_field(results):
    """Agent must report crc_c_validated as true for all polynomials."""
    for k in POLYS_KOOPMAN:
        key = hex(k)
        assert results["polynomials"][key]["crc_c_validated"] is True, \
            f"{key}: crc_c_validated must be true"


# ---------------------------------------------------------------------------
# Known-value cross-checks (Koopman published data)
# ---------------------------------------------------------------------------

def test_known_0xe7_is_primitive(results):
    assert results["polynomials"]["0xe7"]["is_primitive"] is True
    assert results["polynomials"]["0xe7"]["is_irreducible"] is True
    assert results["polynomials"]["0xe7"]["period"] == 255


def test_known_0xe7_hd3(results):
    assert results["polynomials"]["0xe7"]["max_dataword_hd3"] == 247


def test_known_0xe7_factor_degrees(results):
    assert sorted(results["polynomials"]["0xe7"]["factor_degrees"]) == [8]


def test_known_0x98_has_x_plus_1(results):
    assert results["polynomials"]["0x98"]["has_x_plus_1_factor"] is True
    assert results["polynomials"]["0x98"]["is_irreducible"] is False


def test_known_0x98_period(results):
    assert results["polynomials"]["0x98"]["period"] == 127


def test_known_0x98_hd4(results):
    assert results["polynomials"]["0x98"]["max_dataword_hd4"] == 119


def test_known_0x98_factor_degrees(results):
    assert sorted(results["polynomials"]["0x98"]["factor_degrees"]) == [1, 7]


# ---------------------------------------------------------------------------
# Consistency checks
# ---------------------------------------------------------------------------

def test_hd4_at_most_hd3(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        p = results["polynomials"][key]
        assert p["max_dataword_hd4"] <= p["max_dataword_hd3"], \
            f"{key}: hd4 ({p['max_dataword_hd4']}) > hd3 ({p['max_dataword_hd3']})"


def test_periods_positive(results):
    for k in POLYS_KOOPMAN:
        assert results["polynomials"][hex(k)]["period"] > 0


def test_crc_values_in_range(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        for field in ["crc_alpha", "crc_bravo", "crc_charlie"]:
            val = results["polynomials"][key][field]
            assert 0 <= val <= 255, f"{key}.{field}: {val} out of 8-bit range"


def test_primitive_implies_irreducible(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        p = results["polynomials"][key]
        if p["is_primitive"]:
            assert p["is_irreducible"], \
                f"{key}: primitive but not irreducible"


def test_irreducible_factor_degrees(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        p = results["polynomials"][key]
        if p["is_irreducible"]:
            assert sorted(p["factor_degrees"]) == [8], \
                f"{key}: irreducible but factor_degrees != [8]"


def test_x_plus_1_implies_degree_1_in_factors(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        p = results["polynomials"][key]
        if p["has_x_plus_1_factor"]:
            assert 1 in p["factor_degrees"], \
                f"{key}: has_x_plus_1_factor but no degree-1 factor"


def test_factor_degrees_sum_to_8(results):
    for k in POLYS_KOOPMAN:
        key = hex(k)
        degrees = results["polynomials"][key]["factor_degrees"]
        assert sum(degrees) == 8, \
            f"{key}: factor degrees sum to {sum(degrees)}, expected 8"


def test_best_hd4_polynomial_correct(results, expected):
    best_key = None
    best_val = -1
    for k in POLYS_KOOPMAN:
        key = hex(k)
        val = expected[key]["max_dataword_hd4"]
        if val > best_val or (val == best_val and
                              (best_key is None or k < int(best_key, 16))):
            best_val = val
            best_key = key
    assert results["best_hd4_polynomial"] == best_key


def test_best_hd4_is_valid(results):
    valid = {hex(k) for k in POLYS_KOOPMAN}
    assert results["best_hd4_polynomial"] in valid


# ---------------------------------------------------------------------------
# Binary data format verification
# ---------------------------------------------------------------------------

def test_binary_test_data_exists():
    assert os.path.exists("/app/test_data.bin"), "test_data.bin not found"


def test_binary_test_data_format():
    with open("/app/test_data.bin", "rb") as f:
        magic = f.read(4)
        assert magic == b"CRC8", f"Bad magic: {magic}"
        version = struct.unpack("B", f.read(1))[0]
        assert version == 1
        count = struct.unpack("B", f.read(1))[0]
        assert count == 3


# ---------------------------------------------------------------------------
# Reference implementation self-checks
# ---------------------------------------------------------------------------

def test_reference_crc_0x01_with_0xe7():
    poly_std = koopman_to_standard(0xE7)
    assert ref_crc8([0x01], poly_std) == 0xCF


def test_reference_crc_0x01_with_0x98():
    poly_std = koopman_to_standard(0x98)
    assert ref_crc8([0x01], poly_std) == 0x31


def test_reference_period_0xe7():
    assert ref_period(koopman_to_standard(0xE7)) == 255


def test_reference_period_0x98():
    assert ref_period(koopman_to_standard(0x98)) == 127


def test_reference_hd3_0xe7():
    assert ref_max_dw_hd3(koopman_to_standard(0xE7)) == 247


def test_reference_hd4_0x98():
    assert ref_max_dw_hd4(koopman_to_standard(0x98)) == 119
