#!/usr/bin/env python3
"""
Diagnose baseline retrieval runs, optimize BM25 parameters,
and produce all required deliverables.
"""

import json
import os
import subprocess
import sys

APP_DIR = "/app"
TOOLS_DIR = "/app/tools"
RUNS_DIR = "/app/runs"
RESULTS_DIR = "/app/results"
INDEX_FILE = "/app/index.json"
QRELS_FILE = "/app/qrels.txt"
QUERIES_FILE = "/app/queries.tsv"
TARGETS_FILE = "/app/targets.json"

os.makedirs(RESULTS_DIR, exist_ok=True)

# Import tools directly for efficient grid search
sys.path.insert(0, TOOLS_DIR)
from bm25_search import load_index, load_queries, search_bm25, write_run
from evaluate import load_qrels, load_run, compute_metrics


def run_eval_cli(run_file):
    """Run evaluation via CLI (consistent with tests)."""
    r = subprocess.run(
        ["python3", os.path.join(TOOLS_DIR, "evaluate.py"),
         "--qrels", QRELS_FILE, "--run", run_file, "-c"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  WARNING: evaluate.py failed for {run_file}: {r.stderr}", file=sys.stderr)
    metrics = {}
    for line in r.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            try:
                metrics[parts[0].strip()] = float(parts[2].strip())
            except ValueError:
                pass
    return metrics


def get_query_ids_in_run(run_file):
    """Extract unique query IDs from a TREC run file."""
    qids = set()
    with open(run_file) as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                qids.add(parts[0])
    return qids


def count_results_per_query(run_file):
    """Count results per query in a TREC run file."""
    counts = {}
    with open(run_file) as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                qid = parts[0]
                counts[qid] = counts.get(qid, 0) + 1
    return counts


def get_score_stats(run_file):
    """Get score statistics from a TREC run file."""
    scores = []
    with open(run_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                try:
                    scores.append(float(parts[4]))
                except ValueError:
                    pass
    if not scores:
        return {}
    return {
        'min': min(scores),
        'max': max(scores),
        'mean': sum(scores) / len(scores),
        'has_negative': any(s < 0 for s in scores),
    }


# ---------- 1. Diagnose baselines ----------

def diagnose_baselines():
    """Evaluate each baseline and identify deficiencies."""
    with open(TARGETS_FILE) as f:
        targets = json.load(f)

    all_query_ids = set()
    with open(QUERIES_FILE) as f:
        for line in f:
            parts = line.strip().split('\t', 1)
            if len(parts) == 2:
                all_query_ids.add(parts[0])

    diagnosis = {}

    for run_name in ["run_A", "run_B", "run_C"]:
        run_path = os.path.join(RUNS_DIR, run_name + ".txt")
        metrics = run_eval_cli(run_path)
        m = {
            "map": round(metrics.get("map", 0.0), 4),
            "ndcg_cut_10": round(metrics.get("ndcg_cut_10", 0.0), 4),
            "recall_1000": round(metrics.get("recall_1000", 0.0), 4),
        }

        meets = {}
        for mk in ["map", "ndcg_cut_10", "recall_1000"]:
            meets[mk] = m[mk] >= targets[mk]

        # Diagnose deficiency
        qids_in_run = get_query_ids_in_run(run_path)
        missing_queries = all_query_ids - qids_in_run
        result_counts = count_results_per_query(run_path)
        score_stats = get_score_stats(run_path)

        if missing_queries:
            deficiency = (
                "Incomplete query coverage: missing results for queries "
                + str(sorted(missing_queries)) + ". The evaluation tool with -c flag "
                "assigns zero scores for missing queries, dragging down all "
                "aggregate metrics proportionally to the number of missing queries."
            )
        elif score_stats.get('has_negative', False):
            deficiency = (
                "Uses a query likelihood retrieval model with Dirichlet smoothing "
                "instead of BM25. The negative log-probability scores are characteristic "
                "of language model scoring. This model produces substantially worse "
                "ranking quality than well-tuned BM25 on this corpus, with poor MAP "
                "and nDCG@10 due to suboptimal document ranking."
            )
        elif result_counts and max(result_counts.values()) <= 5:
            max_hits = max(result_counts.values())
            deficiency = (
                "Severely truncated result depth: only " + str(max_hits) + " hits returned per "
                "query instead of the standard 1000. With " + str(max_hits) + " results per query "
                "and 5-8 relevant documents per query, many relevant documents are "
                "missed entirely, causing very low recall and degraded MAP."
            )
        else:
            deficiency = (
                "Unknown deficiency: the run file structure appears normal but "
                "metrics do not meet targets."
            )

        diagnosis[run_name] = {**m, "meets_targets": meets, "deficiency": deficiency}
        print("  %s: MAP=%.4f nDCG@10=%.4f R@1000=%.4f" % (
            run_name, m['map'], m['ndcg_cut_10'], m['recall_1000']))

    with open(os.path.join(RESULTS_DIR, "diagnosis.json"), "w") as f:
        json.dump(diagnosis, f, indent=2)
    return diagnosis


# ---------- 2. Grid search BM25 parameters ----------

def grid_search():
    """Search BM25 parameter space and find best configuration."""
    index = load_index(INDEX_FILE)
    queries = load_queries(QUERIES_FILE)
    qrels = load_qrels(QRELS_FILE)

    k1_values = [0.5, 0.7, 0.9, 1.0, 1.2, 1.5, 2.0]
    b_values = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    configs = {}
    best_k1, best_b, best_map = 0.9, 0.4, -1.0

    for k1 in k1_values:
        for b in b_values:
            results = search_bm25(index, queries, k1=k1, b=b, hits=1000)
            write_run(results, '/tmp/_grid_run.txt', 'grid')
            run = load_run('/tmp/_grid_run.txt')
            m = compute_metrics(qrels, run, complete=True)
            config_name = "bm25_k1=%s_b=%s" % (k1, b)
            configs[config_name] = {
                "map": round(m['map'], 4),
                "k1": k1,
                "b": b,
            }
            if m['map'] > best_map:
                best_map = m['map']
                best_k1 = k1
                best_b = b

    if os.path.exists('/tmp/_grid_run.txt'):
        os.remove('/tmp/_grid_run.txt')

    print("  Best BM25: k1=%s, b=%s, MAP~%.4f" % (best_k1, best_b, best_map))
    return configs, best_k1, best_b


# ---------- 3. Evaluate top configurations ----------

def evaluate_top_configs(grid_configs, best_k1, best_b):
    """Run full evaluation on top configs and produce comparison."""
    index = load_index(INDEX_FILE)
    queries = load_queries(QUERIES_FILE)
    all_metrics = {}

    # Evaluate baselines via CLI
    for run_name in ["run_A", "run_B", "run_C"]:
        run_path = os.path.join(RUNS_DIR, run_name + ".txt")
        m = run_eval_cli(run_path)
        all_metrics[run_name] = {
            "map": round(m.get("map", 0.0), 4),
            "ndcg_cut_10": round(m.get("ndcg_cut_10", 0.0), 4),
            "recall_1000": round(m.get("recall_1000", 0.0), 4),
        }

    # Sort grid configs by MAP and take top 4 distinct
    sorted_configs = sorted(grid_configs.items(),
                            key=lambda x: x[1]["map"], reverse=True)
    top_configs = []
    seen = set()
    for name, info in sorted_configs:
        key = (info["k1"], info["b"])
        if key not in seen:
            seen.add(key)
            top_configs.append(info)
            if len(top_configs) >= 4:
                break

    # Evaluate top BM25 configs via CLI
    for i, cfg in enumerate(top_configs):
        k1, b = cfg["k1"], cfg["b"]
        out_path = "/tmp/_eval_%d.txt" % i
        results = search_bm25(index, queries, k1=k1, b=b, hits=1000)
        write_run(results, out_path, 'bm25_%s_%s' % (k1, b))
        m = run_eval_cli(out_path)
        config_name = "bm25_k1=%s_b=%s" % (k1, b)
        all_metrics[config_name] = {
            "map": round(m.get("map", 0.0), 4),
            "ndcg_cut_10": round(m.get("ndcg_cut_10", 0.0), 4),
            "recall_1000": round(m.get("recall_1000", 0.0), 4),
        }
        if os.path.exists(out_path):
            os.remove(out_path)

    with open(os.path.join(RESULTS_DIR, "metrics_comparison.json"), "w") as f:
        json.dump(all_metrics, f, indent=2)
    return all_metrics


# ---------- 4. Produce optimized run and config ----------

def produce_optimized_run(best_k1, best_b, all_metrics):
    """Generate the optimized run file and config JSON."""
    index = load_index(INDEX_FILE)
    queries = load_queries(QUERIES_FILE)

    out_path = os.path.join(RESULTS_DIR, "optimized_run.txt")
    results = search_bm25(index, queries, k1=best_k1, b=best_b, hits=1000)
    write_run(results, out_path, 'optimized')

    m = run_eval_cli(out_path)

    config = {
        "parameters": {
            "model": "BM25",
            "k1": best_k1,
            "b": best_b,
            "hits": 1000,
        },
        "map": round(m.get("map", 0.0), 4),
        "ndcg_cut_10": round(m.get("ndcg_cut_10", 0.0), 4),
        "recall_1000": round(m.get("recall_1000", 0.0), 4),
        "rationale": (
            "After systematic grid search over %d BM25 "
            "parameter configurations, BM25 with k1=%s and b=%s "
            "was selected as optimal. This configuration achieves the highest "
            "MAP across the parameter space. Run A suffered from a severely "
            "truncated result depth (only 3 hits per query), missing most "
            "relevant documents. Run B had incomplete query coverage, missing "
            "3 of 8 queries entirely. Run C used a query likelihood model "
            "(Dirichlet smoothing) instead of BM25, producing poor rankings "
            "characterized by negative log-probability scores."
        ) % (len(all_metrics) - 3, best_k1, best_b),
    }
    with open(os.path.join(RESULTS_DIR, "optimal_config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print("  Optimized: MAP=%.4f nDCG@10=%.4f R@1000=%.4f" % (
        config['map'], config['ndcg_cut_10'], config['recall_1000']))


# ---------- Main ----------

if __name__ == "__main__":
    print("=== Diagnosing baselines ===")
    diagnosis = diagnose_baselines()

    print("=== Grid searching BM25 parameters ===")
    grid_configs, best_k1, best_b = grid_search()

    print("=== Evaluating top configurations ===")
    all_metrics = evaluate_top_configs(grid_configs, best_k1, best_b)

    print("=== Producing optimized run ===")
    produce_optimized_run(best_k1, best_b, all_metrics)

    print("=== All results written to /app/results/ ===")
