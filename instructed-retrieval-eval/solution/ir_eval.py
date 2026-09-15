#!/usr/bin/env python3
"""
Complete IR evaluation pipeline using pytrec_eval-terrier and scipy.
"""
import importlib.metadata
import json
import math
import os
import random
import re
from collections import Counter, defaultdict

import pytrec_eval
import scipy
from scipy.stats import kendalltau

DATA_DIR = "/app/data"
OUTPUT_PATH = "/app/results.json"
BM25_K1 = 1.2
BM25_B = 0.75
NUM_PERMUTATIONS = 10000
SIGNIFICANCE_LEVEL = 0.05
RANDOM_SEED = 42

METRICS_LIST = ["ndcg@5", "ndcg@10", "map@10", "mrr@10",
                "recall@10", "recall@100", "precision@5", "precision@10"]

PYTREC_MEASURES = {'ndcg_cut_5', 'ndcg_cut_10', 'map_cut_10',
                   'recall_10', 'recall_100', 'P_5', 'P_10'}

PYTREC_TO_OUTPUT = {
    'ndcg_cut_5': 'ndcg@5',
    'ndcg_cut_10': 'ndcg@10',
    'map_cut_10': 'map@10',
    'recall_10': 'recall@10',
    'recall_100': 'recall@100',
    'P_5': 'precision@5',
    'P_10': 'precision@10',
}

RANK_CORR_PAIRS = [
    ("ndcg@10", "map@10"),
    ("ndcg@10", "ndcg@5"),
    ("ndcg@5", "map@10"),
]


# ============================================================
# Tokenization
# ============================================================

def tokenize(text):
    """Lowercase, split on non-alphanumeric, remove tokens < 2 chars."""
    tokens = re.split(r'[^a-zA-Z0-9]+', text.lower())
    return [t for t in tokens if len(t) >= 2]


# ============================================================
# BM25 Retriever (Okapi BM25)
# ============================================================

class BM25:
    def __init__(self, corpus, k1=BM25_K1, b=BM25_B):
        self.k1 = k1
        self.b = b
        self.doc_ids = [doc["docid"] for doc in corpus]
        self.doc_tokens = [tokenize(doc["text"]) for doc in corpus]
        self.doc_lens = [len(t) for t in self.doc_tokens]
        self.avgdl = sum(self.doc_lens) / len(self.doc_lens) if self.doc_lens else 1
        self.N = len(corpus)
        self.df = Counter()
        self.tf = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            self.tf.append(tf)
            for term in set(tokens):
                self.df[term] += 1

    def _idf(self, term):
        """Okapi IDF: log((N - df + 0.5) / (df + 0.5) + 1)."""
        df = self.df.get(term, 0)
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)

    def retrieve(self, query_text, top_k=100):
        """Retrieve top-k documents using Okapi BM25 scoring."""
        tokens = tokenize(query_text)
        scores = []
        for i in range(self.N):
            s = 0.0
            dl = self.doc_lens[i]
            for term in tokens:
                tf = self.tf[i].get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s += idf * numerator / denominator
            scores.append((self.doc_ids[i], s))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


# ============================================================
# Data Loading
# ============================================================

def load_task_info(task_dir):
    with open(os.path.join(task_dir, "task_info.json")) as f:
        return json.load(f)


def load_queries(task_dir):
    queries = []
    with open(os.path.join(task_dir, "queries.jsonl")) as f:
        for line in f:
            queries.append(json.loads(line))
    return queries


def load_corpus(task_dir):
    corpus = []
    with open(os.path.join(task_dir, "corpus.jsonl")) as f:
        for line in f:
            corpus.append(json.loads(line))
    return corpus


def load_qrels(task_dir):
    qrels = {}
    with open(os.path.join(task_dir, "qrels.tsv")) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, _, docid, rel = parts
            qrels.setdefault(qid, {})[docid] = int(rel)
    return qrels


def load_run_file(path):
    """Load TREC-format run file. Returns dict: qid -> [(docid, score), ...]."""
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, _, docid, rank, score, _ = parts
            run[qid].append((docid, float(score)))
    for qid in run:
        run[qid].sort(key=lambda x: -x[1])
    return dict(run)


# ============================================================
# pytrec_eval Integration
# ============================================================

def run_to_pytrec_format(run):
    """Convert run from {qid: [(docid, score), ...]} to pytrec {qid: {docid: score}}."""
    return {qid: {docid: score for docid, score in docs} for qid, docs in run.items()}


def truncate_run(run, k):
    """Truncate run to top-k documents per query."""
    return {qid: docs[:k] for qid, docs in run.items()}


def evaluate_with_pytrec(qrels, run):
    """Compute all metrics using pytrec_eval-terrier.

    Returns (metrics_dict, per_query_results).
    """
    pytrec_run_full = run_to_pytrec_format(run)
    pytrec_run_top10 = run_to_pytrec_format(truncate_run(run, 10))

    # Standard metrics via pytrec_eval
    evaluator = pytrec_eval.RelevanceEvaluator(qrels, PYTREC_MEASURES)
    per_query = evaluator.evaluate(pytrec_run_full)

    metrics = {}
    for pytrec_name, output_name in PYTREC_TO_OUTPUT.items():
        vals = [per_query[qid][pytrec_name] for qid in per_query]
        metrics[output_name] = sum(vals) / len(vals) if vals else 0.0

    # MRR@10: trec_eval's recip_rank has no cutoff, so truncate run to top-10
    mrr_evaluator = pytrec_eval.RelevanceEvaluator(qrels, {'recip_rank'})
    mrr_pq = mrr_evaluator.evaluate(pytrec_run_top10)
    mrr_vals = [mrr_pq[qid]['recip_rank'] for qid in mrr_pq]
    metrics['mrr@10'] = sum(mrr_vals) / len(mrr_vals) if mrr_vals else 0.0

    return metrics, per_query


# ============================================================
# Significance Testing
# ============================================================

def paired_permutation_test(per_query_a, per_query_b, target_measure,
                            num_permutations=NUM_PERMUTATIONS, seed=RANDOM_SEED):
    """Two-sided paired permutation test on per-query metric scores."""
    common_qids = sorted(set(per_query_a.keys()) & set(per_query_b.keys()))
    if not common_qids:
        return 0.0, 1.0

    scores_a = [per_query_a[qid][target_measure] for qid in common_qids]
    scores_b = [per_query_b[qid][target_measure] for qid in common_qids]
    n = len(common_qids)

    observed_delta = sum(scores_a) / n - sum(scores_b) / n
    diffs = [scores_a[i] - scores_b[i] for i in range(n)]

    rng = random.Random(seed)
    count = 0
    for _ in range(num_permutations):
        perm_delta = 0.0
        for d in diffs:
            if rng.random() < 0.5:
                perm_delta += d
            else:
                perm_delta -= d
        perm_delta /= n
        if abs(perm_delta) >= abs(observed_delta):
            count += 1

    p_value = count / num_permutations
    return observed_delta, p_value


# ============================================================
# Rank Correlation Analysis
# ============================================================

def compute_rank_correlations(aggregate):
    """Compute Kendall's tau between system rankings for metric pairs."""
    systems = ["neural_a", "neural_b", "bm25_plain", "bm25_instructed"]
    rank_corr = {}
    for metric_a, metric_b in RANK_CORR_PAIRS:
        scores_a = [aggregate[s][metric_a] for s in systems]
        scores_b = [aggregate[s][metric_b] for s in systems]
        tau, p_value = kendalltau(scores_a, scores_b)

        ranking_a = sorted(systems, key=lambda s: -aggregate[s][metric_a])
        ranking_b = sorted(systems, key=lambda s: -aggregate[s][metric_b])

        key = f"{metric_a}_vs_{metric_b}"
        rank_corr[key] = {
            "tau": round(float(tau), 6),
            "p_value": round(float(p_value), 6),
            "system_ranking_a": ranking_a,
            "system_ranking_b": ranking_b,
        }
    return rank_corr


# ============================================================
# Main Pipeline
# ============================================================

def process_task(task_name):
    """Process a single task: load data, run BM25, evaluate all systems."""
    task_dir = os.path.join(DATA_DIR, task_name)
    task_info = load_task_info(task_dir)
    queries = load_queries(task_dir)
    corpus = load_corpus(task_dir)
    qrels = load_qrels(task_dir)

    # Load neural runs
    neural_a = load_run_file(os.path.join(task_dir, "runs", "neural_a.tsv"))
    neural_b = load_run_file(os.path.join(task_dir, "runs", "neural_b.tsv"))

    # BM25 retrieval
    bm25 = BM25(corpus)
    instruction = task_info["instruction"]

    bm25_plain = {}
    bm25_instructed = {}
    for q in queries:
        qid = q["qid"]
        bm25_plain[qid] = bm25.retrieve(q["text"], top_k=100)
        bm25_instructed[qid] = bm25.retrieve(instruction + " " + q["text"], top_k=100)

    # Evaluate all systems via pytrec_eval
    systems = {
        "neural_a": neural_a,
        "neural_b": neural_b,
        "bm25_plain": bm25_plain,
        "bm25_instructed": bm25_instructed,
    }

    task_results = {}
    per_query_results = {}
    for sys_name, run in systems.items():
        metrics, pq = evaluate_with_pytrec(qrels, run)
        task_results[sys_name] = metrics
        per_query_results[sys_name] = pq

    # Significance tests on nDCG@10
    delta_ab, p_ab = paired_permutation_test(
        per_query_results["neural_a"], per_query_results["neural_b"],
        'ndcg_cut_10')
    delta_bm25, p_bm25 = paired_permutation_test(
        per_query_results["bm25_plain"], per_query_results["bm25_instructed"],
        'ndcg_cut_10')

    sig_results = {
        "neural_a_vs_neural_b": {
            "metric": "ndcg@10",
            "delta": round(delta_ab, 6),
            "p_value": round(p_ab, 6),
            "significant": p_ab < SIGNIFICANCE_LEVEL,
        },
        "bm25_plain_vs_bm25_instructed": {
            "metric": "ndcg@10",
            "delta": round(delta_bm25, 6),
            "p_value": round(p_bm25, 6),
            "significant": p_bm25 < SIGNIFICANCE_LEVEL,
        },
    }

    return task_results, sig_results


def main():
    tasks = sorted([d for d in os.listdir(DATA_DIR)
                    if os.path.isdir(os.path.join(DATA_DIR, d))])

    all_per_task = {}
    all_significance = {}

    for task_name in tasks:
        print(f"Processing task: {task_name}")
        task_results, sig_results = process_task(task_name)
        all_per_task[task_name] = task_results
        all_significance[task_name] = sig_results

    # Compute aggregate: macro-average across tasks
    all_systems = ["neural_a", "neural_b", "bm25_plain", "bm25_instructed"]
    aggregate = {}
    for sys_name in all_systems:
        agg_metrics = {}
        for metric in METRICS_LIST:
            vals = [all_per_task[t][sys_name][metric] for t in tasks]
            agg_metrics[metric] = round(sum(vals) / len(vals), 6)
        aggregate[sys_name] = agg_metrics

    # Round per-task metrics
    for task_name in tasks:
        for sys_name in all_systems:
            for metric in METRICS_LIST:
                all_per_task[task_name][sys_name][metric] = round(
                    all_per_task[task_name][sys_name][metric], 6
                )

    # Rank correlation analysis using scipy
    rank_corr = compute_rank_correlations(aggregate)

    # Get tool versions
    try:
        pytrec_version = importlib.metadata.version("pytrec-eval-terrier")
    except Exception:
        pytrec_version = "unknown"

    output = {
        "per_task": all_per_task,
        "aggregate": aggregate,
        "significance_tests": all_significance,
        "rank_correlation": rank_corr,
        "meta": {
            "num_tasks": len(tasks),
            "metrics_computed": METRICS_LIST,
            "bm25_params": {"k1": BM25_K1, "b": BM25_B},
            "significance_level": SIGNIFICANCE_LEVEL,
            "num_permutations": NUM_PERMUTATIONS,
            "tools": {
                "pytrec_eval_version": pytrec_version,
                "scipy_version": scipy.__version__,
            },
        },
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
