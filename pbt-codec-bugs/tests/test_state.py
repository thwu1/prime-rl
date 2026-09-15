"""Verification tests for the codec audit task.

Checks three deliverables:
  1. All correctness bugs in codec.py are fixed (specific pathological inputs)
  2. Property-based test suite exists, uses Hypothesis correctly, and passes
  3. Bug taxonomy report exists with correct structure covering all bug categories
"""

import ast
import json
import math
import os
import struct
import subprocess
import sys

sys.path.insert(0, '/app')

from compact import encode, decode


# =====================================================================
# Deliverable 1: Bug fixes verified via specific pathological inputs
# =====================================================================


# --- Bug 1: Zigzag encoding for arbitrary-precision integers ---
# Original (n << 1) ^ (n >> 63) only works within 64-bit range.

class TestZigzagLargeIntegers:
    def test_positive_2_pow_63(self):
        n = 2**63
        assert decode(encode(n)) == n

    def test_negative_minus_2_pow_63_minus_1(self):
        n = -(2**63) - 1
        assert decode(encode(n)) == n

    def test_2_pow_100(self):
        n = 2**100
        assert decode(encode(n)) == n

    def test_neg_2_pow_100(self):
        n = -(2**100)
        assert decode(encode(n)) == n

    def test_boundary_positive(self):
        for n in [2**63 - 1, 2**63, 2**63 + 1]:
            assert decode(encode(n)) == n

    def test_boundary_negative(self):
        for n in [-(2**63), -(2**63) - 1, -(2**63) + 1]:
            assert decode(encode(n)) == n

    def test_2_pow_200(self):
        n = 2**200 + 17
        assert decode(encode(n)) == n

    def test_small_ints_still_work(self):
        for n in range(-200, 201):
            assert decode(encode(n)) == n


# --- Bug 2: Float negative-zero preservation ---
# TAG_FLOAT_ZERO optimisation must not conflate 0.0 and -0.0.

class TestFloatNegativeZero:
    def test_neg_zero_sign_preserved(self):
        result = decode(encode(-0.0))
        assert isinstance(result, float)
        assert math.copysign(1.0, result) == -1.0, \
            f"-0.0 sign was lost: copysign is {math.copysign(1.0, result)}"

    def test_pos_zero_unchanged(self):
        result = decode(encode(0.0))
        assert isinstance(result, float)
        assert math.copysign(1.0, result) == 1.0

    def test_zeros_encode_differently(self):
        assert encode(0.0) != encode(-0.0), \
            "0.0 and -0.0 must produce different byte sequences"

    def test_neg_zero_bits(self):
        result = decode(encode(-0.0))
        assert struct.pack('>d', result) == struct.pack('>d', -0.0)

    def test_regular_floats_unaffected(self):
        for f in [1.0, -1.0, 3.14, -2.71828, 1e100, 1e-100]:
            assert decode(encode(f)) == f

    def test_special_floats_unaffected(self):
        assert decode(encode(float('inf'))) == float('inf')
        assert decode(encode(float('-inf'))) == float('-inf')
        assert math.isnan(decode(encode(float('nan'))))


# --- Bug 3: Dict key position tracking (bytes vs characters) ---
# pos must advance by UTF-8 byte length of the key, not len(key).

class TestDictNonAsciiKeys:
    def test_latin_accented(self):
        d = {"café": 1}
        assert decode(encode(d)) == d

    def test_emoji_key(self):
        d = {"\U0001f389": "party"}
        assert decode(encode(d)) == d

    def test_mixed_ascii_and_non_ascii(self):
        d = {"hello": 1, "wörld": 2}
        assert decode(encode(d)) == d

    def test_cjk_keys(self):
        d = {"日本語": "japanese", "中文": "chinese"}
        assert decode(encode(d)) == d

    def test_non_ascii_key_with_nested_value(self):
        d = {"clé": [1, 2, 3]}
        assert decode(encode(d)) == d

    def test_multiple_non_ascii_keys(self):
        d = {"à": 1, "é": 2, "ü": 3}
        assert decode(encode(d)) == d

    def test_key_with_3_byte_chars(self):
        d = {"€€€": 100}
        assert decode(encode(d)) == d

    def test_ascii_keys_still_work(self):
        d = {"a": 1, "bb": 2, "ccc": [3, 4, 5]}
        assert decode(encode(d)) == d


# --- Bug 4: Tuple encoder element count vs byte count ---
# Encoder must write len(value) (element count), not len(inner_buf).

class TestTupleRoundtrip:
    def test_single_int(self):
        assert decode(encode((42,))) == (42,)

    def test_pair_of_ints(self):
        assert decode(encode((1, 2))) == (1, 2)

    def test_triple_of_ints(self):
        assert decode(encode((1, 2, 3))) == (1, 2, 3)

    def test_strings_in_tuple(self):
        assert decode(encode(("hello", "world"))) == ("hello", "world")

    def test_mixed_types(self):
        t = (1, "hello", True, None, 3.14)
        assert decode(encode(t)) == t

    def test_nested_tuples(self):
        t = ((1, 2), (3, 4))
        assert decode(encode(t)) == t

    def test_tuple_in_list(self):
        v = [(1, 2), (3, 4)]
        assert decode(encode(v)) == v

    def test_empty_tuple(self):
        assert decode(encode(())) == ()

    def test_tuple_with_none_still_works(self):
        assert decode(encode((None, None))) == (None, None)
        assert decode(encode((True, False))) == (True, False)


# --- Cross-cutting: complex nested structures after all fixes ---

class TestComplexNested:
    def test_deeply_nested(self):
        data = {
            "users": [
                {"name": "André", "scores": (95, 87, 92)},
                {"name": "José", "scores": (88, 91, 76)},
            ],
            "métadata": {"version": 2**70, "flags": [True, False, None]},
        }
        assert decode(encode(data)) == data

    def test_all_types_combined(self):
        data = [
            None, True, False,
            0, -1, 2**100, -(2**100),
            0.0, -0.0, 1.5,
            float('inf'), float('-inf'),
            "", "hello", "日本語",
            b"", b"\x00\xff",
            [], [1, 2],
            {}, {"ключ": "значение"},
            (), (1, "two", None),
        ]
        result = decode(encode(data))
        assert len(result) == len(data)
        for i, (orig, decoded) in enumerate(zip(data, result)):
            if isinstance(orig, float) and math.isnan(orig):
                assert math.isnan(decoded)
            elif isinstance(orig, float) and orig == 0.0:
                assert decoded == 0.0
                assert math.copysign(1.0, decoded) == math.copysign(1.0, orig), \
                    f"Index {i}: zero sign mismatch"
            else:
                assert decoded == orig, f"Index {i}: {orig!r} != {decoded!r}"
            assert type(decoded) is type(orig), \
                f"Index {i}: type mismatch {type(orig)} vs {type(decoded)}"


# --- Regression: existing basic functionality still works ---

class TestExistingUnitTestsStillPass:
    def test_none_roundtrip(self):
        assert decode(encode(None)) is None

    def test_bool_roundtrip(self):
        assert decode(encode(True)) is True
        assert decode(encode(False)) is False

    def test_small_int_range(self):
        for n in range(-100, 101):
            assert decode(encode(n)) == n

    def test_regular_float(self):
        assert decode(encode(3.14)) == 3.14

    def test_string_roundtrip(self):
        assert decode(encode("hello world")) == "hello world"

    def test_bytes_roundtrip(self):
        assert decode(encode(b"\x00\x01\x02")) == b"\x00\x01\x02"

    def test_list_roundtrip(self):
        assert decode(encode([1, 2, 3])) == [1, 2, 3]

    def test_dict_roundtrip(self):
        assert decode(encode({"a": 1, "b": 2})) == {"a": 1, "b": 2}

    def test_nested_roundtrip(self):
        d = {"name": "test", "values": [1, 2, 3], "active": True}
        assert decode(encode(d)) == d


# =====================================================================
# Deliverable 2: Property-based test suite verification
# =====================================================================

class TestPropertyBasedTestSuite:
    """Verify that /app/tests/test_pbt.py exists, uses Hypothesis
    with custom composite strategies, and passes."""

    PBT_PATH = '/app/tests/test_pbt.py'

    def test_pbt_file_exists(self):
        assert os.path.isfile(self.PBT_PATH), \
            f"Property-based test file not found at {self.PBT_PATH}"

    def test_pbt_is_valid_python(self):
        with open(self.PBT_PATH) as f:
            source = f.read()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"test_pbt.py has syntax errors: {exc}")

    def test_pbt_imports_hypothesis(self):
        with open(self.PBT_PATH) as f:
            source = f.read()
        tree = ast.parse(source)
        hyp_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and 'hypothesis' in node.module:
                hyp_imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if 'hypothesis' in alias.name:
                        hyp_imports.append(alias.name)
        assert len(hyp_imports) > 0, \
            "test_pbt.py must import from hypothesis"

    def test_pbt_uses_given_decorator(self):
        with open(self.PBT_PATH) as f:
            source = f.read()
        assert 'given' in source, \
            "test_pbt.py must use Hypothesis @given decorator"

    def test_pbt_has_custom_composite_strategy(self):
        """The suite must use st.recursive, @st.composite, or st.deferred
        to build custom strategies for the codec's recursive type system."""
        with open(self.PBT_PATH) as f:
            source = f.read()
        has_recursive = 'recursive' in source
        has_composite = 'composite' in source
        has_deferred = 'deferred' in source
        assert has_recursive or has_composite or has_deferred, \
            "test_pbt.py must define custom composite strategies " \
            "(st.recursive, @st.composite, or st.deferred)"

    def test_pbt_has_at_least_three_test_functions(self):
        with open(self.PBT_PATH) as f:
            source = f.read()
        tree = ast.parse(source)
        test_fns = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
        ]
        assert len(test_fns) >= 3, \
            f"test_pbt.py must have >= 3 test functions, found {len(test_fns)}"

    def test_pbt_tests_pass(self):
        """Execute the PBT tests and confirm they all pass."""
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', self.PBT_PATH,
             '-v', '--tb=short', '-x', '-q'],
            capture_output=True, text=True, timeout=180, cwd='/app',
        )
        assert result.returncode == 0, \
            f"PBT tests failed (exit {result.returncode}):\n" \
            f"{result.stdout[-2000:]}\n{result.stderr[-1000:]}"


# =====================================================================
# Deliverable 3: Bug taxonomy report verification
# =====================================================================

class TestBugTaxonomyReport:
    """Verify that /app/bug_report.json exists and documents all
    discovered bugs with required fields and coverage."""

    REPORT_PATH = '/app/bug_report.json'

    def test_report_exists(self):
        assert os.path.isfile(self.REPORT_PATH), \
            f"Bug taxonomy not found at {self.REPORT_PATH}"

    def test_report_is_valid_json_array(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "Bug report must be a JSON array"

    def test_report_has_at_least_four_entries(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        assert len(data) >= 4, \
            f"Bug report must document at least 4 bugs, found {len(data)}"

    def test_report_entry_structure(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        required = {'function', 'root_cause', 'trigger_input', 'property_type'}
        for i, entry in enumerate(data):
            assert isinstance(entry, dict), f"Entry {i} must be a dict"
            missing = required - set(entry.keys())
            assert not missing, f"Entry {i} missing fields: {missing}"
            for field in required:
                val = entry[field]
                assert isinstance(val, str) and len(val.strip()) > 0, \
                    f"Entry {i} field '{field}' must be a non-empty string"

    def test_report_covers_zigzag_bug(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        blob = ' '.join(
            f"{e.get('function','')} {e.get('root_cause','')}"
            for e in data
        ).lower()
        assert any(kw in blob for kw in ['zigzag', '64', 'arbitrary', 'precision', 'shift']), \
            "Bug report must document the zigzag/integer encoding bug"

    def test_report_covers_float_zero_bug(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        blob = ' '.join(
            f"{e.get('function','')} {e.get('root_cause','')}"
            for e in data
        ).lower()
        assert any(kw in blob for kw in ['zero', '-0', 'copysign', 'sign', 'negative zero']), \
            "Bug report must document the float negative-zero bug"

    def test_report_covers_dict_position_bug(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        blob = ' '.join(
            f"{e.get('function','')} {e.get('root_cause','')}"
            for e in data
        ).lower()
        assert any(kw in blob for kw in ['dict', 'key', 'utf', 'byte', 'char', 'position']), \
            "Bug report must document the dict key position tracking bug"

    def test_report_covers_tuple_count_bug(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        blob = ' '.join(
            f"{e.get('function','')} {e.get('root_cause','')}"
            for e in data
        ).lower()
        assert any(kw in blob for kw in ['tuple', 'count', 'element', 'inner_buf', 'byte length']), \
            "Bug report must document the tuple element count bug"
