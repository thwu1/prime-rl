#!/usr/bin/env python3
"""Generate mutation analysis report by computationally testing each cataloged mutation.

Reads the mutation catalog, checks for pragma annotations (equivalent mutations),
and applies each non-equivalent mutation to verify it is killed by the test suite.
"""

import json
import os
import shutil
import subprocess
import tempfile

APP_DIR = "/app"

# Concrete code changes for each cataloged mutation
MUTATION_CODE = {
    "M01": {
        "file": "intervallib/intervals.py",
        "original": "    return a[0] < b[1] and b[0] < a[1]",
        "mutated": "    return a[0] <= b[1] and b[0] < a[1]",
    },
    "M02": {
        "file": "intervallib/intervals.py",
        "original": "    return a[0] < b[1] and b[0] < a[1]",
        "mutated": "    return a[0] < b[1] and b[0] <= a[1]",
    },
    "M03": {
        "file": "intervallib/intervals.py",
        "original": "        if start <= result[-1][1]:",
        "mutated": "        if start < result[-1][1]:",
    },
    "M04": {
        "file": "intervallib/intervals.py",
        "original": "        if start > current:",
        "mutated": "        if start >= current:",
    },
    "M05": {
        "file": "intervallib/intervals.py",
        "original": "    if current < hi:",
        "mutated": "    if current <= hi:",
    },
    "M06": {
        "file": "intervallib/intervals.py",
        "original": "            total += ce - cs",
        "mutated": "            total += ce + cs",
    },
    "M07": {
        "file": "intervallib/intervals.py",
        "original": "    return total / (hi - lo)",
        "mutated": "    return total / (hi + lo)",
    },
    "M08": {
        "file": "intervallib/scheduling.py",
        "original": "            if indexed[mid][1][1] <= target_start:",
        "mutated": "            if indexed[mid][1][1] < target_start:",
    },
    "M09": {
        "file": "intervallib/scheduling.py",
        "original": "        time += proc_time",
        "mutated": "        time = proc_time",
    },
    "M10": {
        "file": "intervallib/scheduling.py",
        "original": "            if es > earliest_start[v]:",
        "mutated": "            if es >= earliest_start[v]:",
    },
    "M11": {
        "file": "intervallib/solver.py",
        "original": "            if dp[1] > ds[1]:",
        "mutated": "            if dp[1] >= ds[1]:",
    },
    "M12": {
        "file": "intervallib/solver.py",
        "original": "            if dp[0] >= dp[1] or ds[0] >= ds[1]:",
        "mutated": "            if dp[0] > dp[1] or ds[0] >= ds[1]:",
    },
    "M13": {
        "file": "intervallib/solver.py",
        "original": "    while t < time_end:",
        "mutated": "    while t <= time_end:",
    },
    "M14": {
        "file": "intervallib/solver.py",
        "original": "        if load > capacity:",
        "mutated": "        if load >= capacity:",
    },
    "M15": {
        "file": "intervallib/solver.py",
        "original": "        while (len(active) >= resource_capacity or not ready) and active:",
        "mutated": "        while (len(active) > resource_capacity or not ready) and active:",
    },
}

# Read the mutation catalog
with open(os.path.join(APP_DIR, "mutations.json")) as f:
    catalog = json.load(f)

killed = 0
survived = 0
equivalent = 0

for mutation in catalog["mutations"]:
    mid = mutation["id"]
    mcode = MUTATION_CODE[mid]
    filepath = os.path.join(APP_DIR, mcode["file"])

    with open(filepath) as f:
        content = f.read()

    # Check if the line has pragma annotation (equivalent mutation)
    original_stripped = mcode["original"].strip()
    is_equivalent = any(
        original_stripped in line and "pragma: no mutate" in line
        for line in content.splitlines()
    )

    if is_equivalent:
        equivalent += 1
        print(f"{mid}: equivalent (pragma annotated)")
        continue

    # Apply mutation to a temporary copy and run tests to verify kill
    with tempfile.TemporaryDirectory() as tmp:
        app_copy = os.path.join(tmp, "app")
        shutil.copytree(
            APP_DIR,
            app_copy,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".mutmut-cache", "mutants", ".git"
            ),
        )

        fp = os.path.join(app_copy, mcode["file"])
        with open(fp) as f:
            src = f.read()

        if mcode["original"] not in src:
            print(f"{mid}: WARNING - original string not found after pragma, skipping")
            survived += 1
            continue

        modified = src.replace(mcode["original"], mcode["mutated"], 1)
        with open(fp, "w") as f:
            f.write(modified)

        result = subprocess.run(
            ["python3", "-m", "pytest", os.path.join(app_copy, "tests"), "-x", "-q", "--tb=no"],
            capture_output=True,
            text=True,
            cwd=app_copy,
            env={**os.environ, "PYTHONPATH": app_copy, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=60,
        )

        if result.returncode != 0:
            killed += 1
            print(f"{mid}: killed")
        else:
            survived += 1
            print(f"{mid}: SURVIVED")

total = len(catalog["mutations"])
killable = total - equivalent
score = killed / killable if killable > 0 else 0.0

report = {
    "total_mutants": total,
    "killed": killed,
    "survived": survived,
    "equivalent": equivalent,
    "mutation_score": round(score, 4),
}

with open(os.path.join(APP_DIR, "mutation_analysis.json"), "w") as f:
    json.dump(report, f, indent=2)

print(f"\nFinal report: {json.dumps(report, indent=2)}")
