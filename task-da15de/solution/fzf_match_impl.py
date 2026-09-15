#!/usr/bin/env python3
"""
fzf-compatible match engine: replicates FuzzyMatchV2, ExactMatchNaive,
PrefixMatch, SuffixMatch, and EqualMatch under the 'default' scoring scheme.
"""


# --------------- scoring constants (default scheme) ---------------
SCORE_MATCH = 16
SCORE_GAP_START = -3
SCORE_GAP_EXTENSION = -1

BONUS_BOUNDARY = SCORE_MATCH // 2          # 8
BONUS_NON_WORD = SCORE_MATCH // 2          # 8
BONUS_CAMEL_123 = BONUS_BOUNDARY + SCORE_GAP_EXTENSION  # 7
BONUS_CONSECUTIVE = -(SCORE_GAP_START + SCORE_GAP_EXTENSION)  # 4
BONUS_FIRST_CHAR_MULTIPLIER = 2

BONUS_BOUNDARY_WHITE = BONUS_BOUNDARY + 2  # 10
BONUS_BOUNDARY_DELIMITER = BONUS_BOUNDARY + 1  # 9

# --------------- character classes ---------------
CHAR_WHITE = 0
CHAR_NON_WORD = 1
CHAR_DELIMITER = 2
CHAR_LOWER = 3
CHAR_UPPER = 4
CHAR_LETTER = 5
CHAR_NUMBER = 6

INITIAL_CHAR_CLASS = CHAR_WHITE  # default scheme

_DELIMITER_CHARS = frozenset("/,:;|")
_WHITE_CHARS = frozenset(" \t\n\x0b\x0c\r\x85\xa0")


def _char_class(c):
    o = ord(c)
    if 97 <= o <= 122:
        return CHAR_LOWER
    if 65 <= o <= 90:
        return CHAR_UPPER
    if 48 <= o <= 57:
        return CHAR_NUMBER
    if c in _WHITE_CHARS:
        return CHAR_WHITE
    if c in _DELIMITER_CHARS:
        return CHAR_DELIMITER
    return CHAR_NON_WORD


def _bonus_for(prev_class, cur_class):
    if cur_class >= CHAR_NON_WORD:
        if prev_class == CHAR_WHITE:
            return BONUS_BOUNDARY_WHITE
        if prev_class == CHAR_DELIMITER:
            return BONUS_BOUNDARY_DELIMITER
        if prev_class == CHAR_NON_WORD:
            return BONUS_BOUNDARY
    if prev_class == CHAR_LOWER and cur_class == CHAR_UPPER:
        return BONUS_CAMEL_123
    if prev_class != CHAR_NUMBER and cur_class == CHAR_NUMBER:
        return BONUS_CAMEL_123
    if cur_class in (CHAR_NON_WORD, CHAR_DELIMITER):
        return BONUS_NON_WORD
    if cur_class == CHAR_WHITE:
        return BONUS_BOUNDARY_WHITE
    return 0


_BONUS = [[_bonus_for(i, j) for j in range(CHAR_NUMBER + 1)]
          for i in range(CHAR_NUMBER + 1)]


def _bonus_at(text, idx):
    if idx == 0:
        return BONUS_BOUNDARY_WHITE
    return _BONUS[_char_class(text[idx - 1])][_char_class(text[idx])]


def _calculate_score(text, pattern, sidx, eidx, case_sensitive):
    pidx = 0
    score = 0
    in_gap = False
    consecutive = 0
    first_bonus = 0
    prev_class = INITIAL_CHAR_CLASS if sidx == 0 else _char_class(text[sidx - 1])
    for idx in range(sidx, eidx):
        char = text[idx]
        cur_class = _char_class(char)
        if not case_sensitive:
            char = char.lower()
        if char == pattern[pidx]:
            score += SCORE_MATCH
            bonus = _BONUS[prev_class][cur_class]
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
            score += SCORE_GAP_EXTENSION if in_gap else SCORE_GAP_START
            in_gap = True
            consecutive = 0
            first_bonus = 0
        prev_class = cur_class
    return score


# ===================== fuzzy_match_v2 =====================

def fuzzy_match_v2(text, pattern, case_sensitive=False):
    M = len(pattern)
    if M == 0:
        return (0, 0, 0)
    N = len(text)
    if M > N:
        return (-1, -1, 0)
    if not case_sensitive:
        pattern = pattern.lower()

    # Build lowered text and bonus arrays
    T = list(text)
    B = [0] * N
    prev_class = INITIAL_CHAR_CLASS
    for i in range(N):
        cur_class = _char_class(text[i])
        B[i] = _BONUS[prev_class][cur_class]
        prev_class = cur_class
        if not case_sensitive:
            T[i] = text[i].lower()

    # Forward scan: first occurrence of each pattern char; track last occurrence
    # of the last pattern char for matrix width.
    F = []
    pidx = 0
    last_idx = 0
    pchar = pattern[0]
    for i in range(N):
        ch = T[i]
        if ch == pchar:
            if pidx < M:
                F.append(i)
                pidx += 1
                if pidx < M:
                    pchar = pattern[pidx]
            last_idx = i

    if pidx != M:
        return (-1, -1, 0)

    # Single-char pattern: find best-scoring position
    if M == 1:
        max_score = 0
        max_pos = 0
        pchar0 = pattern[0]
        for i in range(N):
            if T[i] == pchar0:
                s = SCORE_MATCH + B[i] * BONUS_FIRST_CHAR_MULTIPLIER
                if s > max_score:
                    max_score = s
                    max_pos = i
                    if B[i] >= BONUS_BOUNDARY:
                        break
        return (max_pos, max_pos + 1, max_score)

    # Phase 2: H0 (first pattern char scoring)
    f0 = F[0]
    width = last_idx - f0 + 1
    pchar0 = pattern[0]

    H0 = [0] * N
    C0 = [0] * N
    prev_h0 = 0
    in_gap = False
    for i in range(N):
        if T[i] == pchar0:
            H0[i] = SCORE_MATCH + B[i] * BONUS_FIRST_CHAR_MULTIPLIER
            C0[i] = 1
            in_gap = False
        else:
            if in_gap:
                H0[i] = max(prev_h0 + SCORE_GAP_EXTENSION, 0)
            else:
                H0[i] = max(prev_h0 + SCORE_GAP_START, 0)
            C0[i] = 0
            in_gap = True
        prev_h0 = H0[i]

    # Phase 3: fill score matrix H[row][col], col relative to f0
    H = [[0] * width for _ in range(M)]
    C = [[0] * width for _ in range(M)]
    for j in range(width):
        H[0][j] = H0[f0 + j]
        C[0][j] = C0[f0 + j]

    max_score = 0
    max_score_pos = 0

    for i in range(1, M):
        fi = F[i]
        pc = pattern[i]
        in_gap = False
        for j in range(fi, last_idx + 1):
            col = j - f0
            s1 = 0
            s2 = 0
            consecutive = 0

            # left (gap)
            if col > 0:
                if in_gap:
                    s2 = H[i][col - 1] + SCORE_GAP_EXTENSION
                else:
                    s2 = H[i][col - 1] + SCORE_GAP_START

            # diagonal (match)
            if T[j] == pc and col > 0:
                s1 = H[i - 1][col - 1] + SCORE_MATCH
                b = B[j]
                consecutive = C[i - 1][col - 1] + 1
                if consecutive > 1:
                    fb = B[j - consecutive + 1]
                    if b >= BONUS_BOUNDARY and b > fb:
                        consecutive = 1
                    else:
                        b = max(b, BONUS_CONSECUTIVE, fb)
                if s1 + b < s2:
                    s1 += B[j]
                    consecutive = 0
                else:
                    s1 += b

            C[i][col] = consecutive
            in_gap = s1 < s2
            score = max(s1, s2, 0)
            if i == M - 1 and score > max_score:
                max_score = score
                max_score_pos = j
            H[i][col] = score

    # Phase 4: backtrace
    i = M - 1
    j = max_score_pos
    prefer_match = True
    start_j = f0

    while True:
        col = j - f0
        curr_i = i
        s = H[curr_i][col]

        s1 = 0
        if curr_i > 0 and j >= F[curr_i]:
            s1 = H[curr_i - 1][col - 1]

        s2 = 0
        if j > F[curr_i]:
            s2 = H[curr_i][col - 1]

        if s > s1 and (s > s2 or (s == s2 and prefer_match)):
            if curr_i == 0:
                start_j = j
                break
            i -= 1

        prefer_match = (
            C[curr_i][col] > 1
            or (curr_i + 1 < M and col + 1 < width
                and C[curr_i + 1][col + 1] > 0)
        )
        j -= 1

    return (start_j, max_score_pos + 1, max_score)


# ===================== exact_match_naive =====================

def exact_match_naive(text, pattern, case_sensitive=False):
    if len(pattern) == 0:
        return (0, 0, 0)
    if not case_sensitive:
        pattern = pattern.lower()

    len_runes = len(text)
    len_pattern = len(pattern)
    if len_runes < len_pattern:
        return (-1, -1, 0)

    best_pos = -1
    best_bonus = -1
    pidx = 0
    bonus = 0
    index = 0

    while index < len_runes:
        char = text[index]
        if not case_sensitive:
            char = char.lower()
        pchar = pattern[pidx]
        if char == pchar:
            if pidx == 0:
                bonus = _bonus_at(text, index)
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
        sidx = best_pos - len_pattern + 1
        eidx = best_pos + 1
        score = _calculate_score(text, pattern, sidx, eidx, case_sensitive)
        return (sidx, eidx, score)
    return (-1, -1, 0)


# ===================== prefix_match =====================

def prefix_match(text, pattern, case_sensitive=False):
    if len(pattern) == 0:
        return (0, 0, 0)
    if not case_sensitive:
        pattern = pattern.lower()

    trimmed_len = 0
    if len(pattern) > 0 and not pattern[0].isspace():
        for c in text:
            if c in _WHITE_CHARS:
                trimmed_len += 1
            else:
                break

    if len(text) - trimmed_len < len(pattern):
        return (-1, -1, 0)

    for i, r in enumerate(pattern):
        char = text[trimmed_len + i]
        if not case_sensitive:
            char = char.lower()
        if char != r:
            return (-1, -1, 0)

    lp = len(pattern)
    score = _calculate_score(text, pattern, trimmed_len, trimmed_len + lp,
                             case_sensitive)
    return (trimmed_len, trimmed_len + lp, score)


# ===================== suffix_match =====================

def suffix_match(text, pattern, case_sensitive=False):
    len_runes = len(text)
    trimmed_len = len_runes
    if len(pattern) == 0 or not pattern[-1].isspace():
        while trimmed_len > 0 and text[trimmed_len - 1] in _WHITE_CHARS:
            trimmed_len -= 1

    if len(pattern) == 0:
        return (trimmed_len, trimmed_len, 0)

    if not case_sensitive:
        pattern = pattern.lower()

    diff = trimmed_len - len(pattern)
    if diff < 0:
        return (-1, -1, 0)

    for i, r in enumerate(pattern):
        char = text[i + diff]
        if not case_sensitive:
            char = char.lower()
        if char != r:
            return (-1, -1, 0)

    lp = len(pattern)
    sidx = trimmed_len - lp
    eidx = trimmed_len
    score = _calculate_score(text, pattern, sidx, eidx, case_sensitive)
    return (sidx, eidx, score)


# ===================== equal_match =====================

def equal_match(text, pattern, case_sensitive=False):
    lp = len(pattern)
    if lp == 0:
        return (-1, -1, 0)
    if not case_sensitive:
        pattern = pattern.lower()

    trimmed_start = 0
    if not pattern[0].isspace():
        for c in text:
            if c in _WHITE_CHARS:
                trimmed_start += 1
            else:
                break

    trimmed_end = 0
    if not pattern[-1].isspace():
        for c in reversed(text):
            if c in _WHITE_CHARS:
                trimmed_end += 1
            else:
                break

    if len(text) - trimmed_start - trimmed_end != lp:
        return (-1, -1, 0)

    segment = text[trimmed_start:len(text) - trimmed_end] if trimmed_end > 0 \
        else text[trimmed_start:]
    if not case_sensitive:
        segment = segment.lower()
    if segment != pattern:
        return (-1, -1, 0)

    score = ((SCORE_MATCH + BONUS_BOUNDARY_WHITE) * lp
             + (BONUS_FIRST_CHAR_MULTIPLIER - 1) * BONUS_BOUNDARY_WHITE)
    return (trimmed_start, trimmed_start + lp, score)
