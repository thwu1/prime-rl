#!/usr/bin/env python
"""Build strict-filter SFT data after deterministic execution grading."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from datasets import Dataset
from prepare_sft_data import CHAT_TEMPLATE, one_epoch_training_plan
from strict_trajectory_grader import grade_trajectory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start-operation", type=int, default=11)
    parser.add_argument("--through-operation", type=int, required=True)
    parser.add_argument("--train-examples-per-operation", type=int, default=50_000)
    parser.add_argument("--validation-examples-per-operation", type=int, default=5_000)
    parser.add_argument("--seq-len", type=int, default=2048)
    parser.add_argument("--world-size", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--micro-batch-size", type=int, default=4)
    parser.add_argument("--validation-batch-size", type=int, default=32)
    parser.add_argument("--validation-micro-batch-size", type=int, default=4)
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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def canonical_response(prompt: dict[str, Any]) -> str:
    return "<solution> " + str(prompt["completion"])


def model_facing_digest(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row["messages"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_split(
    args: argparse.Namespace,
    collection_name: str,
    expected_per_operation: int,
    output_dir: Path,
    batch_size: int,
    micro_batch_size: int,
) -> tuple[dict[str, Any], set[str]]:
    output_path = output_dir / "train-00000-of-00001.parquet"
    manifest_path = output_dir / "manifest.json"
    if output_path.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest, set(manifest["used_prompt_content_sha256"])
    if output_dir.exists():
        raise FileExistsError(f"Incomplete executable-filtered dataset directory: {output_dir}")

    operations = list(range(args.start_operation, args.through_operation + 1))
    kept_rows: list[dict[str, Any]] = []
    source_sha256_by_op: dict[str, str] = {}
    prompt_sha256_by_op: dict[str, str] = {}
    operation_stats: dict[str, dict[str, Any]] = {}
    issue_code_rows: Counter[str] = Counter()
    issue_combinations: Counter[str] = Counter()
    template_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    used_prompt_content_sha256: set[str] = set()
    exact_examples: set[str] = set()
    allowed_extra_rows = 0

    for operation in operations:
        collection_dir = args.source_root / "iterations" / f"op{operation}" / collection_name
        accepted_path = collection_dir / "accepted.jsonl"
        prompts_path = collection_dir / "prompts.jsonl"
        source_rows = load_jsonl(accepted_path)
        if len(source_rows) != expected_per_operation:
            raise ValueError(
                f"Expected {expected_per_operation} source rows in {accepted_path}, found {len(source_rows)}"
            )
        source_ids = [str(row["id"]) for row in source_rows]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(f"Source trace IDs are not unique in {accepted_path}")
        prompts = {str(row["id"]): row for row in load_jsonl(prompts_path)}
        kept_for_operation = 0
        removed_for_operation = 0
        kept_prompt_ids: set[str] = set()

        for source in source_rows:
            if int(source["op"]) != operation:
                raise ValueError(f"Unexpected operation {source['op']} in {accepted_path}")
            if not source["strict_correct"] or not source["answer_correct"]:
                raise ValueError(f"Source row is not released-verifier strict-correct: {source['id']}")
            if int(source["num_tokens"]) > args.seq_len:
                raise ValueError(f"Source row exceeds seq_len={args.seq_len}: {source['id']}")
            prompt_id = str(source["prompt_id"])
            if prompt_id not in prompts:
                raise ValueError(f"Missing prompt {prompt_id} for source row {source['id']}")
            prompt = prompts[prompt_id]
            expected_user = str(prompt["prompt"]).removesuffix(" <solution>")
            if source["messages"][0]["content"] != expected_user:
                raise ValueError(f"Source trace and generator prompt disagree for {source['id']}")
            gold = canonical_response(prompt)
            problem = str(prompt["problem"])
            oracle_report = grade_trajectory(gold, gold, problem=problem)
            if not oracle_report["perfect"]:
                raise ValueError(f"Canonical solution failed execution grading: {prompt_id}")
            report = grade_trajectory(gold, str(source["messages"][1]["content"]), problem=problem)
            allowed_extra_rows += int(bool(report["graph_report"]["allowed_extra_nodes"]))
            if not report["perfect"]:
                removed_for_operation += 1
                combination = "+".join(report["issue_codes"])
                issue_combinations[combination] += 1
                for code in report["issue_codes"]:
                    issue_code_rows[code] += 1
                continue

            row = {
                **source,
                "source_filter_mode": str(source["filter_mode"]),
                "filter_mode": "executable_strict",
                "executable_correct": True,
            }
            kept_rows.append(row)
            kept_for_operation += 1
            kept_prompt_ids.add(prompt_id)
            used_prompt_content_sha256.add(str(prompt["content_sha256"]))
            exact_examples.add(model_facing_digest(row))
            template_counts[str(row["template"])] += 1
            mode_counts[str(row["mode"])] += 1

        operation_stats[str(operation)] = {
            "source_rows": len(source_rows),
            "kept_rows": kept_for_operation,
            "removed_rows": removed_for_operation,
            "kept_fraction": kept_for_operation / len(source_rows),
            "kept_unique_prompts": len(kept_prompt_ids),
        }
        source_sha256_by_op[str(operation)] = file_sha256(accepted_path)
        prompt_sha256_by_op[str(operation)] = file_sha256(prompts_path)

    ids = [str(row["id"]) for row in kept_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Filtered trace IDs are not unique")
    if not kept_rows:
        raise ValueError("Execution grader removed every source row")

    dataset = Dataset.from_list(kept_rows)
    plan_args = SimpleNamespace(
        world_size=args.world_size,
        batch_size=batch_size,
        micro_batch_size=micro_batch_size,
        seq_len=args.seq_len,
    )
    training_plan = one_epoch_training_plan(dataset, plan_args)
    output_dir.mkdir(parents=True, exist_ok=False)
    dataset.to_parquet(output_path)

    lengths = [int(row["num_tokens"]) for row in kept_rows]
    source_row_count = expected_per_operation * len(operations)
    manifest = {
        "format": "prime-rl messages SFT parquet",
        "filter_definition": (
            "Released-verifier strict-correct model trajectories retained only when every written equality "
            "executes consistently and all graph nodes are canonical or exact prompt-defined constants"
        ),
        "chat_template": CHAT_TEMPLATE,
        "source_root": str(args.source_root.resolve()),
        "source_collection": collection_name,
        "operations": operations,
        "source_examples_per_operation": expected_per_operation,
        "source_rows": source_row_count,
        "rows": len(kept_rows),
        "removed_rows": source_row_count - len(kept_rows),
        "kept_fraction": len(kept_rows) / source_row_count,
        "operation_stats": operation_stats,
        "counts_by_template": dict(sorted(template_counts.items())),
        "counts_by_mode": dict(sorted(mode_counts.items())),
        "unique_prompts": len(used_prompt_content_sha256),
        "unique_model_facing_examples": len(exact_examples),
        "exact_duplicate_rows": len(kept_rows) - len(exact_examples),
        "allowed_prompt_constant_extra_rows": allowed_extra_rows,
        "removed_issue_code_rows": dict(sorted(issue_code_rows.items())),
        "removed_issue_combinations": dict(sorted(issue_combinations.items())),
        "source_accepted_sha256_by_op": source_sha256_by_op,
        "source_prompts_sha256_by_op": prompt_sha256_by_op,
        "used_prompt_content_sha256": sorted(used_prompt_content_sha256),
        "token_count_including_eos": sum(lengths),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "rows_over_seq_len": sum(length > args.seq_len for length in lengths),
        "seq_len": args.seq_len,
        "training_plan": training_plan,
        "parquet_sha256": file_sha256(output_path),
        "implementation_sha256": {
            "frontier_build_executable_dataset.py": file_sha256(Path(__file__)),
            "strict_trajectory_grader.py": file_sha256(Path(__file__).with_name("strict_trajectory_grader.py")),
            "solution_graph.py": file_sha256(Path(__file__).with_name("solution_graph.py")),
            "prepare_sft_data.py": file_sha256(Path(__file__).with_name("prepare_sft_data.py")),
        },
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest, used_prompt_content_sha256


def main() -> None:
    args = parse_args()
    if args.through_operation < args.start_operation:
        raise ValueError("through-operation must be >= start-operation")
    args.output_root.mkdir(parents=True, exist_ok=True)
    train_manifest, train_prompt_digests = build_split(
        args,
        "collection",
        args.train_examples_per_operation,
        args.output_root / "cumulative_dataset",
        args.batch_size,
        args.micro_batch_size,
    )
    gc.collect()
    validation_manifest, validation_prompt_digests = build_split(
        args,
        "validation_collection",
        args.validation_examples_per_operation,
        args.output_root / "cumulative_validation_dataset",
        args.validation_batch_size,
        args.validation_micro_batch_size,
    )
    overlap = train_prompt_digests & validation_prompt_digests
    if overlap:
        raise ValueError(f"Filtered training and validation data share {len(overlap)} prompt contents")
    audit = {
        "filter_definition": train_manifest["filter_definition"],
        "training_rows": train_manifest["rows"],
        "training_removed_rows": train_manifest["removed_rows"],
        "validation_rows": validation_manifest["rows"],
        "validation_removed_rows": validation_manifest["removed_rows"],
        "overlapping_prompt_contents": 0,
    }
    write_json(args.output_root / "held_out_audit.json", audit)
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
