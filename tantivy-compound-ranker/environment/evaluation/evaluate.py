#!/usr/bin/env python3
"""Search engine evaluation harness.

Computes NDCG@10 for each query using graded relevance judgments.
Run via: make evaluate
"""

import json
import sys

sys.path.insert(0, "/app")
from evaluation.metrics import ndcg_at_k


def main():
    with open("/app/output.json") as f:
        output = json.load(f)

    with open("/app/data/qrels.json") as f:
        raw_qrels = json.load(f)

    print("NDCG@10 per query:")
    scores = []
    for query in sorted(output.keys()):
        if query not in raw_qrels:
            print(f"  {query}: no qrels available")
            continue
        ranked_ids = [r["doc_id"] for r in output[query]]
        grades = {int(k): v for k, v in raw_qrels[query].items()}
        score = ndcg_at_k(ranked_ids, grades, k=10)
        scores.append(score)
        status = "PASS" if score >= 0.80 else "FAIL"
        print(f"  [{status}] {query}: {score:.4f}")

    if scores:
        avg = sum(scores) / len(scores)
        print(f"\nAverage NDCG@10: {avg:.4f}")
        if all(s >= 0.80 for s in scores):
            print("All queries PASS (>= 0.80)")
        else:
            print("Some queries FAIL (< 0.80)")
            sys.exit(1)


if __name__ == "__main__":
    main()
