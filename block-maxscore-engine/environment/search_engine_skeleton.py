"""
Rank-Safe BM25 Search Engine with Native Scoring

Requirements:
- Compile /app/scorer.c into /app/libscorer.so and load it via ctypes
- Use sqlite3 for index persistence at /app/index.db
- Implement an efficient search algorithm for top-k retrieval
- Expose Python API and CLI

See /app/bm25.py for the BM25 scoring formula reference.
See /app/reference.py for the exhaustive scorer your results must match.
See /app/scorer.c for the C library function signatures.
"""


def build_index(docs_path, stats_path, block_size=128):
    """Build an index from the corpus using the C scoring library.

    Must load /app/libscorer.so via ctypes and call bm25_score_block
    for computing block-level BM25 scores during construction.

    Args:
        docs_path: Path to documents.jsonl
        stats_path: Path to stats.json
        block_size: Number of postings per block (default 128)

    Returns:
        A custom index object (not a raw dict, list, tuple, or set)
    """
    raise NotImplementedError("Implement index construction")


def save_index(index, db_path):
    """Persist index to a SQLite database.

    Required tables: corpus_stats, terms, blocks, doc_lengths.
    """
    raise NotImplementedError("Implement SQLite persistence")


def load_index(db_path):
    """Load index from a SQLite database."""
    raise NotImplementedError("Implement SQLite loading")


def search(index, query_terms, k):
    """Return top-k results matching the reference scorer exactly.

    Args:
        index: Index object from build_index()
        query_terms: List of term strings (deduplicate if repeated)
        k: Number of results to return

    Returns:
        [(doc_id, score), ...] sorted by descending score, ascending
        doc_id for ties. Must match reference.exhaustive_search().
    """
    raise NotImplementedError("Implement search")


if __name__ == "__main__":
    raise NotImplementedError("Implement CLI: build and query subcommands")
