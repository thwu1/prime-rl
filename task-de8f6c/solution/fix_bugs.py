#!/usr/bin/env python3
"""Diagnose and fix all defects in the stt_verifier package.

"""


def fix_wer():
    """Fix two defects in wer.py:
    1. Regex pattern only matches 1-2 digit numbers, missing 3-digit conversion.
    2. Insertion and deletion counters are swapped in backtracking.
    """
    path = '/app/stt_verifier/wer.py'
    with open(path) as f:
        content = f.read()

    # Fix 1: Expand regex to match all digit sequences
    content = content.replace(
        r"\b(\d{1,2})\b",
        r"\b(\d+)\b"
    )

    # Fix 2: Swap ins/dels back to correct assignment in backtracking
    # In edit distance: moving along j (hypothesis) without i = insertion
    #                   moving along i (reference) without j = deletion
    buggy_block = (
        "        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:\n"
        "            dels += 1\n"
        "            j -= 1\n"
        "        else:\n"
        "            ins += 1\n"
        "            i -= 1"
    )
    fixed_block = (
        "        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:\n"
        "            ins += 1\n"
        "            j -= 1\n"
        "        else:\n"
        "            dels += 1\n"
        "            i -= 1"
    )
    content = content.replace(buggy_block, fixed_block)

    with open(path, 'w') as f:
        f.write(content)


def fix_vad():
    """Fix transposed frame_length and hop_length in vad.py.
    Standard STFT uses 25ms frames with 10ms hops, not the reverse.
    """
    path = '/app/stt_verifier/vad.py'
    with open(path) as f:
        content = f.read()

    # Swap back to correct values: frame=25ms, hop=10ms
    content = content.replace(
        "frame_length = int(sr * 0.010)",
        "frame_length = int(sr * 0.025)"
    )
    content = content.replace(
        "hop_length = int(sr * 0.025)",
        "hop_length = int(sr * 0.010)"
    )

    with open(path, 'w') as f:
        f.write(content)


def fix_matcher():
    """Fix inverted threshold comparison in matcher.py.
    A match is 'full' when WER is at or below the threshold, not above it.
    """
    path = '/app/stt_verifier/matcher.py'
    with open(path) as f:
        content = f.read()

    content = content.replace(
        "if wer >= threshold:",
        "if wer <= threshold:"
    )

    with open(path, 'w') as f:
        f.write(content)


def verify_fixes():
    """Run basic sanity checks on the fixed modules."""
    import sys
    sys.path.insert(0, '/app')

    from stt_verifier.wer import normalize_text, compute_wer

    # Verify 3-digit number conversion
    result = normalize_text("error 404")
    assert "four hundred" in result, f"Number conversion failed: {result}"

    # Verify correct ins/del attribution
    r = compute_wer("screen reader on", "screen reader")
    assert r['deletions'] == 1, f"Expected 1 deletion, got {r['deletions']}"
    assert r['insertions'] == 0, f"Expected 0 insertions, got {r['insertions']}"

    r = compute_wer("hello world", "hello beautiful world")
    assert r['insertions'] == 1, f"Expected 1 insertion, got {r['insertions']}"
    assert r['deletions'] == 0, f"Expected 0 deletions, got {r['deletions']}"

    # Verify matcher threshold
    from stt_verifier.matcher import match_sequence
    r = match_sequence(["screen reader on"], "screen reader on")
    assert r['matches'][0]['status'] == 'full', f"Expected full, got {r['matches'][0]['status']}"

    print("All fixes verified successfully.")


if __name__ == '__main__':
    fix_wer()
    fix_vad()
    fix_matcher()
    verify_fixes()
