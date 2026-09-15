#!/usr/bin/env python3
"""CLI: python3 cli.py "formula" < data.csv"""

import sys
import csv
import json


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cli.py <formula> [--json]", file=sys.stderr)
        sys.exit(1)

    formula = sys.argv[1]
    use_json = "--json" in sys.argv

    reader = csv.DictReader(sys.stdin)
    data = {}
    for row in reader:
        for k, v in row.items():
            data.setdefault(k, [])
            try:
                data[k].append(float(v))
            except ValueError:
                data[k].append(v)

    sys.path.insert(0, "/app")
    from design_matrix import dmatrix

    cols, mat = dmatrix(formula, data)

    if use_json:
        print(json.dumps({"columns": cols, "matrix": mat}))
    else:
        w = csv.writer(sys.stdout)
        w.writerow(cols)
        for row in mat:
            w.writerow(row)


if __name__ == "__main__":
    main()
