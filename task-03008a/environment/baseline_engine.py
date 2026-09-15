"""BM25 Search Engine — Baseline Implementation"""
import json
import math
from collections import Counter, defaultdict


class SearchEngine:
    def __init__(self):
        self.k1 = 1.2
        self.b = 0.75
        self.N = 0
        self.avgdl = 0.0
        self.doc_lengths = []
        self.index = {}
        self._idf_cache = {}
        self._stats = {}

    def build_index(self, corpus_path):
        raw = defaultdict(list)
        self.doc_lengths = []
        with open(corpus_path) as f:
            for line in f:
                doc = json.loads(line)
                doc_id = doc["id"]
                tokens = doc["text"].lower().split()
                while doc_id >= len(self.doc_lengths):
                    self.doc_lengths.append(0)
                self.doc_lengths[doc_id] = len(tokens)
                for term, cnt in Counter(tokens).items():
                    raw[term].append((doc_id, cnt))
        self.N = len(self.doc_lengths)
        self.avgdl = sum(self.doc_lengths) / self.N if self.N else 0.0
        for term, postings in raw.items():
            postings.sort()
            self.index[term] = postings
        for term in self.index:
            df = len(self.index[term])
            self._idf_cache[term] = math.log(
                (self.N - df + 0.5) / (df + 0.5) + 1.0
            )

    def _score(self, term, doc_id, tf):
        idf = self._idf_cache.get(term, 0.0)
        dl = self.doc_lengths[doc_id]
        num = tf * (self.k1 + 1)
        den = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        return idf * num / den

    def search(self, query, top_k=10):
        terms = list(dict.fromkeys(query.lower().split()))
        terms = [t for t in terms if t in self.index]
        if not terms:
            self._stats = {"postings_scored": 0}
            return []
        scored = 0
        doc_scores = defaultdict(float)
        for t in terms:
            for doc_id, tf in self.index[t]:
                s = self._score(t, doc_id, tf)
                if s > 0:
                    doc_scores[doc_id] += s
                    scored += 1
        self._stats = {"postings_scored": scored}
        results = sorted(doc_scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]
        return results

    def get_search_stats(self):
        return dict(self._stats)
