#!/usr/bin/env python3
"""Audit deterministic image build statuses against a JSONL build plan."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--status-root",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_status"),
    )
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.plan.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("empty build plan")
    if len({(row["task"], row["role"]) for row in rows}) != len(rows):
        raise SystemExit("build plan contains duplicate task/role rows")

    counts: Counter[str] = Counter()
    problems: list[dict] = []
    for row in rows:
        tag = row["image"].rsplit(":", 1)[-1]
        status_path = args.status_root / tag / f"{row['task']}.{row['role']}.json"
        if not status_path.is_file():
            counts["missing"] += 1
            problems.append({"task": row["task"], "role": row["role"], "problem": "missing_status"})
            continue
        try:
            status = json.loads(status_path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            counts["invalid_status"] += 1
            problems.append(
                {"task": row["task"], "role": row["role"], "problem": "invalid_status", "detail": str(error)}
            )
            continue
        state = status.get("state", "unknown")
        counts[state] += 1
        mismatches = {
            field: {"expected": row[field], "actual": status.get(field)}
            for field in ("context_sha256", "image")
            if status.get(field) != row[field]
        }
        if state != "success" or mismatches:
            problems.append(
                {
                    "task": row["task"],
                    "role": row["role"],
                    "problem": "status_mismatch" if mismatches else state,
                    "mismatches": mismatches,
                    "detail": status.get("detail"),
                }
            )

    summary = {
        "planned": len(rows),
        "counts": dict(sorted(counts.items())),
        "ready": len(rows) - len(problems),
        "problems": problems,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.require_all and problems:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
