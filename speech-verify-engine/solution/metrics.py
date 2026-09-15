"""Word Error Rate computation and segmented alignment."""
from dataclasses import dataclass
from .normalizer import normalize


@dataclass
class SegmentResult:
    ref_words: list
    hyp_words: list
    wer: float
    edit_distance: int


def _edit_distance(ref, hyp):
    """Compute word-level edit distance between two word lists."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m]


def wer(reference, hypothesis):
    """Compute Word Error Rate between reference and hypothesis strings.

    Both strings are normalized before comparison.
    Returns (substitutions + deletions + insertions) / reference_length.
    """
    ref_words = normalize(reference).split()
    hyp_words = normalize(hypothesis).split()

    if not ref_words and not hyp_words:
        return 0.0
    if not ref_words:
        return 1.0
    if not hyp_words:
        return 1.0

    ed = _edit_distance(ref_words, hyp_words)
    return ed / len(ref_words)


def segmented_wer(hyp_words, ref_segments):
    """Find optimal consecutive partition of hypothesis minimizing total WER.

    Partitions hyp_words into len(ref_segments) consecutive groups such that
    total edit distance / total reference words is minimized.

    Returns (overall_wer, list[SegmentResult]).
    """
    N = len(hyp_words)
    K = len(ref_segments)

    if K == 0:
        return (0.0 if N == 0 else 1.0), []

    total_ref = sum(len(seg) for seg in ref_segments)
    if total_ref == 0:
        overall = 0.0 if N == 0 else 1.0
        return overall, [
            SegmentResult(list(seg), [], 0.0, 0) for seg in ref_segments
        ]

    INF = float('inf')
    # dp[j][i] = min total edit distance using first j segments covering hyp[0:i]
    dp = [[INF] * (N + 1) for _ in range(K + 1)]
    dp[0][0] = 0
    parent = [[-1] * (N + 1) for _ in range(K + 1)]

    for j in range(1, K + 1):
        ref_seg = ref_segments[j - 1]
        for i in range(N + 1):
            for k in range(i + 1):
                if dp[j - 1][k] == INF:
                    continue
                ed = _edit_distance(ref_seg, hyp_words[k:i])
                total = dp[j - 1][k] + ed
                if total < dp[j][i]:
                    dp[j][i] = total
                    parent[j][i] = k

    total_ed = dp[K][N]
    if total_ed == INF:
        return 1.0, [
            SegmentResult(list(seg), [], 1.0, len(seg))
            for seg in ref_segments
        ]

    overall_wer = total_ed / total_ref

    # Traceback to recover split boundaries
    boundaries = [N]
    i = N
    for j in range(K, 0, -1):
        k = parent[j][i]
        boundaries.append(k)
        i = k
    boundaries.reverse()

    results = []
    for j in range(K):
        seg_hyp = list(hyp_words[boundaries[j]:boundaries[j + 1]])
        seg_ref = list(ref_segments[j])
        ed = _edit_distance(seg_ref, seg_hyp)
        if len(seg_ref) > 0:
            seg_wer = ed / len(seg_ref)
        else:
            seg_wer = 0.0 if len(seg_hyp) == 0 else 1.0
        results.append(SegmentResult(seg_ref, seg_hyp, seg_wer, ed))

    return overall_wer, results
