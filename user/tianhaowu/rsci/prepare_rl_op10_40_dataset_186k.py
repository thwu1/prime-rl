#!/usr/bin/env python
"""Generate the OP10-40 bank sized for 5,000 duplicate-free 32-group updates."""

import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import prepare_rl_op10_40_dataset as dataset

dataset.TRAIN_PER_OPERATION = 6_000
dataset.REQUIRED_DISTINCT_TASK_PULLS = 160_064
dataset.DEFAULT_OUTPUT_DIR = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-186k"
)
TARGET_EVAL_CONFIG = Path(__file__).parent / "configs/rl/op10_40_strict_grpo_r128_defect_p00.toml"
TARGET_EVAL_AUDIT = "target_eval_audit.json"
base_protocol_record = dataset.protocol_record
base_finalize = dataset.finalize
base_validate_finalized = dataset.validate_finalized


def protocol_record() -> dict:
    record = base_protocol_record()
    record["no_repeat_capacity"] = {
        "training_steps": 5_000,
        "batch_size": 4_096,
        "group_size": 128,
        "max_inflight_rollouts": 8_192,
        "task_groups_per_step": 32,
        "inflight_task_groups": 64,
        "required_distinct_task_pulls": dataset.REQUIRED_DISTINCT_TASK_PULLS,
    }
    return record


def file_identities(path: Path) -> tuple[int, Counter[int], set[str], set[str]]:
    rows = 0
    operations: Counter[int] = Counter()
    ids: set[str] = set()
    prompt_hashes: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows += 1
            operations[int(row["op"])] += 1
            ids.add(str(row["id"]))
            prompt = dataset.prompt_text(row).encode("utf-8")
            prompt_hashes.add(hashlib.sha256(prompt).hexdigest())
    return rows, operations, ids, prompt_hashes


def target_eval_record(output_dir: Path) -> dict[str, Any]:
    config = tomllib.loads(TARGET_EVAL_CONFIG.read_text(encoding="utf-8"))
    eval_envs = config["orchestrator"]["eval"]["env"]
    expected_operations = list(range(11, 46))
    configured_operations = [int(env["args"]["min_op"]) for env in eval_envs]
    if configured_operations != expected_operations:
        raise ValueError(f"Target eval operations differ: {configured_operations}")

    train_path = output_dir / "train.jsonl"
    train_rows, train_operations, train_ids, train_prompts = file_identities(train_path)
    if train_rows != 186_000 or train_operations != Counter({operation: 6_000 for operation in range(10, 41)}):
        raise ValueError(f"Target-eval audit found the wrong training distribution: {train_operations}")
    if len(train_ids) != train_rows or len(train_prompts) != train_rows:
        raise ValueError("Target-eval audit found duplicate training IDs or prompts")

    eval_raw_ids: set[str] = set()
    eval_prompts: set[str] = set()
    eval_files: dict[str, Any] = {}
    eval_rows = 0
    for operation, env in zip(expected_operations, eval_envs, strict=True):
        args = env["args"]
        if int(args["max_op"]) != operation:
            raise ValueError(f"Target eval op{operation} has a mismatched max_op")
        path = Path(args["dataset_path"])
        rows, operations, ids, prompt_hashes = file_identities(path)
        if rows != 200 or operations != Counter({operation: 200}):
            raise ValueError(f"Target eval op{operation} has the wrong row distribution: {operations}")
        if len(prompt_hashes) != rows:
            raise ValueError(f"Target eval op{operation} contains duplicate prompts")
        eval_rows += rows
        eval_raw_ids.update(ids)
        eval_prompts.update(prompt_hashes)
        eval_files[str(operation)] = {
            "path": str(path.resolve()),
            "rows": rows,
            "sha256": dataset.file_sha256(path),
        }

    if len(eval_prompts) != eval_rows:
        raise ValueError("Target OP11-45 eval contains cross-file duplicate prompts")
    prompt_overlap = train_prompts & eval_prompts
    raw_id_overlap = train_ids & eval_raw_ids
    if prompt_overlap:
        raise ValueError(f"Training data overlaps the target OP11-45 eval: prompt_overlap={len(prompt_overlap)}")
    return {
        "schema_version": 2,
        "target_eval_config": {
            "path": str(TARGET_EVAL_CONFIG.resolve()),
            "sha256": dataset.file_sha256(TARGET_EVAL_CONFIG),
        },
        "train": {
            "path": str(train_path.resolve()),
            "rows": train_rows,
            "unique_ids": len(train_ids),
            "unique_prompts": len(train_prompts),
            "sha256": dataset.file_sha256(train_path),
        },
        "eval": {
            "operations": expected_operations,
            "rows": eval_rows,
            "unique_raw_ids": len(eval_raw_ids),
            "raw_id_duplicates": eval_rows - len(eval_raw_ids),
            "unique_prompts": len(eval_prompts),
            "unique_task_keys": len(eval_prompts),
            "files": eval_files,
        },
        "prompt_overlap": 0,
        "raw_id_overlap": len(raw_id_overlap),
    }


def validate_finalized(output_dir: Path) -> dict[str, Any]:
    manifest = base_validate_finalized(output_dir)
    audit_path = output_dir / TARGET_EVAL_AUDIT
    if not audit_path.is_file():
        raise FileNotFoundError(f"Missing target-eval audit: {audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    expected = target_eval_record(output_dir)
    if audit != expected:
        raise ValueError(f"Target-eval audit differs: {audit_path}")
    expected_manifest_record = {
        "path": str(audit_path.resolve()),
        "sha256": dataset.file_sha256(audit_path),
    }
    if manifest.get("target_eval_audit") != expected_manifest_record:
        raise ValueError(f"Dataset manifest does not bind the target-eval audit: {audit_path}")
    return manifest


def finalize(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "dataset_manifest.json"
    if manifest_path.is_file():
        base_validate_finalized(output_dir)
    else:
        base_finalize(output_dir)

    audit_path = output_dir / TARGET_EVAL_AUDIT
    dataset.write_json(audit_path, target_eval_record(output_dir))
    manifest = base_validate_finalized(output_dir)
    manifest["target_eval_audit"] = {
        "path": str(audit_path.resolve()),
        "sha256": dataset.file_sha256(audit_path),
    }
    dataset.write_json(manifest_path, manifest)
    manifest = validate_finalized(output_dir)
    print(json.dumps({"status": "finalized_with_target_eval_audit", "manifest": manifest}, indent=2, sort_keys=True))
    return manifest


dataset.protocol_record = protocol_record
dataset.finalize = finalize
dataset.validate_finalized = validate_finalized


if __name__ == "__main__":
    dataset.main()
