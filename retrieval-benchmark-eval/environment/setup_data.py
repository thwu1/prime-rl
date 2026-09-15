"""Generate synthetic multi-task IR benchmark data in TREC format."""

import random
import os
import json

random.seed(42)

TASKS = [
    {"id": "sci_citation", "domain": "science",
     "instruction": "Retrieve papers cited by the given paper based on title and abstract.",
     "n_queries": 12, "n_docs": 200, "a_boost": 0.70, "b_boost": 0.50, "rel_density": 0.35},
    {"id": "sci_abstract", "domain": "science",
     "instruction": "Find papers with semantically relevant abstracts to the query.",
     "n_queries": 15, "n_docs": 250, "a_boost": 0.65, "b_boost": 0.55, "rel_density": 0.40},
    {"id": "web_qa", "domain": "web",
     "instruction": "Retrieve web documents that answer the question.",
     "n_queries": 18, "n_docs": 300, "a_boost": 0.75, "b_boost": 0.35, "rel_density": 0.30},
    {"id": "web_fact", "domain": "web",
     "instruction": "Find evidence supporting or refuting the claim.",
     "n_queries": 10, "n_docs": 150, "a_boost": 0.12, "b_boost": 0.08, "rel_density": 0.20},
    {"id": "med_trial", "domain": "medical",
     "instruction": "Match patient descriptions to eligible clinical trials.",
     "n_queries": 14, "n_docs": 180, "a_boost": 0.18, "b_boost": 0.12, "rel_density": 0.25},
    {"id": "med_lit", "domain": "medical",
     "instruction": "Retrieve medical literature for the clinical question.",
     "n_queries": 16, "n_docs": 220, "a_boost": 0.60, "b_boost": 0.40, "rel_density": 0.35},
]

base_dir = "/opt/benchmark"
task_meta = {}

for t in TASKS:
    tid = t["id"]
    tdir = os.path.join(base_dir, "tasks", tid)
    os.makedirs(tdir, exist_ok=True)

    task_meta[tid] = {"domain": t["domain"], "instruction": t["instruction"]}

    doc_ids = [f"d{i:04d}" for i in range(t["n_docs"])]
    query_ids = [f"q{i:03d}" for i in range(t["n_queries"])]

    qrels = {}  # (qid, did) -> rel

    for qi, qid in enumerate(query_ids):
        if qi == 0:
            # Edge case: query with NO relevant documents
            n_judged = random.randint(4, 8)
            for did in random.sample(doc_ids, n_judged):
                qrels[(qid, did)] = 0
        elif qi == 1:
            # Edge case: query with only marginally relevant docs (rel=1)
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

    # Write qrels in TREC format
    with open(os.path.join(tdir, "qrels.tsv"), "w") as f:
        for (qid, did) in sorted(qrels.keys()):
            f.write(f"{qid}\t0\t{did}\t{qrels[(qid, did)]}\n")

    # Generate system runs
    for sys_label, boost in [("a", t["a_boost"]), ("b", t["b_boost"])]:
        run_path = os.path.join(tdir, f"run_{sys_label}.tsv")
        with open(run_path, "w") as f:
            for qid in query_ids:
                rel_docs = {did for (q, did), r in qrels.items() if q == qid and r > 0}
                scored = []
                for did in doc_ids:
                    if did in rel_docs and random.random() < boost:
                        score = random.uniform(0.5, 1.0)
                    else:
                        score = random.uniform(0.0, 0.5)
                    scored.append((did, score))
                scored.sort(key=lambda x: (-x[1], x[0]))
                for rank, (did, score) in enumerate(scored[:100], 1):
                    f.write(f"{qid}\tQ0\t{did}\t{rank}\t{score:.6f}\tsystem_{sys_label}\n")

with open(os.path.join(base_dir, "tasks.json"), "w") as f:
    json.dump(task_meta, f, indent=2)

print("Benchmark data generated successfully.")
