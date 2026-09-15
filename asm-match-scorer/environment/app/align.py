"""Needleman-Wunsch global sequence alignment for assembly instruction matching."""

GAP_PENALTY = 10
MNEMONIC_MISMATCH = 8


def _instruction_penalty(a, b):
    """Penalty for aligning two instructions."""
    mn_a, ops_a = a
    mn_b, ops_b = b
    if mn_a != mn_b:
        return MNEMONIC_MISMATCH
    n = max(len(ops_a), len(ops_b))
    diffs = 0
    for i in range(n):
        oa = ops_a[i] if i < len(ops_a) else ''
        ob = ops_b[i] if i < len(ops_b) else ''
        if oa != ob:
            diffs += 1
    return 2 * diffs


def needleman_wunsch(target, candidate):
    """Global sequence alignment returning list of (t_instr|None, c_instr|None)."""
    m, n = len(target), len(candidate)

    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = i * GAP_PENALTY
    for j in range(1, n + 1):
        dp[0][j] = j * GAP_PENALTY

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            match = dp[i - 1][j - 1] + _instruction_penalty(target[i - 1], candidate[j - 1])
            delete = dp[i - 1][j] + GAP_PENALTY
            insert = dp[i][j - 1] + GAP_PENALTY
            dp[i][j] = min(match, delete, insert)

    # Traceback
    alignment = []
    i, j = m, n
    while i > 0 and j > 0:
        if (i > 0 and j > 0
                and dp[i][j] == dp[i - 1][j - 1] + _instruction_penalty(target[i - 1], candidate[j - 1])):
            alignment.append((target[i - 1], candidate[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + GAP_PENALTY:
            alignment.append((target[i - 1], None))
            i -= 1
        else:
            alignment.append((None, candidate[j - 1]))
            j -= 1

    alignment.reverse()
    return alignment
