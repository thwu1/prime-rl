#!/usr/bin/env python3
"""Generate baseline run files and effectiveness targets."""

import json
import os
import subprocess

INDEX_DIR = "/app/index"
QUERIES = "/app/queries.tsv"
RUNS_DIR = "/app/runs"

os.makedirs(RUNS_DIR, exist_ok=True)

# Run A: BM25 with severely misconfigured parameters
# k1=0.1 means term frequency barely matters; b=0.9 means extreme length normalization
subprocess.run([
    "python3", "-m", "pyserini.search.lucene",
    "--index", INDEX_DIR, "--topics", QUERIES,
    "--output", os.path.join(RUNS_DIR, "run_A.txt"),
    "--bm25", "--k1", "0.1", "--b", "0.9",
    "--hits", "1000"
], check=True)

# Run B: BM25 with default parameters but missing queries 3, 7, 8
subprocess.run([
    "python3", "-m", "pyserini.search.lucene",
    "--index", INDEX_DIR, "--topics", QUERIES,
    "--output", "/tmp/run_B_full.txt",
    "--bm25",
    "--hits", "1000"
], check=True)

with open("/tmp/run_B_full.txt") as f:
    lines = f.readlines()
with open(os.path.join(RUNS_DIR, "run_B.txt"), "w") as f:
    for line in lines:
        qid = line.strip().split()[0]
        if qid not in ("3", "7", "8"):
            f.write(line)
os.remove("/tmp/run_B_full.txt")

# Run C: Query likelihood with Dirichlet smoothing (different retrieval model)
subprocess.run([
    "python3", "-m", "pyserini.search.lucene",
    "--index", INDEX_DIR, "--topics", QUERIES,
    "--output", os.path.join(RUNS_DIR, "run_C.txt"),
    "--qld",
    "--hits", "1000"
], check=True)

# Effectiveness targets
targets = {
    "map": 0.45,
    "ndcg_cut_10": 0.50,
    "recall_1000": 0.90
}
with open("/app/targets.json", "w") as f:
    json.dump(targets, f, indent=2)

print("Generated 3 baseline runs and targets.json")
