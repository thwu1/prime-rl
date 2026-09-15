"""Fix bugs in the sr_verify package by analyzing and patching source files."""


def fix_normalizer():
    """Fix two bugs in normalizer.py:
    1. Regex pattern matches digits inside alphanumeric tokens (e.g., 'F1' -> 'Fone')
       because it lacks word boundary anchors.
    2. The zero case in _int_to_words is unreachable due to wrong comparison operator,
       causing '0' to normalize to empty string instead of 'zero'.
    """
    path = '/app/sr_verify/normalizer.py'
    with open(path) as f:
        code = f.read()

    # Bug 1: r'\d+' matches digits inside alphanumeric tokens like F1, 3D
    # Fix: add word boundary anchors so only standalone digit sequences are expanded
    code = code.replace("r'\\d+'", "r'\\b\\d+\\b'")

    # Bug 2: 'if n < 0' never matches for n=0, so _int_to_words(0) returns ''
    # Fix: change to 'if n == 0' to correctly return 'zero'
    code = code.replace("if n < 0:", "if n == 0:")

    with open(path, 'w') as f:
        f.write(code)


def fix_interruptions():
    """Fix boundary condition bug in interruptions.py:
    The comparison uses strict '<' instead of '<=', so words whose last character
    ends exactly at the interruption time are incorrectly excluded from heard text.
    """
    path = '/app/sr_verify/interruptions.py'
    with open(path) as f:
        code = f.read()

    code = code.replace(
        "if end_time < interrupted_at_ms:",
        "if end_time <= interrupted_at_ms:"
    )

    with open(path, 'w') as f:
        f.write(code)


def fix_metrics():
    """Fix edit distance computation in metrics.py:
    The Levenshtein distance is missing the substitution operation — it only considers
    insertions and deletions, computing an LCS-based distance instead. This causes
    WER to be inflated for any input pair that requires character substitutions.
    """
    path = '/app/sr_verify/metrics.py'
    with open(path) as f:
        code = f.read()

    code = code.replace(
        "dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1])",
        "dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])"
    )

    with open(path, 'w') as f:
        f.write(code)


if __name__ == '__main__':
    fix_normalizer()
    fix_interruptions()
    fix_metrics()
    print("All bugs fixed in sr_verify package.")
