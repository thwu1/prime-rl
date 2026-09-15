"""Verify retrieval system produces correct, high-quality results on BRIGHT Pony task."""

import base64
import json
import os
import zlib

import pytrec_eval
import pytest


EVAL_DIR = "/app/.bright_eval"


def _decode_ground_truth():
    """Load and decode the per-instance ground truth from compressed binary."""
    gt_path = os.path.join(EVAL_DIR, "ground_truth.bin")
    assert os.path.isfile(gt_path), f"Ground truth not found at {gt_path}"
    with open(gt_path, "rb") as f:
        encoded = f.read()
    decompressed = zlib.decompress(base64.b64decode(encoded))
    return json.loads(decompressed)


@pytest.fixture
def scores():
    """Load the agent's retrieval scores."""
    scores_path = "/app/scores.json"
    assert os.path.isfile(scores_path), f"Scores file not found at {scores_path}"
    with open(scores_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "scores.json must be a JSON object"
    return data


@pytest.fixture
def ground_truth():
    """Load hidden ground truth relevance judgments (encoded with DNA)."""
    return _decode_ground_truth()


@pytest.fixture
def queries():
    """Load query metadata for validation."""
    q_path = "/app/data/queries.json"
    with open(q_path) as f:
        return json.load(f)


@pytest.fixture
def dna():
    """Load the per-instance DNA seed."""
    dna_path = os.path.join(EVAL_DIR, "dna.txt")
    assert os.path.isfile(dna_path), f"DNA file not found at {dna_path}"
    with open(dna_path) as f:
        return f.read().strip()


class TestDNAIntegrity:
    """Verify DNA is present and document IDs reflect the per-instance prefix."""

    def test_dna_exists(self, dna):
        assert len(dna) == 8, f"DNA must be 8 hex chars, got '{dna}'"
        int(dna, 16)  # Must be valid hex

    def test_doc_ids_have_dna_prefix(self, scores, dna):
        prefix = dna[:4]
        sample_ids = []
        for qid, doc_scores in scores.items():
            sample_ids.extend(list(doc_scores.keys())[:3])
            if len(sample_ids) >= 10:
                break
        assert len(sample_ids) > 0, "No document IDs found in scores"
        for did in sample_ids:
            assert did.startswith(prefix + "_"), (
                f"Doc ID '{did}' does not start with DNA prefix '{prefix}_'. "
                f"Scores must use the document IDs from /app/data/documents.json."
            )


class TestScoresFormat:
    """Validate the structure of scores.json."""

    def test_valid_json_structure(self, scores):
        for qid, doc_scores in scores.items():
            assert isinstance(qid, str), f"Query ID must be string, got {type(qid)}"
            assert isinstance(doc_scores, dict), (
                f"Doc scores for query {qid} must be a dict"
            )
            for did, s in doc_scores.items():
                assert isinstance(did, str), f"Doc ID must be string in query {qid}"
                assert isinstance(s, (int, float)), (
                    f"Score must be numeric in query {qid}, doc {did}"
                )

    def test_all_queries_covered(self, scores, queries):
        expected_ids = {q["id"] for q in queries}
        actual_ids = set(scores.keys())
        missing = expected_ids - actual_ids
        assert len(missing) == 0, (
            f"Missing {len(missing)} query IDs from scores: {missing}"
        )

    def test_nonempty_results_per_query(self, scores):
        for qid, doc_scores in scores.items():
            assert len(doc_scores) > 0, f"Query {qid} has no document scores"


class TestExcludedIds:
    """Verify excluded document IDs are properly filtered."""

    def test_excluded_ids_absent(self, scores, queries):
        for q in queries:
            qid = q["id"]
            if qid in scores:
                excluded = set(q.get("excluded_ids", []))
                present = excluded & set(scores[qid].keys())
                assert len(present) == 0, (
                    f"Query {qid} has {len(present)} excluded docs in results: "
                    f"{list(present)[:5]}"
                )


class TestRetrievalQuality:
    """Evaluate retrieval quality against per-instance ground truth."""

    def test_ndcg_at_10(self, scores, ground_truth):
        evaluator = pytrec_eval.RelevanceEvaluator(
            ground_truth, {"ndcg_cut.10"}
        )
        results = evaluator.evaluate(scores)
        assert len(results) > 0, "No queries were evaluated"
        ndcg_10 = sum(r["ndcg_cut_10"] for r in results.values()) / len(results)
        assert ndcg_10 >= 0.20, (
            f"nDCG@10 = {ndcg_10:.5f}, required >= 0.20"
        )
