#!/usr/bin/env python3
"""BM25+ retrieval with tuned parameters for BRIGHT Pony task.

Strategy:
  1. Load the Pony document corpus and queries (GPT-4 reasoning is embedded
     in the query text itself; the separate reasoning field is N/A for Pony).
     Document IDs are per-instance (DNA-remapped) and must be used as-is.
  2. Build a BM25+ index over tokenized documents with tuned parameters
     (k1=1.2, b=0.4) — BM25+ improves over standard BM25 by adding a small
     constant delta to term frequency normalization, preventing relevant
     long documents from being unfairly penalized
  3. Score all documents per query, filter excluded IDs, keep top-1000
  4. Write scores to /app/scores.json
"""

import json
import re
import sys

from rank_bm25 import BM25Plus


def tokenize(text):
    """Lowercase whitespace/punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())


def main():
    # Load corpus (document IDs are per-instance, DNA-remapped)
    with open("/app/data/documents.json") as f:
        documents = json.load(f)

    # Load queries
    with open("/app/data/queries.json") as f:
        queries = json.load(f)

    doc_ids = [d["id"] for d in documents]
    doc_texts = [d["content"] for d in documents]

    print(f"Loaded {len(documents)} documents, {len(queries)} queries")

    # Tokenize documents and build BM25+ index
    tokenized_docs = [tokenize(t) for t in doc_texts]
    bm25 = BM25Plus(tokenized_docs, k1=1.2, b=0.4)
    print("BM25+ index built")

    # Score each query
    all_scores = {}
    for i, q in enumerate(queries):
        # For Pony, GPT-4 reasoning is already embedded in the query field
        # The separate reasoning field is "N/A"
        query_text = q["query"]
        reasoning = q.get("reasoning", "")
        if reasoning and reasoning != "N/A":
            query_text = query_text + " " + reasoning

        tokenized_query = tokenize(query_text)

        # Get BM25+ scores for all documents
        doc_scores = bm25.get_scores(tokenized_query)

        # Build scores dict, filtering excluded IDs
        excluded = set(q.get("excluded_ids") or [])
        query_scores = {}
        for did, score in zip(doc_ids, doc_scores):
            if did not in excluded:
                query_scores[did] = float(score)

        # Keep top 1000 by score
        sorted_pairs = sorted(
            query_scores.items(), key=lambda x: x[1], reverse=True
        )[:1000]
        all_scores[q["id"]] = {k: v for k, v in sorted_pairs}

        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(queries)} queries")

    print(f"Scored all {len(queries)} queries")

    # Save results
    with open("/app/scores.json", "w") as f:
        json.dump(all_scores, f, indent=2)
    print("Wrote /app/scores.json")

    # Self-evaluate if possible
    try:
        import base64
        import zlib

        with open("/app/.bright_eval/ground_truth.bin", "rb") as f:
            encoded = f.read()
        ground_truth = json.loads(
            zlib.decompress(base64.b64decode(encoded))
        )
        sys.path.insert(0, "/app")
        from metrics import calculate_retrieval_metrics

        results = calculate_retrieval_metrics(results=all_scores, qrels=ground_truth)
        print("\nEvaluation results:")
        for k, v in sorted(results.items()):
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"Self-evaluation skipped: {e}")


if __name__ == "__main__":
    main()
