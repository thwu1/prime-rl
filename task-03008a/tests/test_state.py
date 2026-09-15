
import pytest
import json
import math
import sys
from collections import Counter, defaultdict


class ReferenceBM25:
    """Independent reference BM25 implementation for verification."""

    def __init__(self, corpus_path, k1=1.2, b=0.75):
        self.k1 = k1
        self.b = b
        self.tf = {}
        self.df = {}
        self.doc_lengths = []
        self.N = 0
        self.avgdl = 0.0

        with open(corpus_path) as f:
            for line in f:
                doc = json.loads(line)
                doc_id = doc["id"]
                tokens = doc["text"].lower().split()
                while doc_id >= len(self.doc_lengths):
                    self.doc_lengths.append(0)
                self.doc_lengths[doc_id] = len(tokens)
                tf_counter = Counter(tokens)
                for term, count in tf_counter.items():
                    if term not in self.tf:
                        self.tf[term] = {}
                        self.df[term] = 0
                    self.tf[term][doc_id] = count
                    self.df[term] += 1

        self.N = len(self.doc_lengths)
        self.avgdl = sum(self.doc_lengths) / self.N if self.N else 0

    def idf(self, term):
        df = self.df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)

    def score_term(self, term, doc_id):
        tf_val = self.tf.get(term, {}).get(doc_id, 0)
        if tf_val == 0:
            return 0.0
        dl = self.doc_lengths[doc_id]
        idf_val = self.idf(term)
        num = tf_val * (self.k1 + 1)
        den = tf_val + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        return idf_val * num / den

    def search(self, query, top_k=10):
        terms = list(dict.fromkeys(query.lower().split()))
        terms = [t for t in terms if t in self.tf]
        if not terms:
            return []
        scores = defaultdict(float)
        for term in terms:
            for doc_id in self.tf[term]:
                scores[doc_id] += self.score_term(term, doc_id)
        results = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return [(did, sc) for did, sc in results[:top_k]]

    def exhaustive_posting_count(self, query):
        """Total postings that exhaustive evaluation would touch."""
        terms = list(dict.fromkeys(query.lower().split()))
        terms = [t for t in terms if t in self.tf]
        return sum(len(self.tf[t]) for t in terms)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

sys.path.insert(0, "/app")
from search_engine import SearchEngine


@pytest.fixture(scope="module")
def reference():
    return ReferenceBM25("/app/corpus.jsonl")


@pytest.fixture(scope="module")
def engine():
    eng = SearchEngine()
    eng.build_index("/app/corpus.jsonl")
    return eng


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

QUERIES = [
    "rare42",
    "word5 rare200",
    "the rare42",
    "the of word5 word10 rare42",
    "the of and to",
    "the of in word1 word5 word10 word20 rare50 rare100 rare200",
    "word0",
    "rare200 rare300 rare400",
    "a is the of and in to for on that",
    "word25 rare250",
]

TOP_KS = [5, 10, 50]


# ---------------------------------------------------------------------------
# 1. Correctness: engine results must match reference BM25
# ---------------------------------------------------------------------------

class TestCorrectness:

    @pytest.mark.parametrize("query", QUERIES)
    @pytest.mark.parametrize("top_k", TOP_KS)
    def test_results_match_reference(self, engine, reference, query, top_k):
        ref = reference.search(query, top_k)
        eng = engine.search(query, top_k)

        assert len(eng) == len(ref), (
            f"q={query!r} k={top_k}: expected {len(ref)} results, got {len(eng)}"
        )
        for i, ((r_id, r_sc), (e_id, e_sc)) in enumerate(zip(ref, eng)):
            assert r_id == e_id, (
                f"q={query!r} k={top_k} pos {i}: expected doc {r_id}, got {e_id}"
            )
            assert abs(r_sc - e_sc) < 1e-6, (
                f"q={query!r} k={top_k} pos {i}: expected score {r_sc:.8f}, got {e_sc:.8f}"
            )


# ---------------------------------------------------------------------------
# 2. Efficiency: optimized engine must evaluate fewer postings
# ---------------------------------------------------------------------------

class TestEfficiency:

    def test_stopword_plus_rare(self, engine, reference):
        """High-frequency + low-frequency term query."""
        engine.search("the rare42", top_k=10)
        stats = engine.get_search_stats()
        exhaustive = reference.exhaustive_posting_count("the rare42")

        ratio = stats["postings_scored"] / max(exhaustive, 1)
        assert ratio < 0.40, (
            f"'the rare42': scored {stats['postings_scored']} / {exhaustive} "
            f"= {ratio:.3f}, must be < 0.40"
        )

    def test_two_stopwords_plus_rare(self, engine, reference):
        """Two high-frequency terms + one rare term."""
        q = "the of rare42"
        engine.search(q, top_k=10)
        stats = engine.get_search_stats()
        exhaustive = reference.exhaustive_posting_count(q)

        ratio = stats["postings_scored"] / max(exhaustive, 1)
        assert ratio < 0.40, (
            f"'the of rare42': scored {stats['postings_scored']} / {exhaustive} "
            f"= {ratio:.3f}, must be < 0.40"
        )

    def test_mixed_five_terms(self, engine, reference):
        """Mixed-frequency 5-term query."""
        q = "the of word5 word10 rare42"
        engine.search(q, top_k=10)
        stats = engine.get_search_stats()
        exhaustive = reference.exhaustive_posting_count(q)

        ratio = stats["postings_scored"] / max(exhaustive, 1)
        assert ratio < 0.60, (
            f"5-term mixed: scored {stats['postings_scored']} / {exhaustive} "
            f"= {ratio:.3f}, must be < 0.60"
        )

    def test_long_query_ten_terms(self, engine, reference):
        """10-term query spanning diverse frequencies."""
        q = "the of in word1 word5 word10 word20 rare50 rare100 rare200"
        engine.search(q, top_k=10)
        stats = engine.get_search_stats()
        exhaustive = reference.exhaustive_posting_count(q)

        ratio = stats["postings_scored"] / max(exhaustive, 1)
        assert ratio < 0.50, (
            f"10-term mixed: scored {stats['postings_scored']} / {exhaustive} "
            f"= {ratio:.3f}, must be < 0.50"
        )

    def test_stats_populated(self, engine):
        """get_search_stats must return postings_scored."""
        engine.search("the rare42", top_k=10)
        stats = engine.get_search_stats()
        assert "postings_scored" in stats
        assert isinstance(stats["postings_scored"], int)
        assert stats["postings_scored"] > 0


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_nonexistent_term(self, engine):
        res = engine.search("xyznonexistent99999", top_k=10)
        assert res == []

    def test_single_term_correct(self, engine, reference):
        ref = reference.search("word0", top_k=10)
        eng = engine.search("word0", top_k=10)
        assert len(eng) == len(ref)
        for (r_id, r_sc), (e_id, e_sc) in zip(ref, eng):
            assert r_id == e_id
            assert abs(r_sc - e_sc) < 1e-6

    def test_top_k_larger_than_results(self, engine, reference):
        ref = reference.search("rare400", top_k=10000)
        eng = engine.search("rare400", top_k=10000)
        assert len(eng) == len(ref)
        for (r_id, r_sc), (e_id, e_sc) in zip(ref, eng):
            assert r_id == e_id
            assert abs(r_sc - e_sc) < 1e-6

    def test_top_k_5_is_prefix_of_50(self, engine):
        r5 = engine.search("the of word5 word10 rare42", top_k=5)
        r50 = engine.search("the of word5 word10 rare42", top_k=50)
        assert len(r5) <= len(r50)
        for i in range(len(r5)):
            assert r5[i][0] == r50[i][0]
            assert abs(r5[i][1] - r50[i][1]) < 1e-6

    def test_all_stopwords_correct(self, engine, reference):
        """All-common-term query — limited optimization opportunity."""
        ref = reference.search("the of and to", top_k=10)
        eng = engine.search("the of and to", top_k=10)
        assert len(eng) == len(ref)
        for (r_id, r_sc), (e_id, e_sc) in zip(ref, eng):
            assert r_id == e_id
            assert abs(r_sc - e_sc) < 1e-6

    def test_duplicate_query_terms(self, engine, reference):
        """Duplicate terms in query should be deduplicated."""
        ref = reference.search("rare42 rare42 rare42", top_k=10)
        eng = engine.search("rare42 rare42 rare42", top_k=10)
        assert len(eng) == len(ref)
        for (r_id, r_sc), (e_id, e_sc) in zip(ref, eng):
            assert r_id == e_id
            assert abs(r_sc - e_sc) < 1e-6
