#!/usr/bin/env python3
"""
Generate structured JSON report from raw test results.
"""
import json


def main():
    with open("/app/raw_results.json") as f:
        raw = json.load(f)

    categories = {}
    discrepancies = []

    for r in raw:
        cat = r["category"]
        opt = r["opt_level"]

        if cat not in categories:
            categories[cat] = {
                "files": set(),
                "pass_O0": 0,
                "pass_O1": 0,
                "pass_O2": 0,
                "pass_O3": 0,
            }

        categories[cat]["files"].add(r["file"])

        if r.get("compile_ok", True) and r["exit_code"] == 0:
            opt_key = "pass_" + opt.replace("-", "")
            categories[cat][opt_key] += 1
        else:
            discrepancies.append({
                "file": r["file"],
                "category": cat,
                "opt_level": opt,
                "exit_code": r["exit_code"],
            })

    # Convert file sets to counts
    for cat in categories:
        categories[cat]["count"] = len(categories[cat]["files"])
        del categories[cat]["files"]

    total = sum(c["count"] for c in categories.values())

    report = {
        "total_tests": total,
        "categories": categories,
        "discrepancies": discrepancies,
    }

    with open("/app/results.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report: {total} tests across {len(categories)} categories, "
          f"{len(discrepancies)} discrepancies")
    for cat, data in sorted(categories.items()):
        print(f"  {cat}: {data['count']} tests, "
              f"O0={data['pass_O0']} O1={data['pass_O1']} "
              f"O2={data['pass_O2']} O3={data['pass_O3']}")


if __name__ == "__main__":
    main()
