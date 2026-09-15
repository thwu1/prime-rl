#!/usr/bin/env python3
"""Generate reference posting list data and dictionary/query workload."""
import struct
import json
import os
import random


def _min_bits(val):
    if val == 0:
        return 0
    return val.bit_length()


def bitpack_reference(doc_ids):
    """Reference (correct) bitpacking implementation."""
    if not doc_ids:
        return b""
    deltas = [doc_ids[0]]
    for i in range(1, len(doc_ids)):
        deltas.append(doc_ids[i] - doc_ids[i - 1])
    result = bytearray()
    result.extend(struct.pack('<I', len(doc_ids)))
    i = 0
    while i + 32 <= len(deltas):
        block = deltas[i:i + 32]
        bit_width = max(_min_bits(v) for v in block)
        result.append(bit_width)
        if bit_width > 0:
            total_bytes = 32 * bit_width // 8
            packed = bytearray(total_bytes)
            buf = 0
            bits = 0
            pos = 0
            mask = (1 << bit_width) - 1
            for val in block:
                buf |= (val & mask) << bits
                bits += bit_width
                while bits >= 8:
                    packed[pos] = buf & 0xFF
                    buf >>= 8
                    bits -= 8
                    pos += 1
            result.extend(packed)
        i += 32
    while i < len(deltas):
        result.extend(struct.pack('<I', deltas[i]))
        i += 1
    return bytes(result)


os.makedirs('/app/data', exist_ok=True)

# --- Reference binary posting lists ---

# 8-element list: all remainder, no full blocks
small = [1, 3, 7, 8, 13, 42, 100, 200]
with open('/app/data/postings_small.json', 'w') as f:
    json.dump(small, f)
with open('/app/data/postings_small.bin', 'wb') as f:
    f.write(bitpack_reference(small))

# 32-element list: exactly one full block, no remainder
consecutive = list(range(1, 33))
with open('/app/data/postings_block.json', 'w') as f:
    json.dump(consecutive, f)
with open('/app/data/postings_block.bin', 'wb') as f:
    f.write(bitpack_reference(consecutive))

# 40-element list: one full block + 8 remainder elements
mixed = [10, 20, 25, 30, 35, 40, 45, 50, 55, 60,
         65, 70, 75, 80, 85, 90, 95, 100, 110, 120,
         130, 140, 150, 200, 300, 400, 500, 600, 700, 800,
         900, 1000, 1500, 2000, 3000, 5000, 8000, 10000, 50000, 100000]
with open('/app/data/postings_mixed.json', 'w') as f:
    json.dump(mixed, f)
with open('/app/data/postings_mixed.bin', 'wb') as f:
    f.write(bitpack_reference(mixed))

# --- Dictionary and query workload ---

random.seed(42)
alphabet = 'abcdefghijklmnopqrstuvwxyz'
dictionary = set()

base_words = [
    "search", "engine", "index", "query", "fuzzy", "match", "distance",
    "levenshtein", "automaton", "state", "transition", "accept", "reject",
    "trie", "dictionary", "prefix", "suffix", "insert", "delete", "substitute",
    "posting", "document", "compress", "encode", "decode", "binary", "format",
    "block", "delta", "bitpack", "width", "header", "offset", "buffer",
    "algorithm", "optimize", "benchmark", "performance", "memory", "cache",
    "python", "struct", "integer", "string", "character", "vector", "tuple",
    "function", "method", "class", "module", "import", "return", "value",
    "apple", "banana", "cherry", "dragon", "eagle", "falcon", "grape",
    "hammer", "igloo", "jacket", "kernel", "lemon", "mango", "needle",
    "orange", "pepper", "quartz", "rabbit", "silver", "tiger", "umbrella",
    "violet", "walnut", "xenon", "yellow", "zebra", "anchor", "bridge",
    "castle", "desert", "empire", "forest", "garden", "harbor", "island",
    "jungle", "kitten", "lantern", "marble", "nectar", "orchid", "palace",
    "quiver", "rapids", "shelter", "temple", "utopia", "venture", "wraith",
]
dictionary.update(base_words)

while len(dictionary) < 3000:
    length = random.randint(3, 12)
    word = ''.join(random.choice(alphabet) for _ in range(length))
    dictionary.add(word)

dictionary = sorted(dictionary)
with open('/app/dictionary.txt', 'w') as f:
    for word in dictionary:
        f.write(word + '\n')

# Query workload: mix of exact matches and misspellings
random.seed(123)
queries = []
for _ in range(30):
    word = random.choice(dictionary)
    if random.random() < 0.4:
        queries.append(word)
    else:
        idx = random.randint(0, len(word) - 1)
        c = random.choice(alphabet)
        queries.append(word[:idx] + c + word[idx + 1:])

with open('/app/queries.txt', 'w') as f:
    for q in queries:
        f.write(q + '\n')
