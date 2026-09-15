"""
Faithful Python translation of fzf's FuzzyMatchV2 algorithm from algo.go.
This implements the "default" scoring scheme.

"""

# ─── Character classes ───
CHAR_WHITE = 0
CHAR_NON_WORD = 1
CHAR_DELIMITER = 2
CHAR_LOWER = 3
CHAR_UPPER = 4
CHAR_LETTER = 5
CHAR_NUMBER = 6

# ─── Scoring constants ───
SCORE_MATCH = 16
SCORE_GAP_START = -3
SCORE_GAP_EXTENSION = -1

BONUS_BOUNDARY = SCORE_MATCH // 2            # 8
BONUS_NON_WORD = SCORE_MATCH // 2            # 8
BONUS_CAMEL_123 = BONUS_BOUNDARY + SCORE_GAP_EXTENSION  # 7
BONUS_CONSECUTIVE = -(SCORE_GAP_START + SCORE_GAP_EXTENSION)  # 4
BONUS_FIRST_CHAR_MULTIPLIER = 2

# "default" scheme values
BONUS_BOUNDARY_WHITE = BONUS_BOUNDARY + 2    # 10
BONUS_BOUNDARY_DELIMITER = BONUS_BOUNDARY + 1  # 9

DELIMITER_CHARS = "/,:;|"
WHITE_CHARS = " \t\n\x0b\x0c\r\x85\xa0"

INITIAL_CHAR_CLASS = CHAR_WHITE  # "default" scheme

# ─── Precomputed tables ───

def _char_class_of(char: str) -> int:
    """Classify a single character."""
    o = ord(char)
    if o <= 127:
        return _ASCII_CHAR_CLASSES[o]
    # Non-ASCII fallback (not needed for this task but included for completeness)
    if char.islower():
        return CHAR_LOWER
    if char.isupper():
        return CHAR_UPPER
    if char.isdigit():
        return CHAR_NUMBER
    if char.isalpha():
        return CHAR_LETTER
    if char in WHITE_CHARS:
        return CHAR_WHITE
    if char in DELIMITER_CHARS:
        return CHAR_DELIMITER
    return CHAR_NON_WORD


def _bonus_for(prev_class: int, cur_class: int) -> int:
    """Compute bonus for a character given its class and the previous character's class."""
    if cur_class >= CHAR_NON_WORD:
        # cur is non_word, delimiter, lower, upper, letter, or number
        # Actually the Go code checks: if class >= charNonWord (which means class is NOT charWhite)
        # Wait, let me re-read. charNonWord = 1. So class >= charNonWord means class in {1,2,3,4,5,6}
        # which is everything except charWhite.
        # But the bonus_for function gives boundary bonuses only when prev is white/delimiter/nonword
        # and cur is... let me re-read the Go.
        #
        # Go code:
        #   if class >= charNonWord {
        #       switch prevClass {
        #       case charWhite: return bonusBoundaryWhite
        #       case charDelimiter: return bonusBoundaryDelimiter
        #       case charNonWord: return bonusBoundary
        #       }
        #   }
        # This means: if current char is anything other than white, and previous is
        # white/delimiter/nonword, give a boundary bonus.
        # But wait, this block doesn't have a default — it falls through if prev is
        # lower/upper/letter/number. So boundary bonuses only when prev is a "non-word-like" class.
        pass  # handled below

    # The actual Go logic:
    # 1. If cur_class is not charWhite (>= charNonWord=1):
    if cur_class > CHAR_WHITE:
        if prev_class == CHAR_WHITE:
            return BONUS_BOUNDARY_WHITE
        elif prev_class == CHAR_DELIMITER:
            return BONUS_BOUNDARY_DELIMITER
        elif prev_class == CHAR_NON_WORD:
            return BONUS_BOUNDARY

    # 2. camelCase / letter-to-number transitions
    if prev_class == CHAR_LOWER and cur_class == CHAR_UPPER:
        return BONUS_CAMEL_123
    if prev_class != CHAR_NUMBER and cur_class == CHAR_NUMBER:
        return BONUS_CAMEL_123

    # 3. Non-word / delimiter / white bonuses for the current char
    if cur_class in (CHAR_NON_WORD, CHAR_DELIMITER):
        return BONUS_NON_WORD
    if cur_class == CHAR_WHITE:
        return BONUS_BOUNDARY_WHITE

    return 0


# Build ASCII char class table
_ASCII_CHAR_CLASSES = [CHAR_NON_WORD] * 128
for _i in range(128):
    _ch = chr(_i)
    if 'a' <= _ch <= 'z':
        _ASCII_CHAR_CLASSES[_i] = CHAR_LOWER
    elif 'A' <= _ch <= 'Z':
        _ASCII_CHAR_CLASSES[_i] = CHAR_UPPER
    elif '0' <= _ch <= '9':
        _ASCII_CHAR_CLASSES[_i] = CHAR_NUMBER
    elif _ch in WHITE_CHARS:
        _ASCII_CHAR_CLASSES[_i] = CHAR_WHITE
    elif _ch in DELIMITER_CHARS:
        _ASCII_CHAR_CLASSES[_i] = CHAR_DELIMITER

# Build bonus matrix
_BONUS_MATRIX = [[0] * (CHAR_NUMBER + 1) for _ in range(CHAR_NUMBER + 1)]
for _i in range(CHAR_NUMBER + 1):
    for _j in range(CHAR_NUMBER + 1):
        _BONUS_MATRIX[_i][_j] = _bonus_for(_i, _j)


def fuzzy_match_v2(text: str, pattern: str, case_sensitive: bool = False) -> tuple:
    """
    Reimplementation of fzf's FuzzyMatchV2 algorithm.
    Returns (start, end, score). Returns (-1, -1, 0) on no match.
    Always uses forward matching and "default" scoring scheme.
    """
    if not case_sensitive:
        pattern = pattern.lower()

    M = len(pattern)
    if M == 0:
        return (0, 0, 0)

    N = len(text)
    if M > N:
        return (-1, -1, 0)

    # Phase 1: Check if all pattern chars exist in text (forward scan) and find bounds
    # This is the asciiFuzzyIndex equivalent + existence check
    pidx = 0
    first_idx = 0
    last_idx = 0
    for i in range(N):
        char = text[i]
        if not case_sensitive:
            char = char.lower()
        pchar = pattern[pidx]
        if char == pchar:
            if pidx == 0 and i > 0:
                first_idx = i - 1
            last_idx = i
            pidx += 1
            if pidx == M:
                break

    if pidx != M:
        return (-1, -1, 0)

    # Find the last occurrence of the last pattern char to extend scope
    last_pattern_char = pattern[M - 1]
    for i in range(N - 1, last_idx, -1):
        char = text[i]
        if not case_sensitive:
            char = char.lower()
        if char == last_pattern_char:
            last_idx = i
            break

    # Work with the substring [min_idx, max_idx)
    min_idx = first_idx
    max_idx = last_idx + 1
    n = max_idx - min_idx

    # Build rune array T (working copy of text slice, lowercased if needed)
    T = list(text[min_idx:max_idx])
    if not case_sensitive:
        T = [c.lower() for c in T]

    # Phase 2: Calculate bonus for each position and fill H0 (first row)
    B = [0] * n      # bonus at each position
    H0 = [0] * n     # score for first pattern char at each position
    C0 = [0] * n     # consecutive count for first row

    prev_class = INITIAL_CHAR_CLASS
    if min_idx > 0:
        prev_char = text[min_idx - 1]
        prev_class = _char_class_of(prev_char)

    # First occurrence positions of each pattern char
    F = [0] * M
    pidx = 0
    pchar0 = pattern[0]
    pchar = pattern[0]
    prev_h0 = 0
    in_gap = False
    max_score = 0
    max_score_pos = 0

    for off in range(n):
        orig_char = text[min_idx + off]
        cur_class = _char_class_of(orig_char)
        char = T[off]

        bonus = _BONUS_MATRIX[prev_class][cur_class]
        B[off] = bonus
        prev_class = cur_class

        if char == pchar:
            if pidx < M:
                F[pidx] = off
                pidx += 1
                if pidx < M:
                    pchar = pattern[pidx]

            last_idx_local = off

        if char == pchar0:
            score = SCORE_MATCH + bonus * BONUS_FIRST_CHAR_MULTIPLIER
            H0[off] = score
            C0[off] = 1
            if M == 1 and score > max_score:
                max_score = score
                max_score_pos = off
                if bonus >= BONUS_BOUNDARY:
                    in_gap = False
                    prev_h0 = H0[off]
                    # For single-char pattern with boundary bonus, can break early
                    # but for correctness in forward mode, we actually do break
                    # Actually in Go: if forward && bonus >= bonusBoundary { break }
                    break
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
        return (-1, -1, 0)

    if M == 1:
        return (min_idx + max_score_pos, min_idx + max_score_pos + 1, max_score)

    # Recalculate last_idx_local properly — it's the last position where any pattern char matched
    # Actually in the Go code, lastIdx is updated whenever char == pchar (current pattern char being searched)
    # Let me recalculate: it's the position of F[M-1] at minimum, but could be later if more occurrences
    # exist. Actually F tracks first occurrences. lastIdx in Go is the last position where char == pchar
    # (which is the last pattern char after all are found). Let me re-examine.
    # In Go, lastIdx is set to `off` whenever `char == pchar` (and pchar keeps changing as pidx advances).
    # After pidx == M, pchar stays at pattern[M-1], so lastIdx tracks the last occurrence of pattern[M-1].
    # But in the code above, I already handle F correctly and the loop continues to the end.
    # Let me just find lastIdx as the last position in T where T[pos] == pattern[M-1]
    last_idx_local = F[M - 1]
    for off in range(F[M - 1] + 1, n):
        if T[off] == pattern[M - 1]:
            last_idx_local = off

    # Also need to complete H0, B arrays for positions we may have skipped due to early break
    # Recalculate from scratch more carefully for M > 1 case
    # Actually for M > 1 we never hit the break, so H0 and B should be complete.
    # But we need to also recompute H0 for positions after F[0] that we may need.

    # Phase 3: Fill score matrix
    f0 = F[0]
    width = last_idx_local - f0 + 1

    # H[i][j] = H[i * width + (j - f0)]
    H = [0] * (width * M)
    C = [0] * (width * M)

    # Copy first row from H0
    for j in range(f0, last_idx_local + 1):
        H[j - f0] = H0[j]
        C[j - f0] = C0[j]

    max_score = 0
    max_score_pos = 0

    for i in range(1, M):
        f = F[i]
        pchar_i = pattern[i]
        in_gap = False

        for off in range(f, last_idx_local + 1):
            col = off
            j0 = off - f0
            row = i * width

            char = T[off]
            s1 = 0
            s2 = 0
            consecutive = 0

            # Gap score (from left)
            if j0 > 0:
                left_val = H[row + j0 - 1]
            else:
                left_val = 0

            if in_gap:
                s2 = left_val + SCORE_GAP_EXTENSION
            else:
                s2 = left_val + SCORE_GAP_START

            # Match score (from diagonal)
            if pchar_i == char:
                if j0 > 0:
                    diag_h = H[(i - 1) * width + j0 - 1]
                    diag_c = C[(i - 1) * width + j0 - 1]
                else:
                    diag_h = 0
                    diag_c = 0

                s1 = diag_h + SCORE_MATCH
                b = B[off]
                consecutive = diag_c + 1

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

            C[row + j0] = consecutive
            in_gap = s1 < s2
            score = max(s1, s2, 0)

            if i == M - 1 and score > max_score:
                max_score = score
                max_score_pos = col

            H[row + j0] = score

    # Phase 4: Backtrace to find start position
    j = max_score_pos
    i = M - 1
    prefer_match = True

    while True:
        I = i * width
        j0 = j - f0
        s = H[I + j0]

        s1 = 0
        if i > 0 and j >= F[i]:
            s1 = H[I - width + j0 - 1] if j0 > 0 else 0

        s2 = 0
        if j > F[i]:
            s2 = H[I + j0 - 1]

        if s > s1 and (s > s2 or (s == s2 and prefer_match)):
            if i == 0:
                break
            i -= 1
        else:
            # Check prefer_match for next iteration
            pass

        prefer_match = (C[I + j0] > 1 or
                       (I + width + j0 + 1 < len(C) and C[I + width + j0 + 1] > 0))
        j -= 1

    start = min_idx + j
    end = min_idx + max_score_pos + 1

    return (start, end, max_score)
