/*
 * Block BM25 Scorer — Native scoring library.
 *
 */

double bm25_score_block(const int* tfs, const int* doc_lens, int count,
                        double idf, double avgdl, double k1, double b,
                        double* scores_out) {
    double max_score = 0.0;
    for (int i = 0; i < count; i++) {
        double tf = (double)tfs[i];
        double dl = (double)doc_lens[i];
        double score = idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl));
        scores_out[i] = score;
        if (score > max_score) max_score = score;
    }
    return max_score;
}

int advance_to_target(const int* doc_ids, int count, int start, int target) {
    int lo = start, hi = count;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (doc_ids[mid] < target)
            lo = mid + 1;
        else
            hi = mid;
    }
    return (lo < count) ? lo : -1;
}
