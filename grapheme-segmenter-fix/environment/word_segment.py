"""
UAX#29 Word Boundary segmentation using C shared library for property lookups.

Loads libwordbreak.so via ctypes for fast Unicode property lookups and
implements the UAX#29 default word boundary algorithm.

"""

import ctypes
import os

# Load the compiled shared library
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libwordbreak.so')
_lib = ctypes.CDLL(_LIB_PATH)

# Declare C function signatures
_lib.word_break_property.argtypes = [ctypes.c_uint32]
_lib.word_break_property.restype = ctypes.c_int
_lib.is_extended_pictographic.argtypes = [ctypes.c_uint32]
_lib.is_extended_pictographic.restype = ctypes.c_int

# Category ID -> name mapping (must match gen_word_tables.py CATEGORIES)
_CAT_NAMES = {
    0: 'Other',
    1: 'CR',
    2: 'LF',
    3: 'Newline',
    4: 'Extend',
    5: 'ZWJ',
    6: 'Regional_Indicator',
    7: 'Format',
    8: 'Katakana',
    9: 'Hebrew_Letter',
    10: 'ALetter',
    11: 'Single_Quote',
    12: 'Double_Quote',
    13: 'MidNumLet',
    14: 'MidLetter',
    15: 'MidNum',
    16: 'Numeric',
    17: 'ExtendNumLet',
    18: 'WSegSpace',
}


def word_break_property(ch):
    """Return the Word_Break property value for a character."""
    cat_id = _lib.word_break_property(ord(ch))
    return _CAT_NAMES.get(cat_id, 'Other')


def is_extended_pictographic(ch):
    """Check if character has Extended_Pictographic property."""
    return bool(_lib.is_extended_pictographic(ord(ch)))


def _is_ah_letter(wb):
    """AHLetter = ALetter | Hebrew_Letter"""
    return wb in ('ALetter', 'Hebrew_Letter')


def _is_mid_num_let_q(wb):
    """MidNumLetQ = MidNumLet | Single_Quote"""
    return wb in ('MidNumLet', 'Single_Quote')


def segment_words(text):
    """
    Segment text into word segments per UAX#29 word boundary rules.

    Returns a list of strings whose concatenation equals the input text.
    """
    if not text:
        return []

    n = len(text)
    wb = [word_break_property(ch) for ch in text]

    # Skip forward past Extend/Format/ZWJ characters from position pos.
    def skip_efz_forward(pos):
        j = pos
        while j < n and wb[j] in ('Extend', 'Format', 'ZWJ'):
            j += 1
        return j

    # Find the effective base character index by scanning backward
    # past Extend/Format/ZWJ (implements WB4 lookback).
    def eff_base_idx(pos):
        j = pos
        while j > 0 and wb[j] in ('Extend', 'Format', 'ZWJ'):
            j -= 1
        return j

    breaks = []

    for i in range(1, n):
        prev_wb = wb[i - 1]
        curr_wb = wb[i]

        # WB3: CR × LF
        if prev_wb == 'CR' and curr_wb == 'LF':
            continue

        # WB3a: (Newline | CR | LF) ÷
        if prev_wb in ('Newline', 'CR', 'LF'):
            breaks.append(i)
            continue

        # WB3b: ÷ (Newline | CR | LF)
        if curr_wb in ('Newline', 'CR', 'LF'):
            breaks.append(i)
            continue

        # WB3c: ZWJ × Extended_Pictographic
        # Priority over WB4 — use raw prev_wb, not effective base
        if prev_wb == 'ZWJ' and is_extended_pictographic(text[i]):
            continue

        # WB4: X (Extend | Format | ZWJ)* → X
        # Never break before Extend, Format, or ZWJ
        if curr_wb in ('Extend', 'Format', 'ZWJ'):
            continue

        # --- From here, apply WB4 by using effective base ---
        base_i = eff_base_idx(i - 1)
        base_wb = wb[base_i]
        skipped_efz = (base_i != i - 1)

        # WB3d: WSegSpace × WSegSpace
        if base_wb == 'WSegSpace' and curr_wb == 'WSegSpace' and not skipped_efz:
            continue

        # WB5: AHLetter × AHLetter
        if _is_ah_letter(base_wb) and _is_ah_letter(curr_wb):
            continue

        # WB6: AHLetter × (MidLetter | MidNumLetQ) AHLetter
        if _is_ah_letter(base_wb) and (
            curr_wb == 'MidLetter' or _is_mid_num_let_q(curr_wb)
        ):
            k = skip_efz_forward(i + 1)
            if k < n and _is_ah_letter(wb[k]):
                continue

        # WB7: AHLetter (MidLetter | MidNumLetQ) × AHLetter
        if _is_ah_letter(curr_wb) and (
            base_wb == 'MidLetter' or _is_mid_num_let_q(base_wb)
        ):
            if base_i > 0:
                bb_i = eff_base_idx(base_i - 1)
                if _is_ah_letter(wb[bb_i]):
                    continue

        # WB7a: Hebrew_Letter × Single_Quote
        if base_wb == 'Hebrew_Letter' and curr_wb == 'Single_Quote':
            continue

        # WB7b: Hebrew_Letter × Double_Quote Hebrew_Letter
        if base_wb == 'Hebrew_Letter' and curr_wb == 'Double_Quote':
            k = skip_efz_forward(i + 1)
            if k < n and wb[k] == 'Hebrew_Letter':
                continue

        # WB7c: Hebrew_Letter Double_Quote × Hebrew_Letter
        if curr_wb == 'Hebrew_Letter' and base_wb == 'Double_Quote':
            if base_i > 0:
                bb_i = eff_base_idx(base_i - 1)
                if wb[bb_i] == 'Hebrew_Letter':
                    continue

        # WB8: Numeric × Numeric
        if base_wb == 'Numeric' and curr_wb == 'Numeric':
            continue

        # WB9: AHLetter × Numeric
        if _is_ah_letter(base_wb) and curr_wb == 'Numeric':
            continue

        # WB10: Numeric × AHLetter
        if base_wb == 'Numeric' and _is_ah_letter(curr_wb):
            continue

        # WB11: Numeric (MidNum | MidNumLetQ) × Numeric
        if curr_wb == 'Numeric' and (
            base_wb == 'MidNum' or _is_mid_num_let_q(base_wb)
        ):
            if base_i > 0:
                bb_i = eff_base_idx(base_i - 1)
                if wb[bb_i] == 'Numeric':
                    continue

        # WB12: Numeric × (MidNum | MidNumLetQ) Numeric
        if base_wb == 'Numeric' and (
            curr_wb == 'MidNum' or _is_mid_num_let_q(curr_wb)
        ):
            k = skip_efz_forward(i + 1)
            if k < n and wb[k] == 'Numeric':
                continue

        # WB13: Katakana × Katakana
        if base_wb == 'Katakana' and curr_wb == 'Katakana':
            continue

        # WB13a: (AHLetter | Numeric | Katakana | ExtendNumLet) × ExtendNumLet
        if curr_wb == 'ExtendNumLet' and base_wb in (
            'ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana', 'ExtendNumLet'
        ):
            continue

        # WB13b: ExtendNumLet × (AHLetter | Numeric | Katakana)
        if base_wb == 'ExtendNumLet' and curr_wb in (
            'ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana'
        ):
            continue

        # WB15/WB16: Regional Indicator even/odd pairing
        if base_wb == 'Regional_Indicator' and curr_wb == 'Regional_Indicator':
            count = 0
            k = i - 1
            while k >= 0:
                if wb[k] in ('Extend', 'Format', 'ZWJ'):
                    k -= 1
                    continue
                if wb[k] == 'Regional_Indicator':
                    count += 1
                    k -= 1
                else:
                    break
            # Odd count: last RI needs a partner → no break
            # Even count: all paired → break (new pair)
            if count % 2 == 1:
                continue

        # WB999: Any ÷ Any
        breaks.append(i)

    # Build segments from break positions
    segments = []
    prev = 0
    for b in breaks:
        segments.append(text[prev:b])
        prev = b
    if prev < n:
        segments.append(text[prev:])

    return segments
