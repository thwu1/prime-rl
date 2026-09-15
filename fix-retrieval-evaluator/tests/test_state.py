"""Tests for retrieval evaluation and fusion optimization correctness.

Independently loads benchmark data, fixes known issues, computes reference
metrics using pytrec_eval, and verifies the agent's results.json matches.
"""

import json
import os

import pytest
import pytrec_eval


TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Reference implementations (correct)
# ---------------------------------------------------------------------------

def _load_trec_qrels(path):
    """Load qrels with graded relevance (no binarization)."""
    qrels = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, docid, rel = parts[0], parts[2], int(parts[3])
            qrels.setdefault(qid, {})[docid] = rel
    return qrels


def _load_trec_run(path):
    """Load TREC run with column format auto-detection."""
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]

    # Detect whether columns 3 and 4 are swapped by checking types
    col3_vals = []
    col4_vals = []
    for line in lines[:60]:
        parts = line.split()
        if len(parts) >= 6:
            col3_vals.append(parts[3])
            col4_vals.append(parts[4])

    col3_has_decimals = sum(1 for v in col3_vals if '.' in v) > len(col3_vals) * 0.5
    col4_all_integers = all(v.replace('-', '').isdigit() for v in col4_vals)

    score_col = 3 if (col3_has_decimals and col4_all_integers) else 4

    results = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        qid = parts[0]
        docid = parts[2]
        score = float(parts[score_col])
        results.setdefault(qid, {})[docid] = score
    return results


def _evaluate(qrels, results, k_values=(5, 10)):
    """Compute metrics using pytrec_eval with graded relevance."""
    measures = set()
    measures.add("ndcg_cut." + ",".join(str(k) for k in k_values))
    measures.add("map_cut.10")
    measures.add("recip_rank")

    evaluator = pytrec_eval.RelevanceEvaluator(qrels, measures)
    scores = evaluator.evaluate(results)

    out = {}
    for k in k_values:
        vals = [scores[q][f"ndcg_cut_{k}"] for q in scores]
        out[f"nDCG@{k}"] = sum(vals) / len(vals) if vals else 0.0
    vals = [scores[q]["map_cut_10"] for q in scores]
    out["MAP@10"] = sum(vals) / len(vals) if vals else 0.0
    vals = [scores[q]["recip_rank"] for q in scores]
    out["MRR"] = sum(vals) / len(vals) if vals else 0.0
    return out


def _rrf(runs, k=60):
    """Reference Reciprocal Rank Fusion."""
    fused = {}
    for run in runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for rank_idx, (did, _) in enumerate(ranked):
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += 1.0 / (k + rank_idx + 1)
    return fused


def _normalize(run):
    """Min-max normalize per query to [0, 1]."""
    normalized = {}
    for qid, scores in run.items():
        if not scores:
            normalized[qid] = {}
            continue
        vals = list(scores.values())
        min_s, max_s = min(vals), max(vals)
        rng = max_s - min_s
        if rng == 0:
            normalized[qid] = {did: 0.5 for did in scores}
        else:
            normalized[qid] = {did: (s - min_s) / rng for did, s in scores.items()}
    return normalized


def _combsum(runs):
    """Reference CombSUM with min-max normalization."""
    norm_runs = [_normalize(r) for r in runs]
    fused = {}
    for run in norm_runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += s
    return fused


def _combmnz(runs):
    """Reference CombMNZ with min-max normalization."""
    norm_runs = [_normalize(r) for r in runs]
    fused = {}
    counts = {}
    for run in norm_runs:
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            counts.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += s
                counts[qid].setdefault(did, 0)
                counts[qid][did] += 1
    for qid in fused:
        for did in fused[qid]:
            fused[qid][did] *= counts[qid][did]
    return fused


def _weighted_combsum(runs, model_weights):
    """Reference Weighted CombSUM with per-model weights."""
    norm_runs = [_normalize(r) for r in runs]
    fused = {}
    for i, run in enumerate(norm_runs):
        w = model_weights[i]
        for qid, scores in run.items():
            fused.setdefault(qid, {})
            for did, s in scores.items():
                fused[qid].setdefault(did, 0.0)
                fused[qid][did] += w * s
    return fused


def _domain_ndcg10(qrels, fused, qids):
    """Compute mean nDCG@10 for a set of query IDs."""
    d_qrels = {q: qrels[q] for q in qids if q in qrels}
    d_results = {q: fused[q] for q in qids if q in fused}
    if not d_qrels or not d_results:
        return 0.0
    evaluator = pytrec_eval.RelevanceEvaluator(d_qrels, {"ndcg_cut.10"})
    scores = evaluator.evaluate(d_results)
    vals = [scores[q]["ndcg_cut_10"] for q in scores]
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reference_data():
    """Load data and compute all reference metrics."""
    qrels = _load_trec_qrels("/app/data/qrels.txt")

    queries = []
    with open("/app/data/queries.jsonl") as f:
        for line in f:
            if line.strip():
                queries.append(json.loads(line))

    model_names = ["bm25", "dense", "sparse", "reranker"]
    runs = {}
    for m in model_names:
        runs[m] = _load_trec_run(f"/app/data/runs/{m}.trec")

    # Baseline metrics
    domain_qids = {}
    for q in queries:
        domain_qids.setdefault(q["domain"], []).append(q["id"])

    ref_baselines = {}
    for m, run in runs.items():
        overall = _evaluate(qrels, run)
        per_domain = {}
        for domain, qids in domain_qids.items():
            d_qrels = {q: qrels[q] for q in qids if q in qrels}
            d_run = {q: run[q] for q in qids if q in run}
            if d_qrels and d_run:
                per_domain[domain] = _evaluate(d_qrels, d_run)
        ref_baselines[m] = {"overall": overall, "per_domain": per_domain}

    # Fusion optimization (7 methods per domain)
    run_list = [runs[m] for m in model_names]

    ref_fusion_opt = {}
    for domain, qids in domain_qids.items():
        domain_results = {}

        # RRF variants
        for k in [10, 30, 60, 100]:
            fused = _rrf(run_list, k=k)
            domain_results[f"rrf_k{k}"] = _domain_ndcg10(qrels, fused, qids)

        # CombSUM
        fused = _combsum(run_list)
        domain_results["combsum"] = _domain_ndcg10(qrels, fused, qids)

        # CombMNZ
        fused = _combmnz(run_list)
        domain_results["combmnz"] = _domain_ndcg10(qrels, fused, qids)

        # Weighted CombSUM (weights = per-domain baseline nDCG@10)
        weights = [ref_baselines[m]["per_domain"][domain]["nDCG@10"]
                   for m in model_names]
        fused = _weighted_combsum(run_list, weights)
        domain_results["weighted_combsum"] = _domain_ndcg10(qrels, fused, qids)

        best = max(domain_results, key=domain_results.get)
        ref_fusion_opt[domain] = {
            "best_method": best,
            "best_ndcg10": domain_results[best],
            "all_methods": domain_results,
        }

    # Optimized fusion (per-domain best applied)
    combined = {}
    for domain, qids in domain_qids.items():
        best = ref_fusion_opt[domain]["best_method"]
        if best.startswith("rrf_k"):
            k = int(best.replace("rrf_k", ""))
            fused = _rrf(run_list, k=k)
        elif best == "combsum":
            fused = _combsum(run_list)
        elif best == "combmnz":
            fused = _combmnz(run_list)
        elif best == "weighted_combsum":
            weights = [ref_baselines[m]["per_domain"][domain]["nDCG@10"]
                       for m in model_names]
            fused = _weighted_combsum(run_list, weights)
        else:
            raise ValueError(f"Unknown method: {best}")
        for qid in qids:
            if qid in fused:
                combined[qid] = fused[qid]

    ref_optimized = {"overall": _evaluate(qrels, combined), "per_domain": {}}
    for domain, qids in domain_qids.items():
        d_qrels = {q: qrels[q] for q in qids if q in qrels}
        d_run = {q: combined[q] for q in qids if q in combined}
        if d_qrels and d_run:
            ref_optimized["per_domain"][domain] = _evaluate(d_qrels, d_run)

    # Binary-relevance baseline for comparison
    binary_qrels = {qid: {did: (1 if r > 0 else 0) for did, r in docs.items()}
                    for qid, docs in qrels.items()}
    ref_binary = {}
    for m, run in runs.items():
        ref_binary[m] = _evaluate(binary_qrels, run)

    return {
        "baselines": ref_baselines,
        "fusion_opt": ref_fusion_opt,
        "optimized": ref_optimized,
        "binary_baselines": ref_binary,
        "graded_qrels": qrels,
    }


@pytest.fixture(scope="module")
def agent_results():
    """Load agent's output."""
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestResultsExist:
    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"


class TestResultsStructure:
    def test_has_baseline_metrics(self, agent_results):
        assert "baseline_metrics" in agent_results

    def test_has_all_models(self, agent_results):
        for model in ["bm25", "dense", "sparse", "reranker"]:
            assert model in agent_results["baseline_metrics"], \
                f"Missing model: {model}"

    def test_model_has_overall_and_per_domain(self, agent_results):
        for model in ["bm25", "dense", "sparse", "reranker"]:
            m = agent_results["baseline_metrics"][model]
            assert "overall" in m, f"Missing 'overall' for {model}"
            assert "per_domain" in m, f"Missing 'per_domain' for {model}"

    def test_per_domain_has_all_domains(self, agent_results):
        for model in ["bm25", "dense", "sparse", "reranker"]:
            pd = agent_results["baseline_metrics"][model]["per_domain"]
            for domain in ["biology", "economics", "coding"]:
                assert domain in pd, f"Missing domain '{domain}' for {model}"

    def test_has_fusion_optimization(self, agent_results):
        assert "fusion_optimization" in agent_results
        for domain in ["biology", "economics", "coding"]:
            assert domain in agent_results["fusion_optimization"], \
                f"Missing domain '{domain}' in fusion_optimization"

    def test_has_optimized_fusion(self, agent_results):
        assert "optimized_fusion" in agent_results
        assert "overall" in agent_results["optimized_fusion"]
        assert "per_domain" in agent_results["optimized_fusion"]

    def test_metric_keys_present(self, agent_results):
        expected = {"nDCG@5", "nDCG@10", "MAP@10", "MRR"}
        for model in ["bm25", "dense", "sparse", "reranker"]:
            keys = set(agent_results["baseline_metrics"][model]["overall"].keys())
            assert expected.issubset(keys), \
                f"{model} overall missing keys: {expected - keys}"


# ---------------------------------------------------------------------------
# Baseline metric tests (catches both bugs: column swap + binary relevance)
# ---------------------------------------------------------------------------

class TestBaselineNDCG:
    @pytest.mark.parametrize("model", ["bm25", "dense", "sparse", "reranker"])
    @pytest.mark.parametrize("k", [5, 10])
    def test_ndcg(self, model, k, agent_results, reference_data):
        got = agent_results["baseline_metrics"][model]["overall"][f"nDCG@{k}"]
        expected = reference_data["baselines"][model]["overall"][f"nDCG@{k}"]
        assert abs(got - expected) < TOLERANCE, \
            f"{model} nDCG@{k}: got {got:.5f}, expected {expected:.5f}"


class TestBaselineMAP:
    @pytest.mark.parametrize("model", ["bm25", "dense", "sparse", "reranker"])
    def test_map10(self, model, agent_results, reference_data):
        got = agent_results["baseline_metrics"][model]["overall"]["MAP@10"]
        expected = reference_data["baselines"][model]["overall"]["MAP@10"]
        assert abs(got - expected) < TOLERANCE, \
            f"{model} MAP@10: got {got:.5f}, expected {expected:.5f}"


class TestBaselineMRR:
    @pytest.mark.parametrize("model", ["bm25", "dense", "sparse", "reranker"])
    def test_mrr(self, model, agent_results, reference_data):
        got = agent_results["baseline_metrics"][model]["overall"]["MRR"]
        expected = reference_data["baselines"][model]["overall"]["MRR"]
        assert abs(got - expected) < TOLERANCE, \
            f"{model} MRR: got {got:.5f}, expected {expected:.5f}"


class TestBaselinePerDomain:
    @pytest.mark.parametrize("model", ["bm25", "dense", "sparse", "reranker"])
    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_domain_ndcg10(self, model, domain, agent_results, reference_data):
        got = agent_results["baseline_metrics"][model]["per_domain"][domain]["nDCG@10"]
        expected = reference_data["baselines"][model]["per_domain"][domain]["nDCG@10"]
        assert abs(got - expected) < TOLERANCE, \
            f"{model}/{domain} nDCG@10: got {got:.5f}, expected {expected:.5f}"

    @pytest.mark.parametrize("model", ["bm25", "dense", "sparse", "reranker"])
    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_domain_mrr(self, model, domain, agent_results, reference_data):
        got = agent_results["baseline_metrics"][model]["per_domain"][domain]["MRR"]
        expected = reference_data["baselines"][model]["per_domain"][domain]["MRR"]
        assert abs(got - expected) < TOLERANCE, \
            f"{model}/{domain} MRR: got {got:.5f}, expected {expected:.5f}"


# ---------------------------------------------------------------------------
# Column swap detection test (catches dense.trec bug)
# ---------------------------------------------------------------------------

class TestDenseModelNotInverted:
    def test_dense_reasonable_ndcg(self, agent_results, reference_data):
        """Dense model should have reasonable metrics, not near-zero."""
        ndcg = agent_results["baseline_metrics"]["dense"]["overall"]["nDCG@10"]
        assert ndcg > 0.05, \
            f"Dense nDCG@10 = {ndcg:.4f}, near-zero suggests TREC format issue not fixed"

    def test_dense_matches_reference(self, agent_results, reference_data):
        got = agent_results["baseline_metrics"]["dense"]["overall"]["nDCG@10"]
        expected = reference_data["baselines"]["dense"]["overall"]["nDCG@10"]
        assert abs(got - expected) < TOLERANCE, \
            f"Dense nDCG@10: got {got:.5f}, expected {expected:.5f}"


# ---------------------------------------------------------------------------
# Graded relevance test (catches binarization bug)
# ---------------------------------------------------------------------------

class TestGradedRelevance:
    def test_not_binary_relevance(self, agent_results, reference_data):
        """nDCG with graded relevance must differ from binary baseline."""
        for model in ["bm25", "sparse", "reranker"]:
            graded = agent_results["baseline_metrics"][model]["overall"]["nDCG@10"]
            binary = reference_data["binary_baselines"][model]["nDCG@10"]
            expected = reference_data["baselines"][model]["overall"]["nDCG@10"]
            assert abs(graded - expected) < TOLERANCE, \
                f"{model}: nDCG@10={graded:.5f} closer to binary={binary:.5f} " \
                f"than expected graded={expected:.5f}"


# ---------------------------------------------------------------------------
# Fusion optimization tests
# ---------------------------------------------------------------------------

class TestFusionOptimization:
    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_has_best_method(self, domain, agent_results):
        opt = agent_results["fusion_optimization"][domain]
        assert "best_method" in opt, f"{domain}: missing best_method"
        assert "best_ndcg10" in opt, f"{domain}: missing best_ndcg10"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_has_all_methods(self, domain, agent_results):
        opt = agent_results["fusion_optimization"][domain]
        assert "all_methods" in opt, f"{domain}: missing all_methods"
        methods = opt["all_methods"]
        assert len(methods) >= 7, \
            f"{domain}: only {len(methods)} fusion configs tested, expected >= 7"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_has_weighted_combsum(self, domain, agent_results):
        """weighted_combsum must be present in all_methods."""
        methods = agent_results["fusion_optimization"][domain]["all_methods"]
        assert "weighted_combsum" in methods, \
            f"{domain}: missing weighted_combsum in all_methods"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_best_ndcg10_matches_reference(self, domain, agent_results, reference_data):
        got = agent_results["fusion_optimization"][domain]["best_ndcg10"]
        expected = reference_data["fusion_opt"][domain]["best_ndcg10"]
        assert abs(got - expected) < TOLERANCE, \
            f"{domain} best nDCG@10: got {got:.5f}, expected {expected:.5f}"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_best_method_matches_reference(self, domain, agent_results, reference_data):
        got = agent_results["fusion_optimization"][domain]["best_method"]
        expected = reference_data["fusion_opt"][domain]["best_method"]
        # Allow name differences if values match
        got_val = agent_results["fusion_optimization"][domain]["best_ndcg10"]
        exp_val = reference_data["fusion_opt"][domain]["best_ndcg10"]
        assert abs(got_val - exp_val) < TOLERANCE, \
            f"{domain}: best method mismatch ({got} vs {expected}) " \
            f"with values {got_val:.5f} vs {exp_val:.5f}"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_best_is_actually_best(self, domain, agent_results):
        """The reported best must have the highest nDCG@10 among all tested."""
        opt = agent_results["fusion_optimization"][domain]
        best_val = opt["best_ndcg10"]
        for method, val in opt["all_methods"].items():
            assert best_val >= val - 0.001, \
                f"{domain}: best={best_val:.5f} but {method}={val:.5f}"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_all_method_values_match_reference(self, domain, agent_results, reference_data):
        """Each tested method's nDCG@10 should be close to reference."""
        got_methods = agent_results["fusion_optimization"][domain]["all_methods"]
        ref_methods = reference_data["fusion_opt"][domain]["all_methods"]
        for method_name, ref_val in ref_methods.items():
            matched = False
            for agent_method, agent_val in got_methods.items():
                if abs(agent_val - ref_val) < TOLERANCE:
                    matched = True
                    break
            assert matched, \
                f"{domain}: no agent method matches reference {method_name}={ref_val:.5f}"


# ---------------------------------------------------------------------------
# Optimized fusion tests
# ---------------------------------------------------------------------------

class TestOptimizedFusion:
    def test_overall_ndcg10(self, agent_results, reference_data):
        got = agent_results["optimized_fusion"]["overall"]["nDCG@10"]
        expected = reference_data["optimized"]["overall"]["nDCG@10"]
        assert abs(got - expected) < TOLERANCE, \
            f"Optimized overall nDCG@10: got {got:.5f}, expected {expected:.5f}"

    def test_overall_mrr(self, agent_results, reference_data):
        got = agent_results["optimized_fusion"]["overall"]["MRR"]
        expected = reference_data["optimized"]["overall"]["MRR"]
        assert abs(got - expected) < TOLERANCE, \
            f"Optimized overall MRR: got {got:.5f}, expected {expected:.5f}"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_per_domain_ndcg10(self, domain, agent_results, reference_data):
        got = agent_results["optimized_fusion"]["per_domain"][domain]["nDCG@10"]
        expected = reference_data["optimized"]["per_domain"][domain]["nDCG@10"]
        assert abs(got - expected) < TOLERANCE, \
            f"Optimized {domain} nDCG@10: got {got:.5f}, expected {expected:.5f}"

    @pytest.mark.parametrize("domain", ["biology", "economics", "coding"])
    def test_per_domain_has_all_metrics(self, domain, agent_results):
        metrics = agent_results["optimized_fusion"]["per_domain"][domain]
        for key in ["nDCG@5", "nDCG@10", "MAP@10", "MRR"]:
            assert key in metrics, f"Optimized {domain} missing '{key}'"

    def test_fusion_improves_over_worst_baseline(self, agent_results):
        """Optimized fusion nDCG@10 should be reasonable (not near zero)."""
        fused = agent_results["optimized_fusion"]["overall"]["nDCG@10"]
        assert fused > 0.1, \
            f"Optimized fusion nDCG@10 = {fused:.4f}, unreasonably low"
