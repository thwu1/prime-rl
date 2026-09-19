#!/usr/bin/env python3
"""Build a fail-closed one-task Kimi smoke recovery and two-source certificate."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import tomli_w
from audit_traces import (
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    _audit_trace,
    _clean_stop_problem,
    _summarize_traces,
)
from eval_run_identity import (
    load_eval_run_identity,
    validate_kimi_recovery_smoke_contract,
    validate_kimi_timeout_contract,
)
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    validate_eval_invocations,
    validate_guard_success_linkage,
)

SELECTION_SCHEMA_VERSION = 1
SELECTION_KIND = "one_task_smoke_timeout_recovery"
COMPOSITE_SCHEMA_VERSION = 3
COMPOSITE_KIND = "two_source_smoke_recovery"
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_SEQUENCE_TOKENS = 262_144
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
RECOVERY_POLICY_SUFFIXES = frozenset({".py", ".sbatch", ".sh"})
RECOVERY_POLICY_REQUIRED_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
        "user/tianhaowu/terminal_bench_vmvm/certify_trace_smoke.py",
        "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
        "user/tianhaowu/terminal_bench_vmvm/guard_success_receipt.py",
        "user/tianhaowu/terminal_bench_vmvm/inference_route_guard.py",
        "user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch",
        "user/tianhaowu/terminal_bench_vmvm/run_kimi_smoke_recovery.sbatch",
        "user/tianhaowu/terminal_bench_vmvm/run_trace_smoke_audit.sbatch",
        "user/tianhaowu/terminal_bench_vmvm/smoke_qualification.py",
        "user/tianhaowu/terminal_bench_vmvm/smoke_timeout_recovery.py",
        "user/tianhaowu/terminal_bench_vmvm/snapshot_eval_inputs.py",
        "user/tianhaowu/terminal_bench_vmvm/validate_task_approval.py",
    }
)


class SmokeRecoveryError(ValueError):
    """Recovery inputs cannot be combined without weakening an invariant."""


@dataclass(frozen=True)
class FileArtifact:
    path: Path
    sha256: str
    raw: bytes | None = None

    @property
    def record(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}


@dataclass(frozen=True)
class ManifestEntry:
    index: int
    slug: str
    raw: bytes


@dataclass(frozen=True)
class TraceRow:
    raw: bytes
    trace: dict[str, Any]


@dataclass(frozen=True)
class Selection:
    retained_index: int
    recovery_index: int
    retained_row: TraceRow
    recovery_entry: ManifestEntry
    source_rows: int
    harness_timeout_rows: int
    missing_rows: int


IdentityLoader = Callable[..., dict[str, Any]]


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


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _artifact(path: Path, *, label: str, read: bool = False) -> FileArtifact:
    try:
        if path.is_symlink():
            raise SmokeRecoveryError(f"{label}_unreadable")
        resolved = path.resolve(strict=True)
        if path.is_absolute() and str(path) != str(resolved):
            raise SmokeRecoveryError(f"{label}_path_not_canonical")
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARTIFACT_BYTES:
            raise SmokeRecoveryError(f"{label}_unreadable")
        raw = resolved.read_bytes()
        after = resolved.stat(follow_symlinks=False)
    except SmokeRecoveryError:
        raise
    except (OSError, RuntimeError) as error:
        raise SmokeRecoveryError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after) or len(raw) != after.st_size:
        raise SmokeRecoveryError(f"{label}_changed")
    return FileArtifact(
        path=resolved,
        sha256=_sha256_bytes(raw),
        raw=raw if read else None,
    )


def _artifact_from_record(value: Any, *, label: str, read: bool = False) -> FileArtifact:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(value["path"]).is_absolute()
        or not isinstance(value.get("sha256"), str)
        or SHA256_RE.fullmatch(value["sha256"]) is None
    ):
        raise SmokeRecoveryError(f"{label}_invalid")
    artifact = _artifact(Path(value["path"]), label=label, read=read)
    if artifact.record != value:
        raise SmokeRecoveryError(f"{label}_mismatch")
    return artifact


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise SmokeRecoveryError(f"{label}_invalid")
            value[key] = item
        return value

    def reject_constant(_value: str) -> None:
        raise SmokeRecoveryError(f"{label}_invalid")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except SmokeRecoveryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise SmokeRecoveryError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise SmokeRecoveryError(f"{label}_invalid")
    return value


def _strict_jsonl(raw: bytes, *, label: str) -> list[TraceRow]:
    if not raw or not raw.endswith(b"\n"):
        raise SmokeRecoveryError(f"{label}_invalid")
    rows: list[TraceRow] = []
    for line in raw.splitlines(keepends=True):
        if line in {b"\n", b"\r\n"} or not line.endswith(b"\n"):
            raise SmokeRecoveryError(f"{label}_invalid")
        rows.append(TraceRow(raw=line, trace=_strict_object(line, label=label)))
    return rows


def _manifest_entries(raw: bytes, *, expected_count: int) -> list[ManifestEntry]:
    if not raw or not raw.endswith(b"\n"):
        raise SmokeRecoveryError("task_manifest_invalid")
    entries: list[ManifestEntry] = []
    try:
        lines = raw.splitlines(keepends=True)
        for line in lines:
            decoded = line.decode("utf-8")
            stripped = decoded.strip()
            if not stripped or decoded.lstrip().startswith("#"):
                continue
            slug = stripped.split("\t", 1)[0]
            if not slug or any(character in slug for character in "\r\n"):
                raise SmokeRecoveryError("task_manifest_invalid")
            entries.append(ManifestEntry(index=len(entries), slug=slug, raw=line))
    except UnicodeDecodeError as error:
        raise SmokeRecoveryError("task_manifest_invalid") from error
    if len(entries) != expected_count or len({entry.slug for entry in entries}) != expected_count:
        raise SmokeRecoveryError("task_manifest_count_invalid")
    return entries


def _materialize_recovery_config(template_raw: bytes, task_path: Path, task_sha256: str) -> bytes:
    try:
        config = tomllib.loads(template_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmokeRecoveryError("recovery_config_template_invalid") from error
    if not isinstance(config, dict):
        raise SmokeRecoveryError("recovery_config_template_invalid")
    try:
        validate_kimi_timeout_contract(config, required_profile="recovery")
        validate_kimi_recovery_smoke_contract(config)
    except ValueError as error:
        raise SmokeRecoveryError("recovery_config_template_invalid") from error
    if config.get("num_tasks") != 1:
        raise SmokeRecoveryError("recovery_config_template_invalid")
    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        raise SmokeRecoveryError("recovery_config_template_invalid")
    taskset["task_file"] = str(task_path)
    taskset["task_file_sha256"] = task_sha256
    return tomli_w.dumps(config).encode("utf-8")


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise SmokeRecoveryError("recovery_source_invalid") from error


def _recovery_policy_files(project_root: Path) -> list[Path]:
    workflow_files = _git_output(
        project_root,
        "ls-files",
        "--",
        "user/tianhaowu/terminal_bench_vmvm",
    ).splitlines()
    vmvm_root = project_root / "environments/vmvm_tb_v2"
    vmvm_files = [
        f"environments/vmvm_tb_v2/{relative}"
        for relative in _git_output(vmvm_root, "ls-files", "--", "vmvm_tb_v2").splitlines()
    ]
    relative_files = sorted(
        relative for relative in (*workflow_files, *vmvm_files) if Path(relative).suffix in RECOVERY_POLICY_SUFFIXES
    )
    if (
        not relative_files
        or len(relative_files) != len(set(relative_files))
        or not RECOVERY_POLICY_REQUIRED_FILES.issubset(relative_files)
        or not any(relative.startswith("environments/vmvm_tb_v2/vmvm_tb_v2/") for relative in relative_files)
        or any("\x00" in relative or "\r" in relative for relative in relative_files)
    ):
        raise SmokeRecoveryError("recovery_source_invalid")
    return [project_root / relative for relative in relative_files]


def _recovery_source_binding(
    project_root: Path,
    expected_commit: str,
    source_identity: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        root = project_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SmokeRecoveryError("recovery_source_invalid") from error
    if (
        not root.is_dir()
        or not isinstance(expected_commit, str)
        or REVISION_RE.fullmatch(expected_commit) is None
        or source_identity.get("project_root") != str(root)
        or source_identity.get("prime_rl_commit") != expected_commit
        or _git_output(root, "rev-parse", "--verify", "HEAD").strip() != expected_commit
        or _git_output(root, "status", "--porcelain=v1", "--untracked-files=all").strip()
    ):
        raise SmokeRecoveryError("recovery_source_mismatch")
    vmvm_root = root / "environments/vmvm_tb_v2"
    vmvm_tree = _git_output(root, "ls-tree", expected_commit, "--", "environments/vmvm_tb_v2").strip().split()
    if (
        len(vmvm_tree) != 4
        or vmvm_tree[:2] != ["160000", "commit"]
        or _git_output(vmvm_root, "rev-parse", "--verify", "HEAD").strip() != vmvm_tree[2]
        or _git_output(vmvm_root, "status", "--porcelain=v1", "--untracked-files=all").strip()
    ):
        raise SmokeRecoveryError("recovery_source_mismatch")
    records: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for path in _recovery_policy_files(root):
        artifact = _artifact(path, label="recovery_policy_file")
        relative = path.relative_to(root).as_posix()
        records[relative] = artifact.sha256
        aggregate.update(f"{artifact.sha256}  {relative}\n".encode("utf-8"))
    return {
        "schema_version": 1,
        "project_root": str(root),
        "prime_rl_commit": expected_commit,
        "vmvm_commit": vmvm_tree[2],
        "files": records,
        "closure_sha256": aggregate.hexdigest(),
        "source_dependencies": {
            key: source_identity.get(key)
            for key in (
                "prime_rl_tree_sha256",
                "verifiers_commit",
                "verifiers_tree_sha256",
                "renderers_commit",
                "renderers_tree_sha256",
                "vmvm_tb_v2_sha256",
            )
        },
    }


def _trace_slug(trace: Mapping[str, Any]) -> str:
    task = trace.get("task")
    if not isinstance(task, dict):
        return ""
    slug = task.get("slug")
    if isinstance(slug, str) and slug:
        return slug
    name = task.get("name")
    return name.rsplit("/", 1)[-1] if isinstance(name, str) else ""


def _strict_trace_problems(trace: dict[str, Any]) -> list[str]:
    return _audit_trace(
        trace,
        require_reasoning=True,
        max_sequence_tokens=MAX_SEQUENCE_TOKENS,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        require_exact_provider_json=True,
        require_clean_stop=True,
    )


def derive_selection(manifest_raw: bytes, source_rows: list[TraceRow]) -> Selection:
    """Select one retained trace and one owed task without returning identifiers."""

    entries = _manifest_entries(manifest_raw, expected_count=2)
    if len(source_rows) not in {1, 2}:
        raise SmokeRecoveryError("source_row_count_invalid")
    index_by_slug = {entry.slug: entry.index for entry in entries}
    seen_tasks: set[str] = set()
    seen_trace_ids: set[str] = set()
    eligible: list[tuple[int, TraceRow]] = []
    timeout_indices: list[int] = []
    for row in source_rows:
        trace = row.trace
        slug = _trace_slug(trace)
        trace_id = trace.get("id")
        if (
            slug not in index_by_slug
            or slug in seen_tasks
            or not isinstance(trace_id, str)
            or not trace_id
            or trace_id in seen_trace_ids
        ):
            raise SmokeRecoveryError("source_trace_set_invalid")
        seen_tasks.add(slug)
        seen_trace_ids.add(trace_id)
        index = index_by_slug[slug]
        problems = _strict_trace_problems(trace)
        if not problems:
            eligible.append((index, row))
        elif (
            trace.get("is_completed") is True
            and trace.get("stop_condition") == "harness_timeout"
            and trace.get("errors") == []
            and _clean_stop_problem(trace) == "trace_stop_condition_infrastructure"
        ):
            timeout_indices.append(index)
        else:
            raise SmokeRecoveryError("source_trace_ineligible")
    if len(eligible) != 1 or len(timeout_indices) > 1:
        raise SmokeRecoveryError("recovery_cardinality_invalid")
    retained_index, retained_row = eligible[0]
    recovery_indices = {0, 1} - {retained_index}
    if len(recovery_indices) != 1:
        raise SmokeRecoveryError("recovery_cardinality_invalid")
    recovery_index = recovery_indices.pop()
    if timeout_indices and timeout_indices != [recovery_index]:
        raise SmokeRecoveryError("recovery_target_ambiguous")
    if len(source_rows) == 2 and timeout_indices != [recovery_index]:
        raise SmokeRecoveryError("recovery_target_not_timeout")
    if len(source_rows) == 1 and timeout_indices:
        raise SmokeRecoveryError("recovery_target_ambiguous")
    return Selection(
        retained_index=retained_index,
        recovery_index=recovery_index,
        retained_row=retained_row,
        recovery_entry=entries[recovery_index],
        source_rows=len(source_rows),
        harness_timeout_rows=len(timeout_indices),
        missing_rows=2 - len(source_rows),
    )


def _load_run(run_dir: Path, *, identity_loader: IdentityLoader) -> dict[str, Any]:
    try:
        resolved_run = run_dir.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SmokeRecoveryError("source_run_unreadable") from error
    if not resolved_run.is_dir():
        raise SmokeRecoveryError("source_run_unreadable")
    identity_artifact = _artifact(resolved_run / "eval_run_identity.json", label="source_identity")
    results_artifact = _artifact(resolved_run / "results.jsonl", label="source_results", read=True)
    receipt_artifact = _artifact(resolved_run / "route_guard_success.json", label="source_guard_receipt")
    invocations_artifact = _artifact(resolved_run / "eval_invocations.jsonl", label="source_invocations")
    try:
        envelope = identity_loader(identity_artifact.path, verify_references=True)
        receipt = load_guard_success_receipt(receipt_artifact.path)
    except (OSError, RuntimeError, ValueError) as error:
        raise SmokeRecoveryError("source_run_attestation_invalid") from error
    identity = envelope.get("identity") if isinstance(envelope, dict) else None
    identity_sha256 = envelope.get("eval_run_identity_sha256") if isinstance(envelope, dict) else None
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    if (
        not isinstance(identity, dict)
        or not isinstance(identity_sha256, str)
        or identity.get("role") != "smoke"
        or not isinstance(deployment, dict)
    ):
        raise SmokeRecoveryError("source_run_identity_invalid")
    try:
        linked = validate_guard_success_linkage(
            receipt,
            run_dir=resolved_run,
            eval_run_identity_sha256=identity_sha256,
            eval_run_role="smoke",
            eval_run_identity_file_sha256=identity_artifact.sha256,
            results_sha256=results_artifact.sha256,
            deployment_id=deployment["id"],
            deployment_spec_sha256=deployment["spec"]["sha256"],
            readiness_checkpoint=deployment["readiness_checkpoint"],
            endpoint=deployment["endpoint"],
            serving_route_generation=deployment["serving_route_generation"],
            proxy_policy=deployment["proxy_policy"],
            require_concurrency_telemetry="concurrency_telemetry" in receipt.get("artifacts", {}),
        )
        invocation, invocation_record = validate_eval_invocations(
            invocations_artifact.path,
            eval_run_identity_sha256=identity_sha256,
            eval_run_role="smoke",
        )
    except (GuardReceiptError, KeyError, TypeError) as error:
        raise SmokeRecoveryError("source_run_attestation_invalid") from error
    if (
        invocation.get("resume") is not False
        or linked.get("eval_invocations") != invocation_record
        or invocation_record != invocations_artifact.record
    ):
        raise SmokeRecoveryError("source_run_not_fresh")
    return {
        "run_dir": resolved_run,
        "identity": identity,
        "identity_sha256": identity_sha256,
        "identity_artifact": identity_artifact,
        "results_artifact": results_artifact,
        "receipt_artifact": receipt_artifact,
        "invocations_artifact": invocations_artifact,
        "rows": _strict_jsonl(results_artifact.raw or b"", label="source_results"),
    }


def _write_file(path: Path, raw: bytes, *, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _self_hashed(body: dict[str, Any], field: str) -> dict[str, Any]:
    return {**body, field: _sha256_bytes(canonical_json(body))}


def _selection_body(
    *,
    source: dict[str, Any],
    original_manifest: FileArtifact,
    recovery_task: FileArtifact,
    recovery_config_template: FileArtifact,
    recovery_config: FileArtifact,
    recovery_policy: dict[str, Any],
    recovery_run_dir: Path,
    selection: Selection,
) -> dict[str, Any]:
    identity = source["identity"]
    deployment = identity["deployment"]
    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "kind": SELECTION_KIND,
        "state": "eligible",
        "source_eval_run_identity_sha256": source["identity_sha256"],
        "counts": {
            "original_tasks": 2,
            "source_rows": selection.source_rows,
            "retained_rows": 1,
            "recovery_tasks": 1,
            "missing_rows": selection.missing_rows,
            "harness_timeout_rows": selection.harness_timeout_rows,
        },
        "retained": {
            "manifest_index": selection.retained_index,
            "trace_sha256": _sha256_bytes(selection.retained_row.raw),
        },
        "recovery": {
            "manifest_index": selection.recovery_index,
            "task_line_sha256": _sha256_bytes(selection.recovery_entry.raw),
            "run_dir": str(recovery_run_dir),
        },
        "deployment": {
            "id": deployment["id"],
            "spec": deployment["spec"],
            "readiness_checkpoint": deployment["readiness_checkpoint"],
            "endpoint": deployment["endpoint"],
            "serving_route_generation": deployment["serving_route_generation"],
            "proxy_policy": deployment["proxy_policy"],
        },
        "recovery_policy": recovery_policy,
        "artifacts": {
            "original_task_file": original_manifest.record,
            "recovery_task_file": recovery_task.record,
            "recovery_config_template": recovery_config_template.record,
            "recovery_config": recovery_config.record,
            "source_results": source["results_artifact"].record,
            "source_eval_run_identity": source["identity_artifact"].record,
            "source_eval_invocations": source["invocations_artifact"].record,
            "source_route_guard_success": source["receipt_artifact"].record,
        },
    }


def create_selection(
    source_run_dir: Path,
    original_task_file: Path,
    original_task_file_sha256: str,
    recovery_config_template: Path,
    recovery_config_template_sha256: str,
    recovery_project_root: Path,
    namespace: Path,
    *,
    identity_loader: IdentityLoader = load_eval_run_identity,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """Atomically create a one-task approval in a new recovery namespace."""

    if "RESUME_DIR" in environ:
        raise SmokeRecoveryError("resume_forbidden")
    if not isinstance(original_task_file_sha256, str) or SHA256_RE.fullmatch(original_task_file_sha256) is None:
        raise SmokeRecoveryError("task_manifest_sha256_invalid")
    original = _artifact(original_task_file, label="task_manifest", read=True)
    if original.sha256 != original_task_file_sha256:
        raise SmokeRecoveryError("task_manifest_sha256_mismatch")
    template = _artifact(recovery_config_template, label="recovery_config_template", read=True)
    if (
        not isinstance(recovery_config_template_sha256, str)
        or SHA256_RE.fullmatch(recovery_config_template_sha256) is None
        or template.sha256 != recovery_config_template_sha256
    ):
        raise SmokeRecoveryError("recovery_config_template_sha256_mismatch")
    source_run = source_run_dir.resolve(strict=True)
    lock_path = source_run / ".writer.lock"
    try:
        lock = lock_path.open("rb")
    except OSError as error:
        raise SmokeRecoveryError("source_writer_lock_unreadable") from error
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SmokeRecoveryError("source_writer_active") from error
        source = _load_run(source_run, identity_loader=identity_loader)
        task_record = source["identity"].get("inputs", {}).get("task_file")
        if (
            not isinstance(task_record, dict)
            or task_record.get("sha256") != original.sha256
            or task_record.get("count") != 2
        ):
            raise SmokeRecoveryError("source_task_manifest_mismatch")
        selection = derive_selection(original.raw or b"", source["rows"])
        source_identity = source["identity"]["source"]
        recovery_policy = _recovery_source_binding(
            recovery_project_root,
            str(source_identity.get("prime_rl_commit")),
            source_identity,
        )
        try:
            parent = namespace.parent.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise SmokeRecoveryError("recovery_namespace_parent_invalid") from error
        final_namespace = parent / namespace.name
        if namespace.is_absolute() and str(namespace) != str(final_namespace):
            raise SmokeRecoveryError("recovery_namespace_invalid")
        recovery_root = recovery_project_root.resolve(strict=True)
        if (
            os.path.lexists(final_namespace)
            or final_namespace.is_relative_to(source_run)
            or final_namespace.is_relative_to(recovery_root)
        ):
            raise SmokeRecoveryError("recovery_namespace_exists")
        temporary = Path(tempfile.mkdtemp(prefix=f".{namespace.name}.", dir=parent))
        os.chmod(temporary, 0o700)
        try:
            task_path = temporary / "approved_task.txt"
            _write_file(task_path, selection.recovery_entry.raw, mode=0o400)
            final_task_path = final_namespace / task_path.name
            recovery_task = FileArtifact(
                path=final_task_path,
                sha256=_sha256_bytes(selection.recovery_entry.raw),
                raw=selection.recovery_entry.raw,
            )
            config_raw = _materialize_recovery_config(
                template.raw or b"",
                final_task_path,
                recovery_task.sha256,
            )
            config_path = temporary / "config.toml"
            _write_file(config_path, config_raw, mode=0o400)
            recovery_config = FileArtifact(
                path=final_namespace / config_path.name,
                sha256=_sha256_bytes(config_raw),
                raw=config_raw,
            )
            original_config = _resolved_config(source["identity"], label="original_config")
            parsed_recovery_config = tomllib.loads(config_raw.decode("utf-8"))
            if canonical_json(_normalized_recovery_config(original_config)) != canonical_json(
                _normalized_recovery_config(parsed_recovery_config)
            ):
                raise SmokeRecoveryError("source_execution_mismatch")
            body = _selection_body(
                source=source,
                original_manifest=original,
                recovery_task=recovery_task,
                recovery_config_template=template,
                recovery_config=recovery_config,
                recovery_policy=recovery_policy,
                recovery_run_dir=final_namespace / "run",
                selection=selection,
            )
            attestation = _self_hashed(body, "selection_sha256")
            _write_file(
                temporary / "selection.json",
                json.dumps(attestation, indent=2, sort_keys=True).encode("utf-8") + b"\n",
                mode=0o444,
            )
            os.rename(temporary, final_namespace)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return attestation
    finally:
        lock.close()


def _load_selection(
    path: Path,
    *,
    identity_loader: IdentityLoader,
) -> tuple[dict[str, Any], Selection, dict[str, Any]]:
    artifact = _artifact(path, label="selection", read=True)
    if (
        stat.S_IMODE(artifact.path.stat(follow_symlinks=False).st_mode) != 0o444
        or artifact.path.name != "selection.json"
        or stat.S_IMODE(artifact.path.parent.stat(follow_symlinks=False).st_mode) != 0o700
    ):
        raise SmokeRecoveryError("selection_not_immutable")
    payload = _strict_object(artifact.raw or b"", label="selection")
    body = {key: value for key, value in payload.items() if key != "selection_sha256"}
    if (
        set(payload)
        != {
            "schema_version",
            "kind",
            "state",
            "source_eval_run_identity_sha256",
            "counts",
            "retained",
            "recovery",
            "deployment",
            "recovery_policy",
            "artifacts",
            "selection_sha256",
        }
        or payload.get("schema_version") != SELECTION_SCHEMA_VERSION
        or payload.get("kind") != SELECTION_KIND
        or payload.get("state") != "eligible"
        or payload.get("selection_sha256") != _sha256_bytes(canonical_json(body))
    ):
        raise SmokeRecoveryError("selection_invalid")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "original_task_file",
        "recovery_task_file",
        "recovery_config_template",
        "recovery_config",
        "source_results",
        "source_eval_run_identity",
        "source_eval_invocations",
        "source_route_guard_success",
    }:
        raise SmokeRecoveryError("selection_artifacts_invalid")
    original = _artifact_from_record(artifacts["original_task_file"], label="task_manifest", read=True)
    recovery_task = _artifact_from_record(artifacts["recovery_task_file"], label="recovery_task", read=True)
    template = _artifact_from_record(artifacts["recovery_config_template"], label="recovery_config_template", read=True)
    recovery_config = _artifact_from_record(artifacts["recovery_config"], label="recovery_config", read=True)
    recovery = payload.get("recovery")
    if (
        stat.S_IMODE(recovery_task.path.stat(follow_symlinks=False).st_mode) != 0o400
        or recovery_task.path != artifact.path.parent / "approved_task.txt"
        or stat.S_IMODE(recovery_config.path.stat(follow_symlinks=False).st_mode) != 0o400
        or recovery_config.path != artifact.path.parent / "config.toml"
        or not isinstance(recovery, dict)
        or recovery.get("run_dir") != str(artifact.path.parent / "run")
    ):
        raise SmokeRecoveryError("recovery_namespace_mismatch")
    source_identity_artifact = _artifact_from_record(artifacts["source_eval_run_identity"], label="source_identity")
    source_run = source_identity_artifact.path.parent
    source = _load_run(source_run, identity_loader=identity_loader)
    if any(
        source[name].record != artifacts[artifact_name]
        for name, artifact_name in (
            ("identity_artifact", "source_eval_run_identity"),
            ("results_artifact", "source_results"),
            ("invocations_artifact", "source_eval_invocations"),
            ("receipt_artifact", "source_route_guard_success"),
        )
    ):
        raise SmokeRecoveryError("selection_source_changed")
    selection = derive_selection(original.raw or b"", source["rows"])
    if recovery_task.raw != selection.recovery_entry.raw:
        raise SmokeRecoveryError("recovery_task_mismatch")
    expected_config = _materialize_recovery_config(
        template.raw or b"",
        recovery_task.path,
        recovery_task.sha256,
    )
    if recovery_config.raw != expected_config:
        raise SmokeRecoveryError("recovery_config_mismatch")
    source_identity = source["identity"]["source"]
    recovery_policy = payload.get("recovery_policy")
    if not isinstance(recovery_policy, dict):
        raise SmokeRecoveryError("recovery_policy_invalid")
    expected_policy = _recovery_source_binding(
        Path(str(recovery_policy.get("project_root"))),
        str(recovery_policy.get("prime_rl_commit")),
        source_identity,
    )
    if canonical_json(recovery_policy) != canonical_json(expected_policy):
        raise SmokeRecoveryError("recovery_policy_mismatch")
    original_config = _resolved_config(source["identity"], label="original_config")
    parsed_recovery_config = tomllib.loads((recovery_config.raw or b"").decode("utf-8"))
    if canonical_json(_normalized_recovery_config(original_config)) != canonical_json(
        _normalized_recovery_config(parsed_recovery_config)
    ):
        raise SmokeRecoveryError("source_execution_mismatch")
    expected_body = _selection_body(
        source=source,
        original_manifest=original,
        recovery_task=recovery_task,
        recovery_config_template=template,
        recovery_config=recovery_config,
        recovery_policy=recovery_policy,
        recovery_run_dir=Path(recovery["run_dir"]),
        selection=selection,
    )
    if canonical_json(body) != canonical_json(expected_body):
        raise SmokeRecoveryError("selection_binding_mismatch")
    return payload, selection, source


def _source_compatible(original: Mapping[str, Any], recovery: Mapping[str, Any]) -> bool:
    source_keys = (
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
        "vmvm_tb_v2_sha256",
    )
    original_source = original.get("source")
    recovery_source = recovery.get("source")
    original_deployment = original.get("deployment")
    recovery_deployment = recovery.get("deployment")
    if not all(
        isinstance(value, dict)
        for value in (original_source, recovery_source, original_deployment, recovery_deployment)
    ):
        return False
    try:
        original_execution = _normalized_execution(original)
        recovery_execution = _normalized_execution(recovery)
    except SmokeRecoveryError:
        return False
    return (
        all(original_source.get(key) == recovery_source.get(key) for key in source_keys)
        and original.get("dataset") == recovery.get("dataset")
        and original.get("contract") == recovery.get("contract")
        and original_execution == recovery_execution
        and all(
            original_deployment.get(key) == recovery_deployment.get(key)
            for key in (
                "id",
                "endpoint",
                "serving_route_generation",
                "proxy_policy",
                "spec",
                "readiness_checkpoint",
                "routing",
            )
        )
    )


def _normalized_execution(identity: Mapping[str, Any]) -> dict[str, Any]:
    execution = copy.deepcopy(identity.get("execution"))
    if not isinstance(execution, dict):
        raise SmokeRecoveryError("source_execution_mismatch")
    for key in (
        "rollout_concurrency",
        "multiplex",
        "http_max_connections",
        "http_max_keepalive_connections",
    ):
        execution.pop(key, None)
    runtime = execution.get("runtime")
    environment = execution.get("vmvm_environment")
    if not isinstance(runtime, dict) or not isinstance(environment, dict):
        raise SmokeRecoveryError("source_execution_mismatch")
    runtime.pop("session_timeout", None)
    environment.pop("lease_start_concurrency", None)
    return execution


def _resolved_config(identity: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    config = identity.get("config")
    record = config.get("resolved") if isinstance(config, dict) else None
    artifact = _artifact_from_record(record, label=label, read=True)
    try:
        parsed = tomllib.loads((artifact.raw or b"").decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SmokeRecoveryError(f"{label}_invalid") from error
    return parsed


def _normalized_recovery_config(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = json.loads(canonical_json(config))
    for key in ("output_dir", "num_tasks", "max_concurrent", "multiplex"):
        normalized.pop(key, None)
    client = normalized.get("client")
    taskset = normalized.get("taskset")
    harness = normalized.get("harness")
    timeouts = normalized.get("timeout")
    if not all(isinstance(value, dict) for value in (client, taskset, harness, timeouts)):
        raise SmokeRecoveryError("source_execution_mismatch")
    for key in ("max_connections", "max_keepalive_connections"):
        client.pop(key, None)
    for key in ("task_file", "task_file_sha256"):
        taskset.pop(key, None)
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict):
        raise SmokeRecoveryError("source_execution_mismatch")
    runtime.pop("session_timeout", None)
    timeouts.pop("rollout", None)
    return normalized


def validate_recovery_launch(
    selection_path: Path,
    output_dir: Path,
    task_file: Path,
    task_file_sha256: str,
    config_file: Path,
    config_file_sha256: str,
    *,
    project_root: Path,
    expected_prime_rl_commit: str,
    deployment_id: str,
    deployment_spec: Path,
    deployment_spec_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    proxy_info: Path,
    proxy_info_sha256: str,
    vacli_bin: str,
    vacli_max_concurrent_leases: str,
    vacli_lease_retries: str,
    vacli_max_pull_retries: str,
    vacli_image_pull_timeout_seconds: str,
    vacli_container_privileged: str,
    identity_loader: IdentityLoader = load_eval_run_identity,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """Validate the pre-launch one-task binding without disclosing its identifier."""

    if "RESUME_DIR" in environ:
        raise SmokeRecoveryError("resume_forbidden")
    payload, _, source = _load_selection(selection_path, identity_loader=identity_loader)
    recovery = payload.get("recovery")
    artifacts = payload.get("artifacts")
    deployment = payload.get("deployment")
    if not isinstance(recovery, dict) or not isinstance(artifacts, dict) or not isinstance(deployment, dict):
        raise SmokeRecoveryError("selection_invalid")
    endpoint = deployment.get("endpoint")
    if not isinstance(endpoint, dict):
        raise SmokeRecoveryError("selection_invalid")
    approved = _artifact_from_record(artifacts.get("recovery_task_file"), label="recovery_task")
    config = _artifact_from_record(artifacts.get("recovery_config"), label="recovery_config", read=True)
    spec = _artifact(deployment_spec, label="deployment_spec")
    readiness = _artifact(readiness_checkpoint, label="readiness_checkpoint")
    proxy = _artifact(proxy_info, label="proxy_info")
    try:
        resolved_task = task_file.resolve(strict=True)
        resolved_config = config_file.resolve(strict=True)
        resolved_project = project_root.resolve(strict=True)
        parent = output_dir.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SmokeRecoveryError("recovery_launch_binding_invalid") from error
    normalized_output = parent / output_dir.name
    if (
        not isinstance(task_file_sha256, str)
        or task_file_sha256 != approved.sha256
        or resolved_task != approved.path
        or config_file_sha256 != config.sha256
        or resolved_config != config.path
        or not output_dir.is_absolute()
        or str(output_dir) != str(normalized_output)
        or str(output_dir) != recovery.get("run_dir")
        or os.path.lexists(output_dir)
        or deployment.get("id") != deployment_id
        or spec.record != deployment.get("spec")
        or spec.sha256 != deployment_spec_sha256
        or readiness.record != deployment.get("readiness_checkpoint")
        or readiness.sha256 != readiness_checkpoint_sha256
        or endpoint.get("proxy_info") != proxy.record
        or proxy.sha256 != proxy_info_sha256
    ):
        raise SmokeRecoveryError("recovery_launch_binding_invalid")
    policy = payload.get("recovery_policy")
    if (
        not isinstance(policy, dict)
        or policy.get("project_root") != str(resolved_project)
        or policy.get("prime_rl_commit") != expected_prime_rl_commit
    ):
        raise SmokeRecoveryError("recovery_source_mismatch")
    observed_policy = _recovery_source_binding(
        resolved_project,
        expected_prime_rl_commit,
        source["identity"]["source"],
    )
    if canonical_json(policy) != canonical_json(observed_policy):
        raise SmokeRecoveryError("recovery_policy_mismatch")
    source_environment = source["identity"].get("execution", {}).get("vmvm_environment")
    try:
        requested_environment = {
            "vacli_bin": vacli_bin,
            "lease_retries": int(vacli_lease_retries),
            "max_pull_retries": int(vacli_max_pull_retries),
            "image_pull_timeout_sec": int(vacli_image_pull_timeout_seconds),
            "container_privileged": {"0": False, "1": True}[vacli_container_privileged],
        }
        lease_limit = int(vacli_max_concurrent_leases)
    except (KeyError, ValueError) as error:
        raise SmokeRecoveryError("recovery_vmvm_environment_invalid") from error
    integer_inputs = {
        "lease_retries": vacli_lease_retries,
        "max_pull_retries": vacli_max_pull_retries,
        "image_pull_timeout_sec": vacli_image_pull_timeout_seconds,
    }
    if (
        not isinstance(source_environment, dict)
        or any(
            type(value) is not int or value < 1
            for key, value in requested_environment.items()
            if key not in {"vacli_bin", "container_privileged"}
        )
        or any(str(requested_environment[key]) != raw for key, raw in integer_inputs.items())
        or not isinstance(vacli_bin, str)
        or not vacli_bin
        or lease_limit < 1
        or str(lease_limit) != vacli_max_concurrent_leases
        or requested_environment
        != {key: value for key, value in source_environment.items() if key != "lease_start_concurrency"}
    ):
        raise SmokeRecoveryError("recovery_vmvm_environment_mismatch")
    return {
        "ok": True,
        "state": "launch_eligible",
        "counts": {"tasks": 1, "expected_traces": 1},
        "selection_sha256": payload["selection_sha256"],
    }


def _validate_combined_rows(
    original_manifest: FileArtifact,
    selection: Selection,
    recovery_task: FileArtifact,
    recovery_results: FileArtifact,
) -> tuple[bytes, dict[str, Any], TraceRow]:
    entries = _manifest_entries(original_manifest.raw or b"", expected_count=2)
    recovery_entries = _manifest_entries(recovery_task.raw or b"", expected_count=1)
    recovery_rows = _strict_jsonl(recovery_results.raw or b"", label="recovery_results")
    if len(recovery_rows) != 1 or recovery_entries[0].raw != selection.recovery_entry.raw:
        raise SmokeRecoveryError("recovery_cardinality_invalid")
    recovery_row = recovery_rows[0]
    retained_slug = _trace_slug(selection.retained_row.trace)
    recovery_slug = _trace_slug(recovery_row.trace)
    retained_trace_id = selection.retained_row.trace.get("id")
    recovery_trace_id = recovery_row.trace.get("id")
    if (
        retained_slug == recovery_slug
        or recovery_slug != recovery_entries[0].slug
        or not isinstance(retained_trace_id, str)
        or not retained_trace_id
        or not isinstance(recovery_trace_id, str)
        or not recovery_trace_id
        or retained_trace_id == recovery_trace_id
    ):
        raise SmokeRecoveryError("composite_disjointness_invalid")
    rows_by_slug = {
        retained_slug: selection.retained_row,
        recovery_slug: recovery_row,
    }
    if set(rows_by_slug) != {entry.slug for entry in entries}:
        raise SmokeRecoveryError("composite_task_union_invalid")
    ordered_rows = [rows_by_slug[entry.slug] for entry in entries]
    summary, failed = _summarize_traces(
        (row.trace for row in ordered_rows),
        expected_slugs={entry.slug for entry in entries},
        expected_count=2,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        aggregate_only=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        require_exact_provider_json=True,
        max_sequence_tokens=MAX_SEQUENCE_TOKENS,
        require_clean_stop=True,
    )
    if failed or summary.get("traces") != 2 or summary.get("tasks") != 2:
        raise SmokeRecoveryError("composite_trace_audit_failed")
    return b"".join(row.raw for row in ordered_rows), summary, recovery_row


def _artifact_record_from_v1(payload: Mapping[str, Any], name: str) -> dict[str, str]:
    artifacts = payload.get("artifacts")
    record = artifacts.get(name) if isinstance(artifacts, dict) else None
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise SmokeRecoveryError("recovery_checkpoint_invalid")
    return {"path": str(record.get("path")), "sha256": str(record.get("sha256"))}


def _load_recovery_checkpoint(
    checkpoint_path: Path,
    *,
    identity_loader: IdentityLoader,
) -> tuple[FileArtifact, dict[str, Any], dict[str, Any], dict[str, Any]]:
    from smoke_qualification import (
        Artifact,
        SmokeQualificationError,
        validate_historical_readiness,
        validate_v1_smoke,
    )

    checkpoint = _artifact(checkpoint_path, label="recovery_checkpoint", read=True)
    if stat.S_IMODE(checkpoint.path.stat(follow_symlinks=False).st_mode) != 0o444:
        raise SmokeRecoveryError("recovery_checkpoint_not_immutable")
    payload = _strict_object(checkpoint.raw or b"", label="recovery_checkpoint")
    identity_record = _artifact_record_from_v1(payload, "eval_run_identity")
    identity_artifact = _artifact_from_record(identity_record, label="recovery_identity")
    try:
        envelope = identity_loader(identity_artifact.path, verify_references=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise SmokeRecoveryError("recovery_identity_invalid") from error
    identity = envelope.get("identity") if isinstance(envelope, dict) else None
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    if not isinstance(identity, dict) or identity.get("role") != "smoke" or not isinstance(deployment, dict):
        raise SmokeRecoveryError("recovery_identity_invalid")
    spec_record = deployment.get("spec")
    readiness_record = deployment.get("readiness_checkpoint")
    if not isinstance(spec_record, dict) or not isinstance(readiness_record, dict):
        raise SmokeRecoveryError("recovery_deployment_invalid")
    spec = _artifact_from_record(spec_record, label="recovery_deployment_spec")
    readiness = _artifact_from_record(readiness_record, label="recovery_readiness", read=True)
    try:
        generation, policy = validate_historical_readiness(
            Artifact(readiness.path, readiness.sha256, readiness.raw),
            deployment_id=deployment["id"],
            deployment_spec=Artifact(spec.path, spec.sha256),
            endpoint=deployment["endpoint"],
            model="Kimi-K3",
        )
        validated, evidence = validate_v1_smoke(
            Artifact(checkpoint.path, checkpoint.sha256, checkpoint.raw),
            deployment_id=deployment["id"],
            deployment_spec=Artifact(spec.path, spec.sha256),
            readiness=Artifact(readiness.path, readiness.sha256, readiness.raw),
            endpoint=deployment["endpoint"],
            generation=generation,
            proxy_policy=policy,
            model="Kimi-K3",
            identity_loader=identity_loader,
        )
    except (OSError, RuntimeError, SmokeQualificationError, ValueError) as error:
        raise SmokeRecoveryError("recovery_checkpoint_invalid") from error
    audit_policy = validated.get("audit_policy")
    recovery_config = _resolved_config(identity, label="recovery_config")
    try:
        validate_kimi_timeout_contract(recovery_config, required_profile="recovery")
        validate_kimi_recovery_smoke_contract(recovery_config)
    except ValueError as error:
        raise SmokeRecoveryError("recovery_timeout_contract_invalid") from error
    if (
        not isinstance(audit_policy, dict)
        or audit_policy.get("expected_traces") != 1
        or audit_policy.get("require_exact_provider_json") is not True
        or validated.get("counts", {}).get("traces") != 1
        or identity.get("inputs", {}).get("task_file", {}).get("count") != 1
        or recovery_config.get("num_tasks") != 1
    ):
        raise SmokeRecoveryError("recovery_checkpoint_policy_invalid")
    return checkpoint, validated, identity, evidence


def _composite_body(
    *,
    selection_artifact: FileArtifact,
    selection_payload: dict[str, Any],
    selection: Selection,
    original_source: dict[str, Any],
    recovery_checkpoint: FileArtifact,
    recovery_payload: dict[str, Any],
    recovery_identity: dict[str, Any],
    recovery_evidence: dict[str, Any],
    original_manifest: FileArtifact,
    recovery_task: FileArtifact,
    recovery_results: FileArtifact,
    combined_results: FileArtifact,
    summary: dict[str, Any],
) -> dict[str, Any]:
    deployment = recovery_identity["deployment"]
    source_artifacts = selection_payload["artifacts"]
    recovery_artifacts = recovery_payload["artifacts"]
    return {
        "schema_version": COMPOSITE_SCHEMA_VERSION,
        "kind": COMPOSITE_KIND,
        "state": "passed",
        "ok": True,
        "deployment_id": deployment["id"],
        "deployment_spec_sha256": deployment["spec"]["sha256"],
        "model": "Kimi-K3",
        "endpoint": deployment["endpoint"],
        "serving_route_generation": deployment["serving_route_generation"],
        "proxy_policy": deployment["proxy_policy"],
        "audit_policy": {
            "expected_traces": 2,
            "rollouts_per_task": 1,
            "require_clean_stop": True,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": {
                "provider_route": "/chat/completions",
                "request_model": "Kimi-K3",
                "response_model": "Kimi-K3",
                "request_reasoning_effort": "max",
                "request_chat_template_kwargs": {
                    "enable_thinking": True,
                    "preserve_thinking": True,
                },
            },
            "require_request_graph_match": True,
            "require_exact_provider_json": True,
            "require_token_data": False,
            "require_logprobs": False,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        },
        "counts": {
            "traces": summary["traces"],
            "tasks": summary["tasks"],
            "sampled_tokens": summary["sampled_tokens"],
            "model_io_turns": summary["model_io_turns"],
            "source_runs": 2,
            "retained_rows": 1,
            "recovery_rows": 1,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "ordering": [
            {
                "manifest_index": 0,
                "source": "original" if selection.retained_index == 0 else "recovery",
            },
            {
                "manifest_index": 1,
                "source": "original" if selection.retained_index == 1 else "recovery",
            },
        ],
        "sources": {
            "original": {
                "eval_run_identity_sha256": original_source["identity_sha256"],
                "manifest_index": selection.retained_index,
                "route_guard_success": source_artifacts["source_route_guard_success"],
                "readiness_checkpoint": original_source["identity"]["deployment"]["readiness_checkpoint"],
            },
            "recovery": {
                "eval_run_identity_sha256": recovery_payload["eval_run_identity_sha256"],
                "manifest_index": selection.recovery_index,
                "route_guard_success": recovery_artifacts["route_guard_success"],
                "readiness_checkpoint": recovery_identity["deployment"]["readiness_checkpoint"],
            },
        },
        "artifacts": {
            "results": combined_results.record,
            "original_task_file": original_manifest.record,
            "recovery_task_file": recovery_task.record,
            "recovery_config_template": source_artifacts["recovery_config_template"],
            "recovery_config": source_artifacts["recovery_config"],
            "selection_attestation": selection_artifact.record,
            "original_results": source_artifacts["source_results"],
            "original_eval_run_identity": source_artifacts["source_eval_run_identity"],
            "original_eval_invocations": source_artifacts["source_eval_invocations"],
            "original_route_guard_success": source_artifacts["source_route_guard_success"],
            "recovery_smoke_checkpoint": recovery_checkpoint.record,
            "recovery_results": recovery_artifacts["results"],
            "recovery_eval_run_identity": recovery_artifacts["eval_run_identity"],
            "recovery_eval_invocations": recovery_artifacts["eval_invocations"],
            "recovery_route_guard_success": recovery_artifacts["route_guard_success"],
        },
        "evaluator_evidence": recovery_evidence,
    }


def _prepare_composite(
    selection_path: Path,
    recovery_checkpoint_path: Path,
    combined_results: FileArtifact,
    *,
    identity_loader: IdentityLoader,
) -> tuple[dict[str, Any], FileArtifact, dict[str, Any], dict[str, Any]]:
    selection_artifact = _artifact(selection_path, label="selection", read=True)
    selection_payload, selection, original_source = _load_selection(
        selection_path,
        identity_loader=identity_loader,
    )
    recovery_checkpoint, recovery_payload, recovery_identity, recovery_evidence = _load_recovery_checkpoint(
        recovery_checkpoint_path,
        identity_loader=identity_loader,
    )
    if not _source_compatible(original_source["identity"], recovery_identity):
        raise SmokeRecoveryError("source_execution_mismatch")
    recovery_policy = selection_payload.get("recovery_policy")
    recovery_source = recovery_identity.get("source")
    if (
        not isinstance(recovery_policy, dict)
        or not isinstance(recovery_source, dict)
        or recovery_source.get("project_root") != recovery_policy.get("project_root")
        or recovery_source.get("prime_rl_commit") != recovery_policy.get("prime_rl_commit")
    ):
        raise SmokeRecoveryError("recovery_source_mismatch")
    original_config = _resolved_config(original_source["identity"], label="original_config")
    recovery_config = _resolved_config(recovery_identity, label="recovery_config")
    if canonical_json(_normalized_recovery_config(original_config)) != canonical_json(
        _normalized_recovery_config(recovery_config)
    ):
        raise SmokeRecoveryError("source_execution_mismatch")
    recovery_run_dir = Path(str(selection_payload.get("recovery", {}).get("run_dir")))
    composite_dir = combined_results.path.parent
    if (
        not recovery_run_dir.is_absolute()
        or recovery_run_dir != recovery_checkpoint.path.parent
        or recovery_run_dir == original_source["run_dir"]
        or combined_results.path != composite_dir / "results.jsonl"
        or composite_dir.is_relative_to(original_source["run_dir"])
        or composite_dir.is_relative_to(recovery_run_dir)
        or composite_dir.is_relative_to(selection_artifact.path.parent)
    ):
        raise SmokeRecoveryError("recovery_namespace_mismatch")
    if recovery_identity["inputs"]["task_file"].get("sha256") != selection_payload["artifacts"][
        "recovery_task_file"
    ].get("sha256"):
        raise SmokeRecoveryError("recovery_task_identity_mismatch")
    original_manifest = _artifact_from_record(
        selection_payload["artifacts"]["original_task_file"], label="task_manifest", read=True
    )
    recovery_task = _artifact_from_record(
        selection_payload["artifacts"]["recovery_task_file"], label="recovery_task", read=True
    )
    recovery_results = _artifact_from_record(
        recovery_payload["artifacts"]["results"], label="recovery_results", read=True
    )
    expected_raw, summary, _ = _validate_combined_rows(
        original_manifest,
        selection,
        recovery_task,
        recovery_results,
    )
    if combined_results.raw != expected_raw:
        raise SmokeRecoveryError("composite_results_mismatch")
    body = _composite_body(
        selection_artifact=selection_artifact,
        selection_payload=selection_payload,
        selection=selection,
        original_source=original_source,
        recovery_checkpoint=recovery_checkpoint,
        recovery_payload=recovery_payload,
        recovery_identity=recovery_identity,
        recovery_evidence=recovery_evidence,
        original_manifest=original_manifest,
        recovery_task=recovery_task,
        recovery_results=recovery_results,
        combined_results=combined_results,
        summary=summary,
    )
    return body, recovery_checkpoint, recovery_identity, recovery_evidence


def create_composite(
    selection_path: Path,
    recovery_checkpoint_path: Path,
    namespace: Path,
    *,
    identity_loader: IdentityLoader = load_eval_run_identity,
) -> dict[str, Any]:
    """Atomically materialize the original-order two-trace composite."""

    selection_payload, selection, _ = _load_selection(selection_path, identity_loader=identity_loader)
    recovery_checkpoint, recovery_payload, _, _ = _load_recovery_checkpoint(
        recovery_checkpoint_path,
        identity_loader=identity_loader,
    )
    original_manifest = _artifact_from_record(
        selection_payload["artifacts"]["original_task_file"], label="task_manifest", read=True
    )
    recovery_task = _artifact_from_record(
        selection_payload["artifacts"]["recovery_task_file"], label="recovery_task", read=True
    )
    recovery_results = _artifact_from_record(
        recovery_payload["artifacts"]["results"], label="recovery_results", read=True
    )
    combined_raw, _, _ = _validate_combined_rows(
        original_manifest,
        selection,
        recovery_task,
        recovery_results,
    )
    try:
        parent = namespace.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SmokeRecoveryError("composite_namespace_parent_invalid") from error
    final_namespace = parent / namespace.name
    if namespace.is_absolute() and str(namespace) != str(final_namespace):
        raise SmokeRecoveryError("composite_namespace_invalid")
    if os.path.lexists(final_namespace):
        raise SmokeRecoveryError("composite_namespace_exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{namespace.name}.", dir=parent))
    os.chmod(temporary, 0o700)
    try:
        temporary_results = temporary / "results.jsonl"
        _write_file(temporary_results, combined_raw, mode=0o600)
        final_results = FileArtifact(
            path=final_namespace / "results.jsonl",
            sha256=_sha256_bytes(combined_raw),
            raw=combined_raw,
        )
        body, _, _, _ = _prepare_composite(
            selection_path,
            recovery_checkpoint.path,
            final_results,
            identity_loader=identity_loader,
        )
        checkpoint = _self_hashed(body, "smoke_checkpoint_sha256")
        _write_file(
            temporary / "smoke_checkpoint.json",
            json.dumps(checkpoint, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            mode=0o444,
        )
        os.rename(temporary, final_namespace)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return checkpoint


def validate_composite_qualification(
    qualification_path: Path,
    qualification_sha256: str,
    *,
    deployment_id: str,
    deployment_spec_sha256: str,
    readiness_record: dict[str, str],
    endpoint: dict[str, Any],
    generation: dict[str, Any],
    proxy_policy: dict[str, Any],
    identity_loader: IdentityLoader = load_eval_run_identity,
) -> tuple[dict[str, Any], FileArtifact, dict[str, Any]]:
    """Rebuild and validate a schema-3 composite against both source runs."""

    checkpoint = _artifact(qualification_path, label="composite_checkpoint", read=True)
    if (
        checkpoint.sha256 != qualification_sha256
        or stat.S_IMODE(checkpoint.path.stat(follow_symlinks=False).st_mode) != 0o444
        or checkpoint.path.name != "smoke_checkpoint.json"
        or stat.S_IMODE(checkpoint.path.parent.stat(follow_symlinks=False).st_mode) != 0o700
    ):
        raise SmokeRecoveryError("composite_checkpoint_invalid")
    payload = _strict_object(checkpoint.raw or b"", label="composite_checkpoint")
    body = {key: value for key, value in payload.items() if key != "smoke_checkpoint_sha256"}
    if (
        payload.get("schema_version") != COMPOSITE_SCHEMA_VERSION
        or payload.get("kind") != COMPOSITE_KIND
        or payload.get("state") != "passed"
        or payload.get("ok") is not True
        or payload.get("smoke_checkpoint_sha256") != _sha256_bytes(canonical_json(body))
    ):
        raise SmokeRecoveryError("composite_checkpoint_invalid")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SmokeRecoveryError("composite_artifacts_invalid")
    results = _artifact_from_record(artifacts.get("results"), label="composite_results", read=True)
    if (
        results.path != checkpoint.path.parent / "results.jsonl"
        or stat.S_IMODE(results.path.stat(follow_symlinks=False).st_mode) != 0o600
    ):
        raise SmokeRecoveryError("composite_results_invalid")
    selection = _artifact_from_record(artifacts.get("selection_attestation"), label="selection", read=True)
    recovery = _artifact_from_record(artifacts.get("recovery_smoke_checkpoint"), label="recovery_checkpoint", read=True)
    expected_body, recovery_checkpoint, recovery_identity, evidence = _prepare_composite(
        selection.path,
        recovery.path,
        results,
        identity_loader=identity_loader,
    )
    if canonical_json(body) != canonical_json(expected_body):
        raise SmokeRecoveryError("composite_binding_mismatch")
    deployment = recovery_identity["deployment"]
    if (
        payload.get("deployment_id") != deployment_id
        or payload.get("deployment_spec_sha256") != deployment_spec_sha256
        or deployment.get("readiness_checkpoint") != readiness_record
        or deployment.get("endpoint") != endpoint
        or deployment.get("serving_route_generation") != generation
        or deployment.get("proxy_policy") != proxy_policy
    ):
        raise SmokeRecoveryError("composite_target_mismatch")
    return evidence, recovery_checkpoint, generation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--source-run-dir", type=Path, required=True)
    select.add_argument("--original-task-file", type=Path, required=True)
    select.add_argument("--original-task-file-sha256", required=True)
    select.add_argument("--recovery-config-template", type=Path, required=True)
    select.add_argument("--recovery-config-template-sha256", required=True)
    select.add_argument("--recovery-project-root", type=Path, required=True)
    select.add_argument("--namespace", type=Path, required=True)
    verify = subparsers.add_parser("verify-launch")
    verify.add_argument("--selection", type=Path, required=True)
    verify.add_argument("--output-dir", type=Path, required=True)
    verify.add_argument("--task-file", type=Path, required=True)
    verify.add_argument("--task-file-sha256", required=True)
    verify.add_argument("--config-file", type=Path, required=True)
    verify.add_argument("--config-file-sha256", required=True)
    verify.add_argument("--project-root", type=Path, required=True)
    verify.add_argument("--expected-prime-rl-commit", required=True)
    verify.add_argument("--deployment-id", required=True)
    verify.add_argument("--deployment-spec", type=Path, required=True)
    verify.add_argument("--deployment-spec-sha256", required=True)
    verify.add_argument("--readiness-checkpoint", type=Path, required=True)
    verify.add_argument("--readiness-checkpoint-sha256", required=True)
    verify.add_argument("--proxy-info", type=Path, required=True)
    verify.add_argument("--proxy-info-sha256", required=True)
    verify.add_argument("--vacli-bin", required=True)
    verify.add_argument("--vacli-max-concurrent-leases", required=True)
    verify.add_argument("--vacli-lease-retries", required=True)
    verify.add_argument("--vacli-max-pull-retries", required=True)
    verify.add_argument("--vacli-image-pull-timeout-seconds", required=True)
    verify.add_argument("--vacli-container-privileged", required=True)
    combine = subparsers.add_parser("combine")
    combine.add_argument("--selection", type=Path, required=True)
    combine.add_argument("--recovery-checkpoint", type=Path, required=True)
    combine.add_argument("--namespace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            payload = create_selection(
                args.source_run_dir,
                args.original_task_file,
                args.original_task_file_sha256,
                args.recovery_config_template,
                args.recovery_config_template_sha256,
                args.recovery_project_root,
                args.namespace,
            )
            output = {
                "ok": True,
                "state": payload["state"],
                "counts": payload["counts"],
                "selection_sha256": payload["selection_sha256"],
            }
        elif args.command == "verify-launch":
            output = validate_recovery_launch(
                args.selection,
                args.output_dir,
                args.task_file,
                args.task_file_sha256,
                args.config_file,
                args.config_file_sha256,
                project_root=args.project_root,
                expected_prime_rl_commit=args.expected_prime_rl_commit,
                deployment_id=args.deployment_id,
                deployment_spec=args.deployment_spec,
                deployment_spec_sha256=args.deployment_spec_sha256,
                readiness_checkpoint=args.readiness_checkpoint,
                readiness_checkpoint_sha256=args.readiness_checkpoint_sha256,
                proxy_info=args.proxy_info,
                proxy_info_sha256=args.proxy_info_sha256,
                vacli_bin=args.vacli_bin,
                vacli_max_concurrent_leases=args.vacli_max_concurrent_leases,
                vacli_lease_retries=args.vacli_lease_retries,
                vacli_max_pull_retries=args.vacli_max_pull_retries,
                vacli_image_pull_timeout_seconds=args.vacli_image_pull_timeout_seconds,
                vacli_container_privileged=args.vacli_container_privileged,
            )
        else:
            payload = create_composite(
                args.selection,
                args.recovery_checkpoint,
                args.namespace,
            )
            output = {
                "ok": True,
                "state": payload["state"],
                "counts": payload["counts"],
                "smoke_checkpoint_sha256": payload["smoke_checkpoint_sha256"],
            }
    except (OSError, RuntimeError, ValueError) as error:
        code = str(error)
        if not code or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_:" for character in code):
            code = "recovery_failed"
        print(f"smoke_recovery_error:{code}", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
