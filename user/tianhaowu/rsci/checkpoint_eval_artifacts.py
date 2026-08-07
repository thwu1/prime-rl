#!/usr/bin/env python
"""Validate and manage frozen-checkpoint evaluation completion markers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_STEPS = (0, *range(25, 501, 25))
EXPECTED_OPERATIONS = list(range(11, 46))
EXPECTED_PROMPTS = 35 * 200
ArtifactFingerprint = tuple[tuple[str, int, int], ...]
ValidationCache = dict[int, tuple[ArtifactFingerprint, float]]


def metrics_path(run_dir: Path, step: int) -> Path:
    return run_dir / "evals" / "op11-45" / f"step_{step}" / "metrics.json"


def _pass_at_one_error(payload: dict[str, Any], operation: int, kind: str) -> str | None:
    try:
        value = payload["strict_graph"]["per_op"][str(operation)][kind]["pass@1"]
    except (KeyError, TypeError):
        return f"missing strict_graph.per_op.{operation}.{kind}.pass@1"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return f"strict_graph.per_op.{operation}.{kind}.pass@1 is not finite"
    if not 0.0 <= float(value) <= 1.0:
        return f"strict_graph.per_op.{operation}.{kind}.pass@1 is outside [0, 1]"
    return None


def metrics_validation_error(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "metrics root is not a JSON object"
    expected_fields = {
        "operations": EXPECTED_OPERATIONS,
        "num_prompts": EXPECTED_PROMPTS,
        "samples_per_prompt": 1,
        "num_generations": EXPECTED_PROMPTS,
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            return f"{field}={payload.get(field)!r}, expected {expected!r}"
    if not isinstance(payload.get("model"), str) or not payload["model"]:
        return "model is not a non-empty string"
    for operation in EXPECTED_OPERATIONS:
        for kind in ("empirical", "unbiased"):
            error = _pass_at_one_error(payload, operation, kind)
            if error is not None:
                return error
    return None


def validate_metrics_file(path: Path) -> tuple[str | None, float | None]:
    if not path.is_file():
        return "metrics.json is missing", None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        modified_at = path.stat().st_mtime
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return f"{type(error).__name__}: {error}", None
    return metrics_validation_error(payload), modified_at


def _artifact_fingerprint(run_dir: Path, step: int) -> ArtifactFingerprint | None:
    output_dir = run_dir / "evals" / "op11-45" / f"step_{step}"
    paths = [
        output_dir / "metrics.json",
        output_dir / "strict_results.jsonl",
        output_dir / "generations.jsonl",
        output_dir / "generation_manifest.json",
        output_dir / "generation_completion.json",
        output_dir / "configs" / "eval.toml",
        output_dir / "configs" / "inference.toml",
        run_dir / "configs" / "trainer.toml",
    ]
    if step > 0:
        paths.append(run_dir / "weights" / f"step_{step}" / "STABLE")
    fingerprint = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            return None
        fingerprint.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(fingerprint)


def validate_checkpoint_eval(run_dir: Path, step: int) -> tuple[str | None, float | None]:
    path = metrics_path(run_dir, step)
    error, modified_at = validate_metrics_file(path)
    if error is not None:
        return error, modified_at

    from analyze_verifier_exposure import load_frozen_eval
    from figure3_eval import (
        GENERATION_COMPLETION_NAME,
        GENERATION_MANIFEST_NAME,
        build_generation_manifest,
        canonical_generation_content,
        load_config,
        load_json_object,
        load_rows,
        verify_generation_completion,
        verify_generation_manifest,
    )

    try:
        load_frozen_eval(run_dir, step, tuple(EXPECTED_OPERATIONS), 200)
        output_dir = path.parent
        config = load_config(output_dir / "configs" / "eval.toml")
        rows, hashes = load_rows(config["eval"])
        manifest = build_generation_manifest(config, rows, hashes)
        verify_generation_manifest(output_dir / GENERATION_MANIFEST_NAME, manifest)
        generation_digest, generation_records = canonical_generation_content(
            output_dir / "generations.jsonl",
            rows,
            int(config["eval"]["samples_per_prompt"]),
        )
        completion = verify_generation_completion(
            output_dir,
            manifest,
            generation_digest,
            len(generation_records),
        )
        metrics = load_json_object(path)
        expected_generation_provenance = {
            **completion,
            "generation_manifest": GENERATION_MANIFEST_NAME,
            "generation_completion": GENERATION_COMPLETION_NAME,
        }
        if metrics.get("generation_provenance") != expected_generation_provenance:
            raise ValueError("metrics generation_provenance does not match generation completion")
    except (OSError, ValueError) as validation_error:
        return f"{type(validation_error).__name__}: {validation_error}", modified_at
    return None, modified_at


def inspect_metrics(
    run_dir: Path,
    validation_cache: ValidationCache | None = None,
) -> tuple[list[int], list[int], dict[str, str], list[float]]:
    completed: list[int] = []
    missing: list[int] = []
    invalid: dict[str, str] = {}
    completion_times: list[float] = []
    for step in EXPECTED_STEPS:
        path = metrics_path(run_dir, step)
        fingerprint = _artifact_fingerprint(run_dir, step)
        cached = validation_cache.get(step) if validation_cache is not None else None
        if fingerprint is not None and cached is not None and cached[0] == fingerprint:
            completed.append(step)
            completion_times.append(cached[1])
            continue
        error, modified_at = validate_checkpoint_eval(run_dir, step)
        if error == "metrics.json is missing":
            missing.append(step)
        elif error is not None:
            invalid[str(step)] = error
            if validation_cache is not None:
                validation_cache.pop(step, None)
        else:
            completed.append(step)
            if modified_at is None:
                raise RuntimeError(f"Valid metrics have no modification time: {path}")
            completion_times.append(modified_at)
            if validation_cache is not None:
                if fingerprint is None:
                    raise RuntimeError(f"Valid checkpoint evaluation has incomplete artifacts: {path.parent}")
                validation_cache[step] = (fingerprint, modified_at)
    return completed, missing, invalid, completion_times


def quarantine_invalid_metrics(run_dir: Path, step: int, tag: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", tag) is None:
        raise ValueError(f"Invalid quarantine tag: {tag!r}")
    path = metrics_path(run_dir, step)
    error, _ = validate_checkpoint_eval(run_dir, step)
    if error == "metrics.json is missing":
        raise FileNotFoundError(path)
    if error is None:
        raise ValueError(f"Refusing to quarantine valid metrics: {path}")
    content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    quarantine_path = path.with_name(f"metrics.invalid.{tag}.{content_sha256}.json")
    if quarantine_path.exists():
        if hashlib.sha256(quarantine_path.read_bytes()).hexdigest() != content_sha256:
            raise FileExistsError(quarantine_path)
        path.unlink()
    else:
        path.replace(quarantine_path)
    return quarantine_path


def job_ledger_path(run_dir: Path, array_job_id: str) -> Path:
    return run_dir / "evals" / "op11-45" / "array" / "jobs" / f"{array_job_id}.json"


def _manifest_steps(manifest_path: Path) -> list[int]:
    steps = [int(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not steps:
        raise ValueError(f"Step manifest is empty: {manifest_path}")
    if len(steps) != len(set(steps)):
        raise ValueError(f"Step manifest contains duplicates: {manifest_path}")
    if any(step not in EXPECTED_STEPS for step in steps):
        raise ValueError(f"Step manifest is outside the frozen evaluation grid: {manifest_path}")
    return steps


def write_job_ledger(
    run_dir: Path,
    array_job_id: str,
    manifest_path: Path,
    dependency: str | None,
    max_parallel: int,
) -> Path:
    if re.fullmatch(r"[1-9][0-9]*", array_job_id) is None:
        raise ValueError(f"Invalid array job ID: {array_job_id!r}")
    if max_parallel < 1:
        raise ValueError("max_parallel must be positive")
    manifest_path = manifest_path.resolve()
    steps = _manifest_steps(manifest_path)
    path = job_ledger_path(run_dir, array_job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_dir": str(run_dir.resolve()),
        "array_job_id": array_job_id,
        "manifest_path": str(manifest_path),
        "dependency": dependency,
        "max_parallel": max_parallel,
        "steps": steps,
        "task_to_step": {str(task_id): step for task_id, step in enumerate(steps)},
    }
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)
    return path


def load_job_ledger(run_dir: Path, array_job_id: str) -> dict[str, Any] | None:
    path = job_ledger_path(run_dir, array_job_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Job ledger is not a JSON object: {path}")
    task_to_step = payload.get("task_to_step")
    if (
        payload.get("schema_version") != 1
        or payload.get("run_dir") != str(run_dir.resolve())
        or payload.get("array_job_id") != array_job_id
        or not isinstance(task_to_step, dict)
    ):
        raise ValueError(f"Invalid job ledger identity or schema: {path}")
    expected_tasks = {str(task_id) for task_id in range(len(task_to_step))}
    if set(task_to_step) != expected_tasks or any(
        isinstance(step, bool) or not isinstance(step, int) or step not in EXPECTED_STEPS
        for step in task_to_step.values()
    ):
        raise ValueError(f"Invalid task_to_step mapping: {path}")
    ordered_steps = [task_to_step[str(task_id)] for task_id in range(len(task_to_step))]
    if len(set(task_to_step.values())) != len(task_to_step):
        raise ValueError(f"Duplicate steps in task_to_step mapping: {path}")
    if payload.get("steps") != ordered_steps:
        raise ValueError(f"Ledger steps do not match task_to_step mapping: {path}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("run_dir", type=Path)
    validate.add_argument("step", type=int)

    incomplete = subparsers.add_parser("incomplete-steps")
    incomplete.add_argument("run_dir", type=Path)

    quarantine = subparsers.add_parser("quarantine-invalid")
    quarantine.add_argument("run_dir", type=Path)
    quarantine.add_argument("step", type=int)
    quarantine.add_argument("--tag", required=True)

    ledger = subparsers.add_parser("write-job-ledger")
    ledger.add_argument("run_dir", type=Path)
    ledger.add_argument("array_job_id")
    ledger.add_argument("manifest_path", type=Path)
    ledger.add_argument("--dependency")
    ledger.add_argument("--max-parallel", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    if args.command == "validate":
        error, _ = validate_checkpoint_eval(run_dir, args.step)
        if error is not None:
            print(error, file=sys.stderr)
            return 1
        return 0
    if args.command == "incomplete-steps":
        completed, _, invalid, _ = inspect_metrics(run_dir)
        completed_set = set(completed)
        for step in EXPECTED_STEPS:
            if step not in completed_set:
                print(step)
        for step, error in invalid.items():
            print(f"invalid step {step}: {error}", file=sys.stderr)
        return 0
    if args.command == "quarantine-invalid":
        print(quarantine_invalid_metrics(run_dir, args.step, args.tag))
        return 0
    if args.command == "write-job-ledger":
        print(
            write_job_ledger(
                run_dir,
                args.array_job_id,
                args.manifest_path,
                args.dependency,
                args.max_parallel,
            )
        )
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
