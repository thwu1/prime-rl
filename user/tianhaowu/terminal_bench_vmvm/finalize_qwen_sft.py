#!/usr/bin/env python3
"""Finalize one terminal Qwen routing-epoch-3 run as a text SFT dataset.

The finalizer emits only aggregate counts, hashes, and stable error codes. Child
process output is never forwarded, so task identifiers, trace bodies, prompts,
tool payloads, and provider responses cannot enter the scheduler log.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import direct_qwen_workers as direct
import export_sft as exporter
import migrate_qwen_router_affinity as migration
import migrate_qwen_serving_generation as serving_generation
import sft_run_identity
from audit_traces import (
    QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID,
    QWEN3_A95B_MODEL_IO_CONTRACT_ID,
)

INDEX_FILENAME = "qwen_router_epochs.jsonl"
MAX_CHILD_OUTPUT_BYTES = 1 << 20
MAX_PROVENANCE_BYTES = 1 << 20
MAX_SEQUENCE_TOKENS = 262_144
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REQUIRED_RUNTIME_SUBMODULES = (
    "deps/pydantic-config",
    "deps/renderers",
    "deps/verifiers",
)
SOURCE_EXPORT_ARTIFACTS = (
    "config.toml",
    "provenance.txt",
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/task_file.txt",
    "inputs/image_manifest.json",
    "results.jsonl",
    "direct_workers.json",
    "qwen_router_epochs.jsonl",
    "qwen_router_transition.json",
    "qwen_router_admission_transition.json",
    "qwen_router_epoch1_rows.sha256",
    "qwen_router_epoch2_lineage.jsonl",
)
SANDOQ_SOURCE_EXPORT_ARTIFACTS = (
    "config.toml",
    "provenance.txt",
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/task_file.txt",
    "inputs/image_manifest.json",
    "results.jsonl",
    "direct_workers.json",
    sft_run_identity.EVAL_RUN_IDENTITY_FILENAME,
)
FORMAT_CONTRACT = {
    "assistant_finish_reason": "retained verbatim for every sampled assistant message",
    "assistant_tool_calls": "OpenAI function-call objects",
    "history_assistant_reasoning": "retained verbatim",
    "loss_mask": "message.trainable; exactly one final assistant message is true",
    "sample_unit": "one unique sampled assistant node with its root-to-node context",
    "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
    "task_identity": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
}

Selection = Literal["pass-only", "all-outcomes"]


class FinalizationError(RuntimeError):
    """A fail-closed finalization error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise FinalizationError("arguments_invalid")


@dataclass(frozen=True)
class FinalizeOptions:
    project_dir: Path
    expected_project_revision: str
    source_root: Path
    source_dir: Path
    expected_provenance_sha256: str
    output_root: Path
    output_dir: Path
    expected_count: int
    selection: Selection
    validation_permyriad: int
    split_salt: str
    exclusion_selection_manifest: Path | None = None
    expected_exclusion_selection_manifest_sha256: str | None = None


@dataclass(frozen=True)
class ResolvedPaths:
    project_dir: Path
    source_root: Path
    source_dir: Path
    results: Path
    provenance: Path
    output_root: Path
    output_dir: Path


RepositoryValidator = Callable[[Path, str], Path]
SourceAuditor = Callable[[Path, int, str], dict[str, Any]]
CommandRunner = Callable[[list[str], Path, str], dict[str, Any]]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_normalized_absolute(path: Path) -> bool:
    return path.is_absolute() and path == Path(os.path.normpath(path))


def _canonical_existing_directory(path: Path, code: str) -> Path:
    if not _is_normalized_absolute(path):
        raise FinalizationError(code)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise FinalizationError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise FinalizationError(code)
    return resolved


def _unsafe_boundary(path: Path) -> bool:
    if path == Path(path.anchor) or len(path.parts) < 5:
        return True
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        return True
    return path == home or home.is_relative_to(path)


def _strict_descendant(path: Path, root: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _regular_file(path: Path, code: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise FinalizationError(code) from error
    if not stat.S_ISREG(metadata.st_mode) or path.resolve(strict=True) != path:
        raise FinalizationError(code)
    return path


def _resolve_paths(options: FinalizeOptions) -> ResolvedPaths:
    project = _canonical_existing_directory(options.project_dir, "project_path_unsafe")
    source_root = _canonical_existing_directory(options.source_root, "source_root_unsafe")
    output_root = _canonical_existing_directory(options.output_root, "output_root_unsafe")
    if _unsafe_boundary(source_root) or _unsafe_boundary(output_root):
        raise FinalizationError("path_boundary_unsafe")
    if _paths_overlap(source_root, output_root):
        raise FinalizationError("path_boundaries_overlap")

    source = _canonical_existing_directory(options.source_dir, "source_path_unsafe")
    if not _strict_descendant(source, source_root):
        raise FinalizationError("source_outside_boundary")

    output = options.output_dir
    if not _is_normalized_absolute(output) or not output.name or os.path.lexists(output):
        raise FinalizationError("output_path_unsafe")
    output_parent = _canonical_existing_directory(output.parent, "output_parent_unsafe")
    if output != output_parent / output.name or not _strict_descendant(output, output_root):
        raise FinalizationError("output_outside_boundary")
    if _paths_overlap(project, source) or _paths_overlap(project, output):
        raise FinalizationError("runtime_path_overlaps_project")
    if _paths_overlap(source, output):
        raise FinalizationError("output_overlaps_source")

    results = _regular_file(source / "results.jsonl", "source_results_invalid")
    provenance = _regular_file(source / "provenance.txt", "source_provenance_invalid")
    _regular_file(source / "config.toml", "source_config_invalid")
    return ResolvedPaths(
        project_dir=project,
        source_root=source_root,
        source_dir=source,
        results=results,
        provenance=provenance,
        output_root=output_root,
        output_dir=output,
    )


def _run_git(project_dir: Path, arguments: list[str], code: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FinalizationError(code) from error
    if len(completed.stdout.encode()) > MAX_CHILD_OUTPUT_BYTES or completed.stderr:
        raise FinalizationError(code)
    return completed.stdout


def _validate_repository(
    project_dir: Path,
    expected_revision: str,
    *,
    required_submodules: tuple[str, ...] = REQUIRED_RUNTIME_SUBMODULES,
) -> Path:
    if GIT_SHA_PATTERN.fullmatch(expected_revision) is None:
        raise FinalizationError("project_revision_invalid")
    project = _canonical_existing_directory(project_dir, "project_path_unsafe")
    top_level = _run_git(project, ["rev-parse", "--show-toplevel"], "project_revision_unavailable").strip()
    head = _run_git(project, ["rev-parse", "HEAD"], "project_revision_unavailable").strip()
    head_name = _run_git(
        project,
        ["rev-parse", "--abbrev-ref", "HEAD"],
        "project_revision_unavailable",
    ).strip()
    if top_level != str(project) or head != expected_revision:
        raise FinalizationError("project_revision_mismatch")
    if head_name != "HEAD":
        raise FinalizationError("project_not_detached")
    status = _run_git(
        project,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "project_status_unavailable",
    )
    if status:
        raise FinalizationError("project_not_clean")
    for relative in required_submodules:
        tree_record = _run_git(
            project,
            ["ls-tree", expected_revision, "--", relative],
            "project_submodules_unavailable",
        ).strip()
        fields = tree_record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or GIT_SHA_PATTERN.fullmatch(fields[2]) is None
            or fields[3] != relative
        ):
            raise FinalizationError("project_submodule_mismatch")
        submodule = project / relative
        observed = _run_git(submodule, ["rev-parse", "HEAD"], "project_submodules_unavailable").strip()
        submodule_status = _run_git(
            submodule,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            "project_submodules_unavailable",
        )
        if observed != fields[2] or submodule_status:
            raise FinalizationError("project_submodule_mismatch")
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    _regular_file(workflow / "finalize_qwen_sft.py", "project_finalizer_invalid")
    _regular_file(workflow / "migrate_qwen_router_affinity.py", "project_labeler_invalid")
    _regular_file(workflow / "export_sft.py", "project_exporter_invalid")
    return project


def _stable_sha256(path: Path, *, max_bytes: int | None = None) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise FinalizationError("source_artifact_unreadable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise FinalizationError("source_artifact_invalid")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, 1 << 20):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise FinalizationError("source_artifact_too_large")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after):
        raise FinalizationError("source_artifact_changed")
    return digest.hexdigest()


def _file_artifact(path: Path, code: str) -> dict[str, int | str]:
    file_path = _regular_file(path, code)
    try:
        before = file_path.stat()
        digest = _stable_sha256(file_path)
        after = file_path.stat()
    except OSError as error:
        raise FinalizationError(code) from error
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after):
        raise FinalizationError(code)
    return {"bytes": before.st_size, "sha256": digest}


def _artifact_record(value: object, code: str) -> dict[str, int | str]:
    if not isinstance(value, dict) or set(value) != {"bytes", "sha256"}:
        raise FinalizationError(code)
    size = value.get("bytes")
    digest = value.get("sha256")
    if not _is_plain_int(size) or size < 0 or not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise FinalizationError(code)
    return {"bytes": size, "sha256": digest}


def _expected_source_artifacts(
    source: Path,
    routing_index: Path | None,
    *,
    sandbox_provider: str = "vmvm",
) -> dict[str, dict[str, int | str]]:
    if sandbox_provider not in {"vmvm", "sandoq"}:
        raise FinalizationError("sandbox_provider_invalid")
    relatives = list(SOURCE_EXPORT_ARTIFACTS if sandbox_provider == "vmvm" else SANDOQ_SOURCE_EXPORT_ARTIFACTS)
    if sandbox_provider == "vmvm" and os.path.lexists(source / sft_run_identity.EVAL_RUN_IDENTITY_FILENAME):
        relatives.append(sft_run_identity.EVAL_RUN_IDENTITY_FILENAME)
    paths = {relative: routing_index if relative == INDEX_FILENAME else source / relative for relative in relatives}
    if any(path is None for path in paths.values()):
        raise FinalizationError("routing_index_missing")
    return {relative: _file_artifact(path, "source_artifact_unreadable") for relative, path in paths.items()}


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_published_directory(path: Path, _incomplete: bool) -> None:
    _canonical_existing_directory(path, "sft_output_invalid")


def _publish_output(
    staged: Path,
    destination: Path,
    validate: Callable[[Path, bool], None] | None = None,
) -> None:
    if os.path.lexists(destination):
        raise FinalizationError("output_already_exists")
    try:
        staged_metadata = staged.lstat()
    except OSError as error:
        raise FinalizationError("output_publish_failed") from error
    if not stat.S_ISDIR(staged_metadata.st_mode):
        raise FinalizationError("output_publish_failed")
    if validate is None:
        validate = _validate_published_directory
    try:
        migration._publish_directory(staged, destination, validate)
    except migration.MigrationError as error:
        code = "output_already_exists" if str(error) == "destination_exists" else "output_publish_failed"
        raise FinalizationError(code) from error
    except OSError as error:
        raise FinalizationError("output_publish_failed") from error


def _source_locks_available(source_dir: Path, *, require_router_lock: bool = True) -> None:
    descriptors: list[int] = []
    try:
        filenames = (".direct_router.lock", ".writer.lock") if require_router_lock else (".writer.lock",)
        for filename in filenames:
            path = source_dir / filename
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
            except OSError as error:
                raise FinalizationError("source_lock_invalid") from error
            descriptors.append(descriptor)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise FinalizationError("source_lock_invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise FinalizationError("source_run_active") from error
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _source_sandbox_provider(source_dir: Path) -> str:
    try:
        body = (source_dir / "config.toml").read_bytes()
        provider = sft_run_identity._runtime_provider(body)
    except (OSError, sft_run_identity.SftRunIdentityError) as error:
        raise FinalizationError("source_config_invalid") from error
    return provider or "vmvm"


def _audit_source(source_dir: Path, expected_count: int, expected_provenance_sha256: str) -> dict[str, Any]:
    if SHA256_PATTERN.fullmatch(expected_provenance_sha256) is None:
        raise FinalizationError("expected_provenance_digest_invalid")
    provenance = source_dir / "provenance.txt"
    if _stable_sha256(provenance, max_bytes=MAX_PROVENANCE_BYTES) != expected_provenance_sha256:
        raise FinalizationError("source_provenance_digest_mismatch")
    try:
        config = tomllib.loads((source_dir / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise FinalizationError("source_config_invalid") from error
    if config.get("num_tasks") != expected_count or config.get("num_rollouts") != 1:
        raise FinalizationError("source_expected_count_mismatch")
    sandbox_provider = _source_sandbox_provider(source_dir)
    if sandbox_provider == "sandoq":
        try:
            _artifacts, config_summary, _task_identity, run_identity = exporter._validate_run_provenance(
                source_dir,
                MAX_SEQUENCE_TOKENS,
            )
        except (OSError, ValueError, exporter.ExportError) as error:
            raise FinalizationError("source_eval_run_identity_invalid") from error
        if (
            run_identity is None
            or run_identity.provider != "sandoq"
            or config_summary.get("model") != direct.EXPECTED_MODEL
            or run_identity.provenance.get("cleanup") is not None
        ):
            raise FinalizationError("source_eval_run_identity_invalid")
        if _stable_sha256(provenance, max_bytes=MAX_PROVENANCE_BYTES) != expected_provenance_sha256:
            raise FinalizationError("source_provenance_changed")
        return {
            "eval_run_identity_sha256": run_identity.eval_run_identity_sha256,
            "sandbox_provider": "sandoq",
        }
    try:
        summary = (
            serving_generation.audit_historical_source_generation(source_dir)
            if serving_generation.is_historical_source_generation(source_dir)
            else direct.audit_run_directory(source_dir)
        )
    except (OSError, ValueError, direct.DirectWorkerError, serving_generation.GenerationMigrationError) as error:
        raise FinalizationError("source_routing_provenance_invalid") from error
    if (
        summary.get("routing_epoch") != 3
        or summary.get("manifest_schema_version") != direct.ROUTER_MANIFEST_SCHEMA_VERSION
        or summary.get("router_policy") != direct.ROUTER_POLICY
        or summary.get("request_id_headers") != list(direct.ROUTER_REQUEST_ID_HEADERS)
        or summary.get("provider_concurrency") != direct.PRODUCTION_PROVIDER_CONCURRENCY
    ):
        raise FinalizationError("source_not_routing_epoch_3")
    if _stable_sha256(provenance, max_bytes=MAX_PROVENANCE_BYTES) != expected_provenance_sha256:
        raise FinalizationError("source_provenance_changed")
    result = {**summary, "sandbox_provider": "vmvm"}
    if os.path.lexists(source_dir / sft_run_identity.EVAL_RUN_IDENTITY_FILENAME):
        try:
            _artifacts, _config_summary, _task_identity, run_identity = exporter._validate_run_provenance(
                source_dir,
                MAX_SEQUENCE_TOKENS,
            )
        except (OSError, ValueError, exporter.ExportError) as error:
            raise FinalizationError("source_eval_run_identity_invalid") from error
        if run_identity is None or run_identity.provider != "vmvm":
            raise FinalizationError("source_eval_run_identity_invalid")
        result["eval_run_identity_sha256"] = run_identity.eval_run_identity_sha256
    return result


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    if not body or len(body) > MAX_CHILD_OUTPUT_BYTES:
        raise FinalizationError(code)

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
        raise FinalizationError(code) from error
    if not isinstance(value, dict):
        raise FinalizationError(code)
    return value


def _run_json_command(command: list[str], cwd: Path, code: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise FinalizationError(code) from error
    if completed.returncode != 0 or completed.stderr or len(completed.stdout) > MAX_CHILD_OUTPUT_BYTES:
        raise FinalizationError(code)
    return _parse_json_object(completed.stdout, code)


def _validate_label_summary(
    summary: Mapping[str, Any],
    index: Path,
    expected_count: int,
    *,
    allow_missing: bool = False,
) -> dict[str, int]:
    expected_keys = {
        "ignored_incomplete_tail",
        "ok",
        "results_sha256",
        "rows",
        "index_sha256",
        "epoch_1_rows",
        "epoch_2_rows",
        "epoch_3_rows",
    }
    if set(summary) != expected_keys or summary.get("ok") is not True:
        raise FinalizationError("routing_index_summary_invalid")
    counts = {f"epoch_{epoch}": summary.get(f"epoch_{epoch}_rows") for epoch in range(1, 4)}
    if (
        not all(_is_plain_int(value) and value >= 0 for value in counts.values())
        or not isinstance(summary.get("ignored_incomplete_tail"), bool)
        or not _is_plain_int(summary.get("rows"))
        or (summary["ignored_incomplete_tail"] and not allow_missing)
        or (summary["ignored_incomplete_tail"] and summary["rows"] >= expected_count)
        or (summary["rows"] > expected_count if allow_missing else summary["rows"] != expected_count)
        or sum(counts.values()) != summary["rows"]
        or counts["epoch_3"] < 1
        or SHA256_PATTERN.fullmatch(str(summary.get("results_sha256"))) is None
        or SHA256_PATTERN.fullmatch(str(summary.get("index_sha256"))) is None
    ):
        raise FinalizationError("routing_index_summary_invalid")
    _regular_file(index, "routing_index_invalid")
    if _stable_sha256(index) != summary["index_sha256"]:
        raise FinalizationError("routing_index_digest_mismatch")
    return counts


def _validate_sandoq_export_summary(
    summary: Mapping[str, Any],
    output_dir: Path,
    expected_count: int,
    selection: Selection,
    source_artifacts: Mapping[str, Mapping[str, int | str]],
    expected_exporter_sha256: str,
    validation_permyriad: int,
    split_salt: str,
    *,
    allow_incomplete_marker: bool = False,
) -> None:
    expected_summary_keys = {
        "approved_tasks",
        "eval_run_identity_sha256",
        "excluded_error_traces",
        "input_traces",
        "output_sha256",
        "rows",
        "sandbox_provider",
        "selected_traces",
        "selection",
        "status",
    }
    if (
        set(summary) != expected_summary_keys
        or summary.get("status") != "exported"
        or summary.get("selection") != selection
        or summary.get("sandbox_provider") != "sandoq"
        or not isinstance(summary.get("eval_run_identity_sha256"), str)
        or SHA256_PATTERN.fullmatch(summary["eval_run_identity_sha256"]) is None
        or any(
            not _is_plain_int(summary.get(key)) or summary[key] < 0
            for key in ("approved_tasks", "excluded_error_traces", "input_traces", "selected_traces")
        )
        or summary["approved_tasks"] != expected_count
        or summary["input_traces"] != expected_count
        or summary["selected_traces"] > expected_count
    ):
        raise FinalizationError("sft_export_summary_invalid")
    rows = summary.get("rows")
    output_hashes = summary.get("output_sha256")
    if (
        not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or any(not _is_plain_int(value) or value < 0 for value in rows.values())
        or rows["total"] != rows["train"] + rows["validation"]
        or not isinstance(output_hashes, dict)
        or set(output_hashes) != {"manifest", "target_rendering_contract", "train", "validation"}
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in output_hashes.values())
    ):
        raise FinalizationError("sft_export_summary_invalid")
    published = _canonical_existing_directory(output_dir, "sft_output_invalid")
    split_directories = {
        name: _canonical_existing_directory(published / name, "sft_output_invalid") for name in ("train", "validation")
    }
    expected_names = {
        "manifest.json",
        "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train",
        "validation",
    }
    if allow_incomplete_marker:
        expected_names.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    if {entry.name for entry in published.iterdir()} != expected_names or any(
        {entry.name for entry in directory.iterdir()} != {"train.jsonl"} for directory in split_directories.values()
    ):
        raise FinalizationError("sft_output_contract_invalid")
    paths = {
        "manifest.json": published / "manifest.json",
        "task-split.json": published / "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME: published / exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl": published / "train" / "train.jsonl",
        "validation/train.jsonl": published / "validation" / "train.jsonl",
    }
    observed = {name: _file_artifact(path, "sft_output_invalid") for name, path in paths.items()}
    if (
        observed["manifest.json"]["sha256"] != output_hashes["manifest"]
        or observed["train/train.jsonl"]["sha256"] != output_hashes["train"]
        or observed["validation/train.jsonl"]["sha256"] != output_hashes["validation"]
        or observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"] != output_hashes["target_rendering_contract"]
        or observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"] != exporter.TARGET_RENDERING_CONTRACT_SHA256
    ):
        raise FinalizationError("sft_output_digest_mismatch")
    try:
        manifest = _parse_json_object(paths["manifest.json"].read_bytes(), "sft_output_invalid")
        task_split = _parse_json_object(paths["task-split.json"].read_bytes(), "sft_output_task_split_invalid")
        target_rendering = _parse_json_object(
            paths[exporter.TARGET_RENDERING_CONTRACT_FILENAME].read_bytes(),
            "sft_output_target_rendering_invalid",
        )
    except OSError as error:
        raise FinalizationError("sft_output_invalid") from error
    expected_manifest_keys = {
        "artifacts",
        "config",
        "counts",
        "eval_run_identity",
        "exporter",
        "format",
        "max_sequence_tokens",
        "selection",
        "source_artifacts",
        "split",
        "target_rendering",
    }
    artifacts = manifest.get("artifacts")
    config = manifest.get("config")
    counts = manifest.get("counts")
    exporter_contract = manifest.get("exporter")
    split = manifest.get("split")
    allowed_count_keys = {
        "approved_tasks",
        "emitted_rows",
        "excluded_error_traces",
        "input_traces",
        "scored_fail_traces",
        "scored_pass_traces",
        "selected_fail_traces",
        "selected_pass_traces",
        "selected_traces",
        "selection_excluded_fail_traces",
        "train_rows",
        "train_traces",
        "validation_rows",
        "validation_traces",
    }
    if (
        set(manifest) != expected_manifest_keys
        or manifest.get("selection") != selection
        or manifest.get("max_sequence_tokens") != MAX_SEQUENCE_TOKENS
        or manifest.get("format") != FORMAT_CONTRACT
        or manifest.get("target_rendering") != exporter.TARGET_RENDERING_CONTRACT
        or target_rendering != exporter.TARGET_RENDERING_CONTRACT
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "task-split.json",
            exporter.TARGET_RENDERING_CONTRACT_FILENAME,
            "train/train.jsonl",
            "validation/train.jsonl",
        }
        or any(
            _artifact_record(record, "sft_output_contract_invalid") != observed[name]
            for name, record in artifacts.items()
        )
        or not isinstance(exporter_contract, dict)
        or set(exporter_contract) != {"file_sha256", "format_version"}
        or exporter_contract.get("file_sha256") != expected_exporter_sha256
        or exporter_contract.get("format_version") != exporter.FORMAT_VERSION
        or not isinstance(config, dict)
        or set(config)
        != {
            "capture_model_io",
            "dataset_revision",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "model",
            "num_rollouts",
            "taskset_id",
        }
        or config.get("capture_model_io") is not True
        or config.get("model") != direct.EXPECTED_MODEL
        or config.get("num_rollouts") != 1
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(config.get("taskset_id"), str)
        or not config["taskset_id"]
        or not isinstance(config.get("dataset_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(config["dataset_revision"]) is None
        or not isinstance(counts, dict)
        or not {
            "approved_tasks",
            "emitted_rows",
            "excluded_error_traces",
            "input_traces",
            "scored_pass_traces",
            "selected_pass_traces",
            "selected_traces",
            "train_rows",
            "validation_rows",
        }.issubset(counts)
        or not set(counts).issubset(allowed_count_keys)
        or any(not _is_plain_int(value) or value < 0 for value in counts.values())
        or not isinstance(split, dict)
        or set(split) != {"policy", "split_salt", "validation_permyriad"}
        or split.get("policy") != "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000"
        or split.get("split_salt") != split_salt
        or split.get("validation_permyriad") != validation_permyriad
    ):
        raise FinalizationError("sft_output_contract_invalid")
    if (
        set(task_split)
        != {
            "format_version",
            "split_salt",
            "train_task_sha256",
            "validation_permyriad",
            "validation_task_sha256",
        }
        or task_split.get("format_version") != exporter.FORMAT_VERSION
        or task_split.get("split_salt") != split_salt
        or task_split.get("validation_permyriad") != validation_permyriad
        or not isinstance(task_split.get("train_task_sha256"), list)
        or not isinstance(task_split.get("validation_task_sha256"), list)
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in task_split["train_task_sha256"])
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in task_split["validation_task_sha256"])
        or task_split["train_task_sha256"] != sorted(set(task_split["train_task_sha256"]))
        or task_split["validation_task_sha256"] != sorted(set(task_split["validation_task_sha256"]))
        or set(task_split["train_task_sha256"]) & set(task_split["validation_task_sha256"])
        or len(task_split["train_task_sha256"]) != counts.get("train_traces", 0)
        or len(task_split["validation_task_sha256"]) != counts.get("validation_traces", 0)
    ):
        raise FinalizationError("sft_output_task_split_invalid")
    if (
        counts["approved_tasks"] != expected_count
        or counts["input_traces"] != summary["input_traces"]
        or counts["selected_traces"] != summary["selected_traces"]
        or counts["excluded_error_traces"] != summary["excluded_error_traces"]
        or counts["input_traces"]
        != counts.get("scored_pass_traces", 0) + counts.get("scored_fail_traces", 0) + counts["excluded_error_traces"]
        or counts["selected_traces"] != counts.get("selected_pass_traces", 0) + counts.get("selected_fail_traces", 0)
        or (selection == "pass-only" and counts.get("selected_fail_traces", 0) != 0)
        or (selection == "pass-only" and counts.get("selected_pass_traces", 0) != counts.get("scored_pass_traces", 0))
        or counts["emitted_rows"] != rows["total"]
        or counts["train_rows"] != rows["train"]
        or counts["validation_rows"] != rows["validation"]
        or counts.get("train_traces", 0) + counts.get("validation_traces", 0) != counts["selected_traces"]
    ):
        raise FinalizationError("sft_output_counts_invalid")
    manifest_sources = manifest.get("source_artifacts")
    if (
        not isinstance(manifest_sources, dict)
        or set(manifest_sources) != set(SANDOQ_SOURCE_EXPORT_ARTIFACTS)
        or {name: _artifact_record(record, "sft_source_artifact_invalid") for name, record in manifest_sources.items()}
        != dict(source_artifacts)
    ):
        raise FinalizationError("sft_source_artifact_mismatch")
    try:
        run_identity = sft_run_identity.validate_manifest_identity(
            manifest.get("eval_run_identity"),
            counts=counts,
        )
    except sft_run_identity.SftRunIdentityError as error:
        raise FinalizationError(error.code) from error
    if (
        run_identity is None
        or run_identity.get("sandbox_provider") != "sandoq"
        or run_identity.get("eval_run_identity_sha256") != summary["eval_run_identity_sha256"]
        or run_identity.get("artifact") != source_artifacts[sft_run_identity.EVAL_RUN_IDENTITY_FILENAME]
    ):
        raise FinalizationError("sft_run_identity_mismatch")
    try:
        sft_run_identity.validate_manifest_source_artifacts(
            run_identity,
            source_artifacts,
        )
    except sft_run_identity.SftRunIdentityError as error:
        raise FinalizationError(error.code) from error


def _validate_export_summary(
    summary: Mapping[str, Any],
    output_dir: Path,
    expected_count: int,
    selection: Selection,
    expected_index_sha256: str | None,
    source_artifacts: Mapping[str, Mapping[str, int | str]],
    expected_exporter_sha256: str,
    validation_permyriad: int,
    split_salt: str,
    expected_exclusion_sha256: str | None = None,
    *,
    allow_incomplete_marker: bool = False,
) -> None:
    if expected_index_sha256 is None:
        if expected_exclusion_sha256 is not None:
            raise FinalizationError("sandoq_exclusion_selection_forbidden")
        _validate_sandoq_export_summary(
            summary,
            output_dir,
            expected_count,
            selection,
            source_artifacts,
            expected_exporter_sha256,
            validation_permyriad,
            split_salt,
            allow_incomplete_marker=allow_incomplete_marker,
        )
        return
    has_run_identity = sft_run_identity.EVAL_RUN_IDENTITY_FILENAME in source_artifacts
    expected_keys = {
        "approved_tasks",
        "excluded_error_traces",
        "input_traces",
        "output_sha256",
        "rows",
        "routing_epoch_rows",
        "selected_traces",
        "selection",
        "status",
    }
    if expected_exclusion_sha256 is not None:
        expected_keys.add("exclusion")
    if has_run_identity:
        expected_keys.update({"eval_run_identity_sha256", "sandbox_provider"})
    if set(summary) != expected_keys or summary.get("status") != "exported" or summary.get("selection") != selection:
        raise FinalizationError("sft_export_summary_invalid")
    if has_run_identity and (
        summary.get("sandbox_provider") != "vmvm"
        or not isinstance(summary.get("eval_run_identity_sha256"), str)
        or SHA256_PATTERN.fullmatch(summary["eval_run_identity_sha256"]) is None
    ):
        raise FinalizationError("sft_export_summary_invalid")
    count_keys = ("approved_tasks", "excluded_error_traces", "input_traces", "selected_traces")
    if not all(_is_plain_int(summary.get(key)) and summary[key] >= 0 for key in count_keys):
        raise FinalizationError("sft_export_summary_invalid")
    if (
        summary["approved_tasks"] != expected_count
        or summary["input_traces"] > expected_count
        or summary["selected_traces"] > expected_count
        or (expected_exclusion_sha256 is None and summary["input_traces"] != expected_count)
    ):
        raise FinalizationError("sft_export_summary_invalid")
    if expected_exclusion_sha256 is not None:
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
            or any(
                not _is_plain_int(exclusion.get(key)) or exclusion[key] < 0
                for key in (
                    "excluded_present_traces",
                    "missing_tasks",
                    "missing_or_errored_count",
                    "strict_invalid_pass_count",
                    "union_count",
                )
            )
            or exclusion["selection_manifest_sha256"] != expected_exclusion_sha256
            or exclusion["missing_or_errored_count"] + exclusion["strict_invalid_pass_count"]
            != exclusion["union_count"]
            or exclusion["excluded_present_traces"] + exclusion["missing_tasks"] != exclusion["union_count"]
            or summary["input_traces"] + exclusion["missing_tasks"] != expected_count
        ):
            raise FinalizationError("sft_export_summary_invalid")
    rows = summary.get("rows")
    if (
        not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or not all(_is_plain_int(value) and value >= 0 for value in rows.values())
        or rows["total"] != rows["train"] + rows["validation"]
    ):
        raise FinalizationError("sft_export_summary_invalid")
    routing_rows = summary.get("routing_epoch_rows")
    if (
        not isinstance(routing_rows, dict)
        or set(routing_rows) != {"1", "2", "3"}
        or not all(_is_plain_int(value) and value >= 0 for value in routing_rows.values())
        or sum(routing_rows.values()) != rows["total"]
    ):
        raise FinalizationError("sft_export_summary_invalid")
    output_hashes = summary.get("output_sha256")
    if (
        not isinstance(output_hashes, dict)
        or set(output_hashes) != {"manifest", "routing_epoch_index", "target_rendering_contract", "train", "validation"}
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in output_hashes.values())
        or output_hashes["routing_epoch_index"] != expected_index_sha256
    ):
        raise FinalizationError("sft_export_summary_invalid")
    published = _canonical_existing_directory(output_dir, "sft_output_invalid")
    split_directories = {
        name: _canonical_existing_directory(published / name, "sft_output_invalid") for name in ("train", "validation")
    }
    expected_names = {
        "manifest.json",
        "task-split.json",
        INDEX_FILENAME,
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train",
        "validation",
    }
    if allow_incomplete_marker:
        expected_names.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    if {entry.name for entry in published.iterdir()} != expected_names or any(
        {entry.name for entry in directory.iterdir()} != {"train.jsonl"} for directory in split_directories.values()
    ):
        raise FinalizationError("sft_output_contract_invalid")
    expected_output_paths = {
        "manifest.json": published / "manifest.json",
        "task-split.json": published / "task-split.json",
        INDEX_FILENAME: published / INDEX_FILENAME,
        exporter.TARGET_RENDERING_CONTRACT_FILENAME: published / exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl": published / "train" / "train.jsonl",
        "validation/train.jsonl": published / "validation" / "train.jsonl",
    }
    observed = {name: _file_artifact(path, "sft_output_invalid") for name, path in expected_output_paths.items()}
    if (
        observed["manifest.json"]["sha256"] != output_hashes["manifest"]
        or observed["train/train.jsonl"]["sha256"] != output_hashes["train"]
        or observed["validation/train.jsonl"]["sha256"] != output_hashes["validation"]
        or observed[INDEX_FILENAME]["sha256"] != output_hashes["routing_epoch_index"]
        or observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"] != output_hashes["target_rendering_contract"]
        or observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"] != exporter.TARGET_RENDERING_CONTRACT_SHA256
    ):
        raise FinalizationError("sft_output_digest_mismatch")
    try:
        manifest_body = expected_output_paths["manifest.json"].read_bytes()
        split_body = expected_output_paths["task-split.json"].read_bytes()
        target_rendering_body = expected_output_paths[exporter.TARGET_RENDERING_CONTRACT_FILENAME].read_bytes()
    except OSError as error:
        raise FinalizationError("sft_output_invalid") from error
    manifest_value = _parse_json_object(manifest_body, "sft_output_invalid")
    task_split = _parse_json_object(split_body, "sft_output_task_split_invalid")
    target_rendering_value = _parse_json_object(target_rendering_body, "sft_output_target_rendering_invalid")
    artifacts = manifest_value.get("artifacts")
    config = manifest_value.get("config")
    counts = manifest_value.get("counts")
    exporter_contract = manifest_value.get("exporter")
    source_validation = manifest_value.get("source_validation")
    split = manifest_value.get("split")
    routing = manifest_value.get("routing_epochs")
    expected_manifest_keys = {
        "artifacts",
        "config",
        "counts",
        "exporter",
        "format",
        "max_sequence_tokens",
        "routing_epochs",
        "selection",
        "source_validation",
        "source_artifacts",
        "split",
        "target_rendering",
    }
    if expected_exclusion_sha256 is not None:
        expected_manifest_keys.add("exclusion_selection")
    if has_run_identity:
        expected_manifest_keys.add("eval_run_identity")
    expected_artifact_names = {
        "task-split.json",
        INDEX_FILENAME,
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    }
    allowed_count_keys = {
        "approved_tasks",
        "emitted_rows",
        "excluded_error_traces",
        "input_traces",
        "scored_fail_traces",
        "scored_pass_traces",
        "selected_fail_traces",
        "selected_pass_traces",
        "selected_traces",
        "selection_excluded_fail_traces",
        "train_rows",
        "train_traces",
        "validation_rows",
        "validation_traces",
        *(
            f"routing_epoch_{epoch}_{suffix}"
            for epoch in range(1, 4)
            for suffix in ("input_traces", "selected_traces", "emitted_rows")
        ),
    }
    if expected_exclusion_sha256 is not None:
        allowed_count_keys.update(
            {
                "exclusion_missing_tasks",
                "exclusion_missing_or_errored_tasks",
                "exclusion_selected_traces",
                "exclusion_strict_invalid_pass_tasks",
            }
        )
    if (
        set(manifest_value) != expected_manifest_keys
        or manifest_value.get("selection") != selection
        or manifest_value.get("max_sequence_tokens") != MAX_SEQUENCE_TOKENS
        or manifest_value.get("format") != FORMAT_CONTRACT
        or manifest_value.get("target_rendering") != exporter.TARGET_RENDERING_CONTRACT
        or target_rendering_value != exporter.TARGET_RENDERING_CONTRACT
        or not isinstance(source_validation, dict)
        or set(source_validation)
        != {
            "max_sequence_tokens",
            "model_io_contract",
            "require_exact_provider_json",
            "require_model_io",
            "require_reasoning",
            "require_request_graph_match",
        }
        or not _is_plain_int(source_validation.get("max_sequence_tokens"))
        or source_validation["max_sequence_tokens"] != MAX_SEQUENCE_TOKENS
        or source_validation.get("model_io_contract")
        != (
            QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT_ID
            if expected_exclusion_sha256 is not None
            else QWEN3_A95B_MODEL_IO_CONTRACT_ID
        )
        or source_validation.get("require_exact_provider_json") is not False
        or source_validation.get("require_model_io") is not True
        or source_validation.get("require_reasoning") is not True
        or source_validation.get("require_request_graph_match") is not True
        or not isinstance(artifacts, dict)
        or set(artifacts) != expected_artifact_names
        or any(
            _artifact_record(record, "sft_output_contract_invalid") != observed[name]
            for name, record in artifacts.items()
        )
        or not isinstance(exporter_contract, dict)
        or set(exporter_contract) != {"file_sha256", "format_version"}
        or exporter_contract.get("format_version") != exporter.FORMAT_VERSION
        or exporter_contract.get("file_sha256") != expected_exporter_sha256
        or not isinstance(config, dict)
        or set(config)
        != {
            "capture_model_io",
            "dataset_revision",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "model",
            "num_rollouts",
            "taskset_id",
        }
        or config.get("capture_model_io") is not True
        or config.get("model") != direct.EXPECTED_MODEL
        or config.get("num_rollouts") != 1
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(config.get("taskset_id"), str)
        or not config["taskset_id"]
        or not isinstance(config.get("dataset_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(config["dataset_revision"]) is None
        or not isinstance(counts, dict)
        or not {
            "approved_tasks",
            "emitted_rows",
            "excluded_error_traces",
            "input_traces",
            "scored_pass_traces",
            "selected_pass_traces",
            "selected_traces",
            "train_rows",
            "validation_rows",
        }.issubset(counts)
        or not set(counts).issubset(allowed_count_keys)
        or any(not _is_plain_int(value) or value < 0 for value in counts.values())
        or not isinstance(split, dict)
        or set(split) != {"policy", "split_salt", "validation_permyriad"}
        or split.get("policy") != "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000"
        or split.get("split_salt") != split_salt
        or split.get("validation_permyriad") != validation_permyriad
    ):
        raise FinalizationError("sft_output_contract_invalid")
    if (
        set(task_split)
        != {"format_version", "split_salt", "train_task_sha256", "validation_permyriad", "validation_task_sha256"}
        or task_split.get("format_version") != exporter.FORMAT_VERSION
        or task_split.get("split_salt") != split_salt
        or task_split.get("validation_permyriad") != validation_permyriad
        or not isinstance(task_split.get("train_task_sha256"), list)
        or not isinstance(task_split.get("validation_task_sha256"), list)
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in task_split["train_task_sha256"])
        or any(SHA256_PATTERN.fullmatch(str(value)) is None for value in task_split["validation_task_sha256"])
        or task_split["train_task_sha256"] != sorted(set(task_split["train_task_sha256"]))
        or task_split["validation_task_sha256"] != sorted(set(task_split["validation_task_sha256"]))
        or set(task_split["train_task_sha256"]) & set(task_split["validation_task_sha256"])
        or len(task_split["train_task_sha256"]) != counts.get("train_traces", 0)
        or len(task_split["validation_task_sha256"]) != counts.get("validation_traces", 0)
    ):
        raise FinalizationError("sft_output_task_split_invalid")
    if (
        counts["approved_tasks"] != expected_count
        or counts["input_traces"] != summary["input_traces"]
        or counts["selected_traces"] != summary["selected_traces"]
        or counts["excluded_error_traces"] != summary["excluded_error_traces"]
        or counts["input_traces"]
        != counts.get("scored_pass_traces", 0) + counts.get("scored_fail_traces", 0) + counts["excluded_error_traces"]
        or counts["selected_traces"] != counts.get("selected_pass_traces", 0) + counts.get("selected_fail_traces", 0)
        or (selection == "pass-only" and counts.get("selected_fail_traces", 0) != 0)
        or (selection == "pass-only" and counts.get("selected_pass_traces", 0) != counts.get("scored_pass_traces", 0))
        or counts["emitted_rows"] != rows["total"]
        or counts["train_rows"] != rows["train"]
        or counts["validation_rows"] != rows["validation"]
        or counts.get("train_traces", 0) + counts.get("validation_traces", 0) != counts["selected_traces"]
    ):
        raise FinalizationError("sft_output_counts_invalid")
    manifest_sources = manifest_value.get("source_artifacts")
    if (
        not isinstance(manifest_sources, dict)
        or set(manifest_sources) != set(source_artifacts)
        or {name: _artifact_record(record, "sft_source_artifact_invalid") for name, record in manifest_sources.items()}
        != dict(source_artifacts)
    ):
        raise FinalizationError("sft_source_artifact_mismatch")
    try:
        run_identity = sft_run_identity.validate_manifest_identity(
            manifest_value.get("eval_run_identity"),
            counts=counts,
        )
    except sft_run_identity.SftRunIdentityError as error:
        raise FinalizationError(error.code) from error
    if has_run_identity:
        if (
            run_identity is None
            or run_identity.get("sandbox_provider") != "vmvm"
            or run_identity.get("eval_run_identity_sha256") != summary["eval_run_identity_sha256"]
            or run_identity.get("artifact") != source_artifacts[sft_run_identity.EVAL_RUN_IDENTITY_FILENAME]
        ):
            raise FinalizationError("sft_run_identity_mismatch")
        try:
            sft_run_identity.validate_manifest_source_artifacts(
                run_identity,
                source_artifacts,
            )
        except sft_run_identity.SftRunIdentityError as error:
            raise FinalizationError(error.code) from error
    elif run_identity is not None:
        raise FinalizationError("sft_run_identity_mismatch")
    routing_inputs = routing.get("input_traces") if isinstance(routing, dict) else None
    routing_emitted = routing.get("emitted_rows") if isinstance(routing, dict) else None
    routing_selected = {str(epoch): counts.get(f"routing_epoch_{epoch}_selected_traces", 0) for epoch in range(1, 4)}
    expected_routing_keys = {
        "admission_transition_sha256",
        "current_epoch",
        "emitted_rows",
        "epoch1_row_hashes_sha256",
        "epoch2_lineage_sha256",
        "index_sha256",
        "input_traces",
        "results_sha256",
        "row_mapping",
        "transition_sha256",
    }
    if (
        not isinstance(routing, dict)
        or set(routing) != expected_routing_keys
        or routing.get("current_epoch") != 3
        or routing.get("row_mapping") != "one unique SHA-256 mapping per physical results.jsonl row"
        or not isinstance(routing_inputs, dict)
        or not isinstance(routing_emitted, dict)
        or set(routing_inputs) != {"1", "2", "3"}
        or set(routing_emitted) != {"1", "2", "3"}
        or any(not _is_plain_int(value) or value < 0 for value in (*routing_inputs.values(), *routing_emitted.values()))
        or sum(routing_inputs.values()) != counts["input_traces"]
        or sum(routing_emitted.values()) != counts["emitted_rows"]
        or routing_emitted != routing_rows
        or sum(routing_selected.values()) != counts["selected_traces"]
        or any((routing_selected[epoch] == 0) != (routing_emitted[epoch] == 0) for epoch in ("1", "2", "3"))
        or routing_inputs != {str(epoch): counts.get(f"routing_epoch_{epoch}_input_traces", 0) for epoch in range(1, 4)}
        or routing_emitted
        != {str(epoch): counts.get(f"routing_epoch_{epoch}_emitted_rows", 0) for epoch in range(1, 4)}
        or routing.get("index_sha256") != source_artifacts[INDEX_FILENAME]["sha256"]
        or routing.get("results_sha256") != source_artifacts["results.jsonl"]["sha256"]
        or routing.get("transition_sha256") != source_artifacts["qwen_router_transition.json"]["sha256"]
        or routing.get("admission_transition_sha256")
        != source_artifacts["qwen_router_admission_transition.json"]["sha256"]
        or routing.get("epoch1_row_hashes_sha256") != source_artifacts["qwen_router_epoch1_rows.sha256"]["sha256"]
        or routing.get("epoch2_lineage_sha256") != source_artifacts["qwen_router_epoch2_lineage.jsonl"]["sha256"]
    ):
        raise FinalizationError("sft_output_routing_invalid")
    exclusion_manifest = manifest_value.get("exclusion_selection")
    if expected_exclusion_sha256 is None:
        if exclusion_manifest is not None:
            raise FinalizationError("sft_output_exclusion_invalid")
    elif (
        not isinstance(exclusion_manifest, dict)
        or set(exclusion_manifest)
        != {
            "approved_task_count",
            "artifacts",
            "manifest",
            "missing_or_errored_count",
            "strict_invalid_pass_count",
            "union_count",
        }
        or exclusion_manifest.get("manifest", {}).get("sha256") != expected_exclusion_sha256
        or exclusion_manifest.get("approved_task_count") != expected_count
        or exclusion_manifest.get("union_count") != summary["exclusion"]["union_count"]
        or exclusion_manifest.get("missing_or_errored_count") != summary["exclusion"]["missing_or_errored_count"]
        or exclusion_manifest.get("strict_invalid_pass_count") != summary["exclusion"]["strict_invalid_pass_count"]
        or not isinstance(exclusion_manifest.get("artifacts"), dict)
        or set(exclusion_manifest["artifacts"])
        != {"missing_or_errored_task_file", "strict_invalid_pass_task_file", "task_file"}
        or any(
            _artifact_record(record, "sft_output_exclusion_invalid")["bytes"] < 0
            for record in exclusion_manifest["artifacts"].values()
        )
        or counts.get("exclusion_missing_tasks") != summary["exclusion"]["missing_tasks"]
        or counts.get("exclusion_missing_or_errored_tasks") != summary["exclusion"]["missing_or_errored_count"]
        or counts.get("exclusion_selected_traces") != summary["exclusion"]["excluded_present_traces"]
        or counts.get("exclusion_strict_invalid_pass_tasks") != summary["exclusion"]["strict_invalid_pass_count"]
    ):
        raise FinalizationError("sft_output_exclusion_invalid")


def _validate_options(options: FinalizeOptions) -> None:
    if platform.machine() != "x86_64":
        raise FinalizationError("x86_64_required")
    if not _is_plain_int(options.expected_count) or options.expected_count < 1:
        raise FinalizationError("expected_count_invalid")
    if options.selection not in {"pass-only", "all-outcomes"}:
        raise FinalizationError("selection_invalid")
    if not _is_plain_int(options.validation_permyriad) or not 0 <= options.validation_permyriad < 10_000:
        raise FinalizationError("validation_permyriad_invalid")
    if not options.split_salt or "\x00" in options.split_salt:
        raise FinalizationError("split_salt_invalid")
    if (options.exclusion_selection_manifest is None) != (options.expected_exclusion_selection_manifest_sha256 is None):
        raise FinalizationError("exclusion_selection_arguments_invalid")
    if options.exclusion_selection_manifest is not None and options.selection != "pass-only":
        raise FinalizationError("exclusion_selection_arguments_invalid")
    if options.expected_exclusion_selection_manifest_sha256 is not None and (
        SHA256_PATTERN.fullmatch(options.expected_exclusion_selection_manifest_sha256) is None
    ):
        raise FinalizationError("exclusion_selection_digest_invalid")


def finalize_qwen_sft(
    options: FinalizeOptions,
    *,
    repository_validator: RepositoryValidator = _validate_repository,
    source_auditor: SourceAuditor = _audit_source,
    command_runner: CommandRunner = _run_json_command,
) -> dict[str, Any]:
    """Create an external routing index, then export SFT with that exact index."""
    _validate_options(options)
    project = repository_validator(options.project_dir, options.expected_project_revision)
    paths = _resolve_paths(options)
    if paths.project_dir != project:
        raise FinalizationError("project_path_mismatch")
    sandbox_provider = _source_sandbox_provider(paths.source_dir)
    if sandbox_provider == "sandoq" and options.exclusion_selection_manifest is not None:
        raise FinalizationError("sandoq_exclusion_selection_forbidden")
    exclusion_path: Path | None = None
    exclusion_sha256 = options.expected_exclusion_selection_manifest_sha256
    if options.exclusion_selection_manifest is not None:
        exclusion_path = _regular_file(
            options.exclusion_selection_manifest,
            "exclusion_selection_invalid",
        )
        if stat.S_IMODE(exclusion_path.stat().st_mode) != 0o600:
            raise FinalizationError("exclusion_selection_invalid")
        if _stable_sha256(exclusion_path, max_bytes=MAX_PROVENANCE_BYTES) != exclusion_sha256:
            raise FinalizationError("exclusion_selection_digest_mismatch")
    _source_locks_available(
        paths.source_dir,
        require_router_lock=sandbox_provider == "vmvm",
    )
    source_summary = source_auditor(
        paths.source_dir,
        options.expected_count,
        options.expected_provenance_sha256,
    )
    if source_summary.get("sandbox_provider", "vmvm") != sandbox_provider:
        raise FinalizationError("source_sandbox_provider_mismatch")
    repository_validator(paths.project_dir, options.expected_project_revision)

    workflow = paths.project_dir / "user" / "tianhaowu" / "terminal_bench_vmvm"
    expected_exporter_sha256 = _stable_sha256(workflow / "export_sft.py")
    with tempfile.TemporaryDirectory(
        prefix=f".{paths.output_dir.name}.finalize-",
        dir=paths.output_dir.parent,
    ) as staging:
        staging_dir = Path(staging)
        index: Path | None = None
        staged_output = staging_dir / "dataset"
        label_summary: dict[str, Any] | None = None
        epoch_input_rows: dict[str, int] | None = None
        if sandbox_provider == "vmvm":
            index = staging_dir / INDEX_FILENAME
            label_command = [
                sys.executable,
                str(workflow / "migrate_qwen_router_affinity.py"),
                "label",
                "--run-dir",
                str(paths.source_dir),
                "--output",
                str(index),
            ]
            if exclusion_path is not None:
                label_command.extend(
                    [
                        "--repair-selection-manifest",
                        str(exclusion_path),
                        "--repair-selection-manifest-sha256",
                        str(exclusion_sha256),
                    ]
                )
            label_summary = command_runner(
                label_command,
                paths.project_dir,
                "routing_index_failed",
            )
            epoch_input_rows = _validate_label_summary(
                label_summary,
                index,
                options.expected_count,
                allow_missing=exclusion_path is not None,
            )
            repository_validator(paths.project_dir, options.expected_project_revision)
            if _stable_sha256(paths.provenance, max_bytes=MAX_PROVENANCE_BYTES) != options.expected_provenance_sha256:
                raise FinalizationError("source_provenance_changed")

        export_command = [
            sys.executable,
            str(workflow / "export_sft.py"),
            str(paths.results),
            "--output-dir",
            str(staged_output),
            "--selection",
            options.selection,
            "--expected-count",
            str(options.expected_count),
            "--validation-permyriad",
            str(options.validation_permyriad),
            "--split-salt",
            options.split_salt,
            "--max-sequence-tokens",
            str(MAX_SEQUENCE_TOKENS),
        ]
        if index is not None:
            export_command.extend(["--routing-epoch-index", str(index)])
        if exclusion_path is not None:
            if _stable_sha256(exclusion_path, max_bytes=MAX_PROVENANCE_BYTES) != exclusion_sha256:
                raise FinalizationError("exclusion_selection_changed")
            export_command.extend(
                [
                    "--exclusion-selection-manifest",
                    str(exclusion_path),
                    "--exclusion-selection-manifest-sha256",
                    str(exclusion_sha256),
                ]
            )
        export_summary = command_runner(
            export_command,
            paths.project_dir,
            "sft_export_failed",
        )
        source_artifacts = _expected_source_artifacts(
            paths.source_dir,
            index,
            sandbox_provider=sandbox_provider,
        )
        _validate_export_summary(
            export_summary,
            staged_output,
            options.expected_count,
            options.selection,
            label_summary["index_sha256"] if label_summary is not None else None,
            source_artifacts,
            expected_exporter_sha256,
            options.validation_permyriad,
            options.split_salt,
            exclusion_sha256,
        )
        repository_validator(paths.project_dir, options.expected_project_revision)
        if _stable_sha256(paths.provenance, max_bytes=MAX_PROVENANCE_BYTES) != options.expected_provenance_sha256:
            raise FinalizationError("source_provenance_changed")
        if exclusion_path is not None and (
            _stable_sha256(exclusion_path, max_bytes=MAX_PROVENANCE_BYTES) != exclusion_sha256
            or stat.S_IMODE(exclusion_path.stat().st_mode) != 0o600
        ):
            raise FinalizationError("exclusion_selection_changed")
        _publish_output(
            staged_output,
            paths.output_dir,
            lambda path, incomplete: _validate_export_summary(
                export_summary,
                path,
                options.expected_count,
                options.selection,
                label_summary["index_sha256"] if label_summary is not None else None,
                source_artifacts,
                expected_exporter_sha256,
                options.validation_permyriad,
                options.split_salt,
                exclusion_sha256,
                allow_incomplete_marker=incomplete,
            ),
        )

    summary: dict[str, Any] = {
        "approved_tasks": export_summary["approved_tasks"],
        "excluded_error_traces": export_summary["excluded_error_traces"],
        "input_traces": export_summary["input_traces"],
        "output_sha256": export_summary["output_sha256"],
        "rows": export_summary["rows"],
        "selected_traces": export_summary["selected_traces"],
        "selection": options.selection,
        "status": "finalized",
        **({"exclusion": export_summary["exclusion"]} if "exclusion" in export_summary else {}),
    }
    if sandbox_provider == "vmvm":
        summary["routing_epoch_input_traces"] = epoch_input_rows
        summary["routing_epoch_rows"] = export_summary["routing_epoch_rows"]
        if "eval_run_identity_sha256" in export_summary:
            summary["eval_run_identity_sha256"] = export_summary["eval_run_identity_sha256"]
            summary["sandbox_provider"] = "vmvm"
    else:
        summary["eval_run_identity_sha256"] = export_summary["eval_run_identity_sha256"]
        summary["sandbox_provider"] = "sandoq"
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-provenance-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--selection", choices=("pass-only", "all-outcomes"), required=True)
    parser.add_argument("--validation-permyriad", type=int, required=True)
    parser.add_argument("--split-salt", required=True)
    parser.add_argument("--exclusion-selection-manifest", type=Path)
    parser.add_argument("--expected-exclusion-selection-manifest-sha256")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        options = FinalizeOptions(
            project_dir=args.project_dir,
            expected_project_revision=args.expected_project_revision,
            source_root=args.source_root,
            source_dir=args.source_dir,
            expected_provenance_sha256=args.expected_provenance_sha256,
            output_root=args.output_root,
            output_dir=args.output_dir,
            expected_count=args.expected_count,
            selection=args.selection,
            validation_permyriad=args.validation_permyriad,
            split_salt=args.split_salt,
            exclusion_selection_manifest=args.exclusion_selection_manifest,
            expected_exclusion_selection_manifest_sha256=args.expected_exclusion_selection_manifest_sha256,
        )
        summary = finalize_qwen_sft(options)
    except FinalizationError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
