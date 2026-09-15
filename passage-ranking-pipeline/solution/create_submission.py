#!/usr/bin/env python3
"""Create MS MARCO submission package: metadata JSON + bz2-compressed run."""

import json
import bz2
import os

os.makedirs("/app/output/submission", exist_ok=True)

# Create metadata
metadata = {
    "team": "BM25 Baseline",
    "model_description": "Standard Okapi BM25 reranking with k1=1.2 b=0.75 over top-100 candidates",
    "paper": "",
    "code": "",
    "type": "reranking"
}

with open("/app/output/submission/metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

# bz2-compress the run file
with open("/app/output/run.tsv", "rb") as f:
    run_data = f.read()

with bz2.open("/app/output/submission/dev.txt.bz2", "wb") as f:
    f.write(run_data)

print("Submission package created at /app/output/submission/")
