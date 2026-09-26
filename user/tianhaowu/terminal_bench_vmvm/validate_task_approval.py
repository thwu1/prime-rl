#!/usr/bin/env python3
"""Fail closed unless an eval's snapshotted task set has external approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_TASK_FILE_BYTES = 16 * 1024 * 1024
TASKSET_ID = "terminal-bench-vmvm"


class TaskApprovalError(ValueError):
    """An evaluation input is not bound to the external task approval."""


def _read_bytes(path: Path, *, limit: int, error: str) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as cause:
        raise TaskApprovalError(error) from cause
    if len(data) > limit:
        raise TaskApprovalError(error)
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve(path: Path, *, strict: bool, error: str) -> Path:
    try:
        return path.resolve(strict=strict)
    except (OSError, RuntimeError, ValueError) as cause:
        raise TaskApprovalError(error) from cause


def _parse_config(raw: bytes, *, error: str) -> dict[str, Any]:
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as cause:
        raise TaskApprovalError(error) from cause
    if not isinstance(config, dict):
        raise TaskApprovalError(error)
    return config


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = _read_bytes(
        path,
        limit=MAX_MANIFEST_BYTES,
        error="input_manifest_unreadable",
    )
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise TaskApprovalError("input_manifest_invalid") from cause
    if not isinstance(manifest, dict):
        raise TaskApprovalError("input_manifest_invalid")
    return manifest


def _task_count(data: bytes, *, prefix: str) -> int:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise TaskApprovalError(f"{prefix}_invalid") from cause

    tasks = [line.strip().split("\t", 1)[0] for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not tasks:
        raise TaskApprovalError(f"{prefix}_empty")
    if len(tasks) != len(set(tasks)):
        raise TaskApprovalError(f"{prefix}_duplicates")
    return len(tasks)


def _validate_config_selection(
    config: dict[str, Any],
    *,
    approved_sha256: str,
    approved_count: int,
    error_prefix: str,
) -> str:
    taskset = config.get("taskset")
    if not isinstance(taskset, dict) or taskset.get("id") != TASKSET_ID:
        raise TaskApprovalError(f"{error_prefix}_taskset_invalid")
    if "tasks" in taskset:
        raise TaskApprovalError(f"{error_prefix}_inline_tasks_forbidden")

    task_file = taskset.get("task_file")
    if not isinstance(task_file, str) or not task_file.strip():
        raise TaskApprovalError(f"{error_prefix}_task_file_missing")
    task_file_sha256 = taskset.get("task_file_sha256")
    if not isinstance(task_file_sha256, str) or SHA256_RE.fullmatch(task_file_sha256) is None:
        raise TaskApprovalError(f"{error_prefix}_task_hash_invalid")
    if task_file_sha256 != approved_sha256:
        raise TaskApprovalError(f"{error_prefix}_task_hash_mismatch")

    num_tasks = config.get("num_tasks")
    if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
        raise TaskApprovalError(f"{error_prefix}_task_count_invalid")
    if num_tasks != approved_count:
        raise TaskApprovalError(f"{error_prefix}_task_count_mismatch")
    return task_file


def _manifest_record(
    manifest: dict[str, Any],
    name: str,
    *,
    expected_snapshot: Path,
) -> dict[str, str]:
    record = manifest.get(name)
    if not isinstance(record, dict) or set(record) != {"source", "snapshot", "sha256"}:
        raise TaskApprovalError(f"input_{name}_record_invalid")
    if not all(isinstance(record.get(key), str) for key in record):
        raise TaskApprovalError(f"input_{name}_record_invalid")
    if SHA256_RE.fullmatch(record["sha256"]) is None:
        raise TaskApprovalError(f"input_{name}_record_invalid")
    recorded_snapshot = _resolve(
        Path(record["snapshot"]),
        strict=False,
        error=f"input_{name}_record_invalid",
    )
    if recorded_snapshot != expected_snapshot:
        raise TaskApprovalError(f"input_{name}_snapshot_path_mismatch")
    return record


def validate_approval(
    inputs_dir: Path,
    approved_task_file: Path,
    approved_task_file_sha256: str,
    *,
    resume_config: Path | None = None,
    approved_config: Path | None = None,
    approved_config_sha256: str | None = None,
) -> tuple[str, int]:
    """Validate approval against fresh input snapshots and an optional resume config."""
    if SHA256_RE.fullmatch(approved_task_file_sha256) is None:
        raise TaskApprovalError("external_approval_hash_invalid")

    approved_bytes = _read_bytes(
        approved_task_file,
        limit=MAX_TASK_FILE_BYTES,
        error="external_approval_unreadable",
    )
    if _sha256(approved_bytes) != approved_task_file_sha256:
        raise TaskApprovalError("external_approval_hash_mismatch")
    approved_count = _task_count(approved_bytes, prefix="external_approval")

    resolved_inputs = _resolve(
        inputs_dir,
        strict=True,
        error="input_snapshot_directory_unreadable",
    )
    if not resolved_inputs.is_dir():
        raise TaskApprovalError("input_snapshot_directory_unreadable")
    source_config_path = resolved_inputs / "source_config.toml"
    task_snapshot_path = resolved_inputs / "task_file.txt"
    manifest = _load_manifest(resolved_inputs / "manifest.json")

    config_record = _manifest_record(
        manifest,
        "config",
        expected_snapshot=source_config_path,
    )
    if (approved_config is None) != (approved_config_sha256 is None):
        raise TaskApprovalError("external_config_approval_incomplete")
    if approved_config is not None and approved_config_sha256 is not None:
        if SHA256_RE.fullmatch(approved_config_sha256) is None:
            raise TaskApprovalError("external_config_approval_hash_invalid")
        approved_config_path = _resolve(
            approved_config,
            strict=False,
            error="external_config_approval_path_invalid",
        )
        recorded_config_source = _resolve(
            Path(config_record["source"]),
            strict=False,
            error="input_config_record_invalid",
        )
        if recorded_config_source != approved_config_path:
            raise TaskApprovalError("source_config_source_mismatch")
        if config_record["sha256"] != approved_config_sha256:
            raise TaskApprovalError("source_config_approval_hash_mismatch")
    task_record = _manifest_record(
        manifest,
        "task_file",
        expected_snapshot=task_snapshot_path,
    )

    source_config_bytes = _read_bytes(
        source_config_path,
        limit=MAX_CONFIG_BYTES,
        error="source_config_unreadable",
    )
    if _sha256(source_config_bytes) != config_record["sha256"]:
        raise TaskApprovalError("source_config_hash_mismatch")
    if approved_config_sha256 is not None and _sha256(source_config_bytes) != approved_config_sha256:
        raise TaskApprovalError("source_config_approval_hash_mismatch")
    source_config = _parse_config(source_config_bytes, error="source_config_invalid")
    source_task_file = _validate_config_selection(
        source_config,
        approved_sha256=approved_task_file_sha256,
        approved_count=approved_count,
        error_prefix="source_config",
    )
    declared_source = _resolve(
        Path(source_task_file),
        strict=False,
        error="source_config_task_file_invalid",
    )
    recorded_source = _resolve(
        Path(task_record["source"]),
        strict=False,
        error="input_task_file_record_invalid",
    )
    if declared_source != recorded_source:
        raise TaskApprovalError("source_config_task_file_mismatch")

    task_snapshot_bytes = _read_bytes(
        task_snapshot_path,
        limit=MAX_TASK_FILE_BYTES,
        error="task_snapshot_unreadable",
    )
    if task_record["sha256"] != approved_task_file_sha256:
        raise TaskApprovalError("task_snapshot_manifest_hash_mismatch")
    if _sha256(task_snapshot_bytes) != approved_task_file_sha256:
        raise TaskApprovalError("task_snapshot_hash_mismatch")
    if _task_count(task_snapshot_bytes, prefix="task_snapshot") != approved_count:
        raise TaskApprovalError("task_snapshot_count_mismatch")

    if resume_config is None:
        return approved_task_file_sha256, approved_count

    expected_resume_config = resolved_inputs.parent / "config.toml"
    resolved_resume_config = _resolve(
        resume_config,
        strict=True,
        error="resume_config_unreadable",
    )
    if resolved_resume_config != expected_resume_config:
        raise TaskApprovalError("resume_config_path_mismatch")
    saved_config_bytes = _read_bytes(
        resolved_resume_config,
        limit=MAX_CONFIG_BYTES,
        error="resume_config_unreadable",
    )
    saved_config = _parse_config(saved_config_bytes, error="resume_config_invalid")
    saved_task_file = _validate_config_selection(
        saved_config,
        approved_sha256=approved_task_file_sha256,
        approved_count=approved_count,
        error_prefix="resume_config",
    )
    resolved_saved_task_file = _resolve(
        Path(saved_task_file),
        strict=True,
        error="resume_config_task_file_unreadable",
    )
    if resolved_saved_task_file != task_snapshot_path:
        raise TaskApprovalError("resume_config_task_file_mismatch")
    return approved_task_file_sha256, approved_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--approved-task-file", type=Path, required=True)
    parser.add_argument("--approved-task-file-sha256", required=True)
    parser.add_argument("--resume-config", type=Path)
    parser.add_argument("--approved-config", type=Path)
    parser.add_argument("--approved-config-sha256")
    args = parser.parse_args(argv)
    try:
        approved_sha256, approved_count = validate_approval(
            args.inputs_dir,
            args.approved_task_file,
            args.approved_task_file_sha256,
            resume_config=args.resume_config,
            approved_config=args.approved_config,
            approved_config_sha256=args.approved_config_sha256,
        )
    except TaskApprovalError as error:
        print(f"task_approval_error:{error}", file=sys.stderr)
        return 2
    print(f"{approved_sha256}\t{approved_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
