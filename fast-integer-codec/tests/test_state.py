
"""
Tests for the fastnum library and analysis outputs.

Validates:
1. Correctness of all five library functions via ctypes
2. Bug manifest completeness and accuracy
3. Binary analysis results in /app/analysis.json
4. Mathematical analysis answers in /app/answers.txt
"""

import ctypes
import json
import os
import pytest

# ---------------------------------------------------------------------------
# Load the shared library and declare function signatures
# ---------------------------------------------------------------------------

lib = ctypes.CDLL("/app/libfastnum.so")

lib.uint64_to_dec.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_int]
lib.uint64_to_dec.restype = ctypes.c_int

lib.dec_to_uint64.argtypes = [
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_uint64),
]
lib.dec_to_uint64.restype = ctypes.c_int

lib.bytes_to_hex.argtypes = [
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_char_p,
    ctypes.c_size_t,
]
lib.bytes_to_hex.restype = ctypes.c_int

lib.hex_to_bytes.argtypes = [
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_char_p,
    ctypes.c_size_t,
]
lib.hex_to_bytes.restype = ctypes.c_int

lib.uint64_mul_overflow.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
lib.uint64_mul_overflow.restype = ctypes.c_int

UINT64_MAX = 2**64 - 1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_dec(n: int) -> str:
    buf = ctypes.create_string_buffer(32)
    ret = lib.uint64_to_dec(ctypes.c_uint64(n), buf, 32)
    assert ret > 0, f"uint64_to_dec returned {ret} for n={n}"
    return buf.value.decode("ascii")


def _parse_dec(s: str):
    val = ctypes.c_uint64(0)
    raw = s.encode("ascii")
    ret = lib.dec_to_uint64(raw, len(raw), ctypes.byref(val))
    return ret, val.value


def _encode_hex(data: bytes) -> str:
    src = ctypes.create_string_buffer(data, len(data))
    dst = ctypes.create_string_buffer(len(data) * 2 + 1)
    ret = lib.bytes_to_hex(src, len(data), dst, len(data) * 2 + 1)
    assert ret == 0, f"bytes_to_hex returned {ret}"
    return dst.value.decode("ascii")


def _decode_hex(hexstr: str):
    raw = hexstr.encode("ascii")
    out = ctypes.create_string_buffer(len(raw) // 2)
    ret = lib.hex_to_bytes(raw, len(raw), out, len(raw) // 2)
    if ret != 0:
        return None
    return bytes(out)


# ===================================================================
# uint64_to_dec tests
# ===================================================================


class TestUint64ToDec:
    def test_zero(self):
        assert _to_dec(0) == "0"

    def test_single_digits(self):
        for d in range(10):
            assert _to_dec(d) == str(d)

    def test_powers_of_10(self):
        for exp in range(20):
            n = 10**exp
            if n > UINT64_MAX:
                break
            assert _to_dec(n) == str(n), f"Failed for 10^{exp}"

    def test_powers_of_10_minus_one(self):
        for exp in range(1, 20):
            n = 10**exp - 1
            if n > UINT64_MAX:
                break
            assert _to_dec(n) == str(n), f"Failed for 10^{exp}-1"

    def test_uint64_max(self):
        assert _to_dec(UINT64_MAX) == str(UINT64_MAX)

    def test_19_digit_numbers(self):
        cases = [
            10**18,
            10**18 + 1,
            5 * 10**18,
            10**19 - 1,
            1234567890123456789,
        ]
        for n in cases:
            assert _to_dec(n) == str(n), f"Failed for {n}"

    def test_20_digit_numbers(self):
        cases = [
            10**19,
            10**19 + 1,
            UINT64_MAX,
            UINT64_MAX - 1,
            15000000000000000000,
        ]
        for n in cases:
            assert _to_dec(n) == str(n), f"Failed for {n}"

    def test_various_lengths(self):
        cases = [
            5, 42, 999, 1234, 99999, 123456, 9999999, 12345678,
            999999999, 1234567890, 99999999999, 123456789012,
            9999999999999, 12345678901234, 999999999999999,
            1234567890123456, 99999999999999999, 123456789012345678,
            9999999999999999999, UINT64_MAX,
        ]
        for n in cases:
            assert _to_dec(n) == str(n), f"Failed for {n}"


# ===================================================================
# dec_to_uint64 tests
# ===================================================================


class TestDecToUint64:
    def test_zero(self):
        ret, val = _parse_dec("0")
        assert ret == 0 and val == 0

    def test_single_digits(self):
        for d in range(10):
            ret, val = _parse_dec(str(d))
            assert ret == 0 and val == d

    def test_uint64_max(self):
        ret, val = _parse_dec("18446744073709551615")
        assert ret == 0 and val == UINT64_MAX

    def test_overflow_2_to_64(self):
        ret, _ = _parse_dec("18446744073709551616")
        assert ret == -1, "Should overflow for 2^64"

    def test_overflow_near_boundary(self):
        for extra in ["18446744073709551620", "18446744073709551625",
                       "18446744073709551700", "18446744073709551999"]:
            ret, _ = _parse_dec(extra)
            assert ret == -1, f"Should overflow for {extra}"

    def test_overflow_all_nines_20(self):
        ret, _ = _parse_dec("9" * 20)
        assert ret == -1

    def test_overflow_21_digits(self):
        ret, _ = _parse_dec("1" + "0" * 20)
        assert ret == -2

    def test_boundary_exact_max_last_digit(self):
        ret, val = _parse_dec("18446744073709551615")
        assert ret == 0 and val == UINT64_MAX
        ret, _ = _parse_dec("18446744073709551616")
        assert ret == -1

    def test_leading_zeros_rejected(self):
        ret, _ = _parse_dec("007")
        assert ret == -2
        ret, _ = _parse_dec("00")
        assert ret == -2

    def test_invalid_characters(self):
        ret, _ = _parse_dec("12x4")
        assert ret == -2
        ret, _ = _parse_dec("abc")
        assert ret == -2

    def test_empty(self):
        ret, _ = _parse_dec("")
        assert ret == -2

    def test_roundtrip_with_uint64_to_dec(self):
        cases = [0, 1, 9, 10, 99, 100, 12345, 10**18, UINT64_MAX]
        for n in cases:
            s = _to_dec(n)
            ret, val = _parse_dec(s)
            assert ret == 0 and val == n, f"Roundtrip failed for {n}"


# ===================================================================
# bytes_to_hex tests
# ===================================================================


class TestBytesToHex:
    def test_empty(self):
        assert _encode_hex(b"") == ""

    def test_single_bytes(self):
        assert _encode_hex(b"\x00") == "00"
        assert _encode_hex(b"\x0a") == "0a"
        assert _encode_hex(b"\x0f") == "0f"
        assert _encode_hex(b"\x10") == "10"
        assert _encode_hex(b"\xff") == "ff"

    def test_deadbeef(self):
        assert _encode_hex(b"\xde\xad\xbe\xef") == "deadbeef"

    def test_all_256_bytes(self):
        data = bytes(range(256))
        result = _encode_hex(data)
        expected = "".join(f"{b:02x}" for b in range(256))
        assert result == expected

    def test_hex_letters_a_through_f(self):
        for nibble_val in range(10, 16):
            byte_val = nibble_val
            result = _encode_hex(bytes([byte_val]))
            expected = f"0{chr(ord('a') + nibble_val - 10)}"
            assert result == expected, (
                f"nibble {nibble_val}: got '{result}', expected '{expected}'"
            )


# ===================================================================
# hex_to_bytes tests
# ===================================================================


class TestHexToBytes:
    def test_digits_only(self):
        assert _decode_hex("0123456789") == bytes([0x01, 0x23, 0x45, 0x67, 0x89])

    def test_uppercase(self):
        assert _decode_hex("DEADBEEF") == b"\xde\xad\xbe\xef"

    def test_lowercase(self):
        assert _decode_hex("deadbeef") == b"\xde\xad\xbe\xef"

    def test_mixed_case(self):
        assert _decode_hex("DeAdBeEf") == b"\xde\xad\xbe\xef"

    def test_all_lowercase_letters(self):
        result = _decode_hex("0a0b0c0d0e0f")
        assert result == bytes([0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F])

    def test_invalid_char(self):
        assert _decode_hex("ZZZZ") is None

    def test_odd_length(self):
        assert _decode_hex("ABC") is None

    def test_empty(self):
        assert _decode_hex("") == b""

    def test_roundtrip_with_encoder(self):
        data = bytes(range(256))
        encoded = _encode_hex(data)
        decoded = _decode_hex(encoded)
        assert decoded == data


# ===================================================================
# uint64_mul_overflow tests
# ===================================================================


class TestMulOverflow:
    def test_no_overflow_small(self):
        assert lib.uint64_mul_overflow(100, 200) == 0

    def test_no_overflow_one(self):
        assert lib.uint64_mul_overflow(1, UINT64_MAX) == 0

    def test_no_overflow_zero(self):
        assert lib.uint64_mul_overflow(0, UINT64_MAX) == 0

    def test_no_overflow_zero_reverse(self):
        assert lib.uint64_mul_overflow(UINT64_MAX, 0) == 0

    def test_no_overflow_sqrt_boundary(self):
        assert lib.uint64_mul_overflow(2**32, 2**32 - 1) == 0

    def test_overflow_sqrt_boundary(self):
        assert lib.uint64_mul_overflow(2**32, 2**32 + 1) == 1

    def test_overflow_large(self):
        assert lib.uint64_mul_overflow(2**63, 3) == 1

    def test_overflow_max_times_2(self):
        assert lib.uint64_mul_overflow(UINT64_MAX, 2) == 1

    def test_no_overflow_exact_max(self):
        assert lib.uint64_mul_overflow(6148914691236517205, 3) == 0

    def test_overflow_just_over_max(self):
        assert lib.uint64_mul_overflow(6148914691236517206, 3) == 1

    def test_symmetry(self):
        assert lib.uint64_mul_overflow(2**32, 2**32 + 1) == 1
        assert lib.uint64_mul_overflow(2**32 + 1, 2**32) == 1
        assert lib.uint64_mul_overflow(2**32, 2**32 - 1) == 0
        assert lib.uint64_mul_overflow(2**32 - 1, 2**32) == 0


# ===================================================================
# Bug manifest validation
# ===================================================================


class TestBugManifest:
    """Verify the agent produced a complete and accurate bug manifest."""

    EXPECTED_FUNCTIONS = {
        "uint64_to_dec",
        "dec_to_uint64",
        "bytes_to_hex",
        "hex_to_bytes",
        "uint64_mul_overflow",
    }

    VALID_CATEGORIES = {
        "off-by-one",
        "missing-case",
        "wrong-constant",
        "unimplemented",
        "data-error",
    }

    # Each function maps to the set of acceptable category labels
    ACCEPTABLE_CATEGORIES = {
        "uint64_to_dec": {"data-error", "wrong-constant"},
        "dec_to_uint64": {"off-by-one", "wrong-constant"},
        "bytes_to_hex": {"wrong-constant"},
        "hex_to_bytes": {"missing-case"},
        "uint64_mul_overflow": {"unimplemented"},
    }

    @pytest.fixture(autouse=True)
    def load_manifest(self):
        assert os.path.exists("/app/bug_manifest.json"), (
            "/app/bug_manifest.json not found"
        )
        with open("/app/bug_manifest.json") as f:
            self.manifest = json.load(f)

    def test_is_list(self):
        assert isinstance(self.manifest, list), "bug_manifest.json must be a JSON array"

    def test_exactly_five_bugs(self):
        assert len(self.manifest) == 5, (
            f"Expected 5 bugs, got {len(self.manifest)}. "
            "All five library functions have conformance issues."
        )

    def test_all_entries_have_required_keys(self):
        for i, entry in enumerate(self.manifest):
            assert isinstance(entry, dict), f"Entry {i} is not an object"
            for key in ("function", "category", "impact"):
                assert key in entry, f"Entry {i} missing key '{key}'"

    def test_all_functions_covered(self):
        found = {e["function"] for e in self.manifest}
        assert found == self.EXPECTED_FUNCTIONS, (
            f"Expected functions {sorted(self.EXPECTED_FUNCTIONS)}, "
            f"got {sorted(found)}"
        )

    def test_categories_valid(self):
        for entry in self.manifest:
            assert entry["category"] in self.VALID_CATEGORIES, (
                f"Invalid category '{entry['category']}' for {entry['function']}. "
                f"Must be one of {sorted(self.VALID_CATEGORIES)}"
            )

    def test_categories_accurate(self):
        for entry in self.manifest:
            fn = entry["function"]
            cat = entry["category"]
            acceptable = self.ACCEPTABLE_CATEGORIES.get(fn, set())
            assert cat in acceptable, (
                f"Category '{cat}' is not an accurate classification for "
                f"the bug in {fn}. Acceptable: {sorted(acceptable)}"
            )

    def test_impacts_nonempty(self):
        for entry in self.manifest:
            assert isinstance(entry["impact"], str) and len(entry["impact"]) > 10, (
                f"Impact for {entry['function']} must be a descriptive sentence"
            )


# ===================================================================
# Mathematical analysis answers
# ===================================================================


class TestAnswers:
    def test_answers_file_exists(self):
        assert os.path.exists("/app/answers.txt"), (
            "/app/answers.txt not found"
        )

    def test_overflow_threshold(self):
        with open("/app/answers.txt") as f:
            lines = f.read().strip().split("\n")
        assert len(lines) >= 1, "answers.txt must have at least 1 line"
        assert lines[0].strip() == "1844674407370955161", (
            f"Wrong overflow threshold: got '{lines[0].strip()}'"
        )

    def test_valid_20digit_count(self):
        with open("/app/answers.txt") as f:
            lines = f.read().strip().split("\n")
        assert len(lines) >= 2, "answers.txt must have at least 2 lines"
        expected = str(UINT64_MAX - 10**19 + 1)
        assert lines[1].strip() == expected, (
            f"Wrong 20-digit count: got '{lines[1].strip()}', expected '{expected}'"
        )


# ===================================================================
# Binary analysis results
# ===================================================================


class TestAnalysis:
    """Verify the binary analysis written to /app/analysis.json."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.exists("/app/analysis.json"), (
            "/app/analysis.json not found"
        )
        with open("/app/analysis.json") as f:
            self.analysis = json.load(f)

    def test_ref_exported_functions(self):
        """Reference binary must export exactly these 5 functions."""
        expected = sorted([
            "bytes_to_hex",
            "dec_to_uint64",
            "hex_to_bytes",
            "uint64_mul_overflow",
            "uint64_to_dec",
        ])
        got = self.analysis.get("ref_exported_functions")
        assert got is not None, "Missing ref_exported_functions"
        assert sorted(got) == expected, (
            f"Expected {expected}, got {sorted(got) if isinstance(got, list) else got}"
        )

    def test_ref_hex_approach(self):
        got = self.analysis.get("ref_hex_approach")
        assert got == "arithmetic", (
            f"Expected 'arithmetic', got '{got}'."
        )

    def test_table_variant_has_rodata(self):
        got = self.analysis.get("table_variant_has_rodata_table")
        assert got is True, (
            f"Expected true, got {got}."
        )

    def test_arithmetic_variant_no_rodata(self):
        got = self.analysis.get("arithmetic_variant_has_rodata_table")
        assert got is False, (
            f"Expected false, got {got}."
        )

    def test_higher_throughput_variant(self):
        got = self.analysis.get("higher_throughput_variant")
        assert got == "arithmetic", (
            f"Expected 'arithmetic', got '{got}'."
        )
