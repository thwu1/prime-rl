#!/usr/bin/env python3
"""Freeze strict, answer-only, and strict-wrong composition at one RL step."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_verifier_clock_pairs import (
    BANDS,
    EVAL_OPERATIONS,
    audit_eval_policy_versions,
    canonical_json_sha256,
    file_identity,
    rollout_root,
)

SCHEMA_VERSION = 1
OUTCOMES = ("S", "A", "W")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_ROOT")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--expected-rows", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.step < 0:
        raise ValueError("--step must be non-negative")
    if args.expected_rows < 1:
        raise ValueError("--expected-rows must be positive")
    return args


def parse_runs(values: list[str]) -> dict[str, Path]:
    runs: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path:
            raise ValueError(f"Invalid --run {value!r}; expected LABEL=RUN_ROOT")
        if label in runs:
            raise ValueError(f"Duplicate run label: {label}")
        runs[label] = Path(raw_path).expanduser().resolve()
    if "p00" not in runs or len(runs) < 2:
        raise ValueError("Runs must include p00 and at least one treatment")
    return dict(sorted(runs.items()))


def classify(strict: int, answer: int) -> str:
    if strict:
        if not answer:
            raise ValueError("Strict correctness does not imply answer correctness")
        return "S"
    return "A" if answer else "W"


def load_operation(
    label: str,
    run_root: Path,
    step: int,
    operation: int,
    expected_rows: int,
) -> tuple[dict[int, tuple[str, str]], dict[str, Any]]:
    path = rollout_root(run_root) / f"step_{step}" / f"eval_rollouts_heldout-op{operation}-strict.jsonl"
    identity = {"operation": operation, **file_identity(path)}
    records: dict[int, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            task = row.get("task")
            metrics = row.get("metrics")
            rewards = row.get("rewards")
            if not isinstance(task, dict) or not isinstance(metrics, dict) or not isinstance(rewards, dict):
                raise ValueError(f"Malformed evaluation row at {path}:{line_number}")
            index = task.get("idx")
            prompt = task.get("prompt")
            strict = metrics.get("strict_dependency_graph_reward")
            answer = metrics.get("answer_correct_metric")
            reward = rewards.get("reward")
            if isinstance(index, bool) or not isinstance(index, int) or not isinstance(prompt, str):
                raise ValueError(f"Invalid prompt identity at {path}:{line_number}")
            if (
                isinstance(strict, bool)
                or strict not in (0, 1, 0.0, 1.0)
                or isinstance(answer, bool)
                or answer not in (0, 1, 0.0, 1.0)
            ):
                raise ValueError(f"Non-binary evaluation metric at {path}:{line_number}")
            if isinstance(reward, bool) or not isinstance(reward, (int, float)) or float(reward) != float(strict):
                raise ValueError(f"Evaluation reward is not clean strict reward at {path}:{line_number}")
            if index in records:
                raise ValueError(f"Duplicate prompt index {index} in {path}")
            records[index] = (hashlib.sha256(prompt.encode()).hexdigest(), classify(int(strict), int(answer)))
    if sorted(records) != list(range(expected_rows)):
        raise ValueError(f"OP{operation} prompt indices differ at step {step} for {label}")
    return records, identity


def summarize_outcomes(outcomes: dict[tuple[int, int], str], operations: tuple[int, ...]) -> dict[str, Any]:
    selected = [outcome for (operation, _), outcome in outcomes.items() if operation in operations]
    counts = Counter(selected)
    total = len(selected)
    if total == 0 or set(counts) - set(OUTCOMES):
        raise ValueError(f"Invalid outcome population for operations {operations}")
    return {
        "operations": list(operations),
        "rows": total,
        "counts": {outcome: counts[outcome] for outcome in OUTCOMES},
        "rates": {outcome: counts[outcome] / total for outcome in OUTCOMES},
        "answer_correct_count": counts["S"] + counts["A"],
        "answer_correct_rate": (counts["S"] + counts["A"]) / total,
    }


def paired_contrast(
    control: dict[tuple[int, int], str],
    treatment: dict[tuple[int, int], str],
    operations: tuple[int, ...],
) -> dict[str, Any]:
    keys = sorted(key for key in control if key[0] in operations)
    if keys != sorted(key for key in treatment if key[0] in operations):
        raise ValueError("Paired contrast keys differ")
    result: dict[str, Any] = {"operations": list(operations), "rows": len(keys), "outcomes": {}}
    for outcome in OUTCOMES:
        treatment_only = sum(control[key] != outcome and treatment[key] == outcome for key in keys)
        control_only = sum(control[key] == outcome and treatment[key] != outcome for key in keys)
        result["outcomes"][outcome] = {
            "treatment_minus_control_rate": (treatment_only - control_only) / len(keys),
            "treatment_only": treatment_only,
            "control_only": control_only,
        }
    return result


def main() -> None:
    args = parse_args()
    runs = parse_runs(args.run)
    prompt_hashes: dict[tuple[int, int], str] | None = None
    arm_outcomes: dict[str, dict[tuple[int, int], str]] = {}
    arm_files: dict[str, list[dict[str, Any]]] = {}
    policy_audits = {}

    for label, run_root in runs.items():
        outcomes: dict[tuple[int, int], str] = {}
        hashes: dict[tuple[int, int], str] = {}
        files = []
        for operation in EVAL_OPERATIONS:
            records, identity = load_operation(label, run_root, args.step, operation, args.expected_rows)
            files.append(identity)
            for index, (prompt_hash, outcome) in records.items():
                key = (operation, index)
                hashes[key] = prompt_hash
                outcomes[key] = outcome
        if prompt_hashes is None:
            prompt_hashes = hashes
        elif hashes != prompt_hashes:
            raise ValueError(f"Prompt identities differ between p00 and {label}")
        arm_outcomes[label] = outcomes
        arm_files[label] = files
        policy_audits[label] = audit_eval_policy_versions(run_root, {args.step})

    if prompt_hashes is None:
        raise AssertionError("No runs loaded")
    summaries = {
        label: {band: summarize_outcomes(outcomes, operations) for band, operations in BANDS.items()}
        for label, outcomes in arm_outcomes.items()
    }
    contrasts = {
        f"{label}_minus_p00": {
            band: paired_contrast(arm_outcomes["p00"], outcomes, operations) for band, operations in BANDS.items()
        }
        for label, outcomes in arm_outcomes.items()
        if label != "p00"
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": "verifier_defect_source_composition",
        "step": args.step,
        "run_roots": {label: str(path) for label, path in runs.items()},
        "expected_rows_per_operation": args.expected_rows,
        "outcomes": {
            "S": "strict_dependency_graph_reward == 1",
            "A": "strict_dependency_graph_reward == 0 and answer_correct_metric == 1",
            "W": "answer_correct_metric == 0",
        },
        "evaluation_reward": "clean binary strict_dependency_graph_reward",
        "causal_claim_valid": False,
        "phase_transition_claim_valid": False,
        "prompt_sequence_sha256": canonical_json_sha256([[*key, prompt_hashes[key]] for key in sorted(prompt_hashes)]),
        "implementation": file_identity(Path(__file__)),
        "input_files": arm_files,
        "policy_version_audits": policy_audits,
        "summaries": summaries,
        "paired_prompt_contrasts": contrasts,
    }
    result["content_sha256"] = canonical_json_sha256(result)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "content_sha256": result["content_sha256"]}))


if __name__ == "__main__":
    main()
