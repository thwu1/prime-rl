
"""Verification tests for the myconv charconv library."""

import subprocess
import re
import pytest


def _run_test_runner():
    """Run the compiled C++ test runner and return parsed results."""
    result = subprocess.run(
        ["/tmp/charconv_test_runner"],
        capture_output=True, text=True, timeout=120
    )
    lines = result.stdout.strip().splitlines()
    tests = {}
    for line in lines:
        m = re.match(r'^(PASS|FAIL)\s+(\S+)(.*)', line)
        if m:
            status = m.group(1)
            name = m.group(2)
            detail = m.group(3).strip()
            tests[name] = (status, detail)
    return tests, result.returncode, result.stdout, result.stderr


@pytest.fixture(scope="module")
def test_results():
    """Compile and run the test runner once, share results across tests."""
    tests, rc, stdout, stderr = _run_test_runner()
    return tests, rc, stdout, stderr


def _assert_pass(test_results, name):
    tests = test_results[0]
    assert name in tests, (
        f"Test '{name}' not found in output. "
        f"Available: {list(tests.keys())}"
    )
    status, detail = tests[name]
    assert status == "PASS", f"Test '{name}' failed: {detail}"


# --- Integer to_chars ---

def test_int_to_chars_basic(test_results):
    _assert_pass(test_results, "int_to_chars_0")
    _assert_pass(test_results, "int_to_chars_42")
    _assert_pass(test_results, "int_to_chars_neg42")


def test_int_to_chars_int64_min(test_results):
    _assert_pass(test_results, "int_to_chars_int64_min")


def test_int_to_chars_int32_min(test_results):
    _assert_pass(test_results, "int_to_chars_int32_min")


def test_int_to_chars_lowercase(test_results):
    _assert_pass(test_results, "int_to_chars_hex_ff")
    _assert_pass(test_results, "int_to_chars_hex_deadbeef")
    _assert_pass(test_results, "int_to_chars_base36_z")


def test_int_to_chars_buffer_overflow(test_results):
    _assert_pass(test_results, "int_to_chars_buf_overflow")
    _assert_pass(test_results, "int_to_chars_buf_exact_fit")


# --- Integer from_chars ---

def test_int_from_chars_basic(test_results):
    _assert_pass(test_results, "int_from_chars_42")
    _assert_pass(test_results, "int_from_chars_neg99")


def test_int_from_chars_no_0x(test_results):
    _assert_pass(test_results, "int_from_chars_no_0x")


def test_int_from_chars_overflow_ull(test_results):
    _assert_pass(test_results, "int_from_chars_ull_overflow")
    _assert_pass(test_results, "int_from_chars_ull_max_ok")


def test_int_roundtrip(test_results):
    _assert_pass(test_results, "int_roundtrip_base10")
    _assert_pass(test_results, "int_roundtrip_base16")
    _assert_pass(test_results, "int_roundtrip_base2")
    _assert_pass(test_results, "int_roundtrip_base36")


# --- Float to_chars (double, shortest) ---

def test_float_to_chars_shortest(test_results):
    _assert_pass(test_results, "float_to_chars_0.1_short")
    _assert_pass(test_results, "float_to_chars_3.14_short")


def test_float_to_chars_roundtrip(test_results):
    _assert_pass(test_results, "float_rt_0.1")
    _assert_pass(test_results, "float_rt_0.3")
    _assert_pass(test_results, "float_rt_3.14")
    _assert_pass(test_results, "float_rt_1e10")
    _assert_pass(test_results, "float_rt_1e-10")
    _assert_pass(test_results, "float_rt_dbl_max")
    _assert_pass(test_results, "float_rt_dbl_min")
    _assert_pass(test_results, "float_rt_neg_pi")


def test_float_to_chars_special(test_results):
    _assert_pass(test_results, "float_to_chars_zero")
    _assert_pass(test_results, "float_to_chars_neg_zero")
    _assert_pass(test_results, "float_to_chars_inf")
    _assert_pass(test_results, "float_to_chars_neg_inf")
    _assert_pass(test_results, "float_to_chars_nan")


# --- Float from_chars ---

def test_float_from_chars_no_whitespace(test_results):
    _assert_pass(test_results, "float_from_chars_no_ws")


def test_float_from_chars_no_plus(test_results):
    _assert_pass(test_results, "float_from_chars_no_plus")


def test_float_from_chars_no_0x(test_results):
    _assert_pass(test_results, "float_from_chars_no_0x")


def test_float_from_chars_respects_last(test_results):
    _assert_pass(test_results, "float_from_chars_respects_last")


def test_float_from_chars_overflow(test_results):
    _assert_pass(test_results, "float_from_chars_overflow")


# --- Float type-specific (float32) ---

def test_float32_to_chars_short(test_results):
    _assert_pass(test_results, "float32_to_chars_short")


def test_float32_roundtrip(test_results):
    _assert_pass(test_results, "float32_rt_0.1f")


def test_float32_from_chars_overflow(test_results):
    _assert_pass(test_results, "float32_from_chars_overflow")


# --- chars_format to_chars ---

def test_fmt_to_chars_scientific(test_results):
    _assert_pass(test_results, "fmt_tc_scientific")


def test_fmt_to_chars_fixed(test_results):
    _assert_pass(test_results, "fmt_tc_fixed")


def test_fmt_to_chars_hex_format(test_results):
    _assert_pass(test_results, "fmt_tc_hex_format")


def test_fmt_to_chars_hex_roundtrip(test_results):
    _assert_pass(test_results, "fmt_tc_hex_rt")


# --- chars_format to_chars with precision ---

def test_fmt_to_chars_sci_prec(test_results):
    _assert_pass(test_results, "fmt_tc_sci_prec")


def test_fmt_to_chars_fixed_prec(test_results):
    _assert_pass(test_results, "fmt_tc_fixed_prec")


def test_fmt_to_chars_hex_prec(test_results):
    _assert_pass(test_results, "fmt_tc_hex_prec")


def test_fmt_to_chars_general_prec(test_results):
    _assert_pass(test_results, "fmt_tc_general_prec")


# --- chars_format from_chars ---

def test_fmt_from_chars_sci_requires_exp(test_results):
    _assert_pass(test_results, "fmt_fc_sci_requires_exp")


def test_fmt_from_chars_sci_accepts_exp(test_results):
    _assert_pass(test_results, "fmt_fc_sci_accepts_exp")


def test_fmt_from_chars_fixed_stops_at_exp(test_results):
    _assert_pass(test_results, "fmt_fc_fixed_stops_at_exp")


def test_fmt_from_chars_hex_parse(test_results):
    _assert_pass(test_results, "fmt_fc_hex_parse")


def test_fmt_from_chars_general_both(test_results):
    _assert_pass(test_results, "fmt_fc_general_both")


# --- Header check ---

def test_no_charconv_header(test_results):
    """Ensure the implementation does not use <charconv>."""
    _assert_pass(test_results, "no_charconv_header")
