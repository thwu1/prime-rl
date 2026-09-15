#!/usr/bin/env python3
"""
Solver for the BPE merge recovery task.

Recovers a full BPE tokenizer from a flat mergeable_ranks mapping by:
1. Extracting the byte shuffle from single-byte entries
2. Recovering the ordered merge table using recursive BPE decomposition
3. Detecting the regex splitting pattern by testing candidates
4. Writing a working tokenizer.py module

"""

import json
import os
import sys

# ---- Step 1: Load mergeable_ranks ----

with open('/app/mergeable_ranks.json') as f:
    raw_ranks = json.load(f)

# Convert hex keys to bytes
mergeable_ranks = {}
for hex_key, rank in raw_ranks.items():
    byte_key = bytes.fromhex(hex_key)
    mergeable_ranks[byte_key] = rank

print(f"Loaded {len(mergeable_ranks)} entries from mergeable_ranks")

# ---- Step 2: Recover byte shuffle ----

byte_shuffle = {}
inverse_byte_shuffle = {}

for byte_key, rank in mergeable_ranks.items():
    if len(byte_key) == 1:
        byte_val = byte_key[0]
        byte_shuffle[byte_val] = rank
        inverse_byte_shuffle[rank] = byte_val

assert len(byte_shuffle) == 256, f"Expected 256 single-byte entries, got {len(byte_shuffle)}"
print(f"Recovered byte shuffle (256 entries)")

# Check if it's actually a permutation
assert set(byte_shuffle.values()) == set(range(256)), "Byte shuffle is not a valid permutation of 0..255"

# ---- Step 3: Recover merges using BPE decomposition ----

def bpe(mergeable_ranks, token, max_rank):
    """
    Run BPE on a token's byte sequence using only merges with rank < max_rank.
    This decomposes the token into its two children at the time it was merged.
    """
    parts = [bytes([b]) for b in token]
    while True:
        min_idx = None
        min_rank = None
        for i in range(len(parts) - 1):
            pair_bytes = parts[i] + parts[i + 1]
            rank = mergeable_ranks.get(pair_bytes)
            if rank is not None and (min_rank is None or rank < min_rank):
                min_idx = i
                min_rank = rank
        if min_rank is None or (max_rank is not None and min_rank >= max_rank):
            break
        parts = parts[:min_idx] + [parts[min_idx] + parts[min_idx + 1]] + parts[min_idx + 2:]
    return parts


def recover_merges(mergeable_ranks):
    """
    Recover the ordered merge table from the flat mergeable_ranks mapping.
    For each multi-byte token, run BPE on it (up to but not including its own rank)
    to find the two children that were merged to create it.
    """
    merges = {}
    for token, rank in sorted(mergeable_ranks.items(), key=lambda x: x[1]):
        if len(token) == 1:
            continue  # skip single-byte tokens
        pair = tuple(bpe(mergeable_ranks, token, max_rank=rank))
        assert len(pair) == 2, (
            f"Expected 2 parts for token {token.hex()} (rank {rank}), "
            f"got {len(pair)}: {[p.hex() for p in pair]}"
        )
        ix0 = mergeable_ranks[pair[0]]
        ix1 = mergeable_ranks[pair[1]]
        merges[(ix0, ix1)] = rank
    return merges


merges = recover_merges(mergeable_ranks)
print(f"Recovered {len(merges)} merges")

# ---- Step 4: Build vocab in shuffled rank space ----

vocab = {rank: bytes([rank]) for rank in range(256)}
for (p0, p1), idx in sorted(merges.items(), key=lambda x: x[1]):
    vocab[idx] = vocab[p0] + vocab[p1]

# ---- Step 5: Detect regex pattern ----

import regex as re

GPT2_SPLIT_PATTERN = r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
GPT4_SPLIT_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""

candidate_patterns = [
    ("gpt4", GPT4_SPLIT_PATTERN),
    ("gpt2", GPT2_SPLIT_PATTERN),
    ("none", None),
]


def get_stats(ids, counts=None):
    counts = {} if counts is None else counts
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def merge_ids(ids, pair, idx):
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


def encode_chunk(text_bytes, merges, byte_shuffle):
    ids = [byte_shuffle[b] for b in text_bytes]
    while len(ids) >= 2:
        stats = get_stats(ids)
        pair = min(stats, key=lambda p: merges.get(p, float("inf")))
        if pair not in merges:
            break
        idx = merges[pair]
        ids = merge_ids(ids, pair, idx)
    return ids


def try_encode(text, pattern, merges, byte_shuffle):
    if not text:
        return []
    if pattern is None:
        return encode_chunk(text.encode("utf-8"), merges, byte_shuffle)
    compiled = re.compile(pattern)
    chunks = re.findall(compiled, text)
    all_ids = []
    for chunk in chunks:
        chunk_bytes = chunk.encode("utf-8")
        ids = encode_chunk(chunk_bytes, merges, byte_shuffle)
        all_ids.extend(ids)
    return all_ids


# Load test cases
with open('/app/test_cases.json') as f:
    test_cases = json.load(f)

detected_pattern = None
detected_pattern_name = None

for name, pattern in candidate_patterns:
    try:
        all_match = True
        for case in test_cases:
            result = try_encode(case['text'], pattern, merges, byte_shuffle)
            if result != case['expected_ids']:
                all_match = False
                break
        if all_match:
            detected_pattern = pattern
            detected_pattern_name = name
            break
    except Exception as e:
        print(f"  Pattern {name} failed with error: {e}")
        continue

if detected_pattern_name is None:
    print("ERROR: Could not detect regex pattern!")
    sys.exit(1)

print(f"Detected regex pattern: {detected_pattern_name}")

# ---- Step 6: Write tokenizer_data.json ----

tokenizer_data = {
    "merges": {f"{k[0]},{k[1]}": v for k, v in merges.items()},
    "byte_shuffle": {str(k): v for k, v in byte_shuffle.items()},
    "inverse_byte_shuffle": {str(k): v for k, v in inverse_byte_shuffle.items()},
    "pattern": detected_pattern,
}

with open('/app/tokenizer_data.json', 'w') as f:
    json.dump(tokenizer_data, f)

# ---- Step 7: Write tokenizer.py ----

tokenizer_code = '''"""
Recovered BPE tokenizer.
Implements encode(text) -> list[int] and decode(ids) -> str.
"""
import json
import regex as re

# Load recovered tokenizer data
with open('/app/tokenizer_data.json') as _f:
    _data = json.load(_f)

_merges = {tuple(int(x) for x in k.split(',')): v for k, v in _data['merges'].items()}
_byte_shuffle = {int(k): v for k, v in _data['byte_shuffle'].items()}
_inverse_byte_shuffle = {int(k): v for k, v in _data['inverse_byte_shuffle'].items()}
_pattern = _data['pattern']
_compiled_pattern = re.compile(_pattern) if _pattern else None

# Build vocab in shuffled rank space
_vocab = {rank: bytes([rank]) for rank in range(256)}
for (p0, p1), idx in sorted(_merges.items(), key=lambda x: x[1]):
    _vocab[idx] = _vocab[p0] + _vocab[p1]


def _get_stats(ids):
    counts = {}
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def _merge(ids, pair, idx):
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


def _encode_chunk(text_bytes):
    ids = [_byte_shuffle[b] for b in text_bytes]
    while len(ids) >= 2:
        stats = _get_stats(ids)
        pair = min(stats, key=lambda p: _merges.get(p, float("inf")))
        if pair not in _merges:
            break
        idx = _merges[pair]
        ids = _merge(ids, pair, idx)
    return ids


def encode(text):
    """Encode a string into a list of token IDs."""
    if not text:
        return []
    if _compiled_pattern is None:
        return _encode_chunk(text.encode("utf-8"))
    chunks = re.findall(_compiled_pattern, text)
    all_ids = []
    for chunk in chunks:
        chunk_bytes = chunk.encode("utf-8")
        ids = _encode_chunk(chunk_bytes)
        all_ids.extend(ids)
    return all_ids


def decode(ids):
    """Decode a list of token IDs back into a string."""
    if not ids:
        return ""
    text_bytes = b"".join(_vocab[idx] for idx in ids)
    raw_bytes = bytes(_inverse_byte_shuffle[b] for b in text_bytes)
    return raw_bytes.decode("utf-8", errors="replace")
'''

with open('/app/tokenizer.py', 'w') as f:
    f.write(tokenizer_code)

print("Wrote /app/tokenizer.py")

# ---- Step 8: Verify ----

# Re-import and verify
sys.path.insert(0, '/app')
import importlib
if 'tokenizer' in sys.modules:
    importlib.reload(sys.modules['tokenizer'])
else:
    import tokenizer

for case in test_cases:
    result = tokenizer.encode(case['text'])
    expected = case['expected_ids']
    assert result == expected, (
        f"VERIFY FAIL: encode({case['text']!r})\n"
        f"  got:      {result}\n"
        f"  expected: {expected}"
    )
    if case['text']:
        decoded = tokenizer.decode(expected)
        assert decoded == case['text'], (
            f"VERIFY FAIL: decode({expected})\n"
            f"  got:      {decoded!r}\n"
            f"  expected: {case['text']!r}"
        )

print("All verifications passed!")
