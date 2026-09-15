
import re
import subprocess
import sys
import json

import numpy as np
import pytest

sys.path.insert(0, "/app")

import bm25s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_data():
    corpus = []
    with open("/app/corpus.jsonl", "r") as f:
        for line in f:
            corpus.append(json.loads(line)["text"])
    with open("/app/queries.json", "r") as f:
        queries = json.load(f)
    return corpus, queries


def build_bm25s_retriever(corpus_texts, method, k1=1.5, b=0.75, delta=0.5):
    tokens = bm25s.tokenize(corpus_texts, stopwords="en", return_ids=False, show_progress=False)
    retriever = bm25s.BM25(method=method, k1=k1, b=b, delta=delta)
    retriever.index(tokens, show_progress=False)
    return retriever


def retrieve_bm25s(retriever, query_texts, k=10):
    tokens = bm25s.tokenize(query_texts, stopwords="en", return_ids=False, show_progress=False)
    docs, scores = retriever.retrieve(tokens, k=k, show_progress=False)
    return docs, scores


def compare_sorted_scores(engine_scores, bm25s_scores, atol=1e-4):
    """Compare top-k score sets (sorted descending) per query."""
    assert engine_scores.shape == bm25s_scores.shape, (
        f"Shape mismatch: {engine_scores.shape} vs {bm25s_scores.shape}"
    )
    for q in range(engine_scores.shape[0]):
        e_sorted = np.sort(engine_scores[q])[::-1]
        b_sorted = np.sort(bm25s_scores[q])[::-1]
        np.testing.assert_allclose(
            e_sorted, b_sorted, atol=atol, rtol=1e-4,
            err_msg=f"Score mismatch for query {q}",
        )


def compare_full_scores(engine_indices, engine_scores, bm25s_indices, bm25s_scores,
                         n_docs, atol=1e-4):
    """Reconstruct full score vectors indexed by doc-id and compare element-wise."""
    n_queries = engine_scores.shape[0]
    for q in range(n_queries):
        e_full = np.zeros(n_docs, dtype=np.float64)
        b_full = np.zeros(n_docs, dtype=np.float64)
        for j in range(engine_scores.shape[1]):
            e_full[int(engine_indices[q][j])] = float(engine_scores[q][j])
            b_full[int(bm25s_indices[q][j])] = float(bm25s_scores[q][j])
        np.testing.assert_allclose(
            e_full, b_full, atol=atol, rtol=1e-4,
            err_msg=f"Full-vector mismatch for query {q}",
        )


# ---------------------------------------------------------------------------
# Anti-cheat: ensure engine does not wrap bm25s
# ---------------------------------------------------------------------------

class TestEngineIndependence:
    """Verify the engine is a standalone implementation, not a bm25s wrapper."""

    def test_no_bm25s_reference_in_source(self):
        """bm25_engine.py must not contain any reference to bm25s."""
        with open("/app/bm25_engine.py") as f:
            source = f.read()
        assert not re.search(r'\bbm25s\b', source, re.IGNORECASE), \
            "bm25_engine.py must not contain any reference to 'bm25s'"

    def test_engine_runs_without_bm25s(self):
        """Verify engine produces results in a subprocess where bm25s is blocked."""
        script = (
            "import sys, json\n"
            "sys.modules['bm25s'] = None\n"
            "sys.path.insert(0, '/app')\n"
            "from bm25_engine import BM25Engine\n"
            "with open('/app/corpus.jsonl') as f:\n"
            "    corpus = [json.loads(l)['text'] for l in f][:50]\n"
            "engine = BM25Engine(method='robertson', k1=1.5, b=0.75, delta=0.5)\n"
            "engine.index(corpus)\n"
            "idx, sc = engine.retrieve(['algorithm optimization'], k=5)\n"
            "assert idx.shape == (1, 5), f'Wrong shape: {idx.shape}'\n"
            "assert sc.shape == (1, 5), f'Wrong shape: {sc.shape}'\n"
            "print('PASS')\n"
        )
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"Engine failed without bm25s:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout


# ---------------------------------------------------------------------------
# Score parity tests
# ---------------------------------------------------------------------------

class TestBM25VariantParity:
    """Verify BM25Engine matches bm25s across all 5 variants."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.corpus, self.queries = load_data()
        self.n_docs = len(self.corpus)
        self.k1 = 1.5
        self.b = 0.75
        self.delta = 0.5

    # ---- top-k score parity (k=10) across all variants ------------------

    @pytest.mark.parametrize("method", ["robertson", "lucene", "atire", "bm25l", "bm25+"])
    def test_topk_parity(self, method):
        from bm25_engine import BM25Engine

        k = 10
        retriever = build_bm25s_retriever(self.corpus, method, self.k1, self.b, self.delta)
        _, bm25s_scores = retrieve_bm25s(retriever, self.queries, k=k)

        engine = BM25Engine(method=method, k1=self.k1, b=self.b, delta=self.delta)
        engine.index(self.corpus)
        _, engine_scores = engine.retrieve(self.queries, k=k)

        compare_sorted_scores(engine_scores, bm25s_scores)

    # ---- full score-vector parity (k = n_docs) --------------------------

    @pytest.mark.parametrize("method", ["robertson", "lucene", "atire", "bm25l", "bm25+"])
    def test_full_vector_parity(self, method):
        from bm25_engine import BM25Engine

        retriever = build_bm25s_retriever(self.corpus, method, self.k1, self.b, self.delta)
        b_idx, b_sc = retrieve_bm25s(retriever, self.queries[:5], k=self.n_docs)

        engine = BM25Engine(method=method, k1=self.k1, b=self.b, delta=self.delta)
        engine.index(self.corpus)
        e_idx, e_sc = engine.retrieve(self.queries[:5], k=self.n_docs)

        compare_full_scores(e_idx, e_sc, b_idx, b_sc, self.n_docs)

    # ---- single-term queries --------------------------------------------

    @pytest.mark.parametrize("method", ["robertson", "lucene", "atire", "bm25l", "bm25+"])
    def test_single_term_queries(self, method):
        from bm25_engine import BM25Engine

        single_queries = ["algorithm", "eigenvalue", "compute"]
        k = 5
        retriever = build_bm25s_retriever(self.corpus, method, self.k1, self.b, self.delta)
        _, bm25s_scores = retrieve_bm25s(retriever, single_queries, k=k)

        engine = BM25Engine(method=method, k1=self.k1, b=self.b, delta=self.delta)
        engine.index(self.corpus)
        _, engine_scores = engine.retrieve(single_queries, k=k)

        compare_sorted_scores(engine_scores, bm25s_scores)

    # ---- non-default parameters -----------------------------------------

    @pytest.mark.parametrize("method", ["robertson", "lucene", "atire", "bm25l", "bm25+"])
    @pytest.mark.parametrize("k1,b,delta", [(1.2, 0.5, 1.0), (0.8, 0.9, 0.25)])
    def test_nondefault_params(self, method, k1, b, delta):
        from bm25_engine import BM25Engine

        k = 5
        retriever = build_bm25s_retriever(self.corpus, method, k1, b, delta)
        _, bm25s_scores = retrieve_bm25s(retriever, self.queries[:5], k=k)

        engine = BM25Engine(method=method, k1=k1, b=b, delta=delta)
        engine.index(self.corpus)
        _, engine_scores = engine.retrieve(self.queries[:5], k=k)

        compare_sorted_scores(engine_scores, bm25s_scores)

    # ---- top-1 retrieval ------------------------------------------------

    @pytest.mark.parametrize("method", ["robertson", "lucene", "atire", "bm25l", "bm25+"])
    def test_top1(self, method):
        from bm25_engine import BM25Engine

        retriever = build_bm25s_retriever(self.corpus, method, self.k1, self.b, self.delta)
        _, bm25s_scores = retrieve_bm25s(retriever, self.queries[:5], k=1)

        engine = BM25Engine(method=method, k1=self.k1, b=self.b, delta=self.delta)
        engine.index(self.corpus)
        _, engine_scores = engine.retrieve(self.queries[:5], k=1)

        compare_sorted_scores(engine_scores, bm25s_scores)
