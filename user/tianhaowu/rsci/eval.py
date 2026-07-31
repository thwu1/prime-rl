#!/usr/bin/env python
"""Evaluate an Interplay checkpoint on a generated GSM-Infinite JSONL dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openai import OpenAI

ANSWER_PATTERNS = (
    re.compile(r"<answer>\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE),
    re.compile(r"Answer\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    eval_config = config["eval"]
    required = {
        "dataset",
        "output_dir",
        "model",
        "api_base_url",
        "max_tokens",
        "temperature",
        "stop",
        "skip_special_tokens",
        "request_timeout_seconds",
    }
    missing = sorted(required - eval_config.keys())
    if missing:
        raise ValueError(f"Missing eval config fields: {missing}")
    if eval_config["max_tokens"] < 1:
        raise ValueError("eval.max_tokens must be positive")
    if eval_config["request_timeout_seconds"] <= 0:
        raise ValueError("eval.request_timeout_seconds must be positive")
    return config


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"Evaluation dataset is empty: {path}")
    required = {"id", "prompt", "answer", "op", "mode", "context"}
    for index, row in enumerate(rows):
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"Dataset row {index} is missing fields: {missing}")
    return rows


def extract_answer(text: str) -> str | None:
    for pattern in ANSWER_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            return matches[-1]
    return None


def normalize_answer(answer: str | None) -> Decimal | None:
    if answer is None:
        return None
    try:
        value = Decimal(answer.replace(",", "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def aggregate(results: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for result in results:
        grouped[str(result[key])].append(result["correct"])
    return {
        name: {
            "correct": sum(outcomes),
            "total": len(outcomes),
            "accuracy": sum(outcomes) / len(outcomes),
        }
        for name, outcomes in sorted(grouped.items())
    }


def output_paths(output_dir: Path) -> tuple[Path, Path]:
    return output_dir / "results.jsonl", output_dir / "metrics.json"


def run(config: dict[str, Any]) -> dict[str, Any]:
    eval_config = config["eval"]
    dataset_path = Path(eval_config["dataset"])
    output_dir = Path(eval_config["output_dir"])
    rows = load_rows(dataset_path)
    results_path, metrics_path = output_paths(output_dir)
    if not eval_config.get("overwrite", False):
        existing = [path for path in (results_path, metrics_path) if path.exists()]
        if existing:
            raise FileExistsError(f"Evaluation outputs already exist: {existing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    client = OpenAI(
        base_url=eval_config["api_base_url"],
        api_key="unused",
        timeout=eval_config["request_timeout_seconds"],
        max_retries=0,
    )
    response = client.completions.create(
        model=eval_config["model"],
        prompt=[row["prompt"] for row in rows],
        max_tokens=eval_config["max_tokens"],
        temperature=eval_config["temperature"],
        stop=eval_config["stop"],
        extra_body={"skip_special_tokens": eval_config["skip_special_tokens"]},
    )
    choices = sorted(response.choices, key=lambda choice: choice.index)
    if len(choices) != len(rows):
        raise RuntimeError(f"Server returned {len(choices)} choices for {len(rows)} prompts")

    results = []
    for row, choice in zip(rows, choices, strict=True):
        predicted_answer = extract_answer(choice.text)
        correct = normalize_answer(predicted_answer) == normalize_answer(str(row["answer"]))
        results.append(
            {
                "id": row["id"],
                "op": row["op"],
                "mode": row["mode"],
                "context": row["context"],
                "gold_answer": str(row["answer"]),
                "predicted_answer": predicted_answer,
                "correct": correct,
                "finish_reason": choice.finish_reason,
                "response": choice.text,
            }
        )

    correct = sum(result["correct"] for result in results)
    metrics = {
        "model": eval_config["model"],
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "total": len(results),
        "correct": correct,
        "accuracy": correct / len(results),
        "unparsed_answers": sum(result["predicted_answer"] is None for result in results),
        "by_op": aggregate(results, "op"),
        "by_mode": aggregate(results, "mode"),
        "by_context": aggregate(results, "context"),
        "sampling": {
            "max_tokens": eval_config["max_tokens"],
            "temperature": eval_config["temperature"],
            "stop": eval_config["stop"],
            "skip_special_tokens": eval_config["skip_special_tokens"],
        },
    }
    results_partial = results_path.with_suffix(".jsonl.partial")
    metrics_partial = metrics_path.with_suffix(".json.partial")
    results_partial.write_text(
        "".join(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n" for result in results),
        encoding="utf-8",
    )
    metrics_partial.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results_partial.replace(results_path)
    metrics_partial.replace(metrics_path)
    return metrics


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    rows = load_rows(Path(config["eval"]["dataset"]))
    if args.validate_only:
        print(json.dumps({"config": str(args.config), "rows": len(rows)}, indent=2))
        return
    print(json.dumps(run(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
