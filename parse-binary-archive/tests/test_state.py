"""Verify parser evaluation, conformant parser, and pipeline results."""

import ctypes
import struct
import json
import os
import csv

import pytest


def bits_of(d):
    """Return uint64 bit pattern of an IEEE 754 binary64."""
    return struct.unpack('<Q', struct.pack('<d', d))[0]


def load_parser(path):
    """Load a parser shared library."""
    assert os.path.exists(path), f"Parser not found: {path}"
    lib = ctypes.CDLL(path)
    lib.fast_parse_double.argtypes = [
        ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double)
    ]
    lib.fast_parse_double.restype = ctypes.c_int
    return lib


def c_parse(lib, s):
    """Call the C parser and return the double value."""
    result = ctypes.c_double()
    encoded = s.encode('ascii') if isinstance(s, str) else s
    rc = lib.fast_parse_double(encoded, len(encoded), ctypes.byref(result))
    assert rc == 0, f"Parse error for input {s!r}"
    return result.value


# Canonical inputs used to independently verify the ranking
CANONICAL_INPUTS = [
    # negative zero category
    "-0.0", "-0e0", "-0.0e10", "-0e-5",
    # subnormal category
    "5e-324", "1e-310", "1e-320", "1e-309",
    # boundary category (normal/subnormal boundary with long mantissa)
    "2.2250738585072014e-308", "2.2250738585072013e-308",
    # precision category (extended fast-path exponents)
    "1e23", "1e30", "1e35", "5e25",
    # long mantissa + large exponent (tests slow-path buffer handling)
    "1234567890123456789e-320", "9999999999999999999e-340",
    # normal (should pass for all parsers)
    "1.0", "-1.0", "0.1", "42",
    # overflow
    "1e309", "-1e309",
]


# ========== Evaluation report tests ==========


class TestEvaluationReport:
    """Verify the solver's evaluation report structure and ranking."""

    @pytest.fixture(scope="class")
    def evaluation(self):
        path = '/app/evaluation.json'
        assert os.path.exists(path), "evaluation.json not found at /app/evaluation.json"
        with open(path) as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def ground_truth_ranking(self):
        """Compute ground truth ranking by running canonical inputs."""
        parser_paths = {
            "alpha": '/app/parsers/libparser_alpha.so',
            "beta": '/app/parsers/libparser_beta.so',
            "gamma": '/app/parsers/libparser_gamma.so',
        }
        failures = {}
        for name, path in parser_paths.items():
            lib = load_parser(path)
            fail_count = 0
            for s in CANONICAL_INPUTS:
                expected = float(s)
                actual = c_parse(lib, s)
                if bits_of(actual) != bits_of(expected):
                    fail_count += 1
            failures[name] = fail_count
        ranking = sorted(failures, key=lambda x: failures[x])
        return ranking

    def test_ranking_key_exists(self, evaluation):
        assert 'ranking' in evaluation, "evaluation.json must contain 'ranking' key"

    def test_ranking_has_three_entries(self, evaluation):
        assert len(evaluation['ranking']) == 3, (
            f"ranking should have 3 entries, got {len(evaluation['ranking'])}"
        )

    def test_ranking_correct(self, evaluation, ground_truth_ranking):
        solver_ranking = evaluation['ranking']
        assert solver_ranking == ground_truth_ranking, (
            f"Ranking mismatch: solver={solver_ranking}, "
            f"expected={ground_truth_ranking}"
        )

    def test_per_parser_analysis_exists(self, evaluation):
        for name in ['alpha', 'beta', 'gamma']:
            assert name in evaluation, f"Missing analysis for parser '{name}'"

    def test_per_parser_failure_count(self, evaluation):
        for name in ['alpha', 'beta', 'gamma']:
            info = evaluation[name]
            assert 'failure_count' in info, (
                f"Missing 'failure_count' for parser '{name}'"
            )
            assert isinstance(info['failure_count'], int), (
                f"failure_count for '{name}' should be int"
            )

    def test_per_parser_categories(self, evaluation):
        for name in ['alpha', 'beta', 'gamma']:
            info = evaluation[name]
            assert 'categories' in info, (
                f"Missing 'categories' for parser '{name}'"
            )
            assert isinstance(info['categories'], dict), (
                f"categories for '{name}' should be dict"
            )


# ========== Conformance corpus tests ==========


class TestConformanceCorpus:
    """Verify the solver's conformance test corpus."""

    @pytest.fixture(scope="class")
    def corpus(self):
        path = '/app/conformance_tests.csv'
        assert os.path.exists(path), (
            "conformance_tests.csv not found at /app/conformance_tests.csv"
        )
        entries = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append(row)
        return entries

    def test_has_required_columns(self, corpus):
        if corpus:
            assert 'input_string' in corpus[0], "CSV must have 'input_string' column"
            assert 'category' in corpus[0], "CSV must have 'category' column"

    def test_minimum_size(self, corpus):
        assert len(corpus) >= 15, (
            f"Corpus too small: {len(corpus)} entries (need >= 15)"
        )

    def test_required_categories_present(self, corpus):
        categories = set(row['category'] for row in corpus)
        required = {'negative_zero', 'subnormal', 'boundary', 'precision', 'overflow'}
        missing = required - categories
        assert not missing, f"Missing required categories: {missing}"

    def test_minimum_entries_per_category(self, corpus):
        from collections import Counter
        counts = Counter(row['category'] for row in corpus)
        for cat in ['negative_zero', 'subnormal', 'boundary', 'precision', 'overflow']:
            assert counts.get(cat, 0) >= 3, (
                f"Category '{cat}' needs >= 3 entries, got {counts.get(cat, 0)}"
            )

    def test_all_entries_parseable(self, corpus):
        for row in corpus:
            s = row['input_string']
            try:
                float(s)
            except ValueError:
                pytest.fail(f"Unparseable input_string: {s!r}")


# ========== Conformant parser tests ==========


class TestConformantParser:
    """Verify the fixed parser produces correct IEEE 754 results."""

    @pytest.fixture(scope="class")
    def lib(self):
        path = '/app/libconformant.so'
        assert os.path.exists(path), (
            "libconformant.so not found at /app/libconformant.so"
        )
        return load_parser(path)

    @pytest.mark.parametrize("s", [
        "-0.0", "-0e0", "-0.0e10", "-0.00", "-0e-5",
    ])
    def test_negative_zero(self, lib, s):
        v = c_parse(lib, s)
        expected_bits = bits_of(-0.0)
        actual_bits = bits_of(v)
        assert actual_bits == expected_bits, (
            f"Input {s!r}: expected -0.0 (0x{expected_bits:016x}), "
            f"got 0x{actual_bits:016x}"
        )

    def test_positive_zero(self, lib):
        v = c_parse(lib, "0.0")
        assert bits_of(v) == bits_of(0.0), "Positive zero should be +0.0"

    @pytest.mark.parametrize("s", [
        "5e-324", "4.9406564584124654e-324", "1e-310", "1e-315",
        "1e-320", "1e-309", "1e-323", "2.2250738585072013e-308",
        "1.5e-310", "9.9e-321", "1e-308", "2e-308",
    ])
    def test_subnormal(self, lib, s):
        expected = float(s)
        actual = c_parse(lib, s)
        assert bits_of(actual) == bits_of(expected), (
            f"Input {s!r}: expected {expected!r} (0x{bits_of(expected):016x}), "
            f"got {actual!r} (0x{bits_of(actual):016x})"
        )

    def test_smallest_normal(self, lib):
        s = "2.2250738585072014e-308"
        expected = float(s)
        actual = c_parse(lib, s)
        assert bits_of(actual) == bits_of(expected), (
            f"DBL_MIN: expected 0x{bits_of(expected):016x}, "
            f"got 0x{bits_of(actual):016x}"
        )

    @pytest.mark.parametrize("s", [
        "1e23", "1e24", "1e28", "1e30", "1e35", "5e25",
    ])
    def test_extended_exponent(self, lib, s):
        expected = float(s)
        actual = c_parse(lib, s)
        assert bits_of(actual) == bits_of(expected), (
            f"Input {s!r}: expected {expected!r} (0x{bits_of(expected):016x}), "
            f"got {actual!r} (0x{bits_of(actual):016x})"
        )

    @pytest.mark.parametrize("s", [
        "1.0", "-1.0", "3.14159265358979323",
        "100.0", "0.1", "0.01",
        "1e10", "1e-10", "1e100", "1e-100",
        "9007199254740992.0", "9007199254740993.0",
        "1.7976931348623157e308",
        "42", "0", "-42.5e3",
    ])
    def test_normal(self, lib, s):
        expected = float(s)
        actual = c_parse(lib, s)
        assert bits_of(actual) == bits_of(expected), (
            f"Input {s!r}: expected 0x{bits_of(expected):016x}, "
            f"got 0x{bits_of(actual):016x}"
        )

    def test_positive_overflow(self, lib):
        v = c_parse(lib, "1e309")
        assert v == float('inf'), f"Expected +inf, got {v}"

    def test_negative_overflow(self, lib):
        v = c_parse(lib, "-1e309")
        assert v == float('-inf'), f"Expected -inf, got {v}"

    @pytest.mark.parametrize("s", [
        "1234567890123456789e-320",
        "9999999999999999999e-340",
        "1234567890123456789e-200",
        "1000000000000000000e-330",
    ])
    def test_long_mantissa_large_exponent(self, lib, s):
        """19-digit mantissa with large exponent must be correctly parsed."""
        expected = float(s)
        actual = c_parse(lib, s)
        assert bits_of(actual) == bits_of(expected), (
            f"Input {s!r}: expected {expected!r} (0x{bits_of(expected):016x}), "
            f"got {actual!r} (0x{bits_of(actual):016x})"
        )


# ========== Pipeline results tests ==========


class TestPipelineResults:
    """Verify the pipeline produces correct aggregates with the conformant parser."""

    @pytest.fixture(scope="class")
    def reference(self):
        """Compute reference aggregates using Python's float()."""
        with open('/app/data/input.txt') as f:
            lines = [line.strip() for line in f if line.strip()]

        values = [float(line) for line in lines]

        xor_acc = 0
        neg_zero_count = 0
        subnormal_count = 0
        for v in values:
            b = bits_of(v)
            xor_acc ^= b
            if b == 0x8000000000000000:
                neg_zero_count += 1
            exp_field = (b >> 52) & 0x7FF
            sig_field = b & ((1 << 52) - 1)
            if exp_field == 0 and sig_field != 0:
                subnormal_count += 1

        s = c = 0.0
        for v in values:
            y = v - c
            t = s + y
            c = (t - s) - y
            s = t

        return {
            "total_count": len(values),
            "xor_hash": f"{xor_acc:016x}",
            "kahan_sum_hex": f"{bits_of(s):016x}",
            "negative_zero_count": neg_zero_count,
            "subnormal_count": subnormal_count,
        }

    def test_results_json_exists(self):
        assert os.path.exists('/app/results.json'), (
            "results.json not found at /app/results.json"
        )

    def test_total_count(self, reference):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['total_count'] == reference['total_count']

    def test_xor_hash(self, reference):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['xor_hash'] == reference['xor_hash']

    def test_kahan_sum(self, reference):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['kahan_sum_hex'] == reference['kahan_sum_hex']

    def test_negative_zero_count(self, reference):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['negative_zero_count'] == reference['negative_zero_count']

    def test_subnormal_count(self, reference):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert results['subnormal_count'] == reference['subnormal_count']
