#!/usr/bin/env python3
"""Run the terminal Qwen repair, pass-only export, and merge chain.

The controller emits only aggregate counts, digests, and stable status codes.
Every child process writes to a private log, and child output is never forwarded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import export_sft as exporter
import finalize_qwen_repair_sft as repair_finalizer
import finalize_qwen_sft as common
import merge_qwen_sft as merger

EXPECTED_ORIGINAL_COUNT = 2_500
MAX_SEQUENCE_TOKENS = 262_144
MAX_CHILD_SUMMARY_BYTES = 1 << 20
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
STAGE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
DIRECT_FORBIDDEN_ENV = frozenset(
    {
        "INFERENCE_BASE_URL",
        "INFERENCE_DEPLOYMENT_ID",
        "INFERENCE_JOB_ID",
        "INFERENCE_PROXY_INFO",
        "INFERENCE_PROXY_URL",
        "DIRECT_QWEN_MANIFEST_SHA256",
        "DIRECT_QWEN_ROUTER_POLICY",
        "DIRECT_QWEN_REQUEST_ID_HEADERS",
        "DIRECT_QWEN_PROVIDER_CONCURRENCY",
        "RESUME_DIR",
    }
)


class RepairChainError(RuntimeError):
    """A fail-closed controller error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise RepairChainError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class RepairChainOptions:
    project_dir: Path
    expected_project_revision: str
    source_root: Path
    source_dir: Path
    approved_task_file_sha256: str
    expected_provenance_sha256: str
    runtime_root: Path
    runtime_dir: Path
    output_root: Path
    original_export_dir: Path
    repair_export_dir: Path
    merged_output_dir: Path
    validation_permyriad: int
    split_salt: str


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    project_dir: Path
    workflow_dir: Path
    source_root: Path
    source_dir: Path
    approved_task_file: Path
    provenance: Path
    runtime_root: Path
    runtime_dir: Path
    output_root: Path
    original_export_dir: Path
    repair_export_dir: Path
    merged_output_dir: Path


@dataclass(frozen=True, slots=True)
class ProjectAttestation:
    revision: str
    submodules: Mapping[str, str]
    materializer_sha256: str
    exporter_sha256: str
    repair_template_sha256: str


@dataclass(frozen=True, slots=True)
class ChildCommand:
    stage: str
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    expects_summary: bool = True


@dataclass(frozen=True, slots=True)
class FileState:
    mode: int
    size: int
    sha256: str


ChildRunner = Callable[[ChildCommand, Path], dict[str, Any] | None]
ProjectValidator = Callable[[Path, str], ProjectAttestation]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _is_normalized_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(path))


def _canonical_directory(path: Path, code: str) -> Path:
    if not _is_normalized_absolute(path):
        raise RepairChainError(code)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise RepairChainError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise RepairChainError(code)
    return resolved


def _unsafe_boundary(path: Path) -> bool:
    if path == Path(path.anchor) or len(path.parts) < 5:
        return True
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        return True
    return path == home or home.is_relative_to(path)


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _strict_descendant(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _regular_file(path: Path, code: str, *, mode: int | None = None) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise RepairChainError(code) from error
    if not stat.S_ISREG(metadata.st_mode) or resolved != path:
        raise RepairChainError(code)
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise RepairChainError(code)
    return path


def _new_path(path: Path, root: Path, code: str) -> Path:
    if not _is_normalized_absolute(path) or not path.name or os.path.lexists(path):
        raise RepairChainError(code)
    parent = _canonical_directory(path.parent, code)
    candidate = parent / path.name
    if candidate != path or not _strict_descendant(candidate, root):
        raise RepairChainError(code)
    return candidate


def _resolve_paths(options: RepairChainOptions) -> ResolvedPaths:
    project = _canonical_directory(options.project_dir, "project_path_unsafe")
    source_root = _canonical_directory(options.source_root, "source_root_unsafe")
    source = _canonical_directory(options.source_dir, "source_path_unsafe")
    runtime_root = _canonical_directory(options.runtime_root, "runtime_root_unsafe")
    output_root = _canonical_directory(options.output_root, "output_root_unsafe")
    roots = (source_root, runtime_root, output_root)
    if any(_unsafe_boundary(root) for root in roots):
        raise RepairChainError("path_boundary_unsafe")
    if any(_overlap(first, second) for index, first in enumerate(roots) for second in roots[index + 1 :]):
        raise RepairChainError("path_boundaries_overlap")
    if any(_overlap(project, root) for root in roots):
        raise RepairChainError("runtime_path_overlaps_project")
    if not _strict_descendant(source, source_root):
        raise RepairChainError("source_outside_boundary")

    runtime = _new_path(options.runtime_dir, runtime_root, "runtime_path_unsafe")
    outputs = (
        _new_path(options.original_export_dir, output_root, "original_output_path_unsafe"),
        _new_path(options.repair_export_dir, output_root, "repair_output_path_unsafe"),
        _new_path(options.merged_output_dir, output_root, "merged_output_path_unsafe"),
    )
    if any(_overlap(first, second) for index, first in enumerate(outputs) for second in outputs[index + 1 :]):
        raise RepairChainError("output_paths_overlap")
    if any(_overlap(runtime, output) or _overlap(source, output) for output in outputs):
        raise RepairChainError("artifact_paths_overlap")

    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    _canonical_directory(workflow, "project_workflow_invalid")
    approved = _regular_file(source / "inputs" / "task_file.txt", "approved_task_file_invalid")
    provenance = _regular_file(source / "provenance.txt", "source_provenance_invalid")
    for relative in ("config.toml", "results.jsonl"):
        _regular_file(source / relative, "source_artifact_invalid")
    return ResolvedPaths(
        project_dir=project,
        workflow_dir=workflow,
        source_root=source_root,
        source_dir=source,
        approved_task_file=approved,
        provenance=provenance,
        runtime_root=runtime_root,
        runtime_dir=runtime,
        output_root=output_root,
        original_export_dir=outputs[0],
        repair_export_dir=outputs[1],
        merged_output_dir=outputs[2],
    )


def _sha256(path: Path, code: str, *, max_bytes: int | None = None) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RepairChainError(code) from error
    digest = hashlib.sha256()
    size = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RepairChainError(code)
        while chunk := os.read(descriptor, 1 << 20):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise RepairChainError(code)
            digest.update(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise RepairChainError(code) from error
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RepairChainError(code)
    return digest.hexdigest()


def _read_bytes(path: Path, code: str, *, limit: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise RepairChainError(code)
            body = handle.read(limit + 1)
    except OSError as error:
        raise RepairChainError(code) from error
    if len(body) > limit:
        raise RepairChainError(code)
    return body


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise RepairChainError(code) from error
    if not isinstance(value, dict):
        raise RepairChainError(code)
    return value


def _default_project_validator(project: Path, revision: str) -> ProjectAttestation:
    try:
        validated = common._validate_repository(project, revision)
    except common.FinalizationError as error:
        raise RepairChainError(error.code) from error
    workflow = validated / "user" / "tianhaowu" / "terminal_bench_vmvm"
    controller = _regular_file(workflow / "qwen_repair_chain.py", "project_controller_invalid")
    if Path(__file__).resolve(strict=True) != controller:
        raise RepairChainError("controller_origin_mismatch")
    submodules: dict[str, str] = {}
    for relative in common.REQUIRED_RUNTIME_SUBMODULES:
        try:
            record = common._run_git(
                validated,
                ["ls-tree", revision, "--", relative],
                "project_submodules_unavailable",
            ).strip()
        except common.FinalizationError as error:
            raise RepairChainError(error.code) from error
        fields = record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or GIT_SHA_PATTERN.fullmatch(fields[2]) is None
            or fields[3] != relative
        ):
            raise RepairChainError("project_submodule_mismatch")
        submodules[relative] = fields[2]
    return ProjectAttestation(
        revision=revision,
        submodules=submodules,
        materializer_sha256=_sha256(
            workflow / "materialize_qwen_repair.py",
            "project_materializer_invalid",
        ),
        exporter_sha256=_sha256(
            workflow / "export_sft.py",
            "project_exporter_invalid",
        ),
        repair_template_sha256=_sha256(
            workflow / "configs" / "eval" / "mobius_qwen_a95b_2500.toml",
            "project_repair_template_invalid",
        ),
    )


def _validate_options(options: RepairChainOptions) -> None:
    if GIT_SHA_PATTERN.fullmatch(options.expected_project_revision) is None:
        raise RepairChainError("project_revision_invalid")
    if not _valid_sha256(options.approved_task_file_sha256):
        raise RepairChainError("approval_digest_invalid")
    if not _valid_sha256(options.expected_provenance_sha256):
        raise RepairChainError("provenance_digest_invalid")
    if not _is_plain_int(options.validation_permyriad) or not 0 <= options.validation_permyriad < 10_000:
        raise RepairChainError("validation_permyriad_invalid")
    if not options.split_salt or "\x00" in options.split_salt:
        raise RepairChainError("split_salt_invalid")


def _validate_attestation(
    validator: ProjectValidator,
    paths: ResolvedPaths,
    options: RepairChainOptions,
    expected: ProjectAttestation | None = None,
) -> ProjectAttestation:
    attestation = validator(paths.project_dir, options.expected_project_revision)
    if (
        attestation.revision != options.expected_project_revision
        or set(attestation.submodules) != set(common.REQUIRED_RUNTIME_SUBMODULES)
        or any(GIT_SHA_PATTERN.fullmatch(value) is None for value in attestation.submodules.values())
        or not _valid_sha256(attestation.materializer_sha256)
        or not _valid_sha256(attestation.exporter_sha256)
        or not _valid_sha256(attestation.repair_template_sha256)
        or (expected is not None and attestation != expected)
    ):
        raise RepairChainError("project_attestation_mismatch")
    return attestation


def _load_source_config(path: Path) -> dict[str, Any]:
    body = _read_bytes(path, "source_config_invalid", limit=1 << 20)
    try:
        config = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RepairChainError("source_config_invalid") from error
    if not isinstance(config, dict):
        raise RepairChainError("source_config_invalid")
    return config


def _task_record_count(path: Path) -> int:
    body = _read_bytes(path, "approved_task_file_invalid", limit=16 << 20)
    try:
        lines = body.decode().splitlines()
    except UnicodeDecodeError as error:
        raise RepairChainError("approved_task_file_invalid") from error
    identifiers: set[str] = set()
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        identifier = raw.strip().split("\t", 1)[0]
        if not identifier or identifier in identifiers:
            raise RepairChainError("approved_task_file_invalid")
        identifiers.add(identifier)
    return len(identifiers)


def _validate_original_contract(paths: ResolvedPaths, options: RepairChainOptions) -> None:
    if _sha256(paths.approved_task_file, "approval_digest_unavailable") != options.approved_task_file_sha256:
        raise RepairChainError("approval_digest_mismatch")
    if _sha256(paths.provenance, "provenance_digest_unavailable") != options.expected_provenance_sha256:
        raise RepairChainError("provenance_digest_mismatch")
    if _task_record_count(paths.approved_task_file) != EXPECTED_ORIGINAL_COUNT:
        raise RepairChainError("approved_task_count_mismatch")
    config = _load_source_config(paths.source_dir / "config.toml")
    client = config.get("client")
    sampling = config.get("sampling")
    chat = sampling.get("chat_template_kwargs") if isinstance(sampling, dict) else None
    if (
        config.get("num_tasks") != EXPECTED_ORIGINAL_COUNT
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != direct.MAX_DIRECT_CONCURRENCY
        or config.get("multiplex") != direct.MAX_DIRECT_CONCURRENCY
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("max_connections") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or client.get("max_keepalive_connections") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != 32_768
        or not isinstance(chat, dict)
        or chat.get("enable_thinking") is not True
        or chat.get("preserve_thinking") is not True
    ):
        raise RepairChainError("source_generation_contract_invalid")


def _snapshot_tree(root: Path) -> dict[str, FileState]:
    snapshot: dict[str, FileState] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise RepairChainError("source_snapshot_failed") from error
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise RepairChainError("source_snapshot_failed") from error
            if stat.S_ISDIR(metadata.st_mode):
                snapshot[f"{relative}/"] = FileState(stat.S_IMODE(metadata.st_mode), 0, "")
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                snapshot[relative] = FileState(
                    stat.S_IMODE(metadata.st_mode),
                    metadata.st_size,
                    _sha256(path, "source_snapshot_failed"),
                )
            else:
                raise RepairChainError("source_snapshot_failed")
    return snapshot


def _assert_snapshot(root: Path, expected: Mapping[str, FileState], code: str) -> None:
    try:
        observed = _snapshot_tree(root)
    except RepairChainError as error:
        raise RepairChainError(code) from error
    if observed != expected:
        raise RepairChainError(code)


def _bind_export_tree(root: Path, expected_manifest_sha256: str, code: str) -> str:
    if not _valid_sha256(expected_manifest_sha256):
        raise RepairChainError(code)
    manifest = _regular_file(root / "manifest.json", code)
    if _sha256(manifest, code) != expected_manifest_sha256:
        raise RepairChainError(code)
    try:
        tree_sha256 = merger._export_tree_sha256(root, code)
    except merger.MergeError as error:
        raise RepairChainError(code) from error
    if _sha256(manifest, code) != expected_manifest_sha256:
        raise RepairChainError(code)
    return tree_sha256


def _assert_export_tree(root: Path, expected_sha256: str, code: str) -> None:
    try:
        observed = merger._export_tree_sha256(root, code)
    except merger.MergeError as error:
        raise RepairChainError(code) from error
    if observed != expected_sha256:
        raise RepairChainError(code)


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    except OSError as error:
        raise RepairChainError("runtime_directory_create_failed") from error


def _open_private_log(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "wb")
    except OSError as error:
        raise RepairChainError("child_log_create_failed") from error


def _run_child(command: ChildCommand, log_dir: Path) -> dict[str, Any] | None:
    if STAGE_PATTERN.fullmatch(command.stage) is None or not command.argv:
        raise RepairChainError("child_command_invalid")
    stdout_path = log_dir / f"{command.stage}.stdout.log"
    stderr_path = log_dir / f"{command.stage}.stderr.log"
    with _open_private_log(stdout_path) as stdout, _open_private_log(stderr_path) as stderr:
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=command.environment.get("PROJECT_DIR"),
                env=dict(command.environment),
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
        except OSError as error:
            raise RepairChainError(f"{command.stage}_failed") from error
    _regular_file(stdout_path, "child_log_invalid", mode=0o600)
    _regular_file(stderr_path, "child_log_invalid", mode=0o600)
    if completed.returncode != 0:
        raise RepairChainError(f"{command.stage}_failed")
    if not command.expects_summary:
        return None
    body = _read_bytes(stdout_path, f"{command.stage}_summary_invalid", limit=MAX_CHILD_SUMMARY_BYTES)
    return _parse_json_object(body, f"{command.stage}_summary_invalid")


def _base_environment(project: Path, environment: Mapping[str, str]) -> dict[str, str]:
    result = dict(environment)
    result["PROJECT_DIR"] = str(project)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def _direct_environment(
    project: Path,
    repair_dir: Path,
    selection_dir: Path,
    task_sha256: str,
    environment: Mapping[str, str],
) -> dict[str, str]:
    result = _base_environment(project, environment)
    for key in DIRECT_FORBIDDEN_ENV:
        result.pop(key, None)
    job_id = result.get("SLURM_JOB_ID", "")
    if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
        raise RepairChainError("slurm_allocation_required")
    result.update(
        {
            "OUTPUT_DIR": str(repair_dir),
            "EVAL_CONFIG": str(selection_dir / "repair_config.toml"),
            "DIRECT_QWEN_APPROVED_TASK_FILE": str(selection_dir / "repair_tasks.txt"),
            "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256": task_sha256,
            "OPENAI_API_KEY": "EMPTY",
            "VACLI_MAX_CONCURRENT_LEASES": "2",
        }
    )
    return result


def _require_summary(value: dict[str, Any] | None, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepairChainError(code)
    return value


def _validate_materializer_summary(
    summary: dict[str, Any],
    options: RepairChainOptions,
    attestation: ProjectAttestation,
    selection_dir: Path,
) -> tuple[int, int, int, str | None, str | None]:
    count = summary.get("approved_repair_count")
    missing = summary.get("missing_or_errored_count")
    strict_invalid = summary.get("strict_invalid_pass_count")
    if (
        summary.get("ok") is not True
        or not _is_plain_int(count)
        or not 0 <= count <= EXPECTED_ORIGINAL_COUNT
        or not _is_plain_int(missing)
        or not _is_plain_int(strict_invalid)
        or min(missing, strict_invalid) < 0
        or missing + strict_invalid != count
        or not _valid_sha256(summary.get("repair_union_indices_sha256"))
        or not _valid_sha256(summary.get("task_index_order_sha256"))
    ):
        raise RepairChainError("materialize_summary_invalid")
    if count == 0:
        if (
            summary.get("status") != "nothing_to_repair"
            or summary.get("approved_task_file_sha256") != options.approved_task_file_sha256
            or os.path.lexists(selection_dir)
        ):
            raise RepairChainError("materialize_summary_invalid")
        return 0, 0, 0, None, None
    if (
        summary.get("status") != "materialized"
        or not _valid_sha256(summary.get("task_file_sha256"))
        or not _valid_sha256(summary.get("manifest_sha256"))
        or not _valid_sha256(summary.get("config_sha256"))
    ):
        raise RepairChainError("materialize_summary_invalid")
    selection = _canonical_directory(selection_dir, "repair_selection_invalid")
    task_file = _regular_file(selection / "repair_tasks.txt", "repair_selection_invalid", mode=0o600)
    config_file = _regular_file(selection / "repair_config.toml", "repair_selection_invalid", mode=0o600)
    manifest_file = _regular_file(selection / "repair_manifest.json", "repair_selection_invalid", mode=0o600)
    missing_file = _regular_file(
        selection / "repair_missing_or_errored_tasks.txt",
        "repair_selection_invalid",
        mode=0o600,
    )
    strict_file = _regular_file(
        selection / "repair_strict_invalid_pass_tasks.txt",
        "repair_selection_invalid",
        mode=0o600,
    )
    if {entry.name for entry in selection.iterdir()} != {
        "repair_tasks.txt",
        "repair_missing_or_errored_tasks.txt",
        "repair_strict_invalid_pass_tasks.txt",
        "repair_config.toml",
        "repair_manifest.json",
    }:
        raise RepairChainError("repair_selection_invalid")
    task_sha256 = _sha256(task_file, "repair_selection_invalid")
    manifest_sha256 = _sha256(manifest_file, "repair_selection_invalid")
    if (
        task_sha256 != summary["task_file_sha256"]
        or manifest_sha256 != summary["manifest_sha256"]
        or _sha256(config_file, "repair_selection_invalid") != summary["config_sha256"]
        or _task_record_count(task_file) != count
        or (_task_record_count(missing_file) if missing else missing_file.stat().st_size) != missing
        or (_task_record_count(strict_file) if strict_invalid else strict_file.stat().st_size) != strict_invalid
    ):
        raise RepairChainError("repair_selection_invalid")
    try:
        repair_selection = repair_finalizer._load_repair_selection(
            manifest_file,
            manifest_sha256,
            count,
        )
    except repair_finalizer.RepairFinalizationError as error:
        raise RepairChainError("repair_selection_invalid") from error
    if (
        repair_selection.approved_task_count != EXPECTED_ORIGINAL_COUNT
        or repair_selection.repository_revision != attestation.revision
        or dict(repair_selection.submodules) != dict(attestation.submodules)
        or repair_selection.materializer_sha256 != attestation.materializer_sha256
        or repair_selection.exporter_sha256 != attestation.exporter_sha256
        or repair_selection.template_sha256 != attestation.repair_template_sha256
        or repair_selection.task_file_sha256 != task_sha256
        or repair_selection.repair_union_indices_sha256 != summary["repair_union_indices_sha256"]
        or repair_selection.missing_or_errored_count != missing
        or repair_selection.strict_invalid_pass_count != strict_invalid
    ):
        raise RepairChainError("repair_selection_attestation_mismatch")
    config = _load_source_config(config_file)
    client = config.get("client")
    sampling = config.get("sampling")
    chat = sampling.get("chat_template_kwargs") if isinstance(sampling, dict) else None
    taskset = config.get("taskset")
    if (
        config.get("num_tasks") != count
        or config.get("max_concurrent") != direct.MAX_DIRECT_CONCURRENCY
        or config.get("multiplex") != direct.MAX_DIRECT_CONCURRENCY
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(client, dict)
        or client.get("max_connections") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or client.get("max_keepalive_connections") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or client.get("capture_model_io") is not True
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != 32_768
        or not isinstance(chat, dict)
        or chat.get("enable_thinking") is not True
        or chat.get("preserve_thinking") is not True
        or not isinstance(taskset, dict)
        or taskset.get("task_file") != str(task_file)
        or taskset.get("task_file_sha256") != task_sha256
    ):
        raise RepairChainError("repair_generation_contract_invalid")
    return count, missing, strict_invalid, task_sha256, manifest_sha256


def _validate_finalizer_summary(
    summary: dict[str, Any],
    expected_count: int,
    code: str,
    *,
    expected_exclusion: tuple[int, int, str] | None = None,
) -> dict[str, Any]:
    rows = summary.get("rows")
    if (
        summary.get("status") != "finalized"
        or summary.get("selection") != "pass-only"
        or summary.get("approved_tasks") != expected_count
        or not _is_plain_int(summary.get("input_traces"))
        or not 0 <= summary["input_traces"] <= expected_count
        or (expected_exclusion is None and summary["input_traces"] != expected_count)
        or not _is_plain_int(summary.get("selected_traces"))
        or not 0 <= summary["selected_traces"] <= expected_count
        or not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or not all(_is_plain_int(value) and value >= 0 for value in rows.values())
        or rows["total"] != rows["train"] + rows["validation"]
    ):
        raise RepairChainError(code)
    public = {
        "approved_tasks": summary["approved_tasks"],
        "input_traces": summary["input_traces"],
        "rows": dict(rows),
        "selected_traces": summary["selected_traces"],
    }
    if expected_exclusion is not None:
        expected_missing, expected_strict, expected_sha256 = expected_exclusion
        exclusion = summary.get("exclusion")
        if (
            not isinstance(exclusion, dict)
            or set(exclusion)
            != {
                "excluded_present_traces",
                "missing_tasks",
                "missing_or_errored_count",
                "selection_manifest_sha256",
                "strict_invalid_pass_count",
                "union_count",
            }
            or exclusion.get("missing_or_errored_count") != expected_missing
            or exclusion.get("strict_invalid_pass_count") != expected_strict
            or exclusion.get("union_count") != expected_missing + expected_strict
            or exclusion.get("selection_manifest_sha256") != expected_sha256
            or not _is_plain_int(exclusion.get("missing_tasks"))
            or not _is_plain_int(exclusion.get("excluded_present_traces"))
            or exclusion["missing_tasks"] + exclusion["excluded_present_traces"] != exclusion["union_count"]
            or summary["input_traces"] + exclusion["missing_tasks"] != expected_count
        ):
            raise RepairChainError(code)
        public["exclusion"] = dict(exclusion)
    elif "exclusion" in summary:
        raise RepairChainError(code)
    return public


def _validate_merge_summary(summary: dict[str, Any]) -> dict[str, Any]:
    rows = summary.get("rows")
    tasks = summary.get("tasks")
    output_sha256 = summary.get("output_sha256")
    if (
        summary.get("ok") is not True
        or not _valid_sha256(summary.get("manifest_sha256"))
        or not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or not isinstance(tasks, dict)
        or set(tasks) != {"total", "train", "validation"}
        or not all(_is_plain_int(value) and value >= 0 for value in (*rows.values(), *tasks.values()))
        or rows["total"] != rows["train"] + rows["validation"]
        or tasks["total"] != tasks["train"] + tasks["validation"]
        or not isinstance(output_sha256, dict)
        or set(output_sha256) != {"target_rendering_contract", "task_split", "train", "validation"}
        or not all(_valid_sha256(value) for value in output_sha256.values())
    ):
        raise RepairChainError("merge_summary_invalid")
    return {
        "manifest_sha256": summary["manifest_sha256"],
        "output_sha256": dict(output_sha256),
        "rows": dict(rows),
        "tasks": dict(tasks),
    }


def _validate_original_output_hashes(summary: Mapping[str, Any], output: Path) -> dict[str, str]:
    declared = summary.get("output_sha256")
    artifact_paths = {
        "manifest": output / "manifest.json",
        "routing_epoch_index": output / common.INDEX_FILENAME,
        "target_rendering_contract": output / exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train": output / "train" / "train.jsonl",
        "validation": output / "validation" / "train.jsonl",
    }
    if (
        not isinstance(declared, dict)
        or set(declared) != set(artifact_paths)
        or not all(_valid_sha256(value) for value in declared.values())
    ):
        raise RepairChainError("original_export_invalid")
    for name, path in artifact_paths.items():
        artifact = _regular_file(path, "original_export_invalid")
        if _sha256(artifact, "original_export_invalid") != declared[name]:
            raise RepairChainError("original_export_invalid")
    return dict(declared)


def _validate_merged_output_hashes(summary: Mapping[str, Any], output: Path) -> None:
    declared = summary.get("output_sha256")
    artifact_paths = {
        "task_split": output / "task-split.json",
        "target_rendering_contract": output / exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train": output / "train" / "train.jsonl",
        "validation": output / "validation" / "train.jsonl",
    }
    if not isinstance(declared, dict) or set(declared) != set(artifact_paths):
        raise RepairChainError("merged_output_invalid")
    for name, path in artifact_paths.items():
        artifact = _regular_file(path, "merged_output_invalid")
        if _sha256(artifact, "merged_output_invalid") != declared[name]:
            raise RepairChainError("merged_output_invalid")


def _write_private_summary(path: Path, value: Mapping[str, Any]) -> None:
    body = json.dumps(value, allow_nan=False, indent=2, sort_keys=True).encode() + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise RepairChainError("summary_publish_failed") from error


def _run_stage(
    runner: ChildRunner,
    command: ChildCommand,
    log_dir: Path,
    paths: ResolvedPaths,
    options: RepairChainOptions,
    attestation: ProjectAttestation,
    project_validator: ProjectValidator,
    original_snapshot: Mapping[str, FileState],
    repair_snapshot: Mapping[str, FileState] | None = None,
    repair_dir: Path | None = None,
    selection_snapshot: Mapping[str, FileState] | None = None,
    selection_dir: Path | None = None,
) -> dict[str, Any] | None:
    _validate_attestation(project_validator, paths, options, attestation)
    try:
        summary = runner(command, log_dir)
    finally:
        _assert_snapshot(paths.source_dir, original_snapshot, "original_source_changed")
        if repair_snapshot is not None and repair_dir is not None:
            _assert_snapshot(repair_dir, repair_snapshot, "repair_source_changed")
        if selection_snapshot is not None and selection_dir is not None:
            _assert_snapshot(selection_dir, selection_snapshot, "repair_selection_changed")
        _validate_attestation(project_validator, paths, options, attestation)
    return summary


def run_repair_chain(
    options: RepairChainOptions,
    *,
    runner: ChildRunner = _run_child,
    project_validator: ProjectValidator = _default_project_validator,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute one fresh chain without overwriting any source or destination."""
    _validate_options(options)
    paths = _resolve_paths(options)
    attestation = _validate_attestation(project_validator, paths, options)
    _validate_original_contract(paths, options)
    original_snapshot = _snapshot_tree(paths.source_dir)
    child_environment = _base_environment(paths.project_dir, environment or os.environ)

    _private_directory(paths.runtime_dir)
    log_dir = paths.runtime_dir / "logs"
    _private_directory(log_dir)
    selection_dir = paths.runtime_dir / "selection"
    repair_dir = paths.runtime_dir / "repair-run"
    repair_source: Path | None = None
    repair_snapshot: Mapping[str, FileState] | None = None
    selection_snapshot: Mapping[str, FileState] | None = None
    original_export_tree_sha256: str | None = None
    repair_export_tree_sha256: str | None = None
    repair_count = 0
    missing_or_errored_count = 0
    strict_invalid_pass_count = 0
    materialize_command = ChildCommand(
        stage="materialize",
        argv=(
            sys.executable,
            str(paths.workflow_dir / "materialize_qwen_repair.py"),
            "--source-dir",
            str(paths.source_dir),
            "--approved-task-file",
            str(paths.approved_task_file),
            "--approved-task-file-sha256",
            options.approved_task_file_sha256,
            "--output-dir",
            str(selection_dir),
        ),
        environment=child_environment,
    )

    try:
        materialize_summary = _require_summary(
            _run_stage(
                runner,
                materialize_command,
                log_dir,
                paths,
                options,
                attestation,
                project_validator,
                original_snapshot,
            ),
            "materialize_summary_invalid",
        )
        (
            repair_count,
            missing_or_errored_count,
            strict_invalid_pass_count,
            repair_task_sha256,
            selection_manifest_sha256,
        ) = _validate_materializer_summary(materialize_summary, options, attestation, selection_dir)
        selection_snapshot = _snapshot_tree(selection_dir) if repair_count else None

        if repair_count:
            assert repair_task_sha256 is not None
            assert selection_manifest_sha256 is not None
            direct_command = ChildCommand(
                stage="repair_eval",
                argv=("/bin/bash", str(paths.workflow_dir / "run_qwen_direct_eval.sbatch")),
                environment=_direct_environment(
                    paths.project_dir,
                    repair_dir,
                    selection_dir,
                    repair_task_sha256,
                    environment or os.environ,
                ),
                expects_summary=False,
            )
            _run_stage(
                runner,
                direct_command,
                log_dir,
                paths,
                options,
                attestation,
                project_validator,
                original_snapshot,
                selection_snapshot=selection_snapshot,
                selection_dir=selection_dir,
            )
            repair_source = _canonical_directory(repair_dir, "repair_source_invalid")
            repair_provenance = _regular_file(
                repair_source / "provenance.txt",
                "repair_provenance_invalid",
            )
            repair_provenance_sha256 = _sha256(
                repair_provenance,
                "repair_provenance_invalid",
            )
            repair_snapshot = _snapshot_tree(repair_source)
        else:
            repair_source = None
            repair_provenance_sha256 = None
            repair_snapshot = None

        original_argv = [
            sys.executable,
            str(paths.workflow_dir / "finalize_qwen_sft.py"),
            "--project-dir",
            str(paths.project_dir),
            "--expected-project-revision",
            options.expected_project_revision,
            "--source-root",
            str(paths.source_root),
            "--source-dir",
            str(paths.source_dir),
            "--expected-provenance-sha256",
            options.expected_provenance_sha256,
            "--output-root",
            str(paths.output_root),
            "--output-dir",
            str(paths.original_export_dir),
            "--expected-count",
            str(EXPECTED_ORIGINAL_COUNT),
            "--selection",
            "pass-only",
            "--validation-permyriad",
            str(options.validation_permyriad),
            "--split-salt",
            options.split_salt,
        ]
        if repair_count:
            assert selection_manifest_sha256 is not None
            original_argv.extend(
                [
                    "--exclusion-selection-manifest",
                    str(selection_dir / "repair_manifest.json"),
                    "--expected-exclusion-selection-manifest-sha256",
                    selection_manifest_sha256,
                ]
            )
        original_command = ChildCommand(
            stage="finalize_original",
            argv=tuple(original_argv),
            environment=child_environment,
        )
        original_summary = _require_summary(
            _run_stage(
                runner,
                original_command,
                log_dir,
                paths,
                options,
                attestation,
                project_validator,
                original_snapshot,
                repair_snapshot,
                repair_source,
                selection_snapshot,
                selection_dir if repair_count else None,
            ),
            "original_finalizer_summary_invalid",
        )
        original_public = _validate_finalizer_summary(
            original_summary,
            EXPECTED_ORIGINAL_COUNT,
            "original_finalizer_summary_invalid",
            expected_exclusion=(
                missing_or_errored_count,
                strict_invalid_pass_count,
                str(selection_manifest_sha256),
            )
            if repair_count
            else None,
        )
        original_output_sha256 = _validate_original_output_hashes(
            original_summary,
            paths.original_export_dir,
        )
        original_export_tree_sha256 = _bind_export_tree(
            paths.original_export_dir,
            original_output_sha256["manifest"],
            "original_export_invalid",
        )
        original_public["output_sha256"] = original_output_sha256

        if repair_count == 0:
            if os.path.lexists(paths.repair_export_dir) or os.path.lexists(paths.merged_output_dir):
                raise RepairChainError("zero_repair_destination_changed")
            result: dict[str, Any] = {
                "ok": True,
                "original": original_public,
                "project_revision": options.expected_project_revision,
                "repair_count": 0,
                "missing_or_errored_count": 0,
                "strict_invalid_pass_count": 0,
                "source_approval_sha256": options.approved_task_file_sha256,
                "source_provenance_sha256": options.expected_provenance_sha256,
                "status": "finalized_without_repair",
            }
            _write_private_summary(paths.runtime_dir / "chain_summary.json", result)
            return result

        assert repair_source is not None
        assert repair_provenance_sha256 is not None
        assert repair_snapshot is not None
        assert selection_manifest_sha256 is not None
        selection_manifest = selection_dir / "repair_manifest.json"
        repair_command = ChildCommand(
            stage="finalize_repair",
            argv=(
                sys.executable,
                str(paths.workflow_dir / "finalize_qwen_repair_sft.py"),
                "--project-dir",
                str(paths.project_dir),
                "--expected-project-revision",
                options.expected_project_revision,
                "--source-root",
                str(paths.runtime_dir),
                "--source-dir",
                str(repair_source),
                "--expected-provenance-sha256",
                repair_provenance_sha256,
                "--repair-selection-manifest",
                str(selection_manifest),
                "--expected-repair-selection-manifest-sha256",
                selection_manifest_sha256,
                "--output-root",
                str(paths.output_root),
                "--output-dir",
                str(paths.repair_export_dir),
                "--expected-count",
                str(repair_count),
                "--validation-permyriad",
                str(options.validation_permyriad),
                "--split-salt",
                options.split_salt,
            ),
            environment=child_environment,
        )
        repair_summary = _require_summary(
            _run_stage(
                runner,
                repair_command,
                log_dir,
                paths,
                options,
                attestation,
                project_validator,
                original_snapshot,
                repair_snapshot,
                repair_source,
                selection_snapshot,
                selection_dir,
            ),
            "repair_finalizer_summary_invalid",
        )
        assert original_export_tree_sha256 is not None
        _assert_export_tree(
            paths.original_export_dir,
            original_export_tree_sha256,
            "original_export_changed",
        )
        repair_public = _validate_finalizer_summary(
            repair_summary,
            repair_count,
            "repair_finalizer_summary_invalid",
        )
        attestation_path = _regular_file(
            paths.repair_export_dir / repair_finalizer.ATTESTATION_FILENAME,
            "repair_attestation_invalid",
            mode=0o600,
        )
        attestation_sha256 = _sha256(attestation_path, "repair_attestation_invalid")
        if repair_summary.get("attestation_sha256") != attestation_sha256:
            raise RepairChainError("repair_attestation_invalid")
        repair_manifest = _regular_file(
            paths.repair_export_dir / "manifest.json",
            "repair_export_invalid",
        )
        repair_manifest_sha256 = _sha256(repair_manifest, "repair_export_invalid")
        if repair_summary.get("manifest_sha256") != repair_manifest_sha256:
            raise RepairChainError("repair_export_invalid")
        repair_export_tree_sha256 = _bind_export_tree(
            paths.repair_export_dir,
            repair_manifest_sha256,
            "repair_export_invalid",
        )
        repair_public["attestation_sha256"] = attestation_sha256
        repair_public["manifest_sha256"] = repair_manifest_sha256
        for copy_name, source_name in repair_finalizer.SELECTION_SOURCE_FILENAMES.items():
            selection_copy = _regular_file(
                paths.repair_export_dir / copy_name,
                "repair_selection_copy_invalid",
                mode=0o600,
            )
            selection_source = _regular_file(
                selection_dir / source_name,
                "repair_selection_invalid",
                mode=0o600,
            )
            if _sha256(selection_copy, "repair_selection_copy_invalid") != _sha256(
                selection_source,
                "repair_selection_invalid",
            ):
                raise RepairChainError("repair_selection_copy_invalid")

        assert repair_export_tree_sha256 is not None
        merge_command = ChildCommand(
            stage="merge",
            argv=(
                sys.executable,
                str(paths.workflow_dir / "merge_qwen_sft.py"),
                "--original-export-dir",
                str(paths.original_export_dir),
                "--original-export-manifest-sha256",
                original_output_sha256["manifest"],
                "--original-export-tree-sha256",
                original_export_tree_sha256,
                "--repair-export-dir",
                str(paths.repair_export_dir),
                "--repair-export-manifest-sha256",
                repair_manifest_sha256,
                "--repair-export-tree-sha256",
                repair_export_tree_sha256,
                "--repair-selection-manifest",
                str(selection_manifest),
                "--repair-selection-manifest-sha256",
                selection_manifest_sha256,
                "--repair-attestation-manifest",
                str(attestation_path),
                "--repair-attestation-manifest-sha256",
                attestation_sha256,
                "--output-dir",
                str(paths.merged_output_dir),
                "--project-dir",
                str(paths.project_dir),
                "--expected-project-revision",
                options.expected_project_revision,
            ),
            environment=child_environment,
        )
        merge_summary = _require_summary(
            _run_stage(
                runner,
                merge_command,
                log_dir,
                paths,
                options,
                attestation,
                project_validator,
                original_snapshot,
                repair_snapshot,
                repair_source,
                selection_snapshot,
                selection_dir,
            ),
            "merge_summary_invalid",
        )
        _assert_export_tree(
            paths.original_export_dir,
            original_export_tree_sha256,
            "original_export_changed",
        )
        _assert_export_tree(
            paths.repair_export_dir,
            repair_export_tree_sha256,
            "repair_export_changed",
        )
        merged_public = _validate_merge_summary(merge_summary)
        if merged_public["tasks"]["total"] != original_public["selected_traces"] + repair_public[
            "selected_traces"
        ] or any(
            merged_public["rows"][split] != original_public["rows"][split] + repair_public["rows"][split]
            for split in ("total", "train", "validation")
        ):
            raise RepairChainError("merge_count_mismatch")
        merged_manifest = _regular_file(paths.merged_output_dir / "manifest.json", "merged_output_invalid")
        if _sha256(merged_manifest, "merged_output_invalid") != merged_public["manifest_sha256"]:
            raise RepairChainError("merged_output_invalid")
        _validate_merged_output_hashes(merge_summary, paths.merged_output_dir)
        result = {
            "merged": merged_public,
            "ok": True,
            "original": original_public,
            "project_revision": options.expected_project_revision,
            "repair": repair_public,
            "repair_count": repair_count,
            "missing_or_errored_count": missing_or_errored_count,
            "strict_invalid_pass_count": strict_invalid_pass_count,
            "repair_selection_manifest_sha256": selection_manifest_sha256,
            "source_approval_sha256": options.approved_task_file_sha256,
            "source_provenance_sha256": options.expected_provenance_sha256,
            "status": "merged",
        }
        _write_private_summary(paths.runtime_dir / "chain_summary.json", result)
        return result
    finally:
        _assert_snapshot(paths.source_dir, original_snapshot, "original_source_changed")
        if repair_source is not None and repair_snapshot is not None:
            _assert_snapshot(repair_source, repair_snapshot, "repair_source_changed")
        if repair_count and selection_snapshot is not None:
            _assert_snapshot(selection_dir, selection_snapshot, "repair_selection_changed")
        if original_export_tree_sha256 is not None:
            _assert_export_tree(
                paths.original_export_dir,
                original_export_tree_sha256,
                "original_export_changed",
            )
        if repair_export_tree_sha256 is not None:
            _assert_export_tree(
                paths.repair_export_dir,
                repair_export_tree_sha256,
                "repair_export_changed",
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--approved-task-file-sha256", required=True)
    parser.add_argument("--expected-provenance-sha256", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--original-export-dir", type=Path, required=True)
    parser.add_argument("--repair-export-dir", type=Path, required=True)
    parser.add_argument("--merged-output-dir", type=Path, required=True)
    parser.add_argument("--validation-permyriad", type=int, required=True)
    parser.add_argument("--split-salt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = run_repair_chain(
            RepairChainOptions(
                project_dir=args.project_dir,
                expected_project_revision=args.expected_project_revision,
                source_root=args.source_root,
                source_dir=args.source_dir,
                approved_task_file_sha256=args.approved_task_file_sha256,
                expected_provenance_sha256=args.expected_provenance_sha256,
                runtime_root=args.runtime_root,
                runtime_dir=args.runtime_dir,
                output_root=args.output_root,
                original_export_dir=args.original_export_dir,
                repair_export_dir=args.repair_export_dir,
                merged_output_dir=args.merged_output_dir,
                validation_permyriad=args.validation_permyriad,
                split_salt=args.split_salt,
            )
        )
    except RepairChainError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
