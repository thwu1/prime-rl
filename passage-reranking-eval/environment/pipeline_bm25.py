"""Okapi BM25 scoring."""

import math
from tokenizer import tokenize_doc


class BM25Scorer:
    def __init__(self, index, k1=1.2, b=0.75):
        self.index = index
        self.k1 = k1
        self.b = b

    def idf(self, term):
        """Compute inverse document frequency for a term."""
        n = self.index.df.get(term, 0)
        return math.log((self.index.N - n + 0.5) / (n + 0.5) + 1.0)

    def score(self, query_tokens, passage_text, pid):
        """Score a passage against pre-tokenized query terms using BM25."""
        p_tokens = tokenize_doc(passage_text)
        dl = self.index.doc_lens.get(pid, len(p_tokens))
        avg_dl = self.index.avg_dl

        tf_map = {}
        for t in p_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        total = 0.0
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf_val = self.idf(qt)
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * avg_dl / dl)
            )
            total += idf_val * tf_norm

        return total
