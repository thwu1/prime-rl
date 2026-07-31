#!/usr/bin/env python
"""Generate deterministic GSM-Infinite datasets for the RSCI experiments."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, TextIO

import numpy as np
from vendor.gsm_infinite.DependencyGraph import RNG, AbstractParameterSpecial
from vendor.gsm_infinite.forward_generator import drawAll
from vendor.gsm_infinite.reverse_generator import drawAllEquan

SOURCE_REPOSITORY = "https://github.com/Interplay-LM-Reasoning/Interplay-LM-Reasoning"
SOURCE_COMMIT = "ab728f05d81de9af38d0ca155a84166b037e355a"
SCHEMA_VERSION = 1

CONTEXTS = {
    "zoo": "crazy_zootopia",
    "teacher": "teachers_in_school",
    "movie": "movie_festival_awards",
}
MODES: dict[str, Callable[..., tuple[Any, ...]]] = {
    "forward": drawAll,
    "reverse": drawAllEquan,
}
OP_TO_GENERATOR_MAX = {
    2: 3,
    3: 3,
    4: 4,
    5: 6,
    6: 6,
    7: 10,
    8: 10,
    9: 10,
    10: 15,
    11: 15,
    12: 20,
    13: 20,
    14: 20,
    15: 20,
    16: 25,
    17: 25,
    18: 25,
    19: 30,
    20: 30,
}
REJECTION_ERRORS = (AssertionError, IndexError, OverflowError, ValueError, ZeroDivisionError)


@dataclass(frozen=True)
class GenerationTask:
    split: str
    op: int
    context: str
    mode: str
    index: int


@dataclass
class AttemptStats:
    attempted: int = 0
    accepted: int = 0
    duplicates: int = 0
    rejected: Counter[str] = field(default_factory=Counter)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ops", type=int, nargs="+", default=[2])
    parser.add_argument("--train-per-op", type=int, default=1)
    parser.add_argument("--validation-per-op", type=int, default=1)
    parser.add_argument("--test-per-op", type=int, default=1)
    parser.add_argument(
        "--context-mixture",
        default="zoo=1",
        help="Comma-separated weights using zoo, teacher, and movie.",
    )
    parser.add_argument(
        "--mode-mixture",
        default="forward=0.5,reverse=0.5",
        help="Comma-separated weights using forward and reverse.",
    )
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--depth", type=int, choices=(2, 3), default=2)
    parser.add_argument("--number-range", type=int, default=5)
    parser.add_argument("--id-max-op", type=int, default=10)
    parser.add_argument("--generator-op-max", type=int)
    parser.add_argument("--max-attempts-per-sample", type=int, default=10_000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def parse_mixture(value: str, choices: Iterable[str]) -> dict[str, float]:
    allowed = set(choices)
    weights: dict[str, float] = {}
    for component in value.split(","):
        name, separator, raw_weight = component.strip().partition("=")
        if not separator:
            raise ValueError(f"Mixture component must have NAME=WEIGHT form: {component!r}")
        if name not in allowed:
            raise ValueError(f"Unknown mixture name {name!r}; choose from {sorted(allowed)}")
        if name in weights:
            raise ValueError(f"Duplicate mixture name: {name!r}")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"Mixture weights must be finite and positive: {component!r}")
        weights[name] = weight

    total = sum(weights.values())
    if not weights:
        raise ValueError("A mixture must contain at least one component")
    return {name: weight / total for name, weight in weights.items()}


def allocate_counts(total: int, weights: dict[Any, float]) -> dict[Any, int]:
    exact = {key: total * weight / sum(weights.values()) for key, weight in weights.items()}
    counts = {key: math.floor(value) for key, value in exact.items()}
    remainder = total - sum(counts.values())
    priority = sorted(exact, key=lambda key: (-(exact[key] - counts[key]), key))
    for key in priority[:remainder]:
        counts[key] += 1
    return counts


def iter_tasks(
    ops: list[int],
    split_counts: dict[str, int],
    context_weights: dict[str, float],
    mode_weights: dict[str, float],
) -> Iterator[GenerationTask]:
    for split, count in split_counts.items():
        context_counts = allocate_counts(count, context_weights)
        for op in ops:
            for context, context_count in sorted(context_counts.items()):
                mode_counts = allocate_counts(context_count, mode_weights)
                for mode, cell_count in sorted(mode_counts.items()):
                    for index in range(cell_count):
                        yield GenerationTask(split, op, context, mode, index)


def derive_seed(base_seed: int, task: GenerationTask, attempt: int) -> int:
    material = "\0".join(map(str, (base_seed, task.split, task.op, task.context, task.mode, task.index, attempt)))
    return int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], "big")


def split_solution(solution: str) -> tuple[str, str]:
    if "Answer:" not in solution:
        raise ValueError("Generated solution does not contain an Answer marker")
    body, answer = solution.rsplit("Answer:", 1)
    answer = answer.strip().splitlines()[0].strip().rstrip(".")
    if not body.strip() or not answer:
        raise ValueError("Generated solution has an empty rationale or answer")
    return body.strip(), answer


def graph_relation_counts(topo: list[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for node in topo:
        if isinstance(node, AbstractParameterSpecial):
            continue
        dependencies = [dependency for dependency in node.edgefromlist if not isinstance(dependency, RNG)]
        if not dependencies:
            counts["constant"] += 1
        elif len(dependencies) == 1:
            counts["copy"] += 1
        elif len(dependencies) == 2:
            relation = {"+": "addition", "-": "subtraction"}.get(node.notation)
            if relation is None:
                raise ValueError(f"Unrecognized binary graph relation: {node.notation!r}")
            counts[relation] += 1
        else:
            counts["addition"] += len(dependencies) - 1

        if any(isinstance(dependency, RNG) for dependency in node.edgefromlist):
            relation = {"+": "addition", "*": "multiplication"}.get(node.rngnot)
            if relation is not None:
                counts[relation] += 1
    return dict(sorted(counts.items()))


def solution_operator_counts(solution_body: str) -> dict[str, int]:
    symbols = {
        "addition": "+",
        "division": "/",
        "multiplication": "*",
        "subtraction": "-",
    }
    return {name: count for name, symbol in symbols.items() if (count := solution_body.count(symbol)) > 0}


def stable_sample_id(problem: str, question: str, solution: str) -> tuple[str, str]:
    digest = hashlib.sha256(
        json.dumps([problem, question, solution], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return f"gsm_infinite_{digest[:24]}", digest


def make_row(
    result: tuple[Any, ...],
    task: GenerationTask,
    depth: int,
    id_max_op: int,
) -> tuple[dict[str, Any], str]:
    problem, question, solution, op_count, _upstream_id, _abstract, _instance, topo = result
    if op_count != task.op:
        raise ValueError(f"Requested op {task.op}, but generator returned op {op_count}")

    solution_body, answer = split_solution(solution)
    sample_id, digest = stable_sample_id(problem, question, solution)
    prompt = f"<question> {problem.strip()} {question.strip()} </question> <solution>"
    completion = f"{solution_body} </solution> <answer> {answer} </answer>"
    operator_counts = solution_operator_counts(solution_body)
    row = {
        "id": sample_id,
        "problem": problem,
        "question": question,
        "solution": solution,
        "answer": answer,
        "op": op_count,
        "op_count": op_count,
        "op_class": f"op_{op_count:02d}",
        "generalization_split": "id" if op_count <= id_max_op else "ood",
        "operator_types": sorted(operator_counts),
        "solution_operator_counts": operator_counts,
        "graph_relation_counts": graph_relation_counts(topo),
        "context": task.context,
        "template": CONTEXTS[task.context],
        "mode": "normalforward" if task.mode == "forward" else "forwardreverse",
        "length": "zero_context",
        "d": depth,
        "difficulty": "medium" if depth == 2 else "hard",
        "prompt": prompt,
        "completion": completion,
        "text": f"{prompt} {completion}",
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ],
    }
    validate_row(row)
    return row, digest


def validate_row(row: dict[str, Any]) -> None:
    for field_name in ("id", "problem", "question", "solution", "answer", "prompt", "completion", "text"):
        if not isinstance(row[field_name], str) or not row[field_name].strip():
            raise ValueError(f"Generated row has an empty {field_name!r} field")
    if row["op"] != row["op_count"]:
        raise ValueError("op and op_count disagree")
    if row["text"] != f"{row['prompt']} {row['completion']}":
        raise ValueError("text is inconsistent with prompt and completion")
    if split_solution(row["solution"])[1] != row["answer"]:
        raise ValueError("answer is inconsistent with solution")


def generate_result(
    task: GenerationTask,
    args: argparse.Namespace,
    attempt: int,
    quiet_output: TextIO,
) -> tuple[Any, ...]:
    seed = derive_seed(args.seed, task, attempt)
    random.seed(seed)
    np.random.seed(seed)
    generator_op_max = args.generator_op_max if args.generator_op_max is not None else OP_TO_GENERATOR_MAX[task.op]
    with contextlib.redirect_stdout(quiet_output):
        return MODES[task.mode](
            op_max=generator_op_max,
            ip_max=20,
            verbose=False,
            mod=-1,
            force=True,
            number_range=args.number_range,
            strictline=generator_op_max,
            outputlistparameters=True,
            target_length="zero_context",
            template=CONTEXTS[task.context],
            d=args.depth,
            tokenizer=None,
            oplist=[task.op],
        )


def reserve_digest(connection: sqlite3.Connection, digest: str, row: dict[str, Any], split: str) -> bool:
    try:
        connection.execute(
            "INSERT INTO samples(digest, sample_id, split_name, op) VALUES (?, ?, ?, ?)",
            (digest, row["id"], split, row["op"]),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def prepare_outputs(output_dir: Path, splits: Iterable[str], overwrite: bool) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {split: output_dir / f"{split}.jsonl" for split in splits}
    managed = [
        *(output_dir / f"{split}.jsonl" for split in ("train", "validation", "test")),
        output_dir / "manifest.json",
        output_dir / "dedup.sqlite3",
    ]
    managed.extend([path.with_suffix(path.suffix + ".partial") for path in managed])
    existing = [path for path in managed if path.exists()]
    if existing and not overwrite:
        listing = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Managed output files already exist: {listing}; pass --overwrite to replace them")
    if overwrite:
        for path in existing:
            path.unlink()
    return paths


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def empty_summary(splits: Iterable[str]) -> dict[str, dict[str, Any]]:
    return {split: {"total": 0, "by_context": Counter(), "by_mode": Counter(), "by_op": Counter()} for split in splits}


def update_summary(summary: dict[str, dict[str, Any]], split: str, row: dict[str, Any]) -> None:
    summary[split]["total"] += 1
    summary[split]["by_context"][row["context"]] += 1
    summary[split]["by_mode"][row["mode"]] += 1
    summary[split]["by_op"][row["op"]] += 1


def serialize_summary(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        split: {
            "total": values["total"],
            "by_context": dict(sorted(values["by_context"].items())),
            "by_mode": dict(sorted(values["by_mode"].items())),
            "by_op": {str(key): value for key, value in sorted(values["by_op"].items())},
        }
        for split, values in summary.items()
    }


def generate_dataset(args: argparse.Namespace) -> dict[str, Any]:
    if len(set(args.ops)) != len(args.ops) or any(op < 1 for op in args.ops):
        raise ValueError("--ops must contain unique positive integers")
    unsupported = sorted(set(args.ops) - OP_TO_GENERATOR_MAX.keys())
    if unsupported and args.generator_op_max is None:
        raise ValueError(f"No released generator schedule for ops {unsupported}; provide --generator-op-max explicitly")
    if args.number_range < 3:
        raise ValueError("--number-range must be at least 3")
    if args.max_attempts_per_sample < 1:
        raise ValueError("--max-attempts-per-sample must be positive")
    if args.generator_op_max is not None and args.generator_op_max < max(args.ops):
        raise ValueError("--generator-op-max must be at least the largest requested operation")

    split_counts = {
        "train": args.train_per_op,
        "validation": args.validation_per_op,
        "test": args.test_per_op,
    }
    if any(count < 0 for count in split_counts.values()) or not any(split_counts.values()):
        raise ValueError("Split counts must be nonnegative and at least one must be positive")
    split_counts = {split: count for split, count in split_counts.items() if count}
    context_weights = parse_mixture(args.context_mixture, CONTEXTS)
    mode_weights = parse_mixture(args.mode_mixture, MODES)
    tasks = iter_tasks(args.ops, split_counts, context_weights, mode_weights)
    total_tasks = len(args.ops) * sum(split_counts.values())
    output_paths = prepare_outputs(args.output_dir, split_counts, args.overwrite)
    partial_paths = {split: path.with_suffix(".jsonl.partial") for split, path in output_paths.items()}
    database_path = args.output_dir / "dedup.sqlite3.partial"
    summary = empty_summary(split_counts)
    stats = AttemptStats()

    handles = {split: path.open("w", encoding="utf-8") for split, path in partial_paths.items()}
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE samples(digest TEXT PRIMARY KEY, sample_id TEXT, split_name TEXT, op INTEGER)")
    try:
        with open(os.devnull, "w", encoding="utf-8") as quiet_output:
            for position, task in enumerate(tasks, start=1):
                accepted = False
                for attempt in range(args.max_attempts_per_sample):
                    stats.attempted += 1
                    try:
                        result = generate_result(task, args, attempt, quiet_output)
                        row, digest = make_row(result, task, args.depth, args.id_max_op)
                    except REJECTION_ERRORS as error:
                        stats.rejected[type(error).__name__] += 1
                        continue
                    if not reserve_digest(connection, digest, row, task.split):
                        stats.duplicates += 1
                        continue
                    handles[task.split].write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    update_summary(summary, task.split, row)
                    stats.accepted += 1
                    accepted = True
                    break
                if not accepted:
                    raise RuntimeError(f"Could not generate {task} in {args.max_attempts_per_sample} attempts")
                if position == total_tasks or position % 100 == 0:
                    connection.commit()
                    print(f"generated {position}/{total_tasks} samples ({stats.attempted} attempts)")
        connection.commit()
    finally:
        connection.close()
        for handle in handles.values():
            handle.close()

    for split, partial_path in partial_paths.items():
        partial_path.replace(output_paths[split])
    database_path.replace(args.output_dir / "dedup.sqlite3")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": {"repository": SOURCE_REPOSITORY, "commit": SOURCE_COMMIT},
        "generation": {
            "seed": args.seed,
            "ops": args.ops,
            "split_counts_per_op": split_counts,
            "context_mixture_requested": context_weights,
            "mode_mixture_requested": mode_weights,
            "depth": args.depth,
            "number_range": args.number_range,
            "id_max_op": args.id_max_op,
            "generator_op_max_override": args.generator_op_max,
        },
        "counts": serialize_summary(summary),
        "attempts": {
            "attempted": stats.attempted,
            "accepted": stats.accepted,
            "duplicates": stats.duplicates,
            "rejected_by_exception": dict(sorted(stats.rejected.items())),
        },
        "files": {
            split: {
                "path": path.name,
                "rows": summary[split]["total"],
                "sha256": file_sha256(path),
            }
            for split, path in output_paths.items()
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_partial = manifest_path.with_suffix(".json.partial")
    manifest_partial.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_partial.replace(manifest_path)
    return manifest


def main() -> None:
    args = parse_args()
    manifest = generate_dataset(args)
    print(json.dumps({"output_dir": str(args.output_dir), "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
