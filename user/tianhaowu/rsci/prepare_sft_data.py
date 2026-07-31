#!/usr/bin/env python
"""Convert released Interplay composition JSONL files into a prime-rl SFT dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from datasets import Dataset
from transformers import AutoTokenizer

CHAT_TEMPLATE = (
    """{% for message in messages %}{{ message['content'] }}{% if not loop.last %} {% endif %}{% endfor %}"""
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--operations", type=int, nargs="+", default=[11, 12, 13, 14])
    parser.add_argument("--examples-per-operation", type=int, default=50_000)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--seq-len", type=int, default=2048)
    parser.add_argument("--world-size", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--micro-batch-size", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def split_solution(solution: str) -> tuple[str, str]:
    if "Answer:" not in solution:
        raise ValueError("Solution does not contain an Answer: marker")
    body, answer = solution.rsplit("Answer:", 1)
    answer = answer.strip().splitlines()[0].strip().rstrip(".")
    if not body.strip() or not answer:
        raise ValueError("Solution body or answer is empty")
    return body.strip(), answer


def convert_row(row: dict[str, Any]) -> dict[str, Any]:
    problem = str(row["problem"]).strip()
    question = str(row["question"]).strip()
    solution_body, answer = split_solution(str(row["solution"]).strip())
    prompt = f"<question> {problem} {question} </question>"
    completion = f"<solution> {solution_body} </solution> <answer> {answer} </answer>"
    return {
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ],
        "op": int(row["op"]),
        "id": str(row["id"]),
        "template": str(row["template"]),
        "mode": str(row["mode"]),
    }


def tokenize_lengths(tokenizer: Any, rows: list[dict[str, Any]], batch_size: int = 1024) -> list[int]:
    lengths: list[int] = []
    for start in range(0, len(rows), batch_size):
        conversations = [row["messages"] for row in rows[start : start + batch_size]]
        tokenized = tokenizer.apply_chat_template(
            conversations,
            chat_template=CHAT_TEMPLATE,
            tokenize=True,
            add_generation_prompt=False,
            padding=False,
            return_dict=True,
        )
        lengths.extend(len(tokens) + 1 for tokens in tokenized["input_ids"])
    return lengths


def one_epoch_training_plan(dataset: Dataset, args: argparse.Namespace) -> dict[str, Any]:
    denominator = args.world_size * args.micro_batch_size
    if args.batch_size % denominator:
        raise ValueError("batch-size must be divisible by world-size * micro-batch-size")
    shuffled_lengths = list(dataset.shuffle(seed=0)["num_tokens"])
    packed_tokens = args.seq_len * args.micro_batch_size
    packed_micro_batches_by_rank: list[int] = []
    for rank in range(args.world_size):
        accumulated = 0
        packed_micro_batches = 0
        for length in shuffled_lengths[rank :: args.world_size]:
            accumulated += int(length) - 1
            if accumulated >= packed_tokens:
                packed_micro_batches += 1
                accumulated = 0
        if accumulated:
            packed_micro_batches += 1
        packed_micro_batches_by_rank.append(packed_micro_batches)
    grad_accumulation_steps = args.batch_size // denominator
    return {
        "world_size": args.world_size,
        "batch_size": args.batch_size,
        "micro_batch_size": args.micro_batch_size,
        "seq_len": args.seq_len,
        "global_tokens_per_step": args.batch_size * args.seq_len,
        "grad_accumulation_steps": grad_accumulation_steps,
        "packed_micro_batches_by_rank": packed_micro_batches_by_rank,
        "optimizer_steps_for_one_epoch": max(
            math.ceil(count / grad_accumulation_steps) for count in packed_micro_batches_by_rank
        ),
    }


def main() -> None:
    args = parse_args()
    output_path = args.output_dir / "train-00000-of-00001.parquet"
    manifest_path = args.output_dir / "manifest.json"
    existing = [path for path in (output_path, manifest_path) if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(f"SFT outputs already exist: {existing}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        output_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)

    rows: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for operation in args.operations:
        path = args.input_dir / f"op{operation}-{args.examples_per_operation // 1000}k.jsonl"
        raw = path.read_bytes()
        source_hashes[str(operation)] = hashlib.sha256(raw).hexdigest()
        operation_rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(operation_rows) != args.examples_per_operation:
            raise ValueError(f"Expected {args.examples_per_operation} rows in {path}, found {len(operation_rows)}")
        rows.extend(convert_row(row) for row in operation_rows)

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    lengths = tokenize_lengths(tokenizer, rows)
    for row, length in zip(rows, lengths, strict=True):
        row["num_tokens"] = length
    dataset = Dataset.from_list(rows)
    training_plan = one_epoch_training_plan(dataset, args)
    dataset.to_parquet(output_path)
    counts_by_op = Counter(row["op"] for row in rows)
    counts_by_template = Counter(row["template"] for row in rows)
    counts_by_mode = Counter(row["mode"] for row in rows)
    manifest = {
        "format": "prime-rl messages SFT parquet",
        "chat_template": CHAT_TEMPLATE,
        "input_dir": str(args.input_dir.resolve()),
        "source_sha256_by_op": source_hashes,
        "operations": args.operations,
        "rows": len(rows),
        "counts_by_op": dict(sorted(counts_by_op.items())),
        "counts_by_template": dict(sorted(counts_by_template.items())),
        "counts_by_mode": dict(sorted(counts_by_mode.items())),
        "tokenizer": args.tokenizer,
        "token_count_including_eos": sum(lengths),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "rows_over_seq_len": sum(length > args.seq_len for length in lengths),
        "seq_len": args.seq_len,
        "training_plan": training_plan,
        "parquet_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
