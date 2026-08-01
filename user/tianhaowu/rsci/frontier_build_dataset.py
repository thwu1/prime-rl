#!/usr/bin/env python
"""Build an exact cumulative frontier-SFT parquet from accepted trace shards."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from datasets import Dataset
from prepare_sft_data import CHAT_TEMPLATE, one_epoch_training_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-operation", type=int, default=11)
    parser.add_argument("--through-operation", type=int, required=True)
    parser.add_argument("--examples-per-operation", type=int, default=50_000)
    parser.add_argument("--collection-name", default="collection")
    parser.add_argument("--seq-len", type=int, default=2048)
    parser.add_argument("--world-size", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--micro-batch-size", type=int, default=4)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def load_shard(path: Path, operation: int, expected: int, seq_len: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} rows in {path}, found {len(rows)}")
    ids: set[str] = set()
    for line_number, row in enumerate(rows, start=1):
        if int(row["op"]) != operation:
            raise ValueError(f"Unexpected op in {path}:{line_number}: {row['op']}")
        trace_id = str(row["id"])
        if trace_id in ids:
            raise ValueError(f"Duplicate trace id in {path}:{line_number}: {trace_id}")
        ids.add(trace_id)
        messages = row["messages"]
        if [message["role"] for message in messages] != ["user", "assistant"]:
            raise ValueError(f"Invalid messages in {path}:{line_number}")
        if int(row["num_tokens"]) > seq_len:
            raise ValueError(f"Overlength accepted trace in {path}:{line_number}")
        if not row["answer_correct"]:
            raise ValueError(f"Answer-incorrect accepted trace in {path}:{line_number}")
        if row["filter_mode"] == "strict" and not row["strict_correct"]:
            raise ValueError(f"Strict-incorrect accepted trace in {path}:{line_number}")
    return rows


def main() -> None:
    args = parse_args()
    if args.through_operation < args.start_operation:
        raise ValueError("through-operation must be >= start-operation")
    output_path = args.output_dir / "train-00000-of-00001.parquet"
    manifest_path = args.output_dir / "manifest.json"
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Cumulative dataset already exists: {args.output_dir}")

    operations = list(range(args.start_operation, args.through_operation + 1))
    rows: list[dict[str, Any]] = []
    source_sha256_by_op: dict[str, str] = {}
    source_paths_by_op: dict[str, str] = {}
    for operation in operations:
        source = args.track_root / "iterations" / f"op{operation}" / args.collection_name / "accepted.jsonl"
        source_rows = load_shard(source, operation, args.examples_per_operation, args.seq_len)
        rows.extend(source_rows)
        source_sha256_by_op[str(operation)] = file_sha256(source)
        source_paths_by_op[str(operation)] = str(source.resolve())

    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Trace ids are not unique across cumulative shards")
    dataset = Dataset.from_list(rows)
    plan_args = SimpleNamespace(
        world_size=args.world_size,
        batch_size=args.batch_size,
        micro_batch_size=args.micro_batch_size,
        seq_len=args.seq_len,
    )
    training_plan = one_epoch_training_plan(dataset, plan_args)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    dataset.to_parquet(output_path)

    counts_by_op = Counter(int(row["op"]) for row in rows)
    lengths = [int(row["num_tokens"]) for row in rows]
    manifest = {
        "format": "prime-rl messages SFT parquet",
        "chat_template": CHAT_TEMPLATE,
        "track_root": str(args.track_root.resolve()),
        "collection_name": args.collection_name,
        "operations": operations,
        "examples_per_operation": args.examples_per_operation,
        "rows": len(rows),
        "counts_by_op": dict(sorted(counts_by_op.items())),
        "strict_correct_rows": sum(bool(row["strict_correct"]) for row in rows),
        "answer_correct_rows": sum(bool(row["answer_correct"]) for row in rows),
        "source_paths_by_op": source_paths_by_op,
        "source_sha256_by_op": source_sha256_by_op,
        "token_count_including_eos": sum(lengths),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "rows_over_seq_len": sum(length > args.seq_len for length in lengths),
        "seq_len": args.seq_len,
        "training_plan": training_plan,
        "parquet_sha256": file_sha256(output_path),
        "implementation_sha256": {
            "frontier_build_dataset.py": file_sha256(Path(__file__)),
            "prepare_sft_data.py": file_sha256(Path(__file__).with_name("prepare_sft_data.py")),
        },
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
