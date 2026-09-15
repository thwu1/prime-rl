A corpus of 500 documents and 15 queries are pre-loaded at `/app/`. Build a standalone BM25 retrieval engine at `/app/bm25_engine.py` that produces **numerically identical** results to the `bm25s` Python library (v0.3.9, available via pip) across all five of its supported scoring variants: `robertson`, `lucene`, `atire`, `bm25l`, and `bm25+`.

## Data Files

- `/app/corpus.jsonl` — one JSON object per line, each with a `"text"` field
- `/app/queries.json` — array of query strings
- `/app/stopwords_en.json` — English stopwords list

## Required Interface

Expose a `BM25Engine` class at module level:

- `__init__(self, method, k1, b, delta)` — scoring variant and parameters
- `index(self, corpus_texts: List[str])` — build the retrieval index from raw text
- `retrieve(self, queries: List[str], k: int) -> Tuple[np.ndarray, np.ndarray]` — return `(doc_indices, scores)` of shape `(n_queries, k)`, descending by score

## Acceptance Criteria

- All per-document scores must match `bm25s` output within absolute tolerance of 1e-4 for every variant, query, and parameter combination tested
- Tokenization must produce token sequences identical to `bm25s` with English stopword filtering
- The module must NOT import, reference, or depend on `bm25s` in any way
- Verification covers all 5 variants with both default parameters (k1=1.5, b=0.75, delta=0.5) and non-default combinations, single-term queries, and retrieval depths from top-1 through full-corpus