#!/usr/bin/env python3
"""Filter expanded DeepSWE SFT rows at whole-trajectory token-length granularity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from renderers import Nemotron3RendererConfig
from renderers.base import create_renderer
from transformers import AutoTokenizer

from prime_rl.utils.chat_template import (
    deserialize_tool_calls,
    normalize_messages,
    strip_message_content,
)

JSON_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expanded-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--variant-name", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-length", type=int, required=True)
    parser.add_argument("--validation-size", type=int, default=64)
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


def normalize_tools(raw_tools: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not raw_tools:
        return []
    if isinstance(raw_tools, str):
        raw_tools = json.loads(raw_tools)
    return [
        tool
        if tool.get("type") == "function" and "function" in tool
        else {
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "parameters": tool.get("parameters"),
                **({} if tool.get("strict") is None else {"strict": tool["strict"]}),
            },
        }
        for tool in raw_tools
    ]


def resolve_messages(row: dict[str, Any]) -> list[dict[str, Any]]:
    messages = normalize_messages(row["messages"], default_role="assistant")
    return strip_message_content(deserialize_tool_calls(messages))


def strip_reasoning(message: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in message.items()
        if key not in {"reasoning", "reasoning_content"}
    }


def rendered_input_length(renderer, tokenizer, messages, tools) -> int:
    token_ids = list(renderer.render(messages, tools=tools).token_ids)
    if tokenizer.eos_token_id not in token_ids:
        token_ids.append(tokenizer.eos_token_id)
    return len(token_ids) - 1


def trajectory_turn_lengths(
    renderer,
    tokenizer,
    row: dict[str, Any],
    *,
    source: str,
    max_length: int,
) -> tuple[list[int], int]:
    messages = resolve_messages(row)
    tools = normalize_tools(row.get("tools", row.get("tool_defs")))
    stripped_messages = [strip_reasoning(message) for message in messages]
    baseline = renderer.render(stripped_messages, tools=tools)
    counts = Counter(baseline.message_indices)
    prefix_tokens = counts[-1]
    lengths: list[int] = []
    assistant_message_indices: list[int] = []

    for message_index, (message, stripped_message) in enumerate(zip(messages, stripped_messages, strict=True)):
        prefix_tokens += counts[message_index]
        if message["role"] != "assistant":
            continue

        bare_render = renderer.render([stripped_message])
        target_render = renderer.render([message])
        bare_message_tokens = bare_render.message_indices.count(0)
        target_message_tokens = target_render.message_indices.count(0)
        if bare_message_tokens != counts[message_index]:
            raise ValueError(
                f"{source}: assistant message {message_index} is context-dependent "
                f"({bare_message_tokens=} != {counts[message_index]=})"
            )
        lengths.append(prefix_tokens + target_message_tokens - bare_message_tokens - 1)
        assistant_message_indices.append(message_index)

    if not lengths:
        raise ValueError(f"{source}: trajectory has no assistant messages")

    over_limit = [index for index, length in enumerate(lengths) if length > max_length]
    direct_turns = {0, len(lengths) // 2, len(lengths) - 1, max(range(len(lengths)), key=lengths.__getitem__)}
    direct_turns.update(over_limit)
    for turn_index in sorted(direct_turns):
        message_index = assistant_message_indices[turn_index]
        direct_messages = [
            dict(message) if index == message_index or message["role"] != "assistant" else strip_reasoning(message)
            for index, message in enumerate(messages[: message_index + 1])
        ]
        direct_length = rendered_input_length(renderer, tokenizer, direct_messages, tools)
        if direct_length != lengths[turn_index]:
            raise ValueError(
                f"{source}: turn {turn_index} algebra/direct mismatch "
                f"({lengths[turn_index]} != {direct_length})"
            )
    return lengths, len(direct_turns)


def audit_source_split(renderer, tokenizer, path: Path, max_length: int) -> tuple[list[dict[str, Any]], int]:
    audits: list[dict[str, Any]] = []
    direct_checks = 0
    with path.open(encoding="utf-8") as source:
        for source_index, line in enumerate(source):
            if not line.strip():
                raise ValueError(f"{path}:{source_index + 1}: blank rows are unsupported")
            row = json.loads(line)
            source_label = f"{path}:{source_index + 1}"
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise TypeError(f"{source_label}: task_id must be a string")
            lengths, checks = trajectory_turn_lengths(
                renderer,
                tokenizer,
                row,
                source=source_label,
                max_length=max_length,
            )
            direct_checks += checks
            too_long_turns = [
                {"turn_index": index, "rendered_input_tokens": length}
                for index, length in enumerate(lengths)
                if length > max_length
            ]
            audits.append(
                {
                    "source_split_row_index": source_index,
                    "task_id": task_id,
                    "source_episode_id": row.get("source_episode_id"),
                    "turn_lengths": lengths,
                    "assistant_turns": len(lengths),
                    "max_rendered_input_tokens": max(lengths),
                    "too_long_turns": too_long_turns,
                    "retained": not too_long_turns,
                }
            )
            if (source_index + 1) % 25 == 0:
                removed = sum(not audit["retained"] for audit in audits)
                print(f"{path}: audited={source_index + 1} removed={removed}", flush=True)

    retained_index = 0
    for audit in audits:
        if audit["retained"]:
            audit["retained_split_row_index"] = retained_index
            retained_index += 1
    return audits, direct_checks


def empty_expanded_counts() -> Counter[str]:
    return Counter(
        {
            "source_trajectories": 0,
            "expanded_samples": 0,
            "target_assistant_turns": 0,
            "context_assistant_turns": 0,
            "targets_with_reasoning": 0,
            "targets_without_reasoning": 0,
            "tasks": 0,
        }
    )


def filter_expanded_split(
    source_path: Path,
    output_path: Path,
    audits: list[dict[str, Any]],
    max_length: int,
) -> tuple[dict[str, Any], set[str]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = empty_expanded_counts()
    tasks: set[str] = set()
    seen_turns: dict[int, int] = defaultdict(int)

    with source_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as destination:
        for row_number, line in enumerate(source, 1):
            row = json.loads(line)
            source_index = row.get("source_split_row_index")
            turn_index = row.get("target_assistant_turn_index")
            if not isinstance(source_index, int) or not 0 <= source_index < len(audits):
                raise ValueError(f"{source_path}:{row_number}: invalid source trajectory index")
            audit = audits[source_index]
            if not isinstance(turn_index, int) or turn_index != seen_turns[source_index]:
                raise ValueError(f"{source_path}:{row_number}: non-contiguous target assistant turn")
            if row.get("task_id") != audit["task_id"]:
                raise ValueError(f"{source_path}:{row_number}: task differs from cumulative source")
            if row.get("source_trajectory_assistant_turn_count") != audit["assistant_turns"]:
                raise ValueError(f"{source_path}:{row_number}: assistant-turn count differs from source")
            seen_turns[source_index] += 1

            if not audit["retained"]:
                continue
            rendered_length = audit["turn_lengths"][turn_index]
            if rendered_length > max_length:
                raise AssertionError(f"{source_path}:{row_number}: unsafe row survived trajectory filter")
            row["source_original_split_row_index"] = source_index
            row["source_split_row_index"] = audit["retained_split_row_index"]
            row["rendered_input_tokens"] = rendered_length
            row["source_trajectory_max_rendered_input_tokens"] = audit["max_rendered_input_tokens"]
            row["source_trajectory_length_cap"] = max_length
            for chunk in JSON_ENCODER.iterencode(row):
                destination.write(chunk)
            destination.write("\n")

            counts["expanded_samples"] += 1
            counts["target_assistant_turns"] += 1
            counts["context_assistant_turns"] += turn_index
            target_key = "targets_with_reasoning" if row.get("target_has_reasoning") else "targets_without_reasoning"
            counts[target_key] += 1
            tasks.add(audit["task_id"])

    for source_index, audit in enumerate(audits):
        if seen_turns[source_index] != audit["assistant_turns"]:
            raise ValueError(
                f"{source_path}: trajectory {source_index} has {seen_turns[source_index]} expanded rows, "
                f"expected {audit['assistant_turns']}"
            )

    counts["source_trajectories"] = sum(audit["retained"] for audit in audits)
    counts["tasks"] = len(tasks)
    return {
        **dict(counts),
        "source": {"path": str(source_path), "sha256": sha256_file(source_path)},
        "artifact": artifact(output_path, rows=counts["expanded_samples"]),
    }, tasks


def allocate_validation_rows(group_sizes: list[int], target_size: int) -> list[int]:
    if target_size < len(group_sizes) or target_size > sum(group_sizes):
        raise ValueError(
            f"validation-size must be between trajectory count {len(group_sizes)} "
            f"and retained row count {sum(group_sizes)}, got {target_size}"
        )
    allocations = [1] * len(group_sizes)
    remaining = target_size - len(group_sizes)
    capacities = [size - 1 for size in group_sizes]
    while remaining:
        eligible = [index for index, capacity in enumerate(capacities) if allocations[index] - 1 < capacity]
        index = max(eligible, key=lambda candidate: (group_sizes[candidate] / allocations[candidate], -candidate))
        allocations[index] += 1
        remaining -= 1
    return allocations


def write_validation_view(source_path: Path, output_path: Path, target_size: int) -> dict[str, Any]:
    groups: dict[int, list[tuple[int, bytes]]] = defaultdict(list)
    with source_path.open("rb") as source:
        for row_index, line in enumerate(source):
            row = json.loads(line)
            groups[row["source_split_row_index"]].append((row_index, line))

    ordered_groups = [groups[index] for index in range(len(groups))]
    allocations = allocate_validation_rows([len(group) for group in ordered_groups], target_size)
    selected: list[tuple[int, bytes]] = []
    selection: list[dict[str, Any]] = []
    for source_index, (group, allocation) in enumerate(zip(ordered_groups, allocations, strict=True)):
        local_indices = [((2 * index + 1) * len(group)) // (2 * allocation) for index in range(allocation)]
        if len(local_indices) != len(set(local_indices)):
            raise AssertionError(f"validation trajectory {source_index} selection is not unique")
        selected.extend(group[index] for index in local_indices)
        selection.append(
            {
                "source_split_row_index": source_index,
                "source_rows": len(group),
                "selected_turn_indices": local_indices,
            }
        )

    selected.sort(key=lambda item: item[0])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as destination:
        for _, line in selected:
            destination.write(line)
    return {
        "selection": "at least one deterministic evenly-spaced assistant turn per retained validation trajectory",
        "rows": len(selected),
        "trajectory_allocations": selection,
        "artifact": artifact(output_path, rows=len(selected)),
    }


def percentile(sorted_values: list[int], quantile: float) -> int:
    return sorted_values[int(quantile * (len(sorted_values) - 1))]


def selection_summary(audits: list[dict[str, Any]], max_length: int, direct_checks: int) -> dict[str, Any]:
    retained = [audit for audit in audits if audit["retained"]]
    removed = [audit for audit in audits if not audit["retained"]]
    retained_lengths = sorted(length for audit in retained for length in audit["turn_lengths"])
    directly_over = sum(len(audit["too_long_turns"]) for audit in removed)
    removed_turns = sum(audit["assistant_turns"] for audit in removed)
    return {
        "max_length": max_length,
        "source_trajectories": len(audits),
        "retained_trajectories": len(retained),
        "removed_trajectories": len(removed),
        "source_expanded_samples": sum(audit["assistant_turns"] for audit in audits),
        "retained_expanded_samples": len(retained_lengths),
        "removed_expanded_samples": removed_turns,
        "directly_over_limit_samples": directly_over,
        "collateral_samples_removed_with_unsafe_trajectories": removed_turns - directly_over,
        "direct_render_checks": direct_checks,
        "retained_length_distribution": {
            "min": retained_lengths[0],
            "median": percentile(retained_lengths, 0.5),
            "p90": percentile(retained_lengths, 0.9),
            "p95": percentile(retained_lengths, 0.95),
            "p99": percentile(retained_lengths, 0.99),
            "max": retained_lengths[-1],
        },
    }


def excluded_rows(audits_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        split: [
            {
                key: audit[key]
                for key in (
                    "source_split_row_index",
                    "task_id",
                    "source_episode_id",
                    "assistant_turns",
                    "max_rendered_input_tokens",
                    "too_long_turns",
                )
            }
            for audit in audits
            if not audit["retained"]
        ]
        for split, audits in audits_by_split.items()
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_length < 1:
        raise ValueError("max-length must be positive")
    if args.validation_size < 1:
        raise ValueError("validation-size must be positive")

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=True)
    renderer_config = Nemotron3RendererConfig(
        enable_thinking=True,
        ultra=False,
        normalize_tool_response_wrappers=False,
        truncate_history_thinking=True,
        preserve_all_thinking=False,
        preserve_thinking_between_tool_calls=False,
    )
    renderer = create_renderer(tokenizer, renderer_config)

    audits_by_split: dict[str, list[dict[str, Any]]] = {}
    direct_checks: dict[str, int] = {}
    for split in ("train", "validation"):
        source_path = args.source_root / split / "train.jsonl"
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        audits_by_split[split], direct_checks[split] = audit_source_split(
            renderer,
            tokenizer,
            source_path,
            args.max_length,
        )

    temporary = Path(tempfile.mkdtemp(prefix=f".{args.output_root.name}.", dir=args.output_root.parent))
    completed = False
    try:
        variant_dir = temporary / args.variant_name
        counts: dict[str, Any] = {}
        tasks: dict[str, set[str]] = {}
        for split in ("train", "validation"):
            counts[split], tasks[split] = filter_expanded_split(
                args.expanded_root / split / "train.jsonl",
                variant_dir / split / "train.jsonl",
                audits_by_split[split],
                args.max_length,
            )

        if tasks["train"] & tasks["validation"]:
            raise ValueError("Retained train and validation tasks overlap")
        task_split = {
            "parent": str(args.source_root / "task-split.json"),
            "selection": "task-disjoint parent split followed by whole-trajectory length filtering",
            "train_tasks": sorted(tasks["train"]),
            "validation_tasks": sorted(tasks["validation"]),
        }
        write_json(variant_dir / "task-split.json", task_split)

        excluded_path = variant_dir / "excluded-trajectories.json"
        write_json(excluded_path, excluded_rows(audits_by_split))
        validation_view = write_validation_view(
            variant_dir / "validation" / "train.jsonl",
            variant_dir / f"validation-cp1-{args.validation_size}" / "train.jsonl",
            args.validation_size,
        )

        selection = {
            split: selection_summary(audits_by_split[split], args.max_length, direct_checks[split])
            for split in ("train", "validation")
        }
        manifest = {
            "format_version": 1,
            "dataset_id": args.variant_name,
            "source": {
                "cumulative": {
                    "path": str(args.source_root),
                    "manifest_sha256": sha256_file(args.source_root / "manifest.json"),
                },
                "assistant_turn_expanded": {
                    "path": str(args.expanded_root),
                    "manifest_sha256": sha256_file(args.expanded_root / "manifest.json"),
                },
            },
            "format": {
                "sample_unit": "one assistant generation",
                "history_assistant_reasoning": "removed",
                "loss_mask": "message.trainable; exactly one final assistant message is true",
                "target": "full authentic current assistant reasoning_content, content, tool_calls, and stop token",
            },
            "renderer": renderer_config.model_dump(),
            "tokenizer": {"name": args.model, "eos_token_id": tokenizer.eos_token_id},
            "selection_contract": (
                "Remove an entire source trajectory if any assistant-turn-expanded SFT input exceeds max_length; "
                "never truncate a retained row."
            ),
            "selection": selection,
            "counts": counts,
            "validation_view": validation_view,
            "artifacts": {
                "train/train.jsonl": counts["train"]["artifact"],
                "validation/train.jsonl": counts["validation"]["artifact"],
                f"validation-cp1-{args.validation_size}/train.jsonl": validation_view["artifact"],
                "task-split.json": artifact(variant_dir / "task-split.json"),
                "excluded-trajectories.json": artifact(excluded_path),
            },
        }
        write_json(variant_dir / "manifest.json", manifest)
        write_json(
            temporary / "manifest.json",
            {
                "format_version": 1,
                "variants": {
                    args.variant_name: {
                        "dataset_id": args.variant_name,
                        "train_samples": counts["train"]["expanded_samples"],
                        "validation_samples": counts["validation"]["expanded_samples"],
                    }
                },
            },
        )
        os.replace(temporary, args.output_root)
        completed = True
    finally:
        if not completed and temporary.exists():
            shutil.rmtree(temporary)

    return {
        "status": "materialized",
        "output_root": str(args.output_root),
        "variant": args.variant_name,
        "selection": selection,
        "validation_view_rows": validation_view["rows"],
    }


def main() -> None:
    args = parse_args()
    if args.output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.output_root}")
    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(materialize(args), indent=2))


if __name__ == "__main__":
    main()
