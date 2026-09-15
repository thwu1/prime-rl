
"""Evaluate retrieval runs and perform term-level BM25 analysis."""

import json
import subprocess


def run_trec_eval(qrels_path, run_path, metrics):
    """Run pyserini.eval.trec_eval and parse metric values."""
    cmd = ["python3", "-m", "pyserini.eval.trec_eval"]
    for m in metrics:
        cmd.extend(["-m", m])
    cmd.extend([qrels_path, run_path])

    result = subprocess.run(cmd, capture_output=True, text=True)
    parsed = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "all":
            parsed[parts[0]] = round(float(parts[2]), 4)
    return parsed


def evaluate_all_runs():
    """Evaluate all four runs and write results.json."""
    qrels = "/app/qrels.txt"
    run_configs = {
        "bm25_default": "/app/runs/bm25_default.txt",
        "bm25_tuned": "/app/runs/bm25_tuned.txt",
        "bm25_expanded": "/app/runs/bm25_expanded.txt",
        "fused": "/app/runs/fused.txt",
    }

    results = {}
    for name, run_path in run_configs.items():
        metrics = run_trec_eval(qrels, run_path, ["map", "ndcg_cut.10"])
        results[name] = {
            "map": metrics.get("map", 0.0),
            "ndcg_cut_10": metrics.get("ndcg_cut_10", 0.0),
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    return results


def perform_term_analysis():
    """For each query, compute top-5 BM25 term weights for the top document."""
    from pyserini.index.lucene import LuceneIndexReader

    index_reader = LuceneIndexReader("/app/index")

    # Read queries
    queries = {}
    with open("/app/queries.tsv") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                queries[parts[0]] = parts[1]

    # Read BM25 default run to find top document per query
    top_docs = {}
    with open("/app/runs/bm25_default.txt") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                qid = parts[0]
                docid = parts[2]
                if qid not in top_docs:
                    top_docs[qid] = docid

    # For each query, compute per-term BM25 weights for the top document
    term_analysis = {}
    for qid in sorted(queries.keys()):
        if qid not in top_docs:
            continue
        top_doc = top_docs[qid]

        # get_document_vector returns analyzed (stemmed) terms
        doc_vector = index_reader.get_document_vector(top_doc)
        if doc_vector is None:
            continue

        # Compute BM25 term weights using analyzer=None
        # because terms from get_document_vector are already analyzed
        bm25_weights = {}
        for term in doc_vector:
            weight = index_reader.compute_bm25_term_weight(
                top_doc, term, analyzer=None
            )
            if weight > 0:
                bm25_weights[term] = round(float(weight), 5)

        # Sort by weight descending, take top 5
        top_terms = sorted(bm25_weights.items(), key=lambda x: -x[1])[:5]

        term_analysis[qid] = {
            "top_doc": top_doc,
            "top_terms": [{"term": t, "weight": w} for t, w in top_terms],
        }

    with open("/app/term_analysis.json", "w") as f:
        json.dump(term_analysis, f, indent=2)


if __name__ == "__main__":
    print("Evaluating retrieval runs...")
    results = evaluate_all_runs()
    for name, metrics in results.items():
        print(
            f"  {name}: MAP={metrics['map']:.4f} "
            f"nDCG@10={metrics['ndcg_cut_10']:.4f}"
        )

    print("Computing term analysis...")
    perform_term_analysis()
    print("Done.")
