"""BM25 Search Engine — Optimized Implementation

Implements a dynamic pruning strategy over a block-structured inverted index
to achieve rank-safe top-k retrieval with significantly fewer posting evaluations
than exhaustive scoring.
"""

import json
import math
import heapq
from collections import Counter, defaultdict


class SearchEngine:

    def __init__(self):
        self.k1 = 1.2
        self.b = 0.75
        self.N = 0
        self.avgdl = 0.0
        self.doc_lengths = []
        self.index = {}
        self.global_max = {}
        self._stats = {}

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def build_index(self, corpus_path, block_size=128):
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

        idf_map = {}
        for term, postings in raw.items():
            df = len(postings)
            idf_map[term] = math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)

        for term, postings in raw.items():
            postings.sort()
            idf = idf_map[term]
            blocks = []
            gmax = 0.0

            for start in range(0, len(postings), block_size):
                chunk = postings[start:start + block_size]
                bmax = 0.0
                bpostings = []
                for doc_id, tf in chunk:
                    dl = self.doc_lengths[doc_id]
                    score = idf * (tf * (self.k1 + 1)) / (
                        tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                    )
                    bpostings.append((doc_id, score))
                    if score > bmax:
                        bmax = score
                if bmax > gmax:
                    gmax = bmax
                blocks.append({
                    "postings": bpostings,
                    "max_score": bmax,
                    "min_doc": bpostings[0][0],
                    "max_doc": bpostings[-1][0],
                })

            self.index[term] = blocks
            self.global_max[term] = gmax

    # ------------------------------------------------------------------
    # Score lookup via binary search
    # ------------------------------------------------------------------

    def _lookup_score(self, term, doc_id):
        blocks = self.index.get(term)
        if blocks is None:
            return 0.0
        lo, hi = 0, len(blocks)
        while lo < hi:
            mid = (lo + hi) // 2
            if blocks[mid]["max_doc"] < doc_id:
                lo = mid + 1
            else:
                hi = mid
        if lo >= len(blocks) or blocks[lo]["min_doc"] > doc_id:
            return 0.0
        postings = blocks[lo]["postings"]
        lo2, hi2 = 0, len(postings)
        while lo2 < hi2:
            mid = (lo2 + hi2) // 2
            if postings[mid][0] < doc_id:
                lo2 = mid + 1
            else:
                hi2 = mid
        if lo2 < len(postings) and postings[lo2][0] == doc_id:
            return postings[lo2][1]
        return 0.0

    # ------------------------------------------------------------------
    # Optimized search with dynamic pruning
    # ------------------------------------------------------------------

    def search(self, query, top_k=10):
        terms = list(dict.fromkeys(query.lower().split()))
        terms = [t for t in terms if t in self.index]
        if not terms:
            self._stats = {"postings_scored": 0}
            return []

        n = len(terms)

        # Sort terms by ascending global max score
        terms.sort(key=lambda t: self.global_max[t])
        max_scores = [self.global_max[t] for t in terms]

        # Cumulative max scores: cum[i] = sum(max_scores[0..i])
        cum = []
        s = 0.0
        for ms in max_scores:
            s += ms
            cum.append(s)

        # Block iterators per term
        bi = [0] * n
        ei = [0] * n
        blocks_list = [self.index[t] for t in terms]

        def exhausted(i):
            return bi[i] >= len(blocks_list[i])

        def cur_doc(i):
            return blocks_list[i][bi[i]]["postings"][ei[i]][0]

        def cur_block_max(i):
            return blocks_list[i][bi[i]]["max_score"]

        def advance(i):
            ei[i] += 1
            if ei[i] >= len(blocks_list[i][bi[i]]["postings"]):
                bi[i] += 1
                ei[i] = 0

        heap = []
        threshold = 0.0
        ess = 0
        scored = 0
        skipped = 0

        while True:
            # Advance the partition boundary
            while ess < n and cum[ess] < threshold:
                ess += 1
            if ess >= n:
                break

            # Block-level skipping for terms in the active partition
            any_alive = False
            for i in range(ess, n):
                while not exhausted(i):
                    bms = cur_block_max(i)
                    upper = bms
                    for j in range(ess, n):
                        if j != i:
                            upper += max_scores[j]
                    if ess > 0:
                        upper += cum[ess - 1]
                    if upper < threshold:
                        skipped += 1
                        bi[i] += 1
                        ei[i] = 0
                    else:
                        break
                if not exhausted(i):
                    any_alive = True

            if not any_alive:
                break

            # Find minimum doc_id among active terms
            min_doc = None
            for i in range(ess, n):
                if not exhausted(i):
                    d = cur_doc(i)
                    if min_doc is None or d < min_doc:
                        min_doc = d
            if min_doc is None:
                break

            # Score candidate using ALL terms
            score = 0.0
            for i in range(n):
                if i >= ess and not exhausted(i) and cur_doc(i) == min_doc:
                    sc = blocks_list[i][bi[i]]["postings"][ei[i]][1]
                else:
                    sc = self._lookup_score(terms[i], min_doc)
                if sc > 0:
                    score += sc
                    scored += 1

            # Update top-k heap
            item = (score, -min_doc)
            if len(heap) < top_k:
                heapq.heappush(heap, item)
                if len(heap) == top_k:
                    threshold = heap[0][0]
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
                threshold = heap[0][0]

            # Advance active iterators past min_doc
            for i in range(ess, n):
                if not exhausted(i) and cur_doc(i) == min_doc:
                    advance(i)

        self._stats = {"postings_scored": scored, "blocks_skipped": skipped}

        results = [(-neg_id, sc) for sc, neg_id in sorted(heap, reverse=True)]
        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_search_stats(self):
        return dict(self._stats)
