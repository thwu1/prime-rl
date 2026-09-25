#!/usr/bin/env python3
"""Select, certify, and merge the exact Qwen 2,499-run error retry.

The command intentionally keeps task identities private.  Standard output contains
only aggregate counts and artifact digests; task names are written only to mode-0600
artifacts below a mode-0700 directory.
"""

from __future__ import annotations

import argparse
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
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import audit_traces
import direct_qwen_workers as direct
import export_sft

SCHEMA_VERSION = 1
SELECTION_KIND = "qwen-2499-exact-error-retry-selection"
RETRY_CERTIFICATE_KIND = "qwen-2499-exact-error-retry-run"
MERGED_CERTIFICATE_KIND = "qwen-2499-error-retry-merged-certificate"
MERGE_MANIFEST_KIND = "qwen-2499-error-retry-merge"

TASK_FILENAME = "retry_tasks.txt"
CONFIG_FILENAME = "retry_config.toml"
SELECTION_FILENAME = "selection_manifest.json"
RETRY_CERTIFICATE_FILENAME = "qwen_2499_error_retry_run_certificate.json"
MERGED_RESULTS_FILENAME = "results.jsonl"
MERGED_CERTIFICATE_FILENAME = "qwen_2499_retry_certificate.json"
MERGE_MANIFEST_FILENAME = "merge_manifest.json"

# These pins name the only source generation this workflow is permitted to repair.
ORIGINAL_RESULTS_SHA256 = "4b4221826019fc7e0615393246e05620b605b3c19a2be35f26afb8adc085a641"
CONTINUATION_RESULTS_SHA256 = "465ada70ad4eefbfebbd0fc7f33a30a8dfb89e2ab8b6ff6d9b5dda4a05e6b4f7"
CONTINUATION_CERTIFICATE_SHA256 = "17786bb8406fe59a5768e405fc978a50b330d386af543fb26d3fc4c000149ef5"
CONTINUATION_TASK_FILE_SHA256 = "760dbc88fa47580da3334e2d3aa98bad25271c7795cbd59f7aba86ae06438929"
CANONICAL_UNIVERSE_TASK_FILE_SHA256 = "5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c"
CANONICAL_SOURCE_TASK_FILE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
CANONICAL_DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
CANONICAL_IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"

CANONICAL_SOURCE_COUNT = 2_500
CANONICAL_UNIVERSE_COUNT = 2_499
ORIGINAL_TRACE_COUNT = 1_392
CONTINUATION_TRACE_COUNT = 1_233
RETAINED_ORIGINAL_COUNT = 1_266
ORIGINAL_CONTINUATION_OVERLAP_COUNT = 125
ERROR_RETRY_COUNT = 64
SANDOQ_PROVISIONING_RETRIES = 1
BASE_POSITIVE_COUNT = 1_562
BASE_ZERO_COUNT = 873
BASE_ERROR_COUNT = 64
CONTINUATION_POSITIVE_COUNT = 813
CONTINUATION_ZERO_COUNT = 356
CONTINUATION_RESULTS_BYTES = 543_568_158

RETRY_TASK_PLACEHOLDER = "__QWEN_RETRY_TASK_FILE__"
RETRY_TASK_SHA256_PLACEHOLDER = "__QWEN_RETRY_TASK_FILE_SHA256__"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_TASK_FILE_BYTES = 16 << 20
MAX_CERTIFICATE_BYTES = 2 << 20
MAX_CONFIG_BYTES = 2 << 20
MAX_PROFILE_BYTES = 1 << 20
MAX_JSONL_ROW_BYTES = 128 << 20
MAX_SEQUENCE_TOKENS = 262_144
RETRY_MODEL_IO_CONTRACT = audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT
RETRY_MODEL_IO_CONTRACT_ID = audit_traces.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT_ID
RETRY_RUN_IDENTITY_ROLE = "qwen-direct-error-retry-2499"
RETRY_CONFIG_TEMPLATE_SHA256 = "6d52dae24f3bafbff97c024a7241cf6abd0912cda02eb6e6c5d36a062453b63b"
RETRY_PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
FORBIDDEN_PUBLIC_KEYS = frozenset({"task", "tasks", "task_id", "task_ids", "slug", "slugs"})


class QwenRetryError(RuntimeError):
    """A fail-closed error represented only by a stable aggregate code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise QwenRetryError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class Artifact:
    bytes: int
    sha256: str

    def value(self, *, path: Path | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {"bytes": self.bytes, "sha256": self.sha256}
        if path is not None:
            value["path"] = str(path)
        return value


@dataclass(frozen=True, slots=True)
class TraceRecord:
    offset: int
    length: int
    row_sha256: str
    outcome: str


@dataclass(frozen=True, slots=True)
class TraceScan:
    artifact: Artifact
    rows: Mapping[str, TraceRecord]
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SelectionContext:
    original_results: Path
    continuation_results: Path
    continuation_certificate: Path
    continuation_task_file: Path
    canonical_universe_task_file: Path
    config_template: Path
    provider_profile: Path
    expected_run_dir: Path
    universe_members: tuple[str, ...]
    continuation_members: tuple[str, ...]
    retry_members: tuple[str, ...]
    original_scan: TraceScan
    continuation_scan: TraceScan
    source_artifacts: Mapping[str, Artifact]
    template_body: bytes
    profile_body: bytes


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise QwenRetryError("strict_json_invalid") from error


def _parse_object(body: bytes, code: str, *, canonical: bool = False) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise QwenRetryError(code) from error
    if not isinstance(value, dict) or (canonical and _canonical_json(value) != body):
        raise QwenRetryError(code)
    return value


def _normalized_absolute(path: Path, code: str, *, must_exist: bool = True) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise QwenRetryError(code)
    if not must_exist:
        return path
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except (OSError, RuntimeError) as error:
        raise QwenRetryError(code) from error
    if resolved != path or stat.S_ISLNK(metadata.st_mode):
        raise QwenRetryError(code)
    return resolved


def _regular_file(path: Path, code: str, *, required_mode: int | None = None) -> Path:
    path = _normalized_absolute(path, code)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise QwenRetryError(code) from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or (required_mode is not None and stat.S_IMODE(metadata.st_mode) != required_mode)
    ):
        raise QwenRetryError(code)
    return path


def _private_directory(path: Path, code: str) -> Path:
    path = _normalized_absolute(path, code)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise QwenRetryError(code) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise QwenRetryError(code)
    return path


def _artifact(path: Path, code: str, *, max_bytes: int | None = None) -> Artifact:
    path = _regular_file(path, code)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1 << 20):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise QwenRetryError(code)
            digest.update(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise QwenRetryError(code) from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise QwenRetryError(f"{code}_changed")
    return Artifact(size, digest.hexdigest())


def _read_regular(
    path: Path,
    code: str,
    *,
    max_bytes: int,
    required_mode: int | None = None,
) -> tuple[bytes, Artifact]:
    path = _regular_file(path, code, required_mode=required_mode)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if before.st_size > max_bytes:
            raise QwenRetryError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise QwenRetryError(code)
        after = os.fstat(descriptor)
    except OSError as error:
        raise QwenRetryError(code) from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise QwenRetryError(f"{code}_changed")
    payload = bytes(body)
    return payload, Artifact(len(payload), _sha256(payload))


def _task_members(body: bytes, *, expected_count: int, code: str) -> tuple[str, ...]:
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise QwenRetryError(code) from error
    members: list[str] = []
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        member = raw.strip().split("\t", 1)[0]
        if (
            not member
            or member in {".", ".."}
            or "/" in member
            or "\\" in member
            or "\x00" in member
        ):
            raise QwenRetryError(code)
        members.append(member)
    if len(members) != expected_count or len(set(members)) != expected_count:
        raise QwenRetryError(code)
    return tuple(members)


def _strict_reward(trace: Mapping[str, Any]) -> float:
    rewards = trace.get("rewards")
    if not isinstance(rewards, Mapping) or not rewards:
        raise QwenRetryError("trace_reward_invalid")
    values = tuple(rewards.values())
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        for value in values
    ):
        raise QwenRetryError("trace_reward_invalid")
    reward = float(sum(values))
    if reward not in {0.0, 1.0}:
        raise QwenRetryError("trace_reward_invalid")
    return reward


def _positive_trace_is_trainable(trace: dict[str, Any]) -> bool:
    problems = audit_traces._audit_trace(
        trace,
        require_reasoning=True,
        max_sequence_tokens=MAX_SEQUENCE_TOKENS,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        model_io_contract=RETRY_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        require_exact_provider_json=True,
        require_clean_stop=True,
    )
    if problems:
        return False
    try:
        export_sft._validate_trainable_trace(
            trace,
            reward=1.0,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            require_exact_provider_json=True,
        )
    except export_sft.ExportError:
        return False
    return True


def _scan_results(
    path: Path,
    *,
    expected_sha256: str,
    expected_count: int,
    evaluator_order: tuple[str, ...] | None,
    validate_positive: bool,
    allowed_members: frozenset[str] | None = None,
) -> TraceScan:
    path = _regular_file(path, "results_invalid", required_mode=0o600)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    rows: dict[str, TraceRecord] = {}
    trace_ids: set[str] = set()
    indices: set[int] = set()
    counts: Counter[str] = Counter()
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                offset = handle.tell()
                raw = handle.readline(MAX_JSONL_ROW_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_JSONL_ROW_BYTES:
                    raise QwenRetryError("results_row_too_large")
                if not raw.endswith(b"\n") or not raw.strip():
                    raise QwenRetryError("results_jsonl_invalid")
                total_bytes += len(raw)
                digest.update(raw)
                trace = _parse_object(raw, "results_jsonl_invalid")
                trace_id = trace.get("id")
                task = trace.get("task")
                if not isinstance(trace_id, str) or not trace_id or not isinstance(task, Mapping):
                    raise QwenRetryError("trace_identity_invalid")
                trace_id_hash = _sha256(trace_id.encode("utf-8"))
                if trace_id_hash in trace_ids:
                    raise QwenRetryError("duplicate_trace_id")
                trace_ids.add(trace_id_hash)
                try:
                    slug = export_sft._opaque_task_slug(task, evaluator_order=evaluator_order)
                except export_sft.ExportError as error:
                    raise QwenRetryError("trace_identity_invalid") from error
                index = task.get("idx")
                if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in indices:
                    raise QwenRetryError("trace_identity_invalid")
                indices.add(index)
                if slug in rows or (allowed_members is not None and slug not in allowed_members):
                    raise QwenRetryError("trace_coverage_invalid")
                errors = trace.get("errors")
                if not isinstance(errors, list):
                    raise QwenRetryError("trace_errors_invalid")
                if errors:
                    outcome = "error"
                else:
                    reward = _strict_reward(trace)
                    if trace.get("is_completed") is not True:
                        raise QwenRetryError("trace_completion_invalid")
                    stop_condition = trace.get("stop_condition")
                    if not isinstance(stop_condition, str) or not stop_condition:
                        raise QwenRetryError("trace_completion_invalid")
                    if reward == 0.0:
                        outcome = "zero"
                    elif validate_positive and not _positive_trace_is_trainable(trace):
                        outcome = "invalid_positive"
                    else:
                        outcome = "positive"
                counts[outcome] += 1
                rows[slug] = TraceRecord(offset, len(raw), _sha256(raw), outcome)
        after = os.fstat(descriptor)
    except OSError as error:
        raise QwenRetryError("results_unreadable") from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise QwenRetryError("results_changed")
    artifact = Artifact(total_bytes, digest.hexdigest())
    if artifact.sha256 != expected_sha256 or len(rows) != expected_count:
        raise QwenRetryError("results_binding_mismatch")
    return TraceScan(artifact=artifact, rows=rows, counts=dict(counts))


def _validate_continuation_certificate(body: bytes) -> dict[str, Any]:
    value = _parse_object(body, "continuation_certificate_invalid")
    try:
        coverage = value["coverage_audit"]
        merge = value["merge_contract"]
        lineage = value["lineage"]
        selection = lineage["selection"]
        epoch3 = lineage["epoch3_source"]
        epoch3_artifacts = epoch3["artifacts"]
        run = value["run"]
    except (KeyError, TypeError) as error:
        raise QwenRetryError("continuation_certificate_invalid") from error
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "qwen-sandoq-source-continuation-pass-only"
        or value.get("state") != "passed"
        or value.get("certification_scope") != "pass-only-positive-trace-eligibility"
        or value.get("all_outcomes_trainability_claimed") is not False
        or run.get("task_count") != CONTINUATION_TRACE_COUNT
        or run.get("task_file_sha256") != CONTINUATION_TASK_FILE_SHA256
        or run.get("results")
        != {"bytes": CONTINUATION_RESULTS_BYTES, "sha256": CONTINUATION_RESULTS_SHA256}
        or coverage.get("input_traces") != CONTINUATION_TRACE_COUNT
        or coverage.get("covered_tasks") != CONTINUATION_TRACE_COUNT
        or coverage.get("error_traces_nonexported") != ERROR_RETRY_COUNT
        or coverage.get("positive_reward_traces") != CONTINUATION_POSITIVE_COUNT
        or coverage.get("positive_traces_trainable") != CONTINUATION_POSITIVE_COUNT
        or coverage.get("zero_reward_traces_nonexported") != CONTINUATION_ZERO_COUNT
        or coverage.get("exact_task_coverage") is not True
        or coverage.get("results") != run.get("results")
        or selection.get("task_file_sha256") != CONTINUATION_TASK_FILE_SHA256
        or epoch3_artifacts.get("results.jsonl", {}).get("sha256") != ORIGINAL_RESULTS_SHA256
        or epoch3_artifacts.get("inputs/task_file.txt", {}).get("sha256")
        != CANONICAL_SOURCE_TASK_FILE_SHA256
        or merge.get("canonical_sandoq_coverage_tasks") != CANONICAL_UNIVERSE_COUNT
        or merge.get("continuation_coverage_tasks") != CONTINUATION_TRACE_COUNT
        or merge.get("retained_coverage_tasks") != RETAINED_ORIGINAL_COUNT
        or merge.get("disjoint_coverage") is not True
        or merge.get("exhaustive_coverage") is not True
        or merge.get("original_order_required") is not True
    ):
        raise QwenRetryError("continuation_certificate_invalid")
    return value


def _validate_pinned_digest(supplied: str, expected: str, code: str) -> None:
    if SHA256_RE.fullmatch(supplied or "") is None or supplied != expected:
        raise QwenRetryError(code)


def _load_selection_context(
    *,
    original_results: Path,
    original_results_sha256: str,
    continuation_results: Path,
    continuation_results_sha256: str,
    continuation_certificate: Path,
    continuation_certificate_sha256: str,
    continuation_task_file: Path,
    continuation_task_file_sha256: str,
    canonical_universe_task_file: Path,
    canonical_universe_task_file_sha256: str,
    config_template: Path,
    config_template_sha256: str,
    provider_profile: Path,
    provider_profile_sha256: str,
    expected_run_dir: Path,
) -> SelectionContext:
    _validate_pinned_digest(original_results_sha256, ORIGINAL_RESULTS_SHA256, "original_results_digest_invalid")
    _validate_pinned_digest(
        continuation_results_sha256,
        CONTINUATION_RESULTS_SHA256,
        "continuation_results_digest_invalid",
    )
    _validate_pinned_digest(
        continuation_certificate_sha256,
        CONTINUATION_CERTIFICATE_SHA256,
        "continuation_certificate_digest_invalid",
    )
    _validate_pinned_digest(
        continuation_task_file_sha256,
        CONTINUATION_TASK_FILE_SHA256,
        "continuation_task_digest_invalid",
    )
    _validate_pinned_digest(
        canonical_universe_task_file_sha256,
        CANONICAL_UNIVERSE_TASK_FILE_SHA256,
        "canonical_universe_digest_invalid",
    )
    _validate_pinned_digest(
        config_template_sha256,
        RETRY_CONFIG_TEMPLATE_SHA256,
        "config_template_digest_invalid",
    )
    _validate_pinned_digest(
        provider_profile_sha256,
        RETRY_PROVIDER_PROFILE_SHA256,
        "provider_profile_digest_invalid",
    )
    original_results = _regular_file(original_results, "original_results_invalid", required_mode=0o600)
    continuation_results = _regular_file(continuation_results, "continuation_results_invalid", required_mode=0o600)
    continuation_certificate = _regular_file(
        continuation_certificate,
        "continuation_certificate_invalid",
        required_mode=0o600,
    )
    continuation_task_file = _regular_file(
        continuation_task_file,
        "continuation_task_file_invalid",
        required_mode=0o600,
    )
    canonical_universe_task_file = _regular_file(
        canonical_universe_task_file,
        "canonical_universe_task_file_invalid",
        required_mode=0o600,
    )
    config_template = _regular_file(config_template, "config_template_invalid")
    provider_profile = _regular_file(provider_profile, "provider_profile_invalid")
    expected_run_dir = _normalized_absolute(expected_run_dir, "expected_run_dir_invalid", must_exist=False)

    continuation_task_body, continuation_task_artifact = _read_regular(
        continuation_task_file,
        "continuation_task_file_invalid",
        max_bytes=MAX_TASK_FILE_BYTES,
        required_mode=0o600,
    )
    universe_body, universe_artifact = _read_regular(
        canonical_universe_task_file,
        "canonical_universe_task_file_invalid",
        max_bytes=MAX_TASK_FILE_BYTES,
        required_mode=0o600,
    )
    certificate_body, certificate_artifact = _read_regular(
        continuation_certificate,
        "continuation_certificate_invalid",
        max_bytes=MAX_CERTIFICATE_BYTES,
        required_mode=0o600,
    )
    template_body, template_artifact = _read_regular(
        config_template,
        "config_template_invalid",
        max_bytes=MAX_CONFIG_BYTES,
    )
    profile_body, profile_artifact = _read_regular(
        provider_profile,
        "provider_profile_invalid",
        max_bytes=MAX_PROFILE_BYTES,
    )
    if (
        continuation_task_artifact.sha256 != CONTINUATION_TASK_FILE_SHA256
        or universe_artifact.sha256 != CANONICAL_UNIVERSE_TASK_FILE_SHA256
        or certificate_artifact.sha256 != CONTINUATION_CERTIFICATE_SHA256
        or template_artifact.sha256 != config_template_sha256
        or profile_artifact.sha256 != provider_profile_sha256
    ):
        raise QwenRetryError("source_artifact_digest_mismatch")
    _validate_continuation_certificate(certificate_body)
    continuation_members = _task_members(
        continuation_task_body,
        expected_count=CONTINUATION_TRACE_COUNT,
        code="continuation_task_file_invalid",
    )
    universe_members = _task_members(
        universe_body,
        expected_count=CANONICAL_UNIVERSE_COUNT,
        code="canonical_universe_task_file_invalid",
    )
    continuation_set = frozenset(continuation_members)
    universe_set = frozenset(universe_members)
    if not continuation_set.issubset(universe_set):
        raise QwenRetryError("continuation_outside_canonical_universe")

    original_scan = _scan_results(
        original_results,
        expected_sha256=ORIGINAL_RESULTS_SHA256,
        expected_count=ORIGINAL_TRACE_COUNT,
        evaluator_order=None,
        validate_positive=False,
    )
    continuation_scan = _scan_results(
        continuation_results,
        expected_sha256=CONTINUATION_RESULTS_SHA256,
        expected_count=CONTINUATION_TRACE_COUNT,
        evaluator_order=tuple(sorted(continuation_members)),
        validate_positive=False,
        allowed_members=continuation_set,
    )
    original_set = frozenset(original_scan.rows)
    retained_set = universe_set - continuation_set
    if (
        frozenset(continuation_scan.rows) != continuation_set
        or len(retained_set) != RETAINED_ORIGINAL_COUNT
        or not retained_set.issubset(original_set)
        or len(original_set & continuation_set) != ORIGINAL_CONTINUATION_OVERLAP_COUNT
        or len(original_set - universe_set) != 1
        or len(retained_set | continuation_set) != CANONICAL_UNIVERSE_COUNT
    ):
        raise QwenRetryError("canonical_coverage_invalid")
    base_counts: Counter[str] = Counter()
    retry_set: set[str] = set()
    for member in universe_members:
        record = continuation_scan.rows.get(member) if member in continuation_set else original_scan.rows.get(member)
        if record is None:
            raise QwenRetryError("canonical_coverage_invalid")
        base_counts[record.outcome] += 1
        if record.outcome == "error":
            retry_set.add(member)
    if base_counts != Counter(
        positive=BASE_POSITIVE_COUNT,
        zero=BASE_ZERO_COUNT,
        error=BASE_ERROR_COUNT,
    ) or not retry_set.issubset(continuation_set):
        raise QwenRetryError("canonical_outcome_partition_invalid")
    retry_members = tuple(member for member in universe_members if member in retry_set)
    if len(retry_members) != ERROR_RETRY_COUNT:
        raise QwenRetryError("retry_count_invalid")
    return SelectionContext(
        original_results=original_results,
        continuation_results=continuation_results,
        continuation_certificate=continuation_certificate,
        continuation_task_file=continuation_task_file,
        canonical_universe_task_file=canonical_universe_task_file,
        config_template=config_template,
        provider_profile=provider_profile,
        expected_run_dir=expected_run_dir,
        universe_members=universe_members,
        continuation_members=continuation_members,
        retry_members=retry_members,
        original_scan=original_scan,
        continuation_scan=continuation_scan,
        source_artifacts={
            "canonical_universe_task_file": universe_artifact,
            "config_template": template_artifact,
            "continuation_certificate": certificate_artifact,
            "continuation_results": continuation_scan.artifact,
            "continuation_task_file": continuation_task_artifact,
            "original_results": original_scan.artifact,
            "provider_profile": profile_artifact,
        },
        template_body=template_body,
        profile_body=profile_body,
    )


def _retry_task_body(context: SelectionContext) -> bytes:
    return "".join(f"{member}\n" for member in context.retry_members).encode("utf-8")


def _parse_toml(body: bytes, code: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise QwenRetryError(code) from error
    if not isinstance(value, dict):
        raise QwenRetryError(code)
    return value


def _validate_provider_profile(body: bytes) -> dict[str, Any]:
    profile = _parse_object(body, "provider_profile_invalid", canonical=True)
    if (
        set(profile)
        != {
            "base_url",
            "cluster_identifier",
            "effective_task_network",
            "environment",
            "provider_token_file",
            "schema_version",
            "task_network",
            "transport_mode",
        }
        or profile.get("schema_version") != 3
        or profile.get("base_url") != "https://sandoq.eks-prod.cf.aws.metafb.cloud"
        or profile.get("cluster_identifier") != "use2"
        or profile.get("environment") != "oci-runner-firecracker-small"
        or profile.get("task_network") != "host"
        or profile.get("effective_task_network") != "public"
        or profile.get("transport_mode") != "auto"
        or not isinstance(profile.get("provider_token_file"), str)
        or not Path(profile["provider_token_file"]).is_absolute()
    ):
        raise QwenRetryError("provider_profile_invalid")
    return profile


def _render_config(template: bytes, *, task_file: Path, task_sha256: str) -> bytes:
    try:
        text = template.decode("utf-8")
    except UnicodeDecodeError as error:
        raise QwenRetryError("config_template_invalid") from error
    quoted_task_placeholder = json.dumps(RETRY_TASK_PLACEHOLDER)
    quoted_digest_placeholder = json.dumps(RETRY_TASK_SHA256_PLACEHOLDER)
    if text.count(quoted_task_placeholder) != 1 or text.count(quoted_digest_placeholder) != 1:
        raise QwenRetryError("config_template_placeholders_invalid")
    text = text.replace(quoted_task_placeholder, json.dumps(str(task_file)))
    text = text.replace(quoted_digest_placeholder, json.dumps(task_sha256))
    return text.encode("utf-8")


def _validate_retry_config(
    body: bytes,
    *,
    task_file: Path,
    task_sha256: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    config = _parse_toml(body, "retry_config_invalid")
    client = config.get("client")
    sampling = config.get("sampling")
    thinking = sampling.get("chat_template_kwargs") if isinstance(sampling, Mapping) else None
    taskset = config.get("taskset")
    harness = config.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, Mapping) else None
    harness_env = harness.get("env") if isinstance(harness, Mapping) else None
    timeouts = config.get("timeout")
    retries = config.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, Mapping) else None
    overrides = harness.get("config_overrides") if isinstance(harness, Mapping) else None
    required_overrides = {
        "agent.step_limit=200",
        "environment.environment_class=local",
        "environment.timeout=36000",
        "model.cost_tracking=ignore_errors",
        "model.model_kwargs.drop_params=true",
        "model.model_kwargs.timeout=15000",
        "model.model_kwargs.temperature=0.7",
        "model.model_kwargs.top_p=0.95",
        "model.model_kwargs.parallel_tool_calls=false",
    }
    retry_classes = {"ProviderError", "SandboxError", "TunnelError", "InterceptionError"}
    if (
        set(config)
        != {
            "client",
            "harness",
            "max_concurrent",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_turns",
            "model",
            "multiplex",
            "num_rollouts",
            "num_tasks",
            "retain_traces",
            "retries",
            "rich",
            "sampling",
            "taskset",
            "timeout",
        }
        or config.get("model") != direct.EXPECTED_MODEL
        or config.get("num_tasks") != ERROR_RETRY_COUNT
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != 64
        or config.get("multiplex") != 64
        or config.get("max_turns") != 200
        or any(config.get(key) != MAX_SEQUENCE_TOKENS for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or config.get("retain_traces") is not False
        or not isinstance(client, Mapping)
        or set(client)
        != {
            "api_key_var",
            "base_url",
            "capture_model_io",
            "connect_timeout",
            "max_connections",
            "max_keepalive_connections",
            "max_retries",
            "outbound_body_denylist",
            "timeout",
            "type",
        }
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("base_url") != "http://127.0.0.1:8000/v1"
        or client.get("api_key_var") != "OPENAI_API_KEY"
        or client.get("timeout") != 7_200
        or client.get("connect_timeout") != 30
        or client.get("max_connections") != 32
        or client.get("max_keepalive_connections") != 32
        or client.get("max_retries") != 0
        or set(client.get("outbound_body_denylist", ()))
        != {"logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"}
        or not isinstance(sampling, Mapping)
        or set(sampling)
        != {
            "chat_template_kwargs",
            "max_tokens",
            "reasoning_effort",
            "temperature",
            "top_k",
            "top_p",
        }
        or sampling.get("reasoning_effort") != "medium"
        or sampling.get("max_tokens") != 32_768
        or thinking != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, Mapping)
        or set(taskset)
        != {
            "capture_convention_artifacts",
            "dataset_dir",
            "dataset_revision",
            "enable_compose",
            "id",
            "ignore_dockerfile",
            "image_manifest",
            "image_manifest_sha256",
            "image_prefix",
            "image_tag",
            "resource_cpu_cap",
            "resource_memory_mb_cap",
            "resource_multiplier",
            "resource_storage_mb_cap",
            "task_file",
            "task_file_sha256",
            "timeout_multiplier",
            "verifier_runtime_retries",
        }
        or taskset.get("id") != "terminal-bench-vmvm"
        or taskset.get("dataset_revision") != CANONICAL_DATASET_REVISION
        or not isinstance(taskset.get("dataset_dir"), str)
        or not Path(taskset["dataset_dir"]).is_absolute()
        or Path(str(taskset.get("task_file", ""))) != task_file
        or taskset.get("task_file_sha256") != task_sha256
        or taskset.get("image_manifest_sha256") != CANONICAL_IMAGE_MANIFEST_SHA256
        or taskset.get("ignore_dockerfile") is not True
        or taskset.get("enable_compose") is not False
        or taskset.get("verifier_runtime_retries") != 0
        or taskset.get("timeout_multiplier", 0) < 2.0
        or taskset.get("resource_cpu_cap") != 2
        or taskset.get("resource_memory_mb_cap") != 4_096
        or taskset.get("resource_storage_mb_cap") != 10_240
        or not isinstance(harness, Mapping)
        or set(harness) != {"config_file", "config_overrides", "env", "id", "runtime", "version"}
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.4.6"
        or harness.get("config_file") != "mini"
        or not isinstance(overrides, list)
        or len(overrides) != len(set(overrides))
        or set(overrides) != required_overrides
        or harness_env != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1"}
        or not isinstance(runtime, Mapping)
        or set(runtime)
        != {
            "buffered_chat_completions",
            "ecr_token_file",
            "expected_environment",
            "guest_tunnel_url",
            "host_tunnel",
            "mode",
            "network_access",
            "session_timeout",
            "tunnel_pool_size",
            "tunnel_ready_timeout",
            "type",
        }
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("session_timeout") != 43_200
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("buffered_chat_completions") is not True
        or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
        or runtime.get("expected_environment") != profile.get("environment")
        or not isinstance(timeouts, Mapping)
        or set(timeouts) != {"finalize", "rollout", "scoring", "setup"}
        or timeouts.get("setup", 0) < 3_600
        or timeouts.get("rollout", 0) < 36_000
        or timeouts.get("finalize", 0) < 3_600
        or timeouts.get("scoring", 0) < 21_600
        or not isinstance(rollout_retries, Mapping)
        or set(retries) != {"rollout"}
        or set(rollout_retries) != {"include", "max_retries"}
        or rollout_retries.get("max_retries") != 0
        or set(rollout_retries.get("include", ())) != retry_classes
    ):
        raise QwenRetryError("retry_config_contract_invalid")
    return config


def _indices_sha256(indices: Iterator[int]) -> str:
    return _sha256("".join(f"{index}\n" for index in indices).encode("ascii"))


def _module_sha256() -> str:
    return _artifact(Path(__file__).resolve(), "module_unreadable").sha256


def _selection_manifest_value(
    context: SelectionContext,
    *,
    task_path: Path,
    task_artifact: Artifact,
    config_path: Path,
    config_artifact: Artifact,
) -> dict[str, Any]:
    universe_index = {member: index for index, member in enumerate(context.universe_members)}
    continuation_index = {member: index for index, member in enumerate(context.continuation_members)}
    canonical_indices = (universe_index[member] for member in context.retry_members)
    continuation_indices = (continuation_index[member] for member in context.retry_members)
    source_paths = {
        "original_results": context.original_results,
        "continuation_results": context.continuation_results,
        "continuation_certificate": context.continuation_certificate,
        "continuation_task_file": context.continuation_task_file,
        "canonical_universe_task_file": context.canonical_universe_task_file,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SELECTION_KIND,
        "state": "selected",
        "privacy": {
            "excluded_singleton_count": CANONICAL_SOURCE_COUNT - CANONICAL_UNIVERSE_COUNT,
            "excluded_singleton_disclosed": False,
            "identifiers_in_public_summary": False,
            "task_artifacts_private": True,
        },
        "source": {
            name: context.source_artifacts[name].value(path=source_paths[name])
            for name in source_paths
        },
        "canonical_coverage": {
            "canonical_source_count": CANONICAL_SOURCE_COUNT,
            "canonical_source_task_file_sha256": CANONICAL_SOURCE_TASK_FILE_SHA256,
            "canonical_universe_count": CANONICAL_UNIVERSE_COUNT,
            "canonical_universe_order_sha256": context.source_artifacts[
                "canonical_universe_task_file"
            ].sha256,
            "continuation_count": CONTINUATION_TRACE_COUNT,
            "disjoint": True,
            "exact": True,
            "exhaustive": True,
            "retained_original_count": RETAINED_ORIGINAL_COUNT,
        },
        "outcomes_before_retry": {
            "error": BASE_ERROR_COUNT,
            "positive": BASE_POSITIVE_COUNT,
            "total": CANONICAL_UNIVERSE_COUNT,
            "zero": BASE_ZERO_COUNT,
        },
        "selection": {
            "canonical_indices_sha256": _indices_sha256(iter(canonical_indices)),
            "continuation_indices_sha256": _indices_sha256(iter(continuation_indices)),
            "count": ERROR_RETRY_COUNT,
            "predicate": "canonical-outcome-errors-nonempty",
            "task_file": task_artifact.value(path=task_path),
        },
        "execution": {
            "config": config_artifact.value(path=config_path),
            "config_template": context.source_artifacts["config_template"].value(path=context.config_template),
            "expected_run_artifacts": [
                "config.toml",
                "direct_workers.json",
                "eval_run_identity.json",
                "inputs/source_config.toml",
                "inputs/task_file.txt",
                "provenance.txt",
                "results.jsonl",
                "sandoq_cleanup_audit.json",
            ],
            "expected_run_dir": str(context.expected_run_dir),
            "provider_profile": context.source_artifacts["provider_profile"].value(path=context.provider_profile),
            "sandbox": {
                "environment": "oci-runner-firecracker-small",
                "provider": "sandoq",
                "resource_caps": {
                    "cpu": 2,
                    "memory_mb": 4_096,
                    "policy": "min-declared-and-provider-cap",
                    "storage_mb": 10_240,
                },
                "task_network": "public",
            },
            "routing": {
                "http_max_connections": 32,
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "rollout_concurrency": 64,
            },
        },
        "trace_contract": {
            "id": RETRY_MODEL_IO_CONTRACT_ID,
            "sha256": audit_traces.model_io_contract_sha256(RETRY_MODEL_IO_CONTRACT),
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "positive_rows_must_be_trainable": True,
            "require_exact_provider_json": True,
        },
        "code": {"module_sha256": _module_sha256()},
    }


def _write_exclusive(path: Path, body: bytes) -> Artifact:
    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
    except OSError as error:
        raise QwenRetryError("artifact_publish_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return Artifact(len(body), _sha256(body))


def _create_private_output(path: Path) -> Path:
    path = _normalized_absolute(path, "output_path_invalid", must_exist=False)
    parent = _private_directory(path.parent, "output_parent_invalid")
    if os.path.lexists(path):
        raise QwenRetryError("output_exists")
    try:
        os.mkdir(path, 0o700)
        if path.parent != parent:
            raise QwenRetryError("output_path_invalid")
        return _private_directory(path, "output_path_invalid")
    except OSError as error:
        raise QwenRetryError("output_create_failed") from error


def _remove_owned_output(path: Path) -> None:
    try:
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o700:
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


def select(
    *,
    original_results: Path,
    original_results_sha256: str,
    continuation_results: Path,
    continuation_results_sha256: str,
    continuation_certificate: Path,
    continuation_certificate_sha256: str,
    continuation_task_file: Path,
    continuation_task_file_sha256: str,
    canonical_universe_task_file: Path,
    canonical_universe_task_file_sha256: str,
    config_template: Path,
    config_template_sha256: str,
    provider_profile: Path,
    provider_profile_sha256: str,
    expected_run_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    context = _load_selection_context(
        original_results=original_results,
        original_results_sha256=original_results_sha256,
        continuation_results=continuation_results,
        continuation_results_sha256=continuation_results_sha256,
        continuation_certificate=continuation_certificate,
        continuation_certificate_sha256=continuation_certificate_sha256,
        continuation_task_file=continuation_task_file,
        continuation_task_file_sha256=continuation_task_file_sha256,
        canonical_universe_task_file=canonical_universe_task_file,
        canonical_universe_task_file_sha256=canonical_universe_task_file_sha256,
        config_template=config_template,
        config_template_sha256=config_template_sha256,
        provider_profile=provider_profile,
        provider_profile_sha256=provider_profile_sha256,
        expected_run_dir=expected_run_dir,
    )
    profile = _validate_provider_profile(context.profile_body)
    output = _create_private_output(output_dir)
    try:
        task_path = output / TASK_FILENAME
        config_path = output / CONFIG_FILENAME
        manifest_path = output / SELECTION_FILENAME
        task_body = _retry_task_body(context)
        task_artifact = _write_exclusive(task_path, task_body)
        config_body = _render_config(context.template_body, task_file=task_path, task_sha256=task_artifact.sha256)
        _validate_retry_config(config_body, task_file=task_path, task_sha256=task_artifact.sha256, profile=profile)
        config_artifact = _write_exclusive(config_path, config_body)
        manifest = _selection_manifest_value(
            context,
            task_path=task_path,
            task_artifact=task_artifact,
            config_path=config_path,
            config_artifact=config_artifact,
        )
        manifest_body = _canonical_json(manifest)
        manifest_artifact = _write_exclusive(manifest_path, manifest_body)
        directory_descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        _remove_owned_output(output)
        raise
    return {
        "config_sha256": config_artifact.sha256,
        "contract_sha256": manifest_artifact.sha256,
        "retry_count": ERROR_RETRY_COUNT,
        "state": "selected",
        "task_file_sha256": task_artifact.sha256,
    }


def _manifest_path(value: object, code: str) -> Path:
    if not isinstance(value, Mapping) or set(value) != {"bytes", "path", "sha256"}:
        raise QwenRetryError(code)
    path = value.get("path")
    size = value.get("bytes")
    digest = value.get("sha256")
    if (
        not isinstance(path, str)
        or not _plain_int(size)
        or SHA256_RE.fullmatch(str(digest or "")) is None
    ):
        raise QwenRetryError(code)
    return _normalized_absolute(Path(path), code)


def _load_contract(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    if SHA256_RE.fullmatch(expected_sha256 or "") is None:
        raise QwenRetryError("contract_digest_invalid")
    body, artifact = _read_regular(
        path,
        "contract_invalid",
        max_bytes=MAX_CERTIFICATE_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise QwenRetryError("contract_digest_mismatch")
    value = _parse_object(body, "contract_invalid", canonical=True)
    if (
        set(value)
        != {
            "canonical_coverage",
            "code",
            "execution",
            "kind",
            "outcomes_before_retry",
            "privacy",
            "schema_version",
            "selection",
            "source",
            "state",
            "trace_contract",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != SELECTION_KIND
        or value.get("state") != "selected"
    ):
        raise QwenRetryError("contract_invalid")
    return value, body


def _context_from_contract(value: Mapping[str, Any]) -> SelectionContext:
    source = value.get("source")
    execution = value.get("execution")
    if not isinstance(source, Mapping) or not isinstance(execution, Mapping):
        raise QwenRetryError("contract_invalid")
    records = {
        name: source.get(name)
        for name in (
            "original_results",
            "continuation_results",
            "continuation_certificate",
            "continuation_task_file",
            "canonical_universe_task_file",
        )
    }
    config_template_record = execution.get("config_template")
    provider_profile_record = execution.get("provider_profile")
    expected_run = execution.get("expected_run_dir")
    if not isinstance(expected_run, str):
        raise QwenRetryError("contract_invalid")
    paths = {name: _manifest_path(record, "contract_invalid") for name, record in records.items()}
    config_template = _manifest_path(config_template_record, "contract_invalid")
    provider_profile = _manifest_path(provider_profile_record, "contract_invalid")
    return _load_selection_context(
        original_results=paths["original_results"],
        original_results_sha256=str(records["original_results"]["sha256"]),  # type: ignore[index]
        continuation_results=paths["continuation_results"],
        continuation_results_sha256=str(records["continuation_results"]["sha256"]),  # type: ignore[index]
        continuation_certificate=paths["continuation_certificate"],
        continuation_certificate_sha256=str(records["continuation_certificate"]["sha256"]),  # type: ignore[index]
        continuation_task_file=paths["continuation_task_file"],
        continuation_task_file_sha256=str(records["continuation_task_file"]["sha256"]),  # type: ignore[index]
        canonical_universe_task_file=paths["canonical_universe_task_file"],
        canonical_universe_task_file_sha256=str(records["canonical_universe_task_file"]["sha256"]),  # type: ignore[index]
        config_template=config_template,
        config_template_sha256=str(config_template_record["sha256"]),  # type: ignore[index]
        provider_profile=provider_profile,
        provider_profile_sha256=str(provider_profile_record["sha256"]),  # type: ignore[index]
        expected_run_dir=Path(expected_run),
    )


def _validate_fresh_run_dir(run_dir: Path, *, allow_wrapper_artifacts: bool = False) -> None:
    if not os.path.lexists(run_dir):
        parent = _normalized_absolute(run_dir.parent, "run_parent_invalid")
        try:
            metadata = parent.lstat()
        except OSError as error:
            raise QwenRetryError("run_parent_invalid") from error
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise QwenRetryError("run_parent_invalid")
        return
    run = _private_directory(run_dir, "run_dir_invalid")
    allowed_top = {"control"}
    if allow_wrapper_artifacts:
        allowed_top.update({".direct_router.lock", "direct_router.log", "direct_workers.json"})
    observed = {entry.name for entry in os.scandir(run)}
    if not observed.issubset(allowed_top):
        raise QwenRetryError("run_dir_not_fresh")
    for name in observed - {"control"}:
        path = run / name
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or bool(metadata.st_mode & 0o077)
        ):
            raise QwenRetryError("run_dir_not_fresh")
    control = run / "control"
    if control.exists():
        if control.is_symlink() or not control.is_dir():
            raise QwenRetryError("run_dir_not_fresh")
        allowed_control = {"sandoq-pool.wal.jsonl"}
        if not {entry.name for entry in os.scandir(control)}.issubset(allowed_control):
            raise QwenRetryError("run_dir_not_fresh")


def verify_launch(
    *,
    contract: Path,
    contract_sha256: str,
    task_file: Path,
    task_file_sha256: str,
    config: Path,
    config_sha256: str,
    provider_profile: Path,
    provider_profile_sha256: str,
    run_dir: Path,
    allow_wrapper_artifacts: bool = False,
) -> dict[str, Any]:
    value, _body = _load_contract(contract, contract_sha256)
    context = _context_from_contract(value)
    task_file = _regular_file(task_file, "retry_task_file_invalid", required_mode=0o600)
    config = _regular_file(config, "retry_config_invalid", required_mode=0o600)
    provider_profile = _regular_file(provider_profile, "provider_profile_invalid")
    run_dir = _normalized_absolute(run_dir, "run_dir_invalid", must_exist=False)
    task_body, task_artifact = _read_regular(
        task_file,
        "retry_task_file_invalid",
        max_bytes=MAX_TASK_FILE_BYTES,
        required_mode=0o600,
    )
    config_body, config_artifact = _read_regular(
        config,
        "retry_config_invalid",
        max_bytes=MAX_CONFIG_BYTES,
        required_mode=0o600,
    )
    profile_body, profile_artifact = _read_regular(
        provider_profile,
        "provider_profile_invalid",
        max_bytes=MAX_PROFILE_BYTES,
    )
    if (
        task_file_sha256 != task_artifact.sha256
        or config_sha256 != config_artifact.sha256
        or provider_profile_sha256 != profile_artifact.sha256
        or task_body != _retry_task_body(context)
        or run_dir != context.expected_run_dir
    ):
        raise QwenRetryError("launch_binding_mismatch")
    profile = _validate_provider_profile(profile_body)
    _validate_retry_config(config_body, task_file=task_file, task_sha256=task_artifact.sha256, profile=profile)
    expected = _selection_manifest_value(
        context,
        task_path=task_file,
        task_artifact=task_artifact,
        config_path=config,
        config_artifact=config_artifact,
    )
    if value != expected:
        raise QwenRetryError("contract_evidence_mismatch")
    _validate_fresh_run_dir(run_dir, allow_wrapper_artifacts=allow_wrapper_artifacts)
    return {
        "config_sha256": config_artifact.sha256,
        "contract_sha256": contract_sha256,
        "retry_count": ERROR_RETRY_COUNT,
        "state": "launch-verified",
        "task_file_sha256": task_artifact.sha256,
    }


@contextmanager
def _completed_run_lock(run_dir: Path) -> Iterator[None]:
    run_dir = _private_directory(run_dir, "run_dir_invalid")
    lock = _regular_file(run_dir / ".writer.lock", "run_lock_invalid")
    descriptor = os.open(lock, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise QwenRetryError("run_writer_active") from error
        yield
    finally:
        os.close(descriptor)


def _validate_cleanup(path: Path) -> tuple[dict[str, Any], Artifact]:
    body, artifact = _read_regular(path, "cleanup_invalid", max_bytes=MAX_CERTIFICATE_BYTES, required_mode=0o600)
    value = _parse_object(body, "cleanup_invalid")
    count_fields = {
        "recorded_outer_sessions",
        "verified_http_404",
        "already_absent",
        "deleted_and_verified",
        "assignments_acquired",
        "assignment_release_rows",
        "assignment_cancellation_rows",
        "cleanup_gateway_retry_count",
        "assignments_cleanup_verified",
        "assignment_event_order_high_water",
        "assignment_measured_high_water",
        "outer_sessions_created",
        "outer_sessions_deleted",
        "outer_session_high_water",
        "pool_drain_deleted",
        "gateway_close_warnings",
        "recovered_poisoned_assignments",
        "failures",
    }
    digest_fields = {"raw_audit_sha256", "pool_event_log_sha256", "pool_wal_sha256", "pool_drain_sha256"}
    expected_keys = {"schema_version", "kind", "state", *count_fields, *digest_fields}
    # One rollout may fail before acquiring its first sandbox.  Preserve the
    # concurrency evidence while still requiring every acquired assignment and
    # every recorded outer session to have been cleaned up successfully.
    accepted_high_water = {ERROR_RETRY_COUNT - 1, ERROR_RETRY_COUNT}
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-pool-cleanup"
        or value.get("state") != "passed"
        or any(not _plain_int(value.get(key)) for key in count_fields)
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digest_fields)
        or value.get("failures") != 0
        or value.get("recorded_outer_sessions") != value.get("verified_http_404")
        or value.get("assignments_acquired", 0) < ERROR_RETRY_COUNT
        or value.get("assignments_cleanup_verified") != value.get("assignments_acquired")
        or value.get("assignment_release_rows", 0) + value.get("assignment_cancellation_rows", 0)
        != value.get("assignments_acquired")
        or value.get("outer_sessions_created") != value.get("recorded_outer_sessions")
        or value.get("outer_sessions_deleted") != value.get("recorded_outer_sessions")
        or value.get("assignment_measured_high_water") not in accepted_high_water
        or value.get("assignment_event_order_high_water")
        != value.get("assignment_measured_high_water")
        or value.get("outer_session_high_water", 0) < value.get("assignment_measured_high_water", 0)
        or value.get("outer_session_high_water", 0) > value.get("assignments_acquired", 0)
    ):
        raise QwenRetryError("cleanup_invalid")
    return value, artifact


def _validate_run_identity(run_dir: Path, *, task_sha256: str, config_sha256: str) -> dict[str, Any]:
    try:
        from eval_run_identity import load_eval_run_identity

        envelope = load_eval_run_identity(run_dir / "eval_run_identity.json", verify_references=True)
    except Exception as error:
        raise QwenRetryError("run_identity_invalid") from error
    identity = envelope.get("identity")
    if not isinstance(identity, Mapping):
        raise QwenRetryError("run_identity_invalid")
    source = identity.get("source")
    contract = identity.get("contract")
    execution = identity.get("execution")
    inputs = identity.get("inputs")
    config = identity.get("config")
    deployment = identity.get("deployment")
    task_record = inputs.get("task_file") if isinstance(inputs, Mapping) else None
    source_config = config.get("source") if isinstance(config, Mapping) else None
    resolved_config = config.get("resolved") if isinstance(config, Mapping) else None
    router = deployment.get("router") if isinstance(deployment, Mapping) else None
    worker_manifest = deployment.get("worker_manifest") if isinstance(deployment, Mapping) else None
    runtime = execution.get("runtime") if isinstance(execution, Mapping) else None
    environment = execution.get("sandoq_environment") if isinstance(execution, Mapping) else None
    harness = contract.get("harness") if isinstance(contract, Mapping) else None
    if (
        identity.get("role") != RETRY_RUN_IDENTITY_ROLE
        or not isinstance(source, Mapping)
        or source.get("sandbox_provider") != "sandoq"
        or not isinstance(contract, Mapping)
        or contract.get("model") != direct.EXPECTED_MODEL
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "medium"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or contract.get("context_tokens")
        != {
            "max_input_tokens": MAX_SEQUENCE_TOKENS,
            "max_output_tokens": MAX_SEQUENCE_TOKENS,
            "max_total_tokens": MAX_SEQUENCE_TOKENS,
        }
        or contract.get("sampling_max_tokens") != 32_768
        or contract.get("capture_model_io") is not True
        or contract.get("retain_traces") is not False
        or not isinstance(harness, Mapping)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.4.6"
        or harness.get("placement") != "sandbox"
        or harness.get("step_limit") != 200
        or harness.get("request_timeout_seconds") != 15_000
        or harness.get("request_max_retries") != 0
        or not isinstance(task_record, Mapping)
        or task_record.get("count") != ERROR_RETRY_COUNT
        or task_record.get("sha256") != task_sha256
        or Path(str(task_record.get("path", ""))).resolve() != run_dir / "inputs/task_file.txt"
        or not isinstance(source_config, Mapping)
        or source_config.get("sha256") != config_sha256
        or Path(str(source_config.get("path", ""))).resolve() != run_dir / "inputs/source_config.toml"
        or not isinstance(resolved_config, Mapping)
        or Path(str(resolved_config.get("path", ""))).resolve() != run_dir / "config.toml"
        or not isinstance(execution, Mapping)
        or execution.get("cleanup_must_succeed") is not True
        or execution.get("rollout_concurrency") != 64
        or execution.get("multiplex") != 64
        or execution.get("http_max_connections") != 32
        or execution.get("http_max_keepalive_connections") != 32
        or not isinstance(runtime, Mapping)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("expected_environment") != "oci-runner-firecracker-small"
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "sandoq"
        or type(runtime.get("provisioning_retries")) is not int
        or runtime.get("provisioning_retries") != SANDOQ_PROVISIONING_RETRIES
        or not isinstance(environment, Mapping)
        or environment.get("environment") != "oci-runner-firecracker-small"
        or environment.get("task_network") != "public"
        or environment.get("provider_task_network") != "host"
        or environment.get("provider_profile_sha256")
        != "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
        or environment.get("tunnel_policy") != "native-sandoq-reverse-tunnel"
        or environment.get("allow_dockerhub_fallback") is not False
        or any(
            key in environment
            for key in (
                "runtime_tunnel_receipt_sha256",
                "runtime_resource_receipt_sha256",
                "miniswe_compatibility_receipt_sha256",
            )
        )
        or environment.get("pool_size") != 64
        or environment.get("pool_min_size") != 0
        or not isinstance(deployment, Mapping)
        or deployment.get("kind") != "direct_qwen"
        or not isinstance(router, Mapping)
        or router.get("policy") != "consistent_hash"
        or router.get("request_id_headers") != ["x-session-id"]
        or router.get("provider_concurrency") != 32
        or not isinstance(worker_manifest, Mapping)
        or Path(str(worker_manifest.get("path", ""))).resolve() != run_dir / "direct_workers.json"
    ):
        raise QwenRetryError("run_identity_invalid")
    return envelope


def _pop_exact(mapping: dict[str, Any], key: str, expected: object) -> None:
    if key not in mapping or mapping.pop(key) != expected:
        raise QwenRetryError("run_config_binding_mismatch")


def _validate_resolved_config(
    body: bytes,
    *,
    source_body: bytes,
    run_dir: Path,
    task_sha256: str,
) -> dict[str, Any]:
    resolved = _parse_toml(body, "run_config_invalid")
    source = _parse_toml(source_body, "retry_config_invalid")
    client = resolved.get("client")
    taskset = resolved.get("taskset")
    runtime = resolved.get("harness", {}).get("runtime") if isinstance(resolved.get("harness"), dict) else None
    retries = resolved.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
    if not isinstance(client, dict) or not isinstance(taskset, dict) or not isinstance(runtime, dict):
        raise QwenRetryError("run_config_invalid")
    endpoint = urlsplit(str(client.get("base_url", "")))
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or endpoint.port is None
        or endpoint.path.rstrip("/") != "/v1"
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.query
        or endpoint.fragment
        or Path(str(resolved.get("output_dir", ""))).resolve() != run_dir
        or Path(str(taskset.get("task_file", ""))).resolve() != run_dir / "inputs/task_file.txt"
        or taskset.get("task_file_sha256") != task_sha256
        or Path(str(taskset.get("image_manifest", ""))).resolve() != run_dir / "inputs/image_manifest.json"
        or taskset.get("image_manifest_sha256") != CANONICAL_IMAGE_MANIFEST_SHA256
    ):
        raise QwenRetryError("run_config_binding_mismatch")

    # Normalize only the deterministic fields added or path-rewritten by the
    # evaluator.  Any other semantic drift remains visible in the final equality.
    normalized = json.loads(json.dumps(resolved))
    for key, expected in (
        ("shuffle", False),
        ("verbose", False),
        ("dry_run", False),
        ("server", False),
        ("output_dir", str(run_dir)),
    ):
        _pop_exact(normalized, key, expected)
    normalized_taskset = normalized["taskset"]
    source_taskset = source["taskset"]
    for key, expected in (
        ("dataset", "hello-world"),
        ("require_image", False),
        ("verifier_image_suffix", "-verifier"),
        ("use_declared_images", False),
        ("oracle_solution_network_mode", "declared"),
    ):
        _pop_exact(normalized_taskset, key, expected)
    normalized_taskset["task_file"] = source_taskset["task_file"]
    normalized_taskset["image_manifest"] = source_taskset["image_manifest"]
    normalized_runtime = normalized["harness"]["runtime"]
    provisioning_retries = normalized_runtime.get("provisioning_retries")
    if type(provisioning_retries) is not int or provisioning_retries != SANDOQ_PROVISIONING_RETRIES:
        raise QwenRetryError("run_config_binding_mismatch")
    normalized_runtime.pop("provisioning_retries")
    for key, expected in (
        ("image", "python:3.11-slim"),
        ("workdir", "/app"),
        ("cpu", 1.0),
        ("memory", 2.0),
        ("disk", 5.0),
    ):
        _pop_exact(normalized_runtime, key, expected)
    normalized_client = normalized["client"]
    normalized_client["base_url"] = source["client"]["base_url"]
    _pop_exact(normalized_client, "headers", {})
    _pop_exact(normalized_client, "extra_headers_from_state", {})
    if not isinstance(rollout_retries, dict):
        raise QwenRetryError("run_config_binding_mismatch")
    _pop_exact(normalized["retries"]["rollout"], "exclude", [])
    _pop_exact(normalized, "args", {})
    _pop_exact(normalized, "extra_env_kwargs", {})
    _pop_exact(normalized, "pool", {"type": "elastic", "multiplex": 128})
    if normalized != source:
        raise QwenRetryError("run_config_binding_mismatch")
    return resolved


def _validate_worker_manifest(run_dir: Path, task_sha256: str) -> tuple[dict[str, Any], Artifact]:
    path = run_dir / "direct_workers.json"
    artifact = _artifact(path, "worker_manifest_invalid", max_bytes=MAX_CERTIFICATE_BYTES)
    try:
        value = direct.validate_saved_manifest(path, expected_admission=(64, 32, 32))
    except direct.DirectWorkerError as error:
        raise QwenRetryError("worker_manifest_invalid") from error
    if (
        len(value.get("workers", ())) != 24
        or value.get("approved_task_allowlist_sha256") != task_sha256
        or value.get("router", {}).get("policy") != "consistent_hash"
        or value.get("router", {}).get("request_id_headers") != ["x-session-id"]
    ):
        raise QwenRetryError("worker_manifest_invalid")
    return value, artifact


def _run_evidence(
    context: SelectionContext,
    selection_value: Mapping[str, Any],
    run_dir: Path,
) -> tuple[TraceScan, dict[str, Any], dict[str, Any]]:
    run_dir = _private_directory(run_dir, "run_dir_invalid")
    if run_dir != context.expected_run_dir:
        raise QwenRetryError("run_binding_mismatch")
    task_record = selection_value["selection"]["task_file"]
    config_record = selection_value["execution"]["config"]
    task_sha256 = str(task_record["sha256"])
    config_sha256 = str(config_record["sha256"])
    expected_task_body = _retry_task_body(context)
    run_task_body, run_task_artifact = _read_regular(
        run_dir / "inputs/task_file.txt",
        "run_task_file_invalid",
        max_bytes=MAX_TASK_FILE_BYTES,
        required_mode=0o600,
    )
    run_source_config_body, run_source_config_artifact = _read_regular(
        run_dir / "inputs/source_config.toml",
        "run_source_config_invalid",
        max_bytes=MAX_CONFIG_BYTES,
        required_mode=0o600,
    )
    selection_config_body, _selection_config_artifact = _read_regular(
        Path(str(config_record["path"])),
        "retry_config_invalid",
        max_bytes=MAX_CONFIG_BYTES,
        required_mode=0o600,
    )
    if (
        run_task_body != expected_task_body
        or run_task_artifact.sha256 != task_sha256
        or run_source_config_body != selection_config_body
        or run_source_config_artifact.sha256 != config_sha256
    ):
        raise QwenRetryError("run_input_binding_mismatch")
    profile = _validate_provider_profile(context.profile_body)
    resolved_config_body, resolved_config_artifact = _read_regular(
        run_dir / "config.toml",
        "run_config_invalid",
        max_bytes=MAX_CONFIG_BYTES,
        required_mode=0o600,
    )
    _validate_retry_config(
        selection_config_body,
        task_file=Path(str(task_record["path"])),
        task_sha256=task_sha256,
        profile=profile,
    )
    _validate_resolved_config(
        resolved_config_body,
        source_body=selection_config_body,
        run_dir=run_dir,
        task_sha256=task_sha256,
    )
    _workers, worker_artifact = _validate_worker_manifest(run_dir, task_sha256)
    identity = _validate_run_identity(run_dir, task_sha256=task_sha256, config_sha256=config_sha256)
    identity_value = identity["identity"]
    if (
        identity_value.get("config", {}).get("resolved", {}).get("sha256") != resolved_config_artifact.sha256
        or identity_value.get("deployment", {}).get("worker_manifest", {}).get("sha256")
        != worker_artifact.sha256
    ):
        raise QwenRetryError("run_identity_binding_mismatch")
    cleanup, cleanup_artifact = _validate_cleanup(run_dir / "sandoq_cleanup_audit.json")
    retry_scan = _scan_results(
        run_dir / "results.jsonl",
        expected_sha256=_artifact(run_dir / "results.jsonl", "retry_results_invalid").sha256,
        expected_count=ERROR_RETRY_COUNT,
        evaluator_order=tuple(sorted(context.retry_members)),
        validate_positive=True,
        allowed_members=frozenset(context.retry_members),
    )
    evidence = {
        "cleanup": cleanup_artifact.value(path=run_dir / "sandoq_cleanup_audit.json"),
        "eval_run_identity": _artifact(
            run_dir / "eval_run_identity.json", "run_identity_invalid", max_bytes=MAX_CERTIFICATE_BYTES
        ).value(path=run_dir / "eval_run_identity.json"),
        "resolved_config": resolved_config_artifact.value(path=run_dir / "config.toml"),
        "results": retry_scan.artifact.value(path=run_dir / "results.jsonl"),
        "worker_manifest": worker_artifact.value(path=run_dir / "direct_workers.json"),
    }
    runtime = {
        "cleanup_failures": cleanup["failures"],
        "eval_run_identity_sha256": identity["eval_run_identity_sha256"],
        "provider_concurrency": 32,
        "router_policy": "consistent_hash",
        "worker_count": 24,
    }
    return retry_scan, evidence, runtime


def _retry_certificate_value(
    *,
    contract_sha256: str,
    retry_scan: TraceScan,
    evidence: Mapping[str, Any],
    runtime: Mapping[str, Any],
    context: SelectionContext,
) -> dict[str, Any]:
    accepted_members = frozenset(
        member for member, record in retry_scan.rows.items() if record.outcome == "positive"
    )
    universe_indices = {member: index for index, member in enumerate(context.universe_members)}
    accepted_indices = (universe_indices[member] for member in context.universe_members if member in accepted_members)
    counts = Counter(retry_scan.counts)
    retained = ERROR_RETRY_COUNT - len(accepted_members)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RETRY_CERTIFICATE_KIND,
        "state": "passed",
        "selection_contract_sha256": contract_sha256,
        "run": dict(evidence),
        "runtime": dict(runtime),
        "retry_outcomes": {
            "accepted_positive": len(accepted_members),
            "error": counts["error"],
            "invalid_positive": counts["invalid_positive"],
            "retained_original": retained,
            "total": ERROR_RETRY_COUNT,
            "zero": counts["zero"],
        },
        "accepted": {
            "canonical_indices_sha256": _indices_sha256(iter(accepted_indices)),
            "count": len(accepted_members),
            "predicate": "reward-one-and-exact-model-io-and-sft-trainable",
            "row_sha256_set_sha256": _sha256(
                "".join(f"{retry_scan.rows[member].row_sha256}\n" for member in sorted(accepted_members)).encode()
            ),
        },
        "trace_contract": {
            "id": RETRY_MODEL_IO_CONTRACT_ID,
            "sha256": audit_traces.model_io_contract_sha256(RETRY_MODEL_IO_CONTRACT),
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        },
        "code": {"module_sha256": _module_sha256()},
    }


def certify(
    *,
    contract: Path,
    contract_sha256: str,
    run_dir: Path,
    cleanup_audit: Path,
    output: Path,
) -> dict[str, Any]:
    value, _body = _load_contract(contract, contract_sha256)
    context = _context_from_contract(value)
    run_dir = _normalized_absolute(run_dir, "run_dir_invalid")
    cleanup_audit = _normalized_absolute(cleanup_audit, "cleanup_invalid")
    output = _normalized_absolute(output, "certificate_output_invalid", must_exist=False)
    if cleanup_audit != run_dir / "sandoq_cleanup_audit.json" or output != run_dir / RETRY_CERTIFICATE_FILENAME:
        raise QwenRetryError("certificate_output_binding_invalid")
    with _completed_run_lock(run_dir):
        retry_scan, evidence, runtime = _run_evidence(context, value, run_dir)
        certificate = _retry_certificate_value(
            contract_sha256=contract_sha256,
            retry_scan=retry_scan,
            evidence=evidence,
            runtime=runtime,
            context=context,
        )
        artifact = _write_exclusive(output, _canonical_json(certificate))
    return {
        "accepted_positive": certificate["accepted"]["count"],
        "certificate_sha256": artifact.sha256,
        "retained_original": certificate["retry_outcomes"]["retained_original"],
        "state": "certified",
        "total": ERROR_RETRY_COUNT,
    }


def _load_retry_certificate(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    if SHA256_RE.fullmatch(expected_sha256 or "") is None:
        raise QwenRetryError("retry_certificate_digest_invalid")
    body, artifact = _read_regular(
        path,
        "retry_certificate_invalid",
        max_bytes=MAX_CERTIFICATE_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise QwenRetryError("retry_certificate_digest_mismatch")
    value = _parse_object(body, "retry_certificate_invalid", canonical=True)
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != RETRY_CERTIFICATE_KIND
        or value.get("state") != "passed"
    ):
        raise QwenRetryError("retry_certificate_invalid")
    return value, body


def _read_indexed_row(path: Path, record: TraceRecord) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            handle.seek(record.offset)
            body = handle.read(record.length)
    except OSError as error:
        raise QwenRetryError("results_unreadable") from error
    if len(body) != record.length or _sha256(body) != record.row_sha256:
        raise QwenRetryError("results_changed")
    return body


def _write_merged_results(
    path: Path,
    *,
    context: SelectionContext,
    retry_scan: TraceScan,
) -> tuple[Artifact, dict[str, int]]:
    accepted = {member for member, record in retry_scan.rows.items() if record.outcome == "positive"}
    continuation_set = frozenset(context.continuation_members)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    size = 0
    counts: Counter[str] = Counter()
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            for member in context.universe_members:
                if member in accepted:
                    source_path = context.expected_run_dir / "results.jsonl"
                    record = retry_scan.rows[member]
                elif member in continuation_set:
                    source_path = context.continuation_results
                    record = context.continuation_scan.rows[member]
                else:
                    source_path = context.original_results
                    record = context.original_scan.rows[member]
                body = _read_indexed_row(source_path, record)
                output.write(body)
                digest.update(body)
                size += len(body)
                counts[record.outcome if record.outcome != "invalid_positive" else "error"] += 1
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise QwenRetryError("merged_results_publish_failed") from error
    if sum(counts.values()) != CANONICAL_UNIVERSE_COUNT:
        raise QwenRetryError("merged_coverage_invalid")
    return Artifact(size, digest.hexdigest()), dict(counts)


def _merged_certificate_value(
    *,
    output: Path,
    merged_results: Artifact,
    merged_counts: Mapping[str, int],
    contract_sha256: str,
    retry_certificate_sha256: str,
    retry_certificate: Mapping[str, Any],
    context: SelectionContext,
) -> dict[str, Any]:
    accepted = int(retry_certificate["accepted"]["count"])
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MERGED_CERTIFICATE_KIND,
        "state": "passed",
        "canonical_predecessor": {
            "kind": "qwen-sandoq-source-continuation-pass-only",
            "sha256": CONTINUATION_CERTIFICATE_SHA256,
        },
        "retry": {
            "accepted_positive": accepted,
            "run_certificate_sha256": retry_certificate_sha256,
            "selection_contract_sha256": contract_sha256,
        },
        "coverage": {
            "canonical_order": True,
            "disjoint": True,
            "exact": True,
            "exhaustive": True,
            "task_count": CANONICAL_UNIVERSE_COUNT,
            "universe_task_file_sha256": CANONICAL_UNIVERSE_TASK_FILE_SHA256,
        },
        "outcomes": {
            "error": merged_counts.get("error", 0),
            "positive": merged_counts.get("positive", 0),
            "total": sum(merged_counts.values()),
            "zero": merged_counts.get("zero", 0),
        },
        "results": merged_results.value(path=output / MERGED_RESULTS_FILENAME),
        "source_results": {
            "continuation": context.source_artifacts["continuation_results"].value(),
            "original": context.source_artifacts["original_results"].value(),
        },
        "trainability": {
            "all_new_positive_rows_validated": True,
            "base_positive_rows_bound_by_predecessor": BASE_POSITIVE_COUNT,
            "model_io_contract_id": RETRY_MODEL_IO_CONTRACT_ID,
            "model_io_contract_sha256": audit_traces.model_io_contract_sha256(RETRY_MODEL_IO_CONTRACT),
            "new_positive_rows": accepted,
        },
        "code": {"module_sha256": _module_sha256()},
    }


def _merge_manifest_value(
    *,
    output: Path,
    results_artifact: Artifact,
    certificate_artifact: Artifact,
    contract_sha256: str,
    retry_certificate_sha256: str,
    outcomes: Mapping[str, int],
) -> dict[str, Any]:
    results = results_artifact.value(path=output / MERGED_RESULTS_FILENAME)
    certificate = certificate_artifact.value(path=output / MERGED_CERTIFICATE_FILENAME)
    safe_counts = {
        "error": outcomes.get("error", 0),
        "positive": outcomes.get("positive", 0),
        "total": sum(outcomes.values()),
        "zero": outcomes.get("zero", 0),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MERGE_MANIFEST_KIND,
        "state": "ready",
        "artifacts": {"certificate": certificate, "results": results},
        "lineage": {
            "canonical_predecessor_certificate_sha256": CONTINUATION_CERTIFICATE_SHA256,
            "retry_run_certificate_sha256": retry_certificate_sha256,
            "selection_contract_sha256": contract_sha256,
        },
        "counts": safe_counts,
        "package_inputs": {
            "certificate": certificate,
            "results": results,
            "task_count": CANONICAL_UNIVERSE_COUNT,
        },
        "sft_export_inputs": {
            "certificate": certificate,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "results": results,
            "selection": "pass-only-positive",
            "task_count": CANONICAL_UNIVERSE_COUNT,
        },
    }


def merge(
    *,
    contract: Path,
    contract_sha256: str,
    retry_certificate: Path,
    retry_certificate_sha256: str,
    run_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    selection, _selection_body = _load_contract(contract, contract_sha256)
    context = _context_from_contract(selection)
    run_dir = _normalized_absolute(run_dir, "run_dir_invalid")
    if run_dir != context.expected_run_dir:
        raise QwenRetryError("run_binding_mismatch")
    retry_certificate = _normalized_absolute(retry_certificate, "retry_certificate_invalid")
    if retry_certificate != run_dir / RETRY_CERTIFICATE_FILENAME:
        raise QwenRetryError("retry_certificate_binding_invalid")
    certificate, _certificate_body = _load_retry_certificate(retry_certificate, retry_certificate_sha256)
    with _completed_run_lock(run_dir):
        retry_scan, evidence, runtime = _run_evidence(context, selection, run_dir)
        expected_retry_certificate = _retry_certificate_value(
            contract_sha256=contract_sha256,
            retry_scan=retry_scan,
            evidence=evidence,
            runtime=runtime,
            context=context,
        )
        if certificate != expected_retry_certificate:
            raise QwenRetryError("retry_certificate_evidence_mismatch")
        output = _create_private_output(output_dir)
        try:
            results_artifact, outcomes = _write_merged_results(
                output / MERGED_RESULTS_FILENAME,
                context=context,
                retry_scan=retry_scan,
            )
            accepted = certificate["accepted"]["count"]
            if (
                outcomes.get("positive", 0) != BASE_POSITIVE_COUNT + accepted
                or outcomes.get("zero", 0) != BASE_ZERO_COUNT
                or outcomes.get("error", 0) != BASE_ERROR_COUNT - accepted
                or sum(outcomes.values()) != CANONICAL_UNIVERSE_COUNT
            ):
                raise QwenRetryError("merged_outcome_partition_invalid")
            merged_certificate = _merged_certificate_value(
                output=output,
                merged_results=results_artifact,
                merged_counts=outcomes,
                contract_sha256=contract_sha256,
                retry_certificate_sha256=retry_certificate_sha256,
                retry_certificate=certificate,
                context=context,
            )
            merged_certificate_artifact = _write_exclusive(
                output / MERGED_CERTIFICATE_FILENAME,
                _canonical_json(merged_certificate),
            )
            manifest = _merge_manifest_value(
                output=output,
                results_artifact=results_artifact,
                certificate_artifact=merged_certificate_artifact,
                contract_sha256=contract_sha256,
                retry_certificate_sha256=retry_certificate_sha256,
                outcomes=outcomes,
            )
            manifest_artifact = _write_exclusive(output / MERGE_MANIFEST_FILENAME, _canonical_json(manifest))
        except BaseException:
            _remove_owned_output(output)
            raise
    return {
        "certificate_sha256": merged_certificate_artifact.sha256,
        "error": outcomes.get("error", 0),
        "manifest_sha256": manifest_artifact.sha256,
        "positive": outcomes.get("positive", 0),
        "state": "merged",
        "task_count": CANONICAL_UNIVERSE_COUNT,
        "zero": outcomes.get("zero", 0),
    }


def _add_contract_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selector = commands.add_parser("select")
    selector.add_argument("--original-results", type=Path, required=True)
    selector.add_argument("--original-results-sha256", required=True)
    selector.add_argument("--continuation-results", type=Path, required=True)
    selector.add_argument("--continuation-results-sha256", required=True)
    selector.add_argument("--continuation-certificate", type=Path, required=True)
    selector.add_argument("--continuation-certificate-sha256", required=True)
    selector.add_argument("--continuation-task-file", type=Path, required=True)
    selector.add_argument("--continuation-task-file-sha256", required=True)
    selector.add_argument("--canonical-universe-task-file", type=Path, required=True)
    selector.add_argument("--canonical-universe-task-file-sha256", required=True)
    selector.add_argument("--config-template", type=Path, required=True)
    selector.add_argument("--config-template-sha256", required=True)
    selector.add_argument("--provider-profile", type=Path, required=True)
    selector.add_argument("--provider-profile-sha256", required=True)
    selector.add_argument("--expected-run-dir", type=Path, required=True)
    selector.add_argument("--output-dir", type=Path, required=True)

    verifier = commands.add_parser("verify-launch")
    _add_contract_arguments(verifier)
    verifier.add_argument("--task-file", type=Path, required=True)
    verifier.add_argument("--task-file-sha256", required=True)
    verifier.add_argument("--config", type=Path, required=True)
    verifier.add_argument("--config-sha256", required=True)
    verifier.add_argument("--provider-profile", type=Path, required=True)
    verifier.add_argument("--provider-profile-sha256", required=True)
    verifier.add_argument("--run-dir", type=Path, required=True)
    verifier.add_argument("--allow-wrapper-artifacts", action="store_true")

    certifier = commands.add_parser("certify")
    _add_contract_arguments(certifier)
    certifier.add_argument("--run-dir", type=Path, required=True)
    certifier.add_argument("--cleanup-audit", type=Path, required=True)
    certifier.add_argument("--output", type=Path, required=True)

    merger = commands.add_parser("merge")
    _add_contract_arguments(merger)
    merger.add_argument("--retry-certificate", type=Path, required=True)
    merger.add_argument("--retry-certificate-sha256", required=True)
    merger.add_argument("--run-dir", type=Path, required=True)
    merger.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = vars(_parser().parse_args(argv))
        command = args.pop("command")
        if command == "select":
            summary = select(**args)
        elif command == "verify-launch":
            summary = verify_launch(**args)
        elif command == "certify":
            summary = certify(**args)
        else:
            summary = merge(**args)
        if any(key in FORBIDDEN_PUBLIC_KEYS for key in summary):
            raise QwenRetryError("public_summary_invalid")
    except QwenRetryError as error:
        raise SystemExit(error.code) from None
    except Exception:
        raise SystemExit("qwen_2499_error_retry_failed") from None
    print(json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
