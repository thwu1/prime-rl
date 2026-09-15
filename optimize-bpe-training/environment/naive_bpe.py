"""
Naive BPE tokenizer implementation — reference for correctness.

This recomputes all pair statistics from scratch after every merge,
giving O(N*K) total work where N is total token count and K is merge count.
"""

import regex as re

GPT4_SPLIT_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""


def get_stats(ids, counts=None):
    """Count consecutive pairs in a list of integers."""
    counts = {} if counts is None else counts
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def merge(ids, pair, idx):
    """Replace all consecutive occurrences of pair with idx."""
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
    def __init__(self, pattern=None):
        self.pattern = GPT4_SPLIT_PATTERN if pattern is None else pattern
        self.compiled_pattern = re.compile(self.pattern)
        self.merges = {}
        self.vocab = {idx: bytes([idx]) for idx in range(256)}

    def train(self, text, num_merges):
        """
        Train BPE for num_merges steps. Returns ordered list of merge pairs.

        Tie-breaking: highest frequency wins; among ties, the lexicographically
        smallest (token1, token2) tuple is chosen.
        """
        text_chunks = re.findall(self.compiled_pattern, text)
        ids = [list(ch.encode("utf-8")) for ch in text_chunks]

        merges = {}
        vocab = {idx: bytes([idx]) for idx in range(256)}
        merge_list = []

        for i in range(num_merges):
            stats = {}
            for chunk_ids in ids:
                get_stats(chunk_ids, stats)
            if not stats:
                break
            # Deterministic tie-breaking: highest count, then smallest pair tuple
            pair = max(stats, key=lambda p: (stats[p], -p[0], -p[1]))
            idx = 256 + i
            ids = [merge(chunk_ids, pair, idx) for chunk_ids in ids]
            merges[pair] = idx
            vocab[idx] = vocab[pair[0]] + vocab[pair[1]]
            merge_list.append(pair)

        self.merges = merges
        self.vocab = vocab
        return merge_list

    def encode(self, text):
        """Encode text to token ids using trained merges."""
        text_chunks = re.findall(self.compiled_pattern, text)
        ids = []
        for chunk in text_chunks:
            chunk_bytes = chunk.encode("utf-8")
            chunk_ids = list(chunk_bytes)
            while len(chunk_ids) >= 2:
                stats = get_stats(chunk_ids)
                pair = min(stats, key=lambda p: self.merges.get(p, float("inf")))
                if pair not in self.merges:
                    break
                idx = self.merges[pair]
                chunk_ids = merge(chunk_ids, pair, idx)
            ids.extend(chunk_ids)
        return ids

    def decode(self, ids):
        """Decode token ids back to text."""
        text_bytes = b"".join(self.vocab[idx] for idx in ids)
        return text_bytes.decode("utf-8", errors="replace")
