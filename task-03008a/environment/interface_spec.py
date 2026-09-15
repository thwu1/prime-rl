"""
Block-Max MAXSCORE Search Engine — Interface Specification

Implement a class `BlockMaxSearchEngine` in /app/search_engine.py with the methods below.
Refer to /app/bm25_spec.md for the exact BM25 scoring formula and parameters.

class BlockMaxSearchEngine:

    def build_index(self, corpus_path: str, block_size: int = 128) -> None:
        '''Build a block-structured inverted index from a JSONL corpus.

        Each posting list must be divided into fixed-size blocks of at most
        `block_size` postings, sorted by document ID. Each block must store
        a pre-computed maximum BM25 score (the highest score any posting in
        that block can achieve for its term). These block-max scores enable
        the block-max MAXSCORE algorithm to skip entire blocks that cannot
        contribute to the top-k results.

        Parameters:
            corpus_path: path to a JSONL file where each line is
                         {"id": int, "text": str}
            block_size:  maximum number of postings per block (default 128)
        '''

    def search_exhaustive(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        '''Score every document against the query using BM25 and return the
        top-k results.

        Returns a list of (doc_id, score) tuples sorted by score descending,
        then doc_id ascending for ties. Only include documents with score > 0.
        Returns at most top_k results.

        This method must also populate stats accessible via get_last_search_stats()
        with at least: {'postings_scored': <int>, 'blocks_skipped': 0}
        '''

    def search_bmm(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        '''Block-max MAXSCORE search.

        Must return IDENTICAL results to search_exhaustive (rank-safe).
        Must implement the MAXSCORE algorithm:
          1. Sort query terms by ascending global max score.
          2. Partition terms into essential (high max-score) and non-essential
             (low max-score) based on the current heap threshold.
          3. Only iterate posting lists of essential terms to find candidates.
          4. Score each candidate using ALL terms (essential + non-essential).
          5. As the heap threshold rises, re-partition: terms whose cumulative
             max score falls below the threshold become non-essential.
          6. Use block-level max scores to skip blocks of essential terms
             that cannot contribute any candidate above the threshold.

        This method must also populate stats accessible via get_last_search_stats()
        with at least: {'postings_scored': <int>, 'blocks_skipped': <int>}
        where postings_scored counts (term, doc) BM25 score computations
        that yielded a nonzero score.
        '''

    def get_last_search_stats(self) -> dict:
        '''Return statistics from the most recent search call.

        Must include at least:
          - 'postings_scored': int  -- number of (term, doc) pairs where a
                                      nonzero BM25 score was computed
          - 'blocks_skipped': int  -- number of posting-list blocks skipped
                                      by block-max pruning (0 for exhaustive)
        '''
"""
