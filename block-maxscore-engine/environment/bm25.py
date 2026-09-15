"""BM25 scoring functions.

Parameters: k1=1.2, b=0.75, Lucene-style IDF.
These are the authoritative scoring functions for this task.
"""
import math

K1 = 1.2
B = 0.75


def idf(df, N):
    """Inverse document frequency (Lucene-style log(1 + ...))."""
    return math.log(1.0 + (N - df + 0.5) / (df + 0.5))


def bm25_term_score(tf, df, N, dl, avgdl):
    """BM25 score contribution of a single term occurrence in a document.

    Args:
        tf: term frequency in the document
        df: document frequency (number of docs containing this term)
        N: total number of documents in the corpus
        dl: document length (number of terms in the document)
        avgdl: average document length across the corpus

    Returns:
        float: BM25 score contribution
    """
    idf_val = idf(df, N)
    tf_val = (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * dl / avgdl))
    return idf_val * tf_val
