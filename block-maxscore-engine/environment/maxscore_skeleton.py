"""
Block-Max MAXSCORE Search Engine

Implement a rank-safe BM25 search engine using the block-max MAXSCORE algorithm.
See /app/bm25.py for the BM25 scoring functions and /app/reference.py for the
exhaustive reference implementation that your results must match exactly.

Required exports:
  - build_index(docs_path, stats_path, block_size=128) -> index object
  - search(index, query_terms, k) -> [(doc_id, score), ...]

The MAXSCORE algorithm:
  1. Sort query terms by ascending global max BM25 score.
  2. Partition into essential (high max-score) and non-essential (low max-score)
     based on the current heap threshold.
  3. Use only essential terms to find candidate documents.
  4. For each candidate, compute the full BM25 score using all terms.
  5. Update the top-k heap and re-partition as the threshold changes.

Block-max enhancement:
  - Divide each posting list into fixed-size blocks (~128 postings).
  - Annotate each block with the maximum BM25 score of any posting in it.
  - Use block-max scores for tighter upper-bound estimates, enabling
    entire blocks to be skipped when they cannot contribute to the top-k.
"""


def build_index(docs_path, stats_path, block_size=128):
    """Build a block-max inverted index from the corpus.

    Args:
        docs_path: Path to documents.jsonl
        stats_path: Path to stats.json
        block_size: Number of postings per block (default 128)

    Returns:
        An index object that can be passed to search()
    """
    raise NotImplementedError("Implement block-max index construction")


def search(index, query_terms, k):
    """Search the index using block-max MAXSCORE.

    Args:
        index: Index object built by build_index()
        query_terms: List of query term strings
        k: Number of top results to return

    Returns:
        List of (doc_id, score) tuples, sorted by descending score,
        then ascending doc_id for ties. Must be rank-safe: identical
        results to the exhaustive scorer in /app/reference.py.
    """
    raise NotImplementedError("Implement block-max MAXSCORE search")
