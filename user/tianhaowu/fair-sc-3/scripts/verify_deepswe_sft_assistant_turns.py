#!/usr/bin/env python3
"""Exhaustively verify assistant-turn-expanded DeepSWE SFT artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    return parser.parse_args()


def verify_messages(messages: Any, *, source: str) -> bool:
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{source}: messages must be a nonempty list")
    target = messages[-1]
    if target.get("role") != "assistant" or target.get("trainable") is not True:
        raise ValueError(f"{source}: final message is not the trainable assistant target")
    if sum(message.get("trainable") is True for message in messages) != 1:
        raise ValueError(f"{source}: expected exactly one trainable message")

    for message_index, message in enumerate(messages[:-1]):
        if message.get("trainable") is not False:
            raise ValueError(f"{source}: context message {message_index} is not masked")
        if message.get("role") == "assistant" and (
            message.get("reasoning") is not None or message.get("reasoning_content") is not None
        ):
            raise ValueError(f"{source}: context assistant {message_index} retains reasoning")
    return "reasoning_content" in target


def verify_split(path: Path, expected: dict[str, Any]) -> dict[str, int]:
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    tasks: set[str] = set()
    previous_source_index = -1
    next_turn_index = 0
    trajectory_turn_count = 0

    with path.open("rb") as source:
        for row_number, line in enumerate(source, 1):
            digest.update(line)
            row = json.loads(line)
            source_index = row.get("source_split_row_index")
            turn_index = row.get("target_assistant_turn_index")
            turn_count = row.get("source_trajectory_assistant_turn_count")
            message_index = row.get("target_assistant_message_index")
            if not all(isinstance(value, int) for value in (source_index, turn_index, turn_count, message_index)):
                raise TypeError(f"{path}:{row_number}: invalid source/target indices")

            if source_index != previous_source_index:
                if previous_source_index >= 0 and next_turn_index != trajectory_turn_count:
                    raise ValueError(f"{path}:{row_number}: previous trajectory ended early")
                if source_index != previous_source_index + 1:
                    raise ValueError(f"{path}:{row_number}: non-contiguous source trajectory index")
                previous_source_index = source_index
                next_turn_index = 0
                trajectory_turn_count = turn_count
                counts["source_trajectories"] += 1
            elif turn_count != trajectory_turn_count:
                raise ValueError(f"{path}:{row_number}: trajectory turn count changed within a group")

            if turn_index != next_turn_index:
                raise ValueError(f"{path}:{row_number}: non-contiguous assistant target index")
            messages = row.get("messages")
            has_reasoning = verify_messages(messages, source=f"{path}:{row_number}")
            if message_index != len(messages) - 1:
                raise ValueError(f"{path}:{row_number}: target message index does not match prefix length")
            if row.get("target_has_reasoning") is not has_reasoning:
                raise ValueError(f"{path}:{row_number}: target reasoning flag is incorrect")
            if row.get("assistant_target_count") != 1:
                raise ValueError(f"{path}:{row_number}: assistant_target_count must be one")
            if row.get("history_reasoning_policy") != "strip_all_prior_assistant_reasoning":
                raise ValueError(f"{path}:{row_number}: incorrect history reasoning policy")

            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise TypeError(f"{path}:{row_number}: task_id must be a string")
            tasks.add(task_id)
            counts["expanded_samples"] += 1
            counts["target_assistant_turns"] += 1
            counts["context_assistant_turns"] += turn_index
            counts["targets_with_reasoning" if has_reasoning else "targets_without_reasoning"] += 1
            next_turn_index += 1

    if previous_source_index >= 0 and next_turn_index != trajectory_turn_count:
        raise ValueError(f"{path}: final trajectory ended early")
    counts["tasks"] = len(tasks)

    observed = dict(counts)
    expected_counts = {
        key: value
        for key, value in expected.items()
        if key not in {"source", "artifact"}
    }
    if observed != expected_counts:
        raise ValueError(f"{path}: counts differ: observed={observed}, expected={expected_counts}")
    artifact = expected["artifact"]
    if path.stat().st_size != artifact["bytes"]:
        raise ValueError(f"{path}: byte size differs from manifest")
    if digest.hexdigest() != artifact["sha256"]:
        raise ValueError(f"{path}: SHA-256 differs from manifest")
    return observed


def main() -> None:
    args = parse_args()
    root_manifest = json.loads((args.dataset_root / "manifest.json").read_text())
    summaries: dict[str, Any] = {}
    for variant in root_manifest["variants"]:
        variant_dir = args.dataset_root / variant
        manifest = json.loads((variant_dir / "manifest.json").read_text())
        summaries[variant] = {
            split: verify_split(
                variant_dir / split / "train.jsonl",
                manifest["counts"][split],
            )
            for split in ("train", "validation")
        }
        train_tasks = set(json.loads((variant_dir / "task-split.json").read_text())["train_tasks"])
        validation_tasks = set(json.loads((variant_dir / "task-split.json").read_text())["validation_tasks"])
        if train_tasks & validation_tasks:
            raise ValueError(f"{variant}: train and validation tasks overlap")

    print(json.dumps({"status": "verified", "variants": summaries}, indent=2))


if __name__ == "__main__":
    main()
