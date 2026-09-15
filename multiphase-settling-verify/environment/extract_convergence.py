#!/usr/bin/env python3
"""Extract MMS convergence data from results.json to TSV for gnuplot."""
import json
import sys

try:
    with open("/app/results.json") as f:
        data = json.load(f)
except FileNotFoundError:
    print("Error: results.json not found. Run mflow_verify.py first.",
          file=sys.stderr)
    sys.exit(1)

norms = data["mms"]["l2_norms"]
for k in sorted(norms, key=int):
    print(f"{k}\t{norms[k]}")
