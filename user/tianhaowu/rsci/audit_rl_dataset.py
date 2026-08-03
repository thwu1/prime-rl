#!/usr/bin/env python
"""Audit an OP-balanced GSM-Infinite RL prompt pool against held-out data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from solution_graph import compare_solutions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-data", type=Path, required=True)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--operations", type=int, nargs="+", required=True)
    parser.add_argument("--expected-per-operation", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def prompt_text(row: dict[str, Any]) -> str:
    return row.get("prompt") or (
        f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(args: argparse.Namespace) -> dict[str, Any]:
    train_rows = read_jsonl(args.train_data)
    train_counts = Counter(int(row["op"]) for row in train_rows)
    expected_counts = {op: args.expected_per_operation for op in args.operations}
    if dict(sorted(train_counts.items())) != expected_counts:
        raise ValueError(f"Training OP counts differ: {dict(sorted(train_counts.items()))} != {expected_counts}")

    train_ids = [str(row["id"]) for row in train_rows]
    if len(train_ids) != len(set(train_ids)):
        raise ValueError("Training data contains duplicate sample IDs")
    train_prompts = [prompt_text(row) for row in train_rows]
    if len(train_prompts) != len(set(train_prompts)):
        raise ValueError("Training data contains duplicate prompts")

    canonical_strict_failures = [
        str(row["id"])
        for row in train_rows
        if not compare_solutions(str(row["solution"]), str(row["completion"]))["perfect"]
    ]
    if canonical_strict_failures:
        raise ValueError(f"Canonical completions fail strict grading: {canonical_strict_failures[:10]}")

    validation_files = [args.validation_dir / f"op{op}-200.jsonl" for op in args.operations]
    missing_validation = [str(path) for path in validation_files if not path.is_file()]
    if missing_validation:
        raise FileNotFoundError(f"Missing validation files: {missing_validation}")
    validation_rows = [row for path in validation_files for row in read_jsonl(path)]
    validation_prompts = {prompt_text(row) for row in validation_rows}
    prompt_overlap = sorted(set(train_prompts) & validation_prompts)
    if prompt_overlap:
        raise ValueError(f"Training prompts overlap released validation: {prompt_overlap[:10]}")

    contexts = Counter(str(row["context"]) for row in train_rows)
    modes = Counter(str(row["mode"]) for row in train_rows)
    return {
        "schema_version": 1,
        "train": {
            "path": str(args.train_data.resolve()),
            "sha256": file_sha256(args.train_data),
            "rows": len(train_rows),
            "unique_ids": len(set(train_ids)),
            "unique_prompts": len(set(train_prompts)),
            "canonical_strict_passes": len(train_rows) - len(canonical_strict_failures),
            "by_op": dict(sorted(train_counts.items())),
            "by_context": dict(sorted(contexts.items())),
            "by_mode": dict(sorted(modes.items())),
        },
        "validation": {
            "directory": str(args.validation_dir.resolve()),
            "rows": len(validation_rows),
            "prompt_overlap": len(prompt_overlap),
            "files": {path.name: file_sha256(path) for path in validation_files},
        },
    }


def main() -> None:
    args = parse_args()
    report = audit(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
