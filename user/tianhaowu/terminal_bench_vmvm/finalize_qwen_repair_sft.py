#!/usr/bin/env python3
"""Finalize one fresh direct Qwen repair run as an attested pass-only SFT corpus.

Only aggregate counts, digests, and stable error codes are emitted. Task
identifiers and trace content are never written to stdout or stderr.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import export_sft as exporter
import finalize_qwen_sft as common
import migrate_qwen_router_affinity as migration
import migrate_qwen_serving_generation as generation
import sft_run_identity

ATTESTATION_FILENAME = "qwen_repair_attestation.json"
ATTESTATION_KIND = "qwen-direct-repair-attestation"
ATTESTATION_SCHEMA_VERSION = 2
SANDOQ_ATTESTATION_KIND = "qwen-sandoq-native-repair-attestation"
SANDOQ_ATTESTATION_SCHEMA_VERSION = 3
VMVM_TO_SANDOQ_TRANSITION_KIND = "vmvm-epoch3-to-sandoq-native-repair-v1"
GENERATION_ATTESTATION_SCHEMA_VERSION = 3
SELECTION_COPY_FILENAME = "repair_selection_manifest.json"
SELECTION_TASK_COPY_FILENAME = "repair_selection_tasks.txt"
SELECTION_MISSING_ERROR_COPY_FILENAME = "repair_selection_missing_or_errored_tasks.txt"
SELECTION_STRICT_INVALID_PASS_COPY_FILENAME = "repair_selection_strict_invalid_pass_tasks.txt"
SELECTION_SOURCE_FILENAMES = {
    SELECTION_COPY_FILENAME: "repair_manifest.json",
    SELECTION_TASK_COPY_FILENAME: "repair_tasks.txt",
    SELECTION_MISSING_ERROR_COPY_FILENAME: "repair_missing_or_errored_tasks.txt",
    SELECTION_STRICT_INVALID_PASS_COPY_FILENAME: "repair_strict_invalid_pass_tasks.txt",
}
MAX_MANIFEST_BYTES = 1 << 20
MAX_SEQUENCE_TOKENS = 262_144
SHA256_PATTERN = common.SHA256_PATTERN
SOURCE_ARTIFACTS = (
    "config.toml",
    "inputs/task_file.txt",
    "provenance.txt",
    "results.jsonl",
    "direct_workers.json",
)
SANDOQ_SOURCE_ARTIFACTS = (
    "config.toml",
    "inputs/task_file.txt",
    "provenance.txt",
    "results.jsonl",
    "direct_workers.json",
    sft_run_identity.EVAL_RUN_IDENTITY_FILENAME,
)
GENERATION_SOURCE_ARTIFACTS = (
    generation.CAPACITY_SMOKE_FILENAME,
    *(
        f"{generation.RUN_BUNDLE_DIRECTORY}/{name}"
        for name in (*sorted(generation.BUNDLE_FILES), generation.TRANSITION_FILENAME)
    ),
)
SELECTION_SOURCE_ARTIFACTS = frozenset(
    {
        "config",
        "direct_workers",
        "inputs_manifest",
        "source_config",
        "provenance",
        "results",
        "task_file",
        "image_manifest",
    }
)
LOCKED_SOURCE_ARTIFACTS = (
    *SOURCE_ARTIFACTS,
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/image_manifest.json",
)
SANDOQ_LOCKED_SOURCE_ARTIFACTS = (
    *SANDOQ_SOURCE_ARTIFACTS,
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/image_manifest.json",
)


class RepairFinalizationError(RuntimeError):
    """A fail-closed repair finalization error represented by a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise RepairFinalizationError("arguments_invalid")


@dataclass(frozen=True)
class RepairFinalizeOptions:
    project_dir: Path
    expected_project_revision: str
    source_root: Path
    source_dir: Path
    expected_provenance_sha256: str
    repair_selection_manifest: Path
    expected_repair_selection_manifest_sha256: str
    output_root: Path
    output_dir: Path
    expected_count: int
    validation_permyriad: int
    split_salt: str


@dataclass(frozen=True)
class RepairSelection:
    body: bytes
    sha256: str
    selection_bodies: Mapping[str, bytes]
    selection_artifacts: Mapping[str, Mapping[str, int | str]]
    selection_paths: Mapping[str, Path]
    config_sha256: str
    task_file_sha256: str
    repair_union_indices_sha256: str
    task_count: int
    missing_or_errored_count: int
    strict_invalid_pass_count: int
    approved_task_count: int
    template_sha256: str
    materializer_sha256: str
    exporter_sha256: str
    repository_revision: str
    submodules: Mapping[str, str]


RepositoryValidator = Callable[[Path, str], Path]
CommandRunner = Callable[[list[str], Path, str], dict[str, Any]]
SourceAuditor = Callable[[Path, int, str, RepairSelection], dict[str, Any]]
RuntimeValidator = Callable[[Path], Path]


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and common.GIT_SHA_PATTERN.fullmatch(value) is not None


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _file_artifact(
    path: Path,
    code: str,
    *,
    max_bytes: int | None = None,
    capture_body: bool = True,
    required_mode: int | None = None,
) -> tuple[bytes, dict[str, int | str]]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RepairFinalizationError(code) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RepairFinalizationError(code)
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise RepairFinalizationError(code)
        digest = hashlib.sha256()
        body = bytearray()
        size = 0
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise RepairFinalizationError(code)
            digest.update(chunk)
            if capture_body:
                body.extend(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise RepairFinalizationError(code) from error
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RepairFinalizationError(code)
    return bytes(body), {"bytes": size, "sha256": digest.hexdigest()}


def _parse_json(body: bytes, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise RepairFinalizationError(code) from error
    if not isinstance(value, dict):
        raise RepairFinalizationError(code)
    return value


def _selection_slugs(body: bytes, *, allow_empty: bool) -> tuple[str, ...]:
    if body and not body.endswith(b"\n"):
        raise RepairFinalizationError("repair_selection_invalid")
    try:
        values = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise RepairFinalizationError("repair_selection_invalid") from error
    if any(not value or value.strip() != value or "\t" in value or "\x00" in value for value in values):
        raise RepairFinalizationError("repair_selection_invalid")
    if len(values) != len(set(values)) or (not allow_empty and not values):
        raise RepairFinalizationError("repair_selection_invalid")
    return tuple(values)


def _load_repair_selection(path: Path, expected_sha256: str, expected_count: int) -> RepairSelection:
    if not _valid_sha256(expected_sha256):
        raise RepairFinalizationError("repair_selection_digest_invalid")
    body, artifact = _file_artifact(
        path,
        "repair_selection_unreadable",
        max_bytes=MAX_MANIFEST_BYTES,
        required_mode=0o600,
    )
    if artifact["sha256"] != expected_sha256:
        raise RepairFinalizationError("repair_selection_digest_mismatch")
    manifest = _parse_json(body, "repair_selection_invalid")
    selection = manifest.get("selection")
    config = manifest.get("config")
    planner = manifest.get("planner")
    approval = manifest.get("approval")
    code = manifest.get("code")
    source = manifest.get("source")
    if (
        set(manifest) != {"approval", "code", "config", "kind", "planner", "schema_version", "selection", "source"}
        or manifest.get("kind") != "qwen-aggregate-repair-selection"
        or not _is_plain_int(manifest.get("schema_version"))
        or manifest.get("schema_version") != 2
        or not isinstance(selection, dict)
        or set(selection)
        != {
            "approved_repair_count",
            "missing_or_errored_count",
            "missing_or_errored_indices_sha256",
            "missing_or_errored_task_file_sha256",
            "repair_union_indices_sha256",
            "strict_invalid_pass_count",
            "strict_invalid_pass_indices_sha256",
            "strict_invalid_pass_task_file_sha256",
            "task_file_sha256",
        }
        or not isinstance(config, dict)
        or set(config)
        != {
            "capture_model_io",
            "enable_thinking",
            "max_concurrent",
            "max_total_tokens",
            "preserve_thinking",
            "provider_concurrency",
            "retry_class_count",
            "retry_policy_sha256",
            "sha256",
            "template_sha256",
        }
        or not isinstance(planner, dict)
        or set(planner)
        != {
            "approved_task_count",
            "contract_verifiers_revision",
            "missing_or_errored_count",
            "module_sha256",
            "retained_count",
            "task_index_order_sha256",
        }
        or not isinstance(approval, dict)
        or set(approval) != {"approved_task_count", "approved_task_file_sha256"}
        or not isinstance(code, dict)
        or set(code) != {"exporter_sha256", "materializer_sha256", "repository_revision", "submodules"}
        or not isinstance(source, dict)
        or set(source) != {"artifacts", "routing_epoch", "task_count"}
    ):
        raise RepairFinalizationError("repair_selection_invalid")
    task_count = selection.get("approved_repair_count")
    missing_or_errored_count = selection.get("missing_or_errored_count")
    strict_invalid_pass_count = selection.get("strict_invalid_pass_count")
    approved_task_count = approval.get("approved_task_count")
    task_file_sha256 = selection.get("task_file_sha256")
    config_sha256 = config.get("sha256")
    materializer_sha256 = code.get("materializer_sha256")
    exporter_sha256 = code.get("exporter_sha256")
    repository_revision = code.get("repository_revision")
    submodules = code.get("submodules")
    source_artifacts = source.get("artifacts")
    retry_policy_bytes = "".join(f"{name}\n" for name in sorted(direct.ROLLOUT_RETRY_POLICY)).encode()
    if (
        not _is_plain_int(task_count)
        or task_count != expected_count
        or not _is_plain_int(missing_or_errored_count)
        or not _is_plain_int(strict_invalid_pass_count)
        or missing_or_errored_count < 0
        or strict_invalid_pass_count < 0
        or missing_or_errored_count + strict_invalid_pass_count != task_count
        or not _is_plain_int(approved_task_count)
        or approved_task_count < task_count
        or not isinstance(source_artifacts, dict)
        or set(source_artifacts) != SELECTION_SOURCE_ARTIFACTS
        or not all(
            isinstance(record, dict)
            and set(record) == {"sha256", "size_bytes"}
            and _valid_sha256(record["sha256"])
            and _is_plain_int(record["size_bytes"])
            and record["size_bytes"] >= 0
            for record in source_artifacts.values()
        )
        or approval.get("approved_task_file_sha256") != source_artifacts.get("task_file", {}).get("sha256")
        or not _valid_sha256(approval.get("approved_task_file_sha256"))
        or not _is_plain_int(planner.get("approved_task_count"))
        or planner.get("approved_task_count") != approved_task_count
        or not _is_plain_int(planner.get("missing_or_errored_count"))
        or planner.get("missing_or_errored_count") != missing_or_errored_count
        or not _is_plain_int(planner.get("retained_count"))
        or planner["retained_count"] + missing_or_errored_count != approved_task_count
        or any(
            not _valid_sha256(selection.get(name))
            for name in (
                "missing_or_errored_indices_sha256",
                "missing_or_errored_task_file_sha256",
                "repair_union_indices_sha256",
                "strict_invalid_pass_indices_sha256",
                "strict_invalid_pass_task_file_sha256",
            )
        )
        or not _valid_sha256(planner.get("task_index_order_sha256"))
        or planner.get("contract_verifiers_revision") != direct.ADMISSION_VERIFIERS_REVISION
        or planner.get("module_sha256") != direct.ADMISSION_RESUME_MODULE_SHA256
        or not _valid_sha256(task_file_sha256)
        or not _valid_sha256(config_sha256)
        or config.get("capture_model_io") is not True
        or config.get("enable_thinking") is not True
        or config.get("preserve_thinking") is not True
        or not _is_plain_int(config.get("max_concurrent"))
        or config.get("max_concurrent") != direct.MAX_DIRECT_CONCURRENCY
        or not _is_plain_int(config.get("provider_concurrency"))
        or config.get("provider_concurrency") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or not _is_plain_int(config.get("max_total_tokens"))
        or config.get("max_total_tokens") != MAX_SEQUENCE_TOKENS
        or not _is_plain_int(config.get("retry_class_count"))
        or config.get("retry_class_count") != len(direct.ROLLOUT_RETRY_POLICY)
        or config.get("retry_policy_sha256") != hashlib.sha256(retry_policy_bytes).hexdigest()
        or not _valid_sha256(config.get("template_sha256"))
        or not _valid_sha256(materializer_sha256)
        or not _valid_sha256(exporter_sha256)
        or not _valid_git_sha(repository_revision)
        or not isinstance(submodules, dict)
        or set(submodules) != set(common.REQUIRED_RUNTIME_SUBMODULES)
        or any(not _valid_git_sha(revision) for revision in submodules.values())
        or not _is_plain_int(source.get("routing_epoch"))
        or source.get("routing_epoch") != 3
        or not _is_plain_int(source.get("task_count"))
        or source.get("task_count") != approved_task_count
    ):
        raise RepairFinalizationError("repair_selection_contract_mismatch")
    selection_bodies: dict[str, bytes] = {SELECTION_COPY_FILENAME: body}
    selection_artifacts: dict[str, Mapping[str, int | str]] = {SELECTION_COPY_FILENAME: artifact}
    selection_paths: dict[str, Path] = {SELECTION_COPY_FILENAME: path}
    for copy_name, source_name in SELECTION_SOURCE_FILENAMES.items():
        if copy_name == SELECTION_COPY_FILENAME:
            continue
        selected_body, selected_artifact = _file_artifact(
            path.parent / source_name,
            "repair_selection_invalid",
            max_bytes=MAX_MANIFEST_BYTES,
            required_mode=0o600,
        )
        selection_bodies[copy_name] = selected_body
        selection_artifacts[copy_name] = selected_artifact
        selection_paths[copy_name] = path.parent / source_name
    union_slugs = _selection_slugs(selection_bodies[SELECTION_TASK_COPY_FILENAME], allow_empty=False)
    missing_slugs = _selection_slugs(
        selection_bodies[SELECTION_MISSING_ERROR_COPY_FILENAME],
        allow_empty=True,
    )
    strict_slugs = _selection_slugs(
        selection_bodies[SELECTION_STRICT_INVALID_PASS_COPY_FILENAME],
        allow_empty=True,
    )
    if (
        len(union_slugs) != task_count
        or len(missing_slugs) != missing_or_errored_count
        or len(strict_slugs) != strict_invalid_pass_count
        or set(missing_slugs) & set(strict_slugs)
        or set(union_slugs) != set(missing_slugs) | set(strict_slugs)
        or selection_artifacts[SELECTION_TASK_COPY_FILENAME]["sha256"] != task_file_sha256
        or selection_artifacts[SELECTION_MISSING_ERROR_COPY_FILENAME]["sha256"]
        != selection["missing_or_errored_task_file_sha256"]
        or selection_artifacts[SELECTION_STRICT_INVALID_PASS_COPY_FILENAME]["sha256"]
        != selection["strict_invalid_pass_task_file_sha256"]
    ):
        raise RepairFinalizationError("repair_selection_contract_mismatch")
    return RepairSelection(
        body=body,
        sha256=expected_sha256,
        selection_bodies=selection_bodies,
        selection_artifacts=selection_artifacts,
        selection_paths=selection_paths,
        config_sha256=str(config_sha256),
        task_file_sha256=str(task_file_sha256),
        repair_union_indices_sha256=str(selection["repair_union_indices_sha256"]),
        task_count=task_count,
        missing_or_errored_count=missing_or_errored_count,
        strict_invalid_pass_count=strict_invalid_pass_count,
        approved_task_count=approved_task_count,
        template_sha256=str(config["template_sha256"]),
        materializer_sha256=str(materializer_sha256),
        exporter_sha256=str(exporter_sha256),
        repository_revision=str(repository_revision),
        submodules=dict(submodules),
    )


@contextmanager
def _hold_source_locks(source: Path, *, require_router_lock: bool = True) -> Iterator[None]:
    descriptors: list[int] = []
    try:
        filenames = (".direct_router.lock", ".writer.lock") if require_router_lock else (".writer.lock",)
        for filename in filenames:
            path = source / filename
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
            except OSError as error:
                raise RepairFinalizationError("source_lock_invalid") from error
            descriptors.append(descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise RepairFinalizationError("source_lock_invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RepairFinalizationError("source_run_active") from error
            try:
                after = path.stat(follow_symlinks=False)
            except OSError as error:
                raise RepairFinalizationError("source_lock_invalid") from error
            if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise RepairFinalizationError("source_lock_invalid")
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _source_artifacts(
    source: Path,
    *,
    sandbox_provider: str = "vmvm",
) -> dict[str, dict[str, int | str]]:
    relatives = SOURCE_ARTIFACTS if sandbox_provider == "vmvm" else SANDOQ_SOURCE_ARTIFACTS
    if sandbox_provider == "vmvm" and (source / generation.RUN_BUNDLE_DIRECTORY).is_dir():
        relatives = (*relatives, *GENERATION_SOURCE_ARTIFACTS)
    return {
        relative: _file_artifact(
            source / relative,
            "source_artifact_unreadable",
            capture_body=False,
        )[1]
        for relative in relatives
    }


def _locked_source_artifacts(
    source: Path,
    *,
    sandbox_provider: str = "vmvm",
) -> dict[str, dict[str, int | str]]:
    relatives = LOCKED_SOURCE_ARTIFACTS if sandbox_provider == "vmvm" else SANDOQ_LOCKED_SOURCE_ARTIFACTS
    if sandbox_provider == "vmvm" and (source / generation.RUN_BUNDLE_DIRECTORY).is_dir():
        relatives = (*relatives, *GENERATION_SOURCE_ARTIFACTS)
    return {
        relative: _file_artifact(
            source / relative,
            "source_artifact_unreadable",
            capture_body=False,
        )[1]
        for relative in relatives
    }


def _selection_requires_generation(repair_selection: RepairSelection) -> bool:
    selection = _parse_json(repair_selection.body, "repair_selection_invalid")
    source = selection.get("source")
    artifacts = source.get("artifacts") if isinstance(source, dict) else None
    results = artifacts.get("results") if isinstance(artifacts, dict) else None
    contract = generation._load_contract()
    return results == contract["source_generation"]["artifacts"]["results.jsonl"]


def _audit_source(
    source: Path,
    expected_count: int,
    expected_provenance_sha256: str,
    repair_selection: RepairSelection,
) -> dict[str, Any]:
    if not _valid_sha256(expected_provenance_sha256):
        raise RepairFinalizationError("expected_provenance_digest_invalid")
    try:
        sandbox_provider = common._source_sandbox_provider(source)
    except common.FinalizationError as error:
        raise RepairFinalizationError(error.code) from error
    artifacts = _source_artifacts(source, sandbox_provider=sandbox_provider)
    generation_present = sandbox_provider == "vmvm" and (source / generation.RUN_BUNDLE_DIRECTORY).is_dir()
    transition: dict[str, Any] | None = None
    if generation_present:
        transition = _parse_json(
            _file_artifact(
                source / generation.RUN_BUNDLE_DIRECTORY / generation.TRANSITION_FILENAME,
                "source_generation_transition_invalid",
                max_bytes=MAX_MANIFEST_BYTES,
            )[0],
            "source_generation_transition_invalid",
        )
    if artifacts["provenance.txt"]["sha256"] != expected_provenance_sha256:
        raise RepairFinalizationError("source_provenance_digest_mismatch")
    if artifacts["inputs/task_file.txt"]["sha256"] != repair_selection.task_file_sha256:
        raise RepairFinalizationError("source_task_digest_mismatch")
    source_config_body, source_config_artifact = _file_artifact(
        source / "inputs" / "source_config.toml",
        "source_config_unreadable",
        max_bytes=MAX_MANIFEST_BYTES,
    )
    transition_artifacts = transition.get("artifacts") if transition is not None else None
    generation_config_artifact = (
        transition_artifacts.get(generation.GENERATION_CONFIG_FILENAME)
        if isinstance(transition_artifacts, dict)
        else None
    )
    if generation_present and (
        not isinstance(generation_config_artifact, dict) or not _valid_sha256(generation_config_artifact.get("sha256"))
    ):
        raise RepairFinalizationError("source_generation_transition_invalid")
    expected_source_config_sha256 = (
        generation_config_artifact["sha256"] if generation_present else repair_selection.config_sha256
    )
    if sandbox_provider == "vmvm" and source_config_artifact["sha256"] != expected_source_config_sha256:
        raise RepairFinalizationError("source_config_digest_mismatch")
    try:
        config_body, _config_artifact = _file_artifact(
            source / "config.toml",
            "source_config_invalid",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        config = tomllib.loads(config_body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RepairFinalizationError("source_config_invalid") from error
    try:
        source_config = tomllib.loads(source_config_body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RepairFinalizationError("source_config_invalid") from error
    client = config.get("client")
    sampling = config.get("sampling")
    chat = sampling.get("chat_template_kwargs") if isinstance(sampling, dict) else None
    retries = config.get("retries")
    rollout = retries.get("rollout") if isinstance(retries, dict) else None
    retry_include = rollout.get("include") if isinstance(rollout, dict) else None
    taskset = config.get("taskset")
    if sandbox_provider == "sandoq":
        try:
            _run_artifacts, config_summary, _task_identity, run_identity = exporter._validate_run_provenance(
                source,
                MAX_SEQUENCE_TOKENS,
            )
        except (OSError, ValueError, exporter.ExportError) as error:
            raise RepairFinalizationError("source_eval_run_identity_invalid") from error
        dataset_revision = taskset.get("dataset_revision") if isinstance(taskset, dict) else None
        if (
            run_identity is None
            or run_identity.provider != "sandoq"
            or config_summary.get("model") != direct.EXPECTED_MODEL
            or config.get("num_tasks") != expected_count
            or config.get("num_rollouts") != 1
            or any(
                config.get(key) != MAX_SEQUENCE_TOKENS
                for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
            )
            or not isinstance(client, dict)
            or client.get("capture_model_io") is not True
            or not isinstance(chat, dict)
            or chat.get("enable_thinking") is not True
            or chat.get("preserve_thinking") is not True
            or not isinstance(rollout, dict)
            or rollout.get("max_retries") != 2
            or not isinstance(retry_include, list)
            or frozenset(retry_include) != direct.ROLLOUT_RETRY_POLICY
            or len(retry_include) != len(set(retry_include))
            or rollout.get("exclude", []) != []
            or not isinstance(taskset, dict)
            or taskset.get("id") != "terminal-bench-vmvm"
            or taskset.get("task_file_sha256") != repair_selection.task_file_sha256
            or not isinstance(dataset_revision, str)
            or not _valid_git_sha(dataset_revision)
        ):
            raise RepairFinalizationError("source_contract_invalid")
        return {
            "artifacts": artifacts,
            "corpus": {
                "task_count": expected_count,
                "task_file_sha256": repair_selection.task_file_sha256,
                "taskset_id": "terminal-bench-vmvm",
                "dataset_revision": dataset_revision,
            },
            "provider": {
                "eval_run_identity_sha256": run_identity.eval_run_identity_sha256,
                "identity_compatibility_sha256": run_identity.compatibility_sha256,
                "sandbox_provider": "sandoq",
                "transition_kind": VMVM_TO_SANDOQ_TRANSITION_KIND,
            },
        }
    expected_max_concurrent = generation.ROLLOUT_CONCURRENCY if generation_present else direct.MAX_DIRECT_CONCURRENCY
    if (
        config.get("num_tasks") != expected_count
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != expected_max_concurrent
        or config.get("multiplex") != expected_max_concurrent
        or any(
            config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or (
            generation_present
            and (
                client.get("max_connections") != generation.PROVIDER_CONCURRENCY
                or client.get("max_keepalive_connections") != generation.PROVIDER_CONCURRENCY
            )
        )
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != 32_768
        or not isinstance(chat, dict)
        or chat.get("enable_thinking") is not True
        or chat.get("preserve_thinking") is not True
        or not isinstance(rollout, dict)
        or rollout.get("max_retries") != 2
        or not isinstance(retry_include, list)
        or not all(isinstance(value, str) for value in retry_include)
        or len(retry_include) != len(set(retry_include))
        or frozenset(retry_include) != direct.ROLLOUT_RETRY_POLICY
        or rollout.get("exclude", []) != []
        or not isinstance(taskset, dict)
        or taskset.get("id") != "terminal-bench-vmvm"
        or taskset.get("task_file_sha256") != repair_selection.task_file_sha256
        or source_config.get("num_tasks") != expected_count
    ):
        raise RepairFinalizationError("source_contract_invalid")
    if _selection_requires_generation(repair_selection) != generation_present:
        raise RepairFinalizationError("source_generation_transition_missing")
    if generation_present:
        assert transition is not None
        transition_selection = transition.get("repair_selection")
        if (
            not isinstance(transition_selection, dict)
            or transition_selection.get("manifest_sha256") != repair_selection.sha256
            or transition_selection.get("task_file_sha256") != repair_selection.task_file_sha256
            or transition_selection.get("union_indices_sha256") != repair_selection.repair_union_indices_sha256
        ):
            raise RepairFinalizationError("source_generation_selection_mismatch")
    try:
        summary = generation.audit_repair_run(source) if generation_present else direct.audit_run_directory(source)
    except (OSError, ValueError, direct.DirectWorkerError, generation.GenerationMigrationError) as error:
        raise RepairFinalizationError("source_routing_provenance_invalid") from error
    routing = {
        "routing_epoch": summary.get("routing_epoch"),
        "manifest_schema_version": summary.get("manifest_schema_version"),
        "provider_concurrency": summary.get("provider_concurrency"),
        "queue_size": summary.get("queue_size"),
        "router_policy": summary.get("router_policy"),
        "request_id_headers": summary.get("request_id_headers"),
    }
    expected_routing = {
        "routing_epoch": 1,
        "manifest_schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
        "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
        "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
        "router_policy": direct.ROUTER_POLICY,
        "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
    }
    if generation_present:
        routing.update(
            {
                "serving_generation": summary.get("serving_generation"),
                "capacity_smoke_sha256": summary.get("capacity_smoke_sha256"),
                "rollout_concurrency": summary.get("rollout_concurrency"),
                "serving_generation_transition_sha256": summary.get("serving_generation_transition_sha256"),
                "spec_sha256": summary.get("spec_sha256"),
                "endpoint_bundle_sha256": summary.get("endpoint_bundle_sha256"),
                "worker_count": summary.get("endpoints"),
                "vmvm_lease_concurrency": summary.get("vmvm_lease_concurrency"),
            }
        )
        contract = generation._load_contract()
        expected_routing.update(
            {
                "capacity_smoke_sha256": artifacts[generation.CAPACITY_SMOKE_FILENAME]["sha256"],
                "provider_concurrency": generation.PROVIDER_CONCURRENCY,
                "queue_size": generation.QUEUE_SIZE,
                "rollout_concurrency": generation.ROLLOUT_CONCURRENCY,
                "serving_generation": 2,
                "serving_generation_transition_sha256": _file_artifact(
                    source / generation.RUN_BUNDLE_DIRECTORY / generation.TRANSITION_FILENAME,
                    "source_generation_transition_invalid",
                    capture_body=False,
                )[1]["sha256"],
                "spec_sha256": contract["target_generation"]["spec_sha256"],
                "endpoint_bundle_sha256": contract["target_generation"]["endpoint_bundle_sha256"],
                "worker_count": contract["target_generation"]["worker_count"],
                "vmvm_lease_concurrency": generation.VMVM_LEASE_CONCURRENCY,
            }
        )
    if summary.get("ok") is not True or routing != expected_routing:
        raise RepairFinalizationError("source_not_fresh_schema3_repair")
    dataset_revision = taskset.get("dataset_revision")
    if not isinstance(dataset_revision, str) or not _valid_git_sha(dataset_revision):
        raise RepairFinalizationError("source_corpus_identity_invalid")
    return {
        "artifacts": artifacts,
        "corpus": {
            "task_count": expected_count,
            "task_file_sha256": repair_selection.task_file_sha256,
            "taskset_id": "terminal-bench-vmvm",
            "dataset_revision": dataset_revision,
        },
        "routing": routing,
    }


def _submodule_revisions(project: Path, expected_revision: str) -> dict[str, str]:
    revisions: dict[str, str] = {}
    for relative in common.REQUIRED_RUNTIME_SUBMODULES:
        record = common._run_git(
            project,
            ["ls-tree", expected_revision, "--", relative],
            "project_submodules_unavailable",
        ).strip()
        fields = record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or common.GIT_SHA_PATTERN.fullmatch(fields[2]) is None
            or fields[3] != relative
        ):
            raise RepairFinalizationError("project_submodules_invalid")
        revisions[relative] = fields[2]
    return revisions


def _validate_submodule_revisions(revisions: Mapping[str, str]) -> dict[str, str]:
    if set(revisions) != set(common.REQUIRED_RUNTIME_SUBMODULES) or any(
        not _valid_git_sha(value) for value in revisions.values()
    ):
        raise RepairFinalizationError("project_submodules_invalid")
    return dict(revisions)


def _validate_runtime_origin(project: Path) -> Path:
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    expected_modules = {
        Path(__file__).resolve(strict=True): workflow / "finalize_qwen_repair_sft.py",
        Path(common.__file__).resolve(strict=True): workflow / "finalize_qwen_sft.py",
        Path(direct.__file__).resolve(strict=True): workflow / "direct_qwen_workers.py",
        Path(generation.__file__).resolve(strict=True): workflow / "migrate_qwen_serving_generation.py",
        Path(migration.__file__).resolve(strict=True): workflow / "migrate_qwen_router_affinity.py",
    }
    if Path(__file__).resolve(strict=True).parents[3] != project:
        raise RepairFinalizationError("runtime_origin_mismatch")
    for observed, expected in expected_modules.items():
        try:
            expected_resolved = expected.resolve(strict=True)
            metadata = expected.lstat()
        except OSError as error:
            raise RepairFinalizationError("runtime_origin_mismatch") from error
        if observed != expected_resolved or not stat.S_ISREG(metadata.st_mode) or expected_resolved != expected:
            raise RepairFinalizationError("runtime_origin_mismatch")
    return workflow


def _validate_selection_code(
    selection: RepairSelection,
    project: Path,
    workflow: Path,
    expected_revision: str,
    submodules: Mapping[str, str],
) -> None:
    materializer = _file_artifact(
        workflow / "materialize_qwen_repair.py",
        "materializer_unreadable",
        capture_body=False,
    )[1]
    template = _file_artifact(
        workflow / "configs" / "eval" / "mobius_qwen_a95b_2500.toml",
        "repair_template_unreadable",
        capture_body=False,
    )[1]
    exporter = _file_artifact(
        workflow / "export_sft.py",
        "project_exporter_invalid",
        capture_body=False,
    )[1]
    if (
        workflow.parents[2] != project
        or selection.repository_revision != expected_revision
        or selection.submodules != submodules
        or selection.materializer_sha256 != materializer["sha256"]
        or selection.exporter_sha256 != exporter["sha256"]
        or selection.template_sha256 != template["sha256"]
    ):
        raise RepairFinalizationError("repair_selection_code_mismatch")


def _validate_selection_unchanged(selection: RepairSelection) -> None:
    for name, path in selection.selection_paths.items():
        _body, artifact = _file_artifact(
            path,
            "repair_selection_changed",
            max_bytes=MAX_MANIFEST_BYTES,
            capture_body=False,
            required_mode=0o600,
        )
        if artifact != selection.selection_artifacts[name]:
            raise RepairFinalizationError("repair_selection_changed")


def _validate_source_audit(
    audit: Mapping[str, Any],
    repair_selection: RepairSelection,
    expected_count: int,
) -> None:
    provider = audit.get("provider")
    if provider is not None:
        artifacts = audit.get("artifacts")
        corpus = audit.get("corpus")
        if (
            set(audit) != {"artifacts", "corpus", "provider"}
            or not isinstance(provider, dict)
            or set(provider)
            != {
                "eval_run_identity_sha256",
                "identity_compatibility_sha256",
                "sandbox_provider",
                "transition_kind",
            }
            or provider.get("sandbox_provider") != "sandoq"
            or provider.get("transition_kind") != VMVM_TO_SANDOQ_TRANSITION_KIND
            or not _valid_sha256(provider.get("eval_run_identity_sha256"))
            or not _valid_sha256(provider.get("identity_compatibility_sha256"))
            or not isinstance(artifacts, dict)
            or set(artifacts) != set(SANDOQ_SOURCE_ARTIFACTS)
            or not all(
                isinstance(record, dict)
                and set(record) == {"bytes", "sha256"}
                and _is_plain_int(record["bytes"])
                and record["bytes"] >= 0
                and _valid_sha256(record["sha256"])
                for record in artifacts.values()
            )
            or not isinstance(corpus, dict)
            or set(corpus) != {"task_count", "task_file_sha256", "taskset_id", "dataset_revision"}
            or corpus.get("task_count") != expected_count
            or corpus.get("task_file_sha256") != repair_selection.task_file_sha256
            or corpus.get("taskset_id") != "terminal-bench-vmvm"
            or not _valid_git_sha(corpus.get("dataset_revision"))
        ):
            raise RepairFinalizationError("source_audit_invalid")
        return
    expected_routing = {
        "routing_epoch": 1,
        "manifest_schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
        "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
        "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
        "router_policy": direct.ROUTER_POLICY,
        "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
    }
    artifacts = audit.get("artifacts")
    routing = audit.get("routing")
    corpus = audit.get("corpus")
    generation_role = isinstance(routing, dict) and "serving_generation" in routing
    if generation_role:
        contract = generation._load_contract()
        expected_routing.update(
            {
                "capacity_smoke_sha256": routing.get("capacity_smoke_sha256"),
                "endpoint_bundle_sha256": contract["target_generation"]["endpoint_bundle_sha256"],
                "provider_concurrency": generation.PROVIDER_CONCURRENCY,
                "queue_size": generation.QUEUE_SIZE,
                "rollout_concurrency": generation.ROLLOUT_CONCURRENCY,
                "serving_generation": 2,
                "serving_generation_transition_sha256": routing.get("serving_generation_transition_sha256"),
                "spec_sha256": contract["target_generation"]["spec_sha256"],
                "worker_count": contract["target_generation"]["worker_count"],
                "vmvm_lease_concurrency": generation.VMVM_LEASE_CONCURRENCY,
            }
        )
    expected_artifacts = set(SOURCE_ARTIFACTS) | (set(GENERATION_SOURCE_ARTIFACTS) if generation_role else set())
    if (
        set(audit) != {"artifacts", "routing", "corpus"}
        or not isinstance(artifacts, dict)
        or set(artifacts) != expected_artifacts
        or not all(
            isinstance(record, dict)
            and set(record) == {"bytes", "sha256"}
            and _is_plain_int(record["bytes"])
            and record["bytes"] >= 0
            and _valid_sha256(record["sha256"])
            for record in artifacts.values()
        )
        or routing != expected_routing
        or (
            generation_role
            and (
                not _valid_sha256(routing.get("serving_generation_transition_sha256"))
                or not _valid_sha256(routing.get("capacity_smoke_sha256"))
            )
        )
        or not _is_plain_int(routing.get("routing_epoch"))
        or not _is_plain_int(routing.get("manifest_schema_version"))
        or not _is_plain_int(routing.get("provider_concurrency"))
        or not _is_plain_int(routing.get("queue_size"))
        or not isinstance(corpus, dict)
        or set(corpus) != {"task_count", "task_file_sha256", "taskset_id", "dataset_revision"}
        or not _is_plain_int(corpus.get("task_count"))
        or corpus.get("task_count") != expected_count
        or corpus.get("task_file_sha256") != repair_selection.task_file_sha256
        or corpus.get("taskset_id") != "terminal-bench-vmvm"
        or not _valid_git_sha(corpus.get("dataset_revision"))
    ):
        raise RepairFinalizationError("source_audit_invalid")


def _write_exclusive(path: Path, body: bytes) -> dict[str, int | str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(path, flags, 0o600), "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise RepairFinalizationError("staging_write_failed") from error
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _replace_manifest(path: Path, value: Mapping[str, Any]) -> dict[str, int | str]:
    body = _json_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    artifact = _write_exclusive(temporary, body)
    try:
        os.replace(temporary, path)
        migration._fsync_directory(path.parent)
    except OSError as error:
        if temporary.exists():
            temporary.unlink()
        raise RepairFinalizationError("staging_manifest_write_failed") from error
    return artifact


def _validate_export_summary(
    summary: Mapping[str, Any],
    output: Path,
    expected_count: int,
    source_artifacts: Mapping[str, Mapping[str, int | str]],
    corpus: Mapping[str, Any],
    validation_permyriad: int,
    split_salt: str,
    expected_exporter_sha256: str,
    provider: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, int | str]]]:
    expected_keys = {
        "approved_tasks",
        "excluded_error_traces",
        "input_traces",
        "output_sha256",
        "rows",
        "selected_traces",
        "selection",
        "status",
    }
    if provider is not None:
        expected_keys.update({"eval_run_identity_sha256", "sandbox_provider"})
    if set(summary) != expected_keys or summary.get("status") != "exported" or summary.get("selection") != "pass-only":
        raise RepairFinalizationError("sft_export_summary_invalid")
    if provider is not None and (
        summary.get("sandbox_provider") != "sandoq"
        or summary.get("eval_run_identity_sha256") != provider.get("eval_run_identity_sha256")
    ):
        raise RepairFinalizationError("sft_export_summary_invalid")
    if (
        not _is_plain_int(summary.get("input_traces"))
        or summary.get("input_traces") != expected_count
        or summary.get("approved_tasks") != expected_count
        or not _is_plain_int(summary.get("selected_traces"))
        or not 0 <= summary["selected_traces"] <= expected_count
        or not _is_plain_int(summary.get("excluded_error_traces"))
        or not 0 <= summary["excluded_error_traces"] <= expected_count
    ):
        raise RepairFinalizationError("sft_export_summary_invalid")
    rows = summary.get("rows")
    output_hashes = summary.get("output_sha256")
    if (
        not isinstance(rows, dict)
        or set(rows) != {"total", "train", "validation"}
        or not all(_is_plain_int(value) and value >= 0 for value in rows.values())
        or rows["total"] != rows["train"] + rows["validation"]
        or not isinstance(output_hashes, dict)
        or set(output_hashes) != {"manifest", "target_rendering_contract", "train", "validation"}
        or any(not _valid_sha256(value) for value in output_hashes.values())
    ):
        raise RepairFinalizationError("sft_export_summary_invalid")
    expected_files = {
        "manifest.json": output_hashes["manifest"],
        "task-split.json": None,
        exporter.TARGET_RENDERING_CONTRACT_FILENAME: output_hashes["target_rendering_contract"],
        "train/train.jsonl": output_hashes["train"],
        "validation/train.jsonl": output_hashes["validation"],
    }
    observed: dict[str, dict[str, int | str]] = {}
    for relative, expected_sha256 in expected_files.items():
        _body, artifact = _file_artifact(
            output / relative,
            "sft_output_invalid",
            capture_body=False,
        )
        if expected_sha256 is not None and artifact["sha256"] != expected_sha256:
            raise RepairFinalizationError("sft_output_digest_mismatch")
        observed[relative] = artifact
    manifest_body, _manifest_artifact = _file_artifact(output / "manifest.json", "sft_output_invalid")
    manifest = _parse_json(manifest_body, "sft_output_invalid")
    artifacts = manifest.get("artifacts")
    config = manifest.get("config")
    counts = manifest.get("counts")
    exporter_contract = manifest.get("exporter")
    format_contract = manifest.get("format")
    source_validation = manifest.get("source_validation")
    split = manifest.get("split")
    target_rendering = manifest.get("target_rendering")
    allowed_count_keys = {
        "approved_tasks",
        "input_traces",
        "excluded_error_traces",
        "scored_pass_traces",
        "scored_fail_traces",
        "selection_excluded_fail_traces",
        "selected_traces",
        "selected_pass_traces",
        "selected_fail_traces",
        "emitted_rows",
        "train_traces",
        "train_rows",
        "validation_traces",
        "validation_rows",
    }
    expected_format = {
        "assistant_finish_reason": "retained verbatim for every sampled assistant message",
        "assistant_tool_calls": "OpenAI function-call objects",
        "history_assistant_reasoning": "retained verbatim",
        "loss_mask": "message.trainable; exactly one final assistant message is true",
        "sample_unit": "one unique sampled assistant node with its root-to-node context",
        "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
        "task_identity": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
    }
    expected_manifest_keys = {
        "artifacts",
        "config",
        "counts",
        "exporter",
        "format",
        "max_sequence_tokens",
        "selection",
        "source_validation",
        "source_artifacts",
        "split",
        "target_rendering",
    }
    if provider is not None:
        expected_manifest_keys.add("eval_run_identity")
    if (
        set(manifest) != expected_manifest_keys
        or manifest.get("selection") != "pass-only"
        or not _is_plain_int(manifest.get("max_sequence_tokens"))
        or manifest.get("max_sequence_tokens") != MAX_SEQUENCE_TOKENS
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "task-split.json",
            exporter.TARGET_RENDERING_CONTRACT_FILENAME,
            "train/train.jsonl",
            "validation/train.jsonl",
        }
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
        or not isinstance(counts, dict)
        or not {
            "input_traces",
            "scored_pass_traces",
            "selected_traces",
            "selected_pass_traces",
            "emitted_rows",
        }.issubset(counts)
        or not set(counts).issubset(allowed_count_keys)
        or not all(_is_plain_int(value) and value >= 0 for value in counts.values())
        or not isinstance(exporter_contract, dict)
        or set(exporter_contract) != {"file_sha256", "format_version"}
        or not _is_plain_int(exporter_contract.get("format_version"))
        or exporter_contract.get("format_version") != exporter.FORMAT_VERSION
        or exporter_contract.get("file_sha256") != expected_exporter_sha256
        or format_contract != expected_format
        or target_rendering != exporter.TARGET_RENDERING_CONTRACT
        or not isinstance(source_validation, dict)
        or set(source_validation)
        != {
            "max_sequence_tokens",
            "require_exact_provider_json",
            "require_model_io",
            "require_reasoning",
            "require_request_graph_match",
        }
        or not _is_plain_int(source_validation.get("max_sequence_tokens"))
        or source_validation["max_sequence_tokens"] != MAX_SEQUENCE_TOKENS
        or source_validation.get("require_exact_provider_json") is not False
        or source_validation.get("require_model_io") is not True
        or source_validation.get("require_reasoning") is not True
        or source_validation.get("require_request_graph_match") is not True
        or config.get("capture_model_io") is not True
        or config.get("model") != direct.EXPECTED_MODEL
        or config.get("taskset_id") != corpus["taskset_id"]
        or config.get("dataset_revision") != corpus["dataset_revision"]
        or not _is_plain_int(config.get("num_rollouts"))
        or config.get("num_rollouts") != 1
        or any(
            not _is_plain_int(config.get(key)) or config.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or not isinstance(split, dict)
        or set(split) != {"policy", "split_salt", "validation_permyriad"}
        or split.get("split_salt") != split_salt
        or not _is_plain_int(split.get("validation_permyriad"))
        or split.get("validation_permyriad") != validation_permyriad
        or split.get("policy") != "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000"
        or artifacts.get("task-split.json") != observed["task-split.json"]
        or artifacts.get(exporter.TARGET_RENDERING_CONTRACT_FILENAME)
        != observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]
        or observed[exporter.TARGET_RENDERING_CONTRACT_FILENAME]["sha256"] != exporter.TARGET_RENDERING_CONTRACT_SHA256
        or artifacts.get("train/train.jsonl") != observed["train/train.jsonl"]
        or artifacts.get("validation/train.jsonl") != observed["validation/train.jsonl"]
    ):
        raise RepairFinalizationError("sft_output_contract_invalid")
    if (
        counts["input_traces"] != expected_count
        or counts.get("approved_tasks") != expected_count
        or counts["input_traces"]
        != counts.get("scored_pass_traces", 0)
        + counts.get("scored_fail_traces", 0)
        + counts.get("excluded_error_traces", 0)
        or counts["selected_traces"] != counts["selected_pass_traces"]
        or counts["selected_traces"] != counts["scored_pass_traces"]
        or counts.get("selected_fail_traces", 0) != 0
        or counts.get("selection_excluded_fail_traces", 0) != counts.get("scored_fail_traces", 0)
        or counts["emitted_rows"] != rows["total"]
        or counts.get("train_rows", 0) != rows["train"]
        or counts.get("validation_rows", 0) != rows["validation"]
        or counts.get("train_traces", 0) + counts.get("validation_traces", 0) != counts["selected_traces"]
        or counts["selected_traces"] != summary["selected_traces"]
        or counts.get("excluded_error_traces", 0) != summary["excluded_error_traces"]
    ):
        raise RepairFinalizationError("sft_output_counts_invalid")
    manifest_sources = manifest.get("source_artifacts")
    if not isinstance(manifest_sources, dict):
        raise RepairFinalizationError("sft_output_contract_invalid")
    expected_source_names = [
        "config.toml",
        "provenance.txt",
        "inputs/manifest.json",
        "inputs/source_config.toml",
        "inputs/task_file.txt",
        "inputs/image_manifest.json",
        "results.jsonl",
    ]
    if provider is not None:
        expected_source_names.append(sft_run_identity.EVAL_RUN_IDENTITY_FILENAME)
    expected_export_sources = {relative: source_artifacts[relative] for relative in expected_source_names}
    if manifest_sources != expected_export_sources:
        raise RepairFinalizationError("sft_source_artifact_mismatch")
    try:
        run_identity = sft_run_identity.validate_manifest_identity(
            manifest.get("eval_run_identity"),
            counts=counts,
        )
    except sft_run_identity.SftRunIdentityError as error:
        raise RepairFinalizationError(error.code) from error
    if provider is None:
        if run_identity is not None:
            raise RepairFinalizationError("sft_run_identity_mismatch")
    elif (
        run_identity is None
        or run_identity.get("sandbox_provider") != "sandoq"
        or run_identity.get("eval_run_identity_sha256") != provider.get("eval_run_identity_sha256")
        or run_identity.get("compatibility_sha256") != provider.get("identity_compatibility_sha256")
        or run_identity.get("artifact") != source_artifacts[sft_run_identity.EVAL_RUN_IDENTITY_FILENAME]
    ):
        raise RepairFinalizationError("sft_run_identity_mismatch")
    if run_identity is not None:
        try:
            sft_run_identity.validate_manifest_source_artifacts(
                run_identity,
                source_artifacts,
            )
        except sft_run_identity.SftRunIdentityError as error:
            raise RepairFinalizationError(error.code) from error
    return manifest, observed


def _validate_published(path: Path, allow_incomplete: bool, expected: Mapping[str, Mapping[str, int | str]]) -> None:
    expected_names = {
        "manifest.json",
        "task-split.json",
        exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train",
        "validation",
        ATTESTATION_FILENAME,
        *SELECTION_SOURCE_FILENAMES,
    }
    if allow_incomplete:
        expected_names.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    if {entry.name for entry in path.iterdir()} != expected_names:
        raise RepairFinalizationError("published_artifacts_invalid")
    for directory in (path, path / "train", path / "validation"):
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RepairFinalizationError("published_artifact_mode_invalid")
    if {entry.name for entry in (path / "train").iterdir()} != {"train.jsonl"} or {
        entry.name for entry in (path / "validation").iterdir()
    } != {"train.jsonl"}:
        raise RepairFinalizationError("published_artifacts_invalid")
    for relative, artifact in expected.items():
        target = path / relative
        metadata = target.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RepairFinalizationError("published_artifact_mode_invalid")
        _body, observed = _file_artifact(
            target,
            "published_artifact_invalid",
            capture_body=False,
        )
        if observed != artifact:
            raise RepairFinalizationError("published_artifact_digest_mismatch")


def _validate_options(options: RepairFinalizeOptions) -> None:
    if platform.machine() != "x86_64":
        raise RepairFinalizationError("x86_64_required")
    if not _is_plain_int(options.expected_count) or options.expected_count < 1:
        raise RepairFinalizationError("expected_count_invalid")
    if not _is_plain_int(options.validation_permyriad) or not 0 <= options.validation_permyriad < 10_000:
        raise RepairFinalizationError("validation_permyriad_invalid")
    if not options.split_salt or "\x00" in options.split_salt:
        raise RepairFinalizationError("split_salt_invalid")
    if not _valid_git_sha(options.expected_project_revision):
        raise RepairFinalizationError("project_revision_invalid")


def _validate_repository_call(
    validator: RepositoryValidator,
    project: Path,
    expected_revision: str,
) -> Path:
    try:
        return validator(project, expected_revision)
    except common.FinalizationError as error:
        raise RepairFinalizationError(error.code) from error


def finalize_qwen_repair_sft(
    options: RepairFinalizeOptions,
    *,
    repository_validator: RepositoryValidator = common._validate_repository,
    source_auditor: SourceAuditor = _audit_source,
    command_runner: CommandRunner = common._run_json_command,
    submodule_reader: Callable[[Path, str], dict[str, str]] = _submodule_revisions,
    runtime_validator: RuntimeValidator = _validate_runtime_origin,
) -> dict[str, Any]:
    """Validate and atomically publish an attested pass-only repair corpus."""
    _validate_options(options)
    project = _validate_repository_call(
        repository_validator,
        options.project_dir,
        options.expected_project_revision,
    )
    base_options = common.FinalizeOptions(
        project_dir=options.project_dir,
        expected_project_revision=options.expected_project_revision,
        source_root=options.source_root,
        source_dir=options.source_dir,
        expected_provenance_sha256=options.expected_provenance_sha256,
        output_root=options.output_root,
        output_dir=options.output_dir,
        expected_count=options.expected_count,
        selection="pass-only",
        validation_permyriad=options.validation_permyriad,
        split_salt=options.split_salt,
    )
    try:
        paths = common._resolve_paths(base_options)
    except common.FinalizationError as error:
        raise RepairFinalizationError(error.code) from error
    if paths.project_dir != project:
        raise RepairFinalizationError("project_path_mismatch")
    sandbox_provider = "vmvm"
    if os.path.lexists(paths.source_dir / sft_run_identity.EVAL_RUN_IDENTITY_FILENAME):
        try:
            sandbox_provider = common._source_sandbox_provider(paths.source_dir)
        except common.FinalizationError as error:
            raise RepairFinalizationError(error.code) from error
    workflow = runtime_validator(project)
    repair_selection = _load_repair_selection(
        options.repair_selection_manifest,
        options.expected_repair_selection_manifest_sha256,
        options.expected_count,
    )
    try:
        submodules = _validate_submodule_revisions(submodule_reader(project, options.expected_project_revision))
    except common.FinalizationError as error:
        raise RepairFinalizationError(error.code) from error
    _validate_selection_code(
        repair_selection,
        project,
        workflow,
        options.expected_project_revision,
        submodules,
    )
    exporter_sha256 = _file_artifact(
        workflow / "export_sft.py",
        "project_exporter_invalid",
        capture_body=False,
    )[1]["sha256"]
    staging = Path(tempfile.mkdtemp(prefix=f".{paths.output_dir.name}.repair-sft-", dir=paths.output_root))
    staged_output = staging / "corpus"
    published = False
    try:
        with _hold_source_locks(
            paths.source_dir,
            require_router_lock=True,
        ):
            locked_source_before = _locked_source_artifacts(
                paths.source_dir,
                sandbox_provider=sandbox_provider,
            )
            source_names = SOURCE_ARTIFACTS if sandbox_provider == "vmvm" else SANDOQ_SOURCE_ARTIFACTS
            if sandbox_provider == "vmvm" and (paths.source_dir / generation.RUN_BUNDLE_DIRECTORY).is_dir():
                source_names = (*source_names, *GENERATION_SOURCE_ARTIFACTS)
            source_before = {relative: locked_source_before[relative] for relative in source_names}
            audit = source_auditor(
                paths.source_dir,
                options.expected_count,
                options.expected_provenance_sha256,
                repair_selection,
            )
            if audit.get("artifacts") != source_before:
                raise RepairFinalizationError("source_audit_artifact_mismatch")
            _validate_source_audit(audit, repair_selection, options.expected_count)
            provider = audit.get("provider")
            if (provider is None) != (sandbox_provider == "vmvm"):
                raise RepairFinalizationError("source_sandbox_provider_mismatch")
            _validate_repository_call(
                repository_validator,
                paths.project_dir,
                options.expected_project_revision,
            )
            export_summary = command_runner(
                [
                    sys.executable,
                    str(workflow / "export_sft.py"),
                    str(paths.results),
                    "--output-dir",
                    str(staged_output),
                    "--selection",
                    "pass-only",
                    "--expected-count",
                    str(options.expected_count),
                    "--validation-permyriad",
                    str(options.validation_permyriad),
                    "--split-salt",
                    options.split_salt,
                    "--max-sequence-tokens",
                    str(MAX_SEQUENCE_TOKENS),
                    "--require-task-index-binding",
                ],
                paths.project_dir,
                "sft_export_failed",
            )
            manifest, output_artifacts = _validate_export_summary(
                export_summary,
                staged_output,
                options.expected_count,
                locked_source_before,
                audit["corpus"],
                options.validation_permyriad,
                options.split_salt,
                str(exporter_sha256),
                provider,
            )
            selection_copy_artifacts = {
                name: _write_exclusive(staged_output / name, body)
                for name, body in repair_selection.selection_bodies.items()
            }
            manifest_sources = manifest["source_artifacts"]
            if sandbox_provider == "vmvm":
                for relative, artifact in source_before.items():
                    if relative in manifest_sources and manifest_sources[relative] != artifact:
                        raise RepairFinalizationError("sft_source_artifact_mismatch")
                    manifest_sources[relative] = artifact
            manifest_artifact = _replace_manifest(staged_output / "manifest.json", manifest)
            output_artifacts["manifest.json"] = manifest_artifact

            attestation: dict[str, Any] = {
                "kind": ATTESTATION_KIND,
                "schema_version": (
                    GENERATION_ATTESTATION_SCHEMA_VERSION
                    if "serving_generation" in audit["routing"]
                    else ATTESTATION_SCHEMA_VERSION
                ),
                "repair_selection_manifest_sha256": repair_selection.sha256,
                "selection": {
                    "missing_or_errored_count": repair_selection.missing_or_errored_count,
                    "strict_invalid_pass_count": repair_selection.strict_invalid_pass_count,
                    "union_count": repair_selection.task_count,
                    "union_indices_sha256": repair_selection.repair_union_indices_sha256,
                    "union_task_file_sha256": repair_selection.task_file_sha256,
                },
                "source_artifacts": source_before,
                "corpus": audit["corpus"],
                "code": {
                    "repository_revision": options.expected_project_revision,
                    "submodules": submodules,
                },
            }
            if sandbox_provider == "vmvm":
                attestation.update(
                    {
                        "kind": ATTESTATION_KIND,
                        "routing": audit["routing"],
                        "schema_version": ATTESTATION_SCHEMA_VERSION,
                    }
                )
            else:
                assert isinstance(provider, dict)
                attestation.update(
                    {
                        "kind": SANDOQ_ATTESTATION_KIND,
                        "provider_transition": {
                            "cleanup_implied_successful_traces": export_summary["selected_traces"],
                            "cleanup_must_succeed": True,
                            "kind": VMVM_TO_SANDOQ_TRANSITION_KIND,
                            "repair_eval_run_identity_sha256": provider["eval_run_identity_sha256"],
                            "repair_identity_compatibility_sha256": provider["identity_compatibility_sha256"],
                            "repair_sandbox_provider": "sandoq",
                            "schema_version": 1,
                            "source_sandbox_provider": "vmvm",
                        },
                        "schema_version": SANDOQ_ATTESTATION_SCHEMA_VERSION,
                    }
                )
            attestation_artifact = _write_exclusive(
                staged_output / ATTESTATION_FILENAME,
                _json_bytes(attestation),
            )
            output_artifacts.update(selection_copy_artifacts)
            output_artifacts[ATTESTATION_FILENAME] = attestation_artifact
            for directory in (staged_output, staged_output / "train", staged_output / "validation"):
                os.chmod(directory, 0o700)
            for relative in output_artifacts:
                os.chmod(staged_output / relative, 0o600)
            migration._fsync_tree(staged_output)

            if (
                _locked_source_artifacts(
                    paths.source_dir,
                    sandbox_provider=sandbox_provider,
                )
                != locked_source_before
            ):
                raise RepairFinalizationError("source_changed_during_finalization")
            _validate_selection_unchanged(repair_selection)
            _validate_repository_call(
                repository_validator,
                paths.project_dir,
                options.expected_project_revision,
            )

            def validate_published(path: Path, allow_incomplete: bool) -> None:
                _validate_published(path, allow_incomplete, output_artifacts)

            try:
                migration._publish_directory(staged_output, paths.output_dir, validate_published)
            except migration.MigrationError as error:
                raise RepairFinalizationError("publish_failed") from error
            published = True
        summary = {
            "approved_tasks": export_summary["approved_tasks"],
            "attestation_sha256": attestation_artifact["sha256"],
            "excluded_error_traces": export_summary["excluded_error_traces"],
            "input_traces": export_summary["input_traces"],
            "manifest_sha256": manifest_artifact["sha256"],
            "rows": export_summary["rows"],
            "selected_traces": export_summary["selected_traces"],
            "selection": "pass-only",
            "status": "finalized",
        }
        if sandbox_provider == "sandoq":
            summary["eval_run_identity_sha256"] = export_summary["eval_run_identity_sha256"]
            summary["sandbox_provider"] = "sandoq"
        return summary
    finally:
        if not published and staged_output.exists():
            with suppress(OSError):
                shutil.rmtree(staged_output)
        if staging.exists():
            with suppress(OSError):
                shutil.rmtree(staging)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected-provenance-sha256", required=True)
    parser.add_argument("--repair-selection-manifest", type=Path, required=True)
    parser.add_argument("--expected-repair-selection-manifest-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--validation-permyriad", type=int, required=True)
    parser.add_argument("--split-salt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = finalize_qwen_repair_sft(
            RepairFinalizeOptions(
                project_dir=args.project_dir,
                expected_project_revision=args.expected_project_revision,
                source_root=args.source_root,
                source_dir=args.source_dir,
                expected_provenance_sha256=args.expected_provenance_sha256,
                repair_selection_manifest=args.repair_selection_manifest,
                expected_repair_selection_manifest_sha256=args.expected_repair_selection_manifest_sha256,
                output_root=args.output_root,
                output_dir=args.output_dir,
                expected_count=args.expected_count,
                validation_permyriad=args.validation_permyriad,
                split_salt=args.split_salt,
            )
        )
    except RepairFinalizationError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "finalization_failed", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
