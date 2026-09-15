"""Combine EOF and Gregory regression results into a single output file."""
import json

with open('/tmp/pipeline_work/eof_results.json') as f:
    eof = json.load(f)
with open('/tmp/pipeline_work/gregory_results.json') as f:
    gregory = json.load(f)

results = {**eof, **gregory}

with open('/app/pipeline/results_original.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Results written to /app/pipeline/results_original.json")
