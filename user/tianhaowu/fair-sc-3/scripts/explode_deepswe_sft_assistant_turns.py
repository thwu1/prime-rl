#!/usr/bin/env python3
"""Expand cumulative DeepSWE trajectories into one target assistant turn per row."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

JSON_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--variant", action="append", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def validate_source_messages(messages: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{source}: messages must be a nonempty list")

    assistant_count = 0
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TypeError(f"{source}: message {message_index} is not a mapping")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"{source}: message {message_index} has invalid role {role!r}")
        content = message.get("content")
        if not isinstance(content, str):
            raise TypeError(f"{source}: message {message_index} has non-string content")
        if role != "assistant":
            continue

        assistant_count += 1
        reasoning = message.get("reasoning_content")
        if reasoning is not None and (not isinstance(reasoning, str) or not reasoning.strip()):
            raise ValueError(f"{source}: assistant message {message_index} has invalid reasoning_content")
        if "<think>" in content or "</think>" in content:
            raise ValueError(f"{source}: assistant message {message_index} contains inline thinking")

    if assistant_count == 0:
        raise ValueError(f"{source}: trajectory has no assistant messages")
    return messages


def context_message(message: dict[str, Any]) -> dict[str, Any]:
    context = {
        key: value
        for key, value in message.items()
        if key not in {"reasoning", "reasoning_content", "trainable"}
    }
    context["trainable"] = False
    return context


def target_message(message: dict[str, Any]) -> dict[str, Any]:
    target = {key: value for key, value in message.items() if key != "trainable"}
    target["trainable"] = True
    return target


def validate_expanded_messages(messages: list[dict[str, Any]], *, source: str) -> None:
    if messages[-1].get("role") != "assistant" or messages[-1].get("trainable") is not True:
        raise ValueError(f"{source}: target must be the final trainable assistant message")
    if sum(message.get("trainable") is True for message in messages) != 1:
        raise ValueError(f"{source}: expanded row must contain exactly one trainable message")
    for message in messages[:-1]:
        if message.get("trainable") is not False:
            raise ValueError(f"{source}: context message is not explicitly masked")
        if message.get("role") == "assistant" and (
            message.get("reasoning") is not None or message.get("reasoning_content") is not None
        ):
            raise ValueError(f"{source}: context assistant still contains reasoning")


def expanded_rows(row: dict[str, Any], *, source: str, split_row_index: int):
    messages = validate_source_messages(row.get("messages"), source=source)
    assistant_count = sum(message["role"] == "assistant" for message in messages)
    base = {key: value for key, value in row.items() if key != "messages"}
    original_target_count = base.pop("assistant_target_count", assistant_count)
    if not isinstance(original_target_count, int) or original_target_count < 0:
        raise ValueError(f"{source}: assistant_target_count metadata must be a nonnegative integer")

    history: list[dict[str, Any]] = []
    assistant_turn_index = 0
    for message_index, message in enumerate(messages):
        if message["role"] != "assistant":
            history.append(context_message(message))
            continue

        target = target_message(message)
        sample_messages = [*history, target]
        expanded_source = f"{source}:assistant[{assistant_turn_index}]"
        validate_expanded_messages(sample_messages, source=expanded_source)
        yield {
            **base,
            "messages": sample_messages,
            "assistant_target_count": 1,
            "source_assistant_target_count_metadata": original_target_count,
            "source_trajectory_assistant_turn_count": assistant_count,
            "source_split_row_index": split_row_index,
            "target_assistant_turn_index": assistant_turn_index,
            "target_assistant_message_index": message_index,
            "target_has_reasoning": "reasoning_content" in target,
            "history_reasoning_policy": "strip_all_prior_assistant_reasoning",
        }
        history.append(context_message(message))
        assistant_turn_index += 1


def convert_split(source_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    tasks: set[str] = set()
    with source_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as destination:
        for split_row_index, line in enumerate(source):
            if not line.strip():
                continue
            row = json.loads(line)
            source_label = f"{source_path}:{split_row_index + 1}"
            counts["source_trajectories"] += 1
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise ValueError(f"{source_label}: task_id must be a string")
            tasks.add(task_id)
            for expanded in expanded_rows(
                row,
                source=source_label,
                split_row_index=split_row_index,
            ):
                for chunk in JSON_ENCODER.iterencode(expanded):
                    destination.write(chunk)
                destination.write("\n")
                counts["expanded_samples"] += 1
                counts["target_assistant_turns"] += 1
                counts["context_assistant_turns"] += expanded["target_assistant_turn_index"]
                if expanded["target_has_reasoning"]:
                    counts["targets_with_reasoning"] += 1
                else:
                    counts["targets_without_reasoning"] += 1
                if counts["expanded_samples"] % 5000 == 0:
                    print(
                        f"{output_path}: wrote {counts['expanded_samples']} samples",
                        flush=True,
                    )

    counts["tasks"] = len(tasks)
    return {
        **dict(counts),
        "source": {
            "path": str(source_path),
            "sha256": sha256_file(source_path),
        },
        "artifact": artifact(output_path, rows=counts["expanded_samples"]),
    }


def convert_variant(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    split_summaries: dict[str, Any] = {}
    for split in ("train", "validation"):
        source_path = source_dir / split / "train.jsonl"
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        split_summaries[split] = convert_split(
            source_path,
            output_dir / split / "train.jsonl",
        )

    source_manifest = source_dir / "manifest.json"
    source_task_split = source_dir / "task-split.json"
    if not source_manifest.is_file() or not source_task_split.is_file():
        raise FileNotFoundError(f"{source_dir}: missing manifest.json or task-split.json")
    shutil.copy2(source_task_split, output_dir / "task-split.json")

    manifest = {
        "format_version": 1,
        "dataset_id": f"{source_dir.name}-assistant-turn-expanded-stripped-history-v1",
        "source": {
            "path": str(source_dir),
            "manifest_sha256": sha256_file(source_manifest),
        },
        "format": {
            "sample_unit": "one assistant generation",
            "messages": "OpenAI chat messages ending at the target assistant turn",
            "history_assistant_reasoning": "removed",
            "history_visible_content_and_tool_calls": "preserved",
            "tool_responses": "native role=tool messages linked by tool_call_id",
            "loss_mask": "message.trainable; exactly one final assistant message is true",
            "target": "full authentic current assistant reasoning_content when present, content, tool_calls, and stop token",
            "missing_target_reasoning": "preserve the authentic empty-think turn; never synthesize reasoning",
        },
        "inference_contract": {
            "prior_assistant_reasoning": "remove before rendering every generation request",
            "current_generation_prefix": "<|im_start|>assistant\\n<think>\\n",
            "warning": "Nemotron truncate_history_thinking=true alone does not remove reasoning inside an assistant/tool cycle",
        },
        "counts": split_summaries,
        "artifacts": {
            "train/train.jsonl": split_summaries["train"]["artifact"],
            "validation/train.jsonl": split_summaries["validation"]["artifact"],
            "task-split.json": artifact(output_dir / "task-split.json"),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def write_root_manifest(output_root: Path, manifests: dict[str, dict[str, Any]]) -> None:
    path = output_root / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "variants": {
                    name: {
                        "dataset_id": manifest["dataset_id"],
                        "train_samples": manifest["counts"]["train"]["expanded_samples"],
                        "validation_samples": manifest["counts"]["validation"]["expanded_samples"],
                    }
                    for name, manifest in manifests.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if args.output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.output_root}")
    if len(args.variant) != len(set(args.variant)):
        raise ValueError("Each variant must be specified exactly once")

    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{args.output_root.name}.",
            dir=args.output_root.parent,
        )
    )
    completed = False
    try:
        manifests = {
            variant: convert_variant(
                args.input_root / variant,
                temporary / variant,
            )
            for variant in args.variant
        }
        write_root_manifest(temporary, manifests)
        os.replace(temporary, args.output_root)
        completed = True
    finally:
        if not completed and temporary.exists():
            shutil.rmtree(temporary)

    print(
        json.dumps(
            {
                "status": "converted",
                "output_root": str(args.output_root),
                "variants": {
                    name: {
                        split: summary["counts"][split]["expanded_samples"]
                        for split in ("train", "validation")
                    }
                    for name, summary in manifests.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
