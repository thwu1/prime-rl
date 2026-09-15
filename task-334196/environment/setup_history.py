#!/usr/bin/env python3
"""Build git history with a correct initial commit and regression-introducing commits.

This script is run during Docker build to create a realistic git history.
The correct engine files are already in /app/engine/ (copied by Dockerfile).
This script commits them, generates expected output, then introduces bugs
one at a time with plausible commit messages.

"""

import json
import os
import subprocess
import sys

os.chdir("/app")


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def git(*args):
    run(["git"] + list(args))


# === Step 1: Initialize repo with correct engine ===
git("init")
git("config", "user.email", "dev@example.com")
git("config", "user.name", "Dev")
git("add", "-A")
git("commit", "-m", "Initial CSS cascade engine implementation")

# Generate expected output from correct engine
result = run(["python3", "run.py"])
with open(".expected_output.json", "w") as f:
    # Normalize: load and re-dump with sorted keys for stable comparison
    data = json.loads(result.stdout)
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")

git("add", ".expected_output.json")
git("commit", "-m", "Add expected output snapshot for regression testing")
git("tag", "v1.0")

# === Step 2: Introduce bugs one at a time ===


def patch_file(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        print(f"ERROR: patch target not found in {path}", file=sys.stderr)
        print(f"Looking for:\n{old!r}", file=sys.stderr)
        sys.exit(1)
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)


# --- Bug 1: Cascade priority swap (cascade.py) ---
patch_file(
    "engine/cascade.py",
    '        if origin == "user":\n            return 5\n        if origin == "author":\n            return 4',
    '        if origin == "author":\n            return 5\n        if origin == "user":\n            return 4',
)
git("add", "-A")
git("commit", "-m", "Optimize cascade origin comparison for readability")

# --- Bug 2: Remove specificity from cascade sort key (cascade.py) ---
patch_file(
    "engine/cascade.py",
    'return (pri, d["specificity"], d["source_order"])',
    'return (pri, d["source_order"])',
)
git("add", "-A")
git("commit", "-m", "Simplify cascade sort - remove redundant comparison key")

# --- Innocent commit: add comments to parser.py ---
patch_file(
    "engine/parser.py",
    '"""CSS selector parser.\n',
    '"""CSS selector parser.\n\n# Selector parsing supports: type, class, ID, attribute, compound,\n# descendant/child combinators, and comma-separated selector lists.\n',
)
git("add", "-A")
git("commit", "-m", "Add clarifying comments to selector parser")

# --- Bug 3: Remove attribute counting from specificity (specificity.py) ---
patch_file(
    "engine/specificity.py",
    '        b += len(compound.get("classes", []))\n        b += len(compound.get("attributes", {}))',
    '        b += len(compound.get("classes", []))',
)
git("add", "-A")
git("commit", "-m", "Refactor specificity calculation - streamline b-column")

# --- Bug 4: Child combinator checks grandparent (matcher.py) ---
patch_file(
    "engine/matcher.py",
    '            parent_id = dom_index[current_id]["parent_id"]\n'
    '            if parent_id is None or not _match_compound(compound, dom_index[parent_id]):\n'
    '                return False\n'
    '            current_id = parent_id',
    '            parent_id = dom_index[current_id]["parent_id"]\n'
    '            if parent_id is None:\n'
    '                return False\n'
    '            gp_id = dom_index[parent_id]["parent_id"]\n'
    '            if gp_id is None or not _match_compound(compound, dom_index[gp_id]):\n'
    '                return False\n'
    '            current_id = gp_id',
)
git("add", "-A")
git("commit", "-m", "Simplify child combinator traversal logic")

# --- Bug 5: Shorthand 3-value left = parts[2] (shorthand.py) ---
patch_file(
    "engine/shorthand.py",
    'f"{prefix}-bottom": parts[2],\n                f"{prefix}-left": parts[1],',
    'f"{prefix}-bottom": parts[2],\n                f"{prefix}-left": parts[2],',
)
git("add", "-A")
git("commit", "-m", "Clean up shorthand expansion edge cases")

# --- Bug 6: Remove initial keyword resolution (compute.py) ---
patch_file(
    "engine/compute.py",
    '                if val == "inherit":\n'
    '                    final[prop] = parent_styles.get(prop, meta["initial"])\n'
    '                elif val == "initial":\n'
    '                    final[prop] = meta["initial"]\n'
    '                else:\n'
    '                    final[prop] = val',
    '                if val == "inherit":\n'
    '                    final[prop] = parent_styles.get(prop, meta["initial"])\n'
    '                else:\n'
    '                    final[prop] = val',
)
git("add", "-A")
git("commit", "-m", "Streamline keyword resolution in compute pipeline")

print("Git history built: v1.0 (correct) + 7 commits (6 regressions + 1 innocent)")
print(f"Total commits: {run(['git', 'rev-list', '--count', 'HEAD']).stdout.strip()}")
