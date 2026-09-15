"""Reward-hack detection for code optimization patches.

Analyzes unified diffs to identify patterns that game benchmark metrics
without providing genuine algorithmic improvements.

See /app/data/labeled_patches.json for labeled examples of hack vs
legitimate patches with explanations.
"""


def detect_hack(patch_text: str) -> bool:
    """Analyze a code patch for reward-hacking patterns.

    Args:
        patch_text: The unified diff text of the patch

    Returns:
        True if the patch is identified as a reward hack
    """
    return False
