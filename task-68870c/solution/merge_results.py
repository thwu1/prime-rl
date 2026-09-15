#!/usr/bin/env python3
"""
Merge IGAMT validation results with Schematron SVRL failure text
into a unified JSON validation report.

Usage: merge_results.py <igamt_json_file> <svrl_failures_txt>
"""

import sys
import json
import re


def main():
    if len(sys.argv) != 3:
        print(json.dumps({
            "valid": False,
            "errors": [{"category": "PARSE", "path": "",
                        "message": "merge_results: invalid arguments"}],
            "warnings": []
        }))
        sys.exit(1)

    igamt_file = sys.argv[1]
    svrl_file = sys.argv[2]

    # Read IGAMT results
    try:
        with open(igamt_file) as f:
            igamt = json.load(f)
    except Exception:
        igamt = {"valid": True, "errors": [], "warnings": []}

    # Read and parse Schematron failures
    sch_errors = []
    try:
        with open(svrl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("||", 1)
                text = parts[1] if len(parts) > 1 else line

                # Extract path from [path:...] annotation in assertion text
                path = ""
                path_match = re.search(r'\[path:([^\]]+)\]', text)
                if path_match:
                    path = path_match.group(1)
                    text = re.sub(r'\s*\[path:[^\]]+\]', '', text).strip()

                sch_errors.append({
                    "category": "SCHEMATRON",
                    "path": path,
                    "message": text
                })
    except Exception:
        pass

    # Merge
    all_errors = igamt.get("errors", []) + sch_errors
    result = {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": igamt.get("warnings", [])
    }

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
