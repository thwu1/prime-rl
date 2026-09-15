#!/usr/bin/env python3
"""
Setup script for the BPE merge recovery task.
Trains a BPE tokenizer with regex pre-tokenization and a byte shuffle,
exports the mergeable_ranks format, and generates test cases.
This script runs during Docker build and is deleted afterward.
"""

import json
import os
import random
import regex as re

# ---- BPE core functions ----

def get_stats(ids, counts=None):
    counts = {} if counts is None else counts
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts

def merge(ids, pair, idx):
    newids = []
    i = 0
    while i < len(ids):
        if ids[i] == pair[0] and i < len(ids) - 1 and ids[i+1] == pair[1]:
            newids.append(idx)
            i += 2
        else:
            newids.append(ids[i])
            i += 1
    return newids

# ---- Configuration ----

GPT4_SPLIT_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
NUM_MERGES = 200
BYTE_SHUFFLE_SEED = 42

# ---- Train tokenizer ----

with open('/tmp/training_corpus.txt', 'r') as f:
    training_text = f.read()

compiled_pattern = re.compile(GPT4_SPLIT_PATTERN)
text_chunks = re.findall(compiled_pattern, training_text)
chunk_ids = [list(ch.encode("utf-8")) for ch in text_chunks]

merges = {}
vocab = {idx: bytes([idx]) for idx in range(256)}

for i in range(NUM_MERGES):
    stats = {}
    for cids in chunk_ids:
        get_stats(cids, stats)
    if not stats:
        break
    pair = max(stats, key=stats.get)
    idx = 256 + i
    chunk_ids = [merge(cids, pair, idx) for cids in chunk_ids]
    merges[pair] = idx
    vocab[idx] = vocab[pair[0]] + vocab[pair[1]]

actual_num_merges = len(merges)
print(f"Trained {actual_num_merges} merges")

# ---- Create byte shuffle (deterministic permutation) ----

random.seed(BYTE_SHUFFLE_SEED)
byte_shuffle_list = list(range(256))
random.shuffle(byte_shuffle_list)
byte_shuffle = {i: byte_shuffle_list[i] for i in range(256)}
inverse_byte_shuffle = {v: k for k, v in byte_shuffle.items()}

# ---- Create shuffled merges (remap base token IDs) ----

def remap_id(x):
    if x < 256:
        return byte_shuffle[x]
    return x

shuffled_merges = {}
for (p0, p1), idx in merges.items():
    shuffled_merges[(remap_id(p0), remap_id(p1))] = idx

# Build shuffled vocab
shuffled_vocab = {rank: bytes([rank]) for rank in range(256)}
for (p0, p1), idx in sorted(shuffled_merges.items(), key=lambda x: x[1]):
    shuffled_vocab[idx] = shuffled_vocab[p0] + shuffled_vocab[p1]

# ---- Construct mergeable_ranks ----

mergeable_ranks = {}
for i in range(256):
    key = bytes([i]).hex()
    mergeable_ranks[key] = byte_shuffle[i]

for (p0, p1), idx in sorted(merges.items(), key=lambda x: x[1]):
    raw_bytes = vocab[idx]
    key = raw_bytes.hex()
    mergeable_ranks[key] = idx

# ---- Encode/decode for generating test cases ----

def encode_chunk(text_bytes):
    ids = [byte_shuffle[b] for b in text_bytes]
    while len(ids) >= 2:
        stats = get_stats(ids)
        pair = min(stats, key=lambda p: shuffled_merges.get(p, float("inf")))
        if pair not in shuffled_merges:
            break
        idx = shuffled_merges[pair]
        ids = merge(ids, pair, idx)
    return ids

def encode(text):
    if not text:
        return []
    chunks = re.findall(compiled_pattern, text)
    all_ids = []
    for chunk in chunks:
        chunk_bytes = chunk.encode("utf-8")
        ids = encode_chunk(chunk_bytes)
        all_ids.extend(ids)
    return all_ids

def decode(ids):
    if not ids:
        return ""
    text_bytes = b"".join(shuffled_vocab[idx] for idx in ids)
    raw_bytes = bytes(inverse_byte_shuffle[b] for b in text_bytes)
    return raw_bytes.decode("utf-8", errors="replace")

# ---- Generate test cases ----

test_strings = [
    "",
    "a",
    "ab",
    "hello",
    "hello world",
    "Hello, World!",
    "test123 testing",
    "The quick brown fox jumps over the lazy dog.",
    "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)\n",
    "x = [1, 2, 3]\nfor item in x:\n    print(item)",
    "  spaces   and\ttabs  ",
    "Numbers: 42 3.14 100 255 1000",
    "Special chars: @#$%^&*()_+-={}[]|\\:\";<>?,./~`",
    "Mixed CaSe TeXt WiTh VaRiOuS patterns",
    "the the the the the the the the",
    "aaabbbcccdddeeefffggghhhiiijjj",
    "It's a beautiful day, isn't it? We'll see what we've done.",
    "Line 1\nLine 2\nLine 3\n\nParagraph 2",
    "Repeated: abcabcabcabc defdefdefdef",
    "sorting algorithms and data structures are fundamental",
    "self.value = value\nself.left = None\nself.right = None",
    "hello \uc548\ub155\ud558\uc138\uc694",
]

test_cases = []
for text in test_strings:
    ids = encode(text)
    decoded = decode(ids)
    assert decoded == text, f"Roundtrip failed for: {repr(text)}\n  encoded: {ids}\n  decoded: {repr(decoded)}"
    test_cases.append({"text": text, "expected_ids": ids})

# ---- Save to /app/ ----

os.makedirs('/app', exist_ok=True)

with open('/app/mergeable_ranks.json', 'w') as f:
    json.dump(mergeable_ranks, f, indent=2)

with open('/app/test_cases.json', 'w') as f:
    json.dump(test_cases, f, indent=2)

metadata = {
    "num_merges": actual_num_merges,
    "vocab_size": 256 + actual_num_merges,
    "description": "BPE tokenizer with regex pre-tokenization and byte shuffle"
}
with open('/app/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

readme = """BPE Merge Recovery Task
=======================

You are given a BPE tokenizer's mergeable_ranks -- a flat mapping from
byte sequences (hex-encoded) to integer ranks. This is the same format
used by tiktoken internally.

The tokenizer was trained with:
- A regex-based pre-tokenization pattern (you must determine which one)
- A byte-level permutation applied to the base 256 byte tokens
- BPE merges on top of the permuted byte vocabulary

Your task: recover the full tokenizer and implement encode/decode functions
that exactly match the expected outputs in test_cases.json.

Files:
- mergeable_ranks.json: hex(byte_sequence) -> integer rank
- test_cases.json: [{text, expected_ids}, ...]
- metadata.json: tokenizer metadata
"""

with open('/app/README.txt', 'w') as f:
    f.write(readme)

print("Setup complete!")
print(f"  Vocab size: {256 + actual_num_merges}")
print(f"  Test cases: {len(test_cases)}")
