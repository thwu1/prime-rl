#!/usr/bin/env python3
"""Generate analyze.py in /app/."""

SRC = '''\
"""Analysis pipeline: check all histories and write results.json."""
import json
from pathlib import Path
from history import History
from checker import is_linearizable


def main():
    hdir = Path("/app/histories")
    results = {}
    for fp in sorted(hdir.glob("*.json")):
        seed = fp.stem
        hist = History.from_json(str(fp))
        lin = is_linearizable(hist)
        results[seed] = {"linearizable": lin}
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    for s, r in sorted(results.items()):
        tag = "PASS" if r["linearizable"] else "FAIL"
        print(f"{s}: {tag}")


if __name__ == "__main__":
    main()
'''

with open("/app/analyze.py", "w") as f:
    f.write(SRC)
print("Wrote /app/analyze.py")
