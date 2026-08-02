#!/usr/bin/env python
"""Build matched GSM-Infinite oracle SFT data from frontier prompt multisets."""

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
from generate import SOURCE_COMMIT, SOURCE_REPOSITORY
from prepare_sft_data import (
    CHAT_TEMPLATE,
    one_epoch_training_plan,
    split_solution,
    tokenize_lengths,
)
from transformers import AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tokenizer", required=True)
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_messages(prompt: dict[str, Any], source: dict[str, Any]) -> list[dict[str, str]]:
    solution_body, answer = split_solution(str(prompt["solution"]).strip())
    if answer != str(prompt["answer"]):
        raise ValueError(f"Generator solution and answer disagree for {prompt['id']}")

    expected_user = str(prompt["prompt"]).removesuffix(" <solution>")
    source_messages = source["messages"]
    if [message["role"] for message in source_messages] != ["user", "assistant"]:
        raise ValueError(f"Unexpected source message roles for {source['id']}")
    if source_messages[0]["content"] != expected_user:
        raise ValueError(f"Source trace and generator prompt disagree for {source['id']}")

    assistant = f"<solution> {solution_body} </solution> <answer> {answer} </answer>"
    if assistant != f"<solution> {prompt['completion']}":
        raise ValueError(f"Stored completion and generator solution disagree for {prompt['id']}")
    return [
        {"role": "user", "content": expected_user},
        {"role": "assistant", "content": assistant},
    ]


def oracle_id(source_trace_id: str, prompt_id: str) -> str:
    material = f"matched-gsm-infinite-oracle-v1\0{source_trace_id}\0{prompt_id}"
    return f"oracle_{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def build_split(
    args: argparse.Namespace,
    tokenizer: Any,
    collection_name: str,
    examples_per_operation: int,
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
        raise FileExistsError(f"Incomplete oracle dataset directory already exists: {output_dir}")

    operations = list(range(args.start_operation, args.through_operation + 1))
    rows: list[dict[str, Any]] = []
    source_accepted_sha256_by_op: dict[str, str] = {}
    source_prompts_sha256_by_op: dict[str, str] = {}
    unique_prompts_by_op: dict[str, int] = {}
    used_prompt_content_sha256: set[str] = set()
    exact_examples: set[str] = set()

    for operation in operations:
        collection_dir = args.source_root / "iterations" / f"op{operation}" / collection_name
        accepted_path = collection_dir / "accepted.jsonl"
        prompts_path = collection_dir / "prompts.jsonl"
        source_rows = load_jsonl(accepted_path)
        if len(source_rows) != examples_per_operation:
            raise ValueError(
                f"Expected {examples_per_operation} source rows in {accepted_path}, found {len(source_rows)}"
            )
        source_ids = [str(row["id"]) for row in source_rows]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(f"Source trace IDs are not unique in {accepted_path}")

        prompts = {str(row["id"]): row for row in load_jsonl(prompts_path)}
        if len(prompts) == 0:
            raise ValueError(f"No generator prompts found in {prompts_path}")
        representative_by_prompt_id: dict[str, dict[str, Any]] = {}
        for source_row in source_rows:
            representative_by_prompt_id.setdefault(str(source_row["prompt_id"]), source_row)
        used_prompt_ids = set(representative_by_prompt_id)
        missing_prompt_ids = used_prompt_ids - prompts.keys()
        if missing_prompt_ids:
            raise ValueError(f"{len(missing_prompt_ids)} source prompts are missing from {prompts_path}")

        messages_by_prompt_id = {
            prompt_id: canonical_messages(prompts[prompt_id], representative_by_prompt_id[prompt_id])
            for prompt_id in sorted(used_prompt_ids)
        }
        token_rows = [{"messages": messages_by_prompt_id[prompt_id]} for prompt_id in sorted(used_prompt_ids)]
        lengths = tokenize_lengths(tokenizer, token_rows)
        length_by_prompt_id = dict(zip(sorted(used_prompt_ids), lengths, strict=True))
        overlength = [prompt_id for prompt_id, length in length_by_prompt_id.items() if length > args.seq_len]
        if overlength:
            raise ValueError(
                f"{len(overlength)} canonical oracle examples for op{operation} exceed seq_len={args.seq_len}"
            )

        for prompt_id, messages in messages_by_prompt_id.items():
            used_prompt_content_sha256.add(str(prompts[prompt_id]["content_sha256"]))
            exact_examples.add(
                hashlib.sha256(
                    json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()
                ).hexdigest()
            )

        for source in source_rows:
            if int(source["op"]) != operation:
                raise ValueError(f"Unexpected operation {source['op']} in {accepted_path}")
            prompt_id = str(source["prompt_id"])
            prompt = prompts[prompt_id]
            if int(prompt["op"]) != operation:
                raise ValueError(f"Unexpected prompt operation {prompt['op']} in {prompts_path}")
            messages = messages_by_prompt_id[prompt_id]
            if source["messages"][0] != messages[0]:
                raise ValueError(f"Source trace and canonical oracle user message disagree for {source['id']}")
            row = {
                "id": oracle_id(str(source["id"]), prompt_id),
                "source_trace_id": str(source["id"]),
                "prompt_id": prompt_id,
                "messages": messages,
                "op": operation,
                "template": str(prompt["template"]),
                "mode": str(prompt["mode"]),
                "num_tokens": length_by_prompt_id[prompt_id],
                "answer_correct": True,
                "strict_correct": True,
                "filter_mode": "oracle",
                "source_model": f"{SOURCE_REPOSITORY}@{SOURCE_COMMIT}",
            }
            rows.append(row)

        unique_prompts_by_op[str(operation)] = len(used_prompt_ids)
        source_accepted_sha256_by_op[str(operation)] = file_sha256(accepted_path)
        source_prompts_sha256_by_op[str(operation)] = file_sha256(prompts_path)

    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Oracle row IDs are not unique")
    dataset = Dataset.from_list(rows)
    plan_args = SimpleNamespace(
        world_size=args.world_size,
        batch_size=batch_size,
        micro_batch_size=micro_batch_size,
        seq_len=args.seq_len,
    )
    training_plan = one_epoch_training_plan(dataset, plan_args)
    output_dir.mkdir(parents=True, exist_ok=False)
    dataset.to_parquet(output_path)

    lengths = [int(row["num_tokens"]) for row in rows]
    counts_by_op = Counter(int(row["op"]) for row in rows)
    counts_by_template = Counter(str(row["template"]) for row in rows)
    counts_by_mode = Counter(str(row["mode"]) for row in rows)
    manifest = {
        "format": "prime-rl messages SFT parquet",
        "oracle_definition": (
            "Exact strict-filter source-row multiset with every sampled assistant trajectory replaced by the "
            "GSM-Infinite generator's canonical solution and answer"
        ),
        "canonical_format_reference": "prepare_sft_data.py::convert_row",
        "chat_template": CHAT_TEMPLATE,
        "source_root": str(args.source_root.resolve()),
        "source_collection": collection_name,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT,
        "operations": operations,
        "examples_per_operation": examples_per_operation,
        "rows": len(rows),
        "counts_by_op": dict(sorted(counts_by_op.items())),
        "counts_by_template": dict(sorted(counts_by_template.items())),
        "counts_by_mode": dict(sorted(counts_by_mode.items())),
        "unique_prompts": sum(unique_prompts_by_op.values()),
        "unique_prompts_by_op": unique_prompts_by_op,
        "unique_model_facing_examples": len(exact_examples),
        "exact_duplicate_rows": len(rows) - len(exact_examples),
        "source_row_multiplicities_preserved": True,
        "answer_correct_rows": len(rows),
        "strict_correct_rows": len(rows),
        "source_accepted_sha256_by_op": source_accepted_sha256_by_op,
        "source_prompts_sha256_by_op": source_prompts_sha256_by_op,
        "used_prompt_content_sha256": sorted(used_prompt_content_sha256),
        "tokenizer": args.tokenizer,
        "token_count_including_eos": sum(lengths),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "rows_over_seq_len": sum(length > args.seq_len for length in lengths),
        "seq_len": args.seq_len,
        "training_plan": training_plan,
        "parquet_sha256": file_sha256(output_path),
        "implementation_sha256": {
            "frontier_build_oracle_dataset.py": file_sha256(Path(__file__)),
            "generate.py": file_sha256(Path(__file__).with_name("generate.py")),
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
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)

    train_manifest, train_prompt_digests = build_split(
        args,
        tokenizer,
        "collection",
        args.train_examples_per_operation,
        args.output_root / "cumulative_dataset",
        args.batch_size,
        args.micro_batch_size,
    )
    gc.collect()
    validation_manifest, validation_prompt_digests = build_split(
        args,
        tokenizer,
        "validation_collection",
        args.validation_examples_per_operation,
        args.output_root / "cumulative_validation_dataset",
        args.validation_batch_size,
        args.validation_micro_batch_size,
    )
    overlap = train_prompt_digests & validation_prompt_digests
    if overlap:
        raise ValueError(f"Oracle training and validation data share {len(overlap)} prompt contents")

    audit = {
        "oracle_definition": train_manifest["oracle_definition"],
        "training_manifest": str((args.output_root / "cumulative_dataset" / "manifest.json").resolve()),
        "validation_manifest": str(
            (args.output_root / "cumulative_validation_dataset" / "manifest.json").resolve()
        ),
        "training_rows": train_manifest["rows"],
        "validation_rows": validation_manifest["rows"],
        "training_unique_prompts": train_manifest["unique_prompts"],
        "validation_unique_prompts": validation_manifest["unique_prompts"],
        "overlapping_prompt_contents": 0,
    }
    write_json(args.output_root / "held_out_audit.json", audit)
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
