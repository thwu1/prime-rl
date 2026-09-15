#!/usr/bin/env python3
"""Generate benchmark data for retrieval evaluation and fusion optimization task.

Creates:
- TREC-format qrels with graded relevance (0-3)
- TREC-format retrieval runs for 4 models (one with a column format issue)
- Query metadata JSONL
"""
import json
import os
import random


def main():
    os.makedirs("/app/data/runs", exist_ok=True)

    domains = ["biology", "economics", "coding"]
    DOC_PREFIX = {"biology": "d_bio", "economics": "d_econ", "coding": "d_code"}
    Q_PREFIX = {"biology": "q_bio", "economics": "q_econ", "coding": "q_code"}
    DOCS_PER_DOMAIN = 30
    TOP_K = 20

    # Graded relevance: 3=highly relevant, 2=relevant, 1=marginally relevant
    QUERY_DEFS = {
        "biology": [
            {"idx": 0, "gold": {0: 3, 3: 2, 7: 2, 12: 1, 18: 1}},
            {"idx": 1, "gold": {2: 3, 5: 3, 14: 2, 20: 1}},
            {"idx": 2, "gold": {1: 3, 8: 2, 11: 2, 16: 1, 22: 1, 27: 1}},
            {"idx": 3, "gold": {4: 3, 9: 2, 15: 1, 23: 1}},
            {"idx": 4, "gold": {6: 3, 10: 3, 13: 2, 19: 1, 25: 1}},
            {"idx": 5, "gold": {17: 3, 21: 2, 24: 2, 28: 1}},
        ],
        "economics": [
            {"idx": 0, "gold": {1: 3, 4: 3, 10: 2, 15: 1}},
            {"idx": 1, "gold": {3: 3, 7: 2, 13: 2, 20: 1, 25: 1}},
            {"idx": 2, "gold": {0: 3, 6: 2, 11: 2, 18: 1, 22: 1}},
            {"idx": 3, "gold": {2: 3, 8: 3, 14: 2, 19: 1}},
            {"idx": 4, "gold": {5: 3, 9: 2, 16: 2, 23: 1, 27: 1}},
            {"idx": 5, "gold": {12: 3, 17: 2, 21: 2, 26: 1, 29: 1}},
        ],
        "coding": [
            {"idx": 0, "gold": {0: 3, 6: 3, 12: 2, 18: 1, 24: 1}},
            {"idx": 1, "gold": {2: 3, 8: 2, 14: 2, 20: 1}},
            {"idx": 2, "gold": {4: 3, 10: 3, 16: 2, 22: 1, 28: 1}},
            {"idx": 3, "gold": {1: 3, 9: 2, 15: 2, 21: 1, 27: 1}},
            {"idx": 4, "gold": {3: 3, 7: 3, 13: 2, 19: 1, 25: 1}},
            {"idx": 5, "gold": {5: 3, 11: 2, 17: 2, 23: 1, 29: 1}},
        ],
    }

    MODEL_IDX = {"bm25": 0, "dense": 1, "sparse": 2, "reranker": 3}

    QUERY_TEXTS = {
        "biology": [
            "Why do certain enzymes exhibit allosteric regulation while others follow standard Michaelis-Menten kinetics?",
            "How do histone modifications coordinate with DNA methylation to maintain pluripotency in embryonic stem cells?",
            "What molecular evidence supports the endosymbiotic origin of mitochondria?",
            "How does lateral gene transfer confound phylogenetic tree reconstruction methods?",
            "What cellular mechanisms prevent autoimmune destruction of self-tissues?",
            "How do quorum sensing pathways differ between Gram-positive and Gram-negative bacteria?",
        ],
        "economics": [
            "How does monetary policy transmission change at the zero lower bound?",
            "What welfare effects arise from monopsony power in labor markets?",
            "How do adverse selection and moral hazard create market failures in insurance?",
            "What role do rational expectations play in the Phillips curve breakdown?",
            "Through what mechanisms does financial contagion propagate across banking systems?",
            "How do sovereign debt dynamics interact with currency crisis models?",
        ],
        "coding": [
            "Design an algorithm achieving O(n) time for finding the longest palindromic substring.",
            "How can lock-free concurrent data structures avoid the ABA problem?",
            "What data structure supports O(1) range minimum queries after O(n log n) preprocessing?",
            "How should consistent hashing handle virtual nodes for balanced load distribution?",
            "What is the relationship between topological sorting and cycle detection in directed graphs?",
            "How do persistent data structures enable efficient versioning in functional programming?",
        ],
    }

    # --- Generate queries JSONL ---
    queries = []
    for domain in domains:
        q_prefix = Q_PREFIX[domain]
        for i, qd in enumerate(QUERY_DEFS[domain]):
            queries.append({
                "id": f"{q_prefix}_{qd['idx']}",
                "domain": domain,
                "query": QUERY_TEXTS[domain][i],
            })

    with open("/app/data/queries.jsonl", "w") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")

    # --- Generate qrels (TREC format with graded relevance) ---
    qrels_lines = []
    for domain in domains:
        d_prefix = DOC_PREFIX[domain]
        q_prefix = Q_PREFIX[domain]
        for qd in QUERY_DEFS[domain]:
            qid = f"{q_prefix}_{qd['idx']}"
            for doc_idx in sorted(qd["gold"].keys()):
                rel = qd["gold"][doc_idx]
                did = f"{d_prefix}_{doc_idx:02d}"
                qrels_lines.append(f"{qid} 0 {did} {rel}")

    with open("/app/data/qrels.txt", "w") as f:
        f.write("\n".join(qrels_lines) + "\n")

    # --- Score generation ---
    def model_finds_gold(model, domain, doc_idx, query_idx):
        """Whether model assigns high score to a gold document."""
        midx = MODEL_IDX[model]
        if domain == "biology":
            # ~55% find rate, different docs per model (diversity for RRF)
            h = (doc_idx * 13 + midx * 37 + query_idx * 7) % 100
            return h < 55
        elif domain == "economics":
            # All models find all gold docs (overlapping for CombSUM)
            return True
        else:  # coding
            # ~85% find rate, with model-specific false positives
            h = (doc_idx * 11 + midx * 31 + query_idx * 5) % 100
            return h < 85

    def get_score(model, domain, doc_idx, query_idx, is_gold, rel_level, finds_it, rng):
        """Generate a retrieval score."""
        if model == "bm25":
            if is_gold and finds_it:
                return rng.uniform(15.0, 25.0) * (0.7 + 0.1 * rel_level)
            elif is_gold:
                return rng.uniform(2.0, 7.0)
            elif domain == "coding" and (doc_idx * 13 + query_idx * 7) % 11 < 3:
                return rng.uniform(10.0, 18.0)
            else:
                return rng.uniform(0.5, 11.0)
        elif model == "dense":
            if is_gold and finds_it:
                return rng.uniform(0.65, 0.96) * (0.7 + 0.1 * rel_level)
            elif is_gold:
                return rng.uniform(0.10, 0.35)
            elif domain == "coding" and (doc_idx * 17 + query_idx * 11) % 13 < 3:
                return rng.uniform(0.50, 0.80)
            else:
                return rng.uniform(0.02, 0.48)
        elif model == "sparse":
            if is_gold and finds_it:
                return rng.uniform(10.0, 19.0) * (0.7 + 0.1 * rel_level)
            elif is_gold:
                return rng.uniform(1.5, 5.0)
            elif domain == "coding" and (doc_idx * 19 + query_idx * 13) % 11 < 3:
                return rng.uniform(8.0, 15.0)
            else:
                return rng.uniform(0.2, 8.5)
        else:  # reranker
            if is_gold and finds_it:
                return rng.uniform(0.55, 0.92) * (0.7 + 0.1 * rel_level)
            elif is_gold:
                return rng.uniform(0.08, 0.32)
            elif domain == "coding" and (doc_idx * 23 + query_idx * 17) % 11 < 3:
                return rng.uniform(0.40, 0.75)
            else:
                return rng.uniform(0.01, 0.38)

    # --- Generate retrieval runs in TREC format ---
    models = ["bm25", "dense", "sparse", "reranker"]

    for model in models:
        seed = {"bm25": 42, "dense": 137, "sparse": 256, "reranker": 789}[model]
        rng = random.Random(seed)

        run_lines = []

        for domain in domains:
            d_prefix = DOC_PREFIX[domain]
            q_prefix = Q_PREFIX[domain]

            for qd in QUERY_DEFS[domain]:
                qid = f"{q_prefix}_{qd['idx']}"
                gold = qd["gold"]

                doc_scores = []
                for doc_idx in range(DOCS_PER_DOMAIN):
                    did = f"{d_prefix}_{doc_idx:02d}"
                    is_gold = doc_idx in gold
                    rel_level = gold.get(doc_idx, 0)
                    finds_it = model_finds_gold(model, domain, doc_idx, qd["idx"]) if is_gold else False
                    score = get_score(model, domain, doc_idx, qd["idx"],
                                     is_gold, rel_level, finds_it, rng)
                    doc_scores.append((did, round(score, 4)))

                doc_scores.sort(key=lambda x: x[1], reverse=True)
                doc_scores = doc_scores[:TOP_K]

                for rank, (did, score) in enumerate(doc_scores, 1):
                    if model == "dense":
                        # Column format issue: rank and score positions swapped
                        # Standard: qid Q0 docid rank score run_name
                        # This file: qid Q0 docid score rank run_name
                        run_lines.append(
                            f"{qid} Q0 {did} {score:.4f} {rank} {model}"
                        )
                    else:
                        run_lines.append(
                            f"{qid} Q0 {did} {rank} {score:.4f} {model}"
                        )

        with open(f"/app/data/runs/{model}.trec", "w") as f:
            f.write("\n".join(run_lines) + "\n")

    print(f"Generated {len(queries)} queries, {len(qrels_lines)} qrels, "
          f"{len(models)} run files (top-{TOP_K})")


if __name__ == "__main__":
    main()
