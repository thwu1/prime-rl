#!/usr/bin/env python
"""Build answer-filtered SFT data with per-problem harmonic pass weights."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from datasets import Dataset
from prepare_sft_data import CHAT_TEMPLATE, one_epoch_training_plan, tokenize_lengths
from transformers import AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--operations", type=int, nargs="+", default=[11, 12, 13, 14])
    parser.add_argument("--examples-per-operation", type=int, default=200)
    parser.add_argument("--samples-per-prompt", type=int, default=128)
    parser.add_argument("--train-prompts-per-operation", type=int, default=160)
    parser.add_argument("--split-seed", type=int, default=20260803)
    parser.add_argument("--harmonic-k", type=int, nargs="+", default=[4, 8, 16, 32, 64])
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


def harmonic_weight(pass_rate: float, k: int) -> float:
    if not 0 <= pass_rate <= 1:
        raise ValueError(f"pass_rate must be in [0, 1], got {pass_rate}")
    if k < 1:
        raise ValueError(f"k must be positive, got {k}")
    harmonic_number = math.fsum(1.0 / j for j in range(1, k + 1))
    return math.fsum((1.0 - pass_rate) ** exponent for exponent in range(k)) / harmonic_number


def question_text(row: dict[str, Any]) -> str:
    return f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question>"


def normalize_assistant(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("<solution>"):
        normalized = f"<solution> {normalized}"
    if "<answer>" in normalized.lower() and "</answer>" not in normalized.lower():
        normalized = f"{normalized} </answer>"
    return normalized


def prompt_splits(args: argparse.Namespace) -> dict[tuple[int, int], str]:
    if not 0 < args.train_prompts_per_operation < args.examples_per_operation:
        raise ValueError("train-prompts-per-operation must be between 1 and examples-per-operation - 1")
    splits: dict[tuple[int, int], str] = {}
    for operation in args.operations:
        indices = list(range(args.examples_per_operation))
        random.Random(args.split_seed + operation).shuffle(indices)
        training = set(indices[: args.train_prompts_per_operation])
        for index in indices:
            splits[(operation, index)] = "train" if index in training else "validation"
    return splits


def source_prompts(args: argparse.Namespace) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, str]]:
    prompts: dict[tuple[int, int], dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for operation in args.operations:
        path = args.data_dir / f"op{operation}-{args.examples_per_operation}.jsonl"
        hashes[str(operation)] = file_sha256(path)
        rows = load_jsonl(path)
        if len(rows) != args.examples_per_operation:
            raise ValueError(f"Expected {args.examples_per_operation} prompts in {path}, found {len(rows)}")
        for index, row in enumerate(rows):
            if int(row["op"]) != operation:
                raise ValueError(f"Unexpected operation in {path} row {index}: {row['op']}")
            prompts[(operation, index)] = row
    return prompts, hashes


def load_joined_rollouts(
    args: argparse.Namespace,
) -> tuple[dict[tuple[int, int, int], dict[str, Any]], dict[tuple[int, int, int], dict[str, Any]]]:
    generation_rows = load_jsonl(args.generations)
    score_rows = load_jsonl(args.scores)
    if len(generation_rows) != len(score_rows):
        raise ValueError(f"Generation and score row counts differ: {len(generation_rows)} != {len(score_rows)}")

    generations: dict[tuple[int, int, int], dict[str, Any]] = {}
    scores: dict[tuple[int, int, int], dict[str, Any]] = {}
    for generation, score in zip(generation_rows, score_rows, strict=True):
        generation_identity = (int(generation["op"]), str(generation["id"]), int(generation["sample_rank"]))
        score_identity = (int(score["op"]), str(score["id"]), int(score["sample_rank"]))
        if generation_identity != score_identity:
            raise ValueError(f"Generation and score rows are misaligned: {generation_identity} != {score_identity}")
        key = (int(generation["op"]), int(generation["__idx"]), int(generation["sample_rank"]))
        if key in generations:
            raise ValueError(f"Duplicate generation key: {key}")
        generations[key] = generation
        scores[key] = score

    if generations.keys() != scores.keys():
        raise ValueError("Generation and score keys differ")
    return generations, scores


def validate_rollout_groups(
    args: argparse.Namespace,
    generations: dict[tuple[int, int, int], dict[str, Any]],
) -> None:
    ranks: dict[tuple[int, int], set[int]] = defaultdict(set)
    for operation, index, rank in generations:
        if operation in args.operations:
            ranks[(operation, index)].add(rank)
    expected_prompts = {
        (operation, index)
        for operation in args.operations
        for index in range(args.examples_per_operation)
    }
    if ranks.keys() != expected_prompts:
        raise ValueError("Rollout prompt keys differ from the requested prompt set")
    expected_ranks = set(range(args.samples_per_prompt))
    incomplete = [key for key, observed in ranks.items() if observed != expected_ranks]
    if incomplete:
        raise ValueError(f"Incomplete {args.samples_per_prompt}-rollout groups: {incomplete[:10]}")


def build_rows(
    args: argparse.Namespace,
    prompts: dict[tuple[int, int], dict[str, Any]],
    generations: dict[tuple[int, int, int], dict[str, Any]],
    scores: dict[tuple[int, int, int], dict[str, Any]],
    splits: dict[tuple[int, int], str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[int, int], int]]:
    correct_counts: Counter[tuple[int, int]] = Counter()
    for key, score in scores.items():
        if key[0] in args.operations and bool(score["answer_correct"]):
            correct_counts[(key[0], key[1])] += 1

    rows: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
    for key in sorted(generations):
        operation, index, rank = key
        if operation not in args.operations or not bool(scores[key]["answer_correct"]):
            continue
        prompt_key = (operation, index)
        prompt = prompts[prompt_key]
        pass_rate = correct_counts[prompt_key] / args.samples_per_prompt
        row = {
            "messages": [
                {"role": "user", "content": question_text(prompt)},
                {"role": "assistant", "content": normalize_assistant(str(generations[key]["gen_solution_answer"]))},
            ],
            "op": operation,
            "id": str(generations[key]["id"]),
            "prompt_index": index,
            "sample_rank": rank,
            "template": str(prompt["template"]),
            "mode": str(prompt.get("mode", "")),
            "answer_correct": True,
            "strict_correct": bool(scores[key]["perfect"]),
            "success_count": correct_counts[prompt_key],
            "rollout_count": args.samples_per_prompt,
            "pass_rate": pass_rate,
            "finish_reason": generations[key].get("finish_reason"),
        }
        for k in args.harmonic_k:
            row[f"harmonic_weight_k{k}"] = harmonic_weight(pass_rate, k)
        rows[splits[prompt_key]].append(row)
    return rows, dict(correct_counts)


def split_manifest(
    args: argparse.Namespace,
    split: str,
    rows: list[dict[str, Any]],
    prompt_keys: list[tuple[int, int]],
    output_path: Path,
    training_plan: dict[str, Any],
) -> dict[str, Any]:
    counts_by_op = Counter(int(row["op"]) for row in rows)
    weights = {
        f"harmonic_weight_k{k}": {
            "min": min(float(row[f"harmonic_weight_k{k}"]) for row in rows),
            "max": max(float(row[f"harmonic_weight_k{k}"]) for row in rows),
            "mean": math.fsum(float(row[f"harmonic_weight_k{k}"]) for row in rows) / len(rows),
        }
        for k in args.harmonic_k
    }
    return {
        "format": "prime-rl messages SFT parquet with scalar example weights",
        "split": split,
        "filter": "final-answer correct",
        "chat_template": CHAT_TEMPLATE,
        "operations": args.operations,
        "samples_per_prompt": args.samples_per_prompt,
        "rows": len(rows),
        "prompts": len(prompt_keys),
        "solved_prompts": len({(int(row["op"]), int(row["prompt_index"])) for row in rows}),
        "counts_by_op": {str(key): value for key, value in sorted(counts_by_op.items())},
        "strict_correct_rows": sum(bool(row["strict_correct"]) for row in rows),
        "token_count_including_eos": sum(int(row["num_tokens"]) for row in rows),
        "min_tokens": min(int(row["num_tokens"]) for row in rows),
        "max_tokens": max(int(row["num_tokens"]) for row in rows),
        "weight_formula": "sum((1 - p) ** j for j in range(K)) / H_K; p = answer_correct_count / 128",
        "weight_columns": weights,
        "prompt_keys": [f"{operation}:{index}" for operation, index in sorted(prompt_keys)],
        "training_plan": training_plan,
        "parquet_sha256": file_sha256(output_path),
    }


def write_split(
    args: argparse.Namespace,
    split: str,
    rows: list[dict[str, Any]],
    prompt_keys: list[tuple[int, int]],
    output_dir: Path,
) -> dict[str, Any]:
    output_path = output_dir / "train-00000-of-00001.parquet"
    if output_dir.exists():
        raise FileExistsError(f"Output split already exists: {output_dir}")
    dataset = Dataset.from_list(rows)
    plan_args = SimpleNamespace(
        world_size=args.world_size,
        batch_size=args.batch_size if split == "train" else args.validation_batch_size,
        micro_batch_size=args.micro_batch_size if split == "train" else args.validation_micro_batch_size,
        seq_len=args.seq_len,
    )
    training_plan = one_epoch_training_plan(dataset, plan_args)
    output_dir.mkdir(parents=True)
    dataset.to_parquet(output_path)
    manifest = split_manifest(args, split, rows, prompt_keys, output_path, training_plan)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    args = parse_args()
    if len(args.operations) != len(set(args.operations)):
        raise ValueError("operations contains duplicates")
    if len(args.harmonic_k) != len(set(args.harmonic_k)):
        raise ValueError("harmonic-k contains duplicates")
    if args.samples_per_prompt != 128:
        raise ValueError("This experiment requires exactly 128 rollouts per prompt")
    if args.output_root.exists():
        raise FileExistsError(f"Output root already exists: {args.output_root}")

    prompts, prompt_hashes = source_prompts(args)
    generations, scores = load_joined_rollouts(args)
    validate_rollout_groups(args, generations)
    splits = prompt_splits(args)
    rows, correct_counts = build_rows(args, prompts, generations, scores, splits)

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    for split_rows in rows.values():
        lengths = tokenize_lengths(tokenizer, split_rows)
        for row, length in zip(split_rows, lengths, strict=True):
            row["num_tokens"] = length
    overlength = {
        split: [row for row in split_rows if int(row["num_tokens"]) > args.seq_len]
        for split, split_rows in rows.items()
    }
    if any(overlength.values()):
        details = {split: len(split_rows) for split, split_rows in overlength.items()}
        raise ValueError(f"Answer-correct rows exceed seq_len={args.seq_len}: {details}")

    train_prompts = [key for key, split in splits.items() if split == "train"]
    validation_prompts = [key for key, split in splits.items() if split == "validation"]
    args.output_root.mkdir(parents=True)
    train_manifest = write_split(args, "train", rows["train"], train_prompts, args.output_root / "train")
    validation_manifest = write_split(
        args,
        "validation",
        rows["validation"],
        validation_prompts,
        args.output_root / "validation",
    )
    summary = {
        "source_generations": str(args.generations.resolve()),
        "source_generations_sha256": file_sha256(args.generations),
        "source_scores": str(args.scores.resolve()),
        "source_scores_sha256": file_sha256(args.scores),
        "source_prompt_sha256_by_op": prompt_hashes,
        "split_seed": args.split_seed,
        "train_prompts_per_operation": args.train_prompts_per_operation,
        "validation_prompts_per_operation": args.examples_per_operation - args.train_prompts_per_operation,
        "samples_per_prompt": args.samples_per_prompt,
        "correct_rollouts": sum(correct_counts.values()),
        "correct_rollouts_by_op": {
            str(operation): sum(count for (op, _), count in correct_counts.items() if op == operation)
            for operation in args.operations
        },
        "training_rows": train_manifest["rows"],
        "validation_rows": validation_manifest["rows"],
        "overlapping_prompt_keys": 0,
        "harmonic_k": args.harmonic_k,
        "implementation_sha256": file_sha256(Path(__file__)),
    }
    write_json(args.output_root / "manifest.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
