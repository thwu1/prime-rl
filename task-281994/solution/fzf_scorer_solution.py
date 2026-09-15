"""
fzf FuzzyMatchV2 Scoring Algorithm — Complete Implementation

Faithful Python port of fzf's algo.go (junegunn/fzf).

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


BONUS_MATRIX = [[0] * (CHAR_NUMBER + 1) for _ in range(CHAR_NUMBER + 1)]
for _i in range(CHAR_NUMBER + 1):
    for _j in range(CHAR_NUMBER + 1):
        BONUS_MATRIX[_i][_j] = bonus_for(_i, _j)


def bonus_at(text: str, idx: int) -> int:
    if idx == 0:
        return bonus_boundary_white
    return BONUS_MATRIX[char_class_of(text[idx - 1])][char_class_of(text[idx])]


def normalize_rune(ch: str) -> str:
    if ord(ch) < 0x00C0 or ord(ch) > 0xFF61:
        return ch
    decomposed = unicodedata.normalize('NFD', ch)
    if len(decomposed) > 0:
        base = decomposed[0]
        if ord(base) <= 127 and base.isalpha():
            return base
    return ch


def _lower_char(ch: str) -> str:
    if 'A' <= ch <= 'Z':
        return chr(ord(ch) + 32)
    if ord(ch) > 127:
        return ch.lower()
    return ch


# ---------------------------------------------------------------------------
# Core matching functions
# ---------------------------------------------------------------------------


def try_skip(text: str, case_sensitive: bool, b: str, from_idx: int) -> int:
    if not case_sensitive and b.isalpha() and b.islower():
        upper_b = chr(ord(b) - 32)
        for i in range(from_idx, len(text)):
            if text[i] == b or text[i] == upper_b:
                return i
        return -1
    for i in range(from_idx, len(text)):
        if text[i] == b:
            return i
    return -1


def ascii_fuzzy_index(text: str, pattern: str, case_sensitive: bool) -> Tuple[int, int]:
    if len(pattern) == 0:
        return 0, len(text)

    # If text contains non-ASCII, we can't use the byte-level optimization
    if any(ord(c) > 127 for c in text):
        return 0, len(text)

    # If pattern contains non-ASCII, no match possible in ASCII text
    if any(ord(c) > 127 for c in pattern):
        return -1, -1

    first_idx = 0
    idx = 0
    last_idx = 0
    for pidx, pch in enumerate(pattern):
        b = pch
        idx = try_skip(text, case_sensitive, b, idx)
        if idx < 0:
            return -1, -1
        if pidx == 0 and idx > 0:
            first_idx = idx - 1
        last_idx = idx
        idx += 1

    # Find the last appearance of the last pattern char to widen scope
    b = pattern[-1]
    scope_end = last_idx + 1
    for i in range(len(text) - 1, last_idx, -1):
        ch = text[i]
        if ch == b:
            scope_end = i + 1
            break
        if not case_sensitive and b.isalpha() and b.islower():
            if ch == chr(ord(b) - 32):
                scope_end = i + 1
                break

    return first_idx, scope_end


def calculate_score(case_sensitive: bool, normalize: bool, text: str,
                    pattern: str, sidx: int, eidx: int,
                    with_pos: bool) -> Tuple[int, Optional[List[int]]]:
    pidx = 0
    score = 0
    in_gap = False
    consecutive = 0
    first_bonus = 0
    pos = [] if with_pos else None
    prev_class = INITIAL_CHAR_CLASS
    if sidx > 0:
        prev_class = char_class_of(text[sidx - 1])

    for idx in range(sidx, eidx):
        char = text[idx]
        cls = char_class_of(char)
        if not case_sensitive:
            char = _lower_char(char)
        if normalize:
            char = normalize_rune(char)
        if char == pattern[pidx]:
            if with_pos:
                pos.append(idx)
            score += SCORE_MATCH
            bonus = BONUS_MATRIX[prev_class][cls]
            if consecutive == 0:
                first_bonus = bonus
            else:
                if bonus >= BONUS_BOUNDARY and bonus > first_bonus:
                    first_bonus = bonus
                bonus = max(bonus, first_bonus, BONUS_CONSECUTIVE)
            if pidx == 0:
                score += bonus * BONUS_FIRST_CHAR_MULTIPLIER
            else:
                score += bonus
            in_gap = False
            consecutive += 1
            pidx += 1
        else:
            if in_gap:
                score += SCORE_GAP_EXTENSION
            else:
                score += SCORE_GAP_START
            in_gap = True
            consecutive = 0
            first_bonus = 0
        prev_class = cls
    return score, pos


def _index_at(index: int, max_val: int, forward: bool) -> int:
    if forward:
        return index
    return max_val - index - 1


def fuzzy_match_v1(case_sensitive: bool, normalize: bool, forward: bool,
                   text: str, pattern: str, with_pos: bool) -> Tuple[Result, Optional[List[int]]]:
    if len(pattern) == 0:
        return Result(0, 0, 0), None

    idx, _ = ascii_fuzzy_index(text, pattern, case_sensitive)
    if idx < 0:
        return Result(-1, -1, 0), None

    pidx = 0
    sidx = -1
    eidx = -1
    len_runes = len(text)
    len_pattern = len(pattern)

    for index in range(len_runes):
        tidx = _index_at(index, len_runes, forward)
        char = text[tidx]
        if not case_sensitive:
            char = _lower_char(char)
        if normalize:
            char = normalize_rune(char)
        pchar = pattern[_index_at(pidx, len_pattern, forward)]
        if char == pchar:
            if sidx < 0:
                sidx = index
            pidx += 1
            if pidx == len_pattern:
                eidx = index + 1
                break

    if sidx >= 0 and eidx >= 0:
        pidx -= 1
        for index in range(eidx - 1, sidx - 1, -1):
            tidx = _index_at(index, len_runes, forward)
            char = text[tidx]
            if not case_sensitive:
                char = _lower_char(char)
            if normalize:
                char = normalize_rune(char)
            pidx_ = _index_at(pidx, len_pattern, forward)
            pchar = pattern[pidx_]
            if char == pchar:
                pidx -= 1
                if pidx < 0:
                    sidx = index
                    break

        if not forward:
            sidx, eidx = len_runes - eidx, len_runes - sidx

        score, pos = calculate_score(case_sensitive, normalize, text, pattern, sidx, eidx, with_pos)
        return Result(sidx, eidx, score), pos

    return Result(-1, -1, 0), None


def fuzzy_match_v2(case_sensitive: bool, normalize: bool, forward: bool,
                   text: str, pattern: str,
                   with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    M = len(pattern)
    if M == 0:
        return Result(0, 0, 0), ([] if with_pos else None)

    N = len(text)
    if M > N:
        return Result(-1, -1, 0), None

    # Fallback for very large inputs
    if N * M > (1 << 20) or M > 1000:
        return fuzzy_match_v1(case_sensitive, normalize, forward, text, pattern, with_pos)

    # Phase 1: narrow scope
    min_idx, max_idx = ascii_fuzzy_index(text, pattern, case_sensitive)
    if min_idx < 0:
        return Result(-1, -1, 0), None

    N = max_idx - min_idx

    # Phase 2: compute bonuses and fill first row
    H0 = [0] * N
    C0 = [0] * N
    B = [0] * N
    F = [0] * M  # first occurrence of each pattern char
    T = list(text[min_idx:max_idx])  # working copy

    max_score = 0
    max_score_pos = 0
    pidx = 0
    last_idx = 0
    pchar0 = pattern[0]
    pchar = pattern[0]
    prev_h0 = 0
    prev_class = INITIAL_CHAR_CLASS
    in_gap = False

    for off in range(N):
        char = T[off]
        o = ord(char)
        if o <= 127:
            cls = char_class_of(char)
            if not case_sensitive and cls == CHAR_UPPER:
                char = chr(o + 32)
                T[off] = char
        else:
            cls = char_class_of(char)
            if not case_sensitive and cls == CHAR_UPPER:
                char = char.lower()
            if normalize:
                char = normalize_rune(char)
            T[off] = char

        bonus = BONUS_MATRIX[prev_class][cls]
        B[off] = bonus
        prev_class = cls

        if char == pchar:
            if pidx < M:
                F[pidx] = off
                pidx += 1
                pchar = pattern[min(pidx, M - 1)]
            last_idx = off

        if char == pchar0:
            score = SCORE_MATCH + bonus * BONUS_FIRST_CHAR_MULTIPLIER
            H0[off] = score
            C0[off] = 1
            if M == 1 and ((forward and score > max_score) or (not forward and score >= max_score)):
                max_score = score
                max_score_pos = off
                if forward and bonus >= BONUS_BOUNDARY:
                    in_gap = False
                    prev_h0 = H0[off]
                    continue
            in_gap = False
        else:
            if in_gap:
                H0[off] = max(prev_h0 + SCORE_GAP_EXTENSION, 0)
            else:
                H0[off] = max(prev_h0 + SCORE_GAP_START, 0)
            C0[off] = 0
            in_gap = True
        prev_h0 = H0[off]

    if pidx != M:
        return Result(-1, -1, 0), None

    if M == 1:
        result = Result(min_idx + max_score_pos, min_idx + max_score_pos + 1, max_score)
        if not with_pos:
            return result, None
        return result, [min_idx + max_score_pos]

    # Phase 3: fill score matrix
    f0 = F[0]
    width = last_idx - f0 + 1
    H = [0] * (width * M)
    C = [0] * (width * M)

    # Copy first row
    for i in range(width):
        H[i] = H0[f0 + i]
        C[i] = C0[f0 + i]

    for pidx_off in range(len(F) - 1):
        f = F[pidx_off + 1]
        pc = pattern[pidx_off + 1]
        row = (pidx_off + 1) * width
        in_gap = False

        for off in range(f, last_idx + 1):
            col = off
            j = off - f0  # index into row
            s1 = 0
            s2 = 0
            consecutive = 0

            if in_gap:
                s2 = H[row + j - 1] + SCORE_GAP_EXTENSION
            else:
                s2 = H[row + j - 1] + SCORE_GAP_START if j > 0 else 0
                if j == 0:
                    # First column in this row — left score is 0
                    s2 = 0

            if pc == T[off]:
                s1 = H[row - width + j - 1] + SCORE_MATCH if (j > 0) else 0
                b = B[off]
                consecutive = (C[row - width + j - 1] + 1) if (j > 0) else 1
                if consecutive > 1:
                    fb = B[col - consecutive + 1]
                    if b >= BONUS_BOUNDARY and b > fb:
                        consecutive = 1
                    else:
                        b = max(b, BONUS_CONSECUTIVE, fb)
                if s1 + b < s2:
                    s1 += B[off]
                    consecutive = 0
                else:
                    s1 += b

            C[row + j] = consecutive

            in_gap = s1 < s2
            score = max(s1, s2, 0)
            if pidx_off + 1 == M - 1 and ((forward and score > max_score) or (not forward and score >= max_score)):
                max_score = score
                max_score_pos = col
            H[row + j] = score

    # Phase 4: backtrace
    pos = None
    j = f0
    if with_pos:
        pos = []
        i = M - 1
        j_val = max_score_pos
        prefer_match = True
        while True:
            I = i * width
            j0 = j_val - f0
            s = H[I + j0]
            s1 = 0
            s2 = 0
            if i > 0 and j_val >= F[i]:
                s1 = H[I - width + j0 - 1]
            if j_val > F[i]:
                s2 = H[I + j0 - 1]

            if s > s1 and (s > s2 or (s == s2 and prefer_match)):
                pos.append(j_val + min_idx)
                if i == 0:
                    break
                i -= 1
            prefer_match = (C[I + j0] > 1 or
                           (I + width + j0 + 1 < len(C) and C[I + width + j0 + 1] > 0))
            j_val -= 1
        j = j_val

    return Result(min_idx + j, min_idx + max_score_pos + 1, max_score), pos


def exact_match_naive(case_sensitive: bool, normalize: bool, forward: bool,
                      text: str, pattern: str,
                      with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    if len(pattern) == 0:
        return Result(0, 0, 0), None

    len_runes = len(text)
    len_pattern = len(pattern)

    if len_runes < len_pattern:
        return Result(-1, -1, 0), None

    # Quick check
    idx, _ = ascii_fuzzy_index(text, pattern, case_sensitive)
    if idx < 0:
        return Result(-1, -1, 0), None

    pidx = 0
    best_pos = -1
    bonus = 0
    best_bonus = -1

    for index in range(len_runes):
        index_ = _index_at(index, len_runes, forward)
        char = text[index_]
        if not case_sensitive:
            char = _lower_char(char)
        if normalize:
            char = normalize_rune(char)
        pidx_ = _index_at(pidx, len_pattern, forward)
        pchar = pattern[pidx_]
        if pchar == char:
            if pidx_ == 0:
                bonus = bonus_at(text, index_)
            pidx += 1
            if pidx == len_pattern:
                if bonus > best_bonus:
                    best_pos = index
                    best_bonus = bonus
                if bonus >= BONUS_BOUNDARY:
                    break
                index_back = index - pidx + 1
                pidx = 0
                bonus = 0
                # Continue searching — but we need to handle the index correctly
                # The Go code does `index -= pidx - 1` but since pidx was just set to lenPattern,
                # and we already reset pidx=0, we need to go back
                # Actually the Go code decrements index by (pidx-1) BEFORE resetting pidx
                # Let me re-examine: pidx == lenPattern at this point
                # index -= pidx - 1 means index -= lenPattern - 1
                # But we already set pidx = 0
                # We handled this by setting index_back above but in a for loop we can't
                # reassign index. Let's restructure.
                pass
        else:
            index -= pidx
            pidx = 0
            bonus = 0

    # Need to redo this with a while loop for proper index manipulation
    pidx = 0
    best_pos = -1
    bonus = 0
    best_bonus = -1
    index = 0

    while index < len_runes:
        index_ = _index_at(index, len_runes, forward)
        char = text[index_]
        if not case_sensitive:
            char = _lower_char(char)
        if normalize:
            char = normalize_rune(char)
        pidx_ = _index_at(pidx, len_pattern, forward)
        pchar = pattern[pidx_]
        if pchar == char:
            if pidx_ == 0:
                bonus = bonus_at(text, index_)
            pidx += 1
            if pidx == len_pattern:
                if bonus > best_bonus:
                    best_pos = index
                    best_bonus = bonus
                if bonus >= BONUS_BOUNDARY:
                    break
                index -= pidx - 1
                pidx = 0
                bonus = 0
        else:
            index -= pidx
            pidx = 0
            bonus = 0
        index += 1

    if best_pos >= 0:
        if forward:
            sidx = best_pos - len_pattern + 1
            eidx = best_pos + 1
        else:
            sidx = len_runes - (best_pos + 1)
            eidx = len_runes - (best_pos - len_pattern + 1)
        score, _ = calculate_score(case_sensitive, normalize, text, pattern, sidx, eidx, False)
        return Result(sidx, eidx, score), None

    return Result(-1, -1, 0), None


def prefix_match(case_sensitive: bool, normalize: bool, forward: bool,
                 text: str, pattern: str,
                 with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    if len(pattern) == 0:
        return Result(0, 0, 0), None

    trimmed_len = 0
    if len(pattern) > 0 and not pattern[0].isspace():
        # Count leading whitespace
        for ch in text:
            if ch in WHITE_CHARS or ch.isspace():
                trimmed_len += 1
            else:
                break

    if len(text) - trimmed_len < len(pattern):
        return Result(-1, -1, 0), None

    for i, r in enumerate(pattern):
        char = text[trimmed_len + i]
        if not case_sensitive:
            char = char.lower()
        if normalize:
            char = normalize_rune(char)
        if char != r:
            return Result(-1, -1, 0), None

    lp = len(pattern)
    score, _ = calculate_score(case_sensitive, normalize, text, pattern, trimmed_len, trimmed_len + lp, False)
    return Result(trimmed_len, trimmed_len + lp, score), None


def suffix_match(case_sensitive: bool, normalize: bool, forward: bool,
                 text: str, pattern: str,
                 with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    len_runes = len(text)
    trimmed_len = len_runes
    if len(pattern) == 0 or not pattern[-1].isspace():
        # Strip trailing whitespace
        while trimmed_len > 0 and (text[trimmed_len - 1] in WHITE_CHARS or text[trimmed_len - 1].isspace()):
            trimmed_len -= 1

    if len(pattern) == 0:
        return Result(trimmed_len, trimmed_len, 0), None

    diff = trimmed_len - len(pattern)
    if diff < 0:
        return Result(-1, -1, 0), None

    for i, r in enumerate(pattern):
        char = text[i + diff]
        if not case_sensitive:
            char = char.lower()
        if normalize:
            char = normalize_rune(char)
        if char != r:
            return Result(-1, -1, 0), None

    lp = len(pattern)
    sidx = trimmed_len - lp
    eidx = trimmed_len
    score, _ = calculate_score(case_sensitive, normalize, text, pattern, sidx, eidx, False)
    return Result(sidx, eidx, score), None


def equal_match(case_sensitive: bool, normalize: bool, forward: bool,
                text: str, pattern: str,
                with_pos: bool = False) -> Tuple[Result, Optional[List[int]]]:
    lp = len(pattern)
    if lp == 0:
        return Result(-1, -1, 0), None

    trimmed_len = 0
    if not pattern[0].isspace():
        for ch in text:
            if ch in WHITE_CHARS or ch.isspace():
                trimmed_len += 1
            else:
                break

    trimmed_end_len = 0
    if not pattern[-1].isspace():
        for ch in reversed(text):
            if ch in WHITE_CHARS or ch.isspace():
                trimmed_end_len += 1
            else:
                break

    if len(text) - trimmed_len - trimmed_end_len != lp:
        return Result(-1, -1, 0), None

    match = True
    if normalize:
        for idx, pchar in enumerate(pattern):
            char = text[trimmed_len + idx]
            if not case_sensitive:
                char = char.lower()
            if normalize_rune(pchar) != normalize_rune(char):
                match = False
                break
    else:
        segment = text[trimmed_len:len(text) - trimmed_end_len] if trimmed_end_len > 0 else text[trimmed_len:]
        if not case_sensitive:
            segment = segment.lower()
        match = segment == pattern

    if match:
        score = (SCORE_MATCH + bonus_boundary_white) * lp + (BONUS_FIRST_CHAR_MULTIPLIER - 1) * bonus_boundary_white
        return Result(trimmed_len, trimmed_len + lp, score), None

    return Result(-1, -1, 0), None
