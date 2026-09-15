#!/usr/bin/env python3
"""Run the DRAT checker on all instances and collect results."""

import json
import os
import subprocess
import sys

results = {}
instances_dir = "/app/instances"

if not os.path.isdir(instances_dir):
    print(f"ERROR: {instances_dir} does not exist", file=sys.stderr)
    sys.exit(1)

entries = sorted(os.listdir(instances_dir))
print(f"Found {len(entries)} instance directories", file=sys.stderr)

for name in entries:
    instance_path = os.path.join(instances_dir, name)
    if not os.path.isdir(instance_path):
        continue
    formula = os.path.join(instance_path, "formula.cnf")
    proof = os.path.join(instance_path, "proof.drat")
    if not os.path.isfile(formula) or not os.path.isfile(proof):
        print(f"WARNING: Skipping {name} - missing files", file=sys.stderr)
        continue
    try:
        proc = subprocess.run(
            ["python3", "/app/checker.py", formula, proof],
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            print(
                f"WARNING: checker failed on {name}: {proc.stderr[:300]}",
                file=sys.stderr,
            )
            continue
        output = proc.stdout.strip().split("\n")[-1]
        results[name] = json.loads(output)
        print(f"  {name}: {results[name]}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR processing {name}: {e}", file=sys.stderr)

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Results written to /app/results.json ({len(results)} instances)")
