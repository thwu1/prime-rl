#!/usr/bin/env python
"""Collect self-generated GSM-Infinite traces for one frontier operation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO

from generate import CONTEXTS, MODES, GenerationTask, generate_result, make_row
from openai import AsyncOpenAI
from prepare_sft_data import CHAT_TEMPLATE
from solution_graph import compare_solutions
from transformers import AutoTokenizer

ANSWER_RE = re.compile(r"<answer>\s*([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)
FILTER_MODES = {"answer", "strict"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
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


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    eval_config = config["eval"]
    required = {
        "operation",
        "filter_mode",
        "target_accepted",
        "max_prompts",
        "prompt_batch_size",
        "prompt_seed",
        "output_dir",
        "model",
        "tokenizer",
        "api_base_url",
        "samples_per_prompt",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stop",
        "skip_special_tokens",
        "request_timeout_seconds",
        "max_concurrent_prompts",
        "seq_len",
    }
    missing = sorted(required - eval_config.keys())
    if missing:
        raise ValueError(f"Missing frontier collection fields: {missing}")
    if eval_config["filter_mode"] not in FILTER_MODES:
        raise ValueError(f"eval.filter_mode must be one of {sorted(FILTER_MODES)}")
    for name in ("target_accepted", "max_prompts", "prompt_batch_size", "samples_per_prompt", "seq_len"):
        if int(eval_config[name]) < 1:
            raise ValueError(f"eval.{name} must be positive")
    if int(eval_config["samples_per_prompt"]) != 128:
        raise ValueError("Frontier collection protocol requires samples_per_prompt=128")
    if int(eval_config["prompt_batch_size"]) > int(eval_config["max_concurrent_prompts"]):
        raise ValueError("prompt_batch_size cannot exceed max_concurrent_prompts")
    return config


def question_text(row: dict[str, Any]) -> str:
    return f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question>"


def completion_prompt(row: dict[str, Any]) -> str:
    return f"{question_text(row)} <solution>"


def normalize_assistant(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("<solution>"):
        normalized = f"<solution> {normalized}"
    if "<answer>" in normalized.lower() and "</answer>" not in normalized.lower():
        normalized = f"{normalized} </answer>"
    return normalized


def token_lengths(tokenizer: Any, row: dict[str, Any], assistants: list[str]) -> list[int]:
    conversations = [
        [
            {"role": "user", "content": question_text(row)},
            {"role": "assistant", "content": assistant},
        ]
        for assistant in assistants
    ]
    tokenized = tokenizer.apply_chat_template(
        conversations,
        chat_template=CHAT_TEMPLATE,
        tokenize=True,
        add_generation_prompt=False,
        padding=False,
        return_dict=True,
    )
    return [len(tokens) + 1 for tokens in tokenized["input_ids"]]


def load_prompts(path: Path) -> dict[int, dict[str, Any]]:
    prompts: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return prompts
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            prompt_index = int(row["prompt_index"])
            if prompt_index in prompts:
                raise ValueError(f"Duplicate prompt_index in {path}:{line_number}: {prompt_index}")
            prompts[prompt_index] = row
    if prompts and sorted(prompts) != list(range(max(prompts) + 1)):
        raise ValueError(f"Prompt indices are not contiguous in {path}")
    return prompts


def load_generations(
    path: Path,
    samples_per_prompt: int,
    filter_mode: str,
    prompt_indices: set[int],
) -> tuple[dict[int, set[int]], list[dict[str, Any]]]:
    completed: dict[int, set[int]] = defaultdict(set)
    accepted: list[dict[str, Any]] = []
    if not path.exists():
        return completed, accepted
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            prompt_index = int(record["prompt_index"])
            if prompt_index not in prompt_indices:
                raise ValueError(f"Unknown prompt_index in {path}:{line_number}: {prompt_index}")
            sample_rank = int(record["sample_rank"])
            if not 0 <= sample_rank < samples_per_prompt:
                raise ValueError(f"Invalid sample rank in {path}:{line_number}: {sample_rank}")
            if sample_rank in completed[prompt_index]:
                raise ValueError(f"Duplicate generation in {path}:{line_number}")
            completed[prompt_index].add(sample_rank)
            if record[f"{filter_mode}_correct"] and record["trainable"]:
                accepted.append(record)
    return completed, accepted


def generation_cell(prompt_index: int) -> tuple[str, str, int]:
    cells = [(context, mode) for context in sorted(CONTEXTS) for mode in sorted(MODES)]
    context, mode = cells[prompt_index % len(cells)]
    return context, mode, prompt_index // len(cells)


def generate_prompt(
    prompt_index: int,
    eval_config: dict[str, Any],
    existing_digests: set[str],
    quiet_output: TextIO,
) -> dict[str, Any]:
    context, mode, cell_index = generation_cell(prompt_index)
    task = GenerationTask(
        split=f"frontier-op{int(eval_config['operation'])}",
        op=int(eval_config["operation"]),
        context=context,
        mode=mode,
        index=cell_index,
    )
    generator_args = SimpleNamespace(
        seed=int(eval_config["prompt_seed"]),
        generator_op_max=eval_config.get("generator_op_max"),
        number_range=int(eval_config.get("number_range", 5)),
        depth=int(eval_config.get("depth", 2)),
        id_max_op=int(eval_config.get("id_max_op", 10)),
    )
    for attempt in range(int(eval_config.get("max_attempts_per_prompt", 10_000))):
        try:
            result = generate_result(task, generator_args, attempt, quiet_output)
            row, digest = make_row(result, task, generator_args.depth, generator_args.id_max_op)
        except (AssertionError, IndexError, OverflowError, ValueError, ZeroDivisionError):
            continue
        if digest in existing_digests:
            continue
        existing_digests.add(digest)
        row["prompt_index"] = prompt_index
        row["generation_attempt"] = attempt
        row["content_sha256"] = digest
        return row
    raise RuntimeError(f"Could not generate prompt_index={prompt_index}")


async def request_completions(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    row: dict[str, Any],
    missing_ranks: list[int],
    eval_config: dict[str, Any],
) -> tuple[dict[str, Any], list[int], list[tuple[str, str | None]]]:
    async with semaphore:
        response = await client.completions.create(
            model=eval_config["model"],
            prompt=completion_prompt(row),
            n=len(missing_ranks),
            max_tokens=int(eval_config["max_tokens"]),
            temperature=float(eval_config["temperature"]),
            top_p=float(eval_config["top_p"]),
            stop=eval_config["stop"],
            extra_body={
                "skip_special_tokens": bool(eval_config["skip_special_tokens"]),
                "top_k": int(eval_config["top_k"]),
            },
        )
    choices = sorted(response.choices, key=lambda choice: choice.index)
    if len(choices) != len(missing_ranks):
        raise RuntimeError(
            f"Server returned {len(choices)} samples for prompt_index={row['prompt_index']}; "
            f"expected {len(missing_ranks)}"
        )
    return row, missing_ranks, [(choice.text, choice.finish_reason) for choice in choices]


def score_batch(
    tokenizer: Any,
    row: dict[str, Any],
    ranks: list[int],
    completions: list[tuple[str, str | None]],
    eval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    assistants = [normalize_assistant(text) for text, _ in completions]
    lengths = token_lengths(tokenizer, row, assistants)
    gold_answer = float(row["answer"])
    records: list[dict[str, Any]] = []
    for rank, (raw_text, finish_reason), assistant, length in zip(ranks, completions, assistants, lengths, strict=True):
        answer_match = ANSWER_RE.search(raw_text)
        predicted_answer = float(answer_match.group(1)) if answer_match else None
        answer_correct = predicted_answer == gold_answer
        report = compare_solutions(str(row["solution"]), raw_text)
        records.append(
            {
                "prompt_index": int(row["prompt_index"]),
                "prompt_id": str(row["id"]),
                "sample_rank": rank,
                "finish_reason": finish_reason,
                "raw_completion": raw_text,
                "assistant": assistant,
                "predicted_answer": predicted_answer,
                "answer_correct": answer_correct,
                "strict_correct": bool(report["perfect"]),
                "trainable": length <= int(eval_config["seq_len"]),
                "num_tokens": length,
                "value_mismatch_count": len(report["value_mismatches"]),
                "dependency_mismatch_count": len(report["dependency_mismatches"]),
                "missing_nodes": len(report["missing_in_pred"]),
                "extra_nodes": len(report["extra_in_pred"]),
                "answer_mismatch": report["answer_mismatch"] is not None,
            }
        )
    return records


def accepted_row(
    prompt: dict[str, Any],
    generation: dict[str, Any],
    eval_config: dict[str, Any],
) -> dict[str, Any]:
    trace_material = f"{prompt['id']}\0{generation['sample_rank']}\0{generation['assistant']}"
    trace_hash = hashlib.sha256(trace_material.encode()).hexdigest()
    return {
        "messages": [
            {"role": "user", "content": question_text(prompt)},
            {"role": "assistant", "content": generation["assistant"]},
        ],
        "num_tokens": int(generation["num_tokens"]),
        "op": int(eval_config["operation"]),
        "id": f"frontier_{trace_hash[:24]}",
        "prompt_id": str(prompt["id"]),
        "prompt_index": int(prompt["prompt_index"]),
        "sample_rank": int(generation["sample_rank"]),
        "template": str(prompt["template"]),
        "mode": str(prompt["mode"]),
        "filter_mode": str(eval_config["filter_mode"]),
        "answer_correct": bool(generation["answer_correct"]),
        "strict_correct": bool(generation["strict_correct"]),
        "value_mismatch_count": int(generation["value_mismatch_count"]),
        "dependency_mismatch_count": int(generation["dependency_mismatch_count"]),
        "missing_nodes": int(generation["missing_nodes"]),
        "extra_nodes": int(generation["extra_nodes"]),
        "answer_mismatch": bool(generation["answer_mismatch"]),
        "finish_reason": generation["finish_reason"],
        "source_model": str(eval_config["model"]),
    }


def summarize_generations(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            counts["total"] += 1
            for field in ("answer_correct", "strict_correct", "trainable"):
                counts[field] += bool(record[field])
            counts["answer_correct_trainable"] += bool(record["answer_correct"] and record["trainable"])
            counts["strict_correct_trainable"] += bool(record["strict_correct"] and record["trainable"])
            finish_reasons[str(record["finish_reason"])] += 1
    return {**dict(sorted(counts.items())), "finish_reasons": dict(sorted(finish_reasons.items()))}


async def collect(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    prompts_path = output_dir / "prompts.jsonl"
    generations_path = output_dir / "generations.jsonl"
    accepted_path = output_dir / "accepted.jsonl"
    manifest_path = output_dir / "manifest.json"
    progress_path = output_dir / "progress.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    prompts = load_prompts(prompts_path)
    existing_digests = {str(row["content_sha256"]) for row in prompts.values()}
    samples_per_prompt = int(eval_config["samples_per_prompt"])
    completed, accepted = load_generations(
        generations_path,
        samples_per_prompt,
        str(eval_config["filter_mode"]),
        set(prompts),
    )
    target = int(eval_config["target_accepted"])
    tokenizer = AutoTokenizer.from_pretrained(str(eval_config["tokenizer"]), local_files_only=True)
    client = AsyncOpenAI(
        base_url=str(eval_config["api_base_url"]),
        api_key="unused",
        timeout=float(eval_config["request_timeout_seconds"]),
        max_retries=int(eval_config.get("max_retries", 2)),
    )
    semaphore = asyncio.Semaphore(int(eval_config["max_concurrent_prompts"]))
    prompt_mode = "a" if prompts_path.exists() else "w"
    generation_mode = "a" if generations_path.exists() else "w"
    try:
        with (
            prompts_path.open(prompt_mode, encoding="utf-8") as prompt_output,
            generations_path.open(generation_mode, encoding="utf-8") as generation_output,
            open(os.devnull, "w", encoding="utf-8") as quiet_output,
        ):
            while len(accepted) < target:
                incomplete = [index for index in sorted(prompts) if len(completed[index]) < samples_per_prompt]
                batch_indices = incomplete[: int(eval_config["prompt_batch_size"])]
                while len(batch_indices) < int(eval_config["prompt_batch_size"]):
                    prompt_index = len(prompts)
                    if prompt_index >= int(eval_config["max_prompts"]):
                        raise RuntimeError(
                            f"Reached max_prompts={eval_config['max_prompts']} with "
                            f"{len(accepted)}/{target} accepted traces"
                        )
                    row = generate_prompt(prompt_index, eval_config, existing_digests, quiet_output)
                    prompts[prompt_index] = row
                    completed[prompt_index] = set()
                    prompt_output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    prompt_output.flush()
                    batch_indices.append(prompt_index)

                tasks = []
                for prompt_index in batch_indices:
                    missing = sorted(set(range(samples_per_prompt)) - completed[prompt_index])
                    tasks.append(request_completions(client, semaphore, prompts[prompt_index], missing, eval_config))
                responses = await asyncio.gather(*tasks)
                for row, ranks, completions in responses:
                    records = score_batch(tokenizer, row, ranks, completions, eval_config)
                    for record in records:
                        generation_output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                        completed[int(record["prompt_index"])].add(int(record["sample_rank"]))
                        if record[f"{eval_config['filter_mode']}_correct"] and record["trainable"]:
                            accepted.append(record)
                    generation_output.flush()
                progress = {
                    "operation": int(eval_config["operation"]),
                    "filter_mode": str(eval_config["filter_mode"]),
                    "target_accepted": target,
                    "accepted": len(accepted),
                    "prompts": len(prompts),
                    "generations": sum(len(ranks) for ranks in completed.values()),
                }
                write_json(progress_path, progress)
                print(json.dumps(progress, sort_keys=True), flush=True)
    finally:
        await client.close()

    selected = sorted(accepted, key=lambda row: (int(row["prompt_index"]), int(row["sample_rank"])))[:target]
    accepted_partial = accepted_path.with_suffix(".jsonl.partial")
    with accepted_partial.open("w", encoding="utf-8") as output:
        for generation in selected:
            prompt = prompts[int(generation["prompt_index"])]
            output.write(
                json.dumps(accepted_row(prompt, generation, eval_config), ensure_ascii=False, sort_keys=True) + "\n"
            )
    accepted_partial.replace(accepted_path)
    prompt_counts_by_template = Counter(str(row["template"]) for row in prompts.values())
    prompt_counts_by_mode = Counter(str(row["mode"]) for row in prompts.values())
    accepted_counts_by_template = Counter(
        str(prompts[int(generation["prompt_index"])]["template"]) for generation in selected
    )
    accepted_counts_by_mode = Counter(str(prompts[int(generation["prompt_index"])]["mode"]) for generation in selected)
    manifest = {
        "config": str(config_path.resolve()),
        "config_sha256": file_sha256(config_path),
        "operation": int(eval_config["operation"]),
        "filter_mode": str(eval_config["filter_mode"]),
        "source_model": str(eval_config["model"]),
        "target_accepted": target,
        "accepted": target,
        "accepted_strict": sum(bool(row["strict_correct"]) for row in selected),
        "accepted_answer": sum(bool(row["answer_correct"]) for row in selected),
        "prompts_generated": len(prompts),
        "generations": sum(len(ranks) for ranks in completed.values()),
        "generation_counts": summarize_generations(generations_path),
        "prompt_counts_by_template": dict(sorted(prompt_counts_by_template.items())),
        "prompt_counts_by_mode": dict(sorted(prompt_counts_by_mode.items())),
        "accepted_counts_by_template": dict(sorted(accepted_counts_by_template.items())),
        "accepted_counts_by_mode": dict(sorted(accepted_counts_by_mode.items())),
        "samples_per_prompt": samples_per_prompt,
        "sampling": {
            "temperature": eval_config["temperature"],
            "top_p": eval_config["top_p"],
            "top_k": eval_config["top_k"],
            "max_tokens": eval_config["max_tokens"],
            "stop": eval_config["stop"],
        },
        "prompt_sha256": file_sha256(prompts_path),
        "generations_sha256": file_sha256(generations_path),
        "accepted_sha256": file_sha256(accepted_path),
        "implementation_sha256": {
            "frontier_collect.py": file_sha256(Path(__file__)),
            "generate.py": file_sha256(Path(__file__).with_name("generate.py")),
            "prepare_sft_data.py": file_sha256(Path(__file__).with_name("prepare_sft_data.py")),
            "solution_graph.py": file_sha256(Path(__file__).with_name("solution_graph.py")),
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    print(json.dumps(asyncio.run(collect(args.config, config)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
