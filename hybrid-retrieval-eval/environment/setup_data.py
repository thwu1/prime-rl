#!/usr/bin/env python3
"""Download BRIGHT pony dataset from HuggingFace and save as JSON.

IMPORTANT: Saves queries WITHOUT gold_ids (relevance labels). Ground truth
is downloaded separately at verification time only.
"""
import json
import os
from huggingface_hub import hf_hub_download
import pandas as pd

os.makedirs('/app/data', exist_ok=True)

# Download examples (queries only -- no relevance labels)
print("Downloading pony examples...")
path = hf_hub_download(
    repo_id="xlangai/BRIGHT",
    filename="examples/pony-00000-of-00001.parquet",
    repo_type="dataset"
)
df = pd.read_parquet(path)
examples = []
for _, row in df.iterrows():
    excluded = row['excluded_ids']
    ex = {
        'query': str(row['query']),
        'id': str(row['id']),
        'excluded_ids': [str(x) for x in excluded] if excluded is not None else [],
    }
    examples.append(ex)

with open('/app/data/examples.json', 'w') as f:
    json.dump(examples, f, indent=2)
print(f"Saved {len(examples)} examples (queries only, no relevance labels)")

# Download documents
print("Downloading pony documents...")
path = hf_hub_download(
    repo_id="xlangai/BRIGHT",
    filename="documents/pony-00000-of-00001.parquet",
    repo_type="dataset"
)
df = pd.read_parquet(path)
docs = []
for _, row in df.iterrows():
    docs.append({
        'id': str(row['id']),
        'content': str(row['content']),
    })

with open('/app/data/documents.json', 'w') as f:
    json.dump(docs, f, indent=2)
print(f"Saved {len(docs)} documents")
