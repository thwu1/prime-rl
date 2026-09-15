#!/usr/bin/env python3

"""Cross-validate SAT and ILP solver results and produce report.json."""

import json
import sys


def main():
    try:
        with open('/app/sat_results.json') as f:
            sat = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading SAT results: {e}", file=sys.stderr)
        sat = {}

    try:
        with open('/app/ilp_results.json') as f:
            ilp = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading ILP results: {e}", file=sys.stderr)
        ilp = {}

    report = {}
    all_agree = True
    for name in sorted(set(sat) | set(ilp)):
        s = sat.get(name)
        i = ilp.get(name)
        report[name] = {"sat_crossings": s, "ilp_crossings": i}
        if s != i:
            all_agree = False
            print(f"MISMATCH: {name} SAT={s} ILP={i}")

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    if all_agree:
        print("Cross-validation passed: all instances agree between SAT and ILP.")
    else:
        print("WARNING: some instances have mismatched crossing counts!", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
