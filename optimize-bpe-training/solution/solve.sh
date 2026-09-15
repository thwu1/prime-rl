#!/bin/bash

# Copy optimized implementation into place
cp /solution/fast_bpe_solution.py /app/fast_bpe.py

# Verify correctness via computation
python3 -c "
import sys
sys.path.insert(0, '/app')
from fast_bpe import FastBPETrainer
from naive_bpe import NaiveBPETrainer

# Verify merge identity on small corpus
text = 'aaabdaaabac' * 50
naive = NaiveBPETrainer()
fast = FastBPETrainer()
nm = naive.train(text, 15)
fm = fast.train(text, 15)
assert nm == fm, f'Merge mismatch: {nm} vs {fm}'

# Verify overlapping pair handling
text2 = 'aaaaa ' * 50
naive2 = NaiveBPETrainer()
fast2 = FastBPETrainer()
nm2 = naive2.train(text2, 5)
fm2 = fast2.train(text2, 5)
assert nm2 == fm2, f'Overlap mismatch: {nm2} vs {fm2}'

# Verify encode/decode roundtrip
assert fast2.decode(fast2.encode('aaaaa')) == 'aaaaa'

# Verify performance on full corpus
import time
with open('/app/data/corpus.txt') as f:
    corpus = f.read()
fast3 = FastBPETrainer()
t0 = time.time()
fast3.train(corpus, 500)
elapsed = time.time() - t0
assert elapsed < 30, f'Too slow: {elapsed:.1f}s'

print(f'Solution verified: all checks pass (perf: {elapsed:.1f}s)')
"
