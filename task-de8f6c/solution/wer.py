"""Word Error Rate computation with text normalization."""
import re
import string


_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen',
]
_TENS = [
    '', '', 'twenty', 'thirty', 'forty', 'fifty',
    'sixty', 'seventy', 'eighty', 'ninety',
]


def _int_to_words(n):
    """Convert an integer 0-999 to English words."""
    if n < 0:
        return 'minus ' + _int_to_words(-n)
    if n == 0:
        return 'zero'
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ('' if n % 10 == 0 else ' ' + _ONES[n % 10])
    if n < 1000:
        rest = _int_to_words(n % 100) if n % 100 != 0 else ''
        return _ONES[n // 100] + ' hundred' + (' ' + rest if rest else '')
    return str(n)


def normalize_text(text):
    """Lowercase, strip punctuation, convert integers 0-999 to words, collapse whitespace."""
    text = text.lower()
    text = re.sub(
        r'\b(\d+)\b',
        lambda m: _int_to_words(int(m.group(1))) if 0 <= int(m.group(1)) <= 999 else m.group(0),
        text,
    )
    text = text.translate(str.maketrans('', '', string.punctuation))
    text = ' '.join(text.split())
    return text


def compute_wer(reference, hypothesis, normalize=True):
    """Compute Word Error Rate using word-level edit distance.

    Returns dict with keys: wer, insertions, deletions, substitutions, ref_len.
    """
    if normalize:
        reference = normalize_text(reference)
        hypothesis = normalize_text(hypothesis)

    ref_words = reference.split()
    hyp_words = hypothesis.split()
    n = len(ref_words)
    m = len(hyp_words)

    if n == 0:
        return {
            'wer': float('inf') if m > 0 else 0.0,
            'insertions': m,
            'deletions': 0,
            'substitutions': 0,
            'ref_len': 0,
        }

    # Build DP table
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j - 1],  # substitution
                    dp[i - 1][j],      # deletion
                    dp[i][j - 1],      # insertion
                )

    # Backtrack to count individual operation types
    i, j = n, m
    subs = ins = dels = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_words[i - 1] == hyp_words[j - 1]:
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            subs += 1
            i -= 1
            j -= 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ins += 1
            j -= 1
        else:
            dels += 1
            i -= 1

    return {
        'wer': dp[n][m] / n,
        'insertions': ins,
        'deletions': dels,
        'substitutions': subs,
        'ref_len': n,
    }
