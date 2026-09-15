#!/usr/bin/env python3
"""Generate deterministic input data for the wavelet tree range query engine task."""
import random
import os

os.makedirs('/app', exist_ok=True)

# Integer sequence: 50,000 values in [0, 511]
random.seed(42)
n = 50000
max_val = 511
sequence = [random.randint(0, max_val) for _ in range(n)]
with open('/app/sequence.txt', 'w') as f:
    f.write(' '.join(map(str, sequence)) + '\n')

# Text corpus: 30,000 lowercase letters and spaces
random.seed(1337)
alphabet = 'abcdefghijklmnopqrstuvwxyz '
corpus = ''.join(random.choice(alphabet) for _ in range(30000))
with open('/app/corpus.txt', 'w') as f:
    f.write(corpus)

# Range queries over integer sequence (28 total)
range_queries = [
    # QUANTILE l r k  (8 queries, indices 0-7)
    "QUANTILE 0 10000 0",
    "QUANTILE 0 10000 4999",
    "QUANTILE 0 10000 9999",
    "QUANTILE 20000 30000 100",
    "QUANTILE 0 50000 24999",
    "QUANTILE 40000 50000 0",
    "QUANTILE 10000 20000 5000",
    "QUANTILE 0 50000 49999",
    # DISTINCT l r  (5 queries, indices 8-12)
    "DISTINCT 0 100",
    "DISTINCT 0 10000",
    "DISTINCT 0 50000",
    "DISTINCT 25000 25010",
    "DISTINCT 10000 40000",
    # TOPFREQ l r  (5 queries, indices 13-17)
    "TOPFREQ 0 1000",
    "TOPFREQ 0 50000",
    "TOPFREQ 20000 30000",
    "TOPFREQ 0 100",
    "TOPFREQ 49000 50000",
    # PREVVAL l r v  (5 queries, indices 18-22)
    "PREVVAL 0 10000 256",
    "PREVVAL 0 50000 0",
    "PREVVAL 0 50000 511",
    "PREVVAL 0 100 5",
    "PREVVAL 40000 50000 300",
    # NEXTVAL l r v  (5 queries, indices 23-27)
    "NEXTVAL 0 10000 256",
    "NEXTVAL 0 50000 511",
    "NEXTVAL 0 50000 0",
    "NEXTVAL 0 100 500",
    "NEXTVAL 40000 50000 600",
]
with open('/app/range_queries.txt', 'w') as f:
    for q in range_queries:
        f.write(q + '\n')

# Text queries (13 total: 8 COUNT + 5 LOCATE)
text_queries = [
    "COUNT the",
    "COUNT abc",
    "COUNT a",
    "COUNT zz",
    "COUNT abcde",
    "COUNT mn",
    "COUNT xyz",
    "COUNT aa",
    "LOCATE the 10",
    "LOCATE abc 10",
    "LOCATE a 20",
    "LOCATE zz 10",
    "LOCATE mn 15",
]
with open('/app/text_queries.txt', 'w') as f:
    for q in text_queries:
        f.write(q + '\n')
