#!/usr/bin/env python3
"""Fail-closed readiness gate for a RAM serve-api-v2 deployment.

The gate intentionally owns the exact semantic-probe invocation.  Callers may
tune bounded workload parameters, but cannot pass arbitrary probe arguments or
disable health, sticky-affinity, reasoning, or corruption checks.

All proxy environment variables are removed from child processes. The status
and probe traffic must reach the same-cluster coordinator/proxy directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from deployment_endpoint import (
    DeploymentEndpoint,
    EndpointBindingError,
    load_deployment_endpoint,
)
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    load_deployment_proxy_policy,
    request_timeout_for_model,
    revalidate_deployment_proxy_policy,
    validate_deployment_spec_proxy_policy,
)
from inference_route_generation import (
    RouteGenerationError,
    coordinator_incarnation_from_status,
    route_generation_from_status_endpoints,
)

DEFAULT_SERVE_SH = Path("/storage/home/tianhaowu/ram_common/vllm_tools/serve_api_v2/serve.sh")
DEFAULT_DEPLOYMENT_ROOT = Path("/checkpoint/ram/shared/vllm_deployments_v2")
DEFAULT_PROBE_SCRIPT = Path(__file__).with_name("probe_inference_routes.py")
DEPLOYMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TERMINAL_PHASES = frozenset(
    {
        "cancelled",
        "canceled",
        "dead",
        "expired",
        "failed",
        "stopped",
        "terminated",
    }
)
LIVE_PHASES = frozenset({"booting", "draining", "serving"})
STATUS_PATH = "/usr/bin:/bin"
BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s\"']+")
SENSITIVE_RESULT_KEY_FRAGMENTS = frozenset(
    {
        "api_key",
        "authorization",
        "credentials",
        "proxy_base_url",
        "proxy_info",
        "secret",
    }
)


class GateError(RuntimeError):
    """Expected gate failure with a stable, non-secret reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StatusUnavailable(GateError):
    """A retryable rc=1 status response that did not contain a valid snapshot."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str = ""


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str], timeout: float) -> ProcessResult: ...


@dataclass(frozen=True)
class StatusObservation:
    schema_version: int
    deployment_id: str
    phase: str
    desired: int
    ready: int
    running_not_ready: int
    pending: int
    coordinator_incarnation: dict[str, str] | None
    coord_ticks_completed: int | None
    serving_route_generation: dict[str, Any] | None

    def is_exactly_ready(self, expected_routes: int) -> bool:
        return (
            self.phase == "serving"
            and self.desired == expected_routes
            and self.ready == expected_routes
            and self.running_not_ready == 0
            and self.pending == 0
            and isinstance(self.coordinator_incarnation, dict)
            and isinstance(self.coord_ticks_completed, int)
            and isinstance(self.serving_route_generation, dict)
            and len(self.serving_route_generation.get("routes", [])) == expected_routes
        )


@dataclass(frozen=True)
class GateConfig:
    deployment: str
    expected_spec_sha256: str
    expected_routes: int = 24
    model: str = "Kimi-K3"
    serve_sh: Path = DEFAULT_SERVE_SH
    probe_script: Path = DEFAULT_PROBE_SCRIPT
    spec: Path | None = None
    proxy_info: Path | None = None
    output: Path | None = None
    consecutive_polls: int = 3
    max_status_unavailable: int = 10
    poll_interval: float = 60.0
    wait_timeout: float = 72 * 60 * 60
    status_command_timeout: float = 30.0
    probe_process_timeout: float = 2 * 60 * 60
    probe_requests: int | None = None
    probe_repeats: int = 3
    probe_concurrency: int | None = None
    probe_request_timeout: float = 300.0
    probe_health_timeout: float = 30.0
    probe_max_tokens: int = 4096
    repeated_char_threshold: int = 8

    def resolved_proxy_info(self) -> Path:
        return self.proxy_info or (DEFAULT_DEPLOYMENT_ROOT / self.deployment / "proxy_info.json")

    def resolved_spec(self) -> Path:
        return self.spec or (DEFAULT_DEPLOYMENT_ROOT / self.deployment / "spec.yaml")

    def resolved_output(self) -> Path:
        return self.output or Path(f"readiness-{self.deployment}.json")

    def resolved_probe_requests(self) -> int:
        if self.probe_requests is not None:
            return self.probe_requests
        return self.expected_routes * 8

    def resolved_probe_concurrency(self) -> int:
        if self.probe_concurrency is not None:
            return self.probe_concurrency
        return self.expected_routes


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in environ.items() if not key.casefold().endswith("_proxy")}


def _run_process(argv: Sequence[str], timeout: float) -> ProcessResult:
    child_env = _child_environment(os.environ)
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=child_env,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError("command_timeout") from exc
    except OSError as exc:
        raise GateError("command_unavailable") from exc
    return ProcessResult(completed.returncode, completed.stdout, completed.stderr)


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GateError(f"malformed_status_{field}")
    return value


def _status_problem(result: ProcessResult, reason: str) -> GateError:
    if result.returncode == 1:
        return StatusUnavailable(reason)
    return GateError(reason)


def _parse_status(result: ProcessResult, deployment: str) -> StatusObservation:
    if result.returncode not in {0, 1}:
        raise GateError("status_command_failed")
    if not result.stdout.strip():
        raise _status_problem(result, "empty_status_stdout")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _status_problem(result, "malformed_status_json") from exc
    if payload is None:
        raise _status_problem(result, "null_status")
    if not isinstance(payload, dict):
        raise _status_problem(result, "malformed_status_root")

    phase = payload.get("phase")
    if not isinstance(phase, str):
        raise _status_problem(result, "malformed_status_phase")
    phase = phase.casefold()
    if phase in TERMINAL_PHASES:
        raise GateError("terminal_deployment")

    observed_deployment = payload.get("deployment_id")
    if observed_deployment != deployment:
        raise _status_problem(result, "malformed_status_deployment_id")
    try:
        schema_version = _nonnegative_int(payload.get("schema_version"), "schema_version")
    except GateError as exc:
        raise _status_problem(result, exc.reason) from exc
    if schema_version != 4:
        raise _status_problem(result, "unsupported_status_schema_version")
    if phase not in LIVE_PHASES:
        raise _status_problem(result, "malformed_status_phase")
    expected_returncode = 0 if phase == "serving" else 1
    if result.returncode != expected_returncode:
        raise _status_problem(result, "inconsistent_status_exit_code")

    summary = payload.get("endpoints_summary")
    if not isinstance(summary, dict):
        raise _status_problem(result, "malformed_status_endpoints_summary")
    try:
        desired = _nonnegative_int(summary.get("desired"), "desired")
        ready = _nonnegative_int(summary.get("ready"), "ready")
        running_not_ready = _nonnegative_int(summary.get("running_not_ready"), "running_not_ready")
        pending = _nonnegative_int(summary.get("pending"), "pending")
    except GateError as exc:
        raise _status_problem(result, exc.reason) from exc
    ticks: int | None = None
    coordinator_incarnation: dict[str, str] | None = None
    coord = payload.get("coord")
    if coord is not None:
        if not isinstance(coord, dict):
            raise _status_problem(result, "malformed_status_coord")
        try:
            ticks = _nonnegative_int(coord.get("ticks_completed"), "ticks_completed")
            coordinator_incarnation = coordinator_incarnation_from_status(coord)
        except GateError as exc:
            raise _status_problem(result, exc.reason) from exc
        except RouteGenerationError as exc:
            raise _status_problem(result, "malformed_status_coord") from exc
    serving_route_generation: dict[str, Any] | None = None
    if phase == "serving" and desired > 0 and ready == desired and running_not_ready == 0 and pending == 0:
        try:
            serving_route_generation = route_generation_from_status_endpoints(
                payload.get("endpoints"),
                coord,
                payload.get("proxy"),
            )
        except RouteGenerationError as exc:
            raise _status_problem(result, "malformed_status_serving_endpoints") from exc
        if len(serving_route_generation["routes"]) != desired:
            raise _status_problem(result, "malformed_status_serving_endpoint_count")
    return StatusObservation(
        schema_version=schema_version,
        deployment_id=observed_deployment,
        phase=phase,
        desired=desired,
        ready=ready,
        running_not_ready=running_not_ready,
        pending=pending,
        coordinator_incarnation=coordinator_incarnation,
        coord_ticks_completed=ticks,
        serving_route_generation=serving_route_generation,
    )


def _status_record(status: StatusObservation) -> dict[str, Any]:
    """Return a strict allowlist; never copy the status proxy/spec objects."""

    return asdict(status)


def _load_endpoint(
    config: GateConfig,
    *,
    expected_proxy_info_sha256: str | None = None,
) -> DeploymentEndpoint:
    try:
        return load_deployment_endpoint(
            config.resolved_proxy_info(),
            deployment_id=config.deployment,
            expected_model=config.model,
            deployment_spec=config.resolved_spec(),
            expected_proxy_info_sha256=expected_proxy_info_sha256,
        )
    except EndpointBindingError as exc:
        raise GateError(exc.reason) from exc


def _hash_spec(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
    except OSError as exc:
        raise GateError("spec_unreadable") from exc
    return digest.hexdigest()


def _redact_text(value: str, secret: str) -> str:
    if secret:
        value = value.replace(secret, "<redacted>")
    return BEARER_RE.sub("Bearer <redacted>", value)


def _redact_result(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return _redact_text(value, secret)
    if isinstance(value, list):
        return [_redact_result(item, secret) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if any(fragment in key.casefold() for fragment in SENSITIVE_RESULT_KEY_FRAGMENTS):
                redacted[key] = "<redacted>"
            else:
                redacted[_redact_text(key, secret)] = _redact_result(item, secret)
        return redacted
    return value


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _validate_config(config: GateConfig) -> None:
    if not isinstance(config.deployment, str) or DEPLOYMENT_RE.fullmatch(config.deployment) is None:
        raise GateError("invalid_deployment")
    if not isinstance(config.model, str) or not config.model.strip():
        raise GateError("invalid_model")
    if not isinstance(config.expected_spec_sha256, str) or SHA256_RE.fullmatch(config.expected_spec_sha256) is None:
        raise GateError("invalid_expected_spec_sha256")
    integer_fields = {
        "expected_routes": config.expected_routes,
        "consecutive_polls": config.consecutive_polls,
        "probe_requests": config.resolved_probe_requests(),
        "probe_repeats": config.probe_repeats,
        "probe_concurrency": config.resolved_probe_concurrency(),
        "probe_max_tokens": config.probe_max_tokens,
    }
    for name, value in integer_fields.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise GateError(f"invalid_{name}")
    if (
        not isinstance(config.max_status_unavailable, int)
        or isinstance(config.max_status_unavailable, bool)
        or config.max_status_unavailable < 0
    ):
        raise GateError("invalid_max_status_unavailable")
    if config.resolved_probe_requests() < config.expected_routes:
        raise GateError("invalid_probe_requests")
    if (
        not isinstance(config.repeated_char_threshold, int)
        or isinstance(config.repeated_char_threshold, bool)
        or config.repeated_char_threshold < 2
    ):
        raise GateError("invalid_repeated_char_threshold")
    duration_fields = {
        "poll_interval": config.poll_interval,
        "wait_timeout": config.wait_timeout,
        "status_command_timeout": config.status_command_timeout,
        "probe_process_timeout": config.probe_process_timeout,
        "probe_request_timeout": config.probe_request_timeout,
        "probe_health_timeout": config.probe_health_timeout,
    }
    for name, value in duration_fields.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise GateError(f"invalid_{name}")
        if not math.isfinite(value) or value <= 0:
            raise GateError(f"invalid_{name}")
    if not config.serve_sh.is_file():
        raise GateError("serve_sh_unavailable")
    if not config.probe_script.is_file():
        raise GateError("probe_script_unavailable")


def _status_command(config: GateConfig) -> list[str]:
    # Never execute serve.sh here: its project virtualenv may have been
    # materialized for the login node's architecture.  The configured script
    # still pins the serve_api_v2 checkout whose source must be imported, while
    # the gate's interpreter and PYTHONPATH provide the compute-node runtime.
    serve_src = config.serve_sh.resolve().parent / "src"
    pythonpath = str(serve_src)
    if inherited_pythonpath := os.environ.get("PYTHONPATH"):
        pythonpath = os.pathsep.join((pythonpath, inherited_pythonpath))
    return [
        "/usr/bin/env",
        f"PATH={STATUS_PATH}",
        f"PYTHONPATH={pythonpath}",
        sys.executable,
        "-m",
        "serve_api_v2.cli.status",
        config.deployment,
        "--json",
    ]


def _probe_command(config: GateConfig, proxy_info_sha256: str) -> list[str]:
    return [
        sys.executable,
        str(config.probe_script),
        "--proxy-info",
        str(config.resolved_proxy_info()),
        "--proxy-info-sha256",
        proxy_info_sha256,
        "--deployment-id",
        config.deployment,
        "--deployment-spec",
        str(config.resolved_spec()),
        "--model",
        config.model,
        "--expected-routes",
        str(config.expected_routes),
        "--requests",
        str(config.resolved_probe_requests()),
        "--repeats",
        str(config.probe_repeats),
        "--concurrency",
        str(config.resolved_probe_concurrency()),
        "--timeout",
        str(config.probe_request_timeout),
        "--health-timeout",
        str(config.probe_health_timeout),
        "--max-tokens",
        str(config.probe_max_tokens),
        "--repeated-char-threshold",
        str(config.repeated_char_threshold),
        "--require-reasoning",
    ]


def _base_artifact(config: GateConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "deployment": config.deployment,
        "expected_routes": config.expected_routes,
        "required_consecutive_polls": config.consecutive_polls,
        "max_consecutive_status_unavailable": config.max_status_unavailable,
        "updated_at": _utc_now(),
    }


def run_gate(
    config: GateConfig,
    *,
    runner: CommandRunner = _run_process,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Wait for stable route counts, then run the mandatory semantic probe."""

    _validate_config(config)
    output = config.resolved_output()
    start = monotonic()
    deadline = start + config.wait_timeout
    polls = 0
    consecutive = 0
    consecutive_status_unavailable = 0
    status_unavailable_reason: str | None = None
    last_status: StatusObservation | None = None
    proxy_info_readable = False
    observed_spec_sha256: str | None = None
    endpoint: DeploymentEndpoint | None = None
    proxy_policy: dict[str, Any] | None = None
    serving_route_generation: dict[str, Any] | None = None
    candidate_route_generation: dict[str, Any] | None = None
    last_coord_incarnation: dict[str, str] | None = None
    last_coord_ticks: int | None = None

    def persist(
        state: str,
        *,
        reason: str | None = None,
        probe: Any | None = None,
    ) -> dict[str, Any]:
        artifact = {
            **_base_artifact(config),
            "state": state,
            "polls": polls,
            "consecutive_ready_polls": consecutive,
            "consecutive_status_unavailable": consecutive_status_unavailable,
            "status_unavailable_reason": status_unavailable_reason,
            "proxy_info_readable": proxy_info_readable,
            "endpoint": endpoint.binding if endpoint is not None else None,
            "proxy_policy": proxy_policy,
            "serving_route_generation": serving_route_generation,
            "observed_spec_sha256": observed_spec_sha256,
            "last_status": _status_record(last_status) if last_status else None,
        }
        if reason is not None:
            artifact["reason"] = reason
        if probe is not None:
            artifact["probe"] = probe
        _atomic_write_json(output, artifact)
        return artifact

    expected_request_timeout = request_timeout_for_model(config.model)
    try:
        while True:
            if polls and monotonic() >= deadline:
                raise GateError("wait_timeout")
            observed_spec_sha256 = None
            observed_spec_sha256 = _hash_spec(config.resolved_spec())
            if observed_spec_sha256 != config.expected_spec_sha256:
                raise GateError("spec_sha256_mismatch")
            try:
                validate_deployment_spec_proxy_policy(
                    config.resolved_spec(),
                    expected_spec_sha256=config.expected_spec_sha256,
                    expected_request_timeout=expected_request_timeout,
                )
            except DeploymentProxyPolicyError as exc:
                raise GateError("deployment_proxy_policy_invalid") from exc
            result = runner(_status_command(config), config.status_command_timeout)
            polls += 1
            try:
                observed_status = _parse_status(result, config.deployment)
            except StatusUnavailable as exc:
                consecutive = 0
                consecutive_status_unavailable += 1
                status_unavailable_reason = exc.reason
                if consecutive_status_unavailable > config.max_status_unavailable:
                    raise GateError("status_unavailable_limit_exceeded") from exc
                persist("waiting")
                emit(
                    f"poll={polls} status=unavailable "
                    f"consecutive={consecutive_status_unavailable}/"
                    f"{config.max_status_unavailable}"
                )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise GateError("wait_timeout")
                sleeper(min(config.poll_interval, remaining))
                continue

            consecutive_status_unavailable = 0
            status_unavailable_reason = None
            if observed_status.coordinator_incarnation is not None:
                if (
                    observed_status.coordinator_incarnation == last_coord_incarnation
                    and last_coord_ticks is not None
                    and observed_status.coord_ticks_completed is not None
                ):
                    if observed_status.coord_ticks_completed < last_coord_ticks:
                        raise GateError("coordinator_ticks_regressed")
                    if observed_status.coord_ticks_completed == last_coord_ticks:
                        raise GateError("coordinator_ticks_not_advancing")
                last_coord_incarnation = observed_status.coordinator_incarnation
                last_coord_ticks = observed_status.coord_ticks_completed
            last_status = observed_status
            if last_status.is_exactly_ready(config.expected_routes):
                observed_generation = last_status.serving_route_generation
                if observed_generation == candidate_route_generation:
                    consecutive += 1
                else:
                    candidate_route_generation = observed_generation
                    consecutive = 1
            else:
                consecutive = 0
                candidate_route_generation = None

            if consecutive >= config.consecutive_polls:
                serving_route_generation = candidate_route_generation
                observed_spec_sha256 = _hash_spec(config.resolved_spec())
                if observed_spec_sha256 != config.expected_spec_sha256:
                    raise GateError("spec_sha256_mismatch")
                try:
                    endpoint = _load_endpoint(config)
                except GateError as exc:
                    if exc.reason != "proxy_info_unreadable":
                        raise
                else:
                    if (
                        serving_route_generation is None
                        or endpoint.proxy_job_id != serving_route_generation["proxy"]["slurm_job_id"]
                    ):
                        raise GateError("proxy_job_id_mismatch")
                    try:
                        proxy_policy = load_deployment_proxy_policy(
                            config.resolved_spec(),
                            expected_spec_sha256=config.expected_spec_sha256,
                            expected_request_timeout=expected_request_timeout,
                        )
                    except DeploymentProxyPolicyError as exc:
                        if str(exc) != "proxy_litellm_config_unreadable":
                            raise GateError("deployment_proxy_policy_invalid") from exc
                    else:
                        proxy_info_readable = True

            persist("waiting")
            emit(
                f"poll={polls} phase={last_status.phase} "
                f"ready={last_status.ready}/{last_status.desired} "
                f"stable={consecutive}/{config.consecutive_polls}"
            )
            if proxy_info_readable:
                assert endpoint is not None
                observed_spec_sha256 = None
                observed_spec_sha256 = _hash_spec(config.resolved_spec())
                if observed_spec_sha256 != config.expected_spec_sha256:
                    raise GateError("spec_sha256_mismatch")
                persist("probing")
                try:
                    probe_process = runner(
                        _probe_command(config, endpoint.proxy_info_sha256),
                        config.probe_process_timeout,
                    )
                except GateError:
                    try:
                        _load_endpoint(
                            config,
                            expected_proxy_info_sha256=endpoint.proxy_info_sha256,
                        )
                    except GateError as exc:
                        raise GateError("proxy_info_changed") from exc
                    raise
                try:
                    reloaded_endpoint = _load_endpoint(
                        config,
                        expected_proxy_info_sha256=endpoint.proxy_info_sha256,
                    )
                except GateError as exc:
                    raise GateError("proxy_info_changed") from exc
                if reloaded_endpoint.binding != endpoint.binding:
                    raise GateError("proxy_info_changed")
                observed_spec_sha256 = None
                observed_spec_sha256 = _hash_spec(config.resolved_spec())
                if observed_spec_sha256 != config.expected_spec_sha256:
                    raise GateError("spec_sha256_mismatch")
                try:
                    probe_payload = json.loads(probe_process.stdout)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise GateError("malformed_probe_result") from exc
                if not isinstance(probe_payload, dict) or not isinstance(probe_payload.get("ok"), bool):
                    raise GateError("malformed_probe_result")
                if probe_payload.get("endpoint_authority_sha256") != endpoint.authority_sha256:
                    raise GateError("probe_endpoint_mismatch")
                safe_probe = _redact_result(probe_payload, endpoint.api_key)
                if probe_process.returncode != 0 or probe_payload["ok"] is not True:
                    persist(
                        "failed",
                        reason="probe_failed",
                        probe=safe_probe,
                    )
                    raise GateError("probe_failed")
                coverage = probe_payload.get("coverage")
                expected_backends = sorted(route["backend_sha256"] for route in serving_route_generation["routes"])
                if not isinstance(coverage, dict) or coverage.get("backends") != expected_backends:
                    raise GateError("probe_serving_routes_mismatch")
                post_probe_result = runner(
                    _status_command(config),
                    config.status_command_timeout,
                )
                try:
                    post_probe_status = _parse_status(post_probe_result, config.deployment)
                except GateError as exc:
                    raise GateError("serving_route_generation_changed") from exc
                post_probe_generation = post_probe_status.serving_route_generation
                if (
                    not post_probe_status.is_exactly_ready(config.expected_routes)
                    or post_probe_generation != serving_route_generation
                ):
                    raise GateError("serving_route_generation_changed")
                if last_status.coord_ticks_completed is None or post_probe_status.coord_ticks_completed is None:
                    raise GateError("coordinator_ticks_not_advancing")
                if post_probe_status.coord_ticks_completed < last_status.coord_ticks_completed:
                    raise GateError("coordinator_ticks_regressed")
                if post_probe_status.coord_ticks_completed == last_status.coord_ticks_completed:
                    raise GateError("coordinator_ticks_not_advancing")
                last_status = post_probe_status
                try:
                    final_endpoint = _load_endpoint(
                        config,
                        expected_proxy_info_sha256=endpoint.proxy_info_sha256,
                    )
                except GateError as exc:
                    raise GateError("proxy_info_changed") from exc
                if final_endpoint.binding != endpoint.binding:
                    raise GateError("proxy_info_changed")
                observed_spec_sha256 = _hash_spec(config.resolved_spec())
                if observed_spec_sha256 != config.expected_spec_sha256:
                    raise GateError("spec_sha256_mismatch")
                try:
                    revalidate_deployment_proxy_policy(
                        config.resolved_spec(),
                        expected_spec_sha256=config.expected_spec_sha256,
                        expected_binding=proxy_policy,
                        expected_request_timeout=expected_request_timeout,
                    )
                except DeploymentProxyPolicyError as exc:
                    raise GateError("deployment_proxy_policy_changed") from exc
                return persist(
                    "passed",
                    probe=safe_probe,
                )

            remaining = deadline - monotonic()
            if remaining <= 0:
                raise GateError("wait_timeout")
            sleeper(min(config.poll_interval, remaining))
    except GateError as exc:
        # A probe failure was already persisted with its safe parsed result.
        if exc.reason != "probe_failed":
            persist("failed", reason=exc.reason)
        raise


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_cli_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Wait for exact, stable RAM route readiness and then run the mandatory semantic/sticky-affinity probe."
        )
    )
    parser.add_argument("deployment")
    parser.add_argument(
        "--expected-spec-sha256",
        required=True,
        help="required lowercase SHA-256 pin for the immutable RAM spec.yaml",
    )
    parser.add_argument("--expected-routes", type=_positive_int, default=24)
    parser.add_argument("--model", default="Kimi-K3")
    parser.add_argument("--serve-sh", type=Path, default=DEFAULT_SERVE_SH)
    parser.add_argument("--probe-script", type=Path, default=DEFAULT_PROBE_SCRIPT)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--proxy-info", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--consecutive-polls", type=_positive_int, default=3)
    parser.add_argument(
        "--max-status-unavailable",
        type=_nonnegative_cli_int,
        default=10,
        help="number of consecutive unusable rc=1 status results to tolerate",
    )
    parser.add_argument("--poll-interval", type=_positive_float, default=60.0)
    parser.add_argument("--wait-timeout", type=_positive_float, default=72 * 60 * 60)
    parser.add_argument("--status-command-timeout", type=_positive_float, default=30.0)
    parser.add_argument("--probe-process-timeout", type=_positive_float, default=2 * 60 * 60)
    parser.add_argument("--probe-requests", type=_positive_int)
    parser.add_argument("--probe-repeats", type=_positive_int, default=3)
    parser.add_argument("--probe-concurrency", type=_positive_int)
    parser.add_argument("--probe-request-timeout", type=_positive_float, default=300.0)
    parser.add_argument("--probe-health-timeout", type=_positive_float, default=30.0)
    parser.add_argument("--probe-max-tokens", type=_positive_int, default=4096)
    parser.add_argument("--repeated-char-threshold", type=_positive_int, default=8)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = GateConfig(
        deployment=args.deployment,
        expected_spec_sha256=args.expected_spec_sha256,
        expected_routes=args.expected_routes,
        model=args.model,
        serve_sh=args.serve_sh,
        probe_script=args.probe_script,
        spec=args.spec,
        proxy_info=args.proxy_info,
        output=args.output,
        consecutive_polls=args.consecutive_polls,
        max_status_unavailable=args.max_status_unavailable,
        poll_interval=args.poll_interval,
        wait_timeout=args.wait_timeout,
        status_command_timeout=args.status_command_timeout,
        probe_process_timeout=args.probe_process_timeout,
        probe_requests=args.probe_requests,
        probe_repeats=args.probe_repeats,
        probe_concurrency=args.probe_concurrency,
        probe_request_timeout=args.probe_request_timeout,
        probe_health_timeout=args.probe_health_timeout,
        probe_max_tokens=args.probe_max_tokens,
        repeated_char_threshold=args.repeated_char_threshold,
    )
    try:
        artifact = run_gate(config)
    except GateError as exc:
        print(f"readiness gate failed: {exc.reason}", file=sys.stderr)
        return 1
    except OSError:
        # Atomic artifact persistence itself failed. Do not echo exception text,
        # because filesystem messages can include operator-supplied paths.
        print("readiness gate failed: artifact_write_failed", file=sys.stderr)
        return 1
    print(f"readiness gate passed: deployment={artifact['deployment']} routes={artifact['expected_routes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
