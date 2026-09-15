#!/usr/bin/env python3
"""Apply targeted fixes to the CSS cascade engine and implement unset keyword.

Identifies regression commits via git log, fixes all 6 bugs (including
interacting pairs), implements the unset keyword, and writes a conformance
report with commit hashes and fix group analysis.

"""

import json
import subprocess
import sys
import os

os.chdir("/app")


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd="/app", **kwargs
    )


# === Step 1: Identify regression commits from git history ===

result = run(["git", "log", "--oneline", "--reverse"])
regression_commits = {}

for line in result.stdout.strip().split("\n"):
    parts = line.split(" ", 1)
    if len(parts) < 2:
        continue
    short_hash, msg = parts
    msg_lower = msg.lower()

    # Get full hash for this commit
    full_hash_result = run(["git", "rev-parse", short_hash])
    full_hash = full_hash_result.stdout.strip()

    # Check what files this commit changed
    diff_result = run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", full_hash]
    )
    changed = diff_result.stdout.strip()

    if "cascade origin" in msg_lower and "engine/cascade.py" in changed:
        regression_commits["cascade_priority"] = full_hash
    elif "cascade sort" in msg_lower and "engine/cascade.py" in changed:
        regression_commits["cascade_specificity"] = full_hash
    elif "specificity" in msg_lower and "engine/specificity.py" in changed:
        regression_commits["specificity"] = full_hash
    elif ("combinator" in msg_lower or "traversal" in msg_lower) and "engine/matcher.py" in changed:
        regression_commits["matcher"] = full_hash
    elif "shorthand" in msg_lower and "engine/shorthand.py" in changed:
        regression_commits["shorthand"] = full_hash
    elif "keyword" in msg_lower and "engine/compute.py" in changed:
        regression_commits["compute"] = full_hash

print(f"Found {len(regression_commits)} regression commits:")
for k, v in regression_commits.items():
    print(f"  {k}: {v[:12]}")


# === Step 2: Fix all 6 bugs ===

def patch_file(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        print(f"WARNING: patch target not found in {path}", file=sys.stderr)
        return False
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    return True


# Fix 1: Cascade priority - swap author/user !important back to correct
patch_file(
    "engine/cascade.py",
    '        if origin == "author":\n            return 5\n        if origin == "user":\n            return 4',
    '        if origin == "user":\n            return 5\n        if origin == "author":\n            return 4',
)
print("Fixed: cascade.py - !important origin priority ordering")

# Fix 2: Cascade sort key - add specificity back
patch_file(
    "engine/cascade.py",
    'return (pri, d["source_order"])',
    'return (pri, d["specificity"], d["source_order"])',
)
print("Fixed: cascade.py - specificity restored in cascade sort key")

# Fix 3: Specificity - add attribute counting back
with open("engine/specificity.py") as f:
    content = f.read()
content = content.replace(
    '        b += len(compound.get("classes", []))\n        t = compound.get',
    '        b += len(compound.get("classes", []))\n        b += len(compound.get("attributes", {}))\n        t = compound.get',
)
with open("engine/specificity.py", "w") as f:
    f.write(content)
print("Fixed: specificity.py - attribute selector counting in b-column")

# Fix 4: Child combinator - fix grandparent to parent
patch_file(
    "engine/matcher.py",
    '            parent_id = dom_index[current_id]["parent_id"]\n'
    '            if parent_id is None:\n'
    '                return False\n'
    '            gp_id = dom_index[parent_id]["parent_id"]\n'
    '            if gp_id is None or not _match_compound(compound, dom_index[gp_id]):\n'
    '                return False\n'
    '            current_id = gp_id',
    '            parent_id = dom_index[current_id]["parent_id"]\n'
    '            if parent_id is None or not _match_compound(compound, dom_index[parent_id]):\n'
    '                return False\n'
    '            current_id = parent_id',
)
print("Fixed: matcher.py - child combinator checks parent not grandparent")

# Fix 5: Shorthand 3-value left
patch_file(
    "engine/shorthand.py",
    'f"{prefix}-bottom": parts[2],\n                f"{prefix}-left": parts[2],',
    'f"{prefix}-bottom": parts[2],\n                f"{prefix}-left": parts[1],',
)
print("Fixed: shorthand.py - 3-value shorthand left mirrors right")

# Fix 6: Initial keyword resolution
patch_file(
    "engine/compute.py",
    '                if val == "inherit":\n'
    '                    final[prop] = parent_styles.get(prop, meta["initial"])\n'
    '                else:\n'
    '                    final[prop] = val',
    '                if val == "inherit":\n'
    '                    final[prop] = parent_styles.get(prop, meta["initial"])\n'
    '                elif val == "initial":\n'
    '                    final[prop] = meta["initial"]\n'
    '                else:\n'
    '                    final[prop] = val',
)
print("Fixed: compute.py - initial keyword resolution")


# === Step 3: Implement unset keyword ===

patch_file(
    "engine/compute.py",
    '                elif val == "initial":\n'
    '                    final[prop] = meta["initial"]\n'
    '                else:\n'
    '                    final[prop] = val',
    '                elif val == "initial":\n'
    '                    final[prop] = meta["initial"]\n'
    '                elif val == "unset":\n'
    '                    if meta["inherited"]:\n'
    '                        final[prop] = parent_styles.get(prop, meta["initial"])\n'
    '                    else:\n'
    '                        final[prop] = meta["initial"]\n'
    '                else:\n'
    '                    final[prop] = val',
)
print("Implemented: compute.py - unset keyword support")


# === Step 4: Write conformance report ===

report = {
    "issues_found": [
        {
            "module": "cascade.py",
            "description": (
                "User !important and author !important priorities are inverted. "
                "Per CSS spec section 1.3, user !important (priority 5) must "
                "override author !important (priority 4), but they were swapped."
            ),
            "regression_commit": regression_commits.get("cascade_priority", "unknown"),
        },
        {
            "module": "cascade.py",
            "description": (
                "Specificity comparison removed from cascade sort key. The cascade "
                "must use (priority, specificity, source_order) to resolve ties, but "
                "specificity was dropped, making source_order the sole tiebreaker "
                "within the same priority level."
            ),
            "regression_commit": regression_commits.get("cascade_specificity", "unknown"),
        },
        {
            "module": "specificity.py",
            "description": (
                "Attribute selectors ([attr], [attr=val]) not counted in the "
                "specificity b-column. They should be counted alongside class "
                "selectors per CSS spec section 2.1."
            ),
            "regression_commit": regression_commits.get("specificity", "unknown"),
        },
        {
            "module": "matcher.py",
            "description": (
                "Child combinator (>) traverses to grandparent instead of parent. "
                "The > combinator must match only direct parent-child relationships "
                "per CSS spec section 3.2."
            ),
            "regression_commit": regression_commits.get("matcher", "unknown"),
        },
        {
            "module": "shorthand.py",
            "description": (
                "Three-value shorthand expansion maps left to the bottom value "
                "(parts[2]) instead of the right value (parts[1]). CSS spec "
                "section 4.1: omitted left mirrors right."
            ),
            "regression_commit": regression_commits.get("shorthand", "unknown"),
        },
        {
            "module": "compute.py",
            "description": (
                "The 'initial' CSS-wide keyword is not resolved. When a property "
                "value is 'initial', it should be replaced with the property's "
                "defined initial value from metadata per CSS spec section 5.1."
            ),
            "regression_commit": regression_commits.get("compute", "unknown"),
        },
    ],
    "fix_groups": [
        {
            "modules": ["cascade.py", "specificity.py"],
            "rationale": (
                "The cascade sort key must include specificity for specificity "
                "calculations to affect cascade results. Fixing attribute selector "
                "counting in specificity.py without restoring specificity to the "
                "cascade sort key in cascade.py produces no visible change in "
                "output — source order still decides, masking the specificity fix."
            ),
        },
        {
            "modules": ["cascade.py", "matcher.py"],
            "rationale": (
                "The child combinator bug in matcher.py masks the cascade priority "
                "inversion in cascade.py. With a broken child combinator, author "
                "!important rules using child selectors don't match, so user "
                "!important wins by default. Fixing the combinator without fixing "
                "cascade priorities causes author !important to incorrectly beat "
                "user !important in scenarios where both rules match."
            ),
        },
    ],
    "keywords_implemented": ["unset"],
}

with open("conformance_report.json", "w") as f:
    json.dump(report, f, indent=2)

print("\nWritten: /app/conformance_report.json")

# === Step 5: Verify fix ===

result = run(["make", "diff"])
if result.returncode == 0:
    print("\nSUCCESS: Engine output matches expected output from v1.0")
else:
    print("\nWARNING: Engine output still differs from expected:")
    print(result.stdout)
