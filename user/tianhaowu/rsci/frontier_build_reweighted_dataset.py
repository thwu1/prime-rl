#!/usr/bin/env python
"""Build a fixed-size cumulative frontier dataset with exponential replay decay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from datasets import Dataset
from frontier_build_dataset import file_sha256, load_shard, write_json
from prepare_sft_data import CHAT_TEMPLATE, one_epoch_training_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-operation", type=int, default=11)
    parser.add_argument("--through-operation", type=int, required=True)
    parser.add_argument("--examples-per-operation", type=int, default=50_000)
    parser.add_argument("--collection-name", default="collection")
    parser.add_argument("--replay-decay", type=float, required=True)
    parser.add_argument("--resample-seed", type=int, default=20260802)
    parser.add_argument("--seq-len", type=int, default=2048)
    parser.add_argument("--world-size", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--micro-batch-size", type=int, default=4)
    return parser.parse_args()


def allocate_counts(operations: list[int], examples_per_operation: int, replay_decay: float) -> dict[int, int]:
    if not math.isfinite(replay_decay) or not 0 < replay_decay <= 1:
        raise ValueError("replay-decay must be finite and in (0, 1]")
    total_rows = examples_per_operation * len(operations)
    newest = max(operations)
    weights = {operation: replay_decay ** (newest - operation) for operation in operations}
    weight_sum = sum(weights.values())
    exact = {operation: total_rows * weights[operation] / weight_sum for operation in operations}
    counts = {operation: math.floor(value) for operation, value in exact.items()}
    remainder = total_rows - sum(counts.values())
    priority = sorted(operations, key=lambda operation: (-(exact[operation] - counts[operation]), -operation))
    for operation in priority[:remainder]:
        counts[operation] += 1
    if sum(counts.values()) != total_rows or any(count < 1 for count in counts.values()):
        raise ValueError("Exponential replay allocation produced invalid counts")
    return counts


def operation_seed(seed: int, collection_name: str, operation: int) -> int:
    material = f"{seed}:{collection_name}:{operation}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def resample_rows(
    rows: list[dict[str, Any]],
    target_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    if target_count < 1:
        raise ValueError("target_count must be positive")
    indices = list(range(len(rows)))
    random.Random(seed).shuffle(indices)
    repeats, remainder = divmod(target_count, len(rows))
    selected_indices = indices * repeats + indices[:remainder]
    return [rows[index] for index in selected_indices]


def main() -> None:
    args = parse_args()
    if args.through_operation < args.start_operation:
        raise ValueError("through-operation must be >= start-operation")
    if args.output_dir.exists():
        raise FileExistsError(f"Reweighted dataset already exists: {args.output_dir}")
    temporary_dir = args.output_dir.with_name(f"{args.output_dir.name}.partial")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)
    output_path = temporary_dir / "train-00000-of-00001.parquet"
    manifest_path = temporary_dir / "manifest.json"

    operations = list(range(args.start_operation, args.through_operation + 1))
    target_counts = allocate_counts(operations, args.examples_per_operation, args.replay_decay)
    rows: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    source_paths_by_op: dict[str, str] = {}
    source_sha256_by_op: dict[str, str] = {}
    requested_weights_by_op: dict[str, float] = {}
    for operation in operations:
        source = args.track_root / "iterations" / f"op{operation}" / args.collection_name / "accepted.jsonl"
        source_rows = load_shard(source, operation, args.examples_per_operation, args.seq_len)
        operation_ids = {str(row["id"]) for row in source_rows}
        overlap = source_ids & operation_ids
        if overlap:
            raise ValueError(f"Trace ids overlap across source shards at op{operation}")
        source_ids.update(operation_ids)
        rows.extend(
            resample_rows(
                source_rows,
                target_counts[operation],
                operation_seed(args.resample_seed, args.collection_name, operation),
            )
        )
        source_paths_by_op[str(operation)] = str(source.resolve())
        source_sha256_by_op[str(operation)] = file_sha256(source)
        requested_weights_by_op[str(operation)] = args.replay_decay ** (args.through_operation - operation)

    expected_rows = args.examples_per_operation * len(operations)
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} resampled rows, found {len(rows)}")
    counts_by_op = Counter(int(row["op"]) for row in rows)
    if counts_by_op != Counter(target_counts):
        raise ValueError("Materialized operation counts differ from the allocation")

    dataset = Dataset.from_list(rows)
    plan_args = SimpleNamespace(
        world_size=args.world_size,
        batch_size=args.batch_size,
        micro_batch_size=args.micro_batch_size,
        seq_len=args.seq_len,
    )
    training_plan = one_epoch_training_plan(dataset, plan_args)
    dataset.to_parquet(output_path)

    trace_ids = [str(row["id"]) for row in rows]
    lengths = [int(row["num_tokens"]) for row in rows]
    token_counts_by_op = Counter()
    for row in rows:
        token_counts_by_op[int(row["op"])] += int(row["num_tokens"])
    manifest = {
        "format": "prime-rl messages SFT parquet",
        "chat_template": CHAT_TEMPLATE,
        "track_root": str(args.track_root.resolve()),
        "collection_name": args.collection_name,
        "operations": operations,
        "source_examples_per_operation": args.examples_per_operation,
        "rows": len(rows),
        "unique_trace_ids": len(set(trace_ids)),
        "repeated_rows": len(rows) - len(set(trace_ids)),
        "counts_by_op": dict(sorted(counts_by_op.items())),
        "token_counts_by_op": dict(sorted(token_counts_by_op.items())),
        "replay": {
            "kind": "exponential_operation_decay",
            "formula": "weight(op_i) = replay_decay ** (through_operation - op_i)",
            "replay_decay": args.replay_decay,
            "resample_seed": args.resample_seed,
            "requested_weights_by_op": requested_weights_by_op,
            "allocated_rows_by_op": dict(sorted(target_counts.items())),
            "total_rows_rule": "source_examples_per_operation * number_of_operations",
            "resampling_rule": "seeded permutation cycles; full cycles precede the residual prefix",
        },
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
            "frontier_build_reweighted_dataset.py": file_sha256(Path(__file__)),
            "frontier_build_dataset.py": file_sha256(Path(__file__).with_name("frontier_build_dataset.py")),
            "prepare_sft_data.py": file_sha256(Path(__file__).with_name("prepare_sft_data.py")),
        },
    }
    write_json(manifest_path, manifest)
    temporary_dir.replace(args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
