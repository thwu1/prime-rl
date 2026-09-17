#!/usr/bin/env python3
"""Plan and merge fail-closed, independently guarded Kimi TB4 shards.

The planner snapshots a private 66-case universe and creates deterministic,
non-overlapping shard manifests/configs.  Every shard is launched as a fresh
``run_eval.sbatch`` run; failed attempts are never resumed.  The merger accepts
exactly one route-guard success receipt for every planned shard, revalidates
each receipt and eval identity, permits independently certified route
generations, proves exactly-once coverage, and runs the normal full TB4 audit
before publishing an atomic private result directory.

No task identifier is placed in plan, receipt, CLI output, or error text.
Task-bearing manifests and merged artifacts are always mode 0600.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import tomllib
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Sequence
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
PLAN_ALGORITHM = "ordered-contiguous-v1"
EXPECTED_MODEL = "Kimi-K3"
EXPECTED_TASK_COUNT = 66
EXPECTED_SUPPORTED_TASK_COUNT = 63
EXPECTED_UNSUPPORTED_TASK_COUNT = 3
EXPECTED_ROLLOUT_CONCURRENCY = 4
EXPECTED_LEASE_START_CONCURRENCY = 2
DEFAULT_MAX_SEQUENCE_TOKENS = 262_144
TASKSET_ID = "terminal-bench-vmvm"
EXPECTED_DENYLIST = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TABLE_RE = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")
ASSIGNMENT_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)(\s*=).*$")
MAX_PRIVATE_FILE_BYTES = 64 * 1024 * 1024
SHARDED_CERTIFICATE_TYPE = "terminal_bench_vmvm_tb4_sharded_certificate"
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": "/chat/completions",
    "request_model": EXPECTED_MODEL,
    "response_model": EXPECTED_MODEL,
    "request_reasoning_effort": "max",
    "request_chat_template_kwargs": {
        "enable_thinking": True,
        "preserve_thinking": True,
    },
}


class ShardWorkflowError(ValueError):
    """A private shard plan or independently certified shard is invalid."""


@dataclass(frozen=True)
class TaskEntry:
    identifier: str
    raw_line: bytes


@dataclass(frozen=True)
class PlannedShard:
    index: int
    task_count: int
    task_manifest: Path
    task_manifest_sha256: str
    config: Path
    config_sha256: str
    tasks: frozenset[str]


@dataclass(frozen=True)
class CertifiedShard:
    spec: PlannedShard
    run_dir: Path
    results: Path
    results_sha256: str
    results_count: int
    success_receipt: Path
    success_receipt_sha256: str
    success_receipt_file_sha256: str
    eval_run_identity_sha256: str
    route_generation_sha256: str
    endpoint_binding_sha256: str
    expected_routes: int
    trace_ids: frozenset[str]
    identity_semantics: dict[str, Any]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path, *, label: str) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ShardWorkflowError(f"{label}_unreadable")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except ShardWorkflowError:
        raise
    except OSError as error:
        raise ShardWorkflowError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after):
        raise ShardWorkflowError(f"{label}_changed")
    return digest.hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ShardWorkflowError("json_duplicate_key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ShardWorkflowError("json_non_finite_number")


def _load_json(raw: bytes, *, label: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ShardWorkflowError as error:
        raise ShardWorkflowError(f"{label}_invalid") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShardWorkflowError(f"{label}_invalid") from error


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _stable_read(
    path: Path,
    *,
    label: str,
    require_private: bool = False,
    limit: int = MAX_PRIVATE_FILE_BYTES,
) -> tuple[Path, bytes]:
    try:
        if path.is_symlink():
            raise ShardWorkflowError(f"{label}_unreadable")
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ShardWorkflowError(f"{label}_unreadable")
        if require_private and stat.S_IMODE(before.st_mode) != 0o600:
            raise ShardWorkflowError(f"{label}_not_private")
        with resolved.open("rb") as handle:
            raw = handle.read(limit + 1)
        after = resolved.stat()
    except ShardWorkflowError:
        raise
    except (OSError, RuntimeError) as error:
        raise ShardWorkflowError(f"{label}_unreadable") from error
    if len(raw) > limit:
        raise ShardWorkflowError(f"{label}_too_large")
    if _stat_signature(before) != _stat_signature(after):
        raise ShardWorkflowError(f"{label}_changed")
    return resolved, raw


def _private_write(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ShardWorkflowError("private_artifact_write_failed") from error


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_task_entries(raw: bytes, *, label: str) -> list[TaskEntry]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ShardWorkflowError(f"{label}_invalid") from error
    entries: list[TaskEntry] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        identifier = line.strip().split("\t", 1)[0]
        if not identifier:
            raise ShardWorkflowError(f"{label}_invalid")
        if identifier in seen:
            raise ShardWorkflowError(f"{label}_duplicates")
        seen.add(identifier)
        entries.append(TaskEntry(identifier=identifier, raw_line=line.encode("utf-8") + b"\n"))
    if not entries:
        raise ShardWorkflowError(f"{label}_empty")
    return entries


def _read_toml(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ShardWorkflowError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise ShardWorkflowError(f"{label}_invalid")
    return value


def _config_semantics(config: dict[str, Any]) -> dict[str, Any]:
    """Remove only per-run/per-shard selectors before semantic comparison."""

    value = copy.deepcopy(config)
    value.pop("output_dir", None)
    value.pop("num_tasks", None)
    taskset = value.get("taskset")
    client = value.get("client")
    if not isinstance(taskset, dict) or not isinstance(client, dict):
        raise ShardWorkflowError("config_semantics_invalid")
    if "tasks" in taskset:
        raise ShardWorkflowError("config_inline_tasks_forbidden")
    taskset.pop("task_file", None)
    taskset.pop("task_file_sha256", None)
    client.pop("base_url", None)
    return value


def _config_semantics_sha256(config: dict[str, Any]) -> str:
    return _sha256_bytes(canonical_json(_config_semantics(config)))


def _validate_base_config(config: dict[str, Any], universe_sha256: str) -> str:
    taskset = config.get("taskset")
    if (
        config.get("num_tasks") != EXPECTED_TASK_COUNT
        or not isinstance(taskset, dict)
        or taskset.get("id") != TASKSET_ID
        or "tasks" in taskset
        or taskset.get("task_file_sha256") != universe_sha256
    ):
        raise ShardWorkflowError("base_config_universe_mismatch")
    client = config.get("client")
    sampling = config.get("sampling")
    harness = config.get("harness")
    thinking = sampling.get("chat_template_kwargs") if isinstance(sampling, dict) else None
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    parsed_url = urlsplit(str(client.get("base_url", ""))) if isinstance(client, dict) else None
    if (
        config.get("model") != EXPECTED_MODEL
        or config.get("num_rollouts") != 1
        or config.get("retain_traces") is not False
        or config.get("rich") is not False
        or {config.get("max_input_tokens"), config.get("max_output_tokens"), config.get("max_total_tokens")}
        != {262_144}
        or not isinstance(client, dict)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or set(client.get("outbound_body_denylist") or []) != EXPECTED_DENYLIST
        or len(client.get("outbound_body_denylist") or []) != len(EXPECTED_DENYLIST)
        or client.get("headers") not in (None, {})
        or parsed_url is None
        or not parsed_url.scheme
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or bool(parsed_url.query)
        or bool(parsed_url.fragment)
        or not isinstance(sampling, dict)
        or sampling.get("reasoning_effort") != "max"
        or thinking != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(sampling.get("max_tokens"), int)
        or isinstance(sampling.get("max_tokens"), bool)
        or not 0 < sampling["max_tokens"] <= 262_144
        or not isinstance(runtime, dict)
        or runtime.get("type") != "vmvm"
    ):
        raise ShardWorkflowError("base_config_contract_invalid")
    for key in ("max_concurrent", "multiplex"):
        if config.get(key) != EXPECTED_ROLLOUT_CONCURRENCY:
            raise ShardWorkflowError("base_config_contract_invalid")
    for key in ("max_connections", "max_keepalive_connections"):
        if client.get(key) != EXPECTED_ROLLOUT_CONCURRENCY:
            raise ShardWorkflowError("base_config_contract_invalid")
    return _config_semantics_sha256(config)


def _render_shard_config(
    base_raw: bytes,
    *,
    task_manifest: Path,
    task_manifest_sha256: str,
    task_count: int,
) -> bytes:
    try:
        lines = base_raw.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as error:
        raise ShardWorkflowError("base_config_invalid") from error
    replacements = {
        ("", "num_tasks"): str(task_count),
        ("taskset", "task_file"): json.dumps(str(task_manifest)),
        ("taskset", "task_file_sha256"): json.dumps(task_manifest_sha256),
    }
    replaced: set[tuple[str, str]] = set()
    table = ""
    output: list[str] = []
    for line in lines:
        table_match = TABLE_RE.match(line.rstrip("\r\n"))
        if table_match:
            table = table_match.group(1).strip()
            output.append(line)
            continue
        assignment = ASSIGNMENT_RE.match(line.rstrip("\r\n"))
        key = assignment.group(2) if assignment else None
        target = (table, key) if key is not None else None
        if assignment is not None and target in replacements:
            if target in replaced:
                raise ShardWorkflowError("base_config_selection_ambiguous")
            ending = "\n" if line.endswith("\n") else ""
            output.append(
                f"{assignment.group(1)}{assignment.group(2)}{assignment.group(3)} {replacements[target]}{ending}"
            )
            replaced.add(target)
        else:
            output.append(line)
    if replaced != set(replacements):
        raise ShardWorkflowError("base_config_selection_missing")
    rendered = "".join(output).encode("utf-8")
    parsed = _read_toml(rendered, label="shard_config")
    taskset = parsed.get("taskset")
    if (
        parsed.get("num_tasks") != task_count
        or not isinstance(taskset, dict)
        or Path(str(taskset.get("task_file", ""))).resolve() != task_manifest
        or taskset.get("task_file_sha256") != task_manifest_sha256
    ):
        raise ShardWorkflowError("shard_config_selection_invalid")
    return rendered


def _plan_with_self_hash(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "plan_sha256": _sha256_bytes(canonical_json(body))}


def create_plan(
    universe_manifest: Path,
    universe_manifest_sha256: str,
    base_config: Path,
    output_dir: Path,
    *,
    shard_size: int,
) -> dict[str, Any]:
    """Create an immutable private plan without exposing task identifiers."""

    if SHA256_RE.fullmatch(universe_manifest_sha256) is None:
        raise ShardWorkflowError("universe_sha256_invalid")
    if shard_size < 1 or shard_size > EXPECTED_TASK_COUNT:
        raise ShardWorkflowError("shard_size_invalid")
    _, universe_raw = _stable_read(
        universe_manifest,
        label="universe_manifest",
        require_private=True,
    )
    if _sha256_bytes(universe_raw) != universe_manifest_sha256:
        raise ShardWorkflowError("universe_sha256_mismatch")
    entries = _parse_task_entries(universe_raw, label="universe_manifest")
    if len(entries) != EXPECTED_TASK_COUNT:
        raise ShardWorkflowError("universe_count_mismatch")
    _, base_raw = _stable_read(base_config, label="base_config")
    base_parsed = _read_toml(base_raw, label="base_config")
    semantics_sha256 = _validate_base_config(base_parsed, universe_manifest_sha256)

    try:
        resolved_output = output_dir.resolve(strict=False)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError) as error:
        raise ShardWorkflowError("plan_output_invalid") from error
    if resolved_output.exists():
        raise ShardWorkflowError("plan_output_exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{resolved_output.name}.tmp-", dir=resolved_output.parent))
    os.chmod(temporary, 0o700)
    final_universe = resolved_output / "universe.tasks.txt"
    final_base = resolved_output / "base_config.toml"
    try:
        _private_write(temporary / final_universe.name, universe_raw)
        _private_write(temporary / final_base.name, base_raw)
        shard_records: list[dict[str, Any]] = []
        for index, offset in enumerate(range(0, len(entries), shard_size)):
            shard_entries = entries[offset : offset + shard_size]
            manifest_name = f"shard-{index:03d}.tasks.txt"
            config_name = f"shard-{index:03d}.toml"
            final_manifest = resolved_output / manifest_name
            final_config = resolved_output / config_name
            manifest_raw = b"".join(entry.raw_line for entry in shard_entries)
            manifest_sha256 = _sha256_bytes(manifest_raw)
            config_raw = _render_shard_config(
                base_raw,
                task_manifest=final_manifest,
                task_manifest_sha256=manifest_sha256,
                task_count=len(shard_entries),
            )
            _private_write(temporary / manifest_name, manifest_raw)
            _private_write(temporary / config_name, config_raw)
            shard_records.append(
                {
                    "index": index,
                    "task_count": len(shard_entries),
                    "task_manifest": {
                        "path": str(final_manifest),
                        "sha256": manifest_sha256,
                    },
                    "config": {
                        "path": str(final_config),
                        "sha256": _sha256_bytes(config_raw),
                    },
                }
            )
        body = {
            "schema_version": SCHEMA_VERSION,
            "algorithm": PLAN_ALGORITHM,
            "expected_model": EXPECTED_MODEL,
            "universe": {
                "path": str(final_universe),
                "sha256": universe_manifest_sha256,
                "task_count": EXPECTED_TASK_COUNT,
            },
            "base_config": {
                "path": str(final_base),
                "sha256": _sha256_bytes(base_raw),
                "semantics_sha256": semantics_sha256,
            },
            "shard_size": shard_size,
            "shard_count": len(shard_records),
            "shards": shard_records,
        }
        plan = _plan_with_self_hash(body)
        _private_write(
            temporary / "plan.json",
            json.dumps(plan, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        )
        _fsync_directory(temporary)
        os.replace(temporary, resolved_output)
        _fsync_directory(resolved_output.parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return plan


def _artifact_record(value: Any, *, label: str, root: Path, filename: str) -> tuple[Path, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise ShardWorkflowError(f"{label}_invalid")
    expected = root / filename
    try:
        observed = Path(value["path"]).resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ShardWorkflowError(f"{label}_invalid") from error
    if observed != expected:
        raise ShardWorkflowError(f"{label}_path_mismatch")
    return expected, value["sha256"]


def load_plan(path: Path) -> tuple[dict[str, Any], tuple[PlannedShard, ...]]:
    resolved, raw = _stable_read(path, label="plan", require_private=True)
    value = _load_json(raw, label="plan")
    expected_keys = {
        "schema_version",
        "algorithm",
        "expected_model",
        "universe",
        "base_config",
        "shard_size",
        "shard_count",
        "shards",
        "plan_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ShardWorkflowError("plan_invalid")
    self_hash = value.get("plan_sha256")
    body = {key: item for key, item in value.items() if key != "plan_sha256"}
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("algorithm") != PLAN_ALGORITHM
        or value.get("expected_model") != EXPECTED_MODEL
        or not isinstance(self_hash, str)
        or self_hash != _sha256_bytes(canonical_json(body))
    ):
        raise ShardWorkflowError("plan_invalid")
    root = resolved.parent
    universe = value.get("universe")
    base = value.get("base_config")
    if (
        not isinstance(universe, dict)
        or set(universe) != {"path", "sha256", "task_count"}
        or universe.get("task_count") != EXPECTED_TASK_COUNT
        or not isinstance(base, dict)
        or set(base) != {"path", "sha256", "semantics_sha256"}
        or SHA256_RE.fullmatch(str(base.get("semantics_sha256", ""))) is None
    ):
        raise ShardWorkflowError("plan_invalid")
    universe_path, universe_sha = _artifact_record(
        {"path": universe.get("path"), "sha256": universe.get("sha256")},
        label="plan_universe",
        root=root,
        filename="universe.tasks.txt",
    )
    base_path, base_sha = _artifact_record(
        {"path": base.get("path"), "sha256": base.get("sha256")},
        label="plan_base_config",
        root=root,
        filename="base_config.toml",
    )
    _, universe_raw = _stable_read(universe_path, label="plan_universe", require_private=True)
    _, base_raw = _stable_read(base_path, label="plan_base_config", require_private=True)
    if _sha256_bytes(universe_raw) != universe_sha or _sha256_bytes(base_raw) != base_sha:
        raise ShardWorkflowError("plan_artifact_sha256_mismatch")
    universe_entries = _parse_task_entries(universe_raw, label="plan_universe")
    if len(universe_entries) != EXPECTED_TASK_COUNT:
        raise ShardWorkflowError("plan_universe_count_mismatch")
    base_config = _read_toml(base_raw, label="plan_base_config")
    if _validate_base_config(base_config, universe_sha) != base["semantics_sha256"]:
        raise ShardWorkflowError("plan_config_semantics_mismatch")

    shard_size = value.get("shard_size")
    shard_count = value.get("shard_count")
    records = value.get("shards")
    if (
        not isinstance(shard_size, int)
        or isinstance(shard_size, bool)
        or not 1 <= shard_size <= EXPECTED_TASK_COUNT
        or not isinstance(shard_count, int)
        or isinstance(shard_count, bool)
        or shard_count != math.ceil(EXPECTED_TASK_COUNT / shard_size)
        or not isinstance(records, list)
        or len(records) != shard_count
    ):
        raise ShardWorkflowError("plan_shards_invalid")
    universe_tasks = {entry.identifier for entry in universe_entries}
    observed_tasks: set[str] = set()
    shards: list[PlannedShard] = []
    for index, record in enumerate(records):
        if (
            not isinstance(record, dict)
            or set(record) != {"index", "task_count", "task_manifest", "config"}
            or record.get("index") != index
            or not isinstance(record.get("task_count"), int)
            or isinstance(record.get("task_count"), bool)
            or not 1 <= record["task_count"] <= shard_size
        ):
            raise ShardWorkflowError("plan_shards_invalid")
        manifest_path, manifest_sha = _artifact_record(
            record.get("task_manifest"),
            label="plan_shard_manifest",
            root=root,
            filename=f"shard-{index:03d}.tasks.txt",
        )
        config_path, config_sha = _artifact_record(
            record.get("config"),
            label="plan_shard_config",
            root=root,
            filename=f"shard-{index:03d}.toml",
        )
        _, manifest_raw = _stable_read(
            manifest_path,
            label="plan_shard_manifest",
            require_private=True,
        )
        _, config_raw = _stable_read(
            config_path,
            label="plan_shard_config",
            require_private=True,
        )
        if _sha256_bytes(manifest_raw) != manifest_sha or _sha256_bytes(config_raw) != config_sha:
            raise ShardWorkflowError("plan_artifact_sha256_mismatch")
        entries = _parse_task_entries(manifest_raw, label="plan_shard_manifest")
        tasks = {entry.identifier for entry in entries}
        if len(tasks) != record["task_count"] or observed_tasks & tasks:
            raise ShardWorkflowError("plan_partition_invalid")
        observed_tasks.update(tasks)
        config = _read_toml(config_raw, label="plan_shard_config")
        taskset = config.get("taskset")
        if (
            config.get("num_tasks") != len(tasks)
            or not isinstance(taskset, dict)
            or Path(str(taskset.get("task_file", ""))).resolve() != manifest_path
            or taskset.get("task_file_sha256") != manifest_sha
            or _config_semantics_sha256(config) != base["semantics_sha256"]
        ):
            raise ShardWorkflowError("plan_shard_config_invalid")
        shards.append(
            PlannedShard(
                index=index,
                task_count=len(tasks),
                task_manifest=manifest_path,
                task_manifest_sha256=manifest_sha,
                config=config_path,
                config_sha256=config_sha,
                tasks=frozenset(tasks),
            )
        )
    if observed_tasks != universe_tasks:
        raise ShardWorkflowError("plan_partition_invalid")
    return value, tuple(shards)


@contextmanager
def _hold_writer_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / ".writer.lock"
    try:
        with lock_path.open("rb") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ShardWorkflowError("shard_still_running") from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    except ShardWorkflowError:
        raise
    except OSError as error:
        raise ShardWorkflowError("shard_writer_lock_invalid") from error


def _scan_results(path: Path, expected_tasks: frozenset[str]) -> tuple[str, frozenset[str], int]:
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    trace_ids: set[str] = set()
    try:
        with path.open("rb") as handle:
            for raw in handle:
                digest.update(raw)
                if not raw.endswith(b"\n") or not raw.strip():
                    raise ShardWorkflowError("shard_results_incomplete")
                row = _load_json(raw, label="shard_results")
                if not isinstance(row, dict):
                    raise ShardWorkflowError("shard_results_invalid")
                trace_id = row.get("id")
                if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
                    raise ShardWorkflowError("shard_trace_identity_invalid")
                trace_ids.add(trace_id)
                task_value = row.get("task") or {}
                if not isinstance(task_value, dict):
                    raise ShardWorkflowError("shard_task_identity_invalid")
                task = task_value.get("slug") or str(task_value.get("name", "")).rsplit("/", 1)[-1]
                if not task:
                    raise ShardWorkflowError("shard_task_identity_invalid")
                counts[task] += 1
    except ShardWorkflowError:
        raise
    except OSError as error:
        raise ShardWorkflowError("shard_results_unreadable") from error
    if (
        sum(counts.values()) != len(expected_tasks)
        or set(counts) != set(expected_tasks)
        or any(count != 1 for count in counts.values())
    ):
        raise ShardWorkflowError("shard_results_not_exactly_once")
    return digest.hexdigest(), frozenset(trace_ids), sum(counts.values())


def _identity_semantics(
    identity: dict[str, Any],
    *,
    resolved_config_semantics_sha256: str,
) -> dict[str, Any]:
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict):
        raise ShardWorkflowError("shard_identity_invalid")
    spec = deployment.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("sha256"), str):
        raise ShardWorkflowError("shard_identity_invalid")
    return {
        "source": identity.get("source"),
        "dataset": identity.get("dataset"),
        "contract": identity.get("contract"),
        "execution": identity.get("execution"),
        "resolved_config_semantics_sha256": resolved_config_semantics_sha256,
        "deployment": {
            "id": deployment.get("id"),
            "spec_sha256": spec.get("sha256"),
            "routing": deployment.get("routing"),
            "proxy_policy": deployment.get("proxy_policy"),
        },
    }


def _certify_shard(
    receipt_path: Path,
    shards_by_manifest: dict[str, PlannedShard],
    *,
    expected_semantics_sha256: str,
) -> CertifiedShard:
    from eval_run_identity import EvalIdentityError, load_eval_run_identity
    from guard_success_receipt import (
        GuardReceiptError,
        load_guard_success_receipt,
        validate_guard_success_linkage,
    )

    resolved_receipt, receipt_raw = _stable_read(
        receipt_path,
        label="shard_success_receipt",
        require_private=True,
    )
    try:
        receipt = load_guard_success_receipt(receipt_path)
        artifacts = receipt["artifacts"]
        identity_path = Path(artifacts["eval_run_identity"]["path"])
        envelope = load_eval_run_identity(identity_path, verify_references=True)
    except (OSError, GuardReceiptError, EvalIdentityError, KeyError, TypeError) as error:
        raise ShardWorkflowError("shard_success_receipt_invalid") from error
    identity = envelope.get("identity")
    if not isinstance(identity, dict) or identity.get("role") != "tb4":
        raise ShardWorkflowError("shard_identity_role_invalid")
    inputs = identity.get("inputs")
    config_section = identity.get("config")
    deployment = identity.get("deployment")
    if not all(isinstance(value, dict) for value in (inputs, config_section, deployment)):
        raise ShardWorkflowError("shard_identity_invalid")
    execution = identity.get("execution")
    vmvm_environment = execution.get("vmvm_environment") if isinstance(execution, dict) else None
    if (
        not isinstance(execution, dict)
        or execution.get("rollout_concurrency") != EXPECTED_ROLLOUT_CONCURRENCY
        or execution.get("multiplex") != EXPECTED_ROLLOUT_CONCURRENCY
        or execution.get("http_max_connections") != EXPECTED_ROLLOUT_CONCURRENCY
        or execution.get("http_max_keepalive_connections") != EXPECTED_ROLLOUT_CONCURRENCY
        or not isinstance(vmvm_environment, dict)
        or vmvm_environment.get("lease_start_concurrency") != EXPECTED_LEASE_START_CONCURRENCY
    ):
        raise ShardWorkflowError("shard_execution_contract_invalid")
    task_record = inputs.get("task_file")
    resolved_config_record = config_section.get("resolved")
    source_config_record = config_section.get("source")
    if not all(isinstance(value, dict) for value in (task_record, resolved_config_record, source_config_record)):
        raise ShardWorkflowError("shard_identity_invalid")
    manifest_sha = task_record.get("sha256")
    spec = shards_by_manifest.get(manifest_sha)
    if spec is None or task_record.get("count") != spec.task_count:
        raise ShardWorkflowError("shard_not_in_plan")
    if source_config_record.get("sha256") != spec.config_sha256:
        raise ShardWorkflowError("shard_source_config_mismatch")
    _, source_config_raw = _stable_read(
        Path(str(source_config_record.get("path", ""))),
        label="shard_source_config",
    )
    if (
        _config_semantics_sha256(_read_toml(source_config_raw, label="shard_source_config"))
        != expected_semantics_sha256
    ):
        raise ShardWorkflowError("shard_source_config_semantics_mismatch")
    task_snapshot = Path(str(task_record.get("path", "")))
    _, snapshot_raw = _stable_read(
        task_snapshot,
        label="shard_task_snapshot",
        require_private=True,
    )
    if _sha256_bytes(snapshot_raw) != spec.task_manifest_sha256:
        raise ShardWorkflowError("shard_task_snapshot_mismatch")
    snapshot_tasks = frozenset(
        entry.identifier for entry in _parse_task_entries(snapshot_raw, label="shard_task_snapshot")
    )
    if snapshot_tasks != spec.tasks:
        raise ShardWorkflowError("shard_task_snapshot_mismatch")
    _, resolved_config_raw = _stable_read(
        Path(str(resolved_config_record.get("path", ""))),
        label="shard_resolved_config",
    )
    resolved_config = _read_toml(resolved_config_raw, label="shard_resolved_config")
    resolved_semantics_sha256 = _config_semantics_sha256(resolved_config)

    run_dir = resolved_receipt.parent
    results_path = Path(artifacts["results"]["path"])
    try:
        validate_guard_success_linkage(
            receipt,
            run_dir=run_dir,
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            eval_run_role="tb4",
            eval_run_identity_file_sha256=artifacts["eval_run_identity"]["sha256"],
            results_sha256=artifacts["results"]["sha256"],
            deployment_id=deployment["id"],
            deployment_spec_sha256=deployment["spec"]["sha256"],
            readiness_checkpoint=deployment["readiness_checkpoint"],
            endpoint=deployment["endpoint"],
            serving_route_generation=deployment["serving_route_generation"],
            proxy_policy=deployment["proxy_policy"],
        )
    except (OSError, GuardReceiptError, KeyError, TypeError) as error:
        raise ShardWorkflowError("shard_success_receipt_linkage_invalid") from error
    results_sha, trace_ids, result_count = _scan_results(results_path, spec.tasks)
    if results_sha != artifacts["results"]["sha256"]:
        raise ShardWorkflowError("shard_results_sha256_mismatch")
    route_generation = deployment["serving_route_generation"]
    routes = route_generation.get("routes") if isinstance(route_generation, dict) else None
    if not isinstance(routes, list) or not routes:
        raise ShardWorkflowError("shard_route_generation_invalid")
    return CertifiedShard(
        spec=spec,
        run_dir=run_dir,
        results=results_path,
        results_sha256=results_sha,
        results_count=result_count,
        success_receipt=resolved_receipt,
        success_receipt_sha256=receipt["guard_success_receipt_sha256"],
        success_receipt_file_sha256=_sha256_bytes(receipt_raw),
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        route_generation_sha256=_sha256_bytes(canonical_json(route_generation)),
        endpoint_binding_sha256=_sha256_bytes(canonical_json(deployment["endpoint"])),
        expected_routes=len(routes),
        trace_ids=trace_ids,
        identity_semantics=_identity_semantics(
            identity,
            resolved_config_semantics_sha256=resolved_semantics_sha256,
        ),
    )


def _copy_file(source: Path, output: BinaryIO) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def _dataset_tasks(dataset_dir: Path) -> set[str]:
    try:
        return {
            path.name
            for path in dataset_dir.iterdir()
            if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
        }
    except OSError as error:
        raise ShardWorkflowError("dataset_unreadable") from error


def _run_full_audit(
    results: Path,
    *,
    dataset_dir: Path,
    min_supported_pass_rate: float,
    max_supported_pass_rate: float,
    max_sequence_tokens: int,
) -> tuple[dict[str, Any], bool]:
    try:
        from audit_tb4_results import audit_results

        return audit_results(
            results,
            dataset_dir=dataset_dir,
            min_supported_pass_rate=min_supported_pass_rate,
            max_supported_pass_rate=max_supported_pass_rate,
            max_sequence_tokens=max_sequence_tokens,
        )
    except Exception as error:
        raise ShardWorkflowError("combined_audit_unavailable") from error


def merge_shards(
    plan_path: Path,
    success_receipts: Sequence[Path],
    *,
    output_dir: Path,
    dataset_dir: Path,
    min_supported_pass_rate: float = 0.04,
    max_supported_pass_rate: float = 0.22,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> dict[str, Any]:
    """Publish a full result only from one certified success per planned shard."""

    plan, planned = load_plan(plan_path)
    if len(success_receipts) != len(planned):
        raise ShardWorkflowError("success_receipt_count_mismatch")
    resolved_receipts: list[Path] = []
    for path in success_receipts:
        resolved, _ = _stable_read(
            path,
            label="shard_success_receipt",
            require_private=True,
        )
        if resolved.name != "route_guard_success.json":
            raise ShardWorkflowError("shard_success_receipt_path_invalid")
        resolved_receipts.append(resolved)
    if len({str(path) for path in resolved_receipts}) != len(resolved_receipts):
        raise ShardWorkflowError("success_receipt_duplicate")
    if not 0 <= min_supported_pass_rate <= max_supported_pass_rate <= 1:
        raise ShardWorkflowError("audit_score_bounds_invalid")
    if max_sequence_tokens < 1:
        raise ShardWorkflowError("audit_sequence_limit_invalid")
    resolved_dataset = dataset_dir.resolve(strict=True)
    universe_path = Path(plan["universe"]["path"])
    _, universe_raw = _stable_read(
        universe_path,
        label="plan_universe",
        require_private=True,
    )
    universe_tasks = {entry.identifier for entry in _parse_task_entries(universe_raw, label="plan_universe")}
    if _dataset_tasks(resolved_dataset) != universe_tasks:
        raise ShardWorkflowError("dataset_universe_mismatch")
    shards_by_manifest = {shard.task_manifest_sha256: shard for shard in planned}
    receipt_paths = tuple(resolved_receipts)
    run_dirs = tuple(path.parent for path in receipt_paths)

    certified_by_index: dict[int, CertifiedShard] = {}
    all_trace_ids: set[str] = set()
    baseline_semantics: bytes | None = None
    with ExitStack() as stack:
        for run_dir in sorted(set(run_dirs), key=str):
            stack.enter_context(_hold_writer_lock(run_dir))
        for receipt_path in receipt_paths:
            certified = _certify_shard(
                receipt_path,
                shards_by_manifest,
                expected_semantics_sha256=plan["base_config"]["semantics_sha256"],
            )
            index = certified.spec.index
            if index in certified_by_index:
                raise ShardWorkflowError("multiple_successes_for_shard")
            semantics = canonical_json(certified.identity_semantics)
            if baseline_semantics is None:
                baseline_semantics = semantics
            elif semantics != baseline_semantics:
                raise ShardWorkflowError("shard_identity_semantics_mismatch")
            if all_trace_ids & set(certified.trace_ids):
                raise ShardWorkflowError("cross_shard_trace_identity_duplicate")
            all_trace_ids.update(certified.trace_ids)
            certified_by_index[index] = certified
        if set(certified_by_index) != set(range(len(planned))):
            raise ShardWorkflowError("success_receipt_coverage_incomplete")
        if len(all_trace_ids) != EXPECTED_TASK_COUNT:
            raise ShardWorkflowError("combined_trace_count_mismatch")

        resolved_output = output_dir.resolve(strict=False)
        if resolved_output.exists():
            raise ShardWorkflowError("merge_output_exists")
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{resolved_output.name}.tmp-", dir=resolved_output.parent))
        os.chmod(temporary, 0o700)
        try:
            combined_path = temporary / "results.jsonl"
            descriptor = os.open(combined_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                for index in range(len(planned)):
                    certified = certified_by_index[index]
                    if _copy_file(certified.results, output) != certified.results_sha256:
                        raise ShardWorkflowError("shard_results_changed")
                output.flush()
                os.fsync(output.fileno())
            summary, failed = _run_full_audit(
                combined_path,
                dataset_dir=resolved_dataset,
                min_supported_pass_rate=min_supported_pass_rate,
                max_supported_pass_rate=max_supported_pass_rate,
                max_sequence_tokens=max_sequence_tokens,
            )
            if failed:
                raise ShardWorkflowError("combined_audit_failed")
            try:
                observed_traces = summary["observed_traces"]
                supported_tasks = summary["supported_tasks"]
                unsupported_tasks = len(summary["observed_unsupported_tasks"])
                supported_passes = summary["supported_passes"]
                trace_failures = summary["trace_failures"]
                supported_trace_failures = summary["supported_trace_failures"]
                unsupported_trace_failures = summary["unsupported_trace_failures"]
                global_problems = len(summary["global_problems"])
                supported_pass_rate = summary["supported_pass_rate"]
                all_task_pass_rate = summary["all_task_pass_rate"]
            except (KeyError, TypeError) as error:
                raise ShardWorkflowError("combined_audit_schema_invalid") from error
            if (
                observed_traces != EXPECTED_TASK_COUNT
                or supported_tasks != EXPECTED_SUPPORTED_TASK_COUNT
                or unsupported_tasks != EXPECTED_UNSUPPORTED_TASK_COUNT
                or trace_failures != 0
                or supported_trace_failures != 0
                or unsupported_trace_failures != 0
                or global_problems != 0
                or not isinstance(supported_passes, int)
                or isinstance(supported_passes, bool)
                or not 0 <= supported_passes <= EXPECTED_SUPPORTED_TASK_COUNT
                or not isinstance(supported_pass_rate, (int, float))
                or isinstance(supported_pass_rate, bool)
                or not isinstance(all_task_pass_rate, (int, float))
                or isinstance(all_task_pass_rate, bool)
            ):
                raise ShardWorkflowError("combined_audit_schema_invalid")
            audit_raw = json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            audit_path = temporary / "audit_summary.json"
            _private_write(audit_path, audit_raw)
            shard_records = [
                {
                    "index": index,
                    "task_count": certified_by_index[index].results_count,
                    "task_manifest_sha256": certified_by_index[index].spec.task_manifest_sha256,
                    "guard_success_receipt_sha256": certified_by_index[index].success_receipt_sha256,
                    "guard_success_receipt": {
                        "path": str(certified_by_index[index].success_receipt),
                        "sha256": certified_by_index[index].success_receipt_file_sha256,
                    },
                    "eval_run_identity_sha256": certified_by_index[index].eval_run_identity_sha256,
                    "results_sha256": certified_by_index[index].results_sha256,
                    "route_generation_sha256": certified_by_index[index].route_generation_sha256,
                    "endpoint_binding_sha256": certified_by_index[index].endpoint_binding_sha256,
                    "expected_routes": certified_by_index[index].expected_routes,
                }
                for index in range(len(planned))
            ]
            combined_results_sha256 = _sha256_file(
                combined_path,
                label="combined_results",
            )
            plan_file_sha256 = _sha256_file(plan_path.resolve(strict=True), label="plan")
            deployment_semantics = certified_by_index[0].identity_semantics["deployment"]
            expected_routes = max(record["expected_routes"] for record in shard_records)
            body = {
                "schema_version": 2,
                "artifact_type": SHARDED_CERTIFICATE_TYPE,
                "state": "passed",
                "ok": True,
                "plan": {
                    "path": str(plan_path.resolve(strict=True)),
                    "sha256": plan_file_sha256,
                    "plan_sha256": plan["plan_sha256"],
                },
                "universe_sha256": plan["universe"]["sha256"],
                "universe_task_count": EXPECTED_TASK_COUNT,
                "config_semantics_sha256": plan["base_config"]["semantics_sha256"],
                "resolved_config_semantics_sha256": certified_by_index[0].identity_semantics[
                    "resolved_config_semantics_sha256"
                ],
                "deployment": {
                    "id": deployment_semantics["id"],
                    "spec_sha256": deployment_semantics["spec_sha256"],
                    "proxy_policy_sha256": _sha256_bytes(canonical_json(deployment_semantics["proxy_policy"])),
                },
                "audit_policy": {
                    "expected_tasks": EXPECTED_TASK_COUNT,
                    "expected_supported_tasks": EXPECTED_SUPPORTED_TASK_COUNT,
                    "expected_cpu_unsupported_tasks": EXPECTED_UNSUPPORTED_TASK_COUNT,
                    "rollouts_per_task": 1,
                    "model": EXPECTED_MODEL,
                    "reasoning_effort": "max",
                    "max_sequence_tokens": max_sequence_tokens,
                    "rollout_concurrency": EXPECTED_ROLLOUT_CONCURRENCY,
                    "lease_start_concurrency": EXPECTED_LEASE_START_CONCURRENCY,
                    "require_reasoning": True,
                    "require_response": True,
                    "require_model_io": True,
                    "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
                    "require_tool_schemas": True,
                    "require_tool_call_lineage": True,
                    "require_token_data": False,
                    "require_logprobs": False,
                    "binary_solved_reward": True,
                    "min_supported_pass_rate": min_supported_pass_rate,
                    "max_supported_pass_rate": max_supported_pass_rate,
                },
                "counts": {
                    "observed_traces": observed_traces,
                    "supported_tasks": supported_tasks,
                    "cpu_unsupported_tasks": unsupported_tasks,
                    "supported_passes": supported_passes,
                    "trace_failures": trace_failures,
                    "supported_trace_failures": supported_trace_failures,
                    "cpu_unsupported_trace_failures": unsupported_trace_failures,
                    "global_problems": global_problems,
                },
                "scores": {
                    "supported_pass_rate": supported_pass_rate,
                    "all_task_pass_rate": all_task_pass_rate,
                },
                "artifacts": {
                    "results": {
                        "path": str(resolved_output / "results.jsonl"),
                        "sha256": combined_results_sha256,
                    },
                    "audit_summary": {
                        "path": str(resolved_output / "audit_summary.json"),
                        "sha256": _sha256_bytes(audit_raw),
                    },
                },
                "combined_trace_count": EXPECTED_TASK_COUNT,
                "expected_routes": expected_routes,
                "distinct_route_generations": len({record["route_generation_sha256"] for record in shard_records}),
                "shard_count": len(shard_records),
                "shards": shard_records,
            }
            receipt = {
                **body,
                "tb4_certificate_sha256": _sha256_bytes(canonical_json(body)),
            }
            _private_write(
                temporary / "checkpoint.json",
                json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            )
            _fsync_directory(temporary)
            os.replace(temporary, resolved_output)
            _fsync_directory(resolved_output.parent)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    return receipt


def _checkpoint_artifact(value: Any, *, label: str) -> tuple[Path, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise ShardWorkflowError(f"{label}_invalid")
    try:
        configured = Path(value["path"])
        if configured.is_symlink():
            raise ShardWorkflowError(f"{label}_unreadable")
        path = configured.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ShardWorkflowError(f"{label}_unreadable") from error
    if _sha256_file(path, label=label) != value["sha256"]:
        raise ShardWorkflowError(f"{label}_sha256_mismatch")
    return path, value["sha256"]


def _validate_aggregate_sections(value: dict[str, Any]) -> tuple[int, float, float]:
    expected_policy = {
        "expected_tasks": EXPECTED_TASK_COUNT,
        "expected_supported_tasks": EXPECTED_SUPPORTED_TASK_COUNT,
        "expected_cpu_unsupported_tasks": EXPECTED_UNSUPPORTED_TASK_COUNT,
        "rollouts_per_task": 1,
        "model": EXPECTED_MODEL,
        "reasoning_effort": "max",
        "max_sequence_tokens": DEFAULT_MAX_SEQUENCE_TOKENS,
        "rollout_concurrency": EXPECTED_ROLLOUT_CONCURRENCY,
        "lease_start_concurrency": EXPECTED_LEASE_START_CONCURRENCY,
        "require_reasoning": True,
        "require_response": True,
        "require_model_io": True,
        "model_io_contract": EXPECTED_MODEL_IO_CONTRACT,
        "require_tool_schemas": True,
        "require_tool_call_lineage": True,
        "require_token_data": False,
        "require_logprobs": False,
        "binary_solved_reward": True,
        "min_supported_pass_rate": 0.04,
        "max_supported_pass_rate": 0.22,
    }
    if canonical_json(value.get("audit_policy")) != canonical_json(expected_policy):
        raise ShardWorkflowError("sharded_checkpoint_policy_invalid")
    counts = value.get("counts")
    expected_count_keys = {
        "observed_traces",
        "supported_tasks",
        "cpu_unsupported_tasks",
        "supported_passes",
        "trace_failures",
        "supported_trace_failures",
        "cpu_unsupported_trace_failures",
        "global_problems",
    }
    if not isinstance(counts, dict) or set(counts) != expected_count_keys:
        raise ShardWorkflowError("sharded_checkpoint_counts_invalid")
    if any(not isinstance(counts[key], int) or isinstance(counts[key], bool) or counts[key] < 0 for key in counts):
        raise ShardWorkflowError("sharded_checkpoint_counts_invalid")
    supported_passes = counts["supported_passes"]
    if (
        counts["observed_traces"] != EXPECTED_TASK_COUNT
        or counts["supported_tasks"] != EXPECTED_SUPPORTED_TASK_COUNT
        or counts["cpu_unsupported_tasks"] != EXPECTED_UNSUPPORTED_TASK_COUNT
        or counts["trace_failures"] != 0
        or counts["supported_trace_failures"] != 0
        or counts["cpu_unsupported_trace_failures"] != 0
        or counts["global_problems"] != 0
        or supported_passes > EXPECTED_SUPPORTED_TASK_COUNT
    ):
        raise ShardWorkflowError("sharded_checkpoint_counts_invalid")
    scores = value.get("scores")
    if not isinstance(scores, dict) or set(scores) != {
        "supported_pass_rate",
        "all_task_pass_rate",
    }:
        raise ShardWorkflowError("sharded_checkpoint_scores_invalid")
    supported_rate = scores["supported_pass_rate"]
    all_rate = scores["all_task_pass_rate"]
    if (
        not isinstance(supported_rate, (int, float))
        or isinstance(supported_rate, bool)
        or not isinstance(all_rate, (int, float))
        or isinstance(all_rate, bool)
        or not math.isfinite(float(supported_rate))
        or not math.isfinite(float(all_rate))
        or not math.isclose(
            float(supported_rate),
            supported_passes / EXPECTED_SUPPORTED_TASK_COUNT,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or not math.isclose(
            float(all_rate),
            supported_passes / EXPECTED_TASK_COUNT,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or not 0.04 <= float(supported_rate) <= 0.22
    ):
        raise ShardWorkflowError("sharded_checkpoint_scores_invalid")
    return supported_passes, float(supported_rate), float(all_rate)


def validate_sharded_checkpoint(
    value: dict[str, Any],
    *,
    deployment_id: str,
) -> dict[str, Any]:
    """Revalidate a schema-v2 checkpoint for the launch-certificate adapter."""

    expected_keys = {
        "schema_version",
        "artifact_type",
        "state",
        "ok",
        "plan",
        "universe_sha256",
        "universe_task_count",
        "config_semantics_sha256",
        "resolved_config_semantics_sha256",
        "deployment",
        "audit_policy",
        "counts",
        "scores",
        "artifacts",
        "combined_trace_count",
        "expected_routes",
        "distinct_route_generations",
        "shard_count",
        "shards",
        "tb4_certificate_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ShardWorkflowError("sharded_checkpoint_invalid")
    self_hash = value.get("tb4_certificate_sha256")
    body = {key: item for key, item in value.items() if key != "tb4_certificate_sha256"}
    if (
        value.get("schema_version") != 2
        or value.get("artifact_type") != SHARDED_CERTIFICATE_TYPE
        or value.get("state") != "passed"
        or value.get("ok") is not True
        or not isinstance(self_hash, str)
        or self_hash != _sha256_bytes(canonical_json(body))
        or value.get("universe_task_count") != EXPECTED_TASK_COUNT
        or value.get("combined_trace_count") != EXPECTED_TASK_COUNT
    ):
        raise ShardWorkflowError("sharded_checkpoint_invalid")
    supported_passes, supported_rate, all_rate = _validate_aggregate_sections(value)
    plan_record = value.get("plan")
    if (
        not isinstance(plan_record, dict)
        or set(plan_record) != {"path", "sha256", "plan_sha256"}
        or not isinstance(plan_record.get("plan_sha256"), str)
    ):
        raise ShardWorkflowError("sharded_checkpoint_plan_invalid")
    plan_path, _ = _checkpoint_artifact(
        {"path": plan_record.get("path"), "sha256": plan_record.get("sha256")},
        label="sharded_checkpoint_plan",
    )
    plan, planned = load_plan(plan_path)
    if (
        plan["plan_sha256"] != plan_record["plan_sha256"]
        or plan["universe"]["sha256"] != value.get("universe_sha256")
        or plan["base_config"]["semantics_sha256"] != value.get("config_semantics_sha256")
    ):
        raise ShardWorkflowError("sharded_checkpoint_plan_mismatch")
    deployment = value.get("deployment")
    if (
        not isinstance(deployment, dict)
        or set(deployment) != {"id", "spec_sha256", "proxy_policy_sha256"}
        or deployment.get("id") != deployment_id
        or SHA256_RE.fullmatch(str(deployment.get("spec_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("proxy_policy_sha256", ""))) is None
    ):
        raise ShardWorkflowError("sharded_checkpoint_deployment_invalid")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"results", "audit_summary"}:
        raise ShardWorkflowError("sharded_checkpoint_artifacts_invalid")
    combined_path, combined_sha256 = _checkpoint_artifact(
        artifacts["results"],
        label="sharded_checkpoint_results",
    )
    audit_path, _ = _checkpoint_artifact(
        artifacts["audit_summary"],
        label="sharded_checkpoint_audit",
    )
    if (
        combined_path.name != "results.jsonl"
        or audit_path.name != "audit_summary.json"
        or combined_path.parent != audit_path.parent
        or stat.S_IMODE(combined_path.stat().st_mode) != 0o600
        or stat.S_IMODE(audit_path.stat().st_mode) != 0o600
    ):
        raise ShardWorkflowError("sharded_checkpoint_artifacts_invalid")

    shard_records = value.get("shards")
    if (
        not isinstance(shard_records, list)
        or value.get("shard_count") != len(planned)
        or len(shard_records) != len(planned)
    ):
        raise ShardWorkflowError("sharded_checkpoint_shards_invalid")
    shards_by_manifest = {shard.task_manifest_sha256: shard for shard in planned}
    receipt_paths: list[Path] = []
    records_by_index: dict[int, dict[str, Any]] = {}
    for record in shard_records:
        expected_record_keys = {
            "index",
            "task_count",
            "task_manifest_sha256",
            "guard_success_receipt_sha256",
            "guard_success_receipt",
            "eval_run_identity_sha256",
            "results_sha256",
            "route_generation_sha256",
            "endpoint_binding_sha256",
            "expected_routes",
        }
        if not isinstance(record, dict) or set(record) != expected_record_keys:
            raise ShardWorkflowError("sharded_checkpoint_shards_invalid")
        index = record.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index in records_by_index:
            raise ShardWorkflowError("sharded_checkpoint_shards_invalid")
        for key in (
            "task_manifest_sha256",
            "guard_success_receipt_sha256",
            "eval_run_identity_sha256",
            "results_sha256",
            "route_generation_sha256",
            "endpoint_binding_sha256",
        ):
            if SHA256_RE.fullmatch(str(record.get(key, ""))) is None:
                raise ShardWorkflowError("sharded_checkpoint_shards_invalid")
        receipt_path, _ = _checkpoint_artifact(
            record.get("guard_success_receipt"),
            label="sharded_checkpoint_guard_receipt",
        )
        if stat.S_IMODE(receipt_path.stat().st_mode) != 0o600:
            raise ShardWorkflowError("sharded_checkpoint_guard_receipt_not_private")
        receipt_paths.append(receipt_path)
        records_by_index[index] = record
    if set(records_by_index) != set(range(len(planned))):
        raise ShardWorkflowError("sharded_checkpoint_shards_invalid")

    certified_by_index: dict[int, CertifiedShard] = {}
    all_trace_ids: set[str] = set()
    baseline_semantics: bytes | None = None
    with ExitStack() as stack:
        for run_dir in sorted({path.parent for path in receipt_paths}, key=str):
            stack.enter_context(_hold_writer_lock(run_dir))
        for receipt_path in receipt_paths:
            certified = _certify_shard(
                receipt_path,
                shards_by_manifest,
                expected_semantics_sha256=plan["base_config"]["semantics_sha256"],
            )
            index = certified.spec.index
            record = records_by_index.get(index)
            if record is None or index in certified_by_index:
                raise ShardWorkflowError("sharded_checkpoint_shards_invalid")
            expected_record = {
                "index": index,
                "task_count": certified.results_count,
                "task_manifest_sha256": certified.spec.task_manifest_sha256,
                "guard_success_receipt_sha256": certified.success_receipt_sha256,
                "guard_success_receipt": {
                    "path": str(certified.success_receipt),
                    "sha256": certified.success_receipt_file_sha256,
                },
                "eval_run_identity_sha256": certified.eval_run_identity_sha256,
                "results_sha256": certified.results_sha256,
                "route_generation_sha256": certified.route_generation_sha256,
                "endpoint_binding_sha256": certified.endpoint_binding_sha256,
                "expected_routes": certified.expected_routes,
            }
            if record != expected_record:
                raise ShardWorkflowError("sharded_checkpoint_shard_mismatch")
            semantics = canonical_json(certified.identity_semantics)
            if baseline_semantics is None:
                baseline_semantics = semantics
            elif semantics != baseline_semantics:
                raise ShardWorkflowError("shard_identity_semantics_mismatch")
            if all_trace_ids & set(certified.trace_ids):
                raise ShardWorkflowError("cross_shard_trace_identity_duplicate")
            all_trace_ids.update(certified.trace_ids)
            certified_by_index[index] = certified
    if len(certified_by_index) != len(planned) or len(all_trace_ids) != EXPECTED_TASK_COUNT:
        raise ShardWorkflowError("sharded_checkpoint_coverage_invalid")
    first_semantics = certified_by_index[0].identity_semantics
    deployment_semantics = first_semantics["deployment"]
    if (
        first_semantics.get("resolved_config_semantics_sha256") != value.get("resolved_config_semantics_sha256")
        or deployment_semantics.get("id") != deployment_id
        or deployment_semantics.get("spec_sha256") != deployment["spec_sha256"]
        or _sha256_bytes(canonical_json(deployment_semantics.get("proxy_policy"))) != deployment["proxy_policy_sha256"]
        or max(shard.expected_routes for shard in certified_by_index.values()) != value.get("expected_routes")
        or len({shard.route_generation_sha256 for shard in certified_by_index.values()})
        != value.get("distinct_route_generations")
    ):
        raise ShardWorkflowError("sharded_checkpoint_semantics_invalid")

    universe_path = Path(plan["universe"]["path"])
    _, universe_raw = _stable_read(
        universe_path,
        label="plan_universe",
        require_private=True,
    )
    universe_tasks = frozenset(entry.identifier for entry in _parse_task_entries(universe_raw, label="plan_universe"))
    observed_combined_sha, combined_trace_ids, combined_count = _scan_results(
        combined_path,
        universe_tasks,
    )
    if (
        observed_combined_sha != combined_sha256
        or combined_count != EXPECTED_TASK_COUNT
        or combined_trace_ids != frozenset(all_trace_ids)
    ):
        raise ShardWorkflowError("sharded_checkpoint_results_invalid")
    dataset = first_semantics.get("dataset")
    dataset_path = dataset.get("path") if isinstance(dataset, dict) else None
    if not isinstance(dataset_path, str):
        raise ShardWorkflowError("sharded_checkpoint_dataset_invalid")
    summary, failed = _run_full_audit(
        combined_path,
        dataset_dir=Path(dataset_path),
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
        max_sequence_tokens=DEFAULT_MAX_SEQUENCE_TOKENS,
    )
    _, audit_raw = _stable_read(
        audit_path,
        label="sharded_checkpoint_audit",
        require_private=True,
    )
    audit_value = _load_json(audit_raw, label="sharded_checkpoint_audit")
    if failed or canonical_json(audit_value) != canonical_json(summary):
        raise ShardWorkflowError("sharded_checkpoint_audit_invalid")
    return {
        "certificate_sha256": self_hash,
        "deployment_spec_sha256": deployment["spec_sha256"],
        "expected_routes": value["expected_routes"],
        "route_generation_sha256s": sorted({record["route_generation_sha256"] for record in shard_records}),
        "endpoint_binding_sha256s": sorted({record["endpoint_binding_sha256"] for record in shard_records}),
        "proxy_policy_sha256": deployment["proxy_policy_sha256"],
        "shard_count": len(planned),
        "supported_pass_rate": supported_rate,
        "all_task_pass_rate": all_rate,
        "supported_passes": supported_passes,
        "sharded": True,
    }


def _rate(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="create private shard manifests and configs")
    plan.add_argument("--universe-manifest", type=Path, required=True)
    plan.add_argument("--universe-manifest-sha256", required=True)
    plan.add_argument("--base-config", type=Path, required=True)
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--shard-size", type=int, default=4)

    merge = subparsers.add_parser("merge", help="merge one certified success per shard")
    merge.add_argument("--plan", type=Path, required=True)
    merge.add_argument("--success-receipt", type=Path, action="append", required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.add_argument("--dataset-dir", type=Path, required=True)
    merge.add_argument("--min-supported-pass-rate", type=_rate, default=0.04)
    merge.add_argument("--max-supported-pass-rate", type=_rate, default=0.22)
    merge.add_argument("--max-sequence-tokens", type=int, default=DEFAULT_MAX_SEQUENCE_TOKENS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            plan = create_plan(
                args.universe_manifest,
                args.universe_manifest_sha256,
                args.base_config,
                args.output_dir,
                shard_size=args.shard_size,
            )
            output = {
                "state": "planned",
                "universe_task_count": plan["universe"]["task_count"],
                "shard_count": plan["shard_count"],
                "shard_size": plan["shard_size"],
                "plan_sha256": plan["plan_sha256"],
            }
        else:
            receipt = merge_shards(
                args.plan,
                args.success_receipt,
                output_dir=args.output_dir,
                dataset_dir=args.dataset_dir,
                min_supported_pass_rate=args.min_supported_pass_rate,
                max_supported_pass_rate=args.max_supported_pass_rate,
                max_sequence_tokens=args.max_sequence_tokens,
            )
            output = {
                "state": receipt["state"],
                "combined_trace_count": receipt["combined_trace_count"],
                "shard_count": len(receipt["shards"]),
                "distinct_route_generations": receipt["distinct_route_generations"],
                "tb4_certificate_sha256": receipt["tb4_certificate_sha256"],
            }
    except (OSError, ShardWorkflowError) as error:
        print(f"tb4_shard_workflow_error:{error}", file=os.sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
