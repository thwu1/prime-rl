"""Tests for BM25 multi-index forensics and rank fusion task."""

import json
import math
import os
import re

import numpy as np
import pytest

# Ground truth parameters for each index
GROUND_TRUTH = {
    "a": {"method": "robertson", "k1": 1.2, "b": 0.55},
    "b": {"method": "atire", "k1": 1.8, "b": 0.80},
    "c": {"method": "lucene", "k1": 1.35, "b": 0.65},
}

PARAM_TOLERANCE = 0.05
NDCG_TOLERANCE = 0.05
NUM_DOCS = 40


@pytest.fixture
def results():
    with open("/app/output/results.json") as f:
        return json.load(f)


@pytest.fixture
def qrels():
    with open("/app/qrels.json") as f:
        return json.load(f)


@pytest.fixture
def queries():
    with open("/app/queries.json") as f:
        return json.load(f)


def _compute_dcg(rels, k=10):
    """DCG@k = sum((2^rel_i - 1) / log2(i+1)) for 1-indexed positions."""
    dcg = 0.0
    for i, rel in enumerate(rels[:k]):
        dcg += (2 ** rel - 1) / math.log2(i + 2)  # i+2 because i is 0-indexed
    return dcg


def _compute_ndcg_single(ranked_doc_ids, qrel_dict, k=10):
    """nDCG@k for a single query."""
    rels = [qrel_dict.get(str(did), 0) for did in ranked_doc_ids[:k]]
    dcg = _compute_dcg(rels, k)
    ideal_rels = sorted(qrel_dict.values(), reverse=True)
    idcg = _compute_dcg(ideal_rels, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _compute_mean_ndcg(rankings_dict, qrels_dict, num_queries, k=10):
    """Mean nDCG@k across all queries."""
    ndcgs = []
    for qi in range(num_queries):
        qi_str = str(qi)
        ranking = rankings_dict[qi_str]
        qrel = qrels_dict.get(qi_str, {})
        ndcgs.append(_compute_ndcg_single(ranking, qrel, k))
    return sum(ndcgs) / len(ndcgs)


def _retrieve_from_csc(index_dir, queries_list, stopwords_set, num_docs):
    """Compute full retrieval rankings from a CSC index."""
    data = np.load(f"{index_dir}/data.csc.index.npy")
    indices = np.load(f"{index_dir}/indices.csc.index.npy")
    indptr = np.load(f"{index_dir}/indptr.csc.index.npy")
    with open(f"{index_dir}/vocab.index.json") as f:
        vocab = json.load(f)

    split_fn = re.compile(r"(?u)\b\w\w+\b").findall
    rankings = {}
    for qi, query in enumerate(queries_list):
        tokens = [t for t in split_fn(query.lower()) if t not in stopwords_set]
        token_ids = [vocab[t] for t in tokens if t in vocab]
        scores = np.zeros(num_docs, dtype=np.float64)
        for tid in token_ids:
            start = int(indptr[tid])
            end = int(indptr[tid + 1])
            scores[indices[start:end]] += data[start:end].astype(np.float64)
        rankings[str(qi)] = np.argsort(scores)[::-1][:10].tolist()
    return rankings


# ── Test: output file exists ─────────────────────────────────────────────

def test_output_exists():
    assert os.path.exists("/app/output/results.json"), \
        "/app/output/results.json not found"


# ── Tests: correct identification of each index ──────────────────────────

@pytest.mark.parametrize("idx", ["a", "b", "c"])
def test_index_method(results, idx):
    expected = GROUND_TRUTH[idx]["method"]
    got = results["indexes"][idx]["method"]
    assert got == expected, \
        f"Index {idx}: expected method '{expected}', got '{got}'"


@pytest.mark.parametrize("idx", ["a", "b", "c"])
def test_index_k1(results, idx):
    expected = GROUND_TRUTH[idx]["k1"]
    got = results["indexes"][idx]["k1"]
    assert abs(got - expected) < PARAM_TOLERANCE, \
        f"Index {idx}: expected k1 ~{expected}, got {got}"


@pytest.mark.parametrize("idx", ["a", "b", "c"])
def test_index_b(results, idx):
    expected = GROUND_TRUTH[idx]["b"]
    got = results["indexes"][idx]["b"]
    assert abs(got - expected) < PARAM_TOLERANCE, \
        f"Index {idx}: expected b ~{expected}, got {got}"


# ── Test: individual nDCG accuracy ───────────────────────────────────────

def test_individual_ndcg_accuracy(results, qrels, queries):
    """Verify reported nDCG@10 values by computing independently from CSC matrices."""
    with open("/app/stopwords.json") as f:
        stopwords_set = set(json.load(f))

    for idx in ["a", "b", "c"]:
        rankings = _retrieve_from_csc(
            f"/app/index_{idx}", queries, stopwords_set, NUM_DOCS
        )
        expected_ndcg = _compute_mean_ndcg(rankings, qrels, len(queries))
        got_ndcg = results["individual_ndcg"][idx]
        assert abs(got_ndcg - expected_ndcg) < NDCG_TOLERANCE, (
            f"Index {idx}: nDCG mismatch. "
            f"Expected ~{expected_ndcg:.4f}, got {got_ndcg:.4f}"
        )


# ── Test: best individual selection ──────────────────────────────────────

def test_best_individual_correct(results):
    """Verify best_individual matches the index with highest nDCG."""
    ndcgs = results["individual_ndcg"]
    best = max(ndcgs, key=ndcgs.get)
    assert results["best_individual"] == best, \
        f"Expected best_individual='{best}', got '{results['best_individual']}'"


# ── Test: fusion rankings format ─────────────────────────────────────────

def test_fusion_rankings_format(results, queries):
    """Verify fusion rankings have correct structure."""
    assert "fusion_rankings" in results, "fusion_rankings missing"
    for qi in range(len(queries)):
        key = str(qi)
        assert key in results["fusion_rankings"], \
            f"Missing fusion ranking for query {qi}"
        ranking = results["fusion_rankings"][key]
        assert isinstance(ranking, list), \
            f"fusion_rankings['{key}'] must be a list"
        assert len(ranking) == 10, \
            f"Expected 10 results for query {qi}, got {len(ranking)}"
        for did in ranking:
            assert isinstance(did, int) and 0 <= did < NUM_DOCS, \
                f"Invalid doc ID {did} in query {qi} fusion ranking"


# ── Test: fusion outperforms all individual indexes ──────────────────────

def test_fusion_outperforms_individuals(results, qrels, queries):
    """Verify fusion nDCG exceeds the best individual index nDCG."""
    with open("/app/stopwords.json") as f:
        stopwords_set = set(json.load(f))

    # Compute individual nDCGs independently
    best_individual_ndcg = 0.0
    for idx in ["a", "b", "c"]:
        rankings = _retrieve_from_csc(
            f"/app/index_{idx}", queries, stopwords_set, NUM_DOCS
        )
        ndcg = _compute_mean_ndcg(rankings, qrels, len(queries))
        best_individual_ndcg = max(best_individual_ndcg, ndcg)

    # Compute fusion nDCG independently from agent's fusion rankings
    fusion_ndcg = _compute_mean_ndcg(
        results["fusion_rankings"], qrels, len(queries)
    )

    # Verify reported fusion_ndcg matches our computation
    assert abs(fusion_ndcg - results["fusion_ndcg"]) < NDCG_TOLERANCE, (
        f"Reported fusion nDCG ({results['fusion_ndcg']:.4f}) differs from "
        f"computed ({fusion_ndcg:.4f})"
    )

    # Fusion must outperform (or nearly match) the best individual
    assert fusion_ndcg >= best_individual_ndcg - 0.02, (
        f"Fusion nDCG ({fusion_ndcg:.4f}) does not outperform "
        f"best individual ({best_individual_ndcg:.4f})"
    )


# ── Test: fusion method specified ────────────────────────────────────────

def test_fusion_metadata(results):
    """Verify fusion metadata fields exist and are valid."""
    assert "fusion_method" in results and isinstance(results["fusion_method"], str), \
        "fusion_method must be a non-empty string"
    assert "fusion_k" in results and isinstance(results["fusion_k"], int), \
        "fusion_k must be an integer"
    assert 1 <= results["fusion_k"] <= 1000, \
        "fusion_k must be between 1 and 1000"
