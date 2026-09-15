"""
Block-Max MAXSCORE Search Engine -- Complete Implementation

Implements a rank-safe BM25 search engine using the block-max MAXSCORE algorithm.
Posting lists are divided into fixed-size blocks, each annotated with the maximum
BM25 score achievable by any posting in that block. The MAXSCORE algorithm partitions
query terms into essential and non-essential sets based on the evolving heap threshold,
using essential terms to find candidate documents and block-max scores for
upper-bound filtering.

"""

import json
import math
import heapq
from collections import defaultdict

# BM25 parameters -- must match /app/bm25.py
K1 = 1.2
B = 0.75


def _idf(df, N):
    return math.log(1.0 + (N - df + 0.5) / (df + 0.5))


def _bm25(tf, idf_val, dl, avgdl):
    """BM25 term score given pre-computed IDF."""
    return idf_val * (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * dl / avgdl))


# ---------------------------------------------------------------------------
# Index data structures
# ---------------------------------------------------------------------------


class Block:
    """A fixed-size chunk of a posting list with its max BM25 score."""
    __slots__ = ["postings", "max_score"]

    def __init__(self, postings, max_score):
        self.postings = postings   # list of (doc_id, tf), sorted by doc_id
        self.max_score = max_score  # max BM25 score across all postings in block


class TermEntry:
    """Per-term index data: blocks, global max score, document frequency."""
    __slots__ = ["blocks", "global_max", "df", "idf_val"]

    def __init__(self, blocks, global_max, df, idf_val):
        self.blocks = blocks
        self.global_max = global_max
        self.df = df
        self.idf_val = idf_val


class Index:
    """Block-max inverted index."""

    def __init__(self):
        self.terms = {}        # str -> TermEntry
        self.doc_lengths = {}  # doc_id -> int
        self.N = 0
        self.avgdl = 0.0


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


def build_index(docs_path, stats_path, block_size=128):
    """Build a block-max inverted index from the corpus.

    Each term's posting list is sorted by doc_id and divided into blocks
    of *block_size* postings.  Every block is annotated with the maximum
    BM25 score of any posting within it.
    """
    idx = Index()

    with open(stats_path) as f:
        stats = json.load(f)
    idx.N = stats["num_docs"]
    idx.avgdl = stats["avg_doc_length"]

    # Pass 1: build raw posting lists
    raw = defaultdict(list)
    with open(docs_path) as f:
        for line in f:
            doc = json.loads(line)
            doc_id = doc["id"]
            terms = doc["terms"]
            idx.doc_lengths[doc_id] = len(terms)

            tf_map = defaultdict(int)
            for t in terms:
                tf_map[t] += 1
            for t, tf in tf_map.items():
                raw[t].append((doc_id, tf))

    # Pass 2: sort, compute IDF, build blocks with max scores
    for term, plist in raw.items():
        plist.sort()  # sort by doc_id
        df = len(plist)
        idf_val = _idf(df, idx.N)

        blocks = []
        global_max = 0.0

        for i in range(0, len(plist), block_size):
            bp = plist[i : i + block_size]
            bmax = 0.0
            for did, tf in bp:
                dl = idx.doc_lengths[did]
                s = _bm25(tf, idf_val, dl, idx.avgdl)
                if s > bmax:
                    bmax = s
            blocks.append(Block(bp, bmax))
            if bmax > global_max:
                global_max = bmax

        idx.terms[term] = TermEntry(blocks, global_max, df, idf_val)

    return idx


# ---------------------------------------------------------------------------
# Posting list iterator with block-max support
# ---------------------------------------------------------------------------


class _Iter:
    """Forward-only iterator over a term's posting list with block awareness."""
    __slots__ = ["blocks", "bi", "pi", "exhausted"]

    def __init__(self, term_entry):
        self.blocks = term_entry.blocks
        self.bi = 0   # current block index
        self.pi = 0   # position within current block
        self.exhausted = len(self.blocks) == 0

    def doc(self):
        """Current doc_id, or None if exhausted."""
        if self.exhausted:
            return None
        return self.blocks[self.bi].postings[self.pi][0]

    def posting(self):
        """Current (doc_id, tf) tuple."""
        return self.blocks[self.bi].postings[self.pi]

    def block_max(self):
        """Max BM25 score of the current block."""
        if self.exhausted:
            return 0.0
        return self.blocks[self.bi].max_score

    def advance_to(self, target):
        """Advance to first doc_id >= *target*.  Returns doc_id or None."""
        if self.exhausted:
            return None

        # Skip blocks whose last doc < target
        while self.bi < len(self.blocks):
            last = self.blocks[self.bi].postings[-1][0]
            if last >= target:
                break
            self.bi += 1
            self.pi = 0

        if self.bi >= len(self.blocks):
            self.exhausted = True
            return None

        # Binary search within the current block
        bp = self.blocks[self.bi].postings
        lo, hi = self.pi, len(bp)
        while lo < hi:
            mid = (lo + hi) >> 1
            if bp[mid][0] < target:
                lo = mid + 1
            else:
                hi = mid

        if lo >= len(bp):
            # target is past this block; advance to next
            self.bi += 1
            self.pi = 0
            if self.bi >= len(self.blocks):
                self.exhausted = True
                return None
            return self.blocks[self.bi].postings[0][0]

        self.pi = lo
        return bp[lo][0]

    def next_doc(self):
        """Advance to the next posting.  Returns doc_id or None."""
        if self.exhausted:
            return None
        self.pi += 1
        if self.pi >= len(self.blocks[self.bi].postings):
            self.bi += 1
            self.pi = 0
            if self.bi >= len(self.blocks):
                self.exhausted = True
                return None
        return self.blocks[self.bi].postings[self.pi][0]


# ---------------------------------------------------------------------------
# Block-max MAXSCORE search
# ---------------------------------------------------------------------------


def search(index, query_terms, k):
    """Query the index using the block-max MAXSCORE algorithm.

    Returns a list of (doc_id, score) tuples for the top-k results,
    sorted by descending score then ascending doc_id for ties.
    Rank-safe: produces identical results to exhaustive evaluation.
    """
    if k <= 0:
        return []

    # Deduplicate and filter to terms present in the index
    seen = set()
    terms = []
    for t in query_terms:
        if t not in seen and t in index.terms:
            seen.add(t)
            terms.append(t)
    if not terms:
        return []

    n = len(terms)
    N = index.N
    avgdl = index.avgdl

    # Sort terms by ascending global max score
    terms.sort(key=lambda t: index.terms[t].global_max)

    # Create iterators and cache per-term data
    iters = [_Iter(index.terms[t]) for t in terms]
    gmax = [index.terms[t].global_max for t in terms]
    idf_vals = [index.terms[t].idf_val for t in terms]

    # Prefix sums of global max scores (strictly increasing)
    psum = [0.0] * n
    psum[0] = gmax[0]
    for i in range(1, n):
        psum[i] = psum[i - 1] + gmax[i]

    # Top-k min-heap storing (score, -doc_id)
    # Using -doc_id so that for equal scores the largest doc_id (least
    # desirable) sorts as smallest and sits at the heap root.
    heap = []
    threshold = 0.0

    # Essential boundary: terms[0..ess-1] are non-essential.
    ess = 0

    def _update_ess():
        nonlocal ess
        new_ess = 0
        for i in range(n):
            if psum[i] < threshold:
                new_ess = i + 1
            else:
                break
        ess = new_ess

    # ---------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------
    while ess < n:
        # Find the minimum doc_id among non-exhausted essential terms
        min_doc = None
        for i in range(ess, n):
            if iters[i].exhausted:
                continue
            d = iters[i].doc()
            if d is not None and (min_doc is None or d < min_doc):
                min_doc = d

        if min_doc is None:
            break  # all essential terms exhausted

        # --- Block-max upper-bound filter ---
        # Compute an upper bound on the score for min_doc using block-max
        # scores for essential terms and global max for non-essential.
        upper = 0.0
        for i in range(ess):
            upper += gmax[i]  # non-essential: loose global bound
        for i in range(ess, n):
            if iters[i].exhausted:
                continue
            d = iters[i].doc()
            if d is not None and d == min_doc:
                upper += iters[i].block_max()
            elif d is not None:
                # This essential term's iterator isn't at min_doc yet
                # (its current doc > min_doc). Use global max as bound.
                upper += gmax[i]
            # exhausted terms contribute 0

        if upper < threshold:
            # Cannot possibly beat the current k-th best -- skip.
            for i in range(ess, n):
                if not iters[i].exhausted and iters[i].doc() == min_doc:
                    iters[i].next_doc()
            continue

        # --- Score the candidate document ---
        dl = index.doc_lengths[min_doc]
        score = 0.0

        # Non-essential terms: advance iterator to min_doc and score if present
        for i in range(ess):
            if iters[i].exhausted:
                continue
            d = iters[i].advance_to(min_doc)
            if d == min_doc:
                _, tf = iters[i].posting()
                score += _bm25(tf, idf_vals[i], dl, avgdl)

        # Essential terms: check if they are at min_doc
        for i in range(ess, n):
            if iters[i].exhausted:
                continue
            if iters[i].doc() == min_doc:
                _, tf = iters[i].posting()
                score += _bm25(tf, idf_vals[i], dl, avgdl)

        # --- Update the heap ---
        entry = (score, -min_doc)
        if len(heap) < k:
            heapq.heappush(heap, entry)
            if len(heap) == k:
                threshold = heap[0][0]
                _update_ess()
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
            threshold = heap[0][0]
            _update_ess()

        # Advance essential iterators that are at min_doc
        for i in range(ess, n):
            if not iters[i].exhausted and iters[i].doc() == min_doc:
                iters[i].next_doc()

    # ---------------------------------------------------------------
    # Extract and sort results
    # ---------------------------------------------------------------
    results = [(-neg_id, sc) for sc, neg_id in heap]
    results.sort(key=lambda x: (-x[1], x[0]))
    return results
