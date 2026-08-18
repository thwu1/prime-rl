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
    parser.add_argument(
        "--validation-operations",
        type=int,
        nargs="+",
        help="Validation operations. Defaults to --operations for backward compatibility.",
    )
    parser.add_argument("--expected-per-operation", type=int, required=True)
    parser.add_argument("--expected-validation-per-operation", type=int, default=200)
    parser.add_argument(
        "--required-distinct-task-pulls",
        type=int,
        help="Fail unless the training pool has at least this many globally unique prompts and IDs.",
    )
    parser.add_argument(
        "--require-global-uniqueness",
        action="store_true",
        help="Require validation prompts and IDs to be unique and disjoint from training.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def prompt_text(row: dict[str, Any]) -> str:
    return row.get("prompt") or (
        f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    )


def canonical_completion(row: dict[str, Any]) -> str:
    completion = row.get("completion")
    if completion:
        return str(completion)
    solution = str(row["solution"])
    if "Answer:" not in solution:
        raise ValueError(f"Canonical solution lacks an Answer marker: {row.get('id')}")
    body, answer = solution.rsplit("Answer:", 1)
    answer = answer.strip().splitlines()[0].strip().rstrip(".")
    if not body.strip() or not answer:
        raise ValueError(f"Canonical solution has an empty rationale or answer: {row.get('id')}")
    return f"{body.strip()} </solution> <answer> {answer} </answer>"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(args: argparse.Namespace) -> dict[str, Any]:
    validation_operations = getattr(args, "validation_operations", None) or args.operations
    expected_validation_per_operation = getattr(args, "expected_validation_per_operation", 200)
    required_distinct_task_pulls = getattr(args, "required_distinct_task_pulls", None)
    require_global_uniqueness = getattr(args, "require_global_uniqueness", False)

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
    if required_distinct_task_pulls is not None:
        if required_distinct_task_pulls < 1:
            raise ValueError("--required-distinct-task-pulls must be positive")
        if len(set(train_ids)) < required_distinct_task_pulls:
            raise ValueError(
                "Training data has insufficient unique IDs for no-repeat sampling: "
                f"{len(set(train_ids))} < {required_distinct_task_pulls}"
            )
        if len(set(train_prompts)) < required_distinct_task_pulls:
            raise ValueError(
                "Training data has insufficient unique prompts for no-repeat sampling: "
                f"{len(set(train_prompts))} < {required_distinct_task_pulls}"
            )

    canonical_strict_failures = [
        str(row["id"])
        for row in train_rows
        if not compare_solutions(str(row["solution"]), canonical_completion(row))["perfect"]
    ]
    if canonical_strict_failures:
        raise ValueError(f"Canonical completions fail strict grading: {canonical_strict_failures[:10]}")

    validation_files = [
        args.validation_dir / f"op{op}-{expected_validation_per_operation}.jsonl" for op in validation_operations
    ]
    missing_validation = [str(path) for path in validation_files if not path.is_file()]
    if missing_validation:
        raise FileNotFoundError(f"Missing validation files: {missing_validation}")
    validation_rows_by_op = {
        operation: read_jsonl(path) for operation, path in zip(validation_operations, validation_files, strict=True)
    }
    invalid_validation_counts = {
        operation: len(rows)
        for operation, rows in validation_rows_by_op.items()
        if len(rows) != expected_validation_per_operation
    }
    if invalid_validation_counts:
        raise ValueError(
            "Validation OP counts differ: "
            f"{invalid_validation_counts}; expected {expected_validation_per_operation} per operation"
        )
    invalid_validation_ops = {
        operation: sorted({int(row["op"]) for row in rows})
        for operation, rows in validation_rows_by_op.items()
        if any(int(row["op"]) != operation for row in rows)
    }
    if invalid_validation_ops:
        raise ValueError(f"Validation files contain rows from the wrong operation: {invalid_validation_ops}")

    validation_rows = [row for rows in validation_rows_by_op.values() for row in rows]
    validation_ids = [str(row["id"]) for row in validation_rows]
    if require_global_uniqueness and len(validation_ids) != len(set(validation_ids)):
        raise ValueError("Validation data contains duplicate sample IDs")
    validation_prompts_list = [prompt_text(row) for row in validation_rows]
    if require_global_uniqueness and len(validation_prompts_list) != len(set(validation_prompts_list)):
        raise ValueError("Validation data contains duplicate prompts")
    validation_canonical_strict_failures = [
        str(row["id"])
        for row in validation_rows
        if not compare_solutions(str(row["solution"]), canonical_completion(row))["perfect"]
    ]
    if validation_canonical_strict_failures:
        raise ValueError(
            f"Validation canonical completions fail strict grading: {validation_canonical_strict_failures[:10]}"
        )
    validation_prompts = set(validation_prompts_list)
    prompt_overlap = sorted(set(train_prompts) & validation_prompts)
    if prompt_overlap:
        raise ValueError(f"Training prompts overlap validation: {prompt_overlap[:10]}")
    id_overlap = sorted(set(train_ids) & set(validation_ids))
    if require_global_uniqueness and id_overlap:
        raise ValueError(f"Training sample IDs overlap validation: {id_overlap[:10]}")

    contexts = Counter(str(row["context"]) for row in train_rows)
    modes = Counter(str(row["mode"]) for row in train_rows)
    report = {
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
            "unique_ids": len(set(validation_ids)),
            "unique_prompts": len(validation_prompts),
            "canonical_strict_passes": len(validation_rows) - len(validation_canonical_strict_failures),
            "by_op": {str(operation): len(rows) for operation, rows in sorted(validation_rows_by_op.items())},
            "prompt_overlap": len(prompt_overlap),
            "id_overlap": len(id_overlap),
            "files": {path.name: file_sha256(path) for path in validation_files},
        },
    }
    if required_distinct_task_pulls is not None:
        headroom = len(set(train_prompts)) - required_distinct_task_pulls
        report["no_repeat_capacity"] = {
            "required_distinct_task_pulls": required_distinct_task_pulls,
            "available_unique_ids": len(set(train_ids)),
            "available_unique_prompts": len(set(train_prompts)),
            "headroom_prompts": headroom,
            "headroom_over_required": headroom / required_distinct_task_pulls,
        }
    return report


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
