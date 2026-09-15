#!/usr/bin/env python3
"""Generate synthetic multi-task IR benchmark data with embedded format issues."""
import random
import os
import json

random.seed(42)
delim_rng = random.Random(54321)

TASKS = [
    {"id": "bio_entity", "domain": "biomedical", "n_queries": 12, "n_docs": 180,
     "boosts": {"alpha": 0.70, "beta": 0.55, "gamma": 0.60}, "rel_density": 0.35},
    {"id": "bio_relation", "domain": "biomedical", "n_queries": 14, "n_docs": 200,
     "boosts": {"alpha": 0.65, "beta": 0.45, "gamma": 0.50}, "rel_density": 0.30},
    {"id": "web_qa", "domain": "web", "n_queries": 18, "n_docs": 250,
     "boosts": {"alpha": 0.75, "beta": 0.60, "gamma": 0.35}, "rel_density": 0.40},
    {"id": "web_passage", "domain": "web", "n_queries": 10, "n_docs": 150,
     "boosts": {"alpha": 0.15, "beta": 0.10, "gamma": 0.20}, "rel_density": 0.25},
    {"id": "legal_case", "domain": "legal", "n_queries": 16, "n_docs": 220,
     "boosts": {"alpha": 0.55, "beta": 0.50, "gamma": 0.45}, "rel_density": 0.30},
    {"id": "legal_statute", "domain": "legal", "n_queries": 11, "n_docs": 160,
     "boosts": {"alpha": 0.60, "beta": 0.40, "gamma": 0.55}, "rel_density": 0.35},
]

SYSTEMS = ["alpha", "beta", "gamma"]

base_dir = "/app/data/benchmark"
task_meta = {}

for t in TASKS:
    tid = t["id"]
    tdir = os.path.join(base_dir, "tasks", tid)
    os.makedirs(tdir, exist_ok=True)
    task_meta[tid] = {"domain": t["domain"]}
    doc_ids = [f"d{i:04d}" for i in range(t["n_docs"])]
    query_ids = [f"q{i:03d}" for i in range(t["n_queries"])]

    qrels = {}
    for qi, qid in enumerate(query_ids):
        if qi == 0:
            n_judged = random.randint(4, 8)
            for did in random.sample(doc_ids, n_judged):
                qrels[(qid, did)] = 0
        elif qi == 1:
            n_judged = random.randint(6, 12)
            for did in random.sample(doc_ids, n_judged):
                if random.random() < t["rel_density"] * 0.8:
                    qrels[(qid, did)] = 1
                else:
                    qrels[(qid, did)] = 0
        else:
            n_judged = random.randint(8, 25)
            for did in random.sample(doc_ids, min(n_judged, t["n_docs"])):
                if random.random() < t["rel_density"]:
                    rel = random.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
                else:
                    rel = 0
                qrels[(qid, did)] = rel

    with open(os.path.join(tdir, "qrels.tsv"), "w") as f:
        for (qid, did) in sorted(qrels.keys()):
            # Data bug: ~30% of legal_case qrel lines use space instead of tab
            if tid == "legal_case" and delim_rng.random() < 0.30:
                f.write(f"{qid} 0 {did} {qrels[(qid, did)]}\n")
            else:
                f.write(f"{qid}\t0\t{did}\t{qrels[(qid, did)]}\n")

    for sys_name in SYSTEMS:
        boost = t["boosts"][sys_name]
        # Data bug: web_passage/run_gamma uses spaces instead of tabs
        use_spaces = (tid == "web_passage" and sys_name == "gamma")
        delim = " " if use_spaces else "\t"

        with open(os.path.join(tdir, f"run_{sys_name}.tsv"), "w") as f:
            for qid in query_ids:
                rel_docs = {did for (q, did), r in qrels.items()
                            if q == qid and r > 0}
                scored = []
                for did in doc_ids:
                    if did in rel_docs and random.random() < boost:
                        score = random.uniform(0.5, 1.0)
                    else:
                        score = random.uniform(0.0, 0.5)
                    scored.append((did, score))
                scored.sort(key=lambda x: (-x[1], x[0]))
                for rank, (did, score) in enumerate(scored[:100], 1):
                    f.write(
                        f"{qid}{delim}Q0{delim}{did}{delim}{rank}"
                        f"{delim}{score:.6f}{delim}system_{sys_name}\n"
                    )

with open(os.path.join(base_dir, "tasks.json"), "w") as f:
    json.dump(task_meta, f, indent=2)

print("Benchmark data generated successfully.")
