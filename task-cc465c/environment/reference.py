"""
Naive BPE (Byte Pair Encoding) training implementation.
This serves as the reference that any optimized version must match exactly.

The algorithm:
1. Encode text as UTF-8 bytes (values 0-255)
2. On each iteration:
   a. Count all consecutive byte-pair frequencies
   b. Merge the most frequent pair into a new token
   c. Replace all occurrences of that pair in the sequence
3. Return the merge table: {(token_a, token_b): new_token_id}

Tie-breaking: when multiple pairs share the highest frequency,
the pair whose leftmost occurrence in the current sequence appears
first wins (this falls out naturally from Python's dict insertion
order and max() semantics).
"""


def get_stats(ids):
    """Count consecutive pairs in the token sequence."""
    counts = {}
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def merge(ids, pair, idx):
    """Replace all non-overlapping occurrences of pair (left-to-right) with idx."""
    newids = []
    i = 0
    while i < len(ids):
        if ids[i] == pair[0] and i < len(ids) - 1 and ids[i + 1] == pair[1]:
            newids.append(idx)
            i += 2
        else:
            newids.append(ids[i])
            i += 1
    return newids


class NaiveBPETrainer:
    def train(self, text, num_merges):
        """
        Train BPE on the given text for num_merges merge steps.

        Returns:
            dict: mapping (int, int) -> int, where keys are the merged pair
                  and values are the new token IDs (starting at 256).
        """
        ids = list(text.encode("utf-8"))
        merges = {}
        for i in range(num_merges):
            stats = get_stats(ids)
            if not stats:
                break
            pair = max(stats, key=stats.get)
            idx = 256 + i
            ids = merge(ids, pair, idx)
            merges[pair] = idx
        return merges
