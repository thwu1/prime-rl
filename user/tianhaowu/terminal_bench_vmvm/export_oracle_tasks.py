#!/usr/bin/env python3
"""Export a deterministic training subset from durable oracle results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=2500)
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be positive")
    task_dir = args.oracle_dir / "tasks"
    valid = []
    for path in task_dir.glob("*.json"):
        result = json.loads(path.read_text())
        if result.get("valid") is True:
            valid.append(result["slug"])
    valid.sort()
    if len(valid) < args.limit:
        raise SystemExit(f"only {len(valid)} oracle-valid tasks; need {args.limit}")

    selected = valid[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text("".join(f"{slug}\n" for slug in selected))
    temporary.replace(args.output)
    print(f"wrote {len(selected)} oracle-valid tasks to {args.output}")


if __name__ == "__main__":
    main()
