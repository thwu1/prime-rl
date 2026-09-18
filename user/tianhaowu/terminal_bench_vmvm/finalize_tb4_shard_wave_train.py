#!/usr/bin/env python3
"""Finalize a completed TB4 singleton wave train without exposing task data.

The controller deliberately stops after certifying each wave.  This command
waits for (or requires) its hash-authenticated terminal state, revalidates the
entire controller history against the exact launch inputs, and then delegates
to the normal sharded merger.  A published output is reusable only when it
fully revalidates and is exactly linked to the controller evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from run_tb4_shard_wave_train import (
    PreparedTrain,
    WaveTrainConfig,
    WaveTrainError,
    _controller_lock,
    _load_completion,
    _load_private_json,
    _load_wave_metadata,
    _stable_private_bytes,
    _train_body,
    _validate_completed_history,
    _validate_state,
    _wave_root,
    prepare_train,
    validate_completed_shard,
)
from tb4_shard_workflow import (
    DEFAULT_MAX_SEQUENCE_TOKENS,
    EXPECTED_SUPPORTED_TASK_COUNT,
    EXPECTED_TASK_COUNT,
    EXPECTED_UNSUPPORTED_TASK_COUNT,
    ShardWorkflowError,
    _load_json,
    _stable_read,
    canonical_json,
    merge_shards,
    validate_sharded_checkpoint,
)

DEFAULT_WAIT_POLL_SECONDS = 30.0
DEFAULT_LOCK_POLL_SECONDS = 5.0
DEFAULT_LOCK_TIMEOUT_SECONDS = 120.0
MIN_POLL_SECONDS = 1.0
MAX_POLL_SECONDS = 60.0
MAX_LOCK_TIMEOUT_SECONDS = 600.0
MAX_CONSECUTIVE_STATE_READ_FAILURES = 3
EXPECTED_MIN_SUPPORTED_PASS_RATE = 0.04
EXPECTED_MAX_SUPPORTED_PASS_RATE = 0.22
EXPECTED_WAVE_SIZE = 4
SAFE_ERROR_RE = re.compile(r"[a-z0-9_]{1,96}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class FinalizationError(ValueError):
    """A controller or merged artifact cannot be finalized safely."""


@dataclass(frozen=True)
class FinalizerConfig:
    controller: WaveTrainConfig
    expected_train_sha256: str
    output_dir: Path
    wait_for_completion: bool = False
    wait_poll_seconds: float = DEFAULT_WAIT_POLL_SECONDS
    wait_timeout_seconds: float | None = None
    lock_poll_seconds: float = DEFAULT_LOCK_POLL_SECONDS
    lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS


@dataclass(frozen=True)
class CandidateControllerConfig:
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
    smoke_checkpoint_candidates: tuple[Path, ...]
    dataset_revision: str | None = None
    dataset_archive_path: Path | None = None
    dataset_archive_sha256: str | None = None
    dataset_content_sha256: str | None = None
    wave_size: int = EXPECTED_WAVE_SIZE
    controller_poll_interval_seconds: float = 15.0


@dataclass(frozen=True)
class ControllerEvidence:
    train: dict[str, Any]
    state: dict[str, Any]
    shard_records: tuple[dict[str, Any], ...]
    receipt_paths: tuple[Path, ...]
    supported_count: int
    unsupported_count: int
    solved_count: int


Sleep = Callable[[float], None]
Clock = Callable[[], float]


def _safe_error(value: str) -> str:
    return value if SAFE_ERROR_RE.fullmatch(value) is not None else "finalization_failed"


def _validate_wait_config(config: FinalizerConfig) -> None:
    if not isinstance(config.expected_train_sha256, str) or SHA256_RE.fullmatch(config.expected_train_sha256) is None:
        raise FinalizationError("train_sha256_invalid")
    values = (
        config.wait_poll_seconds,
        config.lock_poll_seconds,
        config.lock_timeout_seconds,
    )
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise FinalizationError("finalizer_timing_invalid")
    if (
        not all(math.isfinite(float(value)) for value in values)
        or not MIN_POLL_SECONDS <= config.wait_poll_seconds <= MAX_POLL_SECONDS
        or not MIN_POLL_SECONDS <= config.lock_poll_seconds <= MAX_POLL_SECONDS
        or not config.lock_poll_seconds <= config.lock_timeout_seconds <= MAX_LOCK_TIMEOUT_SECONDS
    ):
        raise FinalizationError("finalizer_timing_invalid")
    timeout = config.wait_timeout_seconds
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or timeout < config.wait_poll_seconds
    ):
        raise FinalizationError("finalizer_timing_invalid")


def _load_state(controller_root: Path) -> dict[str, Any]:
    try:
        state, _file_sha256 = _load_private_json(
            controller_root / "state.json",
            label="controller_state",
            hash_key="state_sha256",
        )
    except (OSError, WaveTrainError) as error:
        raise FinalizationError("controller_state_unavailable") from error
    return state


def _candidate_controller(
    config: CandidateControllerConfig,
    smoke_checkpoint: Path,
    smoke_checkpoint_sha256: str,
) -> WaveTrainConfig:
    return WaveTrainConfig(
        controller_root=config.controller_root,
        project_dir=config.project_dir,
        project_revision=config.project_revision,
        plan_path=config.plan_path,
        plan_sha256=config.plan_sha256,
        deployment_id=config.deployment_id,
        deployment_spec_path=config.deployment_spec_path,
        deployment_spec_sha256=config.deployment_spec_sha256,
        readiness_path=config.readiness_path,
        readiness_sha256=config.readiness_sha256,
        proxy_info_path=config.proxy_info_path,
        proxy_info_sha256=config.proxy_info_sha256,
        smoke_checkpoint_path=smoke_checkpoint,
        smoke_checkpoint_sha256=smoke_checkpoint_sha256,
        dataset_revision=config.dataset_revision,
        dataset_archive_path=config.dataset_archive_path,
        dataset_archive_sha256=config.dataset_archive_sha256,
        dataset_content_sha256=config.dataset_content_sha256,
        first_shard_index=0,
        shard_count=EXPECTED_TASK_COUNT,
        wave_size=config.wave_size,
        poll_interval_seconds=config.controller_poll_interval_seconds,
    )


def resolve_candidate_controller(
    config: CandidateControllerConfig,
    *,
    wait_poll_seconds: float = DEFAULT_WAIT_POLL_SECONDS,
    wait_timeout_seconds: float | None = None,
    command_runner: Callable[..., Any] = subprocess.run,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> tuple[WaveTrainConfig, str]:
    """Match a new controller to one trusted, independently validated smoke candidate."""

    timing = FinalizerConfig(
        controller=_candidate_controller(config, Path("/invalid"), "0" * 64),
        expected_train_sha256="0" * 64,
        output_dir=Path("/invalid"),
        wait_for_completion=True,
        wait_poll_seconds=wait_poll_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )
    _validate_wait_config(timing)
    candidates = config.smoke_checkpoint_candidates
    if (
        not candidates
        or len(candidates) != len(set(candidates))
        or any(not path.is_absolute() or path.is_symlink() for path in candidates)
    ):
        raise FinalizationError("smoke_candidate_set_invalid")
    started = clock()
    train_path = config.controller_root / "train.json"
    consecutive_failures = 0
    while True:
        try:
            train, _train_file_sha256 = _load_private_json(
                train_path,
                label="train_metadata",
                hash_key="train_sha256",
            )
        except (OSError, WaveTrainError):
            consecutive_failures = consecutive_failures + 1 if train_path.exists() else 0
            if consecutive_failures >= MAX_CONSECUTIVE_STATE_READ_FAILURES:
                raise FinalizationError("train_metadata_invalid") from None
        else:
            matches: list[tuple[WaveTrainConfig, str]] = []
            for candidate in candidates:
                try:
                    resolved, raw = _stable_private_bytes(candidate, label="smoke_checkpoint")
                    if resolved != candidate:
                        raise FinalizationError("smoke_candidate_set_invalid")
                    controller = _candidate_controller(
                        config,
                        candidate,
                        hashlib.sha256(raw).hexdigest(),
                    )
                    prepared = prepare_train(controller, command_runner=command_runner)
                    body = _train_body(prepared)
                    train_sha256 = hashlib.sha256(canonical_json(body)).hexdigest()
                    if train == {**body, "train_sha256": train_sha256}:
                        matches.append((controller, train_sha256))
                except (OSError, FinalizationError, WaveTrainError):
                    continue
            if len(matches) != 1:
                raise FinalizationError(
                    "trusted_train_match_ambiguous" if len(matches) > 1 else "trusted_train_match_missing"
                )
            return matches[0]
        if wait_timeout_seconds is not None and clock() - started >= wait_timeout_seconds:
            raise FinalizationError("controller_wait_timeout")
        sleep(wait_poll_seconds)


def wait_for_complete_state(
    config: FinalizerConfig,
    *,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> dict[str, Any]:
    """Wait only on a stable, self-hash-valid controller state."""

    _validate_wait_config(config)
    state_path = config.controller.controller_root / "state.json"
    started = clock()
    consecutive_failures = 0
    while True:
        try:
            state = _load_state(config.controller.controller_root)
        except FinalizationError:
            if not config.wait_for_completion:
                raise
            consecutive_failures = consecutive_failures + 1 if state_path.exists() else 0
            if consecutive_failures >= MAX_CONSECUTIVE_STATE_READ_FAILURES:
                raise FinalizationError("controller_state_invalid") from None
        else:
            consecutive_failures = 0
            phase = state.get("state")
            if phase == "complete":
                return state
            if phase in {"failed", "interrupted"}:
                raise FinalizationError(f"controller_{phase}")
            if phase not in {"ready", "launching", "observing"}:
                raise FinalizationError("controller_state_invalid")
            if not config.wait_for_completion:
                raise FinalizationError("controller_not_complete")
        timeout = config.wait_timeout_seconds
        if timeout is not None and clock() - started >= timeout:
            raise FinalizationError("controller_wait_timeout")
        sleep(config.wait_poll_seconds)


def _validate_controller_root(root: Path) -> Path:
    try:
        if root.is_symlink():
            raise FinalizationError("controller_root_invalid")
        resolved = root.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
    except FinalizationError:
        raise
    except (OSError, RuntimeError) as error:
        raise FinalizationError("controller_root_invalid") from error
    if resolved != root or not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise FinalizationError("controller_root_invalid")
    return resolved


def _expected_checkpoint_record(
    prepared: PreparedTrain,
    index: int,
    job: Mapping[str, Any],
) -> tuple[dict[str, Any], Path]:
    artifacts = job.get("artifacts")
    if not isinstance(artifacts, dict):
        raise FinalizationError("controller_evidence_invalid")
    output_dir = _wave_root(prepared, index // prepared.config.wave_size) / (f"shard-{index:03d}-attempt-001")
    receipt_path = output_dir / "route_guard_success.json"
    endpoint_sha256 = hashlib.sha256(canonical_json(prepared.route_binding.endpoint)).hexdigest()
    routes = prepared.route_binding.route_generation.get("routes")
    if not isinstance(routes, list) or not routes:
        raise FinalizationError("controller_evidence_invalid")
    try:
        record = {
            "index": index,
            "task_count": 1,
            "task_manifest_sha256": prepared.shards[index].task_manifest_sha256,
            "guard_success_receipt_sha256": job["guard_success_receipt_sha256"],
            "guard_success_receipt": {
                "path": str(receipt_path),
                "sha256": artifacts["route_guard_success"],
            },
            "eval_run_identity_sha256": job["eval_run_identity_sha256"],
            "results_sha256": artifacts["results"],
            "route_generation_sha256": job["route_generation_sha256"],
            "endpoint_binding_sha256": endpoint_sha256,
            "expected_routes": len(routes),
        }
    except (KeyError, TypeError) as error:
        raise FinalizationError("controller_evidence_invalid") from error
    return record, receipt_path


def _collect_controller_evidence(
    prepared: PreparedTrain,
    expected_train_sha256: str,
) -> ControllerEvidence:
    root = prepared.controller_root
    train, _train_file_sha256 = _load_private_json(
        root / "train.json",
        label="train_metadata",
        hash_key="train_sha256",
    )
    if (
        SHA256_RE.fullmatch(expected_train_sha256) is None
        or train.get("train_sha256") != expected_train_sha256
        or {key: value for key, value in train.items() if key != "train_sha256"} != _train_body(prepared)
    ):
        raise FinalizationError("train_spec_mismatch")
    state, _state_file_sha256 = _load_private_json(
        root / "state.json",
        label="controller_state",
        hash_key="state_sha256",
    )
    _validate_state(prepared, train, state)
    if (
        state["state"] != "complete"
        or state["next_position"] != EXPECTED_TASK_COUNT
        or state["current_wave"] is not None
        or state["failure"] is not None
    ):
        raise FinalizationError("controller_not_complete")
    _validate_completed_history(
        prepared,
        train["train_sha256"],
        state,
        wave_loader=_load_wave_metadata,
        shard_validator=validate_completed_shard,
    )

    records_by_index: dict[int, dict[str, Any]] = {}
    receipts_by_index: dict[int, Path] = {}
    supported_count = 0
    unsupported_count = 0
    solved_count = 0
    position = 0
    for completed in state["completed_waves"]:
        wave_number = completed["wave_number"]
        indices = tuple(completed["shard_indices"])
        wave = _load_wave_metadata(
            prepared,
            wave_number,
            indices,
            _wave_root(prepared, wave_number),
            False,
        )
        completion, completion_file_sha256 = _load_completion(
            prepared,
            train["train_sha256"],
            wave_number,
            indices,
            wave,
            validate_completed_shard,
        )
        if completed["completion"] != {
            "path": str(_wave_root(prepared, wave_number) / "completion.json"),
            "sha256": completion_file_sha256,
        }:
            raise FinalizationError("controller_completion_mismatch")
        for index, job in zip(indices, completion["jobs"], strict=True):
            if index != position or index in records_by_index:
                raise FinalizationError("controller_coverage_invalid")
            record, receipt = _expected_checkpoint_record(prepared, index, job)
            records_by_index[index] = record
            receipts_by_index[index] = receipt.resolve(strict=True)
            position += 1
        supported_count += completion["counts"]["supported"]
        unsupported_count += completion["counts"]["unsupported"]
        solved_count += completion["counts"]["solved"]

    if (
        position != EXPECTED_TASK_COUNT
        or set(records_by_index) != set(range(EXPECTED_TASK_COUNT))
        or set(receipts_by_index) != set(range(EXPECTED_TASK_COUNT))
        or len(set(receipts_by_index.values())) != EXPECTED_TASK_COUNT
        or supported_count != EXPECTED_SUPPORTED_TASK_COUNT
        or unsupported_count != EXPECTED_UNSUPPORTED_TASK_COUNT
        or not 0 <= solved_count <= EXPECTED_SUPPORTED_TASK_COUNT
    ):
        raise FinalizationError("controller_coverage_invalid")
    return ControllerEvidence(
        train=train,
        state=state,
        shard_records=tuple(records_by_index[index] for index in range(EXPECTED_TASK_COUNT)),
        receipt_paths=tuple(receipts_by_index[index] for index in range(EXPECTED_TASK_COUNT)),
        supported_count=supported_count,
        unsupported_count=unsupported_count,
        solved_count=solved_count,
    )


def _resolved_output(configured: Path, prepared: PreparedTrain) -> Path:
    try:
        if not configured.is_absolute() or configured.is_symlink() or configured.parent.is_symlink():
            raise FinalizationError("merge_output_invalid")
        parent = configured.parent.resolve(strict=True)
        parent_stat = parent.stat(follow_symlinks=False)
        output = configured.resolve(strict=False)
    except FinalizationError:
        raise
    except (OSError, RuntimeError) as error:
        raise FinalizationError("merge_output_parent_invalid") from error
    if output.parent != parent or not stat.S_ISDIR(parent_stat.st_mode) or stat.S_IMODE(parent_stat.st_mode) != 0o700:
        raise FinalizationError("merge_output_parent_invalid")
    for protected in (
        prepared.project,
        prepared.controller_root,
        prepared.dataset_path,
        prepared.plan_artifact.path.parent,
    ):
        try:
            output.relative_to(protected)
        except ValueError:
            continue
        raise FinalizationError("merge_output_invalid")
    return output


def _load_and_validate_checkpoint(
    output: Path,
    prepared: PreparedTrain,
    evidence: ControllerEvidence,
    *,
    expected_value: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bytes]:
    try:
        output_stat = output.stat(follow_symlinks=False)
    except OSError as error:
        raise FinalizationError("merge_output_invalid") from error
    if output.is_symlink() or not stat.S_ISDIR(output_stat.st_mode) or stat.S_IMODE(output_stat.st_mode) != 0o700:
        raise FinalizationError("merge_output_invalid")
    try:
        members = {path.name: path.stat(follow_symlinks=False) for path in output.iterdir()}
    except OSError as error:
        raise FinalizationError("merge_output_invalid") from error
    if set(members) != {
        "results.jsonl",
        "audit_summary.json",
        "checkpoint.json",
        "deployment_spec.yaml",
        "proxy_policy.json",
    } or any(
        not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600 for metadata in members.values()
    ):
        raise FinalizationError("merge_output_invalid")
    checkpoint_path = output / "checkpoint.json"
    resolved, raw = _stable_read(
        checkpoint_path,
        label="sharded_checkpoint",
        require_private=True,
    )
    if resolved != checkpoint_path:
        raise FinalizationError("sharded_checkpoint_path_invalid")
    value = _load_json(raw, label="sharded_checkpoint")
    if not isinstance(value, dict):
        raise FinalizationError("sharded_checkpoint_invalid")
    if expected_value is not None and value != expected_value:
        raise FinalizationError("sharded_checkpoint_publish_mismatch")
    validated = validate_sharded_checkpoint(
        value,
        deployment_id=prepared.config.deployment_id,
    )
    endpoint_sha256 = hashlib.sha256(canonical_json(prepared.route_binding.endpoint)).hexdigest()
    proxy_policy_sha256 = hashlib.sha256(canonical_json(prepared.route_binding.proxy_policy)).hexdigest()
    if (
        value.get("shards") != list(evidence.shard_records)
        or value.get("plan")
        != {
            "path": str(prepared.plan_artifact.path),
            "sha256": prepared.plan_artifact.sha256,
            "plan_sha256": prepared.plan["plan_sha256"],
        }
        or value.get("distinct_route_generations") != 1
        or value.get("combined_trace_count") != EXPECTED_TASK_COUNT
        or validated.get("shard_count") != EXPECTED_TASK_COUNT
        or validated.get("supported_passes") != evidence.solved_count
        or validated.get("route_generation_sha256s") != [prepared.generation_sha256]
        or validated.get("endpoint_binding_sha256s") != [endpoint_sha256]
        or validated.get("proxy_policy_sha256") != proxy_policy_sha256
        or validated.get("deployment_spec_sha256") != prepared.deployment_spec.sha256
    ):
        raise FinalizationError("sharded_checkpoint_controller_mismatch")
    return validated, raw


def _finalize_locked(
    config: FinalizerConfig,
    *,
    command_runner: Callable[..., Any],
) -> dict[str, Any]:
    prepared = prepare_train(config.controller, command_runner=command_runner)
    if (
        prepared.config.wave_size != EXPECTED_WAVE_SIZE
        or prepared.selected_indices != tuple(range(EXPECTED_TASK_COUNT))
        or len(prepared.shards) != EXPECTED_TASK_COUNT
        or any(shard.task_count != 1 for shard in prepared.shards)
    ):
        raise FinalizationError("full_singleton_plan_required")
    evidence = _collect_controller_evidence(prepared, config.expected_train_sha256)
    output = _resolved_output(config.output_dir, prepared)
    reused_existing = output.exists()
    published: Mapping[str, Any] | None = None
    if not reused_existing:
        published = merge_shards(
            prepared.plan_artifact.path,
            evidence.receipt_paths,
            output_dir=output,
            dataset_dir=prepared.dataset_path,
            min_supported_pass_rate=EXPECTED_MIN_SUPPORTED_PASS_RATE,
            max_supported_pass_rate=EXPECTED_MAX_SUPPORTED_PASS_RATE,
            max_sequence_tokens=DEFAULT_MAX_SEQUENCE_TOKENS,
        )
    validated, checkpoint_raw = _load_and_validate_checkpoint(
        output,
        prepared,
        evidence,
        expected_value=published,
    )
    return {
        "state": "passed",
        "reused_existing": reused_existing,
        "combined_trace_count": EXPECTED_TASK_COUNT,
        "supported_tasks": evidence.supported_count,
        "cpu_unsupported_tasks": evidence.unsupported_count,
        "supported_passes": validated["supported_passes"],
        "supported_pass_rate": validated["supported_pass_rate"],
        "all_task_pass_rate": validated["all_task_pass_rate"],
        "distinct_route_generations": 1,
        "tb4_certificate_sha256": validated["certificate_sha256"],
        "checkpoint_file_sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
        "controller_state_sha256": evidence.state["state_sha256"],
    }


def finalize_wave_train(
    config: FinalizerConfig,
    *,
    command_runner: Callable[..., Any],
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> dict[str, Any]:
    """Wait, lock, revalidate, merge once, and return aggregate-only evidence."""

    wait_for_complete_state(config, sleep=sleep, clock=clock)
    root = _validate_controller_root(config.controller.controller_root)
    started = clock()
    while True:
        entered = False
        try:
            with _controller_lock(root):
                entered = True
                return _finalize_locked(config, command_runner=command_runner)
        except WaveTrainError as error:
            if not entered and str(error) == "controller_already_running":
                if clock() - started >= config.lock_timeout_seconds:
                    raise FinalizationError("controller_lock_timeout") from error
                sleep(config.lock_poll_seconds)
                continue
            raise FinalizationError(_safe_error(str(error))) from error


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-root", type=Path, required=True)
    parser.add_argument("--train-sha256")
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
    parser.add_argument("--smoke-checkpoint", type=Path)
    parser.add_argument("--smoke-checkpoint-sha256")
    parser.add_argument(
        "--smoke-checkpoint-candidate",
        type=Path,
        action="append",
        help="trusted possible winner path; repeat for race participants",
    )
    dataset = parser.add_mutually_exclusive_group(required=True)
    dataset.add_argument("--dataset-revision")
    dataset.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--dataset-archive-sha256")
    parser.add_argument("--dataset-content-sha256")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wave-size", type=int, default=EXPECTED_WAVE_SIZE)
    parser.add_argument("--controller-poll-interval-seconds", type=_positive_float, default=15.0)
    parser.add_argument("--wait-for-completion", action="store_true")
    parser.add_argument("--wait-poll-seconds", type=_positive_float, default=DEFAULT_WAIT_POLL_SECONDS)
    parser.add_argument("--wait-timeout-seconds", type=_positive_float)
    parser.add_argument("--lock-poll-seconds", type=_positive_float, default=DEFAULT_LOCK_POLL_SECONDS)
    parser.add_argument("--lock-timeout-seconds", type=_positive_float, default=DEFAULT_LOCK_TIMEOUT_SECONDS)
    return parser


def _candidate_config_from_args(args: argparse.Namespace) -> CandidateControllerConfig:
    return CandidateControllerConfig(
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
        smoke_checkpoint_candidates=tuple(args.smoke_checkpoint_candidate or ()),
        dataset_revision=args.dataset_revision,
        dataset_archive_path=args.dataset_archive,
        dataset_archive_sha256=args.dataset_archive_sha256,
        dataset_content_sha256=args.dataset_content_sha256,
        wave_size=args.wave_size,
        controller_poll_interval_seconds=args.controller_poll_interval_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    candidate_mode = bool(args.smoke_checkpoint_candidate)
    explicit_values = (
        args.train_sha256,
        args.smoke_checkpoint,
        args.smoke_checkpoint_sha256,
    )
    if candidate_mode:
        if any(value is not None for value in explicit_values):
            parser.error("candidate mode cannot use explicit smoke/train arguments")
        if not args.wait_for_completion:
            parser.error("candidate mode requires --wait-for-completion")
    elif any(value is None for value in explicit_values):
        parser.error("explicit mode requires --train-sha256 and the smoke checkpoint path/hash")
    try:
        candidate_config = _candidate_config_from_args(args)
        if candidate_mode:
            controller, train_sha256 = resolve_candidate_controller(
                candidate_config,
                wait_poll_seconds=args.wait_poll_seconds,
                wait_timeout_seconds=args.wait_timeout_seconds,
                command_runner=subprocess.run,
            )
        else:
            assert args.smoke_checkpoint is not None
            assert args.smoke_checkpoint_sha256 is not None
            assert args.train_sha256 is not None
            controller = _candidate_controller(
                candidate_config,
                args.smoke_checkpoint,
                args.smoke_checkpoint_sha256,
            )
            train_sha256 = args.train_sha256
        config = FinalizerConfig(
            controller=controller,
            expected_train_sha256=train_sha256,
            output_dir=args.output_dir,
            wait_for_completion=args.wait_for_completion,
            wait_poll_seconds=args.wait_poll_seconds,
            wait_timeout_seconds=args.wait_timeout_seconds,
            lock_poll_seconds=args.lock_poll_seconds,
            lock_timeout_seconds=args.lock_timeout_seconds,
        )
        summary = finalize_wave_train(config, command_runner=subprocess.run)
    except (OSError, FinalizationError, ShardWorkflowError, WaveTrainError) as error:
        print(f"tb4_wave_train_finalize_error:{_safe_error(str(error))}", file=sys.stderr)
        return 2
    except Exception:
        print("tb4_wave_train_finalize_error:finalization_failed", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
