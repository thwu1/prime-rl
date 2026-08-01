#!/usr/bin/env python
"""Reproduce Interplay Figure 3 pass@k evaluation with strict graph scoring."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from solution_graph import compare_solutions

PASS_AT_DEFAULT = [1, 2, 4, 8, 16, 32, 64, 128]
ANSWER_RE = re.compile(r"<answer>\s*([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)
GOLD_ANSWER_RE = re.compile(r"Answer:\s*([-+]?\d+(?:\.\d+)?)")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    eval_config = config["eval"]
    required = {
        "data_dir",
        "operations",
        "examples_per_operation",
        "output_dir",
        "model",
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
    }
    missing = sorted(required - eval_config.keys())
    if missing:
        raise ValueError(f"Missing Figure 3 eval config fields: {missing}")
    if eval_config["samples_per_prompt"] < 1:
        raise ValueError("eval.samples_per_prompt must be positive")
    if eval_config["max_tokens"] < 1:
        raise ValueError("eval.max_tokens must be positive")
    if eval_config["max_concurrent_prompts"] < 1:
        raise ValueError("eval.max_concurrent_prompts must be positive")
    prompt_limit = eval_config.get("prompt_limit_per_operation")
    if prompt_limit is not None and not 1 <= int(prompt_limit) <= int(eval_config["examples_per_operation"]):
        raise ValueError("eval.prompt_limit_per_operation must be in [1, examples_per_operation]")
    pass_at = eval_config.get("pass_at", PASS_AT_DEFAULT)
    if any(k < 1 or k > eval_config["samples_per_prompt"] for k in pass_at):
        raise ValueError("Every eval.pass_at value must be in [1, samples_per_prompt]")
    operation_weights = eval_config.get("operation_weights")
    if operation_weights is not None:
        if len(operation_weights) != len(eval_config["operations"]):
            raise ValueError("eval.operation_weights must align with eval.operations")
        if any(weight <= 0 for weight in operation_weights):
            raise ValueError("eval.operation_weights values must be positive")
    return config


def compose_prompt(row: dict[str, Any]) -> str:
    problem = str(row["problem"]).strip()
    question = str(row["question"]).strip()
    return f"<question> {problem} {question} </question> <solution>"


def load_rows(eval_config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    data_dir = Path(eval_config["data_dir"])
    expected = int(eval_config["examples_per_operation"])
    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for operation in eval_config["operations"]:
        path = data_dir / f"op{operation}-{expected}.jsonl"
        raw = path.read_bytes()
        hashes[str(operation)] = hashlib.sha256(raw).hexdigest()
        operation_rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(operation_rows) != expected:
            raise ValueError(f"Expected {expected} rows in {path}, found {len(operation_rows)}")
        if "prompt_limit_per_operation" in eval_config:
            operation_rows = operation_rows[: int(eval_config["prompt_limit_per_operation"])]
        for index, row in enumerate(operation_rows):
            required = {"problem", "question", "solution", "op", "id", "template"}
            missing = sorted(required - row.keys())
            if missing:
                raise ValueError(f"{path} row {index} is missing fields: {missing}")
            if int(row["op"]) != int(operation):
                raise ValueError(f"{path} row {index} has op={row['op']}")
            row["__idx"] = index
            rows.append(row)
    keys = [(str(row["op"]), int(row["__idx"])) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Evaluation rows contain duplicate (op, row-index) keys")
    return rows, hashes


def load_existing(path: Path, samples_per_prompt: int) -> dict[tuple[str, int], set[int]]:
    completed: dict[tuple[str, int], set[int]] = defaultdict(set)
    if not path.exists():
        return completed
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        key = (str(record["op"]), int(record["__idx"]))
        rank = int(record["sample_rank"])
        if not 0 <= rank < samples_per_prompt:
            raise ValueError(f"Invalid sample rank on {path}:{line_number}: {rank}")
        if rank in completed[key]:
            raise ValueError(f"Duplicate sample rank for {key} on {path}:{line_number}: {rank}")
        completed[key].add(rank)
    return completed


async def generate_one(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    row: dict[str, Any],
    missing_ranks: list[int],
    eval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    async with semaphore:
        response = await client.completions.create(
            model=eval_config["model"],
            prompt=compose_prompt(row),
            n=len(missing_ranks),
            max_tokens=eval_config["max_tokens"],
            temperature=eval_config["temperature"],
            top_p=eval_config["top_p"],
            stop=eval_config["stop"],
            extra_body={
                "skip_special_tokens": eval_config["skip_special_tokens"],
                "top_k": eval_config["top_k"],
            },
        )
    choices = sorted(response.choices, key=lambda choice: choice.index)
    if len(choices) != len(missing_ranks):
        raise RuntimeError(
            f"Server returned {len(choices)} samples for op={row['op']} id={row['id']}; expected {len(missing_ranks)}"
        )
    return [
        {
            "op": int(row["op"]),
            "id": str(row["id"]),
            "__idx": int(row["__idx"]),
            "template": row["template"],
            "mode": row.get("mode"),
            "sample_rank": rank,
            "finish_reason": choice.finish_reason,
            "gen_solution_answer": choice.text.strip(),
        }
        for rank, choice in zip(missing_ranks, choices, strict=True)
    ]


async def generate(config: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    generations_path = output_dir / "generations.jsonl"
    metrics_path = output_dir / "metrics.json"
    strict_path = output_dir / "strict_results.jsonl"
    if eval_config.get("overwrite", False):
        for path in (generations_path, metrics_path, strict_path):
            path.unlink(missing_ok=True)
    elif metrics_path.exists():
        raise FileExistsError(f"Completed evaluation already exists: {metrics_path}")

    samples_per_prompt = int(eval_config["samples_per_prompt"])
    completed = load_existing(generations_path, samples_per_prompt)
    pending: list[tuple[dict[str, Any], list[int]]] = []
    all_ranks = set(range(samples_per_prompt))
    for row in rows:
        key = (str(row["op"]), int(row["__idx"]))
        missing_ranks = sorted(all_ranks - completed[key])
        if missing_ranks:
            pending.append((row, missing_ranks))
    if not pending:
        return

    client = AsyncOpenAI(
        base_url=eval_config["api_base_url"],
        api_key="unused",
        timeout=float(eval_config["request_timeout_seconds"]),
        max_retries=int(eval_config.get("max_retries", 2)),
    )
    semaphore = asyncio.Semaphore(int(eval_config["max_concurrent_prompts"]))
    tasks = [generate_one(client, semaphore, row, ranks, eval_config) for row, ranks in pending]
    mode = "a" if generations_path.exists() else "w"
    completed_prompts = len(rows) - len(pending)
    with generations_path.open(mode, encoding="utf-8") as handle:
        for task in asyncio.as_completed(tasks):
            records = await task
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            completed_prompts += 1
            if completed_prompts % 10 == 0 or completed_prompts == len(rows):
                print(f"generated {completed_prompts}/{len(rows)} prompts", flush=True)
    await client.close()


def extract_answer(text: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(text)
    return float(match.group(1)) if match else None


def pass_at_k_unbiased(num_samples: int, num_correct: int, k: int) -> float:
    if num_correct == 0:
        return 0.0
    if num_samples - num_correct < k:
        return 1.0
    return 1.0 - math.comb(num_samples - num_correct, k) / math.comb(num_samples, k)


def aggregate_pass_at_k(
    outcomes: dict[tuple[str, int], dict[int, bool]],
    pass_at: list[int],
    operation_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_op: dict[str, dict[tuple[str, int], dict[int, bool]]] = defaultdict(dict)
    for key, ranks in outcomes.items():
        per_op[key[0]][key] = ranks

    def summarize(
        prompts: dict[tuple[str, int], dict[int, bool]],
        prompt_weights: dict[tuple[str, int], float] | None = None,
    ) -> dict[str, dict[str, float]]:
        weights = prompt_weights or {key: 1.0 for key in prompts}
        denominator = sum(weights.values())
        empirical: dict[str, float] = {}
        unbiased: dict[str, float] = {}
        for k in pass_at:
            empirical[f"pass@{k}"] = (
                sum(
                    weights[key] * any(correct for rank, correct in ranks.items() if rank < k)
                    for key, ranks in prompts.items()
                )
                / denominator
            )
            unbiased[f"pass@{k}"] = (
                sum(
                    weights[key] * pass_at_k_unbiased(len(ranks), sum(ranks.values()), k)
                    for key, ranks in prompts.items()
                )
                / denominator
            )
        return {"empirical": empirical, "unbiased": unbiased}

    result = {
        "total": summarize(outcomes),
        "per_op": {op: summarize(prompts) for op, prompts in sorted(per_op.items(), key=lambda item: int(item[0]))},
    }
    if operation_weights is not None:
        prompt_weights = {key: operation_weights[key[0]] / len(per_op[key[0]]) for key in outcomes}
        result["weighted_total"] = summarize(outcomes, prompt_weights)
        result["operation_weights"] = operation_weights
    return result


def score(config: dict[str, Any], rows: list[dict[str, Any]], hashes: dict[str, str]) -> dict[str, Any]:
    eval_config = config["eval"]
    output_dir = Path(eval_config["output_dir"])
    generations_path = output_dir / "generations.jsonl"
    strict_path = output_dir / "strict_results.jsonl"
    metrics_path = output_dir / "metrics.json"
    gold = {(str(row["op"]), int(row["__idx"])): row for row in rows}
    samples_per_prompt = int(eval_config["samples_per_prompt"])
    strict_outcomes: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)
    answer_outcomes: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)
    parse_failures = 0

    strict_partial = strict_path.with_suffix(".jsonl.partial")
    with generations_path.open(encoding="utf-8") as generations, strict_partial.open("w", encoding="utf-8") as output:
        for line_number, line in enumerate(generations, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = (str(record["op"]), int(record["__idx"]))
            if key not in gold:
                raise ValueError(f"Unknown prompt key in {generations_path}:{line_number}: {key}")
            rank = int(record["sample_rank"])
            if rank in strict_outcomes[key]:
                raise ValueError(f"Duplicate sample rank for {key}: {rank}")
            prediction = str(record["gen_solution_answer"])
            report = compare_solutions(gold[key]["solution"], prediction)
            gold_answer = extract_answer(str(gold[key]["solution"]), GOLD_ANSWER_RE)
            predicted_answer = extract_answer(prediction, ANSWER_RE)
            answer_correct = gold_answer is not None and predicted_answer == gold_answer
            strict_outcomes[key][rank] = bool(report["perfect"])
            answer_outcomes[key][rank] = answer_correct
            if predicted_answer is None:
                parse_failures += 1
            output.write(
                json.dumps(
                    {
                        "op": int(record["op"]),
                        "id": str(record["id"]),
                        "template": record.get("template"),
                        "sample_rank": rank,
                        "perfect": report["perfect"],
                        "answer_correct": answer_correct,
                        "value_mismatch_count": len(report["value_mismatches"]),
                        "dependency_mismatch_count": len(report["dependency_mismatches"]),
                        "answer_mismatch": report["answer_mismatch"] is not None,
                        "extra_nodes": len(report["extra_in_pred"]),
                        "missing_nodes": len(report["missing_in_pred"]),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    expected_keys = set(gold)
    if set(strict_outcomes) != expected_keys:
        missing = sorted(expected_keys - strict_outcomes.keys())[:10]
        raise ValueError(f"Generations are missing prompts; first missing keys: {missing}")
    incomplete = {key: len(ranks) for key, ranks in strict_outcomes.items() if len(ranks) != samples_per_prompt}
    if incomplete:
        raise ValueError(f"Prompts do not have {samples_per_prompt} samples: {dict(list(incomplete.items())[:10])}")

    pass_at = [int(k) for k in eval_config.get("pass_at", PASS_AT_DEFAULT)]
    operation_weights = None
    if "operation_weights" in eval_config:
        operation_weights = {
            str(operation): float(weight)
            for operation, weight in zip(eval_config["operations"], eval_config["operation_weights"], strict=True)
        }
    metrics = {
        "model": eval_config["model"],
        "data_dir": eval_config["data_dir"],
        "dataset_sha256_by_op": hashes,
        "operations": [int(op) for op in eval_config["operations"]],
        "num_prompts": len(rows),
        "samples_per_prompt": samples_per_prompt,
        "num_generations": len(rows) * samples_per_prompt,
        "strict_graph": aggregate_pass_at_k(strict_outcomes, pass_at, operation_weights),
        "answer_only": aggregate_pass_at_k(answer_outcomes, pass_at, operation_weights),
        "diagnostics": {"unparsed_predictions": parse_failures},
        "sampling": {
            "temperature": eval_config["temperature"],
            "top_p": eval_config["top_p"],
            "top_k": eval_config["top_k"],
            "max_tokens": eval_config["max_tokens"],
            "stop": eval_config["stop"],
            "skip_special_tokens": eval_config["skip_special_tokens"],
        },
        "implementation_sha256": {
            "figure3_eval.py": file_sha256(Path(__file__)),
            "solution_graph.py": file_sha256(Path(__file__).with_name("solution_graph.py")),
        },
    }
    metrics_partial = metrics_path.with_suffix(".json.partial")
    metrics_partial.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    strict_partial.replace(strict_path)
    metrics_partial.replace(metrics_path)
    return metrics


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    rows, hashes = load_rows(config["eval"])
    if args.validate_only:
        print(json.dumps({"config": str(args.config), "operations": config["eval"]["operations"], "rows": len(rows)}))
        return
    if not args.score_only:
        asyncio.run(generate(config, rows))
    print(json.dumps(score(config, rows, hashes), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
