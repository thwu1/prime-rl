#!/usr/bin/env bash

cp /solution/search_engine_impl.py /app/search_engine.py

python3 -c "
import sys
sys.path.insert(0, '/app')
from search_engine import SearchEngine

eng = SearchEngine()
eng.build_index('/app/corpus.jsonl')

# Smoke test: correctness and efficiency
r1 = eng.search('the rare42', top_k=10)
stats = eng.get_search_stats()
print(f'Results: {len(r1)} docs, postings scored: {stats[\"postings_scored\"]}')
print('Solution installed successfully.')
"
