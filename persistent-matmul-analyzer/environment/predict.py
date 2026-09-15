#!/usr/bin/env python3

"""Generate GPU performance predictions from profiling database."""
import json
import sys

sys.path.insert(0, '/app')
from modules import generate_results

results = generate_results('/app/profiling.db')

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
