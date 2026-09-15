"""Verify CRUMB evaluation pipeline results.

"""
import json
import math
import os
from collections import defaultdict

import numpy as np
import pytest

DATA_DIR = "/opt/crumb_eval/data"


# ---- Correct reference implementation ----

def _load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_parent_map():
    """Build parent map, resolving null parent_ids from passage ID prefix."""
    parent_map = {}
    for item in _load_jsonl(os.path.join(DATA_DIR, "corpus.jsonl")):
        pid = item["parent_id"]
        if pid is None:
            pid = item["document_id"].split(":")[0]
        parent_map[item["document_id"]] = pid
    return parent_map


def _load_qrels():
    """Load qrels with whitespace normalization on document IDs."""
    qrels = {}
    for item in _load_jsonl(os.path.join(DATA_DIR, "qrels.jsonl")):
        qid = item["query_id"]
        qrels[qid] = {}
        for qr in item["qrels"]:
            doc_id = qr["id"].strip()
            qrels[qid][doc_id] = qr["label"]
    return qrels


def _maxp_run(run_path, parent_map):
    """Load run, deduplicate passages, and apply MaxP aggregation."""
    result = {}
    for item in _load_jsonl(run_path):
        qid = item["query"]["id"]
        # Deduplicate: keep highest score per passage ID
        passage_scores = {}
        for p in item["items"]:
            pid = p["id"]
            score = p["score"]
            if pid not in passage_scores or score > passage_scores[pid]:
                passage_scores[pid] = score
        # MaxP: max score per parent document
        doc_scores = defaultdict(float)
        for pid, score in passage_scores.items():
            parent = parent_map.get(pid, pid.split(":")[0])
            doc_scores[parent] = max(doc_scores[parent], score)
        result[qid] = sorted(doc_scores.items(), key=lambda x: (-x[1], x[0]))
    return result


def _dcg(ranking, qrels, k):
    total = 0.0
    for i, (doc_id, _) in enumerate(ranking[:k]):
        rel = qrels.get(doc_id, 0)
        gain = 2 ** rel - 1
        discount = math.log2(i + 2)
        total += gain / discount
    return total


def _ndcg(ranking, qrels, k):
    ideal = sorted(qrels.items(), key=lambda x: (-x[1], x[0]))
    idcg = 0.0
    for i, (_, rel) in enumerate(ideal[:k]):
        idcg += (2 ** rel - 1) / math.log2(i + 2)
    if idcg == 0:
        return 0.0
    return _dcg(ranking, qrels, k) / idcg


def _recall(ranking, qrels, k):
    relevant = {d for d, r in qrels.items() if r >= 1}
    if not relevant:
        return 0.0
    return sum(1 for d, _ in ranking[:k] if d in relevant) / len(relevant)


def _permutation_test(vals_a, vals_b, n_perm=10000, seed=42):
    np.random.seed(seed)
    a, b = np.array(vals_a), np.array(vals_b)
    obs = np.mean(a) - np.mean(b)
    count = 0
    for _ in range(n_perm):
        mask = np.random.randint(0, 2, len(a)).astype(bool)
        pa = np.where(mask, b, a)
        pb = np.where(mask, a, b)
        if abs(np.mean(pa) - np.mean(pb)) >= abs(obs):
            count += 1
    return count / n_perm


# ---- Compute reference values ----

@pytest.fixture(scope="module")
def reference():
    parent_map = _build_parent_map()
    qrels = _load_qrels()
    qids = sorted(qrels.keys())

    runs_dir = os.path.join(DATA_DIR, "runs")
    run_names = sorted(
        f[:-6] for f in os.listdir(runs_dir) if f.endswith(".jsonl")
    )

    per_run = {}
    pq_ndcg = {}

    for rn in run_names:
        run = _maxp_run(os.path.join(runs_dir, f"{rn}.jsonl"), parent_map)
        ndcgs = []
        recalls = []
        for qid in qids:
            ranking = run.get(qid, [])
            qr = qrels.get(qid, {})
            ndcgs.append(_ndcg(ranking, qr, 10))
            recalls.append(_recall(ranking, qr, 100))
        per_run[rn] = {
            "ndcg@10": round(sum(ndcgs) / len(ndcgs), 4),
            "recall@100": round(sum(recalls) / len(recalls), 4),
        }
        pq_ndcg[rn] = ndcgs

    sig = {}
    for i, ra in enumerate(run_names):
        for j, rb in enumerate(run_names):
            if i >= j:
                continue
            pv = _permutation_test(pq_ndcg[ra], pq_ndcg[rb])
            sig[f"{ra}_vs_{rb}"] = {
                "p_value": round(pv, 4),
                "significant": pv < 0.05,
            }

    ranking = sorted(run_names, key=lambda r: -per_run[r]["ndcg@10"])

    return {
        "per_run_metrics": per_run,
        "significance_matrix": sig,
        "ranking": ranking,
    }


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---- Tests ----

def test_results_file_exists():
    assert os.path.isfile("/app/results.json"), "/app/results.json not found"


def test_structure(results):
    assert "per_run_metrics" in results, "Missing 'per_run_metrics' key"
    assert "significance_matrix" in results, "Missing 'significance_matrix' key"
    assert "ranking" in results, "Missing 'ranking' key"


def test_all_runs_present(results):
    for rn in ["run_0", "run_1", "run_2", "run_3"]:
        assert rn in results["per_run_metrics"], f"{rn} missing from per_run_metrics"


def test_metric_keys(results):
    for rn, metrics in results["per_run_metrics"].items():
        assert "ndcg@10" in metrics, f"ndcg@10 missing for {rn}"
        assert "recall@100" in metrics, f"recall@100 missing for {rn}"


def test_ndcg_values(results, reference):
    for rn in ["run_0", "run_1", "run_2", "run_3"]:
        expected = reference["per_run_metrics"][rn]["ndcg@10"]
        actual = results["per_run_metrics"][rn]["ndcg@10"]
        assert abs(expected - actual) < 0.003, (
            f"nDCG@10 for {rn}: expected {expected}, got {actual}"
        )


def test_recall_values(results, reference):
    for rn in ["run_0", "run_1", "run_2", "run_3"]:
        expected = reference["per_run_metrics"][rn]["recall@100"]
        actual = results["per_run_metrics"][rn]["recall@100"]
        assert abs(expected - actual) < 0.003, (
            f"Recall@100 for {rn}: expected {expected}, got {actual}"
        )


def test_ranking(results, reference):
    assert results["ranking"] == reference["ranking"], (
        f"Ranking mismatch: expected {reference['ranking']}, got {results['ranking']}"
    )


def test_significance_matrix_keys(results):
    expected_keys = {
        "run_0_vs_run_1", "run_0_vs_run_2", "run_0_vs_run_3",
        "run_1_vs_run_2", "run_1_vs_run_3", "run_2_vs_run_3",
    }
    assert set(results["significance_matrix"].keys()) == expected_keys, (
        f"Expected keys {expected_keys}, "
        f"got {set(results['significance_matrix'].keys())}"
    )


def test_pvalues(results, reference):
    for key in reference["significance_matrix"]:
        expected = reference["significance_matrix"][key]["p_value"]
        actual = results["significance_matrix"][key]["p_value"]
        assert abs(expected - actual) < 0.025, (
            f"p-value for {key}: expected {expected}, got {actual}"
        )


def test_significance_flags(results, reference):
    for key in reference["significance_matrix"]:
        ref_p = reference["significance_matrix"][key]["p_value"]
        # Only assert significance for clear-cut cases
        if ref_p < 0.01 or ref_p > 0.10:
            expected = reference["significance_matrix"][key]["significant"]
            actual = results["significance_matrix"][key]["significant"]
            assert expected == actual, (
                f"Significance for {key}: expected {expected}, got {actual} "
                f"(ref p={ref_p})"
            )


def test_results_differ_from_buggy(results):
    """Verify the output differs from the known-buggy initial results."""
    buggy_path = "/opt/crumb_eval/output/initial_results.json"
    if not os.path.isfile(buggy_path):
        pytest.skip("No initial_results.json to compare against")
    with open(buggy_path) as f:
        buggy = json.load(f)
    diffs = 0
    for rn in ["run_0", "run_1", "run_2", "run_3"]:
        if rn in buggy.get("per_run_metrics", {}):
            if abs(results["per_run_metrics"][rn]["ndcg@10"]
                   - buggy["per_run_metrics"][rn]["ndcg@10"]) > 0.005:
                diffs += 1
    assert diffs > 0, (
        "Results appear identical to the buggy initial output — "
        "pipeline defects may not have been corrected"
    )
