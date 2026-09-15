#!/usr/bin/env python3
"""Run all scenarios and compare results with expected values."""

import json
import os
import sys
from netfilter_sim import run_scenario, load_scenario


def compare_results(actual, expected):
    """Compare actual results with expected and return list of errors."""
    errors = []

    if "counters" in expected:
        for key, exp_val in expected["counters"].items():
            act_val = actual["counters"].get(key, 0)
            if act_val != exp_val:
                errors.append(
                    f"  counter {key}: expected {exp_val}, got {act_val}")

    for key in ["conntrack_entries", "total_dropped",
                "total_accepted", "conntrack_drops"]:
        if key in expected:
            if actual[key] != expected[key]:
                errors.append(
                    f"  {key}: expected {expected[key]}, got {actual[key]}")

    if "packet_results" in expected:
        act = actual["packet_results"]
        exp = expected["packet_results"]
        if act != exp:
            for i, (a, e) in enumerate(zip(act, exp)):
                if a != e:
                    errors.append(
                        f"  packet {i+1}: expected '{e}', got '{a}'")

    return errors


def main():
    scenario_dir = "/app/scenarios"
    files = sorted(f for f in os.listdir(scenario_dir)
                   if f.endswith(".json"))

    all_pass = True
    for fname in files:
        path = os.path.join(scenario_dir, fname)
        scenario = load_scenario(path)
        actual = run_scenario(scenario)
        expected = scenario.get("expected", {})

        errors = compare_results(actual, expected)
        name = scenario.get("name", fname)

        if errors:
            print(f"FAIL: {name} ({fname})")
            for e in errors:
                print(e)
            print()
            all_pass = False
        else:
            print(f"PASS: {name} ({fname})")

    print()
    if all_pass:
        print("All scenarios passed!")
    else:
        print("Some scenarios failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
