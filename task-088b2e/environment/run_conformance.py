#!/usr/bin/env python3
"""TTCN-3 Conformance Test Execution Entry Point

Loads test suite definitions and PICS profiles, runs the conformance
engine, and produces report files.

"""

import json
import os
import sys

VERDICT_ORDER = {"none": 0, "pass": 1, "inconc": 2, "fail": 3, "error": 4}
VERDICT_NAMES = {v: k for k, v in VERDICT_ORDER.items()}


def main():
    try:
        from engine import ConformanceEngine
    except ImportError:
        print("ERROR: /app/engine.py not found.", file=sys.stderr)
        print("Create it with a ConformanceEngine class that accepts a", file=sys.stderr)
        print("PICS config dict and exposes execute_suite(suite_def).", file=sys.stderr)
        sys.exit(1)

    suites_dir = "/app/suites"
    pics_dir = "/app/pics"

    suite_files = sorted(f for f in os.listdir(suites_dir) if f.endswith(".json"))
    pics_files = sorted(f for f in os.listdir(pics_dir) if f.endswith(".json"))

    for pics_file in pics_files:
        pics_path = os.path.join(pics_dir, pics_file)
        profile_name = os.path.splitext(pics_file)[0]

        with open(pics_path) as f:
            pics = json.load(f)

        engine = ConformanceEngine(pics)

        report = {"profile": profile_name, "suites": [], "overall_verdict": "none"}

        for sf in suite_files:
            suite_path = os.path.join(suites_dir, sf)
            with open(suite_path) as f:
                suite = json.load(f)

            suite_result = engine.execute_suite(suite)
            report["suites"].append(suite_result)

        max_v = 0
        for s in report["suites"]:
            max_v = max(max_v, VERDICT_ORDER.get(s["suite_verdict"], 0))
        report["overall_verdict"] = VERDICT_NAMES[max_v]

        report_path = f"/app/report_{profile_name}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"Report: {report_path}")
        print(f"  Profile: {profile_name}")
        print(f"  Overall verdict: {report['overall_verdict']}")
        for s in report["suites"]:
            print(f"  {s['suite_name']}: {s['selected']}/{s['total']} selected, "
                  f"verdict={s['suite_verdict']}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
