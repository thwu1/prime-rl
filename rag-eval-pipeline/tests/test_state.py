"""

Tests for MTRAG evaluation pipeline.
Independently computes expected metrics using pytrec_eval and rouge-score,
then verifies the agent's implementation produces matching results.
"""

import json
import csv
import os
import subprocess
import sys
import pytest
from collections import defaultdict

MTRAG_EVAL = "/app/mtrag_eval.py"
INPUT_FILE = "/app/data/input.jsonl"
QRELS_DIR = "/app/data/qrels"
PRED_A = "/app/data/predictions/system_a.jsonl"
PRED_B = "/app/data/predictions/system_b.jsonl"
PRED_C = "/app/data/predictions/system_c.jsonl"
RESULTS_DIR = "/app/test_results"

TOLERANCE = 0.02


def run_cmd(args, expect_fail=False):
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=120
    )
    if not expect_fail:
        assert result.returncode == 0, (
            f"Command failed: {' '.join(args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.returncode, result.stdout, result.stderr


def load_qrels(domain):
    """Load qrels for a domain."""
    qrels = {}
    qrels_file = os.path.join(QRELS_DIR, f"{domain}.tsv")
    with open(qrels_file, 'r') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)
        for row in reader:
            query_id, corpus_id, score = row[0], row[1], int(row[2])
            if query_id not in qrels:
                qrels[query_id] = {}
            qrels[query_id][corpus_id] = score
    return qrels


def load_predictions(pred_file):
    """Load predictions from JSONL."""
    preds = []
    with open(pred_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                preds.append(json.loads(line))
    return preds


def load_input_tasks():
    """Load input tasks."""
    tasks = {}
    with open(INPUT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                tasks[item['task_id']] = item
    return tasks


def extract_domain(collection_name):
    """Extract domain from collection identifier."""
    parts = collection_name.split('-')
    if len(parts) >= 4 and parts[0] == 'mt' and parts[1] == 'rag':
        return parts[2]
    return None


def compute_expected_retrieval(pred_file):
    """Independently compute expected retrieval metrics using pytrec_eval."""
    import pytrec_eval

    predictions = load_predictions(pred_file)

    # Group by collection
    collection_preds = defaultdict(dict)
    for pred in predictions:
        domain = extract_domain(pred['Collection'])
        doc_scores = {}
        for ctx in pred.get('contexts', []):
            doc_scores[ctx['document_id']] = ctx['score']
        collection_preds[domain][pred['task_id']] = doc_scores

    k_values = [1, 3, 5]
    per_collection = {}
    total_count = 0
    all_ndcg = defaultdict(float)
    all_recall = defaultdict(float)

    for domain in sorted(collection_preds.keys()):
        preds = collection_preds[domain]
        qrels = load_qrels(domain)

        ndcg_string = "ndcg_cut." + ",".join([str(k) for k in k_values])
        recall_string = "recall." + ",".join([str(k) for k in k_values])

        evaluator = pytrec_eval.RelevanceEvaluator(qrels, {ndcg_string, recall_string})
        scores = evaluator.evaluate(preds)

        ndcg = {}
        recall = {}
        for k in k_values:
            ndcg[f"nDCG@{k}"] = 0.0
            recall[f"Recall@{k}"] = 0.0

        for qid in scores:
            for k in k_values:
                ndcg[f"nDCG@{k}"] += scores[qid][f"ndcg_cut_{k}"]
                recall[f"Recall@{k}"] += scores[qid][f"recall_{k}"]

        n = len(scores)
        count = len(preds)
        total_count += count

        for k in k_values:
            ndcg[f"nDCG@{k}"] = ndcg[f"nDCG@{k}"] / n if n > 0 else 0
            recall[f"Recall@{k}"] = recall[f"Recall@{k}"] / n if n > 0 else 0

        per_collection[domain] = {**ndcg, **recall, "count": count}

        for key, val in ndcg.items():
            all_ndcg[key] += val * count
        for key, val in recall.items():
            all_recall[key] += val * count

    weighted = {}
    for key in all_ndcg:
        weighted[key] = all_ndcg[key] / total_count if total_count > 0 else 0
    for key in all_recall:
        weighted[key] = all_recall[key] / total_count if total_count > 0 else 0

    return per_collection, weighted


def compute_expected_rouge(pred_file):
    """Independently compute expected ROUGE-L F1 using rouge-score."""
    from rouge_score import rouge_scorer

    input_tasks = load_input_tasks()
    predictions = load_predictions(pred_file)

    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=False)
    scores = {}

    for pred in predictions:
        task_id = pred['task_id']
        if task_id in input_tasks and 'predictions' in pred and pred['predictions']:
            pred_text = pred['predictions'][0]['text']
            target_text = input_tasks[task_id]['targets'][0]['text']
            result = scorer.score(target_text, pred_text)
            scores[task_id] = result['rougeL'].fmeasure

    avg = sum(scores.values()) / len(scores) if scores else 0.0
    return avg, scores


def compute_expected_per_query(pred_file):
    """Independently compute expected per-query scores."""
    import pytrec_eval
    from rouge_score import rouge_scorer

    predictions = load_predictions(pred_file)
    input_tasks = load_input_tasks()

    # Per-query retrieval scores
    collection_preds = defaultdict(dict)
    for pred in predictions:
        domain = extract_domain(pred['Collection'])
        doc_scores = {}
        for ctx in pred.get('contexts', []):
            doc_scores[ctx['document_id']] = ctx['score']
        collection_preds[domain][pred['task_id']] = doc_scores

    per_query = {}
    for domain in sorted(collection_preds.keys()):
        preds = collection_preds[domain]
        qrels = load_qrels(domain)

        ndcg_string = "ndcg_cut." + ",".join([str(k) for k in [1, 3, 5]])
        recall_string = "recall." + ",".join([str(k) for k in [1, 3, 5]])
        evaluator = pytrec_eval.RelevanceEvaluator(qrels, {ndcg_string, recall_string})
        scores = evaluator.evaluate(preds)

        for qid in scores:
            per_query[qid] = {
                "nDCG@5": scores[qid]["ndcg_cut_5"],
                "Recall@5": scores[qid]["recall_5"],
            }

    # Per-query ROUGE-L scores
    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=False)
    for pred in predictions:
        task_id = pred['task_id']
        if task_id in input_tasks and 'predictions' in pred and pred['predictions']:
            pred_text = pred['predictions'][0]['text']
            target_text = input_tasks[task_id]['targets'][0]['text']
            result = scorer.score(target_text, pred_text)
            if task_id in per_query:
                per_query[task_id]["ROUGE-L_F1"] = result['rougeL'].fmeasure

    return per_query


def harmonic_mean(values):
    if not values or any(v == 0 for v in values):
        return 0.0
    return len(values) / sum(1.0 / v for v in values)


class TestScriptExists:
    def test_mtrag_eval_exists(self):
        assert os.path.exists(MTRAG_EVAL), f"{MTRAG_EVAL} does not exist"

    def test_mtrag_eval_runnable(self):
        rc, stdout, stderr = run_cmd(
            ["python3", MTRAG_EVAL, "--help"],
            expect_fail=True  # --help might exit 0 or non-zero
        )
        # Just check it doesn't crash with import errors
        assert "Traceback" not in stderr, f"Script has import errors: {stderr}"


class TestFormatValidation:
    def test_valid_system_a_rag_taskc(self):
        """system_a.jsonl should pass rag_taskc validation."""
        rc, stdout, stderr = run_cmd([
            "python3", MTRAG_EVAL, "validate",
            "--input", INPUT_FILE,
            "--predictions", PRED_A,
            "--mode", "rag_taskc"
        ])
        assert rc == 0

    def test_valid_system_b_rag_taskc(self):
        """system_b.jsonl should pass rag_taskc validation."""
        rc, stdout, stderr = run_cmd([
            "python3", MTRAG_EVAL, "validate",
            "--input", INPUT_FILE,
            "--predictions", PRED_B,
            "--mode", "rag_taskc"
        ])
        assert rc == 0

    def test_valid_system_a_retrieval(self):
        """system_a.jsonl should pass retrieval_taska validation."""
        rc, stdout, stderr = run_cmd([
            "python3", MTRAG_EVAL, "validate",
            "--input", INPUT_FILE,
            "--predictions", PRED_A,
            "--mode", "retrieval_taska"
        ])
        assert rc == 0

    def test_invalid_system_c_rag_taskc(self):
        """system_c.jsonl has format errors and should fail rag_taskc validation."""
        rc, stdout, stderr = run_cmd([
            "python3", MTRAG_EVAL, "validate",
            "--input", INPUT_FILE,
            "--predictions", PRED_C,
            "--mode", "rag_taskc"
        ], expect_fail=True)
        assert rc != 0, "system_c.jsonl should fail validation"

    def test_invalid_system_c_retrieval(self):
        """system_c.jsonl has format errors and should fail retrieval_taska validation."""
        rc, stdout, stderr = run_cmd([
            "python3", MTRAG_EVAL, "validate",
            "--input", INPUT_FILE,
            "--predictions", PRED_C,
            "--mode", "retrieval_taska"
        ], expect_fail=True)
        assert rc != 0, "system_c.jsonl should fail retrieval validation"


class TestRetrievalEvaluation:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.results_dir = str(tmp_path / "results")
        os.makedirs(self.results_dir, exist_ok=True)

    def _run_evaluate(self, pred_file, output_name):
        output_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "evaluate",
            "--input", INPUT_FILE,
            "--predictions", pred_file,
            "--qrels-dir", QRELS_DIR,
            "--output", output_path
        ])
        with open(output_path) as f:
            return json.load(f)

    def test_system_a_retrieval_metrics(self):
        """Verify system_a retrieval metrics against independently computed values."""
        result = self._run_evaluate(PRED_A, "system_a")
        expected_per_coll, expected_weighted = compute_expected_retrieval(PRED_A)

        # Check per-collection metrics
        for domain in expected_per_coll:
            assert domain in result["retrieval"]["per_collection"], \
                f"Missing collection '{domain}' in results"
            actual = result["retrieval"]["per_collection"][domain]
            expected = expected_per_coll[domain]
            for metric in ["nDCG@1", "nDCG@3", "nDCG@5", "Recall@1", "Recall@3", "Recall@5"]:
                assert abs(actual[metric] - expected[metric]) < TOLERANCE, \
                    f"{domain} {metric}: expected {expected[metric]:.5f}, got {actual[metric]:.5f}"

    def test_system_a_weighted_average(self):
        """Verify weighted cross-collection averages for system_a."""
        result = self._run_evaluate(PRED_A, "system_a")
        _, expected_weighted = compute_expected_retrieval(PRED_A)

        actual_weighted = result["retrieval"]["weighted_average"]
        for metric in ["nDCG@1", "nDCG@3", "nDCG@5", "Recall@1", "Recall@3", "Recall@5"]:
            assert abs(actual_weighted[metric] - expected_weighted[metric]) < TOLERANCE, \
                f"Weighted {metric}: expected {expected_weighted[metric]:.5f}, got {actual_weighted[metric]:.5f}"

    def test_system_b_retrieval_metrics(self):
        """Verify system_b retrieval metrics are worse than system_a."""
        result_a = self._run_evaluate(PRED_A, "system_a")
        result_b = self._run_evaluate(PRED_B, "system_b")

        wa_a = result_a["retrieval"]["weighted_average"]
        wa_b = result_b["retrieval"]["weighted_average"]

        # System A should be better than system B on nDCG@5
        assert wa_a["nDCG@5"] > wa_b["nDCG@5"], \
            f"System A nDCG@5 ({wa_a['nDCG@5']}) should be > System B ({wa_b['nDCG@5']})"

    def test_system_b_retrieval_values(self):
        """Verify system_b retrieval metrics match expected."""
        result = self._run_evaluate(PRED_B, "system_b")
        expected_per_coll, expected_weighted = compute_expected_retrieval(PRED_B)

        actual_weighted = result["retrieval"]["weighted_average"]
        for metric in ["nDCG@1", "nDCG@3", "nDCG@5", "Recall@1", "Recall@3", "Recall@5"]:
            assert abs(actual_weighted[metric] - expected_weighted[metric]) < TOLERANCE, \
                f"System B weighted {metric}: expected {expected_weighted[metric]:.5f}, got {actual_weighted[metric]:.5f}"

    def test_collection_count(self):
        """Verify per-collection query counts."""
        result = self._run_evaluate(PRED_A, "system_a")
        per_coll = result["retrieval"]["per_collection"]

        assert per_coll["alpha"]["count"] == 5, \
            f"Alpha count should be 5, got {per_coll['alpha']['count']}"
        assert per_coll["beta"]["count"] == 4, \
            f"Beta count should be 4, got {per_coll['beta']['count']}"


class TestGenerationEvaluation:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.results_dir = str(tmp_path / "results")
        os.makedirs(self.results_dir, exist_ok=True)

    def _run_evaluate(self, pred_file, output_name):
        output_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "evaluate",
            "--input", INPUT_FILE,
            "--predictions", pred_file,
            "--qrels-dir", QRELS_DIR,
            "--output", output_path
        ])
        with open(output_path) as f:
            return json.load(f)

    def test_system_a_rouge_l(self):
        """Verify ROUGE-L F1 for system_a against independently computed values."""
        result = self._run_evaluate(PRED_A, "system_a")
        expected_avg, expected_per_task = compute_expected_rouge(PRED_A)

        actual_avg = result["generation"]["rouge_l_f1"]
        assert abs(actual_avg - expected_avg) < TOLERANCE, \
            f"ROUGE-L F1 avg: expected {expected_avg:.5f}, got {actual_avg:.5f}"

    def test_system_a_rouge_per_task(self):
        """Verify per-task ROUGE-L scores for system_a."""
        result = self._run_evaluate(PRED_A, "system_a")
        _, expected_per_task = compute_expected_rouge(PRED_A)

        actual_per_task = result["generation"]["per_task"]
        for task_id, expected_score in expected_per_task.items():
            assert task_id in actual_per_task, f"Missing task {task_id} in per_task scores"
            assert abs(actual_per_task[task_id] - expected_score) < TOLERANCE, \
                f"{task_id} ROUGE-L: expected {expected_score:.5f}, got {actual_per_task[task_id]:.5f}"

    def test_system_b_rouge_lower(self):
        """System B should have lower ROUGE-L than system A."""
        result_a = self._run_evaluate(PRED_A, "system_a")
        result_b = self._run_evaluate(PRED_B, "system_b")

        assert result_a["generation"]["rouge_l_f1"] > result_b["generation"]["rouge_l_f1"], \
            f"System A ROUGE-L ({result_a['generation']['rouge_l_f1']}) should be > System B ({result_b['generation']['rouge_l_f1']})"

    def test_system_b_rouge_values(self):
        """Verify ROUGE-L for system_b matches expected."""
        result = self._run_evaluate(PRED_B, "system_b")
        expected_avg, _ = compute_expected_rouge(PRED_B)

        assert abs(result["generation"]["rouge_l_f1"] - expected_avg) < TOLERANCE, \
            f"System B ROUGE-L: expected {expected_avg:.5f}, got {result['generation']['rouge_l_f1']:.5f}"


class TestHarmonicMeanAndRanking:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.results_dir = str(tmp_path / "eval_results")
        os.makedirs(self.results_dir, exist_ok=True)

    def _run_evaluate(self, pred_file, output_name):
        output_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "evaluate",
            "--input", INPUT_FILE,
            "--predictions", pred_file,
            "--qrels-dir", QRELS_DIR,
            "--output", output_path
        ])
        with open(output_path) as f:
            return json.load(f)

    def test_harmonic_mean_system_a(self):
        """Verify harmonic mean computation for system_a."""
        result = self._run_evaluate(PRED_A, "system_a")

        ndcg5 = result["retrieval"]["weighted_average"]["nDCG@5"]
        recall5 = result["retrieval"]["weighted_average"]["Recall@5"]
        rouge = result["generation"]["rouge_l_f1"]

        expected_hm = harmonic_mean([ndcg5, recall5, rouge])
        actual_hm = result["overall"]["harmonic_mean"]

        assert abs(actual_hm - expected_hm) < TOLERANCE, \
            f"Harmonic mean: expected {expected_hm:.5f}, got {actual_hm:.5f}"

    def test_harmonic_mean_system_a_greater(self):
        """System A harmonic mean should be greater than system B."""
        result_a = self._run_evaluate(PRED_A, "system_a")
        result_b = self._run_evaluate(PRED_B, "system_b")

        assert result_a["overall"]["harmonic_mean"] > result_b["overall"]["harmonic_mean"], \
            f"System A HM ({result_a['overall']['harmonic_mean']}) should be > System B ({result_b['overall']['harmonic_mean']})"

    def test_ranking_output(self):
        """Verify ranking CSV output."""
        self._run_evaluate(PRED_A, "system_a")
        self._run_evaluate(PRED_B, "system_b")

        ranking_path = os.path.join(self.results_dir, "ranking.csv")
        run_cmd([
            "python3", MTRAG_EVAL, "rank",
            "--results-dir", self.results_dir,
            "--output", ranking_path
        ])

        assert os.path.exists(ranking_path), "Ranking CSV not created"

        with open(ranking_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

        # Check required columns
        for col in ["rank", "system", "nDCG@5", "Recall@5", "ROUGE-L_F1", "harmonic_mean"]:
            assert col in rows[0], f"Missing column '{col}' in ranking CSV"

        # System A should be ranked first
        assert rows[0]["system"] == "system_a", \
            f"Expected system_a ranked first, got {rows[0]['system']}"
        assert rows[1]["system"] == "system_b", \
            f"Expected system_b ranked second, got {rows[1]['system']}"

        # Ranks should be 1 and 2
        assert rows[0]["rank"] == "1", f"First rank should be 1, got {rows[0]['rank']}"
        assert rows[1]["rank"] == "2", f"Second rank should be 2, got {rows[1]['rank']}"

    def test_ranking_harmonic_mean_values(self):
        """Verify harmonic mean values in ranking match evaluation results."""
        result_a = self._run_evaluate(PRED_A, "system_a")
        result_b = self._run_evaluate(PRED_B, "system_b")

        ranking_path = os.path.join(self.results_dir, "ranking.csv")
        run_cmd([
            "python3", MTRAG_EVAL, "rank",
            "--results-dir", self.results_dir,
            "--output", ranking_path
        ])

        with open(ranking_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = {row["system"]: row for row in reader}

        assert abs(float(rows["system_a"]["harmonic_mean"]) - result_a["overall"]["harmonic_mean"]) < TOLERANCE
        assert abs(float(rows["system_b"]["harmonic_mean"]) - result_b["overall"]["harmonic_mean"]) < TOLERANCE


class TestPerQueryScores:
    """Test per-query metric decomposition in evaluate output."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.results_dir = str(tmp_path / "results")
        os.makedirs(self.results_dir, exist_ok=True)

    def _run_evaluate(self, pred_file, output_name):
        output_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "evaluate",
            "--input", INPUT_FILE,
            "--predictions", pred_file,
            "--qrels-dir", QRELS_DIR,
            "--output", output_path
        ])
        with open(output_path) as f:
            return json.load(f)

    def test_per_query_section_exists(self):
        """Evaluate output should have per_query section."""
        result = self._run_evaluate(PRED_A, "system_a")
        assert "per_query" in result, "Missing 'per_query' section in evaluate output"

    def test_per_query_has_all_tasks(self):
        """per_query should have entries for all 9 tasks."""
        result = self._run_evaluate(PRED_A, "system_a")
        assert len(result["per_query"]) == 9, \
            f"Expected 9 per-query entries, got {len(result['per_query'])}"

    def test_per_query_metric_fields(self):
        """Each per_query entry should have nDCG@5, Recall@5, ROUGE-L_F1."""
        result = self._run_evaluate(PRED_A, "system_a")
        per_query = result["per_query"]

        for qid in per_query:
            assert "nDCG@5" in per_query[qid], f"{qid} missing nDCG@5"
            assert "Recall@5" in per_query[qid], f"{qid} missing Recall@5"
            assert "ROUGE-L_F1" in per_query[qid], f"{qid} missing ROUGE-L_F1"

    def test_per_query_ndcg_average_matches_weighted(self):
        """Per-query nDCG@5 values should average to the weighted average."""
        result = self._run_evaluate(PRED_A, "system_a")
        per_query = result["per_query"]

        ndcg5_values = [per_query[qid]["nDCG@5"] for qid in per_query]
        avg_ndcg5 = sum(ndcg5_values) / len(ndcg5_values)

        assert abs(avg_ndcg5 - result["retrieval"]["weighted_average"]["nDCG@5"]) < TOLERANCE, \
            f"Per-query nDCG@5 avg ({avg_ndcg5:.5f}) != weighted avg ({result['retrieval']['weighted_average']['nDCG@5']:.5f})"

    def test_per_query_recall_average_matches_weighted(self):
        """Per-query Recall@5 values should average to the weighted average."""
        result = self._run_evaluate(PRED_A, "system_a")
        per_query = result["per_query"]

        recall5_values = [per_query[qid]["Recall@5"] for qid in per_query]
        avg_recall5 = sum(recall5_values) / len(recall5_values)

        assert abs(avg_recall5 - result["retrieval"]["weighted_average"]["Recall@5"]) < TOLERANCE, \
            f"Per-query Recall@5 avg ({avg_recall5:.5f}) != weighted avg ({result['retrieval']['weighted_average']['Recall@5']:.5f})"

    def test_per_query_rouge_matches_generation(self):
        """Per-query ROUGE-L values should match generation per_task."""
        result = self._run_evaluate(PRED_A, "system_a")
        per_query = result["per_query"]
        per_task = result["generation"]["per_task"]

        for qid in per_task:
            assert qid in per_query, f"Missing {qid} in per_query"
            assert abs(per_query[qid]["ROUGE-L_F1"] - per_task[qid]) < TOLERANCE, \
                f"{qid} ROUGE-L mismatch: per_query={per_query[qid]['ROUGE-L_F1']}, per_task={per_task[qid]}"

    def test_per_query_values_match_independent(self):
        """Verify per-query scores against independently computed values."""
        result = self._run_evaluate(PRED_A, "system_a")
        expected = compute_expected_per_query(PRED_A)

        for qid in expected:
            assert qid in result["per_query"], f"Missing {qid} in per_query"
            actual = result["per_query"][qid]
            for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
                assert abs(actual[metric] - expected[qid][metric]) < TOLERANCE, \
                    f"{qid} {metric}: expected {expected[qid][metric]:.5f}, got {actual[metric]:.5f}"

    def test_per_query_system_b(self):
        """Verify per-query scores for system_b against independently computed values."""
        result = self._run_evaluate(PRED_B, "system_b")
        expected = compute_expected_per_query(PRED_B)

        for qid in expected:
            assert qid in result["per_query"], f"Missing {qid} in per_query"
            actual = result["per_query"][qid]
            for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
                assert abs(actual[metric] - expected[qid][metric]) < TOLERANCE, \
                    f"{qid} {metric}: expected {expected[qid][metric]:.5f}, got {actual[metric]:.5f}"


class TestCompareSubcommand:
    """Test paired permutation significance testing between systems."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.results_dir = str(tmp_path / "compare_results")
        os.makedirs(self.results_dir, exist_ok=True)

    def _run_evaluate(self, pred_file, output_name):
        output_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "evaluate",
            "--input", INPUT_FILE,
            "--predictions", pred_file,
            "--qrels-dir", QRELS_DIR,
            "--output", output_path
        ])
        return output_path

    def _run_compare(self, path_a, path_b, output_name, seed="42"):
        compare_path = os.path.join(self.results_dir, f"{output_name}.json")
        run_cmd([
            "python3", MTRAG_EVAL, "compare",
            "--result-a", path_a,
            "--result-b", path_b,
            "--output", compare_path,
            "--seed", seed
        ])
        with open(compare_path) as f:
            return json.load(f)

    def test_compare_output_format(self):
        """Verify compare output has correct structure."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")
        result = self._run_compare(path_a, path_b, "comparison")

        assert "system_a" in result, "Missing 'system_a' in compare output"
        assert "system_b" in result, "Missing 'system_b' in compare output"
        assert "num_queries" in result, "Missing 'num_queries' in compare output"
        assert "seed" in result, "Missing 'seed' in compare output"
        assert "num_permutations" in result, "Missing 'num_permutations' in compare output"
        assert "metrics" in result, "Missing 'metrics' in compare output"

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            assert metric in result["metrics"], f"Missing metric '{metric}'"
            m = result["metrics"][metric]
            for field in ["mean_a", "mean_b", "delta", "p_value", "significant"]:
                assert field in m, f"Missing field '{field}' in {metric}"

    def test_compare_delta_values(self):
        """Verify delta = mean_a - mean_b."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")
        result = self._run_compare(path_a, path_b, "comparison")

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            m = result["metrics"][metric]
            expected_delta = m["mean_a"] - m["mean_b"]
            assert abs(m["delta"] - expected_delta) < 1e-4, \
                f"{metric} delta: expected {expected_delta:.5f}, got {m['delta']:.5f}"

    def test_compare_p_values_valid(self):
        """p-values should be between 0 and 1."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")
        result = self._run_compare(path_a, path_b, "comparison")

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            p = result["metrics"][metric]["p_value"]
            assert 0 <= p <= 1, f"{metric} p_value={p} not in [0,1]"

    def test_compare_significance_consistency(self):
        """significant should be True iff p_value < 0.05."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")
        result = self._run_compare(path_a, path_b, "comparison")

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            m = result["metrics"][metric]
            assert m["significant"] == (m["p_value"] < 0.05), \
                f"{metric}: significant={m['significant']} inconsistent with p_value={m['p_value']}"

    def test_compare_num_queries(self):
        """num_queries should match the number of shared queries."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")
        result = self._run_compare(path_a, path_b, "comparison")

        assert result["num_queries"] == 9, \
            f"Expected 9 queries, got {result['num_queries']}"

    def test_compare_deterministic_with_seed(self):
        """Same seed should produce identical results."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")

        result1 = self._run_compare(path_a, path_b, "comparison1", seed="42")
        result2 = self._run_compare(path_a, path_b, "comparison2", seed="42")

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            assert result1["metrics"][metric]["p_value"] == result2["metrics"][metric]["p_value"], \
                f"{metric} p_value not deterministic: {result1['metrics'][metric]['p_value']} vs {result2['metrics'][metric]['p_value']}"

    def test_compare_different_seeds_may_differ(self):
        """Different seeds may produce different p-values (verifies seed is used)."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")

        result1 = self._run_compare(path_a, path_b, "comparison_s1", seed="42")
        result2 = self._run_compare(path_a, path_b, "comparison_s2", seed="99")

        # Deltas should be identical regardless of seed
        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            assert abs(result1["metrics"][metric]["delta"] - result2["metrics"][metric]["delta"]) < 1e-6, \
                f"{metric} delta should not depend on seed"

    def test_compare_identical_systems_not_significant(self):
        """Comparing a system against itself should not be significant."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        result = self._run_compare(path_a, path_a, "self_comparison")

        for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
            m = result["metrics"][metric]
            assert abs(m["delta"]) < 1e-6, \
                f"{metric} delta should be 0 for identical systems, got {m['delta']}"
            assert not m["significant"], \
                f"{metric} should not be significant for identical systems (p={m['p_value']})"

    def test_compare_means_match_evaluate(self):
        """Compare means should match the evaluate weighted averages."""
        path_a = self._run_evaluate(PRED_A, "system_a")
        path_b = self._run_evaluate(PRED_B, "system_b")

        with open(path_a) as f:
            eval_a = json.load(f)
        with open(path_b) as f:
            eval_b = json.load(f)

        result = self._run_compare(path_a, path_b, "comparison")

        # mean_a nDCG@5 should match system_a's weighted average nDCG@5
        assert abs(result["metrics"]["nDCG@5"]["mean_a"] -
                   eval_a["retrieval"]["weighted_average"]["nDCG@5"]) < TOLERANCE, \
            "mean_a nDCG@5 should match system_a weighted average"

        assert abs(result["metrics"]["nDCG@5"]["mean_b"] -
                   eval_b["retrieval"]["weighted_average"]["nDCG@5"]) < TOLERANCE, \
            "mean_b nDCG@5 should match system_b weighted average"

        # ROUGE-L means should match
        assert abs(result["metrics"]["ROUGE-L_F1"]["mean_a"] -
                   eval_a["generation"]["rouge_l_f1"]) < TOLERANCE, \
            "mean_a ROUGE-L should match system_a rouge_l_f1"
