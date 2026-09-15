"""
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


def segment_sentences(text):
    """
    Segment text into sentence segments per UAX#29 sentence boundary rules.

    Returns a list of strings whose concatenation equals the input text.

    Implement rules SB1 through SB998 as defined in:
    https://www.unicode.org/reports/tr29/#Sentence_Boundaries

    Key rules to implement:
    - SB3: CR x LF (no break within CRLF)
    - SB4: ParaSep ÷ (break after paragraph separators)
    - SB5: Extend/Format transparency (these chars inherit preceding category)
    - SB6: ATerm x Numeric (don't break abbreviations before numbers)
    - SB7: (Upper|Lower) ATerm x Upper (abbreviation detection)
    - SB8: ATerm Close* Sp* x (non-break-set)* Lower (forward scan)
    - SB8a: SATerm Close* Sp* x (SContinue|SATerm) (continuation)
    - SB9: SATerm Close* x (Close|Sp|ParaSep)
    - SB10: SATerm Close* Sp* x (Sp|ParaSep)
    - SB11: SATerm Close* Sp* ParaSep? ÷ (sentence break)
    - SB998: Any x Any (default: no break)
    """
    raise NotImplementedError("Sentence boundary segmentation not yet implemented")
