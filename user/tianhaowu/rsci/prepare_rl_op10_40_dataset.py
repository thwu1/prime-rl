#!/usr/bin/env python
"""Generate and assemble the fixed OP10-40 RL pool and OP41-45 evaluation set."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit_rl_dataset import audit, prompt_text, read_jsonl
from generate import generate_dataset

TRAIN_OPERATIONS = tuple(range(10, 41))
VALIDATION_OPERATIONS = tuple(range(41, 46))
TRAIN_PER_OPERATION = 1_000
VALIDATION_PER_OPERATION = 200
TRAIN_SEED = 20260803
VALIDATION_SEED = 20260802
REQUIRED_DISTINCT_TASK_PULLS = 20_064
MAX_ATTEMPTS_PER_SAMPLE = 50_000
DEFAULT_OUTPUT_DIR = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k")


@dataclass(frozen=True)
class ShardSpec:
    operation: int
    split: str
    rows: int
    seed: int
    generator_op_max: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-shard", help="Generate or validate one deterministic shard.")
    generate.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    generate.add_argument("--operation", type=int, required=True)

    finalize = subparsers.add_parser("finalize", help="Assemble and audit all completed shards.")
    finalize.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    check = subparsers.add_parser("check", help="Validate an already finalized dataset.")
    check.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
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


def shard_spec(operation: int) -> ShardSpec:
    if operation in TRAIN_OPERATIONS:
        if operation <= 20:
            generator_op_max = None
        elif operation <= 30:
            generator_op_max = 30
        else:
            generator_op_max = 40
        return ShardSpec(operation, "train", TRAIN_PER_OPERATION, TRAIN_SEED, generator_op_max)
    if operation in VALIDATION_OPERATIONS:
        return ShardSpec(operation, "validation", VALIDATION_PER_OPERATION, VALIDATION_SEED, 50)
    raise ValueError(f"Operation must be in {TRAIN_OPERATIONS[0]}-{VALIDATION_OPERATIONS[-1]}, found {operation}")


def shard_dir(output_dir: Path, operation: int) -> Path:
    return output_dir / "sources" / f"op{operation}"


def expected_generation(spec: ShardSpec) -> dict[str, Any]:
    return {
        "seed": spec.seed,
        "ops": [spec.operation],
        "split_counts_per_op": {spec.split: spec.rows},
        "context_mixture_requested": {"movie": 1 / 3, "teacher": 1 / 3, "zoo": 1 / 3},
        "mode_mixture_requested": {"forward": 0.5, "reverse": 0.5},
        "depth": 2,
        "number_range": 5,
        "id_max_op": 10,
        "generator_op_max_override": spec.generator_op_max,
    }


def validate_shard(output_dir: Path, spec: ShardSpec) -> dict[str, Any]:
    source_dir = shard_dir(output_dir, spec.operation)
    manifest_path = source_dir / "manifest.json"
    data_path = source_dir / f"{spec.split}.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing shard manifest: {manifest_path}")
    if not data_path.is_file():
        raise FileNotFoundError(f"Missing shard data: {data_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generation = manifest.get("generation")
    if generation != expected_generation(spec):
        raise ValueError(f"Shard generation protocol differs for op{spec.operation}: {generation}")
    file_record = manifest.get("files", {}).get(spec.split)
    if file_record is None:
        raise ValueError(f"Shard manifest lacks the {spec.split!r} file record: {manifest_path}")
    if int(file_record["rows"]) != spec.rows:
        raise ValueError(f"Shard manifest row count differs for op{spec.operation}: {file_record['rows']}")
    data_sha256 = file_sha256(data_path)
    if file_record["sha256"] != data_sha256:
        raise ValueError(f"Shard file hash differs from its manifest: {data_path}")

    rows = read_jsonl(data_path)
    if len(rows) != spec.rows:
        raise ValueError(f"Expected {spec.rows} rows in {data_path}, found {len(rows)}")
    operations = {int(row["op"]) for row in rows}
    if operations != {spec.operation}:
        raise ValueError(f"Shard contains the wrong operations: {data_path}: {sorted(operations)}")
    ids = [str(row["id"]) for row in rows]
    prompts = [prompt_text(row) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Shard contains duplicate sample IDs: {data_path}")
    if len(prompts) != len(set(prompts)):
        raise ValueError(f"Shard contains duplicate prompts: {data_path}")
    return {
        "operation": spec.operation,
        "split": spec.split,
        "rows": spec.rows,
        "data": str(data_path.resolve()),
        "data_sha256": data_sha256,
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": file_sha256(manifest_path),
    }


def generate_shard(output_dir: Path, operation: int) -> dict[str, Any]:
    spec = shard_spec(operation)
    source_dir = shard_dir(output_dir, operation)
    lock_path = output_dir / "sources" / f".op{operation}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if (source_dir / "manifest.json").is_file():
            record = validate_shard(output_dir, spec)
            print(json.dumps({"status": "already_complete", **record}, indent=2, sort_keys=True))
            return record

        generation_args = Namespace(
            output_dir=source_dir,
            ops=[operation],
            train_per_op=spec.rows if spec.split == "train" else 0,
            validation_per_op=spec.rows if spec.split == "validation" else 0,
            test_per_op=0,
            context_mixture="zoo=1,teacher=1,movie=1",
            mode_mixture="forward=0.5,reverse=0.5",
            seed=spec.seed,
            depth=2,
            number_range=5,
            id_max_op=10,
            generator_op_max=spec.generator_op_max,
            max_attempts_per_sample=MAX_ATTEMPTS_PER_SAMPLE,
            overwrite=source_dir.exists(),
        )
        generate_dataset(generation_args)
        record = validate_shard(output_dir, spec)
        print(json.dumps({"status": "generated", **record}, indent=2, sort_keys=True))
        return record


def protocol_record() -> dict[str, Any]:
    return {
        "train": {
            "operations": list(TRAIN_OPERATIONS),
            "rows_per_operation": TRAIN_PER_OPERATION,
            "rows": len(TRAIN_OPERATIONS) * TRAIN_PER_OPERATION,
            "seed": TRAIN_SEED,
            "generator_op_max": {"op10-20": "released_schedule", "op21-30": 30, "op31-40": 40},
        },
        "validation": {
            "operations": list(VALIDATION_OPERATIONS),
            "rows_per_operation": VALIDATION_PER_OPERATION,
            "rows": len(VALIDATION_OPERATIONS) * VALIDATION_PER_OPERATION,
            "seed": VALIDATION_SEED,
            "generator_op_max": 50,
        },
        "context_mixture": {"movie": 1 / 3, "teacher": 1 / 3, "zoo": 1 / 3},
        "mode_mixture": {"forward": 0.5, "reverse": 0.5},
        "max_attempts_per_sample": MAX_ATTEMPTS_PER_SAMPLE,
        "no_repeat_capacity": {
            "training_steps": 5_000,
            "batch_size": 512,
            "group_size": 128,
            "max_inflight_rollouts": 8_192,
            "task_groups_per_step": 4,
            "inflight_task_groups": 64,
            "required_distinct_task_pulls": REQUIRED_DISTINCT_TASK_PULLS,
        },
    }


def validate_finalized(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "dataset_manifest.json"
    audit_path = output_dir / "audit.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing finalized dataset manifest: {manifest_path}")
    if not audit_path.is_file():
        raise FileNotFoundError(f"Missing finalized dataset audit: {audit_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol") != protocol_record():
        raise ValueError(f"Finalized dataset protocol differs: {manifest_path}")
    if manifest.get("audit", {}).get("sha256") != file_sha256(audit_path):
        raise ValueError(f"Finalized audit hash differs: {audit_path}")
    expected_file_keys = {"train", *(f"validation_op{operation}" for operation in VALIDATION_OPERATIONS)}
    files = manifest.get("files", {})
    if set(files) != expected_file_keys:
        raise ValueError(f"Finalized dataset has the wrong file records: {manifest_path}")
    for record in files.values():
        path = Path(record["path"])
        if not path.is_file() or file_sha256(path) != record["sha256"]:
            raise ValueError(f"Finalized data file differs: {path}")
    audit_report = json.loads(audit_path.read_text(encoding="utf-8"))
    expected_train_rows = len(TRAIN_OPERATIONS) * TRAIN_PER_OPERATION
    expected_validation_rows = len(VALIDATION_OPERATIONS) * VALIDATION_PER_OPERATION
    train_audit = audit_report.get("train", {})
    validation_audit = audit_report.get("validation", {})
    if train_audit.get("rows") != expected_train_rows:
        raise ValueError(f"Finalized audit has the wrong training row count: {audit_path}")
    if train_audit.get("canonical_strict_passes") != expected_train_rows:
        raise ValueError(f"Finalized audit has strict-invalid canonical training rows: {audit_path}")
    if validation_audit.get("rows") != expected_validation_rows:
        raise ValueError(f"Finalized audit has the wrong validation row count: {audit_path}")
    if validation_audit.get("unique_prompts") != expected_validation_rows:
        raise ValueError(f"Finalized audit has duplicate validation prompts: {audit_path}")
    if validation_audit.get("unique_ids") != expected_validation_rows:
        raise ValueError(f"Finalized audit has duplicate validation IDs: {audit_path}")
    if validation_audit.get("canonical_strict_passes") != expected_validation_rows:
        raise ValueError(f"Finalized audit has strict-invalid canonical validation rows: {audit_path}")
    if validation_audit.get("prompt_overlap") != 0 or validation_audit.get("id_overlap") != 0:
        raise ValueError(f"Finalized audit has train-validation overlap: {audit_path}")
    capacity = audit_report.get("no_repeat_capacity", {})
    if capacity.get("required_distinct_task_pulls") != REQUIRED_DISTINCT_TASK_PULLS:
        raise ValueError(f"Finalized audit lacks the no-repeat capacity gate: {audit_path}")
    if capacity.get("available_unique_prompts") != expected_train_rows:
        raise ValueError(f"Finalized audit has the wrong number of unique training prompts: {audit_path}")
    if capacity.get("available_unique_ids") != expected_train_rows:
        raise ValueError(f"Finalized audit has the wrong number of unique training IDs: {audit_path}")
    if capacity.get("headroom_prompts") != expected_train_rows - REQUIRED_DISTINCT_TASK_PULLS:
        raise ValueError(f"Finalized audit has the wrong no-repeat capacity headroom: {audit_path}")
    return manifest


def finalize(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".finalize.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if (output_dir / "dataset_manifest.json").is_file():
            manifest = validate_finalized(output_dir)
            print(json.dumps({"status": "already_complete", "manifest": manifest}, indent=2, sort_keys=True))
            return manifest

        specs = [shard_spec(operation) for operation in (*TRAIN_OPERATIONS, *VALIDATION_OPERATIONS)]
        source_records = [validate_shard(output_dir, spec) for spec in specs]
        (output_dir / "audit.json").unlink(missing_ok=True)

        train_path = output_dir / "train.jsonl"
        train_partial = train_path.with_suffix(train_path.suffix + ".partial")
        with train_partial.open("wb") as output_handle:
            for operation in TRAIN_OPERATIONS:
                source_path = shard_dir(output_dir, operation) / "train.jsonl"
                payload = source_path.read_bytes()
                if payload and not payload.endswith(b"\n"):
                    raise ValueError(f"Shard does not end with a newline: {source_path}")
                output_handle.write(payload)
        train_partial.replace(train_path)

        validation_dir = output_dir / "eval"
        validation_dir.mkdir(parents=True, exist_ok=True)
        for operation in VALIDATION_OPERATIONS:
            source_path = shard_dir(output_dir, operation) / "validation.jsonl"
            target_path = validation_dir / f"op{operation}-{VALIDATION_PER_OPERATION}.jsonl"
            partial_path = target_path.with_suffix(target_path.suffix + ".partial")
            partial_path.write_bytes(source_path.read_bytes())
            partial_path.replace(target_path)

        audit_args = Namespace(
            train_data=train_path,
            validation_dir=validation_dir,
            operations=list(TRAIN_OPERATIONS),
            validation_operations=list(VALIDATION_OPERATIONS),
            expected_per_operation=TRAIN_PER_OPERATION,
            expected_validation_per_operation=VALIDATION_PER_OPERATION,
            required_distinct_task_pulls=REQUIRED_DISTINCT_TASK_PULLS,
            require_global_uniqueness=True,
        )
        audit_report = audit(audit_args)
        audit_path = output_dir / "audit.json"
        write_json(audit_path, audit_report)

        files = {
            "train": {
                "path": str(train_path.resolve()),
                "rows": len(TRAIN_OPERATIONS) * TRAIN_PER_OPERATION,
                "sha256": file_sha256(train_path),
            }
        }
        for operation in VALIDATION_OPERATIONS:
            path = validation_dir / f"op{operation}-{VALIDATION_PER_OPERATION}.jsonl"
            files[f"validation_op{operation}"] = {
                "path": str(path.resolve()),
                "rows": VALIDATION_PER_OPERATION,
                "sha256": file_sha256(path),
            }
        manifest = {
            "schema_version": 1,
            "protocol": protocol_record(),
            "sources": source_records,
            "files": files,
            "audit": {"path": str(audit_path.resolve()), "sha256": file_sha256(audit_path)},
        }
        write_json(output_dir / "dataset_manifest.json", manifest)
        print(json.dumps({"status": "finalized", "manifest": manifest}, indent=2, sort_keys=True))
        return manifest


def main() -> None:
    args = parse_args()
    if args.command == "generate-shard":
        generate_shard(args.output_dir, args.operation)
    elif args.command == "finalize":
        finalize(args.output_dir)
    else:
        manifest = validate_finalized(args.output_dir)
        print(json.dumps({"status": "complete", "manifest": manifest}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
