#!/bin/bash

cp /solution/fast_bpe.py /app/fast_bpe.py

# Verify the implementation produces correct results
python3 -c "
import sys, json, time
sys.path.insert(0, '/app')
from fast_bpe import FastBPETrainer
from reference import NaiveBPETrainer

# Quick correctness check on small input
naive = NaiveBPETrainer()
fast = FastBPETrainer()
for text in ['aaabdaaabac', 'hello world', 'aaa', 'aaaa', 'ababab']:
    for nm in [3, 5, 10]:
        expected = naive.train(text, nm)
        actual = fast.train(text, nm)
        assert actual == expected, f'FAIL on {text!r} nm={nm}'
print('Small correctness checks passed')

# Medium corpus
with open('/app/corpus_medium.txt') as f:
    text = f.read()
with open('/app/reference_merges_medium.json') as f:
    ref = {tuple(map(int, k.split(','))): v for k, v in json.load(f).items()}
merges = fast.train(text, 500)
assert merges == ref, 'Medium corpus mismatch'
print('Medium corpus check passed')

# Large corpus with timing
with open('/app/corpus_large.txt') as f:
    text = f.read()
with open('/app/reference_merges_large.json') as f:
    ref = {tuple(map(int, k.split(','))): v for k, v in json.load(f).items()}
start = time.time()
merges = fast.train(text, 2000)
elapsed = time.time() - start
assert merges == ref, 'Large corpus mismatch'
print(f'Large corpus check passed in {elapsed:.1f}s')
"
