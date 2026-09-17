#!/usr/bin/env python3
"""Run a restart-safe, fail-closed train of singleton Kimi TB4 shard waves.

The controller submits at most four fresh singleton shards at a time.  It does
not submit the next wave until every job in the current wave is recorded by
Slurm as ``COMPLETED`` with exit code zero and its independently guarded output
passes the shard validator.  Controller metadata contains only aggregate
counts, hashes, shard ordinals, and Slurm job IDs; task identifiers and trace
content never leave their existing private artifacts.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from audit_tb4_results import EXPECTED_UNSUPPORTED_TASKS, _score_problem, _unsupported_trace_problems
from audit_traces import (
    DEFAULT_MAX_SEQUENCE_TOKENS,
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    TraceJSONLError,
    _audit_trace,
    _iter_traces,
    _task_slug,
)
from eval_run_identity import EvalIdentityError, load_eval_run_identity
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    stable_sha256_file,
    validate_eval_invocations,
    validate_guard_success_linkage,
)
from inference_route_guard import (
    RouteBinding,
    RouteGuardError,
    load_route_binding,
    verify_live_route_generation,
)
from launch_tb4_shard_wave import (
    DEFAULT_SBATCH,
    DEPLOYMENT_RE,
    EXPECTED_MODEL,
    EXPECTED_VMVM_ENV,
    MAX_WAVE_SIZE,
    PinnedArtifact,
    WaveLaunchError,
    WaveSubmissionInterrupted,
    WaveSubmissionOutcomeUnknown,
    _encode_environment,
    _job_environment,
    _parse_job_id,
    _require_tmux_launcher,
    _selected_dataset,
    _stable_artifact,
    _validate_dataset,
    _validate_generation_bindings,
    launch_wave,
    validate_clean_project,
)
from tb4_shard_workflow import (
    CertifiedShard,
    PlannedShard,
    ShardWorkflowError,
    _certify_shard,
    canonical_json,
    load_plan,
)

SCHEMA_VERSION = 1
CONTROLLER_TYPE = "terminal_bench_vmvm_tb4_singleton_wave_train"
DEFAULT_POLL_INTERVAL_SECONDS = 15.0
MIN_POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_INTERVAL_SECONDS = 60.0
SCHEDULER_TIMEOUT_SECONDS = 30.0
MAX_CONSECUTIVE_SCHEDULER_FAILURES = 3
MAX_PRIVATE_JSON_BYTES = 64 * 1024 * 1024
SQUEUE = "/usr/bin/squeue"
SACCT = "/usr/bin/sacct"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
TOKEN_RE = re.compile(r"[0-9a-f]{16}")
UTC_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
SAFE_ERROR_RE = re.compile(r"[a-z0-9_]{1,96}")
ACTIVE_SLURM_STATES = frozenset(
    {
        "CONFIGURING",
        "COMPLETING",
        "PENDING",
        "REQUEUED",
        "REQUEUE_FED",
        "RESIZING",
        "RUNNING",
        "SIGNALING",
        "STAGE_OUT",
        "STOPPED",
        "SUSPENDED",
    }
)
FAILED_SLURM_STATES = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
        "TIMEOUT",
    }
)


class WaveTrainError(ValueError):
    """The wave train cannot continue without weakening a required invariant."""


class SchedulerQueryUnavailable(WaveTrainError):
    """A bounded scheduler read failed without proving a job outcome."""


class ControllerInterrupted(WaveTrainError):
    """A signal requested a stop at a safe submission boundary."""


@dataclass(frozen=True)
class WaveTrainConfig:
    controller_root: Path
    project_dir: Path
    project_revision: str
    plan_path: Path
    plan_sha256: str
    deployment_id: str
    deployment_spec_path: Path
    deployment_spec_sha256: str
    readiness_path: Path
    readiness_sha256: str
    proxy_info_path: Path
    proxy_info_sha256: str
    smoke_checkpoint_path: Path
    smoke_checkpoint_sha256: str
    dataset_revision: str | None = None
    dataset_archive_path: Path | None = None
    dataset_archive_sha256: str | None = None
    dataset_content_sha256: str | None = None
    first_shard_index: int = 0
    shard_count: int | None = None
    wave_size: int = MAX_WAVE_SIZE
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class PreparedTrain:
    config: WaveTrainConfig
    controller_root: Path
    project: Path
    plan_artifact: PinnedArtifact
    plan: dict[str, Any]
    shards: tuple[PlannedShard, ...]
    selected_indices: tuple[int, ...]
    revisions: dict[str, str]
    deployment_spec: PinnedArtifact
    readiness: PinnedArtifact
    proxy_info: PinnedArtifact
    smoke: PinnedArtifact
    dataset_path: Path
    dataset_archive: PinnedArtifact | None
    generation_sha256: str
    route_binding: RouteBinding


@dataclass(frozen=True)
class SchedulerObservation:
    state: str
    exit_code: str | None


@dataclass(frozen=True)
class ShardEvidence:
    shard_index: int
    slurm_job_id: str
    supported: bool
    solved: int | None
    artifacts: dict[str, str]
    eval_run_identity_sha256: str
    guard_success_receipt_sha256: str
    route_generation_sha256: str


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
LaunchCallback = Callable[
    [PreparedTrain, int, tuple[int, ...], Path, Callable[[], bool]],
    dict[str, Any],
]
WaveLoader = Callable[[PreparedTrain, int, tuple[int, ...], Path, bool], dict[str, Any]]
SchedulerReader = Callable[[Sequence[str]], dict[str, SchedulerObservation]]
ShardValidator = Callable[[PreparedTrain, PlannedShard, Mapping[str, Any]], ShardEvidence]
RouteVerifier = Callable[[PreparedTrain], None]
SubmissionLookup = Callable[[str, str], str | None]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_error(value: str) -> str:
    return value if SAFE_ERROR_RE.fullmatch(value) is not None else "controller_operation_failed"


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WaveTrainError("controller_metadata_invalid")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise WaveTrainError("controller_metadata_invalid")


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _stable_private_bytes(path: Path, *, label: str) -> tuple[Path, bytes]:
    try:
        if path.is_symlink():
            raise WaveTrainError(f"{label}_invalid")
        resolved = path.resolve(strict=True)
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600:
            raise WaveTrainError(f"{label}_not_private")
        if before.st_size > MAX_PRIVATE_JSON_BYTES:
            raise WaveTrainError(f"{label}_too_large")
        raw = resolved.read_bytes()
        after = resolved.stat(follow_symlinks=False)
    except WaveTrainError:
        raise
    except (OSError, RuntimeError) as error:
        raise WaveTrainError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after) or len(raw) != after.st_size:
        raise WaveTrainError(f"{label}_changed")
    return resolved, raw


def _load_private_json(path: Path, *, label: str, hash_key: str) -> tuple[dict[str, Any], str]:
    _resolved, raw = _stable_private_bytes(path, label=label)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except WaveTrainError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WaveTrainError(f"{label}_invalid") from error
    if not isinstance(value, dict) or hash_key not in value:
        raise WaveTrainError(f"{label}_invalid")
    digest = value.get(hash_key)
    body = {key: item for key, item in value.items() if key != hash_key}
    if (
        not isinstance(digest, str)
        or SHA256_RE.fullmatch(digest) is None
        or digest != _sha256_bytes(canonical_json(body))
    ):
        raise WaveTrainError(f"{label}_invalid")
    return value, _sha256_bytes(raw)


def _private_payload(value: Mapping[str, Any], *, hash_key: str) -> tuple[dict[str, Any], bytes]:
    body = dict(value)
    body.pop(hash_key, None)
    envelope = {**body, hash_key: _sha256_bytes(canonical_json(body))}
    try:
        raw = (
            json.dumps(
                envelope,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise WaveTrainError("controller_metadata_invalid") from error
    return envelope, raw


def _write_once_private_json(path: Path, value: Mapping[str, Any], *, hash_key: str) -> dict[str, Any]:
    envelope, raw = _private_payload(value, hash_key=hash_key)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except FileExistsError:
        _existing_path, existing_raw = _stable_private_bytes(path, label=path.stem)
        if existing_raw != raw:
            raise WaveTrainError(f"{path.stem}_already_exists_different") from None
    except OSError as error:
        raise WaveTrainError("controller_metadata_write_failed") from error
    return envelope


def _replace_private_json(path: Path, value: Mapping[str, Any], *, hash_key: str) -> dict[str, Any]:
    envelope, raw = _private_payload(value, hash_key=hash_key)
    temporary_name: str | None = None
    try:
        if path.exists() or path.is_symlink():
            _stable_private_bytes(path, label=path.stem)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
        _fsync_directory(path.parent)
    except OSError as error:
        raise WaveTrainError("controller_metadata_write_failed") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return envelope


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _controller_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".controller.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            existing_flags = os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                existing_flags |= os.O_NOFOLLOW
            descriptor = os.open(lock_path, existing_flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600:
            raise WaveTrainError("controller_lock_invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise WaveTrainError("controller_already_running") from error
    except WaveTrainError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise WaveTrainError("controller_lock_invalid") from error
    assert descriptor is not None
    try:
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or UTC_TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _normalize_slurm_state(value: str) -> str:
    return value.strip().split(maxsplit=1)[0].removesuffix("+").upper()


def query_scheduler(
    job_ids: Sequence[str],
    *,
    runner: CommandRunner = subprocess.run,
) -> dict[str, SchedulerObservation]:
    """Read exact top-level Slurm job states without scheduler client libraries."""

    requested = tuple(job_ids)
    if (
        not requested
        or len(set(requested)) != len(requested)
        or any(SLURM_JOB_ID_RE.fullmatch(job_id) is None for job_id in requested)
    ):
        raise WaveTrainError("scheduler_job_ids_invalid")
    joined = ",".join(requested)
    try:
        queued = runner(
            [SQUEUE, "--noheader", f"--jobs={joined}", "--format=%A|%T"],
            check=False,
            capture_output=True,
            text=True,
            timeout=SCHEDULER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SchedulerQueryUnavailable("scheduler_query_unavailable") from error
    if queued.returncode != 0 or len(queued.stdout) > 1024 * 1024:
        raise SchedulerQueryUnavailable("scheduler_query_unavailable")
    observations: dict[str, SchedulerObservation] = {}
    requested_set = set(requested)
    for raw_line in queued.stdout.splitlines():
        if not raw_line.strip():
            continue
        fields = [field.strip() for field in raw_line.strip().split("|")]
        if len(fields) != 2 or fields[0] not in requested_set or fields[0] in observations:
            raise WaveTrainError("scheduler_response_invalid")
        state = _normalize_slurm_state(fields[1])
        if state not in ACTIVE_SLURM_STATES:
            raise WaveTrainError("scheduler_response_invalid")
        observations[fields[0]] = SchedulerObservation(state=state, exit_code=None)

    missing = [job_id for job_id in requested if job_id not in observations]
    if missing:
        try:
            accounted = runner(
                [
                    SACCT,
                    "--noheader",
                    "--parsable2",
                    "--allocations",
                    f"--jobs={','.join(missing)}",
                    "--format=JobIDRaw,State,ExitCode",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=SCHEDULER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SchedulerQueryUnavailable("scheduler_query_unavailable") from error
        if accounted.returncode != 0 or len(accounted.stdout) > 1024 * 1024:
            raise SchedulerQueryUnavailable("scheduler_query_unavailable")
        missing_set = set(missing)
        for raw_line in accounted.stdout.splitlines():
            if not raw_line.strip():
                continue
            fields = [field.strip() for field in raw_line.strip().split("|")]
            if len(fields) != 3 or fields[0] not in missing_set or fields[0] in observations:
                raise WaveTrainError("scheduler_response_invalid")
            state = _normalize_slurm_state(fields[1])
            if state not in ACTIVE_SLURM_STATES | FAILED_SLURM_STATES | {"COMPLETED"}:
                raise WaveTrainError("scheduler_response_invalid")
            exit_code = fields[2].strip()
            if not re.fullmatch(r"[0-9]+:[0-9]+", exit_code):
                raise WaveTrainError("scheduler_response_invalid")
            observations[fields[0]] = SchedulerObservation(state=state, exit_code=exit_code)
    if set(observations) != requested_set:
        raise SchedulerQueryUnavailable("scheduler_job_missing")
    return {job_id: observations[job_id] for job_id in requested}


def lookup_submission_job(
    job_name: str,
    submitted_at: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str | None:
    """Resolve one interrupted ``sbatch`` by its persisted random job name."""

    if re.fullmatch(r"tb4-shard-[0-9]{3,}-[0-9a-f]{16}", job_name) is None or not _valid_timestamp(submitted_at):
        raise WaveTrainError("submission_lookup_invalid")
    commands = (
        [SQUEUE, "--noheader", f"--name={job_name}", "--format=%A|%j"],
        [
            SACCT,
            "--noheader",
            "--parsable2",
            "--allocations",
            f"--name={job_name}",
            f"--starttime={submitted_at[:10]}",
            "--format=JobIDRaw,JobName",
        ],
    )
    matches: set[str] = set()
    for command in commands:
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=SCHEDULER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SchedulerQueryUnavailable("submission_lookup_unavailable") from error
        if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
            raise SchedulerQueryUnavailable("submission_lookup_unavailable")
        for raw_line in result.stdout.splitlines():
            if not raw_line.strip():
                continue
            fields = [field.strip() for field in raw_line.strip().split("|")]
            if len(fields) != 2 or SLURM_JOB_ID_RE.fullmatch(fields[0]) is None or fields[1] != job_name:
                raise WaveTrainError("submission_lookup_response_invalid")
            matches.add(fields[0])
    if len(matches) > 1:
        raise WaveTrainError("submission_lookup_not_unique")
    return next(iter(matches), None)


def _validate_config(config: WaveTrainConfig) -> None:
    if REVISION_RE.fullmatch(config.project_revision) is None:
        raise WaveTrainError("project_revision_invalid")
    if SHA256_RE.fullmatch(config.plan_sha256) is None:
        raise WaveTrainError("plan_sha256_invalid")
    for label, digest in (
        ("deployment_spec", config.deployment_spec_sha256),
        ("readiness_checkpoint", config.readiness_sha256),
        ("proxy_info", config.proxy_info_sha256),
        ("smoke_checkpoint", config.smoke_checkpoint_sha256),
    ):
        if SHA256_RE.fullmatch(digest) is None:
            raise WaveTrainError(f"{label}_sha256_invalid")
    if DEPLOYMENT_RE.fullmatch(config.deployment_id) is None:
        raise WaveTrainError("deployment_id_invalid")
    if (
        type(config.first_shard_index) is not int
        or config.first_shard_index < 0
        or (config.shard_count is not None and (type(config.shard_count) is not int or config.shard_count < 1))
        or type(config.wave_size) is not int
        or not 1 <= config.wave_size <= MAX_WAVE_SIZE
        or isinstance(config.poll_interval_seconds, bool)
        or not isinstance(config.poll_interval_seconds, (int, float))
        or not math.isfinite(config.poll_interval_seconds)
        or not MIN_POLL_INTERVAL_SECONDS <= config.poll_interval_seconds <= MAX_POLL_INTERVAL_SECONDS
    ):
        raise WaveTrainError("controller_bounds_invalid")
    archive_values = (
        config.dataset_archive_path,
        config.dataset_archive_sha256,
        config.dataset_content_sha256,
    )
    if (config.dataset_revision is not None) == any(value is not None for value in archive_values):
        raise WaveTrainError("dataset_authority_invalid")
    if config.dataset_revision is not None:
        if REVISION_RE.fullmatch(config.dataset_revision) is None:
            raise WaveTrainError("dataset_revision_invalid")
    elif (
        any(value is None for value in archive_values)
        or SHA256_RE.fullmatch(str(config.dataset_archive_sha256)) is None
        or SHA256_RE.fullmatch(str(config.dataset_content_sha256)) is None
    ):
        raise WaveTrainError("dataset_archive_invalid")


def prepare_train(
    config: WaveTrainConfig,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> PreparedTrain:
    """Resolve and validate every immutable controller input before use."""

    _validate_config(config)
    if "RESUME_DIR" in os.environ:
        raise WaveTrainError("resume_forbidden")
    try:
        if config.controller_root.is_symlink():
            raise WaveTrainError("controller_root_invalid")
        project = config.project_dir.resolve(strict=True)
        controller_root = config.controller_root.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise WaveTrainError("controller_path_invalid") from error
    try:
        controller_root.relative_to(project)
    except ValueError:
        pass
    else:
        raise WaveTrainError("controller_root_inside_project")

    try:
        plan_artifact = _stable_artifact(config.plan_path, config.plan_sha256, label="plan")
        if stat.S_IMODE(plan_artifact.path.stat().st_mode) != 0o600:
            raise WaveTrainError("plan_not_private")
        plan, shards = load_plan(plan_artifact.path)
    except (OSError, WaveLaunchError, ShardWorkflowError) as error:
        raise WaveTrainError("plan_invalid") from error
    if plan.get("shard_size") != 1 or any(shard.task_count != 1 for shard in shards):
        raise WaveTrainError("singleton_plan_required")
    stop = len(shards) if config.shard_count is None else config.first_shard_index + config.shard_count
    if config.first_shard_index >= len(shards) or stop > len(shards):
        raise WaveTrainError("shard_selection_invalid")
    selected_indices = tuple(range(config.first_shard_index, stop))

    try:
        revisions = validate_clean_project(project, runner=command_runner)
    except WaveLaunchError as error:
        raise WaveTrainError("project_invalid") from error
    if revisions.get("prime_rl") != config.project_revision:
        raise WaveTrainError("project_revision_mismatch")
    try:
        deployment_spec = _stable_artifact(
            config.deployment_spec_path,
            config.deployment_spec_sha256,
            label="deployment_spec",
        )
        readiness = _stable_artifact(
            config.readiness_path,
            config.readiness_sha256,
            label="readiness_checkpoint",
            load_bytes=True,
        )
        proxy_info = _stable_artifact(
            config.proxy_info_path,
            config.proxy_info_sha256,
            label="proxy_info",
        )
        smoke = _stable_artifact(
            config.smoke_checkpoint_path,
            config.smoke_checkpoint_sha256,
            label="smoke_checkpoint",
            load_bytes=True,
        )
        generation_sha256 = _validate_generation_bindings(
            deployment_id=config.deployment_id,
            deployment_spec=deployment_spec,
            readiness=readiness,
            proxy_info=proxy_info,
            smoke=smoke,
        )
    except WaveLaunchError as error:
        raise WaveTrainError("deployment_chain_invalid") from error

    dataset_archive: PinnedArtifact | None = None
    if config.dataset_archive_path is not None:
        try:
            dataset_archive = _stable_artifact(
                config.dataset_archive_path,
                str(config.dataset_archive_sha256),
                label="dataset_archive",
            )
        except WaveLaunchError as error:
            raise WaveTrainError("dataset_archive_invalid") from error
    selected_shards = tuple(shards[index] for index in selected_indices)
    try:
        dataset_path, _configs = _selected_dataset(selected_shards)
        _validate_dataset(
            shards=selected_shards,
            dataset_revision=config.dataset_revision,
            dataset_archive=dataset_archive,
            dataset_content_sha256=config.dataset_content_sha256,
            runner=command_runner,
        )
        route_binding = load_route_binding(
            deployment_id=config.deployment_id,
            deployment_spec=deployment_spec.path,
            deployment_spec_sha256=deployment_spec.sha256,
            readiness_checkpoint=readiness.path,
            readiness_checkpoint_sha256=readiness.sha256,
            proxy_info=proxy_info.path,
            proxy_info_sha256=proxy_info.sha256,
            expected_model=EXPECTED_MODEL,
        )
    except (WaveLaunchError, RouteGuardError) as error:
        raise WaveTrainError("controller_preflight_failed") from error
    if _sha256_bytes(canonical_json(route_binding.route_generation)) != generation_sha256:
        raise WaveTrainError("route_generation_mismatch")
    return PreparedTrain(
        config=config,
        controller_root=controller_root,
        project=project,
        plan_artifact=plan_artifact,
        plan=plan,
        shards=shards,
        selected_indices=selected_indices,
        revisions=revisions,
        deployment_spec=deployment_spec,
        readiness=readiness,
        proxy_info=proxy_info,
        smoke=smoke,
        dataset_path=dataset_path,
        dataset_archive=dataset_archive,
        generation_sha256=generation_sha256,
        route_binding=route_binding,
    )


def _dataset_record(prepared: PreparedTrain) -> dict[str, Any]:
    config = prepared.config
    if config.dataset_revision is not None:
        return {"kind": "git_revision", "revision": config.dataset_revision}
    assert prepared.dataset_archive is not None
    return {
        "kind": "archive",
        "archive_sha256": prepared.dataset_archive.sha256,
        "content_sha256": config.dataset_content_sha256,
    }


def _train_body(prepared: PreparedTrain) -> dict[str, Any]:
    config = prepared.config
    return {
        "schema_version": SCHEMA_VERSION,
        "controller_type": CONTROLLER_TYPE,
        "project": {
            "path": str(prepared.project),
            "revision": config.project_revision,
            "revisions": prepared.revisions,
        },
        "plan": {
            "path": str(prepared.plan_artifact.path),
            "sha256": prepared.plan_artifact.sha256,
            "plan_sha256": prepared.plan["plan_sha256"],
        },
        "selection": {
            "first_shard_index": prepared.selected_indices[0],
            "shard_count": len(prepared.selected_indices),
            "wave_size": config.wave_size,
        },
        "deployment": {
            "id": config.deployment_id,
            "spec": {
                "path": str(prepared.deployment_spec.path),
                "sha256": prepared.deployment_spec.sha256,
            },
            "readiness_checkpoint": {
                "path": str(prepared.readiness.path),
                "sha256": prepared.readiness.sha256,
            },
            "proxy_info": {
                "path": str(prepared.proxy_info.path),
                "sha256": prepared.proxy_info.sha256,
            },
            "smoke_checkpoint": {
                "path": str(prepared.smoke.path),
                "sha256": prepared.smoke.sha256,
            },
            "route_generation_sha256": prepared.generation_sha256,
            "model": EXPECTED_MODEL,
        },
        "dataset": _dataset_record(prepared),
        "poll_interval_seconds": float(config.poll_interval_seconds),
    }


def _initial_state(train_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "train_sha256": train_sha256,
        "state": "ready",
        "next_position": 0,
        "current_wave": None,
        "completed_waves": [],
        "failure": None,
        "updated_at": _now(),
    }


def _ensure_controller_root(prepared: PreparedTrain) -> None:
    root = prepared.controller_root
    try:
        if root.is_symlink():
            raise WaveTrainError("controller_root_invalid")
        if not root.exists():
            root.parent.mkdir(parents=True, exist_ok=True)
            try:
                root.mkdir(mode=0o700)
            except FileExistsError:
                pass
        root = root.resolve(strict=True)
        mode = stat.S_IMODE(root.stat(follow_symlinks=False).st_mode)
        if not root.is_dir() or mode != 0o700:
            raise WaveTrainError("controller_root_not_private")
    except WaveTrainError:
        raise
    except (OSError, RuntimeError) as error:
        raise WaveTrainError("controller_root_invalid") from error


def _initialize_or_load(prepared: PreparedTrain) -> tuple[dict[str, Any], dict[str, Any]]:
    root = prepared.controller_root.resolve(strict=True)
    expected_body = _train_body(prepared)
    train_path = root / "train.json"
    state_path = root / "state.json"
    train_exists = train_path.exists() or train_path.is_symlink()
    state_exists = state_path.exists() or state_path.is_symlink()
    if not train_exists and not state_exists:
        try:
            existing_names = {path.name for path in root.iterdir()}
        except OSError as error:
            raise WaveTrainError("controller_root_invalid") from error
        if existing_names != {".controller.lock"}:
            raise WaveTrainError("controller_root_not_empty")
        train = _write_once_private_json(train_path, expected_body, hash_key="train_sha256")
        state = _replace_private_json(
            state_path,
            _initial_state(train["train_sha256"]),
            hash_key="state_sha256",
        )
        return train, state
    if train_exists and not state_exists:
        train, _train_file_sha256 = _load_private_json(
            train_path,
            label="train_metadata",
            hash_key="train_sha256",
        )
        allowed_names = {".controller.lock", "train.json"}
        try:
            unexpected = {
                path.name
                for path in root.iterdir()
                if path.name not in allowed_names
                and not (path.name.startswith(".state.json.") and path.name.endswith(".tmp"))
            }
        except OSError as error:
            raise WaveTrainError("controller_root_invalid") from error
        if {key: value for key, value in train.items() if key != "train_sha256"} != expected_body or unexpected:
            raise WaveTrainError("controller_metadata_incomplete")
        state = _replace_private_json(
            state_path,
            _initial_state(train["train_sha256"]),
            hash_key="state_sha256",
        )
        return train, state
    if train_exists != state_exists:
        raise WaveTrainError("controller_metadata_incomplete")
    train, _train_file_sha256 = _load_private_json(
        train_path,
        label="train_metadata",
        hash_key="train_sha256",
    )
    if {key: value for key, value in train.items() if key != "train_sha256"} != expected_body:
        raise WaveTrainError("train_spec_mismatch")
    state, _state_file_sha256 = _load_private_json(
        state_path,
        label="controller_state",
        hash_key="state_sha256",
    )
    _validate_state(prepared, train, state)
    return train, state


def _wave_root(prepared: PreparedTrain, wave_number: int) -> Path:
    return prepared.controller_root / f"wave-{wave_number:03d}"


def _expected_wave_indices(prepared: PreparedTrain, position: int) -> tuple[int, ...]:
    stop = min(position + prepared.config.wave_size, len(prepared.selected_indices))
    return prepared.selected_indices[position:stop]


def _validate_current_wave(
    prepared: PreparedTrain,
    value: Any,
    *,
    expected_number: int,
    expected_position: int,
) -> dict[str, Any]:
    expected_indices = _expected_wave_indices(prepared, expected_position)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "wave_number",
            "phase",
            "shard_indices",
            "output_root",
            "wave_sha256",
            "jobs",
        }
        or type(value.get("wave_number")) is not int
        or value.get("wave_number") != expected_number
        or value.get("phase") not in {"intent", "submitted"}
        or not isinstance(value.get("shard_indices"), list)
        or any(type(index) is not int for index in value["shard_indices"])
        or value.get("shard_indices") != list(expected_indices)
        or value.get("output_root") != str(_wave_root(prepared, expected_number))
    ):
        raise WaveTrainError("controller_state_invalid")
    jobs = value.get("jobs")
    if value["phase"] == "intent":
        if value.get("wave_sha256") is not None or jobs != []:
            raise WaveTrainError("controller_state_invalid")
    else:
        if (
            not isinstance(value.get("wave_sha256"), str)
            or SHA256_RE.fullmatch(value["wave_sha256"]) is None
            or not isinstance(jobs, list)
            or len(jobs) != len(expected_indices)
        ):
            raise WaveTrainError("controller_state_invalid")
        for expected_index, job in zip(expected_indices, jobs, strict=True):
            if (
                not isinstance(job, dict)
                or set(job) != {"shard_index", "slurm_job_id"}
                or job.get("shard_index") != expected_index
                or not isinstance(job.get("slurm_job_id"), str)
                or SLURM_JOB_ID_RE.fullmatch(job["slurm_job_id"]) is None
            ):
                raise WaveTrainError("controller_state_invalid")
    return value


def _validate_state(
    prepared: PreparedTrain,
    train: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    expected_keys = {
        "schema_version",
        "train_sha256",
        "state",
        "next_position",
        "current_wave",
        "completed_waves",
        "failure",
        "updated_at",
        "state_sha256",
    }
    if (
        set(state) != expected_keys
        or state.get("schema_version") != SCHEMA_VERSION
        or state.get("train_sha256") != train.get("train_sha256")
        or state.get("state") not in {"ready", "launching", "observing", "interrupted", "failed", "complete"}
        or type(state.get("next_position")) is not int
        or not 0 <= state["next_position"] <= len(prepared.selected_indices)
        or not _valid_timestamp(state.get("updated_at"))
        or not isinstance(state.get("completed_waves"), list)
    ):
        raise WaveTrainError("controller_state_invalid")
    position = 0
    for number, record in enumerate(state["completed_waves"]):
        indices = _expected_wave_indices(prepared, position)
        receipt_path = _wave_root(prepared, number) / "completion.json"
        completion = record.get("completion") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record)
            != {
                "wave_number",
                "shard_indices",
                "completion",
                "job_count",
                "supported_count",
                "unsupported_count",
                "solved_count",
            }
            or type(record.get("wave_number")) is not int
            or record.get("wave_number") != number
            or not isinstance(record.get("shard_indices"), list)
            or any(type(index) is not int for index in record["shard_indices"])
            or record.get("shard_indices") != list(indices)
            or not isinstance(completion, dict)
            or set(completion) != {"path", "sha256"}
            or completion.get("path") != str(receipt_path)
            or not isinstance(completion.get("sha256"), str)
            or SHA256_RE.fullmatch(completion["sha256"]) is None
            or type(record.get("job_count")) is not int
            or record.get("job_count") != len(indices)
            or type(record.get("supported_count")) is not int
            or type(record.get("unsupported_count")) is not int
            or type(record.get("solved_count")) is not int
            or record["supported_count"] + record["unsupported_count"] != len(indices)
            or not 0 <= record["solved_count"] <= record["supported_count"]
        ):
            raise WaveTrainError("controller_state_invalid")
        position += len(indices)
    if state["next_position"] != position:
        raise WaveTrainError("controller_state_invalid")
    current = state.get("current_wave")
    if current is not None:
        _validate_current_wave(
            prepared,
            current,
            expected_number=len(state["completed_waves"]),
            expected_position=position,
        )
    run_state = state["state"]
    failure = state.get("failure")
    if run_state == "failed":
        if not isinstance(failure, str) or SAFE_ERROR_RE.fullmatch(failure) is None:
            raise WaveTrainError("controller_state_invalid")
    elif failure is not None:
        raise WaveTrainError("controller_state_invalid")
    if run_state == "complete":
        if current is not None or position != len(prepared.selected_indices):
            raise WaveTrainError("controller_state_invalid")
    elif run_state == "ready":
        if current is not None or position >= len(prepared.selected_indices):
            raise WaveTrainError("controller_state_invalid")
    elif run_state in {"launching", "observing"}:
        if current is None or current["phase"] != ("intent" if run_state == "launching" else "submitted"):
            raise WaveTrainError("controller_state_invalid")
    elif run_state == "interrupted":
        if position >= len(prepared.selected_indices) and current is None:
            raise WaveTrainError("controller_state_invalid")


def _state_body(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "state_sha256"}


def _save_state(prepared: PreparedTrain, state: Mapping[str, Any]) -> dict[str, Any]:
    body = _state_body(state)
    body["updated_at"] = _now()
    saved = _replace_private_json(
        prepared.controller_root / "state.json",
        body,
        hash_key="state_sha256",
    )
    train, _ = _load_private_json(
        prepared.controller_root / "train.json",
        label="train_metadata",
        hash_key="train_sha256",
    )
    _validate_state(prepared, train, saved)
    return saved


def _expected_job_environment(
    prepared: PreparedTrain,
    shard: PlannedShard,
    output_dir: Path,
) -> bytes:
    return _encode_environment(
        _job_environment(
            project_dir=prepared.project,
            project_revision=prepared.config.project_revision,
            shard=shard,
            output_dir=output_dir,
            deployment_id=prepared.config.deployment_id,
            deployment_spec=prepared.deployment_spec,
            readiness=prepared.readiness,
            proxy_info=prepared.proxy_info,
            smoke=prepared.smoke,
            dataset_revision=prepared.config.dataset_revision,
            dataset_archive=prepared.dataset_archive,
            dataset_content_sha256=prepared.config.dataset_content_sha256,
        )
    )


def _load_wave_metadata(
    prepared: PreparedTrain,
    wave_number: int,
    indices: tuple[int, ...],
    output_root: Path,
    allow_recovering: bool,
) -> dict[str, Any]:
    expected_root = _wave_root(prepared, wave_number)
    try:
        root_mode = stat.S_IMODE(output_root.stat(follow_symlinks=False).st_mode)
    except OSError as error:
        raise WaveTrainError("wave_metadata_invalid") from error
    if output_root != expected_root or output_root.is_symlink() or not output_root.is_dir() or root_mode != 0o700:
        raise WaveTrainError("wave_metadata_invalid")
    value, _file_sha256 = _load_private_json(
        output_root / "wave.json",
        label="wave_metadata",
        hash_key="wave_sha256",
    )
    expected_keys = {
        "schema_version",
        "state",
        "dry_run",
        "plan",
        "project",
        "deployment",
        "dataset",
        "vmvm_environment",
        "wave_size",
        "jobs",
        "wave_sha256",
    }
    allowed_states = {"submitted", "submitting", "submission_interrupted"} if allow_recovering else {"submitted"}
    expected_deployment = {
        "id": prepared.config.deployment_id,
        "spec_sha256": prepared.deployment_spec.sha256,
        "readiness_checkpoint_sha256": prepared.readiness.sha256,
        "proxy_info_sha256": prepared.proxy_info.sha256,
        "smoke_checkpoint_sha256": prepared.smoke.sha256,
        "route_generation_sha256": prepared.generation_sha256,
        "model": EXPECTED_MODEL,
    }
    if (
        set(value) != expected_keys
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("state") not in allowed_states
        or value.get("dry_run") is not False
        or value.get("plan")
        != {
            "path": str(prepared.plan_artifact.path),
            "sha256": prepared.plan_artifact.sha256,
            "plan_sha256": prepared.plan["plan_sha256"],
        }
        or value.get("project") != {"path": str(prepared.project), "revisions": prepared.revisions}
        or value.get("deployment") != expected_deployment
        or value.get("dataset") != _dataset_record(prepared)
        or value.get("vmvm_environment") != EXPECTED_VMVM_ENV
        or type(value.get("wave_size")) is not int
        or value.get("wave_size") != len(indices)
        or not isinstance(value.get("jobs"), list)
        or len(value["jobs"]) != len(indices)
    ):
        raise WaveTrainError("wave_metadata_invalid")
    submission_phase = 0
    for index, job in zip(indices, value["jobs"], strict=True):
        shard = prepared.shards[index]
        output_dir = output_root / f"shard-{index:03d}-attempt-001"
        environment_path = output_root / f"shard-{index:03d}.env"
        submitted_at = job.get("submission_started_at") if isinstance(job, dict) else None
        submission_token = job.get("submission_token") if isinstance(job, dict) else None
        slurm_job_id = job.get("slurm_job_id") if isinstance(job, dict) else None
        if (
            _valid_timestamp(submitted_at)
            and isinstance(submission_token, str)
            and TOKEN_RE.fullmatch(submission_token) is not None
            and isinstance(slurm_job_id, str)
            and SLURM_JOB_ID_RE.fullmatch(slurm_job_id) is not None
        ):
            job_phase = 0
        elif (
            value.get("state") in {"submitting", "submission_interrupted"}
            and _valid_timestamp(submitted_at)
            and isinstance(submission_token, str)
            and TOKEN_RE.fullmatch(submission_token) is not None
            and slurm_job_id is None
        ):
            job_phase = 1
        elif (
            value.get("state") in {"submitting", "submission_interrupted"}
            and submitted_at is None
            and submission_token is None
            and slurm_job_id is None
        ):
            job_phase = 2
        else:
            raise WaveTrainError("wave_metadata_invalid")
        if job_phase < submission_phase or (job_phase == 1 and submission_phase == 1):
            raise WaveTrainError("wave_metadata_invalid")
        submission_phase = job_phase
        if (
            not isinstance(job, dict)
            or set(job)
            != {
                "shard_index",
                "task_count",
                "config_sha256",
                "task_manifest_sha256",
                "environment",
                "output_dir",
                "submission_started_at",
                "submission_token",
                "slurm_job_id",
            }
            or type(job.get("shard_index")) is not int
            or job.get("shard_index") != index
            or type(job.get("task_count")) is not int
            or job.get("task_count") != 1
            or job.get("config_sha256") != shard.config_sha256
            or job.get("task_manifest_sha256") != shard.task_manifest_sha256
            or job.get("output_dir") != str(output_dir)
        ):
            raise WaveTrainError("wave_metadata_invalid")
        expected_raw = _expected_job_environment(prepared, shard, output_dir)
        environment = job.get("environment")
        if (
            not isinstance(environment, dict)
            or set(environment) != {"path", "sha256"}
            or environment.get("path") != str(environment_path)
            or environment.get("sha256") != _sha256_bytes(expected_raw)
        ):
            raise WaveTrainError("wave_environment_invalid")
        resolved_environment, observed_raw = _stable_private_bytes(
            environment_path,
            label="wave_environment",
        )
        if resolved_environment != environment_path or observed_raw != expected_raw:
            raise WaveTrainError("wave_environment_invalid")
    if value["state"] == "submitted" and submission_phase != 0:
        raise WaveTrainError("wave_metadata_invalid")
    recorded_job_ids = [job["slurm_job_id"] for job in value["jobs"] if job["slurm_job_id"] is not None]
    if len(recorded_job_ids) != len(set(recorded_job_ids)):
        raise WaveTrainError("wave_metadata_invalid")
    return value


def _expected_dataset_identity(prepared: PreparedTrain) -> dict[str, Any]:
    config = prepared.config
    if config.dataset_revision is not None:
        return {
            "kind": "git_revision",
            "path": str(prepared.dataset_path),
            "revision": config.dataset_revision,
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
        }
    assert prepared.dataset_archive is not None
    return {
        "kind": "archive",
        "path": str(prepared.dataset_path),
        "revision": None,
        "archive": {
            "path": str(prepared.dataset_archive.path),
            "sha256": prepared.dataset_archive.sha256,
        },
        "content_sha256": config.dataset_content_sha256,
    }


def _read_manifest_sources(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "inputs/manifest.json"
    try:
        if path.is_symlink():
            raise WaveTrainError("shard_inputs_manifest_invalid")
        raw = path.read_bytes()
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except WaveTrainError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WaveTrainError("shard_inputs_manifest_invalid") from error
    if not isinstance(value, dict):
        raise WaveTrainError("shard_inputs_manifest_invalid")
    return value


def _validate_trace_semantics(certified: CertifiedShard) -> tuple[bool, int | None]:
    try:
        rows = list(_iter_traces(certified.results))
    except (OSError, TraceJSONLError) as error:
        raise WaveTrainError("shard_trace_audit_failed") from error
    if len(rows) != 1:
        raise WaveTrainError("shard_trace_audit_failed")
    row = rows[0]
    slug = _task_slug(row)
    if slug not in certified.spec.tasks:
        raise WaveTrainError("shard_trace_audit_failed")
    if slug in EXPECTED_UNSUPPORTED_TASKS:
        if _unsupported_trace_problems(row, slug):
            raise WaveTrainError("shard_trace_audit_failed")
        return False, None
    problems = _audit_trace(
        row,
        require_reasoning=True,
        max_sequence_tokens=DEFAULT_MAX_SEQUENCE_TOKENS,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
    )
    if row.get("is_completed") is not True:
        problems.append("supported_trace_not_completed")
    stop_condition = row.get("stop_condition")
    if not isinstance(stop_condition, str) or not stop_condition.strip() or stop_condition == "error":
        problems.append("supported_trace_stop_condition_invalid")
    score, score_problem = _score_problem(row)
    if score_problem is not None:
        problems.append(score_problem)
    if problems or score not in {0.0, 1.0}:
        raise WaveTrainError("shard_trace_audit_failed")
    return True, int(score)


def validate_completed_shard(
    prepared: PreparedTrain,
    shard: PlannedShard,
    job: Mapping[str, Any],
) -> ShardEvidence:
    """Validate one completed singleton without returning task-bearing data."""

    if (
        not {"shard_index", "slurm_job_id", "output_dir"}.issubset(job)
        or job.get("shard_index") != shard.index
        or not isinstance(job.get("slurm_job_id"), str)
        or SLURM_JOB_ID_RE.fullmatch(job["slurm_job_id"]) is None
    ):
        raise WaveTrainError("shard_job_metadata_invalid")
    expected_output = Path(str(job["output_dir"]))
    if not expected_output.is_absolute():
        raise WaveTrainError("shard_output_invalid")
    try:
        output_dir = expected_output.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WaveTrainError("shard_output_missing") from error
    if output_dir != expected_output or not output_dir.is_dir() or output_dir.is_symlink():
        raise WaveTrainError("shard_output_invalid")
    writer_lock = output_dir / ".writer.lock"
    try:
        writer_stat = writer_lock.stat(follow_symlinks=False)
    except OSError as error:
        raise WaveTrainError("shard_writer_lock_invalid") from error
    if writer_lock.is_symlink() or not stat.S_ISREG(writer_stat.st_mode) or stat.S_IMODE(writer_stat.st_mode) != 0o600:
        raise WaveTrainError("shard_writer_lock_invalid")
    receipt_path = output_dir / "route_guard_success.json"
    try:
        certified = _certify_shard(
            receipt_path,
            {shard.task_manifest_sha256: shard},
            expected_semantics_sha256=prepared.plan["base_config"]["semantics_sha256"],
        )
    except (OSError, ShardWorkflowError) as error:
        raise WaveTrainError("shard_guarded_artifacts_invalid") from error
    if (
        certified.spec.index != shard.index
        or certified.run_dir != output_dir
        or certified.results_count != 1
        or certified.success_receipt != receipt_path
        or certified.route_generation_sha256 != prepared.generation_sha256
        or certified.endpoint_binding_sha256 != _sha256_bytes(canonical_json(prepared.route_binding.endpoint))
    ):
        raise WaveTrainError("shard_guarded_artifacts_mismatch")
    semantics = certified.identity_semantics
    source = semantics.get("source")
    deployment = semantics.get("deployment")
    if (
        not isinstance(source, dict)
        or source.get("project_root") != str(prepared.project)
        or source.get("prime_rl_commit") != prepared.config.project_revision
        or source.get("verifiers_commit") != prepared.revisions.get("verifiers")
        or source.get("renderers_commit") != prepared.revisions.get("renderers")
        or semantics.get("dataset") != _expected_dataset_identity(prepared)
        or not isinstance(deployment, dict)
        or deployment.get("id") != prepared.config.deployment_id
        or deployment.get("spec_sha256") != prepared.deployment_spec.sha256
        or deployment.get("routing") != {"deployment_id": None, "headers": {}}
        or deployment.get("proxy_policy") != prepared.route_binding.proxy_policy
    ):
        raise WaveTrainError("shard_identity_mismatch")

    try:
        identity_path, identity_file_sha256 = stable_sha256_file(
            output_dir / "eval_run_identity.json",
            label="eval_run_identity",
        )
        envelope = load_eval_run_identity(identity_path, verify_references=True)
        identity = envelope["identity"]
        manifest = _read_manifest_sources(output_dir)
        config_record = manifest.get("config")
        task_record = manifest.get("task_file")
        if (
            not isinstance(config_record, dict)
            or set(config_record) != {"source", "snapshot", "sha256"}
            or config_record.get("source") != str(shard.config)
            or config_record.get("sha256") != shard.config_sha256
            or not isinstance(task_record, dict)
            or set(task_record) != {"source", "snapshot", "sha256"}
            or task_record.get("source") != str(shard.task_manifest)
            or task_record.get("sha256") != shard.task_manifest_sha256
        ):
            raise WaveTrainError("shard_input_source_mismatch")
        receipt = load_guard_success_receipt(receipt_path)
        artifacts = receipt["artifacts"]
        if "concurrency_telemetry" not in artifacts:
            raise WaveTrainError("shard_concurrency_telemetry_missing")
        invocation, invocation_artifact = validate_eval_invocations(
            Path(artifacts["eval_invocations"]["path"]),
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            eval_run_role="tb4",
        )
        if invocation.get("slurm_job_id") != job["slurm_job_id"]:
            raise WaveTrainError("shard_slurm_job_id_mismatch")
        deployment_identity = identity["deployment"]
        if (
            deployment_identity.get("id") != prepared.config.deployment_id
            or deployment_identity.get("spec")
            != {
                "path": str(prepared.deployment_spec.path),
                "sha256": prepared.deployment_spec.sha256,
            }
            or deployment_identity.get("readiness_checkpoint")
            != {"path": str(prepared.readiness.path), "sha256": prepared.readiness.sha256}
            or deployment_identity.get("smoke_checkpoint")
            != {"path": str(prepared.smoke.path), "sha256": prepared.smoke.sha256}
            or deployment_identity.get("endpoint") != prepared.route_binding.endpoint
            or deployment_identity.get("serving_route_generation") != prepared.route_binding.route_generation
            or deployment_identity.get("proxy_policy") != prepared.route_binding.proxy_policy
        ):
            raise WaveTrainError("shard_identity_mismatch")
        linked = validate_guard_success_linkage(
            receipt,
            run_dir=output_dir,
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            eval_run_role="tb4",
            eval_run_identity_file_sha256=identity_file_sha256,
            results_sha256=certified.results_sha256,
            deployment_id=prepared.config.deployment_id,
            deployment_spec_sha256=prepared.deployment_spec.sha256,
            readiness_checkpoint={
                "path": str(prepared.readiness.path),
                "sha256": prepared.readiness.sha256,
            },
            endpoint=prepared.route_binding.endpoint,
            serving_route_generation=prepared.route_binding.route_generation,
            proxy_policy=prepared.route_binding.proxy_policy,
            require_concurrency_telemetry=True,
        )
        if linked["eval_invocations"] != invocation_artifact:
            raise WaveTrainError("shard_invocation_artifact_mismatch")
    except WaveTrainError:
        raise
    except (OSError, KeyError, TypeError, EvalIdentityError, GuardReceiptError) as error:
        raise WaveTrainError("shard_guarded_artifacts_invalid") from error

    before_results = certified.results_sha256
    supported, solved = _validate_trace_semantics(certified)
    try:
        _, after_results = stable_sha256_file(certified.results, label="results")
    except GuardReceiptError as error:
        raise WaveTrainError("shard_results_changed") from error
    if after_results != before_results:
        raise WaveTrainError("shard_results_changed")

    artifact_paths = {
        "results": output_dir / "results.jsonl",
        "eval_run_identity": output_dir / "eval_run_identity.json",
        "eval_invocations": output_dir / "eval_invocations.jsonl",
        "route_guard_success": receipt_path,
        "concurrency_telemetry": output_dir / "concurrency_telemetry.json",
        "config": output_dir / "config.toml",
        "inputs_manifest": output_dir / "inputs/manifest.json",
        "provenance": output_dir / "provenance.txt",
    }
    artifact_hashes: dict[str, str] = {}
    try:
        for name, path in artifact_paths.items():
            resolved, digest = stable_sha256_file(path, label=name)
            if resolved != path:
                raise WaveTrainError("shard_artifact_path_mismatch")
            artifact_hashes[name] = digest
    except GuardReceiptError as error:
        raise WaveTrainError("shard_guarded_artifacts_invalid") from error
    return ShardEvidence(
        shard_index=shard.index,
        slurm_job_id=job["slurm_job_id"],
        supported=supported,
        solved=solved,
        artifacts=artifact_hashes,
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        guard_success_receipt_sha256=certified.success_receipt_sha256,
        route_generation_sha256=certified.route_generation_sha256,
    )


def _evidence_record(evidence: ShardEvidence) -> dict[str, Any]:
    return {
        "shard_index": evidence.shard_index,
        "slurm_job_id": evidence.slurm_job_id,
        "scheduler_state": "COMPLETED",
        "scheduler_exit_code": "0:0",
        "supported": evidence.supported,
        "solved": evidence.solved,
        "artifacts": evidence.artifacts,
        "eval_run_identity_sha256": evidence.eval_run_identity_sha256,
        "guard_success_receipt_sha256": evidence.guard_success_receipt_sha256,
        "route_generation_sha256": evidence.route_generation_sha256,
    }


def _completion_body(
    *,
    train_sha256: str,
    wave_number: int,
    wave: Mapping[str, Any],
    evidences: Sequence[ShardEvidence],
) -> dict[str, Any]:
    supported = sum(evidence.supported for evidence in evidences)
    unsupported = len(evidences) - supported
    solved = sum(evidence.solved or 0 for evidence in evidences)
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "passed",
        "train_sha256": train_sha256,
        "wave_number": wave_number,
        "wave": {
            "path": str(Path(str(wave["jobs"][0]["output_dir"])).parent / "wave.json"),
            "sha256": wave["wave_sha256"],
        },
        "jobs": [_evidence_record(evidence) for evidence in evidences],
        "counts": {
            "jobs": len(evidences),
            "supported": supported,
            "unsupported": unsupported,
            "solved": solved,
        },
        "completed_at": _now(),
    }


def _load_completion(
    prepared: PreparedTrain,
    train_sha256: str,
    wave_number: int,
    indices: tuple[int, ...],
    wave: Mapping[str, Any],
    shard_validator: ShardValidator,
) -> tuple[dict[str, Any], str]:
    path = _wave_root(prepared, wave_number) / "completion.json"
    value, file_sha256 = _load_private_json(
        path,
        label="wave_completion",
        hash_key="completion_sha256",
    )
    expected_keys = {
        "schema_version",
        "state",
        "train_sha256",
        "wave_number",
        "wave",
        "jobs",
        "counts",
        "completed_at",
        "completion_sha256",
    }
    if (
        set(value) != expected_keys
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("state") != "passed"
        or value.get("train_sha256") != train_sha256
        or type(value.get("wave_number")) is not int
        or value.get("wave_number") != wave_number
        or value.get("wave")
        != {
            "path": str(_wave_root(prepared, wave_number) / "wave.json"),
            "sha256": wave["wave_sha256"],
        }
        or not _valid_timestamp(value.get("completed_at"))
        or not isinstance(value.get("jobs"), list)
        or len(value["jobs"]) != len(indices)
        or not isinstance(value.get("counts"), dict)
        or set(value["counts"]) != {"jobs", "supported", "unsupported", "solved"}
        or any(type(item) is not int for item in value["counts"].values())
    ):
        raise WaveTrainError("wave_completion_invalid")
    evidences: list[ShardEvidence] = []
    for index, job, recorded in zip(indices, wave["jobs"], value["jobs"], strict=True):
        if not isinstance(recorded, dict):
            raise WaveTrainError("wave_completion_invalid")
        try:
            evidence = shard_validator(prepared, prepared.shards[index], job)
        except WaveTrainError:
            raise
        except Exception as error:
            raise WaveTrainError("shard_validation_failed") from error
        if recorded != _evidence_record(evidence):
            raise WaveTrainError("wave_completion_artifact_mismatch")
        evidences.append(evidence)
    expected_counts = {
        "jobs": len(evidences),
        "supported": sum(evidence.supported for evidence in evidences),
        "unsupported": sum(not evidence.supported for evidence in evidences),
        "solved": sum(evidence.solved or 0 for evidence in evidences),
    }
    if value["counts"] != expected_counts:
        raise WaveTrainError("wave_completion_invalid")
    return value, file_sha256


def _write_or_validate_completion(
    prepared: PreparedTrain,
    train_sha256: str,
    wave_number: int,
    indices: tuple[int, ...],
    wave: Mapping[str, Any],
    evidences: Sequence[ShardEvidence],
    shard_validator: ShardValidator,
) -> tuple[dict[str, Any], str]:
    path = _wave_root(prepared, wave_number) / "completion.json"
    if path.exists() or path.is_symlink():
        return _load_completion(
            prepared,
            train_sha256,
            wave_number,
            indices,
            wave,
            shard_validator,
        )
    body = _completion_body(
        train_sha256=train_sha256,
        wave_number=wave_number,
        wave=wave,
        evidences=evidences,
    )
    value = _write_once_private_json(path, body, hash_key="completion_sha256")
    _loaded, file_sha256 = _load_completion(
        prepared,
        train_sha256,
        wave_number,
        indices,
        wave,
        shard_validator,
    )
    if _loaded != value:
        raise WaveTrainError("wave_completion_changed")
    return value, file_sha256


def _completed_state_record(
    wave_number: int,
    indices: tuple[int, ...],
    completion: Mapping[str, Any],
    completion_file_sha256: str,
    prepared: PreparedTrain,
) -> dict[str, Any]:
    counts = completion["counts"]
    return {
        "wave_number": wave_number,
        "shard_indices": list(indices),
        "completion": {
            "path": str(_wave_root(prepared, wave_number) / "completion.json"),
            "sha256": completion_file_sha256,
        },
        "job_count": counts["jobs"],
        "supported_count": counts["supported"],
        "unsupported_count": counts["unsupported"],
        "solved_count": counts["solved"],
    }


def _validate_completed_history(
    prepared: PreparedTrain,
    train_sha256: str,
    state: Mapping[str, Any],
    *,
    wave_loader: WaveLoader,
    shard_validator: ShardValidator,
) -> None:
    position = 0
    for record in state["completed_waves"]:
        wave_number = record["wave_number"]
        indices = _expected_wave_indices(prepared, position)
        root = _wave_root(prepared, wave_number)
        wave = wave_loader(prepared, wave_number, indices, root, False)
        completion, file_sha256 = _load_completion(
            prepared,
            train_sha256,
            wave_number,
            indices,
            wave,
            shard_validator,
        )
        if record != _completed_state_record(
            wave_number,
            indices,
            completion,
            file_sha256,
            prepared,
        ):
            raise WaveTrainError("completed_history_mismatch")
        position += len(indices)


def _default_route_verifier(prepared: PreparedTrain) -> None:
    try:
        _stable_artifact(
            prepared.smoke.path,
            prepared.smoke.sha256,
            label="smoke_checkpoint",
        )
        verify_live_route_generation(prepared.route_binding)
    except (WaveLaunchError, RouteGuardError) as error:
        raise WaveTrainError("serving_route_generation_changed") from error


def _default_scheduler_reader(job_ids: Sequence[str]) -> dict[str, SchedulerObservation]:
    return query_scheduler(job_ids)


def _default_submission_lookup(job_name: str, submitted_at: str) -> str | None:
    return lookup_submission_job(job_name, submitted_at)


def _default_launch(
    prepared: PreparedTrain,
    _wave_number: int,
    indices: tuple[int, ...],
    output_root: Path,
    stop_requested: Callable[[], bool],
) -> dict[str, Any]:
    config = prepared.config
    try:
        return launch_wave(
            project_dir=prepared.project,
            project_revision=config.project_revision,
            plan_path=prepared.plan_artifact.path,
            plan_sha256=prepared.plan_artifact.sha256,
            shard_indices=indices,
            output_root=output_root,
            deployment_id=config.deployment_id,
            deployment_spec_path=prepared.deployment_spec.path,
            deployment_spec_sha256=prepared.deployment_spec.sha256,
            readiness_path=prepared.readiness.path,
            readiness_sha256=prepared.readiness.sha256,
            proxy_info_path=prepared.proxy_info.path,
            proxy_info_sha256=prepared.proxy_info.sha256,
            smoke_checkpoint_path=prepared.smoke.path,
            smoke_checkpoint_sha256=prepared.smoke.sha256,
            dataset_revision=config.dataset_revision,
            dataset_archive_path=(prepared.dataset_archive.path if prepared.dataset_archive is not None else None),
            dataset_archive_sha256=(prepared.dataset_archive.sha256 if prepared.dataset_archive is not None else None),
            dataset_content_sha256=config.dataset_content_sha256,
            dry_run=False,
            stop_requested=stop_requested,
            submission_timeout_seconds=SCHEDULER_TIMEOUT_SECONDS,
        )
    except WaveSubmissionInterrupted as error:
        raise ControllerInterrupted("submission_interrupted") from error
    except WaveSubmissionOutcomeUnknown as error:
        raise SchedulerQueryUnavailable("submission_outcome_unknown") from error
    except WaveLaunchError as error:
        raise WaveTrainError("wave_submission_failed") from error


def _current_from_wave(
    wave_number: int,
    indices: tuple[int, ...],
    root: Path,
    wave: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "wave_number": wave_number,
        "phase": "submitted",
        "shard_indices": list(indices),
        "output_root": str(root),
        "wave_sha256": wave["wave_sha256"],
        "jobs": [
            {
                "shard_index": job["shard_index"],
                "slurm_job_id": job["slurm_job_id"],
            }
            for job in wave["jobs"]
        ],
    }


def _revalidate_submission_inputs(
    prepared: PreparedTrain,
    shard: PlannedShard,
    *,
    command_runner: CommandRunner,
) -> None:
    try:
        if validate_clean_project(prepared.project, runner=command_runner) != prepared.revisions:
            raise WaveTrainError("project_changed")
        for path, digest, label in (
            (prepared.plan_artifact.path, prepared.plan_artifact.sha256, "plan"),
            (shard.config, shard.config_sha256, "shard_config"),
            (shard.task_manifest, shard.task_manifest_sha256, "shard_manifest"),
            (prepared.deployment_spec.path, prepared.deployment_spec.sha256, "deployment_spec"),
            (prepared.readiness.path, prepared.readiness.sha256, "readiness_checkpoint"),
            (prepared.proxy_info.path, prepared.proxy_info.sha256, "proxy_info"),
            (prepared.smoke.path, prepared.smoke.sha256, "smoke_checkpoint"),
        ):
            _stable_artifact(path, digest, label=label)
        if prepared.dataset_archive is not None:
            _stable_artifact(
                prepared.dataset_archive.path,
                prepared.dataset_archive.sha256,
                label="dataset_archive",
            )
        current_readiness = _stable_artifact(
            prepared.readiness.path,
            prepared.readiness.sha256,
            label="readiness_checkpoint",
            load_bytes=True,
        )
        current_smoke = _stable_artifact(
            prepared.smoke.path,
            prepared.smoke.sha256,
            label="smoke_checkpoint",
            load_bytes=True,
        )
        _validate_generation_bindings(
            deployment_id=prepared.config.deployment_id,
            deployment_spec=prepared.deployment_spec,
            readiness=current_readiness,
            proxy_info=prepared.proxy_info,
            smoke=current_smoke,
        )
        _validate_dataset(
            shards=(shard,),
            dataset_revision=prepared.config.dataset_revision,
            dataset_archive=prepared.dataset_archive,
            dataset_content_sha256=prepared.config.dataset_content_sha256,
            runner=command_runner,
        )
    except WaveTrainError:
        raise
    except WaveLaunchError as error:
        raise WaveTrainError("submission_inputs_changed") from error


def _retire_pre_submission_directory(
    prepared: PreparedTrain,
    wave_number: int,
    indices: tuple[int, ...],
    output_root: Path,
) -> None:
    """Move aside a provably pre-sbatch directory without reusing its attempts."""

    try:
        if output_root.is_symlink():
            raise WaveTrainError("wave_metadata_invalid")
        root_stat = output_root.stat(follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_IMODE(root_stat.st_mode) != 0o700:
            raise WaveTrainError("wave_metadata_invalid")
        wave_path = output_root / "wave.json"
        if os.path.lexists(wave_path):
            raise WaveTrainError("wave_metadata_invalid")
        expected_environments = {
            f"shard-{index:03d}.env": (
                prepared.shards[index],
                output_root / f"shard-{index:03d}-attempt-001",
            )
            for index in indices
        }
        observed_environment_count = 0
        for path in output_root.iterdir():
            if path.name.startswith(".wave.json.") and path.name.endswith(".tmp"):
                file_stat = path.stat(follow_symlinks=False)
                if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != 0o600:
                    raise WaveTrainError("wave_metadata_invalid")
                continue
            expected = expected_environments.get(path.name)
            if expected is None:
                raise WaveTrainError("wave_metadata_invalid")
            shard, shard_output = expected
            resolved, raw = _stable_private_bytes(path, label="wave_environment")
            if resolved != path or raw != _expected_job_environment(prepared, shard, shard_output):
                raise WaveTrainError("wave_environment_invalid")
            observed_environment_count += 1
        abandoned = output_root.with_name(f"wave-{wave_number:03d}-abandoned-{secrets.token_hex(4)}")
        if abandoned.exists() or abandoned.is_symlink():
            raise WaveTrainError("wave_abandonment_collision")
        os.rename(output_root, abandoned)
        _write_once_private_json(
            abandoned / "abandoned.json",
            {
                "schema_version": SCHEMA_VERSION,
                "state": "abandoned_before_submission",
                "wave_number": wave_number,
                "planned_jobs": len(indices),
                "observed_environment_files": observed_environment_count,
                "abandoned_at": _now(),
            },
            hash_key="abandoned_sha256",
        )
        _fsync_directory(prepared.controller_root)
    except WaveTrainError:
        raise
    except OSError as error:
        raise WaveTrainError("wave_pre_submission_recovery_failed") from error


def _resume_partial_wave_submission(
    prepared: PreparedTrain,
    indices: tuple[int, ...],
    output_root: Path,
    wave: dict[str, Any],
    *,
    ambient_env: Mapping[str, str],
    command_runner: CommandRunner,
    route_verifier: RouteVerifier,
    submission_lookup: SubmissionLookup,
    stop_requested: Callable[[], bool],
) -> dict[str, Any]:
    """Finish a crashed launcher transaction without resubmitting recorded jobs."""

    if wave.get("state") == "submitted":
        return wave
    if wave.get("state") not in {"submitting", "submission_interrupted"}:
        raise WaveTrainError("wave_submission_incomplete")
    wave_path = output_root / "wave.json"
    seen_job_ids = {job["slurm_job_id"] for job in wave["jobs"] if isinstance(job.get("slurm_job_id"), str)}
    try:
        for index, job in zip(indices, wave["jobs"], strict=True):
            if job["slurm_job_id"] is not None:
                continue
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            token = job["submission_token"]
            if token is not None:
                recovered = submission_lookup(
                    f"tb4-shard-{index:03d}-{token}",
                    job["submission_started_at"],
                )
                if recovered is None:
                    raise SchedulerQueryUnavailable("submission_outcome_unknown")
                if SLURM_JOB_ID_RE.fullmatch(recovered) is None:
                    raise WaveTrainError("submission_lookup_response_invalid")
                if recovered in seen_job_ids:
                    raise WaveTrainError("submission_lookup_not_unique")
                job["slurm_job_id"] = recovered
                seen_job_ids.add(recovered)
                wave = _replace_private_json(wave_path, wave, hash_key="wave_sha256")
                continue

            route_verifier(prepared)
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            _require_tmux_launcher(ambient_env, runner=command_runner)
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            shard = prepared.shards[index]
            _revalidate_submission_inputs(
                prepared,
                shard,
                command_runner=command_runner,
            )
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            environment_path = Path(job["environment"]["path"])
            _resolved, raw = _stable_private_bytes(
                environment_path,
                label="wave_environment",
            )
            if raw != _expected_job_environment(
                prepared,
                shard,
                Path(job["output_dir"]),
            ):
                raise WaveTrainError("wave_environment_invalid")
            token = secrets.token_hex(8)
            job["submission_token"] = token
            job["submission_started_at"] = _now()
            wave["state"] = "submitting"
            wave = _replace_private_json(wave_path, wave, hash_key="wave_sha256")
            if stop_requested():
                job["submission_token"] = None
                job["submission_started_at"] = None
                raise ControllerInterrupted("submission_interrupted")
            result = command_runner(
                [
                    DEFAULT_SBATCH,
                    "--parsable",
                    f"--job-name=tb4-shard-{index:03d}-{token}",
                    f"--export-file={environment_path}",
                    str(prepared.project / "user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch"),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=prepared.project,
                env={},
                timeout=SCHEDULER_TIMEOUT_SECONDS,
            )
            submitted_job_id = _parse_job_id(result)
            if submitted_job_id in seen_job_ids:
                raise WaveTrainError("submission_job_id_duplicate")
            job["slurm_job_id"] = submitted_job_id
            seen_job_ids.add(submitted_job_id)
            wave = _replace_private_json(wave_path, wave, hash_key="wave_sha256")
    except SchedulerQueryUnavailable:
        raise
    except subprocess.TimeoutExpired as error:
        wave["state"] = "submitting"
        _replace_private_json(wave_path, wave, hash_key="wave_sha256")
        raise SchedulerQueryUnavailable("submission_outcome_unknown") from error
    except ControllerInterrupted:
        wave["state"] = "submission_interrupted"
        _replace_private_json(wave_path, wave, hash_key="wave_sha256")
        raise
    except (OSError, WaveLaunchError, WaveTrainError) as error:
        wave["state"] = "partial_submission_failed"
        _replace_private_json(wave_path, wave, hash_key="wave_sha256")
        if isinstance(error, WaveTrainError):
            raise
        raise WaveTrainError("wave_submission_incomplete") from error
    wave["state"] = "submitted"
    return _replace_private_json(wave_path, wave, hash_key="wave_sha256")


def _recover_or_launch_current(
    prepared: PreparedTrain,
    state: Mapping[str, Any],
    *,
    ambient_env: Mapping[str, str],
    command_runner: CommandRunner,
    launch_callback: LaunchCallback,
    wave_loader: WaveLoader,
    route_verifier: RouteVerifier,
    submission_lookup: SubmissionLookup,
    stop_requested: Callable[[], bool],
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = state["current_wave"]
    if not isinstance(current, dict):
        raise WaveTrainError("controller_state_invalid")
    wave_number = current["wave_number"]
    indices = tuple(current["shard_indices"])
    output_root = _wave_root(prepared, wave_number)
    if current["phase"] == "submitted":
        wave = wave_loader(prepared, wave_number, indices, output_root, False)
        if _current_from_wave(wave_number, indices, output_root, wave) != current:
            raise WaveTrainError("wave_state_mismatch")
        return dict(state), wave

    if output_root.exists() or output_root.is_symlink():
        if not os.path.lexists(output_root / "wave.json"):
            _retire_pre_submission_directory(
                prepared,
                wave_number,
                indices,
                output_root,
            )
    if output_root.exists() or output_root.is_symlink():
        wave = wave_loader(prepared, wave_number, indices, output_root, True)
        wave = _resume_partial_wave_submission(
            prepared,
            indices,
            output_root,
            wave,
            ambient_env=ambient_env,
            command_runner=command_runner,
            route_verifier=route_verifier,
            submission_lookup=submission_lookup,
            stop_requested=stop_requested,
        )
        wave = wave_loader(prepared, wave_number, indices, output_root, False)
    else:
        try:
            route_verifier(prepared)
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            _require_tmux_launcher(ambient_env, runner=command_runner)
            if stop_requested():
                raise ControllerInterrupted("submission_interrupted")
            wave = launch_callback(prepared, wave_number, indices, output_root, stop_requested)
        except ControllerInterrupted:
            raise
        except WaveTrainError:
            raise
        except (OSError, WaveLaunchError) as error:
            raise WaveTrainError("wave_submission_failed") from error
        wave = wave_loader(prepared, wave_number, indices, output_root, False)
    updated = _state_body(state)
    updated["state"] = "observing"
    updated["current_wave"] = _current_from_wave(wave_number, indices, output_root, wave)
    return _save_state(prepared, updated), wave


def _mark_failed(
    prepared: PreparedTrain,
    state: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    body = _state_body(state)
    body["state"] = "failed"
    body["failure"] = _safe_error(reason)
    return _save_state(prepared, body)


def _interrupt_state(prepared: PreparedTrain, state: Mapping[str, Any]) -> dict[str, Any]:
    body = _state_body(state)
    body["state"] = "interrupted"
    body["failure"] = None
    return _save_state(prepared, body)


def _resume_interrupted(prepared: PreparedTrain, state: Mapping[str, Any]) -> dict[str, Any]:
    body = _state_body(state)
    current = state.get("current_wave")
    if current is None:
        body["state"] = "ready"
    elif current["phase"] == "intent":
        body["state"] = "launching"
    else:
        body["state"] = "observing"
    return _save_state(prepared, body)


def _launch_intent(prepared: PreparedTrain, state: Mapping[str, Any]) -> dict[str, Any]:
    wave_number = len(state["completed_waves"])
    indices = _expected_wave_indices(prepared, state["next_position"])
    if not indices:
        raise WaveTrainError("controller_state_invalid")
    body = _state_body(state)
    body["state"] = "launching"
    body["current_wave"] = {
        "wave_number": wave_number,
        "phase": "intent",
        "shard_indices": list(indices),
        "output_root": str(_wave_root(prepared, wave_number)),
        "wave_sha256": None,
        "jobs": [],
    }
    return _save_state(prepared, body)


def _observe_wave(
    prepared: PreparedTrain,
    train_sha256: str,
    state: Mapping[str, Any],
    wave: Mapping[str, Any],
    *,
    scheduler_reader: SchedulerReader,
    shard_validator: ShardValidator,
) -> tuple[dict[str, Any], bool]:
    current = state["current_wave"]
    assert isinstance(current, dict)
    wave_number = current["wave_number"]
    indices = tuple(current["shard_indices"])
    completion_path = _wave_root(prepared, wave_number) / "completion.json"
    if completion_path.exists() or completion_path.is_symlink():
        completion, completion_file_sha256 = _load_completion(
            prepared,
            train_sha256,
            wave_number,
            indices,
            wave,
            shard_validator,
        )
        return (
            _finish_wave_state(
                prepared,
                state,
                wave_number,
                indices,
                completion,
                completion_file_sha256,
            ),
            True,
        )
    job_ids = tuple(job["slurm_job_id"] for job in wave["jobs"])
    try:
        observations = scheduler_reader(job_ids)
    except WaveTrainError:
        raise
    except Exception as error:
        raise WaveTrainError("scheduler_query_failed") from error
    if set(observations) != set(job_ids):
        raise WaveTrainError("scheduler_response_invalid")
    evidences: list[ShardEvidence] = []
    all_completed = True
    for index, job in zip(current["shard_indices"], wave["jobs"], strict=True):
        observation = observations[job["slurm_job_id"]]
        if not isinstance(observation, SchedulerObservation):
            raise WaveTrainError("scheduler_response_invalid")
        if observation.state in ACTIVE_SLURM_STATES:
            if observation.exit_code is not None:
                raise WaveTrainError("scheduler_response_invalid")
            all_completed = False
            continue
        if observation.state != "COMPLETED" or observation.exit_code != "0:0":
            raise WaveTrainError("shard_job_failed")
        try:
            evidence = shard_validator(prepared, prepared.shards[index], job)
        except WaveTrainError:
            raise
        except Exception as error:
            raise WaveTrainError("shard_validation_failed") from error
        if (
            evidence.shard_index != index
            or evidence.slurm_job_id != job["slurm_job_id"]
            or evidence.route_generation_sha256 != prepared.generation_sha256
        ):
            raise WaveTrainError("shard_validation_mismatch")
        evidences.append(evidence)
    if not all_completed:
        return dict(state), False
    if len(evidences) != len(job_ids):
        raise WaveTrainError("shard_validation_incomplete")
    completion, completion_file_sha256 = _write_or_validate_completion(
        prepared,
        train_sha256,
        wave_number,
        indices,
        wave,
        evidences,
        shard_validator,
    )
    return (
        _finish_wave_state(
            prepared,
            state,
            wave_number,
            indices,
            completion,
            completion_file_sha256,
        ),
        True,
    )


def _finish_wave_state(
    prepared: PreparedTrain,
    state: Mapping[str, Any],
    wave_number: int,
    indices: tuple[int, ...],
    completion: Mapping[str, Any],
    completion_file_sha256: str,
) -> dict[str, Any]:
    body = _state_body(state)
    body["completed_waves"] = [
        *state["completed_waves"],
        _completed_state_record(
            wave_number,
            indices,
            completion,
            completion_file_sha256,
            prepared,
        ),
    ]
    body["next_position"] = state["next_position"] + len(indices)
    body["current_wave"] = None
    body["state"] = "complete" if body["next_position"] == len(prepared.selected_indices) else "ready"
    return _save_state(prepared, body)


def drive_train(
    prepared: PreparedTrain,
    *,
    ambient_env: Mapping[str, str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    launch_callback: LaunchCallback = _default_launch,
    wave_loader: WaveLoader = _load_wave_metadata,
    scheduler_reader: SchedulerReader = _default_scheduler_reader,
    shard_validator: ShardValidator = validate_completed_shard,
    route_verifier: RouteVerifier = _default_route_verifier,
    submission_lookup: SubmissionLookup = _default_submission_lookup,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Drive or restart one controller until completion, failure, or signal."""

    environment = os.environ if ambient_env is None else ambient_env
    if "RESUME_DIR" in environment:
        raise WaveTrainError("resume_forbidden")
    event = threading.Event() if stop_event is None else stop_event
    root = prepared.controller_root
    train: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    _ensure_controller_root(prepared)
    with _controller_lock(root):
        try:
            train, state = _initialize_or_load(prepared)
            train_sha256 = train["train_sha256"]
            _validate_completed_history(
                prepared,
                train_sha256,
                state,
                wave_loader=wave_loader,
                shard_validator=shard_validator,
            )
            if state["state"] == "failed":
                raise WaveTrainError("controller_previously_failed")
            if state["state"] == "complete":
                return state
            if state["state"] == "interrupted":
                state = _resume_interrupted(prepared, state)

            scheduler_failures = 0
            while True:
                if event.is_set():
                    return _interrupt_state(prepared, state)
                if state["state"] == "ready":
                    try:
                        route_verifier(prepared)
                    except WaveTrainError:
                        raise
                    except Exception as error:
                        raise WaveTrainError("serving_route_generation_changed") from error
                    if event.is_set():
                        return _interrupt_state(prepared, state)
                    state = _launch_intent(prepared, state)
                if state["state"] == "launching":
                    try:
                        state, wave = _recover_or_launch_current(
                            prepared,
                            state,
                            ambient_env=environment,
                            command_runner=command_runner,
                            launch_callback=launch_callback,
                            wave_loader=wave_loader,
                            route_verifier=route_verifier,
                            submission_lookup=submission_lookup,
                            stop_requested=event.is_set,
                        )
                    except ControllerInterrupted:
                        return _interrupt_state(prepared, state)
                    except SchedulerQueryUnavailable:
                        scheduler_failures += 1
                        if scheduler_failures >= MAX_CONSECUTIVE_SCHEDULER_FAILURES:
                            raise
                        try:
                            route_verifier(prepared)
                        except WaveTrainError:
                            raise
                        except Exception as error:
                            raise WaveTrainError("serving_route_generation_changed") from error
                        if event.wait(prepared.config.poll_interval_seconds):
                            return _interrupt_state(prepared, state)
                        continue
                else:
                    current = state["current_wave"]
                    assert isinstance(current, dict)
                    indices = tuple(current["shard_indices"])
                    wave = wave_loader(
                        prepared,
                        current["wave_number"],
                        indices,
                        _wave_root(prepared, current["wave_number"]),
                        False,
                    )
                    if (
                        _current_from_wave(
                            current["wave_number"],
                            indices,
                            _wave_root(prepared, current["wave_number"]),
                            wave,
                        )
                        != current
                    ):
                        raise WaveTrainError("wave_state_mismatch")
                if event.is_set():
                    return _interrupt_state(prepared, state)
                try:
                    state, completed = _observe_wave(
                        prepared,
                        train_sha256,
                        state,
                        wave,
                        scheduler_reader=scheduler_reader,
                        shard_validator=shard_validator,
                    )
                except SchedulerQueryUnavailable:
                    scheduler_failures += 1
                    if scheduler_failures >= MAX_CONSECUTIVE_SCHEDULER_FAILURES:
                        raise
                    try:
                        route_verifier(prepared)
                    except WaveTrainError:
                        raise
                    except Exception as error:
                        raise WaveTrainError("serving_route_generation_changed") from error
                    if event.wait(prepared.config.poll_interval_seconds):
                        return _interrupt_state(prepared, state)
                    continue
                scheduler_failures = 0
                if state["state"] == "complete":
                    return state
                if completed:
                    continue
                try:
                    route_verifier(prepared)
                except WaveTrainError:
                    raise
                except Exception as error:
                    raise WaveTrainError("serving_route_generation_changed") from error
                if event.is_set():
                    return _interrupt_state(prepared, state)
                if event.wait(prepared.config.poll_interval_seconds):
                    return _interrupt_state(prepared, state)
        except WaveTrainError as error:
            if state is not None and state.get("state") != "failed":
                try:
                    _mark_failed(prepared, state, _safe_error(str(error)))
                except WaveTrainError:
                    pass
            raise


def run_wave_train(
    config: WaveTrainConfig,
    *,
    ambient_env: Mapping[str, str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    prepared = prepare_train(config, command_runner=command_runner)
    return drive_train(
        prepared,
        ambient_env=ambient_env,
        command_runner=command_runner,
        stop_event=stop_event,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-root", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--project-revision", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--deployment-spec", type=Path, required=True)
    parser.add_argument("--deployment-spec-sha256", required=True)
    parser.add_argument("--readiness-checkpoint", type=Path, required=True)
    parser.add_argument("--readiness-checkpoint-sha256", required=True)
    parser.add_argument("--proxy-info", type=Path, required=True)
    parser.add_argument("--proxy-info-sha256", required=True)
    parser.add_argument("--smoke-checkpoint", type=Path, required=True)
    parser.add_argument("--smoke-checkpoint-sha256", required=True)
    dataset = parser.add_mutually_exclusive_group(required=True)
    dataset.add_argument("--dataset-revision")
    dataset.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--dataset-archive-sha256")
    parser.add_argument("--dataset-content-sha256")
    parser.add_argument("--first-shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--wave-size", type=int, default=MAX_WAVE_SIZE)
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    return parser


def _summary(state: Mapping[str, Any]) -> dict[str, Any]:
    completed = state.get("completed_waves")
    completed_count = sum(record.get("job_count", 0) for record in completed) if isinstance(completed, list) else 0
    return {
        "state": state.get("state"),
        "completed_shards": completed_count,
        "active_shards": (
            len(state.get("current_wave", {}).get("jobs", [])) if isinstance(state.get("current_wave"), dict) else 0
        ),
        "state_sha256": state.get("state_sha256"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = WaveTrainConfig(
        controller_root=args.controller_root,
        project_dir=args.project_dir,
        project_revision=args.project_revision,
        plan_path=args.plan,
        plan_sha256=args.plan_sha256,
        deployment_id=args.deployment_id,
        deployment_spec_path=args.deployment_spec,
        deployment_spec_sha256=args.deployment_spec_sha256,
        readiness_path=args.readiness_checkpoint,
        readiness_sha256=args.readiness_checkpoint_sha256,
        proxy_info_path=args.proxy_info,
        proxy_info_sha256=args.proxy_info_sha256,
        smoke_checkpoint_path=args.smoke_checkpoint,
        smoke_checkpoint_sha256=args.smoke_checkpoint_sha256,
        dataset_revision=args.dataset_revision,
        dataset_archive_path=args.dataset_archive,
        dataset_archive_sha256=args.dataset_archive_sha256,
        dataset_content_sha256=args.dataset_content_sha256,
        first_shard_index=args.first_shard_index,
        shard_count=args.shard_count,
        wave_size=args.wave_size,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        state = run_wave_train(config, stop_event=stop_event)
    except (OSError, WaveTrainError) as error:
        print(f"tb4_wave_train_error:{_safe_error(str(error))}", file=os.sys.stderr)
        return 2
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    print(json.dumps(_summary(state), sort_keys=True))
    return 130 if state["state"] == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
