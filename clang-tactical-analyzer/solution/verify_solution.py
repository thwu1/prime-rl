#!/usr/bin/env python3
"""Spot-check verification for the CLang analyzer solution."""

import subprocess
import json
import sys


def run(scenario):
    r = subprocess.run(
        ["python3", "/app/clang_analyzer.py", f"/app/scenarios/{scenario}"],
        capture_output=True, text=True, timeout=60, cwd="/app"
    )
    if r.returncode != 0:
        print(f"Analyzer failed on {scenario}:")
        print(f"  stdout: {r.stdout[:500]}")
        print(f"  stderr: {r.stderr[:500]}")
        sys.exit(1)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON from {scenario}: {r.stdout[:500]}")
        sys.exit(1)


def check(name, condition, actual=None):
    if not condition:
        msg = f"FAIL: {name}"
        if actual is not None:
            msg += f" (got: {actual})"
        print(msg)
        sys.exit(1)


# Scenario 1
d = run("scenario_1.clang")
check("S1.active", d["active_rules"] == ["Rule_A", "Rule_B"], d["active_rules"])
check("S1.conds", d["defined_conditions"] == ["InOurHalf"], d["defined_conditions"])
check("S1.conflicts", d["conflicts"] == [], d["conflicts"])

# Scenario 2
d = run("scenario_2.clang")
check("S2.active", sorted(d["active_rules"]) == ["Outer_X", "Outer_Y"], d["active_rules"])
check("S2.expanded_x", d["expanded_rules"]["Outer_X"]["num_clauses"] == 2,
      d["expanded_rules"].get("Outer_X"))
check("S2.expanded_y", d["expanded_rules"]["Outer_Y"]["num_clauses"] == 2,
      d["expanded_rules"].get("Outer_Y"))

# Scenario 3
d = run("scenario_3.clang")
check("S3.active", len(d["active_rules"]) == 7, d["active_rules"])
expected = [
    ["Hit1", "Hit2"], ["Hit1", "Hit3"], ["Hit1", "Hit6"], ["Hit1", "Hit7"],
    ["Hit2", "Hit3"], ["Hit2", "Hit6"], ["Hit2", "Hit7"],
    ["Hit3", "Hit6"], ["Hit3", "Hit7"],
    ["Hit4", "Hit6"],
    ["Hit5", "Hit6"], ["Hit5", "Hit7"],
]
check("S3.conflicts", sorted(d["conflicts"]) == sorted(expected), d["conflicts"])

# Scenario 4
d = run("scenario_4.clang")
check("S4.deleted", "Alpha" in d["deleted_entities"], d["deleted_entities"])
check("S4.active", sorted(d["active_rules"]) == ["Alpha_v2", "Gamma"], d["active_rules"])
gamma_deps = d["dependencies"].get("Gamma", [])
check("S4.deps_gamma", "OurBall" in gamma_deps, gamma_deps)
av2_deps = d["dependencies"].get("Alpha_v2", [])
check("S4.deps_alpha_v2", "OurBall" in av2_deps, av2_deps)
beta_deps = d["dependencies"].get("Beta", [])
check("S4.deps_beta", set(beta_deps) >= {"OppBall", "Wing_L"}, beta_deps)

# Scenario 5
d = run("scenario_5.clang")
check("S5.conflict", ["Atk_Final", "Atk_Hold"] in d["conflicts"], d["conflicts"])
check("S5.no_cross", not any(
    any(r.startswith("Def_") for r in p) and any(r.startswith("Atk_") for r in p)
    for p in d["conflicts"]
), d["conflicts"])
af_deps = d["dependencies"].get("Atk_Final", [])
check("S5.deps_af", set(af_deps) >= {"OurBall", "BallInOppThird", "GoShoot"}, af_deps)

print("All spot-checks passed.")
