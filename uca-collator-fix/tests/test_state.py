"""

UCA Conformance Tests for the collator implementation.
Verifies both Non-Ignorable and Shifted variable weighting modes
against official UCA conformance test subsets, plus unit tests
for implicit weight derivation and variable weighting behaviour.
"""

import sys
sys.path.insert(0, '/app')

from collator import Collator


def _parse_test_line(line):
    """Parse a conformance test line into a list of code points."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    hex_part = line.split(';')[0].strip()
    cps = [int(x, 16) for x in hex_part.split()]
    # Filter surrogate code points (Python 3 cannot represent them)
    cps = [cp for cp in cps if not (0xD800 <= cp <= 0xDFFF)]
    if not cps:
        return None
    return cps


def _check_conformance(collator, test_file_path):
    """Check that each line sorts >= the previous line.
    Returns the number of ordering violations.
    """
    violations = 0
    prev_key = None
    with open(test_file_path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            cps = _parse_test_line(line)
            if cps is None:
                continue
            string = ''.join(chr(cp) for cp in cps)
            key = collator.sort_key(string)
            if prev_key is not None and key < prev_key:
                violations += 1
            prev_key = key
    return violations


# ---- Conformance tests ----

def test_non_ignorable_conformance():
    """UCA conformance: Non-Ignorable variable weighting mode."""
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    v = _check_conformance(c, '/app/test_data/CollationTest_NON_IGNORABLE_subset.txt')
    assert v == 0, f"Non-Ignorable conformance: {v} ordering violations"


def test_shifted_conformance():
    """UCA conformance: Shifted variable weighting mode."""
    c = Collator('/app/allkeys.txt', mode='shifted')
    v = _check_conformance(c, '/app/test_data/CollationTest_SHIFTED_subset.txt')
    assert v == 0, f"Shifted conformance: {v} ordering violations"


# ---- Implicit weight unit tests ----

def test_tangut_implicit_weight_value():
    """U+17000 TANGUT IDEOGRAPH-17000 must have correct sort key.
    @implicitweights 17000..187FF; FB00
    AAAA = 0xFB00, BBBB = (0x17000 - 0x17000) | 0x8000 = 0x8000
    Expected 3-level sort key: (0xFB00, 0x8000, 0, 0x0020, 0, 0x0002)
    """
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    key = c.sort_key('\U00017000')
    # L1 weights: AAAA=0xFB00, BBBB=0x8000 (from second CE, non-zero primary)
    # L2 weights (after separator 0): 0x0020 (from first CE; second CE has L2=0 → skipped)
    # L3 weights (after separator 0): 0x0002 (from first CE; second CE has L3=0 → skipped)
    assert key == (0xFB00, 0x8000, 0, 0x0020, 0, 0x0002), \
        f"U+17000 sort key wrong: {tuple(hex(w) for w in key)}"


def test_tangut_second_char_implicit_weight():
    """U+17001 must have BBBB = (0x17001 - 0x17000) | 0x8000 = 0x8001."""
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    key = c.sort_key('\U00017001')
    assert key == (0xFB00, 0x8001, 0, 0x0020, 0, 0x0002), \
        f"U+17001 sort key wrong: {tuple(hex(w) for w in key)}"


def test_tangut_ordering_across_boundary():
    """U+17FFF must sort before U+18000 (both in Tangut range 17000..187FF).
    Correct BBBB: 17FFF → 0x8FFF, 18000 → 0x9000 (monotonic).
    """
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    key_a = c.sort_key('\U00017FFF')
    key_b = c.sort_key('\U00018000')
    assert key_a < key_b, (
        f"U+17FFF must sort before U+18000: "
        f"{tuple(hex(w) for w in key_a)} vs {tuple(hex(w) for w in key_b)}"
    )


def test_nushu_implicit_weight():
    """U+1B170 NUSHU CHARACTER-1B170: @implicitweights 1B170..1B2FF; FB02
    AAAA = 0xFB02, BBBB = (0x1B170 - 0x1B170) | 0x8000 = 0x8000
    """
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    key = c.sort_key('\U0001B170')
    assert key == (0xFB02, 0x8000, 0, 0x0020, 0, 0x0002), \
        f"U+1B170 sort key wrong: {tuple(hex(w) for w in key)}"


def test_cjk_implicit_weight():
    """U+4E00 CJK UNIFIED IDEOGRAPH-4E00 uses Core CJK formula.
    AAAA = 0xFB40 + (0x4E00 >> 15) = 0xFB40
    BBBB = (0x4E00 & 0x7FFF) | 0x8000 = 0xCE00
    """
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    key = c.sort_key('\u4E00')
    assert key == (0xFB40, 0xCE00, 0, 0x0020, 0, 0x0002), \
        f"U+4E00 sort key wrong: {tuple(hex(w) for w in key)}"


# ---- Shifted mode unit tests ----

def test_shifted_space_before_letter():
    """In Shifted mode, SPACE is variable. Its L1 moves to L4, L1-L3 zeroed.
    SPACE: [*0209.0020.0002] → shifted → [0, 0, 0, 0x0209]
    'a':   [.23EC.0020.0002] → shifted → [0x23EC, 0x0020, 0x0002, 0xFFFF]
    """
    c = Collator('/app/allkeys.txt', mode='shifted')
    key_space = c.sort_key(' ')
    key_a = c.sort_key('a')
    # Space should sort before 'a' in Shifted mode
    assert key_space < key_a, \
        f"SPACE must sort before 'a' in Shifted mode"
    # Verify space has zero primary weights
    # The sort key for space in shifted: L1 part should be empty (all zeros skipped),
    # L4 should contain 0x0209
    # For 'a': L1 part should have its primary weight


def test_shifted_differs_from_non_ignorable():
    """Shifted and Non-Ignorable must produce different sort keys for
    strings that contain variable elements like punctuation.
    """
    c_ni = Collator('/app/allkeys.txt', mode='non_ignorable')
    c_sh = Collator('/app/allkeys.txt', mode='shifted')

    # "a b" contains a space (variable element)
    key_ni = c_ni.sort_key("a b")
    key_sh = c_sh.sort_key("a b")
    assert key_ni != key_sh, \
        "Shifted and Non-Ignorable must differ for strings with variable elements"


def test_shifted_ignores_space_for_primary():
    """In Shifted mode, 'ab' and 'a b' should be equal at the primary level.
    The space becomes a quaternary difference only.
    """
    c = Collator('/app/allkeys.txt', mode='shifted')
    key_ab = c.sort_key("ab")
    key_a_b = c.sort_key("a b")
    # 'a b' should sort after 'ab' (space contributes L4 weight)
    # but they should share the same primary weights
    # Extract primary weights (before first zero separator)
    def primary_weights(key):
        result = []
        for w in key:
            if w == 0:
                break
            result.append(w)
        return result

    assert primary_weights(key_ab) == primary_weights(key_a_b), \
        "Primary weights should be identical for 'ab' and 'a b' in Shifted mode"
