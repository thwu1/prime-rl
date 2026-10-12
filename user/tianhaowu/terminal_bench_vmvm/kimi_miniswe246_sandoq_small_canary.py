#!/usr/bin/env python3
"""Run one opaque Kimi Mini-SWE 2.4.6 canary on Firecracker-small."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import direct_kimi_workers
import finalize_kimi_tb4_sandoq_small_v6_supersession as supersession
import qwen_miniswe246_sandoq_smoke as shared

MODEL = "Kimi-K3"
MAX_MODEL_CALLS = 3
MAX_OUTPUT_TOKENS = 128
MODEL_TIMEOUT_SECONDS = 300
EXECUTION_WALL_SECONDS = 960
EXECUTE_PROCESS_TIMEOUT_SECONDS = 965
CLEANUP_PROCESS_TIMEOUT_SECONDS = 25
SANITIZE_PROCESS_TIMEOUT_SECONDS = 5
SUPERVISOR_WALL_SECONDS = 1030
ORCHESTRATOR_WALL_SECONDS = 1050
TB4_MAX_OUTPUT_TOKENS = 512
TB4_MODEL_TIMEOUT_SECONDS = 1800
TB4_AGENT_WALL_SECONDS = 6000
TB4_SESSION_TIMEOUT_SECONDS = 6900
TB4_EXECUTION_WALL_SECONDS = 6600
TB4_EXECUTE_PROCESS_TIMEOUT_SECONDS = 6605
TB4_SUPERVISOR_WALL_SECONDS = 6670
TB4_ORCHESTRATOR_WALL_SECONDS = 6690
EXPECTED_ROUTER_PROFILE = "sandoq-c64-w2-v1"
EXPECTED_ENDPOINT_IDENTIFIER = "cpu-132-021_8103"
EXPECTED_WORKERS = 24
RECEIPT_KIND = "kimi-miniswe246-sandoq-firecracker-small-canary"
TB4_RECEIPT_KIND = "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
EVAL_CONFIG_SHA256 = "517bdc47951cb798cf18332e88b5d4202ac643da4737301a203aeebb96d52ff0"
TB4_EVAL_CONFIG_SHA256 = "5c8987eb2fbae751ae30dce3abdea7d15f878ec05ffdcc0d084f1b69876af002"
TB4_SELECTOR_SHA256 = "c1f745d4a1d3861deefb3fba4daa23f52ff3d1d4952a9fe2ba0ccbdc4040af97"
TB4_IMAGE_MANIFEST_SHA256 = "6dd632029af8da52f99f1d364e983a5da2e855afeb6a2ea5fc84fd00e1683513"
TB4_TASK_TREE_SHA256 = "55ee806f7a9be4c270161863b27010f7b684d2acaf31eff7c490e57f84a0dc86"
TB4_TASK_TREE_FILE_COUNT = 21
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
SHARED_SMOKE_SHA256 = "105c97e244bc1f5ab84f9577926bce437bbd113d72651c1876d9cfc1eea41992"
DIRECT_ROUTER_SHA256 = "38398a48040879e242807dfa1f0272951aad0b9a0be371b42e7cabe61f3313db"
DIRECT_WORKERS_SHA256 = "13d9f2a5d961762d40d3215b308aa0f9949ec73c70ba8f497941d0b49b901b75"
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class CanaryError(RuntimeError):
    """A canary contract failed; callers expose only aggregate state."""


def _loopback_url(value: str, expected_path: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise CanaryError("direct_router_url_invalid") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != expected_path.rstrip("/")
        or parsed.query
        or parsed.fragment
    ):
        raise CanaryError("direct_router_url_invalid")
    return value.rstrip("/")


def read_router_stats(url: str) -> dict[str, Any]:
    request = urllib.request.Request(_loopback_url(url, "/stats"), method="GET")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request,
            timeout=10,
        ) as response:
            body = response.read(shared.MAX_BODY_BYTES + 1)
            status = response.status
    except OSError as error:
        raise CanaryError("direct_router_stats_unavailable") from error
    if status != 200 or len(body) > shared.MAX_BODY_BYTES:
        raise CanaryError("direct_router_stats_unavailable")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CanaryError("direct_router_stats_invalid") from error
    if not isinstance(value, dict):
        raise CanaryError("direct_router_stats_invalid")
    return value


def router_audit(
    stats: dict[str, Any],
    model_calls: int,
    *,
    expected_profile: str = EXPECTED_ROUTER_PROFILE,
    expected_endpoint_identifier: str = EXPECTED_ENDPOINT_IDENTIFIER,
    expected_workers: int = EXPECTED_WORKERS,
    expected_per_worker_capacity: int = 2,
) -> dict[str, bool]:
    session_counts = stats.get("worker_session_counts")
    sticky = (
        isinstance(session_counts, list)
        and len(session_counts) == expected_workers
        and all(type(value) is int and value >= 0 for value in session_counts)
        and sum(session_counts) == 1
        and max(session_counts, default=0) == 1
        and stats.get("tracked_sessions") == 1
        and stats.get("cross_route_anomalies") == 0
    )
    w2_profile = (
        stats.get("kind") == "direct-kimi-transparent-router"
        and stats.get("implementation") == "direct-kimi-transparent-v2"
        and stats.get("policy") == "consistent_hash"
        and stats.get("request_id_headers") == ["x-session-id"]
        and stats.get("capacity_profile") == expected_profile
        and stats.get("endpoint_identifier") == expected_endpoint_identifier
        and stats.get("worker_count") == expected_workers
        and stats.get("active_workers") == expected_workers
        and stats.get("configured_capacity") == 64
        and stats.get("configured_per_worker_capacity") == expected_per_worker_capacity
    )
    healthy = (
        type(model_calls) is int
        and 1 <= model_calls <= MAX_MODEL_CALLS
        and stats.get("chat_requests") == model_calls
        and type(stats.get("total_requests")) is int
        and stats["total_requests"] >= model_calls
        and stats.get("active_requests") == 0
        and stats.get("active_forwarded_requests") == 0
        and stats.get("active_chat_requests") == 0
        and stats.get("active_worker_waiters") == 0
        and stats.get("missing_session_rejections") == 0
        and stats.get("upstream_failures") == 0
        and stats.get("upstream_http_429") == 0
        and stats.get("upstream_http_5xx") == 0
        and stats.get("worker_queue_timeouts") == 0
        and stats.get("capacity_rejections") == 0
        and type(stats.get("max_active_forwarded_requests")) is int
        and stats["max_active_forwarded_requests"] == 1
    )
    return {
        "router_w2_profile_configured": w2_profile,
        "sticky_routing": sticky,
        "router_healthy": healthy,
    }


def _task_tree_identity(task_dir: Path) -> tuple[int, str]:
    try:
        root = task_dir.resolve(strict=True)
        root_before = root.stat()
        entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError as error:
        raise CanaryError("tb4_task_invalid") from error
    digest = hashlib.sha256()
    count = 0
    for path in entries:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise CanaryError("tb4_task_invalid") from error
        if stat.S_ISLNK(metadata.st_mode) or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise CanaryError("tb4_task_invalid")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                body = handle.read(shared.MAX_BODY_BYTES + 1)
                after = os.fstat(handle.fileno())
        except OSError as error:
            raise CanaryError("tb4_task_invalid") from error
        visible = path.lstat()
        if (
            len(body) > shared.MAX_BODY_BYTES
            or not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, stat.S_IMODE(before.st_mode))
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, stat.S_IMODE(after.st_mode))
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, stat.S_IMODE(after.st_mode))
            != (visible.st_dev, visible.st_ino, visible.st_size, visible.st_mtime_ns, stat.S_IMODE(visible.st_mode))
        ):
            raise CanaryError("tb4_task_invalid")
        relative = path.relative_to(root).as_posix()
        digest.update(
            f"{stat.S_IMODE(after.st_mode):04o} {hashlib.sha256(body).hexdigest()}  {relative}\n".encode()
        )
        count += 1
    root_after = root.stat()
    if (root_before.st_dev, root_before.st_ino, root_before.st_mtime_ns) != (
        root_after.st_dev,
        root_after.st_ino,
        root_after.st_mtime_ns,
    ):
        raise CanaryError("tb4_task_invalid")
    return count, digest.hexdigest()


def _read_tb4_selector(selector: Path, selector_sha256: str, dataset_dir: Path) -> tuple[str, bytes]:
    if selector_sha256 != TB4_SELECTOR_SHA256 or shared.sha256_file(selector) != selector_sha256:
        raise CanaryError("tb4_selector_invalid")
    try:
        body = selector.read_bytes()
        lines = [
            line.strip().split("\t", 1)[0]
            for line in body.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        root = dataset_dir.resolve(strict=True)
    except (OSError, UnicodeDecodeError) as error:
        raise CanaryError("tb4_selector_invalid") from error
    if len(lines) != 1 or _SLUG_RE.fullmatch(lines[0]) is None:
        raise CanaryError("tb4_selector_invalid")
    task_dir = (root / lines[0]).resolve(strict=True)
    if task_dir.parent != root or task_dir.name != lines[0]:
        raise CanaryError("tb4_selector_invalid")
    if _task_tree_identity(task_dir) != (TB4_TASK_TREE_FILE_COUNT, TB4_TASK_TREE_SHA256):
        raise CanaryError("tb4_task_invalid")
    try:
        metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CanaryError("tb4_selector_invalid") from error
    if not shared._security_metadata_is_absent(metadata):
        raise CanaryError("tb4_selector_invalid")
    return lines[0], f"{lines[0]}\n".encode()


def materialize_tb4_selector(source: Path, dataset_dir: Path, destination: Path) -> str:
    _, payload = _read_tb4_selector(source, TB4_SELECTOR_SHA256, dataset_dir)
    shared.publish_private_bytes(destination, payload)
    return shared.sha256_file(destination)


def _task_uses_compose(task_dir: Path) -> bool:
    environment = task_dir / "environment"
    return any(
        os.path.lexists(environment / name)
        for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
    )


def clamp_tb4_task(task: Any) -> Any:
    if (
        task.verifier_mode != "separate"
        or task.image is None
        or "@sha256:" not in task.image
        or task.verifier_image is None
        or "@sha256:" not in task.verifier_image
        or task.resources.gpu is not None
        or task.verifier_resources.gpu is not None
        or _task_uses_compose(Path(task.task_dir))
    ):
        raise CanaryError("tb4_task_invalid")

    def clamp(resources: Any) -> Any:
        values = {
            "cpu": min(float(resources.cpu or 1.0), 1.0),
            "memory": min(float(resources.memory or 2.0), 2.0),
            "disk": min(float(resources.disk or 10.0), 10.0),
            "gpu": None,
        }
        return resources.model_copy(update=values)

    return task.model_copy(
        update={
            "resources": clamp(task.resources),
            "verifier_resources": clamp(task.verifier_resources),
        }
    )


def load_selected_task(args: argparse.Namespace) -> tuple[Any, Any]:
    if args.task_profile == "mobius":
        return shared.load_selected_task(
            args.selector,
            args.selector_sha256,
            args.dataset_dir,
            args.image_manifest,
        )
    _read_tb4_selector(args.selector, args.selector_sha256, args.dataset_dir)
    if shared.sha256_file(args.image_manifest) != TB4_IMAGE_MANIFEST_SHA256:
        raise CanaryError("tb4_image_manifest_invalid")
    config = shared.TerminalBenchVMVMConfig(
        dataset_dir=args.dataset_dir,
        task_file=args.selector,
        task_file_sha256=args.selector_sha256,
        image_manifest=args.image_manifest,
        image_manifest_sha256=TB4_IMAGE_MANIFEST_SHA256,
        ignore_dockerfile=True,
        use_declared_images=True,
        enable_compose=False,
        capture_convention_artifacts=True,
        verifier_runtime_retries=0,
        timeout_multiplier=0.5,
        resource_multiplier=1.0,
    )
    taskset = shared.TerminalBenchVMVMTaskset(config)
    tasks = taskset.load_tasks()
    if len(tasks) != 1:
        raise CanaryError("tb4_task_invalid")
    _read_tb4_selector(args.selector, args.selector_sha256, args.dataset_dir)
    return taskset, clamp_tb4_task(tasks[0])


async def finalize_and_score(
    task_profile: str,
    taskset: Any,
    task: Any,
    trace: Any,
    runtime: Any,
) -> float:
    await taskset.finalize(task, trace, runtime)
    if task_profile == "tb4":
        # TB4's selected task uses a separate verifier runtime.  Release the
        # agent assignment before scoring so a one-slot diagnostic pool can
        # create that verifier without deadlocking.  SandoqRuntime.stop() is
        # idempotent; the unconditional finalizer below still verifies it.
        await runtime.stop()
    return float(await taskset.solved(task, trace, runtime))


async def score_with_tb4_diagnostics(
    task_profile: str,
    taskset: Any,
    task: Any,
    trace: Any,
    runtime: Any,
) -> tuple[float | None, dict[str, Any] | None]:
    try:
        score = await finalize_and_score(task_profile, taskset, task, trace, runtime)
        return score, (
            {
                "schema_version": 1,
                "stage": "separate_verifier",
                "state": "passed",
                "failure_class": None,
                "numeric_reward": True,
            }
            if task_profile == "tb4"
            else None
        )
    except Exception as error:
        if task_profile != "tb4":
            raise
        # Preserve the private model-I/O trajectory and aggregate model-call
        # evidence when the separate verifier fails.  A missing numeric reward
        # still makes the public TB4 receipt fail closed.
        failure_class = {
            "TimeoutError": "timeout",
            "SandboxError": "sandbox",
            "RuntimeError": "runtime",
            "ValueError": "validation",
        }.get(type(error).__name__, "other")
        return None, {
            "schema_version": 1,
            "stage": "separate_verifier",
            "state": "failed",
            "failure_class": failure_class,
            "numeric_reward": False,
        }


async def execute_canary(args: argparse.Namespace) -> dict[str, Any]:
    taskset, task = load_selected_task(args)
    tb4 = args.task_profile == "tb4"
    max_output_tokens = TB4_MAX_OUTPUT_TOKENS if tb4 else MAX_OUTPUT_TOKENS
    model_timeout_seconds = TB4_MODEL_TIMEOUT_SECONDS if tb4 else MODEL_TIMEOUT_SECONDS
    agent_wall_seconds = TB4_AGENT_WALL_SECONDS if tb4 else 900
    session_timeout_seconds = TB4_SESSION_TIMEOUT_SECONDS if tb4 else 1020
    relay = shared.ModelRelay(
        _loopback_url(args.base_url, "/v1"),
        "EMPTY",
        os.urandom(16).hex(),
        model=MODEL,
        max_output_tokens=max_output_tokens,
        request_timeout_seconds=model_timeout_seconds,
        reasoning_effort="max",
    )
    runtime = shared.SandoqRuntime(
        shared.SandoqConfig(
            image=task.image,
            workdir=task.workdir or "/app",
            network_access=True,
            mode="oci-runner",
            session_timeout=session_timeout_seconds,
            cpu=float(task.resources.cpu or 1),
            memory=float(task.resources.memory or 2),
            disk=float(task.resources.disk or 5),
            host_tunnel="sandoq",
            guest_tunnel_url="http://127.0.0.1:8485",
            tunnel_pool_size=4,
            tunnel_ready_timeout=30,
            buffered_chat_completions=tb4,
            expected_environment="oci-runner-firecracker-small",
            ecr_token_file=Path("/storage/home/tianhaowu/.config/oci-runner/ecr-token"),
        ),
        name=f"kimi-miniswe246-small-{os.urandom(6).hex()}",
    )
    trace = shared.vf.Trace(task=task)
    sandbox_started = False
    task_setup = False
    task_cleanup = False
    runtime_stopped = False
    result = None
    score: float | None = None
    scoring_state: dict[str, Any] | None = None
    trajectory_bytes = b""
    await relay.start()
    try:
        async with asyncio.timeout(args.wall_seconds):
            await runtime.start()
            sandbox_started = True
            await taskset.setup(task, runtime)
            task_setup = True
            endpoint_context = (
                runtime.interception_endpoint(relay.port, "sandoq-local-relay")
                if tb4
                else runtime.host_endpoint(relay.port)
            )
            async with endpoint_context as guest_endpoint:
                dependency = (
                    'dependencies = ["mini-swe-agent=={version}", "litellm[proxy]==1.91.2"]'
                )
                if shared.PROGRAM_SOURCE.count(dependency) != 1:
                    raise CanaryError("mini_swe_program_contract_changed")
                source = shared.PROGRAM_SOURCE.replace("{version}", "2.4.6")
                program = await runtime.prepare_uv_script(source, {})
                trajectory_path = "/tmp/kimi-miniswe246-small-canary.traj.json"
                argv = [
                    *program,
                    "--model",
                    MODEL,
                    "--model-class",
                    "litellm",
                    "--task",
                    task.prompt or "",
                    "--exit-immediately",
                    "--yolo",
                    "--output",
                    trajectory_path,
                    "--vf-config-file",
                    "mini",
                    "--vf-config-override",
                    "agent.cost_limit=0",
                    "--vf-config-override",
                    "agent.step_limit=3",
                    "--vf-config-override",
                    f"agent.wall_time_limit_seconds={agent_wall_seconds}",
                    "--vf-config-override",
                    "environment.environment_class=local",
                    "--vf-config-override",
                    "environment.timeout=60",
                    "--vf-config-override",
                    "model.cost_tracking=ignore_errors",
                    "--vf-config-override",
                    "model.model_kwargs.custom_llm_provider=openai",
                    "--vf-config-override",
                    "model.model_kwargs.drop_params=true",
                    "--vf-config-override",
                    f"model.model_kwargs.timeout={model_timeout_seconds}",
                    "--vf-config-override",
                    f"model.model_kwargs.max_tokens={max_output_tokens}",
                    "--vf-config-override",
                    "model.model_kwargs.temperature=1.0",
                    "--vf-config-override",
                    "model.model_kwargs.top_p=1.0",
                    "--vf-config-override",
                    "model.model_kwargs.parallel_tool_calls=false",
                    "--vf-config-override",
                    f"model.model_kwargs.api_base={guest_endpoint}/v1",
                    "--vf-config-override",
                    "model.model_kwargs.api_key=sandoq-local-relay",
                ]
                result = await runtime.run_program(
                    argv,
                    {
                        "MSWEA_CONFIGURED": "true",
                        "MSWEA_SILENT_STARTUP": "true",
                        "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10" if tb4 else "1",
                    },
                )
                trajectory_bytes = await runtime.read(trajectory_path)
            score, scoring_state = await score_with_tb4_diagnostics(
                args.task_profile,
                taskset,
                task,
                trace,
                runtime,
            )
    finally:
        if sandbox_started:
            with contextlib.suppress(Exception):
                await taskset.cleanup(task, trace, runtime)
                task_cleanup = True
            try:
                await asyncio.shield(runtime.stop())
                runtime_stopped = True
            except Exception:
                runtime_stopped = False
        await relay.close()
    if args.task_profile == "tb4":
        _read_tb4_selector(args.selector, args.selector_sha256, args.dataset_dir)
    if result is None or not trajectory_bytes:
        raise CanaryError("agent_result_missing")
    audit = shared.trajectory_audit(
        trajectory_bytes,
        len(relay.requests),
        require_all_shell_success=not tb4,
    )
    reasoning_retained = (
        1 <= len(relay.requests) <= MAX_MODEL_CALLS
        and len(relay.reasoning) == len(relay.requests)
        and all(relay.reasoning)
        and relay.prior_reasoning == list(range(len(relay.requests)))
        and audit["trajectory_reasoning_retained"]
    )
    run_state = {
        "sandbox_lifecycle": sandbox_started and task_setup and task_cleanup and runtime_stopped,
        "model_calls": len(relay.requests),
        "shell_execution": bool(audit["shell_execution"]),
        "exact_native_submission_marker": bool(audit["exact_native_submission_marker"] and audit["submitted"]),
        "reasoning_content_retained": reasoning_retained,
        "reward": score,
        "program_exit_ok": result.exit_code == 0,
        "api_calls_match": bool(audit["api_calls_match"]),
        "mini_version_match": bool(audit["mini_version_match"]),
    }
    raw = {
        "schema_version": 1,
        "model_requests": relay.requests,
        "model_responses": relay.responses,
        "trajectory": json.loads(trajectory_bytes),
        "program_stdout": result.stdout,
        "program_stderr": result.stderr,
    }
    shared.publish_private(args.output_dir / "raw-trace.json", raw)
    shared.publish_private(args.output_dir / "run-private.json", run_state)
    if scoring_state is not None:
        shared.publish_private(args.output_dir / "scoring-private.json", scoring_state)
    return run_state


def execute_command(args: argparse.Namespace) -> int:
    try:
        state = asyncio.run(execute_canary(args))
    except Exception:
        with contextlib.suppress(Exception):
            shared.publish_private(args.output_dir / "run-private.json", shared.failed_run_state())
        return 2
    return 0 if state["program_exit_ok"] else 2


def supervised_command(args: argparse.Namespace) -> int:
    execution_wall_seconds = (
        TB4_EXECUTION_WALL_SECONDS if args.task_profile == "tb4" else EXECUTION_WALL_SECONDS
    )
    execute_process_timeout_seconds = (
        TB4_EXECUTE_PROCESS_TIMEOUT_SECONDS
        if args.task_profile == "tb4"
        else EXECUTE_PROCESS_TIMEOUT_SECONDS
    )
    execute = [
        "/usr/bin/timeout",
        "--foreground",
        "--signal=TERM",
        "--kill-after=10s",
        f"{execution_wall_seconds + 20}s",
        sys.executable,
        str(Path(__file__).resolve()),
        "execute",
        "--selector",
        str(args.selector),
        "--selector-sha256",
        args.selector_sha256,
        "--task-profile",
        args.task_profile,
        "--dataset-dir",
        str(args.dataset_dir),
        "--image-manifest",
        str(args.image_manifest),
        "--base-url",
        args.base_url,
        "--output-dir",
        str(args.output_dir),
        "--wall-seconds",
        str(execution_wall_seconds),
    ]
    # Reserve enough of the supervisor's hard budget for a timed-out process's
    # kill grace, authoritative cleanup, cleanup kill grace, sanitization, and
    # sanitization kill grace.  The shared helper can add at most ten seconds
    # after each timeout.
    eval_status = shared._run_logged(execute, args.log, execute_process_timeout_seconds)
    cleanup = [
        sys.executable,
        str(args.workflow_dir / "sandoq_pool_cleanup.py"),
        "--output-dir",
        str(args.output_dir),
        "--base-url",
        "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "--owner",
        os.environ.get("SANDOQ_OWNER", ""),
        "--concurrency",
        "1",
    ]
    shared._run_logged(cleanup, args.log, CLEANUP_PROCESS_TIMEOUT_SECONDS)
    sanitize = [
        sys.executable,
        str(args.workflow_dir / "sanitize_sandoq_cleanup_audit.py"),
        "--raw-audit",
        str(args.output_dir / "pool_cleanup_audit.json"),
        "--event-log",
        os.environ.get("OCI_RUNNER_POOL_EVENT_LOG", ""),
        "--wal",
        os.environ.get("OCI_RUNNER_POOL_WAL", ""),
        "--drain-marker",
        str(args.drain_marker),
        "--output",
        str(args.output_dir / "sandoq_cleanup_audit.json"),
    ]
    cleanup_evidence_status = shared._run_logged(
        sanitize,
        args.log,
        SANITIZE_PROCESS_TIMEOUT_SECONDS,
    )
    return 0 if eval_status == 0 and cleanup_evidence_status == 0 else 2


def public_receipt(
    run_state: dict[str, Any],
    *,
    cleanup: bool,
    router: dict[str, bool],
    kind: str = RECEIPT_KIND,
    binding: dict[str, Any] | None = None,
    transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = set(shared.failed_run_state())
    if set(run_state) != expected:
        run_state = shared.failed_run_state()
    if set(router) != set(_failed_router_audit()) or any(type(value) is not bool for value in router.values()):
        router = _failed_router_audit()
    model_calls = run_state["model_calls"]
    reward = run_state["reward"]
    transport_valid = _transport_audit_valid(transport, model_calls)
    valid = (
        run_state["sandbox_lifecycle"] is True
        and type(model_calls) is int
        and 1 <= model_calls <= MAX_MODEL_CALLS
        and run_state["shell_execution"] is True
        and run_state["reasoning_content_retained"] is True
        and run_state["program_exit_ok"] is True
        and run_state["api_calls_match"] is True
        and run_state["mini_version_match"] is True
        and isinstance(reward, (int, float))
        and not isinstance(reward, bool)
        and cleanup
        and all(router.values())
        and (kind != TB4_RECEIPT_KIND or transport_valid)
    )
    strict = valid and run_state["exact_native_submission_marker"] is True and reward > 0
    if kind == TB4_RECEIPT_KIND:
        status = "diagnostic_passed" if valid else "failed"
    else:
        status = "strict_passed" if strict else "infrastructure_only" if valid else "failed"
    receipt = {
        "schema_version": 3 if binding is not None and transport is not None else 2 if binding is not None else 1,
        "kind": kind,
        "task_count": 1,
        "max_model_calls": MAX_MODEL_CALLS,
        "harness_version": "2.4.6",
        "sandbox_environment": "oci-runner-firecracker-small",
        "sandbox_lifecycle": bool(run_state["sandbox_lifecycle"]),
        "model_calls": model_calls if type(model_calls) is int else 0,
        "shell_execution": bool(run_state["shell_execution"]),
        "exact_native_submission_marker": bool(run_state["exact_native_submission_marker"]),
        "reasoning_content_retained": bool(run_state["reasoning_content_retained"]),
        "reward": float(reward) if isinstance(reward, (int, float)) and not isinstance(reward, bool) else None,
        "cleanup": cleanup,
        **router,
        "status": status,
    }
    if binding is not None:
        receipt["deployment"] = binding
    if transport is not None:
        receipt["transport"] = transport
    return receipt


def _transport_audit_valid(value: Any, model_calls: Any) -> bool:
    summary = value.get("summary") if isinstance(value, dict) else None
    artifact = value.get("summary_record") if isinstance(value, dict) else None
    totals = summary.get("integer_totals") if isinstance(summary, dict) else None
    return (
        isinstance(value, dict)
        and set(value) == {"schema_version", "kind", "summary_record", "summary"}
        and value.get("schema_version") == 1
        and value.get("kind") == "sandoq-buffered-chat-logical-exact-once"
        and isinstance(artifact, dict)
        and set(artifact) == {"bytes", "sha256"}
        and isinstance(artifact.get("bytes"), int)
        and not isinstance(artifact.get("bytes"), bool)
        and artifact["bytes"] > 0
        and _SHA256_RE.fullmatch(str(artifact.get("sha256", ""))) is not None
        and isinstance(summary, dict)
        and summary.get("source_schema") == "logical-exact-once-v1"
        and summary.get("summary_records") == 1
        and summary.get("exact_once_counters_required") is True
        and isinstance(totals, dict)
        and type(model_calls) is int
        and totals.get("logical_requests") == model_calls
        and totals.get("logical_upstream_attempts") == model_calls
        and totals.get("upstream_attempts") == model_calls
        and totals.get("anonymous_upstream_attempts") == 0
        and totals.get("conflicting_requests") == 0
        and totals.get("expired_logical_retries") == 0
        and totals.get("inflight") == 0
        and totals.get("error_count") == 0
        and totals.get("requests") == totals.get("streamed_requests")
        and isinstance(totals.get("coalesced_requests"), int)
        and isinstance(totals.get("replayed_requests"), int)
    )


def transport_attestation(directory: Path) -> dict[str, Any]:
    before = directory.lstat()
    if (
        not stat.S_ISDIR(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o700
        or before.st_uid != os.geteuid()
        or directory.is_symlink()
        or directory.resolve(strict=True) != directory
    ):
        raise CanaryError("transport_log_invalid")
    records = sorted(directory.iterdir())
    if (
        len(records) != 1
        or re.fullmatch(r"summary-[0-9a-f]{32}\.json", records[0].name) is None
        or records[0].is_symlink()
    ):
        raise CanaryError("transport_log_invalid")
    path = records[0]
    file_before = path.lstat()
    if (
        not stat.S_ISREG(file_before.st_mode)
        or stat.S_IMODE(file_before.st_mode) != 0o600
        or file_before.st_uid != os.geteuid()
        or file_before.st_nlink != 1
        or file_before.st_size < 1
        or file_before.st_size > shared.MAX_BODY_BYTES
    ):
        raise CanaryError("transport_log_invalid")
    body = path.read_bytes()
    file_after = path.lstat()
    after = directory.lstat()
    if (
        file_before.st_dev,
        file_before.st_ino,
        file_before.st_size,
        file_before.st_mtime_ns,
        file_before.st_ctime_ns,
    ) != (
        file_after.st_dev,
        file_after.st_ino,
        file_after.st_size,
        file_after.st_mtime_ns,
        file_after.st_ctime_ns,
    ) or len(body) != file_after.st_size or (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        stat.S_IMODE(before.st_mode),
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_uid,
        stat.S_IMODE(after.st_mode),
    ):
        raise CanaryError("transport_log_changed")
    try:
        envelope = json.loads(body)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"schema_version", "kind", "counters"}
            or envelope.get("schema_version") != 1
            or envelope.get("kind") != "sandoq-buffered-model-proxy-summary"
            or not isinstance(envelope.get("counters"), dict)
            or shared.canonical_json(envelope) != body
        ):
            raise ValueError("buffered proxy summary envelope invalid")
        audit_body = (
            b"00:00:00 INFO "
            + supersession.PROXY_SUMMARY_MARKER
            + json.dumps(
                envelope["counters"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        summary = supersession._buffered_proxy_audit(
            audit_body,
            expected_schema="logical-exact-once-v1",
        )
    except (RuntimeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CanaryError("transport_audit_invalid") from error
    return {
        "schema_version": 1,
        "kind": "sandoq-buffered-chat-logical-exact-once",
        "summary_record": {
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "summary": summary,
    }


def _failed_router_audit() -> dict[str, bool]:
    return {
        "router_w2_profile_configured": False,
        "sticky_routing": False,
        "router_healthy": False,
    }


def cleanup_passed(path: Path, task_profile: str) -> bool:
    if task_profile == "mobius":
        return shared._cleanup_passed(path)
    try:
        value = shared.read_private_json(path)
    except (OSError, ValueError, shared.SmokeError):
        return False
    expected_assignments = 2
    return (
        value.get("kind") == "sandoq-pool-cleanup"
        and value.get("state") == "passed"
        and value.get("failures") == 0
        and value.get("assignments_acquired") == expected_assignments
        and value.get("assignments_cleanup_verified") == expected_assignments
        and value.get("assignment_release_rows") == expected_assignments
        and value.get("assignment_cancellation_rows") == 0
        and value.get("recorded_outer_sessions") == expected_assignments
        and value.get("outer_sessions_created") == expected_assignments
        and value.get("outer_sessions_deleted") == expected_assignments
        and value.get("verified_http_404") == expected_assignments
        and value.get("deleted_and_verified", 0) + value.get("already_absent", 0)
        == expected_assignments
        and value.get("outer_session_high_water") == 1
        and value.get("assignment_measured_high_water") == 1
    )


def receipt_exit_code(status: object, task_profile: str) -> int:
    accepted = "diagnostic_passed" if task_profile == "tb4" else "strict_passed"
    return 0 if status == accepted else 2


def smoke_binding(
    manifest_path: Path,
    *,
    expected_revision: str,
    expected_profile: str,
    expected_endpoint_identifier: str,
    expected_workers: int,
    expected_per_worker_capacity: int,
    slurm_job_id: str,
) -> dict[str, Any]:
    if _REVISION_RE.fullmatch(expected_revision) is None or re.fullmatch(r"[1-9][0-9]*", slurm_job_id) is None:
        raise CanaryError("smoke_binding_invalid")
    try:
        manifest = direct_kimi_workers.validate_saved_manifest(manifest_path)
        manifest_sha256 = shared.sha256_file(manifest_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise CanaryError("smoke_binding_invalid") from error
    router = manifest.get("router") if isinstance(manifest, dict) else None
    workers = manifest.get("workers") if isinstance(manifest, dict) else None
    if (
        not isinstance(router, dict)
        or not isinstance(workers, list)
        or router.get("capacity_profile") != expected_profile
        or router.get("endpoint_identifier") != expected_endpoint_identifier
        or router.get("per_worker_capacity") != expected_per_worker_capacity
        or len(workers) != expected_workers
        or any(
            _SHA256_RE.fullmatch(str(manifest.get(key, ""))) is None
            for key in ("source_spec_sha256", "source_proxy_config_sha256", "endpoint_bundle_sha256")
        )
    ):
        raise CanaryError("smoke_binding_invalid")
    return {
        "kind": "direct-kimi-smoke-binding",
        "source_revision": expected_revision,
        "slurm_job_id": slurm_job_id,
        "worker_manifest_sha256": manifest_sha256,
        "source_spec_sha256": manifest["source_spec_sha256"],
        "source_proxy_config_sha256": manifest["source_proxy_config_sha256"],
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "router": {
            "capacity_profile": expected_profile,
            "endpoint_identifier": expected_endpoint_identifier,
            "worker_count": expected_workers,
            "per_worker_capacity": expected_per_worker_capacity,
        },
    }


def orchestrate_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    supervisor_wall_seconds = (
        TB4_SUPERVISOR_WALL_SECONDS if args.task_profile == "tb4" else SUPERVISOR_WALL_SECONDS
    )
    orchestrator_wall_seconds = (
        TB4_ORCHESTRATOR_WALL_SECONDS if args.task_profile == "tb4" else ORCHESTRATOR_WALL_SECONDS
    )
    output_dir: Path | None = None
    binding: dict[str, Any] | None = None
    receipt_kind = TB4_RECEIPT_KIND if args.task_profile == "tb4" else RECEIPT_KIND
    receipt = public_receipt(
        shared.failed_run_state(),
        cleanup=False,
        router=_failed_router_audit(),
        kind=receipt_kind,
    )
    try:
        router_contract = (
            args.expected_router_profile,
            args.expected_endpoint_identifier,
            args.expected_workers,
            args.expected_per_worker_capacity,
        )
        if router_contract not in {
            (EXPECTED_ROUTER_PROFILE, EXPECTED_ENDPOINT_IDENTIFIER, EXPECTED_WORKERS, 2),
            (
                "sandoq-stock-single-c64-v1",
                "tianhaowu-kimi-k3-stock-eval-20260927",
                1,
                64,
            ),
        }:
            raise CanaryError("router_contract_invalid")
        project_root = args.project_root.resolve(strict=True)
        workflow_dir = project_root / "user/tianhaowu/terminal_bench_vmvm"
        shared._clean_source(project_root, args.expected_revision)
        eval_config = workflow_dir / (
            "configs/eval/servers/cpu-132-021_8103/"
            + (
                "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_smoke.toml"
                if args.task_profile == "tb4"
                else "kimi_miniswe246_sandoq_firecracker_small_smoke.toml"
            )
        )
        approved_selector = workflow_dir / (
            "configs/eval/tb4_kimi_k3_short_smoke.tasks.txt"
            if args.task_profile == "tb4"
            else "configs/eval/mobius_valid_tasks_2500.txt"
        )
        expected_files = {
            eval_config: TB4_EVAL_CONFIG_SHA256 if args.task_profile == "tb4" else EVAL_CONFIG_SHA256,
            workflow_dir
            / "configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json": PROVIDER_PROFILE_SHA256,
            approved_selector: (
                TB4_SELECTOR_SHA256 if args.task_profile == "tb4" else shared.APPROVED_TASK_FILE_SHA256
            ),
            workflow_dir / "qwen_miniswe246_sandoq_smoke.py": SHARED_SMOKE_SHA256,
            workflow_dir / "direct_kimi_router.py": DIRECT_ROUTER_SHA256,
            workflow_dir / "direct_kimi_workers.py": DIRECT_WORKERS_SHA256,
            project_root / "extensions/sandoq/sandoq_provider/tunnel.py": shared.REFERENCE_TUNNEL_SHA256,
            args.image_manifest: (
                TB4_IMAGE_MANIFEST_SHA256 if args.task_profile == "tb4" else shared.IMAGE_MANIFEST_SHA256
            ),
        }
        if any(shared.sha256_file(path.resolve(strict=True)) != digest for path, digest in expected_files.items()):
            raise CanaryError("frozen_input_changed")
        shared.validate_sandoq_site(args.sandoq_site)
        base_url = _loopback_url(args.base_url, "/v1")
        router_stats_url = _loopback_url(args.router_stats_url, "/stats")
        job_id = os.environ.get("SLURM_JOB_ID", "")
        if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
            raise CanaryError("slurm_job_invalid")
        binding = smoke_binding(
            args.worker_manifest,
            expected_revision=args.expected_revision,
            expected_profile=args.expected_router_profile,
            expected_endpoint_identifier=args.expected_endpoint_identifier,
            expected_workers=args.expected_workers,
            expected_per_worker_capacity=args.expected_per_worker_capacity,
            slurm_job_id=job_id,
        )
        if not args.output_root.is_absolute() or args.output_root != Path(os.path.normpath(args.output_root)):
            raise CanaryError("output_root_invalid")
        args.output_root.mkdir(mode=0o700, exist_ok=True)
        output_root = args.output_root.resolve(strict=True)
        output_metadata = output_root.lstat()
        if (
            output_root != args.output_root
            or args.output_root.is_symlink()
            or not stat.S_ISDIR(output_metadata.st_mode)
            or output_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(output_metadata.st_mode) != 0o700
        ):
            raise CanaryError("output_root_invalid")
        output_dir = output_root / f"run-{job_id}"
        output_dir.mkdir(mode=0o700)
        (output_dir / "control").mkdir(mode=0o700)
        buffered_stats_dir = output_dir / "control/buffered-proxy-stats"
        if args.task_profile == "tb4":
            buffered_stats_dir.mkdir(mode=0o700)
        log = output_dir / "execution.log"
        log.touch(mode=0o600, exist_ok=False)
        selector = output_dir / "selected-task.txt"
        if args.task_profile == "tb4":
            selector_sha256 = materialize_tb4_selector(approved_selector, args.dataset_dir, selector)
        else:
            selector_sha256 = shared.materialize_selector(
                approved_selector,
                args.dataset_dir,
                selector,
            )
        socket_dir = Path(os.environ.get("SLURM_TMPDIR", "/tmp")) / f"oci-runner-pool-{os.getuid()}"
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        socket_dir.chmod(0o700)
        pool_socket = socket_dir / f"{job_id}.sock"
        drain_marker = pool_socket.with_suffix(".drained.json")
        if any(
            os.path.lexists(path)
            for path in (pool_socket, pool_socket.with_suffix(".sock.owner.json"), drain_marker)
        ):
            raise CanaryError("pool_state_not_fresh")
        environment = dict(os.environ)
        for name in (
            "OPENAI_API_KEY",
            "FIRECRACKER_KEY",
            "SANDOQ_AUTH_TOKEN",
            "OCI_RUNNER_DOCKERHUB_USERNAME",
            "OCI_RUNNER_DOCKERHUB_TOKEN_FILE",
            "SANDOQ_TUNNEL_HTTPS_PROXY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "PRIME_RL_OUTPUT_DIR": str(output_dir),
                "SANDOQ_OWNER": f"{environment.get('USER', 'runner')}-kimi-mswe246-small-{job_id}",
                "OCI_RUNNER_POOL_SOCKET": str(pool_socket),
                "OCI_RUNNER_POOL_WAL": str(output_dir / "control/sandoq-pool.wal.jsonl"),
                "OCI_RUNNER_POOL_EVENT_LOG": str(output_dir / "pool_events.jsonl"),
                **(
                    {"SANDOQ_BUFFERED_STATS_DIR": str(buffered_stats_dir)}
                    if args.task_profile == "tb4"
                    else {}
                ),
            }
        )
        profile = (
            workflow_dir
            / "configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
        )
        supervised = [
            sys.executable,
            str(Path(__file__).resolve()),
            "supervised",
            "--selector",
            str(selector),
            "--selector-sha256",
            selector_sha256,
            "--task-profile",
            args.task_profile,
            "--dataset-dir",
            str(args.dataset_dir),
            "--image-manifest",
            str(args.image_manifest),
            "--base-url",
            base_url,
            "--output-dir",
            str(output_dir),
            "--workflow-dir",
            str(workflow_dir),
            "--log",
            str(log),
            "--drain-marker",
            str(drain_marker),
        ]
        command = [
            sys.executable,
            str(workflow_dir / "terminal_bench_vmvm/sandoq_provider_context.py"),
            "supervise",
            "--profile",
            str(profile),
            "--profile-sha256",
            PROVIDER_PROFILE_SHA256,
            "--concurrency",
            "1",
            "--lease-create-cap",
            "1",
            "--startup-timeout-seconds",
            "3600",
            "--lease-profile",
            "kimi-tb4-long" if args.task_profile == "tb4" else "standard",
            "--ecr-token-file",
            str(args.ecr_token_file),
            "--ecr-token-metadata",
            str(args.ecr_token_metadata),
            "--project-root",
            str(project_root),
            "--sandoq-site",
            str(args.sandoq_site),
            "--",
            *supervised,
        ]
        remaining = max(1.0, orchestrator_wall_seconds - (time.monotonic() - started))
        shared._run_logged_with_environment(command, log, min(supervisor_wall_seconds, remaining), environment)
        run_state = shared.read_private_json(output_dir / "run-private.json")
        cleanup = cleanup_passed(output_dir / "sandoq_cleanup_audit.json", args.task_profile)
        router_stats = read_router_stats(router_stats_url)
        shared.publish_private(
            output_dir / "control/direct-router-stats.private.json",
            router_stats,
        )
        router = router_audit(
            router_stats,
            int(run_state.get("model_calls", 0)),
            expected_profile=args.expected_router_profile,
            expected_endpoint_identifier=args.expected_endpoint_identifier,
            expected_workers=args.expected_workers,
            expected_per_worker_capacity=args.expected_per_worker_capacity,
        )
        transport = (
            transport_attestation(buffered_stats_dir)
            if args.task_profile == "tb4"
            else None
        )
        receipt = public_receipt(
            run_state,
            cleanup=cleanup,
            router=router,
            kind=receipt_kind,
            binding=binding,
            transport=transport,
        )
        if time.monotonic() - started > orchestrator_wall_seconds:
            receipt = public_receipt(
                shared.failed_run_state(),
                cleanup=cleanup,
                router=router,
                kind=receipt_kind,
                binding=binding,
                transport=transport,
            )
        shared.publish_private(output_dir / "receipt.json", receipt)
    except Exception:
        if output_dir is not None and output_dir.is_dir() and not os.path.lexists(output_dir / "receipt.json"):
            with contextlib.suppress(Exception):
                shared.publish_private(output_dir / "receipt.json", receipt)
    print(shared.canonical_json(receipt).decode(), end="")
    return receipt_exit_code(receipt["status"], args.task_profile)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("execute")
    supervised = commands.add_parser("supervised")
    for command in (execute, supervised):
        command.add_argument("--selector", type=Path, required=True)
        command.add_argument("--selector-sha256", required=True)
        command.add_argument("--dataset-dir", type=Path, required=True)
        command.add_argument("--image-manifest", type=Path, required=True)
        command.add_argument("--base-url", required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--task-profile", choices=("mobius", "tb4"), default="mobius")
    execute.add_argument("--wall-seconds", type=int, default=EXECUTION_WALL_SECONDS)
    supervised.add_argument("--workflow-dir", type=Path, required=True)
    supervised.add_argument("--log", type=Path, required=True)
    supervised.add_argument("--drain-marker", type=Path, required=True)
    orchestrate = commands.add_parser("orchestrate")
    orchestrate.add_argument("--project-root", type=Path, required=True)
    orchestrate.add_argument("--expected-revision", required=True)
    orchestrate.add_argument("--base-url", required=True)
    orchestrate.add_argument("--router-stats-url", required=True)
    orchestrate.add_argument("--expected-router-profile", default=EXPECTED_ROUTER_PROFILE)
    orchestrate.add_argument("--expected-endpoint-identifier", default=EXPECTED_ENDPOINT_IDENTIFIER)
    orchestrate.add_argument("--expected-workers", type=int, default=EXPECTED_WORKERS)
    orchestrate.add_argument("--expected-per-worker-capacity", type=int, default=2)
    orchestrate.add_argument("--worker-manifest", type=Path, required=True)
    orchestrate.add_argument("--task-profile", choices=("mobius", "tb4"), default="mobius")
    orchestrate.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/"
            "kimi-miniswe246-sandoq-firecracker-small-canary"
        ),
    )
    orchestrate.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9"),
    )
    orchestrate.add_argument(
        "--image-manifest",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.sandoq.json"),
    )
    orchestrate.add_argument(
        "--sandoq-site",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sandoq_x86_64_sdk1_82068"),
    )
    orchestrate.add_argument(
        "--ecr-token-file",
        type=Path,
        default=Path("/storage/home/tianhaowu/.config/oci-runner/ecr-token"),
    )
    orchestrate.add_argument(
        "--ecr-token-metadata",
        type=Path,
        default=Path("/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json"),
    )
    return result


def main() -> int:
    os.umask(0o077)
    args = parser().parse_args()
    if args.command == "execute":
        return execute_command(args)
    if args.command == "supervised":
        return supervised_command(args)
    return orchestrate_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
