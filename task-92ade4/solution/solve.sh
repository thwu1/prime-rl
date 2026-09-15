#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/bm25_engine.py /app/bm25_engine.py

# Quick smoke test
python3 -c "
import sys, json
sys.path.insert(0, '/app')
from bm25_engine import BM25Engine

with open('/app/corpus.jsonl') as f:
    corpus = [json.loads(l)['text'] for l in f]
with open('/app/queries.json') as f:
    queries = json.load(f)

for method in ['robertson', 'lucene', 'atire', 'bm25l', 'bm25+']:
    engine = BM25Engine(method=method)
    engine.index(corpus)
    idx, sc = engine.retrieve(queries[:3], k=5)
    print(f'{method}: top-3 scores for q0 = {sc[0][:3]}')
print('All variants OK')
"
