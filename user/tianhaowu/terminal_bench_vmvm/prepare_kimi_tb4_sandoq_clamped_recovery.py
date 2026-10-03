#!/usr/bin/env python3
"""Prepare a private Sandoq recovery lane for VMVM-zero-model TB4 work.

The selector is derived without printing member names.  Compose tasks remain
deterministically unsupported; all remaining CPU tasks are capped to the
qualified Firecracker envelope instead of trusting their larger declarations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union

SCHEMA_VERSION = 1
KIND = "kimi-tb4-sandoq-clamped-zero-model-recovery"
STAGE = "tb4-miniswe246-sandoq-clamped-recovery"
SELECTOR = "sandoq-clamped-remainder.tasks.txt"
CONFIG = "sandoq-clamped-remainder.toml"
PLAN = "launch-plan.json"
TASK_COUNT = 27
COMPOSE_UNSUPPORTED = 11
GPU_UNSUPPORTED = 3
SUPPORTED_CONCURRENCIES = frozenset({23, 24})
CPU_CAP = 2
MEMORY_MB_CAP = 4096
STORAGE_MB_CAP = 10240
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ClampedRecoveryError(ValueError):
    """A fail-closed recovery input did not satisfy the aggregate contract."""


def _read(path: Path, *, code: str, private: bool) -> bytes:
    try:
        return split.read_regular(path, code=code, private=private)
    except (OSError, ValueError) as error:
        raise ClampedRecoveryError(code) from error


def _artifact(path: Path, body: bytes) -> dict[str, int | str]:
    return {"path": str(path), "bytes": len(body), "sha256": split.sha256_bytes(body)}


def _json(body: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClampedRecoveryError(code) from error
    if not isinstance(value, dict) or split.canonical_json(value) != body:
        raise ClampedRecoveryError(code)
    return value


def _load_source_plan(
    path: Path,
    expected_sha256: str,
) -> tuple[dict[str, Any], bytes, tuple[split.ManifestEntry, ...]]:
    body = _read(path, code="source_plan_invalid", private=True)
    if (
        SHA256_RE.fullmatch(expected_sha256 or "") is None
        or split.sha256_bytes(body) != expected_sha256
    ):
        raise ClampedRecoveryError("source_plan_invalid")
    plan = _json(body, code="source_plan_invalid")
    source = plan.get("source")
    lanes = plan.get("lanes")
    if (
        plan.get("schema_version") != union.SCHEMA_VERSION
        or plan.get("kind") != union.PLAN_KIND
        or plan.get("state") != "materialized"
        or not isinstance(source, dict)
        or not isinstance(lanes, dict)
        or set(lanes) != {union.SANDOQ_ROLE, union.VMVM_ROLE, union.GPU_ROLE}
        or lanes[union.SANDOQ_ROLE].get("provider") != "sandoq"
        or lanes[union.SANDOQ_ROLE].get("count") != union.SANDOQ_TASKS
        or lanes[union.VMVM_ROLE].get("provider") != "vmvm"
        or lanes[union.VMVM_ROLE].get("count") != union.VMVM_TASKS
        or lanes[union.GPU_ROLE].get("count") != union.GPU_TASKS
    ):
        raise ClampedRecoveryError("source_plan_invalid")
    manifest_record = source.get("manifest")
    if not isinstance(manifest_record, dict):
        raise ClampedRecoveryError("source_plan_invalid")
    manifest_path = Path(str(manifest_record["path"]))
    manifest_body = _read(manifest_path, code="resource_manifest_invalid", private=True)
    if (
        len(manifest_body) != manifest_record.get("bytes")
        or split.sha256_bytes(manifest_body) != manifest_record.get("sha256")
    ):
        raise ClampedRecoveryError("resource_manifest_invalid")
    try:
        _manifest, entries = split.parse_manifest(manifest_body, str(manifest_record["sha256"]))
    except (OSError, TypeError, ValueError) as error:
        raise ClampedRecoveryError("resource_manifest_invalid") from error
    source_members: dict[str, tuple[str, ...]] = {}
    for role in (union.SANDOQ_ROLE, union.VMVM_ROLE):
        record = lanes[role].get("selector")
        if not isinstance(record, dict):
            raise ClampedRecoveryError("source_plan_invalid")
        selector_path = Path(str(record.get("path", "")))
        selector_body = _read(selector_path, code="source_plan_invalid", private=True)
        if _artifact(selector_path, selector_body) != record:
            raise ClampedRecoveryError("source_plan_invalid")
        try:
            members = tuple(selector_body.decode().splitlines())
        except UnicodeDecodeError as error:
            raise ClampedRecoveryError("source_plan_invalid") from error
        if (
            len(members) != len(set(members))
            or selector_body != union._selector_payload(members)
        ):
            raise ClampedRecoveryError("source_plan_invalid")
        source_members[role] = members
    baseline = split.derive_partition(entries)
    manifest_members = {entry.task_id for entry in entries}
    groups = (
        set(source_members[union.SANDOQ_ROLE]),
        set(source_members[union.VMVM_ROLE]),
        set(baseline.gpu_unsupported),
    )
    if (
        tuple(map(len, groups)) != (union.SANDOQ_TASKS, union.VMVM_TASKS, union.GPU_TASKS)
        or any(
            groups[left] & groups[right]
            for left in range(3)
            for right in range(left + 1, 3)
        )
        or set().union(*groups) != manifest_members
        or not set(baseline.compose_required).issubset(groups[1])
    ):
        raise ClampedRecoveryError("source_partition_invalid")
    return plan, body, entries


def _members(
    source_plan: dict[str, Any],
    entries: tuple[split.ManifestEntry, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    record = source_plan["lanes"][union.VMVM_ROLE]["selector"]
    selector_body = _read(Path(str(record["path"])), code="source_plan_invalid", private=True)
    vmvm_members = tuple(selector_body.decode().splitlines())
    compose = frozenset(split.derive_partition(entries).compose_required)
    selected = tuple(member for member in vmvm_members if member not in compose)
    unsupported = tuple(member for member in vmvm_members if member in compose)
    if (
        len(selected) != TASK_COUNT
        or len(unsupported) != COMPOSE_UNSUPPORTED
        or set(selected) & set(unsupported)
        or set(selected) | set(unsupported) != set(vmvm_members)
    ):
        raise ClampedRecoveryError("recovery_partition_invalid")
    return selected, unsupported


def _validate_zero_model_abort(results: Path, expected_count: int) -> tuple[bytes, int]:
    body = _read(results, code="aborted_results_invalid", private=True)
    seen: set[int] = set()
    rows = 0
    for raw_line in body.splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClampedRecoveryError("aborted_results_invalid") from error
        task = row.get("task") if isinstance(row, dict) else None
        index = task.get("idx") if isinstance(task, dict) else None
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < expected_count
            or index in seen
            or not isinstance(row.get("errors"), list)
            or not row["errors"]
            or row.get("nodes") != []
            or row.get("rewards") != {}
            or row.get("metrics") != {}
            or row.get("info") != {}
        ):
            raise ClampedRecoveryError("aborted_run_not_zero_model_only")
        seen.add(index)
        rows += 1
    if not 1 <= rows <= expected_count:
        raise ClampedRecoveryError("aborted_results_invalid")
    return body, rows


def _source_concurrency(source_plan: dict[str, Any]) -> int:
    concurrency = source_plan["lanes"][union.SANDOQ_ROLE].get("concurrency")
    if type(concurrency) is not int or concurrency not in SUPPORTED_CONCURRENCIES:
        raise ClampedRecoveryError("source_concurrency_invalid")
    return concurrency


def _expected_config(
    source_plan: dict[str, Any],
    selector: Path,
    selector_body: bytes,
    concurrency: int,
) -> bytes:
    record = source_plan["lanes"][union.SANDOQ_ROLE]["config"]
    source_path = Path(str(record["path"]))
    body = _read(source_path, code="source_config_invalid", private=True)
    if len(body) != record["bytes"] or split.sha256_bytes(body) != record["sha256"]:
        raise ClampedRecoveryError("source_config_invalid")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ClampedRecoveryError("source_config_invalid") from error
    value["num_tasks"] = TASK_COUNT
    value["max_concurrent"] = concurrency
    value["multiplex"] = concurrency
    value["client"]["max_connections"] = concurrency
    value["client"]["max_keepalive_connections"] = concurrency
    value["taskset"]["task_file"] = str(selector)
    value["taskset"]["task_file_sha256"] = split.sha256_bytes(selector_body)
    value["taskset"]["enable_compose"] = False
    value["taskset"]["resource_multiplier"] = 1.0
    value["taskset"].pop("memory_resource_multiplier", None)
    value["taskset"]["resource_cpu_cap"] = CPU_CAP
    value["taskset"]["resource_memory_mb_cap"] = MEMORY_MB_CAP
    value["taskset"]["resource_storage_mb_cap"] = STORAGE_MB_CAP
    return union._render_toml(value)


def _expected_plan(
    *,
    directory: Path,
    output_dir: Path,
    source_plan_path: Path,
    source_plan_body: bytes,
    source_plan: dict[str, Any],
    aborted_results: Path,
    aborted_body: bytes,
    aborted_rows: int,
    selector_body: bytes,
    config_body: bytes,
    concurrency: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "materialized",
        "source": {
            "union_plan": _artifact(source_plan_path, source_plan_body),
            "resource_manifest": source_plan["source"]["manifest"],
            "image_manifest": source_plan["source"]["image_manifest"],
            "aborted_vmvm_results": _artifact(aborted_results, aborted_body),
        },
        "partition": {
            "source_vmvm_tasks": union.VMVM_TASKS,
            "sandoq_clamped_tasks": TASK_COUNT,
            "compose_unsupported_tasks": COMPOSE_UNSUPPORTED,
            "gpu_unsupported_tasks": GPU_UNSUPPORTED,
            "prior_zero_model_rows": aborted_rows,
            "prior_model_bearing_rows": 0,
            "disjoint": True,
            "pass_at_1_preserved": True,
        },
        "lane": {
            "provider": "sandoq",
            "count": TASK_COUNT,
            "concurrency": concurrency,
            "selector": _artifact(directory / SELECTOR, selector_body),
            "config": _artifact(directory / CONFIG, config_body),
            "output_dir": str(output_dir),
        },
        "policy": {
            "harness": {"id": "mini-swe-agent", "version": union.MINISWE_VERSION},
            "context_tokens": split.MAX_SEQUENCE_TOKENS,
            "generation_tokens": split.SAMPLING_MAX_TOKENS,
            "reasoning_required": True,
            "exact_provider_json_required": True,
            "network_access": True,
            "compose_execution": "unsupported",
            "resource_allocation": "minimum-of-declared-and-qualified-cap",
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
        },
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    source_plan, source_body, entries = _load_source_plan(args.source_plan, args.source_plan_sha256)
    concurrency = _source_concurrency(source_plan)
    selected, _unsupported = _members(source_plan, entries)
    aborted_body, aborted_rows = _validate_zero_model_abort(
        args.aborted_results,
        union.VMVM_TASKS,
    )
    directory = Path(os.path.abspath(args.output))
    output_dir = Path(os.path.abspath(args.run_output))
    try:
        directory.parent.mkdir(mode=0o700)
        parent_metadata = directory.parent.stat(follow_symlinks=False)
    except FileExistsError:
        parent_metadata = directory.parent.stat(follow_symlinks=False)
    except OSError as error:
        raise ClampedRecoveryError("output_parent_invalid") from error
    if (
        directory.parent.is_symlink()
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        raise ClampedRecoveryError("output_parent_invalid")
    if directory.exists() or directory.is_symlink() or output_dir.exists() or output_dir.is_symlink():
        raise ClampedRecoveryError("output_not_fresh")
    selector_body = union._selector_payload(selected)
    config_body = _expected_config(source_plan, directory / SELECTOR, selector_body, concurrency)
    plan = _expected_plan(
        directory=directory,
        output_dir=output_dir,
        source_plan_path=args.source_plan.resolve(strict=True),
        source_plan_body=source_body,
        source_plan=source_plan,
        aborted_results=args.aborted_results.resolve(strict=True),
        aborted_body=aborted_body,
        aborted_rows=aborted_rows,
        selector_body=selector_body,
        config_body=config_body,
        concurrency=concurrency,
    )
    try:
        split._publish_private_bundle(
            directory,
            {SELECTOR: selector_body, CONFIG: config_body, PLAN: split.canonical_json(plan)},
        )
    except (OSError, ValueError) as error:
        raise ClampedRecoveryError("bundle_publish_failed") from error
    return {
        "state": "materialized",
        "tasks": TASK_COUNT,
        "concurrency": concurrency,
        "plan_sha256": split.sha256_bytes(split.canonical_json(plan)),
    }


def verify(plan_path: Path, expected_sha256: str) -> dict[str, Any]:
    body = _read(plan_path, code="plan_invalid", private=True)
    if (
        plan_path.name != PLAN
        or SHA256_RE.fullmatch(expected_sha256 or "") is None
        or split.sha256_bytes(body) != expected_sha256
    ):
        raise ClampedRecoveryError("plan_invalid")
    plan = _json(body, code="plan_invalid")
    source_record = plan.get("source", {}).get("union_plan")
    aborted_record = plan.get("source", {}).get("aborted_vmvm_results")
    if not isinstance(source_record, dict) or not isinstance(aborted_record, dict):
        raise ClampedRecoveryError("plan_invalid")
    source_path = Path(str(source_record.get("path", "")))
    source_plan, source_body, entries = _load_source_plan(source_path, str(source_record.get("sha256", "")))
    concurrency = _source_concurrency(source_plan)
    if len(source_body) != source_record.get("bytes"):
        raise ClampedRecoveryError("plan_invalid")
    selected, _unsupported = _members(source_plan, entries)
    aborted_path = Path(str(aborted_record.get("path", "")))
    aborted_body, aborted_rows = _validate_zero_model_abort(
        aborted_path,
        union.VMVM_TASKS,
    )
    if _artifact(aborted_path, aborted_body) != aborted_record:
        raise ClampedRecoveryError("aborted_results_changed")
    directory = plan_path.parent.resolve(strict=True)
    selector_body = union._selector_payload(selected)
    config_body = _expected_config(source_plan, directory / SELECTOR, selector_body, concurrency)
    output_dir = Path(str(plan.get("lane", {}).get("output_dir", "")))
    expected = _expected_plan(
        directory=directory,
        output_dir=output_dir,
        source_plan_path=source_path.resolve(strict=True),
        source_plan_body=source_body,
        source_plan=source_plan,
        aborted_results=aborted_path.resolve(strict=True),
        aborted_body=aborted_body,
        aborted_rows=aborted_rows,
        selector_body=selector_body,
        config_body=config_body,
        concurrency=concurrency,
    )
    if plan != expected:
        raise ClampedRecoveryError("plan_contract_invalid")
    for name, expected_body in ((SELECTOR, selector_body), (CONFIG, config_body)):
        if _read(directory / name, code="bundle_invalid", private=True) != expected_body:
            raise ClampedRecoveryError("bundle_invalid")
    return {
        "stage": STAGE,
        "provider": "sandoq",
        "config": str(directory / CONFIG),
        "config_sha256": split.sha256_bytes(config_body),
        "selector": str(directory / SELECTOR),
        "selector_sha256": split.sha256_bytes(selector_body),
        "count": TASK_COUNT,
        "concurrency": concurrency,
        "output_dir": str(output_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--source-plan", type=Path, required=True)
    create.add_argument("--source-plan-sha256", required=True)
    create.add_argument("--aborted-results", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--run-output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--plan-sha256", required=True)
    check.add_argument("--format", choices=("json", "tsv"), default="json")
    args = parser.parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else verify(args.plan, args.plan_sha256)
    except (OSError, ValueError) as error:
        print(json.dumps({"code": str(error), "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    if args.command == "verify" and args.format == "tsv":
        fields = (
            "stage",
            "provider",
            "config",
            "config_sha256",
            "selector",
            "selector_sha256",
            "count",
            "concurrency",
            "output_dir",
        )
        print(*(result[key] for key in fields), sep="\t")
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
