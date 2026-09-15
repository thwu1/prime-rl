"""
Unicode UAX #29 Text Segmentation — Grapheme Cluster, Word, and Sentence boundaries.

Uses a compiled C shared library (libpropdb.so) for Unicode property lookups
via ctypes, with ICU's USet API for Extended_Pictographic set operations.

Implements the default extended grapheme cluster, word, and sentence boundary
rules from Unicode Standard Annex #29 (Unicode 17.0).

"""

import ctypes
import ctypes.util
import os
import urllib.request

# ---------------------------------------------------------------------------
# Load native property database via ctypes
# ---------------------------------------------------------------------------

_DATA_DIR = '/app/testdata'

# Download DerivedCoreProperties.txt if not present (needed for InCB / GB9c)
_dcp_path = os.path.join(_DATA_DIR, 'DerivedCoreProperties.txt')
if not os.path.exists(_dcp_path):
    urllib.request.urlretrieve(
        'https://www.unicode.org/Public/UCD/latest/ucd/DerivedCoreProperties.txt',
        _dcp_path
    )

# Load the C shared library
_lib = ctypes.CDLL('/app/libpropdb.so')

# Define function signatures
_lib.init_propdb.argtypes = [ctypes.c_char_p]
_lib.init_propdb.restype = ctypes.c_int

_lib.get_gcb.argtypes = [ctypes.c_int32]
_lib.get_gcb.restype = ctypes.c_int

_lib.get_wb.argtypes = [ctypes.c_int32]
_lib.get_wb.restype = ctypes.c_int

_lib.get_sb.argtypes = [ctypes.c_int32]
_lib.get_sb.restype = ctypes.c_int

_lib.get_incb.argtypes = [ctypes.c_int32]
_lib.get_incb.restype = ctypes.c_int

_lib.is_ext_pict.argtypes = [ctypes.c_int32]
_lib.is_ext_pict.restype = ctypes.c_int

# Initialize the property database
_lib.init_propdb(_DATA_DIR.encode('utf-8'))

# ---------------------------------------------------------------------------
# Property value constants (must match C #defines in propdb.c)
# ---------------------------------------------------------------------------

# GCB
_GCB_MAP = {
    0: 'Other', 1: 'CR', 2: 'LF', 3: 'Control', 4: 'Extend', 5: 'ZWJ',
    6: 'Regional_Indicator', 7: 'Prepend', 8: 'SpacingMark',
    9: 'L', 10: 'V', 11: 'T', 12: 'LV', 13: 'LVT'
}

# WB
_WB_MAP = {
    0: 'Other', 1: 'CR', 2: 'LF', 3: 'Newline', 4: 'Extend', 5: 'ZWJ',
    6: 'Regional_Indicator', 7: 'Format', 8: 'Katakana', 9: 'Hebrew_Letter',
    10: 'ALetter', 11: 'Single_Quote', 12: 'Double_Quote', 13: 'MidNumLet',
    14: 'MidLetter', 15: 'MidNum', 16: 'Numeric', 17: 'ExtendNumLet',
    18: 'WSegSpace'
}

# SB
_SB_MAP = {
    0: 'Other', 1: 'CR', 2: 'LF', 3: 'Sep', 4: 'Extend', 5: 'Format',
    6: 'Sp', 7: 'Lower', 8: 'Upper', 9: 'OLetter', 10: 'Numeric',
    11: 'ATerm', 12: 'STerm', 13: 'Close', 14: 'SContinue'
}

# InCB
_INCB_MAP = {0: 'None', 1: 'Consonant', 2: 'Extend', 3: 'Linker'}


def _gcb(cp):
    return _GCB_MAP.get(_lib.get_gcb(cp), 'Other')


def _wb(cp):
    return _WB_MAP.get(_lib.get_wb(cp), 'Other')


def _sb(cp):
    return _SB_MAP.get(_lib.get_sb(cp), 'Other')


def _is_ext_pict(cp):
    return _lib.is_ext_pict(cp) != 0


def _incb(cp):
    return _INCB_MAP.get(_lib.get_incb(cp), 'None')


# ---------------------------------------------------------------------------
# Grapheme Cluster Boundaries (UAX #29 Section 3.1.1)
# ---------------------------------------------------------------------------

def grapheme_boundaries(codepoints):
    """Return sorted list of all grapheme cluster boundary positions."""
    n = len(codepoints)
    if n == 0:
        return [0]

    types = [_gcb(cp) for cp in codepoints]
    boundaries = {0, n}   # GB1, GB2
    ri_count = 0

    for i in range(1, n):
        prev_t = types[i - 1]
        curr_t = types[i]

        # GB3: CR x LF
        if prev_t == 'CR' and curr_t == 'LF':
            if prev_t == 'Regional_Indicator':
                ri_count += 1
            else:
                ri_count = 0
            continue

        # GB4: (Control | CR | LF) ÷
        if prev_t in ('Control', 'CR', 'LF'):
            boundaries.add(i)
            ri_count = 0
            continue

        # GB5: ÷ (Control | CR | LF)
        if curr_t in ('Control', 'CR', 'LF'):
            boundaries.add(i)
            ri_count = 0
            continue

        # GB6: L x (L | V | LV | LVT)
        if prev_t == 'L' and curr_t in ('L', 'V', 'LV', 'LVT'):
            ri_count = 0
            continue

        # GB7: (LV | V) x (V | T)
        if prev_t in ('LV', 'V') and curr_t in ('V', 'T'):
            ri_count = 0
            continue

        # GB8: (LVT | T) x T
        if prev_t in ('LVT', 'T') and curr_t == 'T':
            ri_count = 0
            continue

        # GB9: x (Extend | ZWJ)
        if curr_t in ('Extend', 'ZWJ'):
            continue

        # GB9a: x SpacingMark
        if curr_t == 'SpacingMark':
            ri_count = 0
            continue

        # GB9b: Prepend x
        if prev_t == 'Prepend':
            ri_count = 0
            continue

        # GB9c: Consonant [Extend|Linker]* Linker [Extend|Linker]* x Consonant
        if _incb(codepoints[i]) == 'Consonant':
            if _check_gb9c(codepoints, i):
                ri_count = 0
                continue

        # GB11: ExtPict Extend* ZWJ x ExtPict
        if _is_ext_pict(codepoints[i]):
            if _check_gb11(codepoints, types, i):
                ri_count = 0
                continue

        # GB12/GB13: RI x RI (pairs)
        if curr_t == 'Regional_Indicator' and prev_t == 'Regional_Indicator':
            ri_count += 1
            if ri_count % 2 == 1:
                continue
            else:
                boundaries.add(i)
                ri_count = 0
                continue

        # Update RI tracking for non-RI current chars
        if prev_t == 'Regional_Indicator':
            ri_count += 1
        else:
            ri_count = 0

        # GB999: Any ÷ Any
        boundaries.add(i)
        ri_count = 0

    return sorted(boundaries)


def _check_gb9c(codepoints, pos):
    """GB9c lookback: Consonant [Extend|Linker]* Linker [Extend|Linker]* x Consonant"""
    found_linker = False
    j = pos - 1
    while j >= 0:
        ic = _incb(codepoints[j])
        if ic == 'Linker':
            found_linker = True
            j -= 1
        elif ic == 'Extend':
            j -= 1
        elif ic == 'Consonant' and found_linker:
            return True
        else:
            break
    return False


def _check_gb11(codepoints, types, pos):
    """GB11: ExtPict Extend* ZWJ x ExtPict"""
    if pos < 2:
        return False
    j = pos - 1
    if types[j] != 'ZWJ':
        return False
    j -= 1
    while j >= 0 and types[j] == 'Extend':
        j -= 1
    return j >= 0 and _is_ext_pict(codepoints[j])


# ---------------------------------------------------------------------------
# Word Boundaries (UAX #29 Section 4.1)
# ---------------------------------------------------------------------------

def _wb_skip_back(types, pos):
    """Find effective type looking backward past Extend/Format/ZWJ."""
    while pos >= 0 and types[pos] in ('Extend', 'Format', 'ZWJ'):
        pos -= 1
    return types[pos] if pos >= 0 else None


def _wb_skip_back_n(types, pos, n):
    """Find the n-th base type looking backward (1-indexed)."""
    count = 0
    while pos >= 0:
        if types[pos] not in ('Extend', 'Format', 'ZWJ'):
            count += 1
            if count == n:
                return types[pos]
        pos -= 1
    return None


def _wb_next_base(types, pos):
    """Find next base type looking forward past Extend/Format/ZWJ."""
    while pos < len(types) and types[pos] in ('Extend', 'Format', 'ZWJ'):
        pos += 1
    return types[pos] if pos < len(types) else None


def _is_ah(t):
    return t in ('ALetter', 'Hebrew_Letter')


def _is_midletterq(t):
    return t in ('MidLetter', 'MidNumLet', 'Single_Quote')


def _is_midnumq(t):
    return t in ('MidNum', 'MidNumLet', 'Single_Quote')


def word_boundaries(codepoints):
    """Return sorted list of all word boundary positions."""
    n = len(codepoints)
    if n == 0:
        return [0]

    types = [_wb(cp) for cp in codepoints]
    boundaries = {0, n}   # WB1, WB2
    ri_count = 0

    for i in range(1, n):
        prev_raw = types[i - 1]
        curr_raw = types[i]

        # WB3: CR x LF
        if prev_raw == 'CR' and curr_raw == 'LF':
            ri_count = 0
            continue

        # WB3a: (Newline | CR | LF) ÷
        if prev_raw in ('Newline', 'CR', 'LF'):
            boundaries.add(i)
            ri_count = 0
            continue

        # WB3b: ÷ (Newline | CR | LF)
        if curr_raw in ('Newline', 'CR', 'LF'):
            boundaries.add(i)
            ri_count = 0
            continue

        # WB3c: ZWJ x \p{Extended_Pictographic}
        if prev_raw == 'ZWJ' and _is_ext_pict(codepoints[i]):
            ri_count = 0
            continue

        # WB3d: WSegSpace x WSegSpace
        if prev_raw == 'WSegSpace' and curr_raw == 'WSegSpace':
            ri_count = 0
            continue

        # WB4: X (Extend | Format | ZWJ)* -> X
        if curr_raw in ('Extend', 'Format', 'ZWJ'):
            continue

        # --- From here, use effective types (skipping Extend/Format/ZWJ) ---
        prev_eff = _wb_skip_back(types, i - 1)
        curr_eff = curr_raw

        # WB5: AHLetter x AHLetter
        if _is_ah(prev_eff) and _is_ah(curr_eff):
            ri_count = 0
            continue

        # WB6: AHLetter x (MidLetter | MidNumLetQ) AHLetter
        if _is_ah(prev_eff) and _is_midletterq(curr_eff):
            nxt = _wb_next_base(types, i + 1)
            if nxt is not None and _is_ah(nxt):
                ri_count = 0
                continue

        # WB7: AHLetter (MidLetter | MidNumLetQ) x AHLetter
        if _is_midletterq(prev_eff) and _is_ah(curr_eff):
            pp = _wb_skip_back_n(types, i - 1, 2)
            if pp is not None and _is_ah(pp):
                ri_count = 0
                continue

        # WB7a: Hebrew_Letter x Single_Quote
        if prev_eff == 'Hebrew_Letter' and curr_eff == 'Single_Quote':
            ri_count = 0
            continue

        # WB7b: Hebrew_Letter x Double_Quote Hebrew_Letter
        if prev_eff == 'Hebrew_Letter' and curr_eff == 'Double_Quote':
            nxt = _wb_next_base(types, i + 1)
            if nxt == 'Hebrew_Letter':
                ri_count = 0
                continue

        # WB7c: Hebrew_Letter Double_Quote x Hebrew_Letter
        if prev_eff == 'Double_Quote' and curr_eff == 'Hebrew_Letter':
            pp = _wb_skip_back_n(types, i - 1, 2)
            if pp == 'Hebrew_Letter':
                ri_count = 0
                continue

        # WB8: Numeric x Numeric
        if prev_eff == 'Numeric' and curr_eff == 'Numeric':
            ri_count = 0
            continue

        # WB9: AHLetter x Numeric
        if _is_ah(prev_eff) and curr_eff == 'Numeric':
            ri_count = 0
            continue

        # WB10: Numeric x AHLetter
        if prev_eff == 'Numeric' and _is_ah(curr_eff):
            ri_count = 0
            continue

        # WB11: Numeric (MidNum | MidNumLetQ) x Numeric
        if _is_midnumq(prev_eff) and curr_eff == 'Numeric':
            pp = _wb_skip_back_n(types, i - 1, 2)
            if pp == 'Numeric':
                ri_count = 0
                continue

        # WB12: Numeric x (MidNum | MidNumLetQ) Numeric
        if prev_eff == 'Numeric' and _is_midnumq(curr_eff):
            nxt = _wb_next_base(types, i + 1)
            if nxt == 'Numeric':
                ri_count = 0
                continue

        # WB13: Katakana x Katakana
        if prev_eff == 'Katakana' and curr_eff == 'Katakana':
            ri_count = 0
            continue

        # WB13a: (AHLetter | Numeric | Katakana | ExtendNumLet) x ExtendNumLet
        if prev_eff in ('ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana',
                         'ExtendNumLet') and curr_eff == 'ExtendNumLet':
            ri_count = 0
            continue

        # WB13b: ExtendNumLet x (AHLetter | Numeric | Katakana)
        if prev_eff == 'ExtendNumLet' and curr_eff in (
                'ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana'):
            ri_count = 0
            continue

        # WB15/WB16: RI x RI (pairs)
        if prev_eff == 'Regional_Indicator' and curr_eff == 'Regional_Indicator':
            ri_count += 1
            if ri_count % 2 == 1:
                continue
            else:
                boundaries.add(i)
                ri_count = 0
                continue

        # Track RI
        if prev_eff == 'Regional_Indicator':
            ri_count += 1
        else:
            ri_count = 0

        # WB999: Any ÷ Any
        boundaries.add(i)
        ri_count = 0

    return sorted(boundaries)


# ---------------------------------------------------------------------------
# Sentence Boundaries (UAX #29 Section 5.1)
# ---------------------------------------------------------------------------

def _sb_skip_back(types, pos, lo=0):
    """Effective type looking backward past Extend/Format (SB5)."""
    while pos >= lo and types[pos] in ('Extend', 'Format'):
        pos -= 1
    return types[pos] if pos >= lo else None


def _sb_skip_back_n(types, pos, n, lo=0):
    """n-th base type looking backward (1-indexed), skipping Extend/Format."""
    count = 0
    while pos >= lo:
        if types[pos] not in ('Extend', 'Format'):
            count += 1
            if count == n:
                return types[pos]
        pos -= 1
    return None


def _sb_check_aterm_context(types, pos, allow_sp, lo=0):
    """Check if (ATerm|STerm) Close* [Sp*] precedes position pos."""
    j = pos - 1
    while j >= lo and types[j] in ('Extend', 'Format'):
        j -= 1
    if j < lo:
        return None

    if types[j] in ('ATerm', 'STerm'):
        return types[j]

    if allow_sp:
        while j >= lo:
            if types[j] in ('Extend', 'Format'):
                j -= 1
                continue
            if types[j] == 'Sp':
                j -= 1
                continue
            break

    while j >= lo:
        if types[j] in ('Extend', 'Format'):
            j -= 1
            continue
        if types[j] == 'Close':
            j -= 1
            continue
        break

    while j >= lo and types[j] in ('Extend', 'Format'):
        j -= 1

    if j >= lo and types[j] in ('ATerm', 'STerm'):
        return types[j]
    return None


def _sb_check_sb11(types, pos, lo=0):
    """Check SB11: (STerm|ATerm) Close* Sp* (Sep|CR|LF)? ÷"""
    j = pos - 1
    while j >= lo and types[j] in ('Extend', 'Format'):
        j -= 1
    if j < lo:
        return False

    if types[j] in ('Sep', 'CR', 'LF'):
        j -= 1
        while j >= lo and types[j] in ('Extend', 'Format'):
            j -= 1
        if j < lo:
            return False

    while j >= lo:
        if types[j] in ('Extend', 'Format'):
            j -= 1
            continue
        if types[j] == 'Sp':
            j -= 1
            continue
        break

    while j >= lo:
        if types[j] in ('Extend', 'Format'):
            j -= 1
            continue
        if types[j] == 'Close':
            j -= 1
            continue
        break

    while j >= lo and types[j] in ('Extend', 'Format'):
        j -= 1

    return j >= lo and types[j] in ('ATerm', 'STerm')


def _sb8_forward_check(types, pos, n):
    """SB8 forward: find Lower before any blocking type."""
    blocking = {'OLetter', 'Upper', 'Lower', 'Sep', 'CR', 'LF', 'STerm', 'ATerm'}
    for j in range(pos, n):
        t = types[j]
        if t in ('Extend', 'Format'):
            continue
        if t in blocking:
            return t == 'Lower'
    return False


def sentence_boundaries(codepoints):
    """Return sorted list of all sentence boundary positions."""
    n = len(codepoints)
    if n == 0:
        return [0]

    types = [_sb(cp) for cp in codepoints]
    boundaries = {0, n}   # SB1, SB2
    seg_start = 0

    for i in range(1, n):
        prev_raw = types[i - 1]
        curr_raw = types[i]

        # SB3: CR x LF
        if prev_raw == 'CR' and curr_raw == 'LF':
            continue

        # SB4: (Sep | CR | LF) ÷
        if prev_raw in ('Sep', 'CR', 'LF'):
            boundaries.add(i)
            seg_start = i
            continue

        # SB5: X (Extend | Format)* -> X
        if curr_raw in ('Extend', 'Format'):
            continue

        prev_eff = _sb_skip_back(types, i - 1, seg_start)
        curr_eff = curr_raw

        # SB6: ATerm x Numeric
        if prev_eff == 'ATerm' and curr_eff == 'Numeric':
            continue

        # SB7: (Upper | Lower) ATerm x Upper
        if prev_eff == 'ATerm' and curr_eff == 'Upper':
            pp = _sb_skip_back_n(types, i - 1, 2, seg_start)
            if pp in ('Upper', 'Lower'):
                continue

        # SB8: ATerm Close* Sp* x ([^...])* Lower
        ctx8 = _sb_check_aterm_context(types, i, allow_sp=True, lo=seg_start)
        if ctx8 == 'ATerm' and _sb8_forward_check(types, i, n):
            continue

        # SB8a: (STerm | ATerm) Close* Sp* x (SContinue | STerm | ATerm)
        if curr_eff in ('SContinue', 'STerm', 'ATerm'):
            ctx = _sb_check_aterm_context(types, i, allow_sp=True, lo=seg_start)
            if ctx is not None:
                continue

        # SB9: (STerm | ATerm) Close* x (Close | Sp | Sep | CR | LF)
        if curr_eff in ('Close', 'Sp', 'Sep', 'CR', 'LF'):
            ctx = _sb_check_aterm_context(types, i, allow_sp=False, lo=seg_start)
            if ctx is not None:
                continue

        # SB10: (STerm | ATerm) Close* Sp* x (Sp | Sep | CR | LF)
        if curr_eff in ('Sp', 'Sep', 'CR', 'LF'):
            ctx = _sb_check_aterm_context(types, i, allow_sp=True, lo=seg_start)
            if ctx is not None:
                continue

        # SB11: (STerm | ATerm) Close* Sp* (Sep | CR | LF)? ÷
        if _sb_check_sb11(types, i, seg_start):
            boundaries.add(i)
            seg_start = i
            continue

        # SB998: Any x Any (default: don't break)

    return sorted(boundaries)
