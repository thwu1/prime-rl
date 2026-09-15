
"""Tests for corrected IR evaluation report at /app/corrected_report.json.

Reference metric values are computed independently from the raw experiment
data using standard IR evaluation methodology (trec_eval-compatible):
  - nDCG@10: gain=2^rel-1, discount=log2(rank+1), IDCG from ALL qrels
  - MAP: binary relevance (rel>=1), denominator = total relevant in qrels
  - ERR@10: global max relevance grade across all queries
  - Unjudged documents treated as relevance 0
"""

import json
import math
import os
import pytest


CORRECTED_PATH = "/app/corrected_report.json"
PUBLISHED_PATH = "/app/published_report.json"
QRELS_PATH = "/app/experiment/qrels.txt"
EXP_DIR = "/app/experiment"
TOL = 0.005


@pytest.fixture(scope="module")
def corrected():
    assert os.path.isfile(CORRECTED_PATH), \
        f"Corrected report not found at {CORRECTED_PATH}"
    with open(CORRECTED_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def published():
    with open(PUBLISHED_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference():
    """Compute reference metric values independently from raw data."""
    # Parse qrels
    qrels = {}
    with open(QRELS_PATH) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                qid, did, rel = parts[0], parts[2], int(parts[3])
                qrels.setdefault(qid, {})[did] = rel

    global_max_rel = max(r for j in qrels.values() for r in j.values())
    query_ids = sorted(qrels.keys())

    # Parse run files
    runs = {}
    for fname in sorted(os.listdir(EXP_DIR)):
        if not fname.endswith(".run"):
            continue
        sname = fname[:-4]
        run = {}
        with open(os.path.join(EXP_DIR, fname)) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6:
                    qid, did, score = parts[0], parts[2], float(parts[4])
                    run.setdefault(qid, []).append((did, score))
        for qid in run:
            run[qid].sort(key=lambda x: -x[1])
        runs[sname] = run

    # Compute reference metrics for each system
    systems = {}
    for sname in sorted(runs.keys()):
        run = runs[sname]
        pq = {}
        nvals, evals, avals = [], [], []

        for qid in query_ids:
            ranked = run.get(qid, [])
            judg = qrels[qid]

            # --- nDCG@10 ---
            rels = [judg.get(doc, 0) for doc, _ in ranked[:10]]
            dcg = sum(
                (2**r - 1) / math.log2(i + 2)
                for i, r in enumerate(rels)
            )
            ideal = sorted(judg.values(), reverse=True)
            idcg = sum(
                (2**r - 1) / math.log2(i + 2)
                for i, r in enumerate(ideal[:10])
            )
            ndcg_val = dcg / idcg if idcg > 0 else 0.0

            # --- ERR@10 ---
            err_val = 0.0
            p = 1.0
            for i, (doc, _) in enumerate(ranked[:10]):
                rel = judg.get(doc, 0)
                r_i = (2**rel - 1) / (2**global_max_rel)
                err_val += p * r_i / (i + 1)
                p *= (1 - r_i)

            # --- AP (for MAP) ---
            total_rel = sum(1 for r in judg.values() if r >= 1)
            ap_val = 0.0
            if total_rel > 0:
                count = 0
                for i, (doc, _) in enumerate(ranked):
                    if judg.get(doc, 0) >= 1:
                        count += 1
                        ap_val += count / (i + 1)
                ap_val /= total_rel

            nvals.append(ndcg_val)
            evals.append(err_val)
            avals.append(ap_val)
            pq[qid] = {
                "ndcg@10": round(ndcg_val, 4),
                "err@10": round(err_val, 4),
                "ap": round(ap_val, 4),
            }

        nq = len(query_ids)
        systems[sname] = {
            "ndcg@10": round(sum(nvals) / nq, 4),
            "err@10": round(sum(evals) / nq, 4),
            "map": round(sum(avals) / nq, 4),
            "per_query": pq,
        }

    ranking = sorted(systems.keys(), key=lambda s: -systems[s]["ndcg@10"])
    return {"systems": systems, "ranking": ranking}


# ── Schema validation ──

class TestSchema:
    def test_top_level_keys(self, corrected):
        assert "systems" in corrected
        assert "ranking" in corrected

    def test_system_names(self, corrected):
        expected = {"system_alpha", "system_beta", "system_gamma"}
        assert set(corrected["systems"].keys()) == expected

    def test_system_metrics_present(self, corrected):
        for sname, data in corrected["systems"].items():
            for m in ("ndcg@10", "err@10", "map"):
                assert m in data, f"{sname} missing {m}"
            assert "per_query" in data, f"{sname} missing per_query"

    def test_per_query_ids(self, corrected):
        expected_qids = {f"q{i:03d}" for i in range(1, 13)}
        for sname, data in corrected["systems"].items():
            assert set(data["per_query"].keys()) == expected_qids, \
                f"{sname} has wrong query ID set"

    def test_per_query_metrics_present(self, corrected):
        for sname, data in corrected["systems"].items():
            for qid, pq in data["per_query"].items():
                for m in ("ndcg@10", "err@10", "ap"):
                    assert m in pq, f"{sname}/{qid} missing {m}"

    def test_ranking_length(self, corrected):
        assert isinstance(corrected["ranking"], list)
        assert len(corrected["ranking"]) == 3


# ── Aggregate metric correctness ──

class TestAggregateMetrics:
    def test_ndcg_all_systems(self, corrected, reference):
        for sname in reference["systems"]:
            actual = corrected["systems"][sname]["ndcg@10"]
            expected = reference["systems"][sname]["ndcg@10"]
            assert abs(actual - expected) < TOL, \
                f"{sname} nDCG@10: got {actual}, expected {expected}"

    def test_map_all_systems(self, corrected, reference):
        for sname in reference["systems"]:
            actual = corrected["systems"][sname]["map"]
            expected = reference["systems"][sname]["map"]
            assert abs(actual - expected) < TOL, \
                f"{sname} MAP: got {actual}, expected {expected}"

    def test_err_all_systems(self, corrected, reference):
        for sname in reference["systems"]:
            actual = corrected["systems"][sname]["err@10"]
            expected = reference["systems"][sname]["err@10"]
            assert abs(actual - expected) < TOL, \
                f"{sname} ERR@10: got {actual}, expected {expected}"


# ── Per-query metric correctness ──

class TestPerQueryMetrics:
    def test_per_query_ndcg(self, corrected, reference):
        for sname in reference["systems"]:
            for qid in reference["systems"][sname]["per_query"]:
                actual = corrected["systems"][sname]["per_query"][qid]["ndcg@10"]
                expected = reference["systems"][sname]["per_query"][qid]["ndcg@10"]
                assert abs(actual - expected) < TOL, \
                    f"{sname}/{qid} nDCG@10: got {actual}, expected {expected}"

    def test_per_query_err(self, corrected, reference):
        for sname in reference["systems"]:
            for qid in reference["systems"][sname]["per_query"]:
                actual = corrected["systems"][sname]["per_query"][qid]["err@10"]
                expected = reference["systems"][sname]["per_query"][qid]["err@10"]
                assert abs(actual - expected) < TOL, \
                    f"{sname}/{qid} ERR@10: got {actual}, expected {expected}"

    def test_per_query_ap(self, corrected, reference):
        for sname in reference["systems"]:
            for qid in reference["systems"][sname]["per_query"]:
                actual = corrected["systems"][sname]["per_query"][qid]["ap"]
                expected = reference["systems"][sname]["per_query"][qid]["ap"]
                assert abs(actual - expected) < TOL, \
                    f"{sname}/{qid} AP: got {actual}, expected {expected}"


# ── Ranking correctness ──

class TestRanking:
    def test_ranking_order(self, corrected, reference):
        assert corrected["ranking"] == reference["ranking"], \
            f"Ranking mismatch: got {corrected['ranking']}, " \
            f"expected {reference['ranking']}"

    def test_ranking_consistent_with_ndcg(self, corrected):
        ranking = corrected["ranking"]
        for i in range(len(ranking) - 1):
            val_i = corrected["systems"][ranking[i]]["ndcg@10"]
            val_next = corrected["systems"][ranking[i + 1]]["ndcg@10"]
            assert val_i >= val_next - TOL, \
                f"Ranking inconsistent: {ranking[i]}={val_i} < " \
                f"{ranking[i+1]}={val_next}"


# ── Metric range and consistency ──

class TestConsistency:
    def test_metric_ranges(self, corrected):
        for sname, data in corrected["systems"].items():
            for m in ("ndcg@10", "err@10", "map"):
                assert 0.0 <= data[m] <= 1.0, \
                    f"{sname} {m} out of range: {data[m]}"
            for qid, pq in data["per_query"].items():
                for m in ("ndcg@10", "err@10", "ap"):
                    assert 0.0 <= pq[m] <= 1.0, \
                        f"{sname}/{qid} {m} out of range: {pq[m]}"

    def test_aggregate_is_mean_ndcg(self, corrected):
        for sname, data in corrected["systems"].items():
            pq_vals = [pq["ndcg@10"] for pq in data["per_query"].values()]
            expected = sum(pq_vals) / len(pq_vals)
            assert abs(data["ndcg@10"] - expected) < TOL, \
                f"{sname} nDCG@10 aggregate != mean of per-query"

    def test_aggregate_is_mean_err(self, corrected):
        for sname, data in corrected["systems"].items():
            pq_vals = [pq["err@10"] for pq in data["per_query"].values()]
            expected = sum(pq_vals) / len(pq_vals)
            assert abs(data["err@10"] - expected) < TOL, \
                f"{sname} ERR@10 aggregate != mean of per-query"

    def test_aggregate_is_mean_ap(self, corrected):
        for sname, data in corrected["systems"].items():
            pq_vals = [pq["ap"] for pq in data["per_query"].values()]
            expected = sum(pq_vals) / len(pq_vals)
            assert abs(data["map"] - expected) < TOL, \
                f"{sname} MAP aggregate != mean of per-query AP"


# ── Anti-cheat ──

class TestAntiCheat:
    def test_corrected_differs_from_published(self, corrected, published):
        """Corrected report must differ from the buggy published report."""
        diffs = 0
        for sname in published["systems"]:
            for m in ("ndcg@10", "map", "err@10"):
                pub_val = published["systems"][sname][m]
                cor_val = corrected["systems"][sname][m]
                if abs(pub_val - cor_val) > 0.001:
                    diffs += 1
        assert diffs >= 3, \
            "Corrected report too similar to published — " \
            "at least 3 aggregate metrics should differ"

    def test_ndcg_not_inflated(self, corrected, published):
        """Correct nDCG should generally be lower than the buggy version
        (buggy IDCG denominator was too small, inflating nDCG)."""
        deflated = 0
        for sname in corrected["systems"]:
            if corrected["systems"][sname]["ndcg@10"] < \
               published["systems"][sname]["ndcg@10"] - 0.001:
                deflated += 1
        assert deflated >= 2, \
            "Expected corrected nDCG to be lower than published for " \
            "most systems (IDCG fix)"
