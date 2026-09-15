#!/usr/bin/env python3
"""Prepare BRIGHT Pony task data from downloaded parquet files with per-instance DNA.

Reads parquet files from /tmp/bright/ and produces:
- /app/data/documents.json  (corpus with DNA-remapped doc IDs)
- /app/data/queries.json    (queries with GPT-4 reasoning, DNA-remapped excluded_ids)
- /app/.bright_eval/dna.txt  (per-instance DNA seed)
- /app/.bright_eval/ground_truth.bin  (encoded ground truth with DNA-remapped IDs)
"""
import base64
import json
import os
import random
import sys
import zlib

import pyarrow.parquet as pq

EVAL_DIR = '/app/.bright_eval'

os.makedirs('/app/data', exist_ok=True)
os.makedirs(EVAL_DIR, exist_ok=True)

# ---- Generate per-instance DNA ----
dna_seed = int.from_bytes(os.urandom(4), 'big')
dna_hex = format(dna_seed, '08x')
with open(os.path.join(EVAL_DIR, 'dna.txt'), 'w') as f:
    f.write(dna_hex)
print(f"DNA seed: {dna_hex}")

rng = random.Random(dna_seed)

# Verify downloaded files
for fname in ['docs.parquet', 'examples.parquet', 'reasoning.parquet']:
    fpath = f'/tmp/bright/{fname}'
    if not os.path.isfile(fpath):
        print(f"ERROR: {fpath} not found", file=sys.stderr)
        sys.exit(1)
    size = os.path.getsize(fpath)
    if size < 1000:
        print(f"ERROR: {fpath} is only {size} bytes (likely bad download)", file=sys.stderr)
        sys.exit(1)
    print(f"  {fname}: {size} bytes")

# ---- Load documents ----
docs_table = pq.read_table('/tmp/bright/docs.parquet')
doc_list = docs_table.to_pylist()

# Generate DNA-based document ID prefix and random suffix mapping
doc_prefix = dna_hex[:4]
# Create a random permutation suffix for extra uniqueness
suffix_pool = list(range(10000, 99999))
rng.shuffle(suffix_pool)

id_map = {}  # old_id -> new_id
for i, d in enumerate(doc_list):
    old_id = d["id"]
    new_id = f"{doc_prefix}_{suffix_pool[i]}_{old_id}"
    id_map[old_id] = new_id

documents = [{"id": id_map[d["id"]], "content": d["content"]} for d in doc_list]

# Shuffle document order so positional shortcuts don't work
rng.shuffle(documents)

with open('/app/data/documents.json', 'w') as f:
    json.dump(documents, f)
print(f"Saved {len(documents)} documents to /app/data/documents.json (with DNA prefix '{doc_prefix}')")

# ---- Queries with GPT-4 reasoning traces ----
reason_table = pq.read_table('/tmp/bright/reasoning.parquet')
reason_list = reason_table.to_pylist()
queries = []
for r in reason_list:
    excluded = r.get("excluded_ids") or []
    # Remap excluded_ids to DNA-prefixed IDs
    remapped_excluded = []
    for eid in excluded:
        if eid == "N/A":
            continue
        if eid in id_map:
            remapped_excluded.append(id_map[eid])
    queries.append({
        "id": r["id"],
        "query": r["query"],
        "reasoning": r.get("reasoning", ""),
        "excluded_ids": remapped_excluded,
    })

with open('/app/data/queries.json', 'w') as f:
    json.dump(queries, f)
print(f"Saved {len(queries)} queries to /app/data/queries.json")

# ---- Ground truth (hidden, encoded) ----
examples_table = pq.read_table('/tmp/bright/examples.parquet')
examples_list = examples_table.to_pylist()
ground_truth = {}
for e in examples_list:
    gold_ids = e.get("gold_ids") or []
    # Remap gold doc IDs to DNA-prefixed IDs
    ground_truth[e["id"]] = {id_map[gid]: 1 for gid in gold_ids if gid in id_map}

# Encode ground truth: zlib compress + base64 to prevent trivial reading
gt_json = json.dumps(ground_truth).encode('utf-8')
gt_compressed = zlib.compress(gt_json, level=9)
gt_encoded = base64.b64encode(gt_compressed)
with open(os.path.join(EVAL_DIR, 'ground_truth.bin'), 'wb') as f:
    f.write(gt_encoded)
print(f"Saved encoded ground truth for {len(ground_truth)} queries")

# Save the DNA-to-ID mapping for debugging (also encoded)
mapping_json = json.dumps(id_map).encode('utf-8')
mapping_compressed = zlib.compress(mapping_json, level=9)
mapping_encoded = base64.b64encode(mapping_compressed)
with open(os.path.join(EVAL_DIR, 'id_mapping.bin'), 'wb') as f:
    f.write(mapping_encoded)

# Sanity check: query IDs match ground truth IDs
query_ids = {q["id"] for q in queries}
gt_ids = set(ground_truth.keys())
assert query_ids == gt_ids, f"ID mismatch: queries-only={query_ids - gt_ids}, gt-only={gt_ids - query_ids}"
print("ID alignment verified.")
print(f"DNA generation complete. Instance ID: {dna_hex}")
