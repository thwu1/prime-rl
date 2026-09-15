"""
fzf Fuzzy Matching Engine — Partial Python Port

Scoring constants, character classification, and the bonus matrix are
implemented below. Core matching functions are stubs.
"""

import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Result:
    start: int
    end: int
    score: int

# ---------------------------------------------------------------------------
# Scoring constants (from fzf algo.go)
# ---------------------------------------------------------------------------

SCORE_MATCH = 16
SCORE_GAP_START = -3
SCORE_GAP_EXTENSION = -1

BONUS_BOUNDARY = SCORE_MATCH // 2           # 8
BONUS_NON_WORD = SCORE_MATCH // 2           # 8
BONUS_CAMEL_123 = BONUS_BOUNDARY + SCORE_GAP_EXTENSION  # 7
BONUS_CONSECUTIVE = -(SCORE_GAP_START + SCORE_GAP_EXTENSION)  # 4
BONUS_FIRST_CHAR_MULTIPLIER = 2

# Configurable boundary bonuses (scheme-dependent)
bonus_boundary_white = BONUS_BOUNDARY + 2      # 10
bonus_boundary_delimiter = BONUS_BOUNDARY + 1  # 9

DELIMITER_CHARS = "/,:;|"
WHITE_CHARS = " \t\n\v\f\r\x85\xa0"

# ---------------------------------------------------------------------------
# Character classification
# ---------------------------------------------------------------------------

CHAR_WHITE = 0
CHAR_NON_WORD = 1
CHAR_DELIMITER = 2
CHAR_LOWER = 3
CHAR_UPPER = 4
CHAR_LETTER = 5
CHAR_NUMBER = 6

INITIAL_CHAR_CLASS = CHAR_WHITE  # default scheme


def char_class_of(ch: str) -> int:
    """Classify a single character into one of the 7 char classes."""
    if len(ch) != 1:
        raise ValueError("Expected single character")
    o = ord(ch)
    if o <= 127:
        if ch.islower():
            return CHAR_LOWER
        if ch.isupper():
            return CHAR_UPPER
        if ch.isdigit():
            return CHAR_NUMBER
        if ch in WHITE_CHARS:
            return CHAR_WHITE
        if ch in DELIMITER_CHARS:
            return CHAR_DELIMITER
        return CHAR_NON_WORD
    # Unicode
    if ch.islower():
        return CHAR_LOWER
    if ch.isupper():
        return CHAR_UPPER
    if ch.isnumeric():
        return CHAR_NUMBER
    if ch.isalpha():
        return CHAR_LETTER
    if ch.isspace():
        return CHAR_WHITE
    if ch in DELIMITER_CHARS:
        return CHAR_DELIMITER
    return CHAR_NON_WORD


def bonus_for(prev_class: int, cur_class: int) -> int:
    """Compute the bonus for a character given the class of the previous character."""
    if cur_class >= CHAR_NON_WORD:
        if prev_class == CHAR_WHITE:
            return bonus_boundary_white
        if prev_class == CHAR_DELIMITER:
            return bonus_boundary_delimiter
        if prev_class == CHAR_NON_WORD:
            return BONUS_BOUNDARY

    if prev_class == CHAR_LOWER and cur_class == CHAR_UPPER:
        return BONUS_CAMEL_123
    if prev_class != CHAR_NUMBER and cur_class == CHAR_NUMBER:
        return BONUS_CAMEL_123

    if cur_class in (CHAR_NON_WORD, CHAR_DELIMITER):
        return BONUS_NON_WORD
    if cur_class == CHAR_WHITE:
        return bonus_boundary_white
    return 0


# Pre-compute bonus matrix
BONUS_MATRIX = [[0] * (CHAR_NUMBER + 1) for _ in range(CHAR_NUMBER + 1)]
for _i in range(CHAR_NUMBER + 1):
    for _j in range(CHAR_NUMBER + 1):
        BONUS_MATRIX[_i][_j] = bonus_for(_i, _j)


def bonus_at(text: str, idx: int) -> int:
    """Get the bonus for the character at position idx in text."""
    if idx == 0:
        return bonus_boundary_white
    return BONUS_MATRIX[char_class_of(text[idx - 1])][char_class_of(text[idx])]


# ---------------------------------------------------------------------------
# Functions to implement
# ---------------------------------------------------------------------------


def normalize_rune(ch: str) -> str:
    """Normalize a Unicode character for matching (strip diacritics)."""
    raise NotImplementedError("normalize_rune")


def try_skip(text: str, case_sensitive: bool, b: str, from_idx: int) -> int:
    """Find next occurrence of character b in text starting at from_idx.
    Returns index or -1 if not found."""
    raise NotImplementedError("try_skip")


def ascii_fuzzy_index(text: str, pattern: str, case_sensitive: bool) -> Tuple[int, int]:
    """Determine the narrowed search scope for pattern in text.
    Returns (first_idx, scope_end) or (-1, -1) if no match is possible."""
    raise NotImplementedError("ascii_fuzzy_index")


def calculate_score(case_sensitive: bool, normalize: bool, text: str,
                    pattern: str, sidx: int, eidx: int,
                    with_pos: bool) -> Tuple[int, Optional[List[int]]]:
    """Score a known match span [sidx, eidx).
    Returns (score, positions_list_or_None)."""
    raise NotImplementedError("calculate_score")


def fuzzy_match_v1(case_sensitive: bool, normalize: bool, forward: bool,
                   text: str, pattern: str, with_pos: bool) -> Tuple[Result, Optional[List[int]]]:
    """Greedy fuzzy match in O(n). Returns (Result, positions)."""
    raise NotImplementedError("fuzzy_match_v1")


def fuzzy_match_v2(case_sensitive: bool, normalize: bool, forward: bool,
                   text: str, pattern: str,
                   with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    """Optimal fuzzy match. Returns (Result, positions)."""
    raise NotImplementedError("fuzzy_match_v2")


def exact_match_naive(case_sensitive: bool, normalize: bool, forward: bool,
                      text: str, pattern: str,
                      with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    """Exact substring match selecting the position with the best bonus.
    Returns (Result, positions)."""
    raise NotImplementedError("exact_match_naive")


def prefix_match(case_sensitive: bool, normalize: bool, forward: bool,
                 text: str, pattern: str,
                 with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    """Check if text starts with pattern (skipping leading whitespace).
    Returns (Result, positions)."""
    raise NotImplementedError("prefix_match")


def suffix_match(case_sensitive: bool, normalize: bool, forward: bool,
                 text: str, pattern: str,
                 with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    """Check if text ends with pattern (skipping trailing whitespace).
    Returns (Result, positions)."""
    raise NotImplementedError("suffix_match")


def equal_match(case_sensitive: bool, normalize: bool, forward: bool,
                text: str, pattern: str,
                with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    """Check if text (stripped) exactly equals pattern.
    Returns (Result, positions)."""
    raise NotImplementedError("equal_match")
