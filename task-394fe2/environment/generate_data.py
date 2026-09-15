#!/usr/bin/env python3
"""Generate CRUMB-style evaluation data with deliberate data quality issues.

The generated dataset includes:
- A passage corpus with parent document mappings (some deliberately null)
- Document-level relevance judgments (some with whitespace-corrupted IDs)
- Four passage-level retrieval runs (one with duplicate entries)
"""
import json
import os
import random

SEED = 42
NUM_DOCS = 150
NUM_QUERIES = 20
NUM_RUNS = 4
PASSAGES_PER_QUERY = 200
DEPLOY_DIR = "/opt/crumb_eval"


def main():
    random.seed(SEED)
    os.makedirs(os.path.join(DEPLOY_DIR, "data", "runs"), exist_ok=True)

    # === Corpus: passages with parent document mapping ===
    corpus = []
    doc_to_chunks = {}

    for d in range(NUM_DOCS):
        doc_id = f"doc_{d:03d}"
        n_chunks = random.randint(2, 4)
        doc_to_chunks[doc_id] = []
        for c in range(n_chunks):
            chunk_id = f"{doc_id}:chunk_{c}"
            doc_to_chunks[doc_id].append(chunk_id)
            words = [f"t{random.randint(0, 300)}" for _ in range(30)]
            corpus.append({
                "document_id": chunk_id,
                "document_content": f"## Section {c}\n" + " ".join(words),
                "parent_id": doc_id,
            })

    # Data issue: set 8 passages to have null parent_id (orphaned)
    orphan_rng = random.Random(SEED + 100)
    orphan_indices = sorted(orphan_rng.sample(range(len(corpus)), 8))
    for idx in orphan_indices:
        corpus[idx]["parent_id"] = None

    with open(os.path.join(DEPLOY_DIR, "data", "corpus.jsonl"), "w") as f:
        for item in corpus:
            f.write(json.dumps(item) + "\n")

    # === Relevance judgments (document-level, graded) ===
    all_doc_ids = sorted(doc_to_chunks.keys())
    queries = []
    ws_rng = random.Random(SEED + 200)
    whitespace_queries = set(ws_rng.sample(range(NUM_QUERIES), 3))

    for q in range(NUM_QUERIES):
        n_relevant = random.randint(4, 10)
        relevant_docs = sorted(random.sample(all_doc_ids, n_relevant))
        qrels = []
        for i, did in enumerate(relevant_docs):
            rel = random.choices([1, 2, 3], weights=[50, 30, 20])[0]
            doc_id_out = did
            # Data issue: add trailing whitespace to 2 IDs in 3 queries
            if q in whitespace_queries and i < 2:
                doc_id_out = did + " "
            qrels.append({"id": doc_id_out, "label": rel})
        queries.append({
            "query_id": f"q_{q:03d}",
            "query_content": (
                f"Find documents about topic_{q} satisfying constraints on "
                f"aspect_{random.randint(0, 5)} and aspect_{random.randint(6, 10)}"
            ),
            "qrels": qrels,
        })

    with open(os.path.join(DEPLOY_DIR, "data", "qrels.jsonl"), "w") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")

    # === Four passage-level retrieval runs ===
    configs = [
        {"boost": 0.50, "noise_std": 0.03},
        {"boost": 0.35, "noise_std": 0.05},
        {"boost": 0.18, "noise_std": 0.07},
        {"boost": 0.06, "noise_std": 0.10},
    ]
    all_chunks = [(c["document_id"], c["parent_id"]) for c in corpus]

    for r in range(NUM_RUNS):
        run_rng = random.Random(SEED + (r + 1) * 7919)
        cfg = configs[r]
        run_data = []
        for qi, query in enumerate(queries):
            rel_map = {qr["id"].strip(): qr["label"] for qr in query["qrels"]}
            sampled = run_rng.sample(
                all_chunks, min(PASSAGES_PER_QUERY, len(all_chunks))
            )
            items = []
            for cid, pid in sampled:
                actual_parent = pid if pid else cid.split(":")[0]
                rel = rel_map.get(actual_parent, 0)
                base = run_rng.uniform(0.10, 0.35)
                boost = (rel / 3.0) * cfg["boost"]
                noise = run_rng.gauss(0, cfg["noise_std"])
                score = max(0.001, round(base + boost + noise, 6))
                items.append({"id": cid, "score": score})

            # Data issue: add duplicate entries to run_2 for first 5 queries
            if r == 2 and qi < 5:
                for dup_idx in range(min(3, len(items))):
                    dup = dict(items[dup_idx])
                    dup["score"] = round(dup["score"] * 0.7, 6)
                    items.append(dup)

            items.sort(key=lambda x: x["score"], reverse=True)
            run_data.append({"query": {"id": query["query_id"]}, "items": items})

        path = os.path.join(DEPLOY_DIR, "data", "runs", f"run_{r}.jsonl")
        with open(path, "w") as f:
            for rd in run_data:
                f.write(json.dumps(rd) + "\n")

    # === Metadata ===
    with open(os.path.join(DEPLOY_DIR, "data", "metadata.json"), "w") as f:
        json.dump({
            "num_documents": NUM_DOCS,
            "num_passages": len(corpus),
            "num_queries": NUM_QUERIES,
            "num_runs": NUM_RUNS,
            "run_names": [f"run_{r}" for r in range(NUM_RUNS)],
            "relevance_scale": "0-3 graded",
            "note": "Passages linked to parent documents via parent_id. "
                    "Qrels are document-level. Runs are passage-level.",
        }, f, indent=2)

    # === Output Schema ===
    with open(os.path.join(DEPLOY_DIR, "output_schema.json"), "w") as f:
        json.dump({
            "per_run_metrics": {
                f"run_{r}": {
                    "ndcg@10": "<float>",
                    "recall@100": "<float>",
                }
                for r in range(NUM_RUNS)
            },
            "significance_matrix": {
                f"run_{i}_vs_run_{j}": {
                    "p_value": "<float>",
                    "significant": "<bool>",
                }
                for i in range(NUM_RUNS)
                for j in range(i + 1, NUM_RUNS)
            },
            "ranking": ["<run names sorted by ndcg@10 descending>"],
        }, f, indent=2)

    print(f"Generated {len(corpus)} passages, {NUM_DOCS} docs, "
          f"{NUM_QUERIES} queries, {NUM_RUNS} runs")


if __name__ == "__main__":
    main()
