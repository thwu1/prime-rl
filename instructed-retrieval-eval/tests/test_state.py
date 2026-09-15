
import json
import math
import os
import pytest

DATA_DIR = "/app/data"
RESULTS_PATH = "/app/results.json"
TASKS = ["biomedical", "legal", "factcheck"]
SYSTEMS_NEURAL = ["neural_a", "neural_b"]
SYSTEMS_BM25 = ["bm25_plain", "bm25_instructed"]
ALL_SYSTEMS = SYSTEMS_NEURAL + SYSTEMS_BM25
METRICS = ["ndcg@5", "ndcg@10", "map@10", "mrr@10", "recall@10", "recall@100", "precision@5", "precision@10"]
RANK_CORR_PAIRS = [("ndcg@10", "map@10"), ("ndcg@10", "ndcg@5"), ("ndcg@5", "map@10")]


# ---------- Data loading helpers ----------

def _load_qrels(task_name):
    qrels = {}
    path = os.path.join(DATA_DIR, task_name, "qrels.tsv")
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                parts = line.strip().split()
            qid, _, docid, rel = parts[0], parts[1], parts[2], int(parts[3])
            qrels.setdefault(qid, {})[docid] = rel
    return qrels


def _load_run(path):
    run = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                parts = line.strip().split()
            qid, _, docid, rank, score = parts[0], parts[1], parts[2], int(parts[3]), float(parts[4])
            run.setdefault(qid, []).append((docid, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return run


# ---------- Reference implementations for verification ----------

def _ref_ndcg(qrels, run, k):
    """Reference nDCG with linear gain (matching pytrec_eval-terrier default)."""
    per_query = []
    for qid in run:
        if qid not in qrels:
            continue
        ranking = [docid for docid, _, _ in run[qid][:k]]
        gains = [qrels[qid].get(d, 0) for d in ranking]
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
        ideal_gains = sorted(qrels[qid].values(), reverse=True)[:k]
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_gains))
        per_query.append(dcg / idcg if idcg > 0 else 0.0)
    return sum(per_query) / len(per_query) if per_query else 0.0


def _ref_map(qrels, run, k):
    """Reference MAP with binary threshold rel >= 1."""
    per_query = []
    for qid in run:
        if qid not in qrels:
            continue
        relevant = {d for d, r in qrels[qid].items() if r >= 1}
        if not relevant:
            continue
        ranking = [docid for docid, _, _ in run[qid][:k]]
        num_rel = 0
        sum_prec = 0.0
        for i, docid in enumerate(ranking):
            if docid in relevant:
                num_rel += 1
                sum_prec += num_rel / (i + 1)
        per_query.append(sum_prec / len(relevant))
    return sum(per_query) / len(per_query) if per_query else 0.0


def _ref_mrr(qrels, run, k):
    """Reference MRR with binary threshold rel >= 1."""
    per_query = []
    for qid in run:
        if qid not in qrels:
            continue
        relevant = {d for d, r in qrels[qid].items() if r >= 1}
        if not relevant:
            continue
        ranking = [docid for docid, _, _ in run[qid][:k]]
        rr = 0.0
        for i, docid in enumerate(ranking):
            if docid in relevant:
                rr = 1.0 / (i + 1)
                break
        per_query.append(rr)
    return sum(per_query) / len(per_query) if per_query else 0.0


def _ref_recall(qrels, run, k):
    """Reference Recall@k."""
    per_query = []
    for qid in run:
        if qid not in qrels:
            continue
        relevant = {d for d, r in qrels[qid].items() if r >= 1}
        if not relevant:
            per_query.append(0.0)
            continue
        ranking = {docid for docid, _, _ in run[qid][:k]}
        per_query.append(len(ranking & relevant) / len(relevant))
    return sum(per_query) / len(per_query) if per_query else 0.0


def _ref_precision(qrels, run, k):
    """Reference Precision@k with binary threshold rel >= 1."""
    per_query = []
    for qid in run:
        if qid not in qrels:
            continue
        relevant = {d for d, r in qrels[qid].items() if r >= 1}
        ranking = [docid for docid, _, _ in run[qid][:k]]
        hits = sum(1 for d in ranking if d in relevant)
        per_query.append(hits / k if k > 0 else 0.0)
    return sum(per_query) / len(per_query) if per_query else 0.0


# ---------- Fixtures ----------

@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} does not exist. Run the evaluation pipeline first."
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------- Test: Output format and structure ----------

class TestOutputStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_top_level_keys(self, results):
        required = {"per_task", "aggregate", "significance_tests", "rank_correlation", "meta"}
        assert required.issubset(set(results.keys())), f"Missing keys: {required - set(results.keys())}"

    def test_all_tasks_present(self, results):
        for task in TASKS:
            assert task in results["per_task"], f"Task '{task}' missing from per_task"

    def test_all_systems_per_task(self, results):
        for task in TASKS:
            for sys_name in ALL_SYSTEMS:
                assert sys_name in results["per_task"][task], \
                    f"System '{sys_name}' missing from task '{task}'"

    def test_all_metrics_per_system(self, results):
        for task in TASKS:
            for sys_name in ALL_SYSTEMS:
                for metric in METRICS:
                    assert metric in results["per_task"][task][sys_name], \
                        f"Metric '{metric}' missing for {task}/{sys_name}"
                    val = results["per_task"][task][sys_name][metric]
                    assert isinstance(val, (int, float)), \
                        f"Metric '{metric}' for {task}/{sys_name} is not numeric: {val}"

    def test_aggregate_keys(self, results):
        agg = results["aggregate"]
        for sys_name in ALL_SYSTEMS:
            assert sys_name in agg, f"System '{sys_name}' missing from aggregate"
            for metric in METRICS:
                assert metric in agg[sys_name], f"Metric '{metric}' missing from aggregate/{sys_name}"

    def test_significance_tests_structure(self, results):
        sig = results["significance_tests"]
        for task in TASKS:
            assert task in sig, f"Task '{task}' missing from significance_tests"
            assert "neural_a_vs_neural_b" in sig[task]
            assert "bm25_plain_vs_bm25_instructed" in sig[task]
            for comp in ["neural_a_vs_neural_b", "bm25_plain_vs_bm25_instructed"]:
                entry = sig[task][comp]
                assert "metric" in entry and entry["metric"] == "ndcg@10"
                assert "delta" in entry and isinstance(entry["delta"], (int, float))
                assert "p_value" in entry and isinstance(entry["p_value"], (int, float))
                assert "significant" in entry and isinstance(entry["significant"], bool)

    def test_rank_correlation_structure(self, results):
        rc = results["rank_correlation"]
        for metric_a, metric_b in RANK_CORR_PAIRS:
            key = f"{metric_a}_vs_{metric_b}"
            assert key in rc, f"Missing rank_correlation key: {key}"
            entry = rc[key]
            assert "tau" in entry and isinstance(entry["tau"], (int, float))
            assert "p_value" in entry and isinstance(entry["p_value"], (int, float))
            assert "system_ranking_a" in entry and isinstance(entry["system_ranking_a"], list)
            assert "system_ranking_b" in entry and isinstance(entry["system_ranking_b"], list)

    def test_meta_section(self, results):
        meta = results["meta"]
        assert meta["num_tasks"] == 3
        assert "metrics_computed" in meta
        assert set(METRICS).issubset(set(meta["metrics_computed"]))
        assert meta["bm25_params"]["k1"] == pytest.approx(1.2)
        assert meta["bm25_params"]["b"] == pytest.approx(0.75)
        assert meta["significance_level"] == pytest.approx(0.05)
        assert meta["num_permutations"] == 10000
        assert "tools" in meta
        assert "pytrec_eval_version" in meta["tools"]
        assert "scipy_version" in meta["tools"]


# ---------- Test: pytrec_eval-terrier consistency ----------

class TestPytrecEvalConsistency:
    """Verify metrics match pytrec_eval-terrier output for neural runs."""

    @pytest.fixture(scope="session")
    def pytrec_metrics(self):
        import pytrec_eval
        all_results = {}
        for task_name in TASKS:
            all_results[task_name] = {}
            qrels = _load_qrels(task_name)
            for system in SYSTEMS_NEURAL:
                run_data = _load_run(
                    os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))

                pytrec_run = {}
                pytrec_run_top10 = {}
                for qid in run_data:
                    pytrec_run[qid] = {
                        docid: score for docid, _, score in run_data[qid]
                    }
                    pytrec_run_top10[qid] = {
                        docid: score for docid, _, score in run_data[qid][:10]
                    }

                evaluator = pytrec_eval.RelevanceEvaluator(
                    qrels,
                    {'ndcg_cut_5', 'ndcg_cut_10', 'map_cut_10',
                     'recall_10', 'recall_100', 'P_5', 'P_10'}
                )
                per_query = evaluator.evaluate(pytrec_run)

                measure_map = {
                    'ndcg_cut_5': 'ndcg@5',
                    'ndcg_cut_10': 'ndcg@10',
                    'map_cut_10': 'map@10',
                    'recall_10': 'recall@10',
                    'recall_100': 'recall@100',
                    'P_5': 'precision@5',
                    'P_10': 'precision@10',
                }
                metrics = {}
                for pytrec_name, output_name in measure_map.items():
                    vals = [per_query[qid][pytrec_name] for qid in per_query]
                    metrics[output_name] = sum(vals) / len(vals) if vals else 0.0

                # MRR@10 via recip_rank on top-10 truncated run
                mrr_eval = pytrec_eval.RelevanceEvaluator(
                    qrels, {'recip_rank'}
                )
                mrr_pq = mrr_eval.evaluate(pytrec_run_top10)
                mrr_vals = [mrr_pq[qid]['recip_rank'] for qid in mrr_pq]
                metrics['mrr@10'] = sum(mrr_vals) / len(mrr_vals) if mrr_vals else 0.0

                all_results[task_name][system] = metrics
        return all_results

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    @pytest.mark.parametrize("metric", METRICS)
    def test_matches_pytrec(self, results, pytrec_metrics, task_name, system, metric):
        expected = pytrec_metrics[task_name][system][metric]
        actual = results["per_task"][task_name][system][metric]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"{metric} for {task_name}/{system}: got {actual}, pytrec_eval gives {expected}"


# ---------- Test: Metric correctness via reference implementations ----------

class TestMetricCorrectness:
    """Verify that metric computation matches reference implementation on provided runs."""

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_ndcg5(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_ndcg(qrels, run, 5)
        actual = results["per_task"][task_name][system]["ndcg@5"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"nDCG@5 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_ndcg10(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_ndcg(qrels, run, 10)
        actual = results["per_task"][task_name][system]["ndcg@10"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"nDCG@10 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_map10(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_map(qrels, run, 10)
        actual = results["per_task"][task_name][system]["map@10"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"MAP@10 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_mrr10(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_mrr(qrels, run, 10)
        actual = results["per_task"][task_name][system]["mrr@10"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"MRR@10 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_recall10(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_recall(qrels, run, 10)
        actual = results["per_task"][task_name][system]["recall@10"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"Recall@10 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_precision5(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_precision(qrels, run, 5)
        actual = results["per_task"][task_name][system]["precision@5"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"Precision@5 mismatch for {task_name}/{system}: got {actual}, expected {expected}"

    @pytest.mark.parametrize("task_name", TASKS)
    @pytest.mark.parametrize("system", SYSTEMS_NEURAL)
    def test_precision10(self, results, task_name, system):
        qrels = _load_qrels(task_name)
        run = _load_run(os.path.join(DATA_DIR, task_name, "runs", f"{system}.tsv"))
        expected = _ref_precision(qrels, run, 10)
        actual = results["per_task"][task_name][system]["precision@10"]
        assert actual == pytest.approx(expected, abs=1e-4), \
            f"Precision@10 mismatch for {task_name}/{system}: got {actual}, expected {expected}"


# ---------- Test: BM25 retrieval quality ----------

class TestBM25Quality:
    """Verify BM25 retrieval produces meaningful rankings."""

    @pytest.mark.parametrize("task_name", TASKS)
    def test_bm25_plain_ndcg10_above_threshold(self, results, task_name):
        ndcg = results["per_task"][task_name]["bm25_plain"]["ndcg@10"]
        assert ndcg > 0.15, \
            f"BM25 plain nDCG@10 too low for {task_name}: {ndcg}"

    @pytest.mark.parametrize("task_name", TASKS)
    def test_bm25_instructed_ndcg10_above_threshold(self, results, task_name):
        ndcg = results["per_task"][task_name]["bm25_instructed"]["ndcg@10"]
        assert ndcg > 0.10, \
            f"BM25 instructed nDCG@10 too low for {task_name}: {ndcg}"

    @pytest.mark.parametrize("task_name", TASKS)
    def test_bm25_mrr_positive(self, results, task_name):
        mrr = results["per_task"][task_name]["bm25_plain"]["mrr@10"]
        assert mrr > 0.0, \
            f"BM25 MRR@10 should be positive for {task_name}: {mrr}"

    @pytest.mark.parametrize("task_name", TASKS)
    def test_bm25_recall100_high(self, results, task_name):
        recall = results["per_task"][task_name]["bm25_plain"]["recall@100"]
        assert recall >= 0.5, \
            f"BM25 Recall@100 too low for {task_name}: {recall}"

    def test_bm25_metrics_are_valid_fractions(self, results):
        for task in TASKS:
            for sys_name in SYSTEMS_BM25:
                for metric in METRICS:
                    val = results["per_task"][task][sys_name][metric]
                    assert 0.0 <= val <= 1.0, \
                        f"Metric {metric} for {task}/{sys_name} out of [0,1]: {val}"


# ---------- Test: Significance tests ----------

class TestSignificance:
    @pytest.mark.parametrize("task_name", TASKS)
    def test_pvalue_valid_range(self, results, task_name):
        for comp in ["neural_a_vs_neural_b", "bm25_plain_vs_bm25_instructed"]:
            p = results["significance_tests"][task_name][comp]["p_value"]
            assert 0.0 <= p <= 1.0, f"p-value out of range for {task_name}/{comp}: {p}"

    @pytest.mark.parametrize("task_name", TASKS)
    def test_significant_consistent_with_pvalue(self, results, task_name):
        for comp in ["neural_a_vs_neural_b", "bm25_plain_vs_bm25_instructed"]:
            entry = results["significance_tests"][task_name][comp]
            if entry["p_value"] < 0.05:
                assert entry["significant"] is True
            else:
                assert entry["significant"] is False

    @pytest.mark.parametrize("task_name", TASKS)
    def test_neural_a_better_than_b_delta(self, results, task_name):
        """neural_a was designed to rank better than neural_b."""
        delta = results["significance_tests"][task_name]["neural_a_vs_neural_b"]["delta"]
        assert delta > 0, f"Expected neural_a > neural_b for {task_name}, got delta={delta}"


# ---------- Test: Aggregate consistency ----------

class TestAggregateConsistency:
    def test_aggregate_is_macro_average(self, results):
        """Aggregate metrics must equal macro-average of per-task metrics."""
        for sys_name in ALL_SYSTEMS:
            for metric in METRICS:
                per_task_vals = [
                    results["per_task"][task][sys_name][metric]
                    for task in TASKS
                ]
                expected_avg = sum(per_task_vals) / len(per_task_vals)
                actual = results["aggregate"][sys_name][metric]
                assert actual == pytest.approx(expected_avg, abs=1e-4), \
                    f"Aggregate {metric} for {sys_name}: got {actual}, expected {expected_avg}"

    def test_neural_metrics_are_valid_fractions(self, results):
        for sys_name in SYSTEMS_NEURAL:
            for metric in METRICS:
                for task in TASKS:
                    val = results["per_task"][task][sys_name][metric]
                    assert 0.0 <= val <= 1.0, \
                        f"Metric {metric} for {task}/{sys_name} out of [0,1]: {val}"


# ---------- Test: Rank correlation ----------

class TestRankCorrelation:
    """Verify Kendall's tau rank correlation between system rankings."""

    def test_tau_values_correct(self, results):
        from scipy.stats import kendalltau
        agg = results["aggregate"]
        for metric_a, metric_b in RANK_CORR_PAIRS:
            key = f"{metric_a}_vs_{metric_b}"
            scores_a = [agg[s][metric_a] for s in ALL_SYSTEMS]
            scores_b = [agg[s][metric_b] for s in ALL_SYSTEMS]
            expected_tau, _ = kendalltau(scores_a, scores_b)
            actual_tau = results["rank_correlation"][key]["tau"]
            assert actual_tau == pytest.approx(expected_tau, abs=1e-4), \
                f"Kendall tau for {key}: got {actual_tau}, expected {expected_tau}"

    def test_pvalue_valid_range(self, results):
        for metric_a, metric_b in RANK_CORR_PAIRS:
            key = f"{metric_a}_vs_{metric_b}"
            p = results["rank_correlation"][key]["p_value"]
            assert 0.0 <= p <= 1.0, f"p-value out of range for {key}: {p}"

    def test_system_ranking_sorted_correctly(self, results):
        agg = results["aggregate"]
        for metric_a, metric_b in RANK_CORR_PAIRS:
            key = f"{metric_a}_vs_{metric_b}"
            rc = results["rank_correlation"][key]

            ranking_a = rc["system_ranking_a"]
            scores_a = [agg[s][metric_a] for s in ranking_a]
            assert scores_a == sorted(scores_a, reverse=True), \
                f"system_ranking_a not correctly sorted by {metric_a} in {key}"

            ranking_b = rc["system_ranking_b"]
            scores_b = [agg[s][metric_b] for s in ranking_b]
            assert scores_b == sorted(scores_b, reverse=True), \
                f"system_ranking_b not correctly sorted by {metric_b} in {key}"

    def test_ranking_contains_all_systems(self, results):
        for metric_a, metric_b in RANK_CORR_PAIRS:
            key = f"{metric_a}_vs_{metric_b}"
            rc = results["rank_correlation"][key]
            assert set(rc["system_ranking_a"]) == set(ALL_SYSTEMS), \
                f"system_ranking_a missing systems in {key}"
            assert set(rc["system_ranking_b"]) == set(ALL_SYSTEMS), \
                f"system_ranking_b missing systems in {key}"


# ---------- Test: Edge case handling ----------

class TestEdgeCases:
    def test_perfect_ranking_ndcg_is_one(self, results):
        """Neural_a achieves perfect ranking (highest-relevance docs first) on all queries.
        With graded relevance in biomedical, perfect ranking should yield nDCG = 1.0."""
        ndcg5 = results["per_task"]["biomedical"]["neural_a"]["ndcg@5"]
        assert ndcg5 == pytest.approx(1.0, abs=1e-4), \
            f"nDCG@5 for biomedical/neural_a should be 1.0 (perfect ranking), got {ndcg5}"

    def test_binary_relevance_task(self, results):
        """Legal task has binary relevance. MAP should be well-defined."""
        map10 = results["per_task"]["legal"]["neural_a"]["map@10"]
        assert map10 > 0.5, \
            f"MAP@10 for legal/neural_a too low ({map10}); binary relevance handling may be wrong"

    def test_precision_at_k_correct(self, results):
        """For neural_a on legal task: precision@5 should be in reasonable range."""
        p5 = results["per_task"]["legal"]["neural_a"]["precision@5"]
        assert 0.2 <= p5 <= 0.6, \
            f"Precision@5 for legal/neural_a outside expected range: {p5}"
