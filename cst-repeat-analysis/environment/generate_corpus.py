#!/usr/bin/env python3
"""Generate a deterministic DNA corpus and query patterns for CST analysis."""
import random
import os

random.seed(314159265)

alphabet = ['A', 'C', 'G', 'T']
weights = {
    'A': [15, 30, 35, 20],
    'C': [30, 10, 25, 35],
    'G': [25, 35, 15, 25],
    'T': [20, 25, 30, 25],
}

n = 3000
text = ['A'] * n
for i in range(1, n):
    text[i] = random.choices(alphabet, weights=weights[text[i - 1]])[0]

# Insert specific motifs at fixed positions to create known repeat structure
motifs = [
    ("ACGTACGTACGT", [400, 1400, 2400]),
    ("GATTACAGATTACA", [700, 1900]),
    ("TATATATA", [1100, 2100]),
    ("CCCCGGGGAAAA", [1600, 2700]),
]

for motif, positions in motifs:
    for pos in positions:
        for j, c in enumerate(motif):
            if pos + j < n:
                text[pos + j] = c

text = ''.join(text)

os.makedirs('/app', exist_ok=True)
with open('/app/corpus.txt', 'w') as f:
    f.write(text)

queries = [
    "ACGT",
    "GATTACA",
    "TATATATA",
    "ACGTACGTACGT",
    "GATTACAGATTACA",
    "CCCCGGGG",
    "AAACCC",
    "GGGTT",
]
with open('/app/queries.txt', 'w') as f:
    for q in queries:
        f.write(q + '\n')
