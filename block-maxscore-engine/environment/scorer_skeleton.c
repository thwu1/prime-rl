/*
 * Block BM25 Scorer — Native scoring library for the search engine.
 * Implement the functions below and compile into /app/libscorer.so.
 *
 * Compile: gcc -O2 -shared -fPIC -o /app/libscorer.so /app/scorer.c -lm
 *
 */

/*
 * Compute BM25 scores for a block of postings.
 *
 * Parameters:
 *   tfs        - array of term frequencies (length: count)
 *   doc_lens   - array of document lengths (length: count)
 *   count      - number of postings in this block
 *   idf        - pre-computed inverse document frequency for the term
 *   avgdl      - average document length across the corpus
 *   k1         - BM25 k1 parameter (1.2)
 *   b          - BM25 b parameter (0.75)
 *   scores_out - output array for computed BM25 scores (length: count)
 *
 * Returns: maximum score found in the block
 *
 * BM25 formula per posting:
 *   score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
 */
double bm25_score_block(const int* tfs, const int* doc_lens, int count,
                        double idf, double avgdl, double k1, double b,
                        double* scores_out) {
    /* TODO: implement */
    return 0.0;
}

/*
 * Binary search in a sorted array of document IDs.
 *
 * Find the first element in doc_ids[start..count-1] that is >= target.
 *
 * Parameters:
 *   doc_ids - sorted (ascending) array of document IDs (length: count)
 *   count   - total number of elements in the array
 *   start   - index to begin searching from (inclusive)
 *   target  - the document ID to search for
 *
 * Returns: index of first element >= target, or -1 if no such element exists
 */
int advance_to_target(const int* doc_ids, int count, int start, int target) {
    /* TODO: implement */
    return -1;
}
