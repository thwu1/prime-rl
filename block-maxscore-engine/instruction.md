Build a rank-safe BM25 search engine over a pre-generated 20,000-document corpus at `/app/data/`. The engine must produce results **identical** to the provided exhaustive reference scorer, use a compiled C shared library for BM25 scoring computations loaded via Python `ctypes`, store its inverted index in a SQLite database, and expose both a Python API and a command-line interface.

## Environment

- `/app/data/documents.jsonl` — 20,000 documents with Zipfian term distributions (each line: `{"id": int, "terms": [str, ...]}`)
- `/app/data/stats.json` — corpus statistics (`num_docs`, `avg_doc_length`)
- `/app/bm25.py` — BM25 scoring functions (k1=1.2, b=0.75, Lucene-style IDF: `log(1 + (N - df + 0.5) / (df + 0.5))`)
- `/app/reference.py` — exhaustive BM25 scorer (do not modify)
- `/app/search_engine.py` — Python skeleton with required function signatures
- `/app/scorer.c` — C skeleton with required function signatures for the native scoring library

## Deliverable

### C Shared Library

Implement `/app/scorer.c` and compile it into `/app/libscorer.so`. The library must export:

- `double bm25_score_block(const int* tfs, const int* doc_lens, int count, double idf, double avgdl, double k1, double b, double* scores_out)` — compute BM25 scores for a batch of postings; return the maximum score in the block
- `int advance_to_target(const int* doc_ids, int count, int start, int target)` — binary search in sorted doc_ids for first element >= target; return index or -1 if none

### Python Search Engine

Implement `/app/search_engine.py`:

- `build_index(docs_path, stats_path, block_size=128)` → custom index object (not a raw `dict`, `list`, `tuple`, or `set`). Must use the C library via `ctypes` for BM25 block scoring during construction.
- `search(index, query_terms, k)` → `[(doc_id, score), ...]` sorted by descending score, then ascending doc_id for ties within 1e-9 tolerance
- `save_index(index, db_path)` → persist the index to a SQLite database
- `load_index(db_path)` → restore the index from a SQLite database

### SQLite Index

The persisted index at `/app/index.db` must contain tables: `corpus_stats`, `terms`, `blocks`, `doc_lengths`.

### CLI

**Build**: `python3 /app/search_engine.py build [--block-size 128]` — constructs the index and persists it to `/app/index.db`

**Query**: `python3 /app/search_engine.py query --index /app/index.db -k 10 term1 term2 ...` — prints a JSON array of `[doc_id, score]` pairs to stdout

## Constraints

- **Rank-safe**: `search()` must return the same `(doc_id, score)` pairs in the same order as `reference.py:exhaustive_search()`. Scores must match within 1e-6.
- **Native scoring**: BM25 block scoring must use the C shared library via `ctypes` — not a pure Python reimplementation of block scoring.
- **Duplicate terms**: deduplicate — `["t1", "t1", "t2"]` must produce the same results as `["t1", "t2"]`.
- **Edge cases**: empty query → `[]`, non-existent terms → `[]`, k=1 → single best result, large k → all matches.
- **Independence**: `search()` must not call or delegate to `reference.exhaustive_search()`.
- **Performance**: a 15-term query must complete within 5x the wall-clock time of the exhaustive scorer.