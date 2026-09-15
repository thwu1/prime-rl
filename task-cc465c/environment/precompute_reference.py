"""Precompute reference BPE merges for test verification."""
import json
import sys
import time

sys.path.insert(0, "/app")
from reference import NaiveBPETrainer

trainer = NaiveBPETrainer()

# Medium corpus: 500 merges
with open("/app/corpus_medium.txt", "r") as f:
    text = f.read()
print(f"Medium corpus: {len(text)} chars")
start = time.time()
merges = trainer.train(text, 500)
elapsed = time.time() - start
print(f"Medium: {len(merges)} merges in {elapsed:.1f}s")
merges_json = {f"{a},{b}": v for (a, b), v in merges.items()}
with open("/app/reference_merges_medium.json", "w") as f:
    json.dump(merges_json, f)

# Large corpus: 2000 merges
with open("/app/corpus_large.txt", "r") as f:
    text = f.read()
print(f"Large corpus: {len(text)} chars")
start = time.time()
merges = trainer.train(text, 2000)
elapsed = time.time() - start
print(f"Large: {len(merges)} merges in {elapsed:.1f}s")
merges_json = {f"{a},{b}": v for (a, b), v in merges.items()}
with open("/app/reference_merges_large.json", "w") as f:
    json.dump(merges_json, f)
