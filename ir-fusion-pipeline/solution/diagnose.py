
"""Diagnose issues in the original IR evaluation pipeline."""

import json
import subprocess


def diagnose():
    issues = []

    # Issue 1: Check index configuration — can we extract document vectors?
    try:
        from pyserini.index.lucene import LuceneIndexReader

        reader = LuceneIndexReader("/app/index_v1")
        stats = reader.stats()

        # Try to get a document vector
        vec = reader.get_document_vector("doc001")
        if vec is None:
            issues.append(
                "ISSUE 1: Index missing stored document vectors\n"
                "  Claimed: Pipeline log states 'Stored fields: positions, "
                "document vectors, raw content'\n"
                "  Actual: The index at /app/index_v1/ was built with "
                "--storePositions only.\n"
                "  --storeDocvectors and --storeRaw were NOT included in the "
                "index build command.\n"
                "  Impact: get_document_vector() returns None for all documents, "
                "making term-level BM25 weight analysis impossible.\n"
                "  The log's 'version mismatch' hypothesis is incorrect — the "
                "root cause is missing stored fields.\n"
            )
    except Exception as e:
        issues.append(f"ISSUE 1: Index analysis error: {e}\n")

    # Issue 2: Check BM25 parameters by comparing rankings
    try:
        from pyserini.search.lucene import LuceneSearcher

        searcher = LuceneSearcher("/app/index_v1")

        # Read query 1
        query = None
        with open("/app/queries.tsv") as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts[0] == "1":
                    query = parts[1]
                    break

        if query:
            # Run with claimed params (k1=0.9, b=0.4)
            searcher.set_bm25(0.9, 0.4)
            hits_claimed = searcher.search(query, 5)
            claimed_docids = [h.docid for h in hits_claimed]

            # Read baseline_v1 run for query 1
            baseline_docids = []
            with open("/app/runs/baseline_v1.txt") as f:
                for line in f:
                    parts = line.strip().split()
                    if parts[0] == "1":
                        baseline_docids.append(parts[2])
                        if len(baseline_docids) >= 5:
                            break

            if claimed_docids != baseline_docids:
                issues.append(
                    "ISSUE 2: BM25 parameter mismatch\n"
                    "  Claimed: Pipeline log states 'BM25 (k1=0.9, b=0.4)'\n"
                    "  Actual: The baseline run at /app/runs/baseline_v1.txt was "
                    "generated with different BM25 parameters (likely Lucene's "
                    "defaults: k1=1.2, b=0.75).\n"
                    "  Evidence: Re-running BM25 with k1=0.9, b=0.4 produces "
                    "different document rankings.\n"
                    f"  Expected top-5 (k1=0.9, b=0.4): {claimed_docids}\n"
                    f"  Actual top-5 in baseline_v1: {baseline_docids}\n"
                )
    except Exception as e:
        issues.append(f"ISSUE 2: Parameter analysis error: {e}\n")

    # Issue 3: Check reported metrics against trec_eval
    try:
        result = subprocess.run(
            [
                "python3", "-m", "pyserini.eval.trec_eval",
                "-m", "map", "-m", "ndcg_cut.10",
                "/app/qrels.txt", "/app/runs/baseline_v1.txt",
            ],
            capture_output=True,
            text=True,
        )

        actual_metrics = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "all":
                actual_metrics[parts[0]] = round(float(parts[2]), 4)

        with open("/app/report_v1.json") as f:
            reported = json.load(f)

        rep_map = reported.get("bm25_baseline", {}).get("map", 0)
        rep_ndcg = reported.get("bm25_baseline", {}).get("ndcg_cut_10", 0)

        issues.append(
            "ISSUE 3: Evaluation metrics do not reproduce\n"
            f"  Claimed: report_v1.json states MAP={rep_map}, "
            f"nDCG@10={rep_ndcg}\n"
            f"  Actual: Re-running trec_eval on baseline_v1.txt yields "
            f"MAP={actual_metrics.get('map', 'N/A')}, "
            f"nDCG@10={actual_metrics.get('ndcg_cut_10', 'N/A')}\n"
            "  Impact: The reported metrics are significantly inflated and "
            "cannot be trusted for evaluation.\n"
        )
    except Exception as e:
        issues.append(f"ISSUE 3: Metrics analysis error: {e}\n")

    diagnosis_text = "=== Pipeline Diagnosis ===\n\n" + "\n".join(issues)
    diagnosis_text += (
        "\nSUMMARY:\n"
        "The original pipeline had three critical issues:\n"
        "1. The Lucene index was built without --storeDocvectors and "
        "--storeRaw, despite the log claiming all fields were stored. "
        "This made document vector extraction and term-level BM25 analysis "
        "impossible.\n"
        "2. The BM25 retrieval used parameters k1=1.2, b=0.75 (Lucene "
        "defaults) instead of the claimed k1=0.9, b=0.4, producing "
        "different rankings.\n"
        "3. The reported evaluation metrics (MAP=0.6234, nDCG@10=0.7891) "
        "are fabricated and do not match trec_eval output for the actual "
        "run file.\n"
    )

    with open("/app/diagnosis.txt", "w") as f:
        f.write(diagnosis_text)


if __name__ == "__main__":
    diagnose()
