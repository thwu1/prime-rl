#!/usr/bin/env python3
"""Tests for IEEE 754 float serialization pipeline task."""

import json
import struct
import math
import os
import sqlite3
import pytest


def hex_to_double(h):
    """Convert 16-char hex IEEE 754 bit pattern to a Python float."""
    return struct.unpack('>d', bytes.fromhex(h))[0]


def hex_to_bits(h):
    return int(h, 16)


def bits_to_hex(bits):
    return format(bits, '016X')


def compute_shortest(hex_val):
    """Independently compute the shortest round-trip-safe decimal string."""
    d = hex_to_double(hex_val)

    if math.isnan(d):
        return "NaN", 0
    if math.isinf(d):
        return ("-Inf" if d < 0 else "Inf"), 0
    if d == 0.0:
        return ("-0" if math.copysign(1.0, d) < 0 else "0"), 0

    sign = "-" if d < 0 else ""
    ad = abs(d)
    original_bytes = struct.pack('>d', ad)

    sci_str = None
    min_digits = 17
    for n in range(1, 18):
        s = f"{ad:.{n-1}e}"
        parsed = float(s)
        if struct.pack('>d', parsed) == original_bytes:
            sci_str = s
            min_digits = n
            break

    if sci_str is None:
        sci_str = f"{ad:.16e}"

    parts = sci_str.split('e')
    mant = parts[0]
    exp = int(parts[1])

    if '.' in mant:
        ip, fp = mant.split('.')
        digits = ip + fp.rstrip('0')
    else:
        digits = mant

    dpos = exp + 1
    if dpos <= 0:
        fixed = "0." + "0" * (-dpos) + digits
    elif dpos >= len(digits):
        fixed = digits + "0" * (dpos - len(digits))
    else:
        fixed = digits[:dpos] + "." + digits[dpos:]

    if len(digits) == 1:
        sci = f"{digits}e{exp}"
    else:
        sci = f"{digits[0]}.{digits[1:]}e{exp}"

    f_full = sign + fixed
    s_full = sign + sci

    if len(f_full) <= len(s_full):
        return f_full, min_digits
    else:
        return s_full, min_digits


def expected_notation(shortest):
    """Determine the expected notation type from a shortest string."""
    if shortest in ("NaN", "Inf", "-Inf", "0", "-0"):
        return "special"
    if 'e' in shortest:
        return "scientific"
    return "fixed"


def compute_pred_succ(hex_val):
    """Independently compute predecessor and successor hex values."""
    bits = hex_to_bits(hex_val)
    d = hex_to_double(hex_val)

    if math.isnan(d) or math.isinf(d):
        return None, None

    sign = bits >> 63

    # Predecessor (next smaller in IEEE 754 total order)
    if sign == 0:  # positive or +0
        if bits == 0:  # +0 -> -0
            pred = 0x8000000000000000
        else:
            pred = bits - 1
    else:  # negative
        pred = bits + 1

    # Successor (next larger in IEEE 754 total order)
    if sign == 0:  # positive or +0
        succ = bits + 1
    else:  # negative or -0
        mag = bits & 0x7FFFFFFFFFFFFFFF
        if mag == 0:  # -0 -> +0
            succ = 0x0000000000000000
        else:
            succ = bits - 1

    return bits_to_hex(pred), bits_to_hex(succ)


def simulate_fast_convert(hex_val):
    """Simulate the buggy fast_convert.c behavior in Python."""
    d = hex_to_double(hex_val)

    if math.isnan(d):
        return "NaN"
    if math.isinf(d):
        return "-Inf" if d < 0 else "Inf"
    # Bug 1: no negative zero check
    if d == 0.0:
        return "0"

    ad = abs(d)
    target = struct.pack('>d', ad)
    sign = "-" if d < 0 else ""

    for p in range(0, 17):
        s = format(ad, f'.{p}e')
        if struct.pack('>d', float(s)) == target:
            return sign + s

    return sign + format(ad, '.16e')


def classify_divergence(fast_out, correct_out, hex_val):
    """Classify the bug type for a divergence."""
    if fast_out == "0" and correct_out == "-0":
        return "negative_zero"
    # If correct uses fixed notation, bug is that fast never tried fixed
    if 'e' not in correct_out:
        return "notation_selection"
    # Correct is scientific but fast has wrong exponent formatting
    return "exponent_padding"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_data():
    """Read all challenge values from the SQLite database."""
    conn = sqlite3.connect('/app/challenge.db')
    c = conn.cursor()
    c.execute("SELECT id, hex_bits, category, precision_class FROM ieee754_values ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows


@pytest.fixture(scope="session")
def results_data():
    """Load and parse results.json."""
    if not os.path.isfile('/app/results.json'):
        pytest.fail("/app/results.json not found")
    with open('/app/results.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fast_convert_sim(db_data):
    """Simulate fast_convert.c output for all values."""
    result = {}
    for row in db_data:
        rid, hex_val = row[0], row[1]
        result[rid] = simulate_fast_convert(hex_val)
    return result


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_output_file_exists(self):
        assert os.path.isfile('/app/results.json'), "/app/results.json not found"

    def test_valid_json(self):
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        assert isinstance(data, dict), "results.json root must be an object"

    def test_has_results_key(self, results_data):
        assert 'results' in results_data, "Missing 'results' key"
        assert isinstance(results_data['results'], list), "'results' must be an array"

    def test_has_divergences_key(self, results_data):
        assert 'divergences' in results_data, "Missing 'divergences' key"
        assert isinstance(results_data['divergences'], list), "'divergences' must be an array"

    def test_has_summary_key(self, results_data):
        assert 'summary' in results_data, "Missing 'summary' key"
        assert isinstance(results_data['summary'], dict), "'summary' must be an object"

    def test_correct_result_count(self, results_data, db_data):
        assert len(results_data['results']) == len(db_data), \
            f"Expected {len(db_data)} results, got {len(results_data['results'])}"

    def test_all_ids_present(self, results_data, db_data):
        expected_ids = {row[0] for row in db_data}
        actual_ids = {r['id'] for r in results_data['results']}
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        assert not missing and not extra, \
            f"Missing IDs: {missing}, Extra IDs: {extra}"

    def test_hex_bits_match_database(self, results_data, db_data):
        db_hex = {row[0]: row[1] for row in db_data}
        failures = []
        for r in results_data['results']:
            if r['hex_bits'] != db_hex.get(r['id']):
                failures.append(f"ID {r['id']}: got {r['hex_bits']}, expected {db_hex.get(r['id'])}")
        assert not failures, f"hex_bits mismatches:\n" + "\n".join(failures)

    def test_result_entry_fields(self, results_data):
        required = {'id', 'hex_bits', 'category', 'shortest', 'notation',
                     'min_digits', 'predecessor_hex', 'successor_hex'}
        for r in results_data['results']:
            missing = required - set(r.keys())
            assert not missing, \
                f"ID {r.get('id', '?')}: missing fields {missing}"

    def test_notation_values_valid(self, results_data):
        valid = {'fixed', 'scientific', 'special'}
        for r in results_data['results']:
            assert r['notation'] in valid, \
                f"ID {r['id']}: invalid notation '{r['notation']}'"

    def test_categories_match_database(self, results_data, db_data):
        db_cat = {row[0]: row[2] for row in db_data}
        failures = []
        for r in results_data['results']:
            if r['category'] != db_cat.get(r['id']):
                failures.append(f"ID {r['id']}: got '{r['category']}', expected '{db_cat.get(r['id'])}'")
        assert not failures, f"category mismatches:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Round-trip safety
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_all_values_roundtrip(self, results_data):
        """Every output string must parse back to the exact same double."""
        failures = []
        for r in results_data['results']:
            original_bytes = bytes.fromhex(r['hex_bits'])
            d = struct.unpack('>d', original_bytes)[0]

            if math.isnan(d):
                if r['shortest'] != "NaN":
                    failures.append(f"ID {r['id']}: expected 'NaN', got '{r['shortest']}'")
                continue

            try:
                parsed = float(r['shortest'])
            except ValueError:
                failures.append(f"ID {r['id']}: '{r['shortest']}' is not a valid float literal")
                continue

            parsed_bytes = struct.pack('>d', parsed)
            if parsed_bytes != original_bytes:
                failures.append(
                    f"ID {r['id']} ({r['hex_bits']}): '{r['shortest']}' -> "
                    f"{parsed_bytes.hex().upper()}"
                )

        assert not failures, \
            f"{len(failures)} round-trip failure(s):\n" + "\n".join(failures[:20])


# ---------------------------------------------------------------------------
# Minimality
# ---------------------------------------------------------------------------

class TestMinimality:
    def test_all_values_are_shortest(self, results_data):
        """No output string should be longer than the independently computed shortest."""
        failures = []
        for r in results_data['results']:
            expected, _ = compute_shortest(r['hex_bits'])
            if len(r['shortest']) > len(expected):
                failures.append(
                    f"ID {r['id']} ({r['hex_bits']}): got '{r['shortest']}' "
                    f"({len(r['shortest'])} chars), shortest is '{expected}' "
                    f"({len(expected)} chars)"
                )

        assert not failures, \
            f"{len(failures)} non-shortest representation(s):\n" + "\n".join(failures[:20])


# ---------------------------------------------------------------------------
# Notation correctness
# ---------------------------------------------------------------------------

class TestNotation:
    def test_notation_matches_representation(self, results_data):
        """The notation field must match the actual representation used."""
        failures = []
        for r in results_data['results']:
            expected = expected_notation(r['shortest'])
            if r['notation'] != expected:
                failures.append(
                    f"ID {r['id']}: notation '{r['notation']}' but string '{r['shortest']}' "
                    f"is actually '{expected}'"
                )

        assert not failures, \
            f"{len(failures)} notation error(s):\n" + "\n".join(failures[:20])

    def test_notation_optimality(self, results_data):
        """The chosen notation must be optimal (or tied-fixed)."""
        failures = []
        for r in results_data['results']:
            exp_shortest, _ = compute_shortest(r['hex_bits'])
            exp_notation = expected_notation(exp_shortest)
            if r['notation'] != exp_notation:
                failures.append(
                    f"ID {r['id']}: used '{r['notation']}' but optimal is '{exp_notation}' "
                    f"('{exp_shortest}')"
                )

        assert not failures, \
            f"{len(failures)} suboptimal notation(s):\n" + "\n".join(failures[:20])


# ---------------------------------------------------------------------------
# Min digits
# ---------------------------------------------------------------------------

class TestMinDigits:
    def test_min_digits_correct(self, results_data):
        """min_digits must match independently computed minimum significant digits."""
        failures = []
        for r in results_data['results']:
            _, expected_md = compute_shortest(r['hex_bits'])
            if r['min_digits'] != expected_md:
                failures.append(
                    f"ID {r['id']} ({r['hex_bits']}): min_digits={r['min_digits']}, "
                    f"expected={expected_md}"
                )
        assert not failures, \
            f"{len(failures)} min_digits error(s):\n" + "\n".join(failures[:20])

    def test_min_digits_range(self, results_data):
        """min_digits must be 0 for specials, 1-17 for others."""
        for r in results_data['results']:
            if r['notation'] == 'special':
                assert r['min_digits'] == 0, \
                    f"ID {r['id']}: special value should have min_digits=0, got {r['min_digits']}"
            else:
                assert 1 <= r['min_digits'] <= 17, \
                    f"ID {r['id']}: min_digits={r['min_digits']} out of range [1,17]"


# ---------------------------------------------------------------------------
# Predecessor / Successor
# ---------------------------------------------------------------------------

class TestPredecessorSuccessor:
    def test_pred_succ_correct(self, results_data):
        """predecessor_hex and successor_hex must match bit arithmetic."""
        failures = []
        for r in results_data['results']:
            exp_pred, exp_succ = compute_pred_succ(r['hex_bits'])
            if r['predecessor_hex'] != exp_pred:
                failures.append(
                    f"ID {r['id']}: predecessor_hex='{r['predecessor_hex']}', "
                    f"expected='{exp_pred}'"
                )
            if r['successor_hex'] != exp_succ:
                failures.append(
                    f"ID {r['id']}: successor_hex='{r['successor_hex']}', "
                    f"expected='{exp_succ}'"
                )
        assert not failures, \
            f"{len(failures)} predecessor/successor error(s):\n" + "\n".join(failures[:20])

    def test_pred_succ_null_for_nonfinite(self, results_data):
        """NaN, +Inf, -Inf must have null predecessor and successor."""
        for r in results_data['results']:
            d = hex_to_double(r['hex_bits'])
            if math.isnan(d) or math.isinf(d):
                assert r['predecessor_hex'] is None, \
                    f"ID {r['id']}: non-finite should have null predecessor_hex"
                assert r['successor_hex'] is None, \
                    f"ID {r['id']}: non-finite should have null successor_hex"

    def test_pred_succ_nonnull_for_finite(self, results_data):
        """Finite values (including +/-0) must have non-null predecessor and successor."""
        for r in results_data['results']:
            d = hex_to_double(r['hex_bits'])
            if not math.isnan(d) and not math.isinf(d):
                assert r['predecessor_hex'] is not None, \
                    f"ID {r['id']}: finite value should have non-null predecessor_hex"
                assert r['successor_hex'] is not None, \
                    f"ID {r['id']}: finite value should have non-null successor_hex"

    def test_predecessor_is_smaller(self, results_data):
        """For non-special finite values, predecessor should be smaller on number line."""
        for r in results_data['results']:
            d = hex_to_double(r['hex_bits'])
            if math.isnan(d) or math.isinf(d):
                continue
            if r['predecessor_hex'] is None:
                continue
            pred_d = hex_to_double(r['predecessor_hex'])
            # In total order, predecessor is strictly less
            # For +0, predecessor is -0 which is "less" in total order
            if d == 0.0 and math.copysign(1.0, d) > 0:
                assert pred_d == 0.0 and math.copysign(1.0, pred_d) < 0, \
                    f"ID {r['id']}: predecessor of +0 should be -0"
            elif d == 0.0 and math.copysign(1.0, d) < 0:
                assert pred_d < 0, \
                    f"ID {r['id']}: predecessor of -0 should be negative"
            else:
                assert pred_d < d, \
                    f"ID {r['id']}: predecessor {pred_d} not less than {d}"

    def test_successor_is_larger(self, results_data):
        """For non-special finite values, successor should be larger on number line."""
        for r in results_data['results']:
            d = hex_to_double(r['hex_bits'])
            if math.isnan(d) or math.isinf(d):
                continue
            if r['successor_hex'] is None:
                continue
            succ_d = hex_to_double(r['successor_hex'])
            if d == 0.0 and math.copysign(1.0, d) < 0:
                assert succ_d == 0.0 and math.copysign(1.0, succ_d) > 0, \
                    f"ID {r['id']}: successor of -0 should be +0"
            elif d == 0.0 and math.copysign(1.0, d) > 0:
                assert succ_d > 0, \
                    f"ID {r['id']}: successor of +0 should be positive"
            else:
                assert succ_d > d, \
                    f"ID {r['id']}: successor {succ_d} not greater than {d}"

    def test_zero_transitions(self, results_data):
        """Verify the specific +0/-0 transition pairs."""
        results_by_hex = {r['hex_bits']: r for r in results_data['results']}

        # +0 -> predecessor is -0, successor is smallest positive subnormal
        if '0000000000000000' in results_by_hex:
            r = results_by_hex['0000000000000000']
            assert r['predecessor_hex'] == '8000000000000000', \
                f"predecessor of +0 should be -0 (8000000000000000)"
            assert r['successor_hex'] == '0000000000000001', \
                f"successor of +0 should be smallest subnormal (0000000000000001)"

        # -0 -> predecessor is smallest negative subnormal, successor is +0
        if '8000000000000000' in results_by_hex:
            r = results_by_hex['8000000000000000']
            assert r['predecessor_hex'] == '8000000000000001', \
                f"predecessor of -0 should be 8000000000000001"
            assert r['successor_hex'] == '0000000000000000', \
                f"successor of -0 should be +0 (0000000000000000)"


# ---------------------------------------------------------------------------
# Special values
# ---------------------------------------------------------------------------

class TestSpecialValues:
    def test_positive_zero(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '0000000000000000'), None)
        assert r is not None, "Missing +0 entry"
        assert r['shortest'] == '0', f"Expected '0', got '{r['shortest']}'"
        assert r['notation'] == 'special'

    def test_negative_zero(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '8000000000000000'), None)
        assert r is not None, "Missing -0 entry"
        assert r['shortest'] == '-0', f"Expected '-0', got '{r['shortest']}'"
        assert r['notation'] == 'special'

    def test_positive_inf(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '7FF0000000000000'), None)
        assert r is not None, "Missing +Inf entry"
        assert r['shortest'] == 'Inf', f"Expected 'Inf', got '{r['shortest']}'"
        assert r['notation'] == 'special'

    def test_negative_inf(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == 'FFF0000000000000'), None)
        assert r is not None, "Missing -Inf entry"
        assert r['shortest'] == '-Inf', f"Expected '-Inf', got '{r['shortest']}'"
        assert r['notation'] == 'special'

    def test_nan(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '7FF8000000000000'), None)
        assert r is not None, "Missing NaN entry"
        assert r['shortest'] == 'NaN', f"Expected 'NaN', got '{r['shortest']}'"
        assert r['notation'] == 'special'


# ---------------------------------------------------------------------------
# Known value spot checks
# ---------------------------------------------------------------------------

class TestKnownValues:
    @pytest.mark.parametrize("hex_bits,expected_shortest", [
        ("3FF0000000000000", "1"),       # 1.0
        ("4000000000000000", "2"),       # 2.0
        ("3FE0000000000000", "0.5"),     # 0.5
        ("3FD0000000000000", "0.25"),    # 0.25
        ("4024000000000000", "10"),      # 10.0
        ("4090000000000000", "1024"),    # 1024.0
        ("3FB0000000000000", "0.0625"),  # 0.0625
        ("4030000000000000", "16"),      # 16.0
    ])
    def test_known_value(self, hex_bits, expected_shortest, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == hex_bits), None)
        assert r is not None, f"Missing entry for {hex_bits}"
        assert r['shortest'] == expected_shortest, \
            f"{hex_bits}: expected '{expected_shortest}', got '{r['shortest']}'"


# ---------------------------------------------------------------------------
# Formatting rules
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_no_trailing_zeros(self, results_data):
        for r in results_data['results']:
            s = r['shortest']
            if s in ("0", "-0", "NaN", "Inf", "-Inf"):
                continue
            before_e = s.split('e')[0] if 'e' in s else s
            if '.' in before_e:
                assert not before_e.endswith('0'), \
                    f"ID {r['id']}: trailing zero in '{s}'"

    def test_no_unnecessary_decimal_point(self, results_data):
        for r in results_data['results']:
            s = r['shortest']
            if s in ("0", "-0", "NaN", "Inf", "-Inf"):
                continue
            before_e = s.split('e')[0] if 'e' in s else s
            assert not before_e.endswith('.'), \
                f"ID {r['id']}: unnecessary decimal point in '{s}'"

    def test_no_plus_in_exponent(self, results_data):
        for r in results_data['results']:
            assert 'e+' not in r['shortest'] and 'E+' not in r['shortest'], \
                f"ID {r['id']}: '+' in exponent in '{r['shortest']}'"

    def test_no_leading_zero_in_exponent(self, results_data):
        for r in results_data['results']:
            s = r['shortest']
            if 'e' not in s:
                continue
            exp_part = s.split('e')[1]
            exp_digits = exp_part.lstrip('-')
            if len(exp_digits) > 1:
                assert not exp_digits.startswith('0'), \
                    f"ID {r['id']}: leading zero in exponent in '{s}'"

    def test_lowercase_e(self, results_data):
        for r in results_data['results']:
            if r['shortest'] in ("NaN", "Inf", "-Inf"):
                continue
            assert 'E' not in r['shortest'], \
                f"ID {r['id']}: uppercase 'E' in '{r['shortest']}'"

    def test_digit_before_decimal(self, results_data):
        for r in results_data['results']:
            clean = r['shortest'].lstrip('-')
            assert not clean.startswith('.'), \
                f"ID {r['id']}: no digit before decimal in '{r['shortest']}'"

    def test_no_empty_outputs(self, results_data):
        for r in results_data['results']:
            assert len(r['shortest']) > 0, f"ID {r['id']}: empty shortest string"


# ---------------------------------------------------------------------------
# Divergence analysis
# ---------------------------------------------------------------------------

class TestDivergences:
    def test_divergences_structure(self, results_data):
        """Each divergence entry must have required fields with valid values."""
        valid_classes = {'negative_zero', 'exponent_padding', 'notation_selection'}
        for d in results_data['divergences']:
            assert 'id' in d, "Divergence entry missing 'id'"
            assert 'fast_output' in d, f"Divergence ID {d.get('id')}: missing 'fast_output'"
            assert 'correct_output' in d, f"Divergence ID {d.get('id')}: missing 'correct_output'"
            assert 'bug_class' in d, f"Divergence ID {d.get('id')}: missing 'bug_class'"
            assert d['bug_class'] in valid_classes, \
                f"Divergence ID {d['id']}: invalid bug_class '{d['bug_class']}'"

    def test_divergences_complete(self, results_data, db_data, fast_convert_sim):
        """All divergences between fast_convert and correct output must be reported."""
        results_by_id = {r['id']: r for r in results_data['results']}

        expected_ids = set()
        for row in db_data:
            rid = row[0]
            fast_out = fast_convert_sim[rid]
            correct = results_by_id[rid]['shortest']
            if fast_out != correct:
                expected_ids.add(rid)

        reported_ids = {d['id'] for d in results_data['divergences']}

        missing = expected_ids - reported_ids
        extra = reported_ids - expected_ids
        assert not missing, f"Missing divergences for IDs: {sorted(missing)}"
        assert not extra, f"Extra divergences for IDs: {sorted(extra)}"

    def test_divergence_fast_output(self, results_data, fast_convert_sim):
        """fast_output field must match simulated fast_convert output."""
        failures = []
        for d in results_data['divergences']:
            expected = fast_convert_sim[d['id']]
            if d['fast_output'] != expected:
                failures.append(
                    f"ID {d['id']}: fast_output '{d['fast_output']}' != "
                    f"expected '{expected}'"
                )
        assert not failures, \
            f"{len(failures)} fast_output mismatch(es):\n" + "\n".join(failures[:20])

    def test_divergence_correct_output(self, results_data):
        """correct_output must match the shortest field in results."""
        results_by_id = {r['id']: r for r in results_data['results']}
        failures = []
        for d in results_data['divergences']:
            expected = results_by_id[d['id']]['shortest']
            if d['correct_output'] != expected:
                failures.append(
                    f"ID {d['id']}: correct_output '{d['correct_output']}' != "
                    f"shortest '{expected}'"
                )
        assert not failures, \
            f"{len(failures)} correct_output mismatch(es):\n" + "\n".join(failures[:20])

    def test_divergence_bug_class(self, results_data, db_data):
        """Bug class must be correctly classified."""
        db_hex = {row[0]: row[1] for row in db_data}
        failures = []
        for d in results_data['divergences']:
            hex_val = db_hex[d['id']]
            expected_class = classify_divergence(
                d['fast_output'], d['correct_output'], hex_val
            )
            if d['bug_class'] != expected_class:
                failures.append(
                    f"ID {d['id']}: bug_class '{d['bug_class']}' != "
                    f"expected '{expected_class}' "
                    f"(fast='{d['fast_output']}', correct='{d['correct_output']}')"
                )
        assert not failures, \
            f"{len(failures)} bug_class error(s):\n" + "\n".join(failures[:20])

    def test_has_negative_zero_divergence(self, results_data):
        """There must be at least one negative_zero divergence (-0 value)."""
        nz = [d for d in results_data['divergences'] if d['bug_class'] == 'negative_zero']
        assert len(nz) >= 1, "Expected at least one negative_zero divergence"

    def test_has_notation_selection_divergences(self, results_data):
        """There must be notation_selection divergences (fixed vs scientific)."""
        ns = [d for d in results_data['divergences'] if d['bug_class'] == 'notation_selection']
        assert len(ns) >= 5, \
            f"Expected at least 5 notation_selection divergences, got {len(ns)}"

    def test_has_exponent_padding_divergences(self, results_data):
        """There must be exponent_padding divergences (C %e formatting)."""
        ep = [d for d in results_data['divergences'] if d['bug_class'] == 'exponent_padding']
        assert len(ep) >= 3, \
            f"Expected at least 3 exponent_padding divergences, got {len(ep)}"


# ---------------------------------------------------------------------------
# Summary verification
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_has_all_categories(self, results_data, db_data):
        db_cats = {row[2] for row in db_data}
        summary = results_data['summary']
        for cat in db_cats:
            assert cat in summary, f"Missing category '{cat}' in summary"

    def test_summary_count_totals(self, results_data):
        expected = {}
        for r in results_data['results']:
            cat = r['category']
            if cat not in expected:
                expected[cat] = {'count': 0, 'scientific': 0, 'fixed': 0, 'special': 0}
            expected[cat]['count'] += 1
            if r['notation'] == 'scientific':
                expected[cat]['scientific'] += 1
            elif r['notation'] == 'fixed':
                expected[cat]['fixed'] += 1
            elif r['notation'] == 'special':
                expected[cat]['special'] += 1

        summary = results_data['summary']
        for cat, exp in expected.items():
            assert summary[cat]['count'] == exp['count'], \
                f"'{cat}': count {summary[cat]['count']} != {exp['count']}"
            assert summary[cat]['scientific_count'] == exp['scientific'], \
                f"'{cat}': scientific_count {summary[cat]['scientific_count']} != {exp['scientific']}"
            assert summary[cat]['fixed_count'] == exp['fixed'], \
                f"'{cat}': fixed_count {summary[cat]['fixed_count']} != {exp['fixed']}"
            assert summary[cat]['special_count'] == exp['special'], \
                f"'{cat}': special_count {summary[cat]['special_count']} != {exp['special']}"

    def test_summary_subcounts_add_up(self, results_data):
        summary = results_data['summary']
        for cat, data in summary.items():
            total = data['scientific_count'] + data['fixed_count'] + data['special_count']
            assert total == data['count'], \
                f"'{cat}': subcounts sum to {total}, but count is {data['count']}"

    def test_summary_no_extra_categories(self, results_data, db_data):
        db_cats = {row[2] for row in db_data}
        summary_cats = set(results_data['summary'].keys())
        extra = summary_cats - db_cats
        assert not extra, f"Extra categories in summary: {extra}"


# ---------------------------------------------------------------------------
# Denormal-specific tests
# ---------------------------------------------------------------------------

class TestDenormals:
    def test_smallest_denormal_uses_scientific(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '0000000000000001'), None)
        assert r is not None, "Missing smallest denormal"
        assert r['notation'] == 'scientific', \
            f"Smallest denormal should use scientific: got '{r['shortest']}'"

    def test_largest_finite_uses_scientific(self, results_data):
        r = next((r for r in results_data['results'] if r['hex_bits'] == '7FEFFFFFFFFFFFFF'), None)
        assert r is not None, "Missing largest finite"
        assert r['notation'] == 'scientific', \
            f"Largest finite should use scientific: got '{r['shortest']}'"
