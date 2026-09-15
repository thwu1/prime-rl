
"""
Tests for the search engine pipeline and NDCG evaluation module.

Three verification layers:
1. NDCG implementation correctness (eval module produces correct metric values)
2. Pipeline ranking quality (BM25 rankings match reference + NDCG targets met)
3. Anti-cheat (determinism, unseen query handling, document coverage)
"""

import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict

import pytest

sys.path.insert(0, "/app")

# ---------------------------------------------------------------------------
# Reference BM25 implementation (ground truth, independent of pipeline code)
# ---------------------------------------------------------------------------

def _ref_tokenize(text):
    return re.findall(r'[a-z0-9]+', text.lower())


def _ref_build_field_index(corpus, field):
    tf = {}
    dl = {}
    df = defaultdict(int)
    for doc in corpus:
        doc_id = doc["id"]
        tokens = _ref_tokenize(doc.get(field, ""))
        dl[doc_id] = len(tokens)
        counts = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        tf[doc_id] = counts
        for t in counts:
            df[t] += 1
    avgdl = sum(dl.values()) / len(corpus) if corpus else 1.0
    return tf, dl, avgdl, dict(df)


def _ref_bm25(query_text, corpus, k1=1.2, b=0.75,
              fields=("title", "body"), boosts=None):
    """Full reference BM25 multi-field scorer."""
    if boosts is None:
        boosts = {"title": 2.0, "body": 1.0}
    n = len(corpus)
    query_tokens = _ref_tokenize(query_text)
    field_indices = {}
    for f in fields:
        field_indices[f] = _ref_build_field_index(corpus, f)

    doc_scores = defaultdict(float)
    for f in fields:
        f_tf, f_dl, f_avgdl, f_df = field_indices[f]
        boost = boosts.get(f, 1.0)
        for term in query_tokens:
            df_val = f_df.get(term, 0)
            if df_val == 0:
                continue
            idf = math.log(1.0 + (n - df_val + 0.5) / (df_val + 0.5))
            for doc in corpus:
                did = doc["id"]
                tf_val = f_tf[did].get(term, 0)
                if tf_val == 0:
                    continue
                dl_val = f_dl[did]
                tf_norm = (tf_val * (k1 + 1.0)) / (
                    tf_val + k1 * (1.0 - b + b * dl_val / f_avgdl)
                )
                doc_scores[did] += idf * tf_norm * boost

    results = []
    for doc in corpus:
        did = doc["id"]
        if did in doc_scores and doc_scores[did] > 0:
            results.append((did, doc_scores[did], doc["title"]))
    results.sort(key=lambda x: (-x[1], x[0]))
    return results


# Reference NDCG (for cross-checking the solver's implementation)
def _ref_dcg(ranked_ids, grades, k=10):
    s = 0.0
    for i in range(min(k, len(ranked_ids))):
        did = int(ranked_ids[i])
        rel = grades.get(did, 0)
        s += rel / math.log2(i + 2)
    return s


def _ref_ndcg(ranked_ids, grades, k=10):
    dcg = _ref_dcg(ranked_ids, grades, k)
    ideal_ids = sorted(grades.keys(), key=lambda d: -grades[d])
    idcg = _ref_dcg(ideal_ids, grades, k)
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DB_PATH = "/app/data/corpus.db"
QUERIES_PATH = "/app/data/queries.json"
QRELS_PATH = "/app/data/qrels.json"
OUTPUT_PATH = "/app/output.json"

QUERIES = [
    "machine learning algorithms",
    "cloud security threats",
    "database index performance",
    "distributed consensus protocol",
    "neural network training",
]


@pytest.fixture(scope="session")
def corpus():
    """Read full corpus directly from SQLite (all 25 documents)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title, body FROM documents ORDER BY id").fetchall()
    conn.close()
    return [{"id": row["id"], "title": row["title"], "body": row["body"]} for row in rows]


@pytest.fixture(scope="session")
def reference_results(corpus):
    """Compute reference BM25 results for all queries."""
    ref = {}
    for q in QUERIES:
        ref[q] = _ref_bm25(q, corpus)
    return ref


@pytest.fixture(scope="session")
def qrels():
    """Load graded relevance judgments with int doc_id keys."""
    with open(QRELS_PATH) as f:
        raw = json.load(f)
    return {q: {int(k): v for k, v in grades.items()} for q, grades in raw.items()}


@pytest.fixture(scope="session")
def engine_output():
    """Run the engine via make and return its output."""
    if os.path.exists(OUTPUT_PATH):
        os.remove(OUTPUT_PATH)
    result = subprocess.run(
        ["make", "run"],
        capture_output=True, text=True, timeout=60, cwd="/app",
    )
    assert result.returncode == 0, (
        f"'make run' exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    assert os.path.exists(OUTPUT_PATH), "Engine did not write output.json"
    with open(OUTPUT_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test: NDCG implementation correctness
# ---------------------------------------------------------------------------

class TestNDCGImplementation:
    """Verifies that evaluation/metrics.py implements DCG and NDCG correctly."""

    def test_dcg_ideal_order(self):
        from evaluation.metrics import dcg_at_k
        ranked = [10, 20, 30, 40]
        grades = {10: 3, 20: 2, 30: 1, 40: 0}
        dcg = dcg_at_k(ranked, grades, k=4)
        expected = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4) + 0 / math.log2(5)
        assert abs(dcg - expected) < 1e-6, f"Expected {expected:.6f}, got {dcg:.6f}"

    def test_dcg_reversed_order(self):
        from evaluation.metrics import dcg_at_k
        ranked = [40, 30, 20, 10]
        grades = {10: 3, 20: 2, 30: 1, 40: 0}
        dcg = dcg_at_k(ranked, grades, k=4)
        expected = 0 / math.log2(2) + 1 / math.log2(3) + 2 / math.log2(4) + 3 / math.log2(5)
        assert abs(dcg - expected) < 1e-6

    def test_dcg_with_unlisted_docs(self):
        from evaluation.metrics import dcg_at_k
        ranked = [99, 10, 20]
        grades = {10: 3, 20: 2}
        dcg = dcg_at_k(ranked, grades, k=3)
        expected = 0 / math.log2(2) + 3 / math.log2(3) + 2 / math.log2(4)
        assert abs(dcg - expected) < 1e-6

    def test_ndcg_perfect_ranking(self):
        from evaluation.metrics import ndcg_at_k
        ranked = [10, 20, 30, 40]
        grades = {10: 3, 20: 2, 30: 1, 40: 0}
        ndcg = ndcg_at_k(ranked, grades, k=4)
        assert abs(ndcg - 1.0) < 1e-6, f"Perfect ranking should give NDCG=1.0, got {ndcg}"

    def test_ndcg_reversed_ranking(self):
        from evaluation.metrics import ndcg_at_k
        ranked = [40, 30, 20, 10]
        grades = {10: 3, 20: 2, 30: 1, 40: 0}
        ndcg = ndcg_at_k(ranked, grades, k=4)
        dcg = 0 / math.log2(2) + 1 / math.log2(3) + 2 / math.log2(4) + 3 / math.log2(5)
        idcg = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4) + 0 / math.log2(5)
        expected = dcg / idcg
        assert abs(ndcg - expected) < 1e-6

    def test_ndcg_no_relevant_docs(self):
        from evaluation.metrics import ndcg_at_k
        ranked = [1, 2, 3]
        grades = {}
        ndcg = ndcg_at_k(ranked, grades, k=3)
        assert ndcg == 0.0, "NDCG with no relevant docs should be 0.0"

    def test_ndcg_single_relevant_at_rank3(self):
        from evaluation.metrics import ndcg_at_k
        ranked = [50, 60, 10]
        grades = {10: 3}
        ndcg = ndcg_at_k(ranked, grades, k=3)
        dcg = 0 / math.log2(2) + 0 / math.log2(3) + 3 / math.log2(4)
        idcg = 3 / math.log2(2)
        expected = dcg / idcg
        assert abs(ndcg - expected) < 1e-6

    def test_ndcg_k_truncation(self):
        from evaluation.metrics import ndcg_at_k
        ranked = [40, 30, 20, 10]
        grades = {10: 3, 20: 2, 30: 1, 40: 0}
        ndcg = ndcg_at_k(ranked, grades, k=2)
        dcg = 0 / math.log2(2) + 1 / math.log2(3)
        idcg = 3 / math.log2(2) + 2 / math.log2(3)
        expected = dcg / idcg
        assert abs(ndcg - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test: pipeline execution
# ---------------------------------------------------------------------------

class TestPipelineExecution:
    def test_engine_produces_output(self, engine_output):
        assert isinstance(engine_output, dict)

    def test_all_queries_present(self, engine_output):
        for q in QUERIES:
            assert q in engine_output, f"Missing query: '{q}'"

    @pytest.mark.parametrize("query", QUERIES)
    def test_results_non_empty(self, engine_output, query):
        assert len(engine_output[query]) > 0, f"No results for '{query}'"

    def test_jq_validation_passes(self, engine_output):
        jq_expr = (
            'to_entries | all(.value | type == "array" and length > 0 '
            'and all(.[]; has("doc_id") and has("score") and has("title")))'
        )
        result = subprocess.run(
            ["jq", "-e", jq_expr, OUTPUT_PATH],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"jq output validation failed.\nstderr: {result.stderr[:300]}"
        )


# ---------------------------------------------------------------------------
# Test: output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    @pytest.mark.parametrize("query", QUERIES)
    def test_result_fields(self, engine_output, query):
        for i, r in enumerate(engine_output[query]):
            for field in ("doc_id", "score", "title"):
                assert field in r, f"Result {i} for '{query}' missing '{field}'"

    @pytest.mark.parametrize("query", QUERIES)
    def test_no_duplicate_ids(self, engine_output, query):
        ids = [r["doc_id"] for r in engine_output[query]]
        assert len(ids) == len(set(ids)), f"Duplicate doc IDs: {ids}"

    @pytest.mark.parametrize("query", QUERIES)
    def test_valid_doc_ids(self, engine_output, query):
        valid = set(range(1, 26))
        for r in engine_output[query]:
            assert int(r["doc_id"]) in valid, f"Invalid doc_id {r['doc_id']}"


# ---------------------------------------------------------------------------
# Test: score properties
# ---------------------------------------------------------------------------

class TestScoreProperties:
    @pytest.mark.parametrize("query", QUERIES)
    def test_scores_positive(self, engine_output, query):
        for r in engine_output[query]:
            assert r["score"] > 0, f"Non-positive score for doc {r['doc_id']}"

    @pytest.mark.parametrize("query", QUERIES)
    def test_scores_descending(self, engine_output, query):
        results = engine_output[query]
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"] - 1e-9, (
                f"Not sorted: pos {i} ({results[i]['score']}) < "
                f"pos {i+1} ({results[i+1]['score']})"
            )


# ---------------------------------------------------------------------------
# Test: NDCG quality targets (uses solver's evaluation module)
# ---------------------------------------------------------------------------

class TestNDCGQuality:
    """Every query must achieve NDCG@10 >= 0.80 using the solver's NDCG impl."""

    @pytest.mark.parametrize("query", QUERIES)
    def test_ndcg_meets_threshold(self, engine_output, qrels, query):
        from evaluation.metrics import ndcg_at_k
        ranked_ids = [r["doc_id"] for r in engine_output[query]]
        grades = qrels[query]
        ndcg = ndcg_at_k(ranked_ids, grades, k=10)
        assert ndcg >= 0.80, (
            f"NDCG@10 for '{query}' is {ndcg:.4f}, must be >= 0.80"
        )

    @pytest.mark.parametrize("query", QUERIES)
    def test_ndcg_agrees_with_reference(self, engine_output, qrels, query):
        """The solver's NDCG implementation must match the reference computation."""
        from evaluation.metrics import ndcg_at_k
        ranked_ids = [r["doc_id"] for r in engine_output[query]]
        grades = qrels[query]
        solver_ndcg = ndcg_at_k(ranked_ids, grades, k=10)
        ref_ndcg = _ref_ndcg(ranked_ids, grades, k=10)
        assert abs(solver_ndcg - ref_ndcg) < 1e-6, (
            f"NDCG mismatch for '{query}': "
            f"solver={solver_ndcg:.6f}, reference={ref_ndcg:.6f}"
        )


# ---------------------------------------------------------------------------
# Test: ranking correctness vs reference BM25
# ---------------------------------------------------------------------------

class TestRankingCorrectness:
    @pytest.mark.parametrize("query", QUERIES)
    def test_top1_matches_reference(self, engine_output, reference_results, query):
        """The top-ranked document must match the reference top-1."""
        ref = reference_results[query]
        assert len(ref) > 0, f"Reference has no results for '{query}'"
        expected_top1 = ref[0][0]
        actual_top1 = engine_output[query][0]["doc_id"]
        assert int(actual_top1) == expected_top1, (
            f"Top-1 mismatch for '{query}': expected doc {expected_top1}, "
            f"got doc {actual_top1}"
        )

    @pytest.mark.parametrize("query", QUERIES)
    def test_top5_overlap(self, engine_output, reference_results, query):
        """At least 4 of the reference top-5 docs must appear in the output top-5."""
        ref = reference_results[query]
        ref_top5 = {r[0] for r in ref[:5]}
        actual_top5 = {int(r["doc_id"]) for r in engine_output[query][:5]}
        overlap = ref_top5 & actual_top5
        assert len(overlap) >= min(4, len(ref_top5)), (
            f"Top-5 overlap too low for '{query}': "
            f"ref={ref_top5}, actual={actual_top5}, overlap={overlap}"
        )

    @pytest.mark.parametrize("query", QUERIES)
    def test_top3_order(self, engine_output, reference_results, query):
        """The top-3 documents must appear in the same relative order as reference."""
        ref = reference_results[query]
        ref_top3_ids = [r[0] for r in ref[:3]]
        actual_ids = [int(r["doc_id"]) for r in engine_output[query]]
        positions = []
        for rid in ref_top3_ids:
            if rid in actual_ids:
                positions.append(actual_ids.index(rid))
        assert positions == sorted(positions), (
            f"Top-3 order mismatch for '{query}': "
            f"ref order={ref_top3_ids}, actual positions={positions}"
        )

    def test_high_id_documents_present(self, engine_output):
        """Documents with IDs > 20 must be indexed and appear in relevant results."""
        consensus_ids = {int(r["doc_id"]) for r in engine_output["distributed consensus protocol"]}
        assert 21 in consensus_ids, (
            "Document 21 (Blockchain Consensus) missing from 'distributed consensus protocol' "
            "results. All 25 documents in the corpus database must be indexed."
        )


# ---------------------------------------------------------------------------
# Test: score accuracy vs reference
# ---------------------------------------------------------------------------

class TestScoreAccuracy:
    @pytest.mark.parametrize("query", QUERIES)
    def test_top1_score_within_tolerance(self, engine_output, reference_results, query):
        """Top-1 score must be within 5% of the reference."""
        ref = reference_results[query]
        ref_score = ref[0][1]
        actual_score = engine_output[query][0]["score"]
        tolerance = max(0.05 * ref_score, 0.01)
        assert abs(actual_score - ref_score) < tolerance, (
            f"Top-1 score mismatch for '{query}': "
            f"expected ~{ref_score:.4f}, got {actual_score:.4f}"
        )

    @pytest.mark.parametrize("query", QUERIES)
    def test_score_ratios_preserved(self, engine_output, reference_results, query):
        """Score ratio between top-1 and top-2 must roughly match reference."""
        ref = reference_results[query]
        if len(ref) < 2:
            return
        actual = engine_output[query]
        if len(actual) < 2:
            pytest.fail(f"Need at least 2 results for '{query}'")
        ref_ratio = ref[0][1] / ref[1][1] if ref[1][1] > 0 else float("inf")
        actual_ratio = actual[0]["score"] / actual[1]["score"] if actual[1]["score"] > 0 else float("inf")
        if ref_ratio < 50 and actual_ratio < 50:
            assert abs(ref_ratio - actual_ratio) / max(ref_ratio, 0.01) < 0.15, (
                f"Score ratio mismatch for '{query}': "
                f"ref ratio={ref_ratio:.2f}, actual ratio={actual_ratio:.2f}"
            )


# ---------------------------------------------------------------------------
# Test: anti-cheat (determinism, unseen queries, document coverage)
# ---------------------------------------------------------------------------

class TestAntiCheat:
    def test_rerun_produces_same_output(self, engine_output):
        """Running the engine again must produce identical output."""
        result = subprocess.run(
            ["make", "run"],
            capture_output=True, text=True, timeout=60, cwd="/app",
        )
        assert result.returncode == 0
        with open(OUTPUT_PATH) as f:
            rerun_output = json.load(f)
        for q in QUERIES:
            assert q in rerun_output
            orig_ids = [r["doc_id"] for r in engine_output[q]]
            rerun_ids = [r["doc_id"] for r in rerun_output[q]]
            assert orig_ids == rerun_ids, (
                f"Re-run produced different ranking for '{q}'"
            )

    def test_additional_query(self, corpus):
        """Engine must handle an unseen query correctly."""
        extra_query = "compiler optimization"
        ref = _ref_bm25(extra_query, corpus)
        if len(ref) == 0:
            return

        with open(QUERIES_PATH) as f:
            original_queries = json.load(f)
        test_queries = original_queries + [extra_query]
        with open(QUERIES_PATH, "w") as f:
            json.dump(test_queries, f)

        try:
            result = subprocess.run(
                ["make", "run"],
                capture_output=True, text=True, timeout=60, cwd="/app",
            )
            assert result.returncode == 0, f"Engine failed on extra query: {result.stderr[:300]}"
            with open(OUTPUT_PATH) as f:
                output = json.load(f)
            assert extra_query in output, "Engine did not handle extra query"
            if len(output[extra_query]) > 0 and len(ref) > 0:
                actual_top1 = int(output[extra_query][0]["doc_id"])
                ref_top1 = ref[0][0]
                assert actual_top1 == ref_top1, (
                    f"Extra query top-1: expected {ref_top1}, got {actual_top1}"
                )
        finally:
            with open(QUERIES_PATH, "w") as f:
                json.dump(original_queries, f)
            subprocess.run(
                ["make", "run"],
                capture_output=True, timeout=60, cwd="/app",
            )

    def test_all_25_documents_indexed(self, engine_output):
        """At least one query must return a document with ID > 20,
        proving the full corpus is indexed."""
        all_doc_ids = set()
        for query_results in engine_output.values():
            for r in query_results:
                all_doc_ids.add(int(r["doc_id"]))
        high_ids = {d for d in all_doc_ids if d > 20}
        assert len(high_ids) > 0, (
            "No document with ID > 20 appears in any results. "
            "The engine must index all 25 documents."
        )
