"""BM25 scoring module."""

import math


class BM25Scorer:
    """Computes BM25 relevance scores for term-document pairs."""

    def __init__(self, k1, b, num_docs):
        self.k1 = k1
        self.b = b
        self.num_docs = num_docs

    def idf(self, df):
        """Compute inverse document frequency for a term."""
        n = self.num_docs
        return math.log(n / df)

    def score(self, tf, df, dl, avgdl):
        """Compute BM25 score for a single term-document-field combination."""
        if df == 0 or tf == 0:
            return 0.0

        idf_val = self.idf(df)

        tf_norm = (tf * (self.k1 + 1.0)) / (
            tf + self.k1 * (1.0 - self.b + self.b * dl / avgdl)
        )

        return idf_val * tf_norm
