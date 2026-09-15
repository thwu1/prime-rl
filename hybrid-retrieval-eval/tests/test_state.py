
import json
import os

import numpy as np
import pytrec_eval
import pytest


def _download_ground_truth():
    """Download relevance labels from HuggingFace at verification time.

    Ground truth (gold_ids) is NEVER present in the agent's environment.
    It is fetched here exclusively for test-time evaluation.
    """
    from huggingface_hub import hf_hub_download
    import pandas as pd

    path = hf_hub_download(
        repo_id="xlangai/BRIGHT",
        filename="examples/pony-00000-of-00001.parquet",
        repo_type="dataset",
    )
    df = pd.read_parquet(path)
    qrels = {}
    excluded_map = {}
    for _, row in df.iterrows():
        qid = str(row["id"])
        gold = row["gold_ids"]
        excluded = row["excluded_ids"]
        qrels[qid] = {str(gid): 1 for gid in gold} if gold is not None else {}
        excluded_map[qid] = (
            {str(x) for x in excluded} if excluded is not None else set()
        )
    return qrels, excluded_map


@pytest.fixture(scope="module")
def ground_truth():
    return _download_ground_truth()


@pytest.fixture(scope="module")
def scores():
    with open("/app/results/scores.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def examples():
    with open("/app/data/examples.json") as f:
        return json.load(f)


def _compute_ndcg10(run_scores, qrels):
    evaluator = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut.10"})
    per_query = evaluator.evaluate(run_scores)
    return round(
        sum(v["ndcg_cut_10"] for v in per_query.values()) / len(per_query), 5
    )


# ---------------------------------------------------------------------------
# 1. Output file existence and basic validity
# ---------------------------------------------------------------------------

class TestOutputFiles:

    def test_scores_file_exists(self):
        assert os.path.isfile("/app/results/scores.json"), \
            "scores.json not found at /app/results/scores.json"

    def test_scores_valid_json(self):
        with open("/app/results/scores.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "scores.json root must be a dict"


# ---------------------------------------------------------------------------
# 2. Score format and completeness
# ---------------------------------------------------------------------------

class TestScoresFormat:

    def test_all_queries_present(self, scores, examples):
        query_ids = {str(e["id"]) for e in examples}
        missing = query_ids - set(scores.keys())
        assert len(missing) == 0, \
            f"{len(missing)} queries missing from scores: {list(missing)[:5]}"

    def test_scores_are_numeric(self, scores):
        for qid, doc_scores in list(scores.items())[:10]:
            for did, score in list(doc_scores.items())[:10]:
                assert isinstance(score, (int, float)), \
                    f"Score for query {qid}, doc {did} is {type(score).__name__}"

    def test_top1000_limit(self, scores):
        over = {qid: len(ds) for qid, ds in scores.items() if len(ds) > 1000}
        assert len(over) == 0, \
            f"{len(over)} queries exceed 1000 docs: {list(over.keys())[:3]}"


# ---------------------------------------------------------------------------
# 3. Excluded-ID filtering
# ---------------------------------------------------------------------------

class TestExcludedIds:

    def test_excluded_ids_absent(self, scores, examples):
        violations = []
        for e in examples:
            qid = str(e["id"])
            if qid in scores:
                for excl_id in e.get("excluded_ids", []):
                    if str(excl_id) in scores[qid]:
                        violations.append((qid, excl_id))
        assert len(violations) == 0, \
            f"{len(violations)} excluded doc IDs found in scores: {violations[:5]}"


# ---------------------------------------------------------------------------
# 4. Anti-cheat: verify genuine retrieval, not fabricated scores
# ---------------------------------------------------------------------------

class TestAntiCheat:

    def test_sufficient_docs_per_query(self, scores):
        """Genuine retrieval scores hundreds of documents, not just a few."""
        min_docs = 100
        low_count = sum(1 for ds in scores.values() if len(ds) < min_docs)
        assert low_count < len(scores) * 0.05, \
            f"{low_count}/{len(scores)} queries have < {min_docs} scored docs"

    def test_score_variance(self, scores):
        """Real retrieval produces non-trivial score variance per query."""
        zero_var = 0
        for qid, doc_scores in scores.items():
            vals = list(doc_scores.values())
            if len(vals) > 20:
                if np.std(vals) < 1e-6:
                    zero_var += 1
        assert zero_var < len(scores) * 0.05, \
            f"{zero_var}/{len(scores)} queries have near-zero score variance"

    def test_score_diversity(self, scores):
        """Scores should have many distinct values (not a few fabricated ones)."""
        low_diversity = 0
        for qid, doc_scores in scores.items():
            vals = list(doc_scores.values())
            if len(vals) > 50:
                unique_vals = len(set(round(v, 6) for v in vals))
                if unique_vals < 20:
                    low_diversity += 1
        assert low_diversity < len(scores) * 0.1, \
            f"{low_diversity}/{len(scores)} queries have < 20 distinct score values"

    def test_different_top_results_per_query(self, scores):
        """Different queries must retrieve different top-10 documents."""
        top10_sets = []
        for qid in sorted(scores.keys()):
            doc_scores = scores[qid]
            sorted_docs = sorted(
                doc_scores.items(), key=lambda x: x[1], reverse=True
            )[:10]
            top10_sets.append(frozenset(d[0] for d in sorted_docs))
        unique_ratio = len(set(top10_sets)) / max(len(top10_sets), 1)
        assert unique_ratio > 0.5, \
            f"Only {unique_ratio:.1%} of queries have unique top-10 doc sets — " \
            "genuine retrieval produces diverse results per query"

    def test_no_suspiciously_perfect_retrieval(self, scores, ground_truth):
        """nDCG@10 must not exceed what the best known systems achieve.

        Even top systems with LLM-based reasoning achieve ~0.50 on BRIGHT.
        Scores above this indicate exploitation of ground truth.
        """
        qrels, _ = ground_truth
        ndcg10 = _compute_ndcg10(scores, qrels)
        assert ndcg10 < 0.55, \
            f"nDCG@10 = {ndcg10:.4f} is suspiciously high — " \
            "top reasoning-enhanced systems achieve ~0.50 on BRIGHT"


# ---------------------------------------------------------------------------
# 5. Retrieval quality threshold (evaluated against held-out ground truth)
# ---------------------------------------------------------------------------

class TestMetricsThreshold:

    def test_ndcg10_above_minimum(self, scores, ground_truth):
        """nDCG@10 must meet the minimum threshold of 0.10."""
        qrels, _ = ground_truth
        ndcg10 = _compute_ndcg10(scores, qrels)
        assert ndcg10 >= 0.10, \
            f"nDCG@10 = {ndcg10:.5f}, must be >= 0.10"
