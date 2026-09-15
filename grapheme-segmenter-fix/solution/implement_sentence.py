#!/usr/bin/env python3
"""
Implement the complete UAX#29 sentence boundary segmentation algorithm.

Writes the full implementation to /app/sentence_segment.py, replacing
the skeleton with a working segmenter that passes all official Unicode
16.0 SentenceBreakTest.txt conformance vectors.

Uses a 4-element sliding window state machine approach inspired by
the unicode-segmentation Rust crate.

"""

IMPL = r'''"""
UAX#29 Sentence Boundary segmentation using C shared library for property lookups.

Loads libsentbreak.so via ctypes for fast Unicode property lookups and
implements the UAX#29 default sentence boundary algorithm.

Specification: https://www.unicode.org/reports/tr29/#Sentence_Boundaries

"""

import ctypes
import os

# Load the compiled shared library
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libsentbreak.so')
_lib = ctypes.CDLL(_LIB_PATH)

# Declare C function signatures
_lib.sentence_break_property.argtypes = [ctypes.c_uint32]
_lib.sentence_break_property.restype = ctypes.c_int

# Category ID -> name mapping (must match gen_sentence_tables.py CATEGORIES)
_CAT_NAMES = {
    0: 'Other',
    1: 'CR',
    2: 'LF',
    3: 'Extend',
    4: 'Sep',
    5: 'Format',
    6: 'Sp',
    7: 'Lower',
    8: 'Upper',
    9: 'OLetter',
    10: 'Numeric',
    11: 'ATerm',
    12: 'SContinue',
    13: 'STerm',
    14: 'Close',
}


def sentence_break_property(ch):
    """Return the Sentence_Break property value for a character."""
    cat_id = _lib.sentence_break_property(ord(ch))
    return _CAT_NAMES.get(cat_id, 'Other')


def _cat_to_part(cat):
    """Map a Sentence_Break category to a state machine part.

    The state machine tracks a simplified view of recent character history:
    - Upper and Lower both map to 'upper_lower' since the rules that
      distinguish them (SB7) only need to know "was it Upper OR Lower"
    - Consecutive Close characters collapse into 'close+'
    - Consecutive Sp characters collapse into 'sp+'
    """
    if cat == 'CR': return 'cr'
    if cat == 'LF': return 'lf'
    if cat == 'Sep': return 'sep'
    if cat == 'ATerm': return 'aterm'
    if cat in ('Upper', 'Lower'): return 'upper_lower'
    if cat == 'Close': return 'close+'
    if cat == 'Sp': return 'sp+'
    if cat == 'STerm': return 'sterm'
    return 'other'


# Characters that terminate the SB8 forward scan without triggering the rule
_SB8_BREAK_SET = frozenset([
    'OLetter', 'Upper', 'Sep', 'CR', 'LF', 'STerm', 'ATerm',
])


def _match_sb8_back(state):
    """Check backward context for SB8: ATerm Close* Sp*.

    Returns True if the state window ends with ATerm optionally followed
    by Close+ and/or Sp+ (only ATerm, not STerm).
    """
    idx = 3
    if state[idx] == 'sp+':
        idx -= 1
    if idx >= 0 and state[idx] == 'close+':
        idx -= 1
    return idx >= 0 and state[idx] == 'aterm'


def _match_saterm_close_sp(state):
    """Check backward context for SB8a and SB10: SATerm Close* Sp*.

    Returns True if the state window ends with (ATerm|STerm) optionally
    followed by Close+ and/or Sp+.
    """
    idx = 3
    if state[idx] == 'sp+':
        idx -= 1
    if idx >= 0 and state[idx] == 'close+':
        idx -= 1
    return idx >= 0 and state[idx] in ('sterm', 'aterm')


def _match_saterm_close(state):
    """Check backward context for SB9: SATerm Close*.

    Returns True if the state window ends with (ATerm|STerm) optionally
    followed by Close+.
    """
    idx = 3
    if state[idx] == 'close+':
        idx -= 1
    return idx >= 0 and state[idx] in ('sterm', 'aterm')


def _match_sb11(state):
    """Check backward context for SB11: SATerm Close* Sp* ParaSep?.

    Returns True if the state window matches the SB11 pattern, indicating
    a sentence break should occur.
    """
    idx = 3
    if state[idx] in ('sep', 'cr', 'lf'):
        idx -= 1
    if idx >= 0 and state[idx] == 'sp+':
        idx -= 1
    if idx >= 0 and state[idx] == 'close+':
        idx -= 1
    return idx >= 0 and state[idx] in ('sterm', 'aterm')


def segment_sentences(text):
    """
    Segment text into sentence segments per UAX#29 sentence boundary rules.

    Returns a list of strings whose concatenation equals the input text.

    Uses a 4-element sliding window state machine. Each character's
    Sentence_Break category is mapped to a simplified state part.
    Consecutive Close and Sp characters are collapsed into single entries,
    ensuring the window can represent patterns up to:
        SATerm Close* Sp* ParaSep?
    which is the deepest pattern needed (SB11).

    SB5 (Extend/Format transparency) is handled by restoring the state
    window when encountering Extend or Format characters, effectively
    making them invisible to all subsequent rules.
    """
    if not text:
        return []

    n = len(text)
    sb = [sentence_break_property(ch) for ch in text]

    # 4-element sliding window of state parts
    state = ['sot', 'sot', 'sot', 'sot']
    breaks = []

    for i in range(n):
        cat = sb[i]
        state_before = [state[0], state[1], state[2], state[3]]

        # Advance state: collapse consecutive Close/Sp into single entries
        if cat == 'Close' and state[3] == 'close+':
            pass  # collapse consecutive Close
        elif cat == 'Sp' and state[3] == 'sp+':
            pass  # collapse consecutive Sp
        else:
            part = _cat_to_part(cat)
            state[0] = state[1]
            state[1] = state[2]
            state[2] = state[3]
            state[3] = part

        # --- Check rules in priority order (SB1 through SB998) ---

        # SB1: sot ÷ Any
        # Start of text is always a sentence boundary. Since we build
        # segments starting from position 0, no explicit break needed.
        if state_before[3] == 'sot':
            continue

        # SB3: CR × LF (do not break within CRLF)
        if cat == 'LF' and state_before[3] == 'cr':
            continue

        # SB4: (Sep | CR | LF) ÷ (break after paragraph separator)
        if state_before[3] in ('sep', 'cr', 'lf'):
            breaks.append(i)
            continue

        # SB5: X (Extend | Format)* → X
        # Extend and Format characters are transparent; they inherit the
        # properties of the preceding character. Implemented by restoring
        # the state to what it was before the Extend/Format.
        if cat in ('Extend', 'Format'):
            state[0] = state_before[0]
            state[1] = state_before[1]
            state[2] = state_before[2]
            state[3] = state_before[3]
            continue

        # SB6: ATerm × Numeric
        if state_before[3] == 'aterm' and cat == 'Numeric':
            continue

        # SB7: (Upper | Lower) ATerm × Upper
        if (state_before[3] == 'aterm'
                and state_before[2] == 'upper_lower'
                and cat == 'Upper'):
            continue

        # SB8: ATerm Close* Sp* × ( ¬(OLetter|Upper|Lower|ParaSep|SATerm) )* Lower
        # Check backward context (ATerm Close* Sp*), then scan forward
        # from current position for Lower before any break-set character.
        if _match_sb8_back(state_before):
            found_lower = False
            for j in range(i, n):
                fcat = sb[j]
                if fcat == 'Lower':
                    found_lower = True
                    break
                if fcat in _SB8_BREAK_SET:
                    break
                # Extend, Format, Numeric, Close, Sp, SContinue, Other
                # all fall through (they are in ¬BreakSet)
            if found_lower:
                continue

        # SB8a: (STerm | ATerm) Close* Sp* × (SContinue | STerm | ATerm)
        if cat in ('SContinue', 'STerm', 'ATerm') and _match_saterm_close_sp(state_before):
            continue

        # SB9: (STerm | ATerm) Close* × (Close | Sp | Sep | CR | LF)
        if cat in ('Close', 'Sp', 'Sep', 'CR', 'LF') and _match_saterm_close(state_before):
            continue

        # SB10: (STerm | ATerm) Close* Sp* × (Sp | Sep | CR | LF)
        if cat in ('Sp', 'Sep', 'CR', 'LF') and _match_saterm_close_sp(state_before):
            continue

        # SB11: (STerm | ATerm) Close* Sp* ParaSep? ÷
        if _match_sb11(state_before):
            breaks.append(i)
            continue

        # SB998: Any × Any (do not break)

    # Build segments from break positions
    segments = []
    prev = 0
    for b in breaks:
        segments.append(text[prev:b])
        prev = b
    if prev < n:
        segments.append(text[prev:])
    return segments
'''

with open('/app/sentence_segment.py', 'w', encoding='utf-8') as f:
    f.write(IMPL)

print("Sentence boundary segmenter implemented successfully.")
