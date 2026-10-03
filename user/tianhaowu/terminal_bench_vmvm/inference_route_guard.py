#!/usr/bin/env python3
"""Run an evaluator only while its readiness-bound endpoint jobs remain serving."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    request_timeout_for_model,
    revalidate_deployment_proxy_policy,
    validate_deployment_spec_proxy_policy,
    validate_proxy_policy_binding,
    validate_worker_rotation_proxy_configs,
)
from eval_run_identity import EvalIdentityError, load_eval_run_identity
from guard_success_receipt import (
    GuardReceiptError,
    build_guard_success_receipt,
    stable_sha256_file,
    validate_eval_invocations,
    write_guard_success_receipt,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    EVAL_IDENTITY_ENV as TELEMETRY_EVAL_IDENTITY_ENV,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    EVAL_ROLE_ENV as TELEMETRY_EVAL_ROLE_ENV,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    SLURM_JOB_ID_ENV as TELEMETRY_SLURM_JOB_ID_ENV,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import (
    TELEMETRY_PATH_ENV,
)
from wait_for_inference_routes import (
    DEFAULT_SERVE_SH,
    GateConfig,
    GateError,
    ProcessResult,
    _parse_status,
    _run_process,
    _status_command,
)

POLL_INTERVAL_SECONDS = 10.0
STATUS_TIMEOUT_SECONDS = 30.0
TERMINATE_TIMEOUT_SECONDS = 10.0
COORDINATOR_STALL_TIMEOUT_SECONDS = 30.0
PROCESS_GROUP_POLL_SECONDS = 0.05
MAX_READINESS_BYTES = 16 * 1024 * 1024


class RouteGuardError(RuntimeError):
    """The live endpoint jobs no longer match the readiness generation."""


@dataclass(frozen=True)
class RouteBinding:
    deployment_id: str
    deployment_spec: Path
    deployment_spec_sha256: str
    readiness_checkpoint: Path
    readiness_checkpoint_sha256: str
    proxy_info: Path
    proxy_info_sha256: str
    expected_model: str
    endpoint: dict[str, Any]
    proxy_policy: dict[str, Any]
    expected_routes: int
    route_generation: dict[str, Any]
    minimum_coord_ticks_completed: int


@dataclass(frozen=True)
class GuardReceiptPlan:
    receipt: Path
    eval_run_identity: Path
    eval_run_identity_sha256: str
    eval_run_role: str
    eval_run_identity_file_sha256: str
    eval_invocations: Path
    eval_invocations_sha256: str
    results: Path
    sandbox_provider: str
    concurrency_telemetry: Path | None
    slurm_job_id: str


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RouteGuardError("readiness_checkpoint_invalid")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise RouteGuardError("readiness_checkpoint_invalid")


def _sha256_file(path: Path, *, label: str, limit: int | None = None) -> tuple[str, bytes | None]:
    digest = hashlib.sha256()
    payload = bytearray() if limit is not None else None
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise RouteGuardError(f"{label}_unreadable")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if payload is not None:
                    payload.extend(chunk)
                    if len(payload) > limit:
                        raise RouteGuardError(f"{label}_too_large")
        after = path.stat()
    except OSError as error:
        raise RouteGuardError(f"{label}_unreadable") from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RouteGuardError(f"{label}_changed")
    return digest.hexdigest(), bytes(payload) if payload is not None else None


def load_route_binding(
    *,
    deployment_id: str,
    deployment_spec: Path,
    deployment_spec_sha256: str,
    readiness_checkpoint: Path,
    readiness_checkpoint_sha256: str,
    proxy_info: Path,
    proxy_info_sha256: str,
    expected_model: str,
    proxy_config_snapshot: Path | None = None,
    proxy_config_snapshot_sha256: str | None = None,
) -> RouteBinding:
    """Load the externally pinned readiness generation without endpoint secrets."""

    try:
        resolved_spec = deployment_spec.resolve(strict=True)
        resolved_readiness = readiness_checkpoint.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RouteGuardError("route_binding_unreadable") from error
    observed_spec, _ = _sha256_file(resolved_spec, label="deployment_spec")
    if observed_spec != deployment_spec_sha256:
        raise RouteGuardError("deployment_spec_sha256_mismatch")
    observed_readiness, raw = _sha256_file(
        resolved_readiness,
        label="readiness_checkpoint",
        limit=MAX_READINESS_BYTES,
    )
    if observed_readiness != readiness_checkpoint_sha256 or raw is None:
        raise RouteGuardError("readiness_checkpoint_sha256_mismatch")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
        generation = validate_readiness_route_generation(
            payload,
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec_sha256,
        )
        readiness_endpoint = validate_endpoint_binding(payload.get("endpoint"))
        expected_request_timeout = request_timeout_for_model(expected_model)
        proxy_policy = validate_proxy_policy_binding(
            payload.get("proxy_policy"),
            expected_request_timeout=expected_request_timeout,
        )
        if proxy_config_snapshot is None and proxy_config_snapshot_sha256 is None:
            revalidate_deployment_proxy_policy(
                resolved_spec,
                expected_spec_sha256=deployment_spec_sha256,
                expected_binding=proxy_policy,
                expected_request_timeout=expected_request_timeout,
            )
        elif proxy_config_snapshot is None or proxy_config_snapshot_sha256 is None:
            raise RouteGuardError("proxy_config_snapshot_invalid")
        else:
            if proxy_policy["proxy_litellm_config"]["sha256"] != proxy_config_snapshot_sha256:
                raise RouteGuardError("proxy_config_snapshot_sha256_mismatch")
            validate_deployment_spec_proxy_policy(
                resolved_spec,
                expected_spec_sha256=deployment_spec_sha256,
                expected_request_timeout=expected_request_timeout,
            )
            generation_routes = generation.get("routes")
            backends = (
                [
                    route.get("backend_sha256")
                    for route in generation_routes
                    if isinstance(route, dict) and isinstance(route.get("backend_sha256"), str)
                ]
                if isinstance(generation_routes, list)
                else []
            )
            validate_worker_rotation_proxy_configs(
                source_snapshot=proxy_config_snapshot,
                source_binding=proxy_policy,
                source_backends=backends,
                target_snapshot=proxy_config_snapshot,
                target_binding=proxy_policy,
                target_backends=backends,
            )
        endpoint = load_deployment_endpoint(
            proxy_info,
            expected_proxy_info_sha256=proxy_info_sha256,
            deployment_id=deployment_id,
            expected_model=expected_model,
            deployment_spec=resolved_spec,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RouteGenerationError,
        EndpointBindingError,
        DeploymentProxyPolicyError,
    ) as error:
        raise RouteGuardError("readiness_checkpoint_invalid") from error
    if endpoint.binding != readiness_endpoint:
        raise RouteGuardError("readiness_endpoint_mismatch")
    if endpoint.proxy_job_id != generation["proxy"]["slurm_job_id"]:
        raise RouteGuardError("readiness_endpoint_mismatch")
    expected_routes = payload.get("expected_routes")
    last_status = payload.get("last_status")
    if not isinstance(last_status, dict):
        raise RouteGuardError("readiness_checkpoint_invalid")
    minimum_coord_ticks_completed = last_status.get("coord_ticks_completed")
    if (
        not isinstance(minimum_coord_ticks_completed, int)
        or isinstance(minimum_coord_ticks_completed, bool)
        or minimum_coord_ticks_completed < 0
    ):
        raise RouteGuardError("readiness_checkpoint_invalid")
    return RouteBinding(
        deployment_id=deployment_id,
        deployment_spec=resolved_spec,
        deployment_spec_sha256=deployment_spec_sha256,
        readiness_checkpoint=resolved_readiness,
        readiness_checkpoint_sha256=readiness_checkpoint_sha256,
        proxy_info=endpoint.proxy_info_path,
        proxy_info_sha256=proxy_info_sha256,
        expected_model=expected_model,
        endpoint=endpoint.binding,
        proxy_policy=proxy_policy,
        expected_routes=expected_routes,
        route_generation=generation,
        minimum_coord_ticks_completed=minimum_coord_ticks_completed,
    )


def prepare_guard_receipt(
    binding: RouteBinding,
    *,
    eval_run_identity: Path,
    eval_run_identity_sha256: str,
    eval_invocations: Path,
    results: Path,
    receipt: Path,
) -> GuardReceiptPlan:
    """Validate immutable run metadata and remove any stale success receipt."""

    try:
        identity_path, identity_file_sha256 = stable_sha256_file(
            eval_run_identity,
            label="eval_run_identity",
        )
        invocations_path, invocations_sha256 = stable_sha256_file(
            eval_invocations,
            label="eval_invocations",
        )
        run_dir = identity_path.parent
        results_path = run_dir / "results.jsonl"
        receipt_path = run_dir / "route_guard_success.json"
        if (
            invocations_path != run_dir / "eval_invocations.jsonl"
            or results.parent.resolve(strict=True) != run_dir
            or results.name != results_path.name
            or receipt.parent.resolve(strict=True) != run_dir
            or receipt.name != receipt_path.name
        ):
            raise RouteGuardError("guard_receipt_path_mismatch")
        envelope = load_eval_run_identity(identity_path, verify_references=True)
    except (OSError, RuntimeError, EvalIdentityError, GuardReceiptError) as error:
        raise RouteGuardError("guard_receipt_binding_invalid") from error
    identity = envelope.get("identity")
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    source = identity.get("source") if isinstance(identity, dict) else None
    eval_run_role = identity.get("role") if isinstance(identity, dict) else None
    sandbox_provider = source.get("sandbox_provider", "vmvm") if isinstance(source, dict) else None
    if (
        envelope.get("eval_run_identity_sha256") != eval_run_identity_sha256
        or sandbox_provider not in {"vmvm", "sandoq"}
        or not isinstance(deployment, dict)
        or deployment.get("id") != binding.deployment_id
        or deployment.get("spec")
        != {
            "path": str(binding.deployment_spec),
            "sha256": binding.deployment_spec_sha256,
        }
        or deployment.get("readiness_checkpoint")
        != {
            "path": str(binding.readiness_checkpoint),
            "sha256": binding.readiness_checkpoint_sha256,
        }
        or deployment.get("endpoint") != binding.endpoint
        or deployment.get("serving_route_generation") != binding.route_generation
        or deployment.get("proxy_policy") != binding.proxy_policy
    ):
        raise RouteGuardError("guard_receipt_binding_invalid")
    try:
        invocation, invocation_artifact = validate_eval_invocations(
            invocations_path,
            eval_run_identity_sha256=eval_run_identity_sha256,
            eval_run_role=eval_run_role,
        )
    except GuardReceiptError as error:
        raise RouteGuardError("eval_invocations_invalid") from error
    if invocation_artifact["sha256"] != invocations_sha256:
        raise RouteGuardError("eval_invocations_changed")
    try:
        receipt_path.unlink(missing_ok=True)
    except OSError as error:
        raise RouteGuardError("stale_guard_receipt_remove_failed") from error
    if receipt_path.exists():
        raise RouteGuardError("stale_guard_receipt_remove_failed")
    telemetry_path = run_dir / "concurrency_telemetry.json"
    if os.path.lexists(telemetry_path):
        raise RouteGuardError("concurrency_telemetry_already_exists")
    concurrency_telemetry = telemetry_path if sandbox_provider == "vmvm" else None
    return GuardReceiptPlan(
        receipt=receipt_path,
        eval_run_identity=identity_path,
        eval_run_identity_sha256=eval_run_identity_sha256,
        eval_run_role=eval_run_role,
        eval_run_identity_file_sha256=identity_file_sha256,
        eval_invocations=invocations_path,
        eval_invocations_sha256=invocations_sha256,
        results=results_path,
        sandbox_provider=sandbox_provider,
        concurrency_telemetry=concurrency_telemetry,
        slurm_job_id=invocation["slurm_job_id"],
    )


def configure_concurrency_telemetry_environment(plan: GuardReceiptPlan) -> None:
    """Expose VMVM telemetry bindings, or remove them for non-VMVM evaluators."""

    environment_names = (
        TELEMETRY_PATH_ENV,
        TELEMETRY_EVAL_IDENTITY_ENV,
        TELEMETRY_EVAL_ROLE_ENV,
        TELEMETRY_SLURM_JOB_ID_ENV,
    )
    if plan.sandbox_provider == "sandoq":
        if plan.concurrency_telemetry is not None:
            raise RouteGuardError("concurrency_telemetry_provider_mismatch")
        for name in environment_names:
            os.environ.pop(name, None)
        return
    if plan.sandbox_provider != "vmvm" or plan.concurrency_telemetry is None:
        raise RouteGuardError("concurrency_telemetry_provider_mismatch")
    os.environ[TELEMETRY_PATH_ENV] = str(plan.concurrency_telemetry)
    os.environ[TELEMETRY_EVAL_IDENTITY_ENV] = plan.eval_run_identity_sha256
    os.environ[TELEMETRY_EVAL_ROLE_ENV] = plan.eval_run_role
    os.environ[TELEMETRY_SLURM_JOB_ID_ENV] = plan.slurm_job_id


def publish_guard_success_receipt(
    binding: RouteBinding,
    plan: GuardReceiptPlan,
) -> None:
    """Publish success only if all pre-run metadata and final results are stable."""

    try:
        _, identity_sha256 = stable_sha256_file(
            plan.eval_run_identity,
            label="eval_run_identity",
        )
        _, invocations_sha256 = stable_sha256_file(
            plan.eval_invocations,
            label="eval_invocations",
        )
        if identity_sha256 != plan.eval_run_identity_file_sha256 or invocations_sha256 != plan.eval_invocations_sha256:
            raise RouteGuardError("guard_receipt_metadata_changed")
        receipt = build_guard_success_receipt(
            eval_run_identity_sha256=plan.eval_run_identity_sha256,
            eval_run_role=plan.eval_run_role,
            eval_run_identity=plan.eval_run_identity,
            eval_invocations=plan.eval_invocations,
            results=plan.results,
            deployment_id=binding.deployment_id,
            deployment_spec_sha256=binding.deployment_spec_sha256,
            readiness_checkpoint=binding.readiness_checkpoint,
            readiness_checkpoint_sha256=binding.readiness_checkpoint_sha256,
            endpoint=binding.endpoint,
            serving_route_generation=binding.route_generation,
            proxy_policy=binding.proxy_policy,
            concurrency_telemetry=plan.concurrency_telemetry,
        )
        if (
            receipt["artifacts"]["eval_run_identity"]["sha256"] != plan.eval_run_identity_file_sha256
            or receipt["artifacts"]["eval_invocations"]["sha256"] != plan.eval_invocations_sha256
        ):
            raise RouteGuardError("guard_receipt_metadata_changed")
        telemetry_artifact = receipt["artifacts"].get("concurrency_telemetry")
        if plan.concurrency_telemetry is None:
            if telemetry_artifact is not None:
                raise RouteGuardError("guard_receipt_metadata_changed")
        elif (
            not isinstance(telemetry_artifact, dict)
            or telemetry_artifact.get("path") != str(plan.concurrency_telemetry)
        ):
            raise RouteGuardError("guard_receipt_metadata_changed")
        write_guard_success_receipt(plan.receipt, receipt)
    except GuardReceiptError as error:
        raise RouteGuardError("guard_receipt_publish_failed") from error


def verify_live_route_generation(
    binding: RouteBinding,
    *,
    runner: Callable[[Sequence[str], float], ProcessResult] = _run_process,
    serve_sh: Path = DEFAULT_SERVE_SH,
) -> int:
    """Fail unless the current exact serving job set matches the bound generation."""

    observed_spec, _ = _sha256_file(binding.deployment_spec, label="deployment_spec")
    observed_readiness, _ = _sha256_file(
        binding.readiness_checkpoint,
        label="readiness_checkpoint",
    )
    if observed_spec != binding.deployment_spec_sha256:
        raise RouteGuardError("deployment_spec_changed")
    if observed_readiness != binding.readiness_checkpoint_sha256:
        raise RouteGuardError("readiness_checkpoint_changed")
    try:
        endpoint = load_deployment_endpoint(
            binding.proxy_info,
            expected_proxy_info_sha256=binding.proxy_info_sha256,
            deployment_id=binding.deployment_id,
            expected_model=binding.expected_model,
            deployment_spec=binding.deployment_spec,
        )
    except EndpointBindingError as error:
        raise RouteGuardError("deployment_endpoint_changed") from error
    if endpoint.binding != binding.endpoint:
        raise RouteGuardError("deployment_endpoint_changed")
    if endpoint.proxy_job_id != binding.route_generation["proxy"]["slurm_job_id"]:
        raise RouteGuardError("deployment_endpoint_changed")
    try:
        revalidate_deployment_proxy_policy(
            binding.deployment_spec,
            expected_spec_sha256=binding.deployment_spec_sha256,
            expected_binding=binding.proxy_policy,
            expected_request_timeout=request_timeout_for_model(binding.expected_model),
        )
    except DeploymentProxyPolicyError as error:
        raise RouteGuardError("deployment_proxy_policy_changed") from error
    config = GateConfig(
        deployment=binding.deployment_id,
        expected_spec_sha256=binding.deployment_spec_sha256,
        expected_routes=binding.expected_routes,
        model=binding.expected_model,
        serve_sh=serve_sh,
        spec=binding.deployment_spec,
        output=Path("unused-route-guard-output.json"),
    )
    try:
        status = _parse_status(
            runner(_status_command(config), STATUS_TIMEOUT_SECONDS),
            binding.deployment_id,
        )
    except GateError as error:
        raise RouteGuardError("serving_route_status_invalid") from error
    observed_generation = status.serving_route_generation
    if not status.is_exactly_ready(binding.expected_routes) or observed_generation != binding.route_generation:
        raise RouteGuardError("serving_route_generation_changed")
    ticks = status.coord_ticks_completed
    if ticks is None or ticks < binding.minimum_coord_ticks_completed:
        raise RouteGuardError("coordinator_ticks_regressed")
    return ticks


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise RouteGuardError("evaluator_process_group_uninspectable") from error
    return True


def _wait_process_group_gone(process_group_id: int, deadline: float) -> bool:
    while _process_group_exists(process_group_id):
        if time.monotonic() >= deadline:
            return False
        time.sleep(PROCESS_GROUP_POLL_SECONDS)
    return True


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATE_TIMEOUT_SECONDS
    if process.poll() is None:
        try:
            process.wait(timeout=TERMINATE_TIMEOUT_SECONDS / 2)
        except subprocess.TimeoutExpired:
            pass
    if _wait_process_group_gone(process_group_id, deadline):
        return
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return
    kill_deadline = time.monotonic() + TERMINATE_TIMEOUT_SECONDS / 2
    if process.poll() is None:
        try:
            process.wait(timeout=TERMINATE_TIMEOUT_SECONDS / 2)
        except subprocess.TimeoutExpired:
            pass
    if not _wait_process_group_gone(process_group_id, kill_deadline):
        raise RouteGuardError("evaluator_process_group_cleanup_failed")


def run_guarded(
    command: Sequence[str],
    binding: RouteBinding,
    *,
    verifier: Callable[[RouteBinding], int | None] = verify_live_route_generation,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    coordinator_stall_timeout: float = COORDINATOR_STALL_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    success_callback: Callable[[], None] | None = None,
) -> int:
    """Supervise one evaluator process group and return only a route-valid exit code."""

    if (
        not command
        or not math.isfinite(poll_interval)
        or poll_interval <= 0
        or not math.isfinite(coordinator_stall_timeout)
        or coordinator_stall_timeout <= poll_interval
    ):
        raise RouteGuardError("guard_configuration_invalid")
    last_coord_ticks = verifier(binding)
    last_coord_progress_at = monotonic()
    previous_handlers: dict[signal.Signals, Any] = {}
    termination_requested = False

    def handle_termination(_signum: int, _frame: Any) -> None:
        nonlocal termination_requested
        if termination_requested:
            return
        termination_requested = True
        raise RouteGuardError("guard_interrupted")

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handle_termination)
    except (OSError, RuntimeError, ValueError) as error:
        for sig, previous_handler in previous_handlers.items():
            signal.signal(sig, previous_handler)
        raise RouteGuardError("guard_signal_setup_failed") from error
    process: subprocess.Popen[Any] | None = None
    try:
        try:
            process = subprocess.Popen(list(command), start_new_session=True)
        except OSError as error:
            raise RouteGuardError("evaluator_start_failed") from error
        while True:
            try:
                returncode = process.wait(timeout=poll_interval)
            except subprocess.TimeoutExpired:
                observed_ticks = verifier(binding)
                observed_at = monotonic()
                if observed_ticks is not None and last_coord_ticks is not None:
                    if observed_ticks < last_coord_ticks:
                        raise RouteGuardError("coordinator_ticks_regressed")
                    if observed_ticks == last_coord_ticks:
                        if observed_at - last_coord_progress_at >= coordinator_stall_timeout:
                            raise RouteGuardError("coordinator_ticks_not_advancing")
                    else:
                        last_coord_progress_at = observed_at
                if observed_ticks is not None:
                    last_coord_ticks = observed_ticks
                continue
            if _process_group_exists(process.pid):
                termination_requested = True
                _terminate_process_group(process)
                raise RouteGuardError("evaluator_process_group_survived")
            observed_ticks = verifier(binding)
            observed_at = monotonic()
            if observed_ticks is not None and last_coord_ticks is not None:
                if observed_ticks < last_coord_ticks:
                    raise RouteGuardError("coordinator_ticks_regressed")
                if (
                    observed_ticks == last_coord_ticks
                    and observed_at - last_coord_progress_at >= coordinator_stall_timeout
                ):
                    raise RouteGuardError("coordinator_ticks_not_advancing")
            if returncode == 0 and success_callback is not None:
                success_callback()
            return returncode
    except BaseException:
        termination_requested = True
        if process is not None:
            _terminate_process_group(process)
        raise
    finally:
        for sig, previous_handler in previous_handlers.items():
            signal.signal(sig, previous_handler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--deployment-spec", type=Path, required=True)
    parser.add_argument("--deployment-spec-sha256", required=True)
    parser.add_argument("--readiness-checkpoint", type=Path, required=True)
    parser.add_argument("--readiness-checkpoint-sha256", required=True)
    parser.add_argument("--proxy-info", type=Path, required=True)
    parser.add_argument("--proxy-info-sha256", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--eval-run-identity", type=Path, required=True)
    parser.add_argument("--eval-run-identity-sha256", required=True)
    parser.add_argument("--eval-invocations", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--success-receipt", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> None:
    args = _parser().parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        binding = load_route_binding(
            deployment_id=args.deployment_id,
            deployment_spec=args.deployment_spec,
            deployment_spec_sha256=args.deployment_spec_sha256,
            readiness_checkpoint=args.readiness_checkpoint,
            readiness_checkpoint_sha256=args.readiness_checkpoint_sha256,
            proxy_info=args.proxy_info,
            proxy_info_sha256=args.proxy_info_sha256,
            expected_model=args.expected_model,
        )
        receipt_plan = prepare_guard_receipt(
            binding,
            eval_run_identity=args.eval_run_identity,
            eval_run_identity_sha256=args.eval_run_identity_sha256,
            eval_invocations=args.eval_invocations,
            results=args.results,
            receipt=args.success_receipt,
        )
        configure_concurrency_telemetry_environment(receipt_plan)
        returncode = run_guarded(
            command,
            binding,
            success_callback=lambda: publish_guard_success_receipt(
                binding,
                receipt_plan,
            ),
        )
    except RouteGuardError as error:
        print(f"route_generation_guard_error:{error}", file=sys.stderr)
        raise SystemExit(2) from error
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
