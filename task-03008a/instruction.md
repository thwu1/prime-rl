`/app/search_engine.py` implements a BM25 search engine over a 50,000-document corpus (`/app/corpus.jsonl`). It returns correct ranked results but exhaustively scores every posting for every query term, making multi-term queries impractically slow.

Optimize the engine so `search(query, top_k)` returns **identical results** — same document IDs, scores (within 1e-6), and ordering — while evaluating far fewer postings. The corpus has highly skewed term frequencies that a well-chosen pruning strategy can exploit.

`/app/benchmark.py` profiles per-query posting counts. `/app/bm25_spec.md` specifies the scoring formula.

## Constraints

- Preserve the `SearchEngine` class API: `build_index(corpus_path)`, `search(query, top_k)`, `get_search_stats()` (must return `{"postings_scored": int}`)
- Rank-safe: output identical to exhaustive BM25 for all queries and top_k values
- Queries mixing high-frequency and low-frequency terms: < 40% of exhaustive posting evaluations
- 10+ term queries spanning diverse frequencies: < 50%
- Correct on single-term, no-match, and all-high-frequency queries