"""Interruption-aware sequence matching for screen reader output."""
from stt_verifier.wer import normalize_text, compute_wer


def match_sequence(expected_messages, transcription, threshold=0.5):
    """Optimally partition transcription words across expected messages using DP.

    Parameters
    ----------
    expected_messages : list[str]
        Ordered list of expected screen reader messages.
    transcription : str
        Transcribed text (may contain partial/concatenated messages).
    threshold : float
        Maximum WER for a match to be classified as 'full'.

    Returns
    -------
    dict
        'matches': list of per-message dicts with keys expected, status,
                   matched_text, score.
        'overall_score': average score across messages.
    """
    norm_trans = normalize_text(transcription)
    trans_words = norm_trans.split() if norm_trans else []
    n = len(trans_words)
    k = len(expected_messages)

    if k == 0:
        return {'matches': [], 'overall_score': 0.0}

    norm_expected = [normalize_text(m) for m in expected_messages]

    NEG_INF = float('-inf')

    # dp[i][j] = best total score matching messages 0..i-1 using trans words 0..j-1
    dp = [[NEG_INF] * (n + 1) for _ in range(k + 1)]
    parent_j = [[0] * (n + 1) for _ in range(k + 1)]
    parent_type = [['missing'] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0

    for i in range(1, k + 1):
        for j in range(n + 1):
            # Option A: message i-1 is missing (consumes no words)
            if dp[i - 1][j] > dp[i][j]:
                dp[i][j] = dp[i - 1][j]
                parent_j[i][j] = j
                parent_type[i][j] = 'missing'

            # Option B: message i-1 uses words [j_start .. j)
            for j_start in range(j):
                window_text = ' '.join(trans_words[j_start:j])
                wer_result = compute_wer(norm_expected[i - 1], window_text, normalize=False)
                wer = wer_result['wer']
                score = max(0.0, 1.0 - wer) if wer != float('inf') else 0.0

                total = dp[i - 1][j_start] + score
                if total > dp[i][j]:
                    dp[i][j] = total
                    parent_j[i][j] = j_start
                    parent_type[i][j] = 'matched'

    # Find best endpoint (allow unused trailing words)
    best_j = 0
    best_val = NEG_INF
    for j in range(n + 1):
        if dp[k][j] >= best_val:
            best_val = dp[k][j]
            best_j = j

    # Backtrack to recover assignments
    assignments = [None] * k
    j = best_j
    for i in range(k, 0, -1):
        prev_j = parent_j[i][j]
        if parent_type[i][j] == 'missing':
            assignments[i - 1] = ('missing', '')
        else:
            assignments[i - 1] = ('matched', ' '.join(trans_words[prev_j:j]))
        j = prev_j

    # Build result list
    matches = []
    for i, (atype, matched_text) in enumerate(assignments):
        if atype == 'missing':
            matches.append({
                'expected': expected_messages[i],
                'status': 'missing',
                'matched_text': '',
                'score': 0.0,
            })
        else:
            wer_result = compute_wer(norm_expected[i], matched_text, normalize=False)
            wer = wer_result['wer']
            score = max(0.0, 1.0 - wer) if wer != float('inf') else 0.0

            if wer >= threshold:
                status = 'full'
            elif score > 0:
                status = 'partial'
            else:
                status = 'missing'

            matches.append({
                'expected': expected_messages[i],
                'status': status,
                'matched_text': matched_text,
                'score': score,
            })

    overall_score = sum(m['score'] for m in matches) / k

    return {
        'matches': matches,
        'overall_score': overall_score,
    }
