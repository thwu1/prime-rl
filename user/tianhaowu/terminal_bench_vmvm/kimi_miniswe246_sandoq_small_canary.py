#!/usr/bin/env python3
"""Run one opaque Kimi Mini-SWE 2.4.6 canary on Firecracker-small."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import stat
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import qwen_miniswe246_sandoq_smoke as shared

MODEL = "Kimi-K3"
MAX_MODEL_CALLS = 3
MAX_OUTPUT_TOKENS = 64
MODEL_TIMEOUT_SECONDS = 120
EXECUTION_WALL_SECONDS = 400
EXECUTE_PROCESS_TIMEOUT_SECONDS = 405
CLEANUP_PROCESS_TIMEOUT_SECONDS = 25
SANITIZE_PROCESS_TIMEOUT_SECONDS = 5
SUPERVISOR_WALL_SECONDS = 470
ORCHESTRATOR_WALL_SECONDS = 490
EXPECTED_ROUTER_PROFILE = "sandoq-c64-w2-v1"
EXPECTED_ENDPOINT_IDENTIFIER = "cpu-132-021_8103"
EXPECTED_WORKERS = 24
RECEIPT_KIND = "kimi-miniswe246-sandoq-firecracker-small-canary"
EVAL_CONFIG_SHA256 = "7675211c4bbc93ad370002957dbf355cfb8514636c79b60d338ab14cfaae844f"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
SHARED_SMOKE_SHA256 = "41ddea1216187dead3eca7cd9e861cb23de5b12dbb989b463533aebe05341727"
DIRECT_ROUTER_SHA256 = "217c7c64a93a5bc41fd2a5f4c5c530da67d50a2d3ff83f117f96926a353dd10c"
DIRECT_WORKERS_SHA256 = "f01a4baffc86c5584bef40d1b95724f04d656b48a5a27dee8527aea8a3080212"
_REVISION_RE = re.compile(r"[0-9a-f]{40}")


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


def router_audit(stats: dict[str, Any], model_calls: int) -> dict[str, bool]:
    session_counts = stats.get("worker_session_counts")
    sticky = (
        isinstance(session_counts, list)
        and len(session_counts) == EXPECTED_WORKERS
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
        and stats.get("capacity_profile") == EXPECTED_ROUTER_PROFILE
        and stats.get("endpoint_identifier") == EXPECTED_ENDPOINT_IDENTIFIER
        and stats.get("worker_count") == EXPECTED_WORKERS
        and stats.get("active_workers") == EXPECTED_WORKERS
        and stats.get("configured_capacity") == 64
        and stats.get("configured_per_worker_capacity") == 2
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


async def execute_canary(args: argparse.Namespace) -> dict[str, Any]:
    taskset, task = shared.load_selected_task(
        args.selector,
        args.selector_sha256,
        args.dataset_dir,
        args.image_manifest,
    )
    relay = shared.ModelRelay(
        _loopback_url(args.base_url, "/v1"),
        "EMPTY",
        os.urandom(16).hex(),
        model=MODEL,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_timeout_seconds=MODEL_TIMEOUT_SECONDS,
        reasoning_effort="max",
    )
    runtime = shared.SandoqRuntime(
        shared.SandoqConfig(
            image=task.image,
            workdir=task.workdir or "/app",
            network_access=True,
            mode="oci-runner",
            session_timeout=440,
            cpu=float(task.resources.cpu or 1),
            memory=float(task.resources.memory or 2),
            disk=float(task.resources.disk or 5),
            host_tunnel="sandoq",
            guest_tunnel_url="http://127.0.0.1:8485",
            tunnel_pool_size=4,
            tunnel_ready_timeout=30,
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
    trajectory_bytes = b""
    await relay.start()
    try:
        async with asyncio.timeout(args.wall_seconds):
            await runtime.start()
            sandbox_started = True
            await taskset.setup(task, runtime)
            task_setup = True
            async with runtime.host_endpoint(relay.port) as guest_endpoint:
                dependency = 'dependencies = ["mini-swe-agent=={version}"]'
                replacement = 'dependencies = ["mini-swe-agent=={version}", "litellm[proxy]==1.91.2"]'
                if shared.PROGRAM_SOURCE.count(dependency) != 1:
                    raise CanaryError("mini_swe_program_contract_changed")
                source = shared.PROGRAM_SOURCE.replace(dependency, replacement).replace("{version}", "2.4.6")
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
                    "agent.wall_time_limit_seconds=380",
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
                    "model.model_kwargs.timeout=120",
                    "--vf-config-override",
                    "model.model_kwargs.max_tokens=64",
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
                        "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1",
                    },
                )
                trajectory_bytes = await runtime.read(trajectory_path)
            await taskset.finalize(task, trace, runtime)
            score = float(await taskset.solved(task, trace, runtime))
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
    if result is None or not trajectory_bytes:
        raise CanaryError("agent_result_missing")
    audit = shared.trajectory_audit(trajectory_bytes, len(relay.requests))
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
    execute = [
        "/usr/bin/timeout",
        "--foreground",
        "--signal=TERM",
        "--kill-after=10s",
        f"{EXECUTION_WALL_SECONDS + 20}s",
        sys.executable,
        str(Path(__file__).resolve()),
        "execute",
        "--selector",
        str(args.selector),
        "--selector-sha256",
        args.selector_sha256,
        "--dataset-dir",
        str(args.dataset_dir),
        "--image-manifest",
        str(args.image_manifest),
        "--base-url",
        args.base_url,
        "--output-dir",
        str(args.output_dir),
        "--wall-seconds",
        str(EXECUTION_WALL_SECONDS),
    ]
    # Reserve enough of the supervisor's hard budget for a timed-out process's
    # kill grace, authoritative cleanup, cleanup kill grace, sanitization, and
    # sanitization kill grace.  The shared helper can add at most ten seconds
    # after each timeout.
    eval_status = shared._run_logged(execute, args.log, EXECUTE_PROCESS_TIMEOUT_SECONDS)
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
) -> dict[str, Any]:
    expected = set(shared.failed_run_state())
    if set(run_state) != expected:
        run_state = shared.failed_run_state()
    if set(router) != set(_failed_router_audit()) or any(type(value) is not bool for value in router.values()):
        router = _failed_router_audit()
    model_calls = run_state["model_calls"]
    reward = run_state["reward"]
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
    )
    strict = valid and run_state["exact_native_submission_marker"] is True and reward > 0
    status = "strict_passed" if strict else "infrastructure_only" if valid else "failed"
    return {
        "schema_version": 1,
        "kind": RECEIPT_KIND,
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


def _failed_router_audit() -> dict[str, bool]:
    return {
        "router_w2_profile_configured": False,
        "sticky_routing": False,
        "router_healthy": False,
    }


def orchestrate_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output_dir: Path | None = None
    receipt = public_receipt(
        shared.failed_run_state(),
        cleanup=False,
        router=_failed_router_audit(),
    )
    try:
        project_root = args.project_root.resolve(strict=True)
        workflow_dir = project_root / "user/tianhaowu/terminal_bench_vmvm"
        shared._clean_source(project_root, args.expected_revision)
        expected_files = {
            workflow_dir
            / "configs/eval/servers/cpu-132-021_8103/kimi_miniswe246_sandoq_firecracker_small_smoke.toml": EVAL_CONFIG_SHA256,
            workflow_dir
            / "configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json": PROVIDER_PROFILE_SHA256,
            workflow_dir / "configs/eval/mobius_valid_tasks_2500.txt": shared.APPROVED_TASK_FILE_SHA256,
            workflow_dir / "qwen_miniswe246_sandoq_smoke.py": SHARED_SMOKE_SHA256,
            workflow_dir / "direct_kimi_router.py": DIRECT_ROUTER_SHA256,
            workflow_dir / "direct_kimi_workers.py": DIRECT_WORKERS_SHA256,
            project_root / "extensions/sandoq/sandoq_provider/tunnel.py": shared.REFERENCE_TUNNEL_SHA256,
            args.image_manifest: shared.IMAGE_MANIFEST_SHA256,
        }
        if any(shared.sha256_file(path.resolve(strict=True)) != digest for path, digest in expected_files.items()):
            raise CanaryError("frozen_input_changed")
        shared.validate_sandoq_site(args.sandoq_site)
        base_url = _loopback_url(args.base_url, "/v1")
        router_stats_url = _loopback_url(args.router_stats_url, "/stats")
        job_id = os.environ.get("SLURM_JOB_ID", "")
        if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
            raise CanaryError("slurm_job_invalid")
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
        log = output_dir / "execution.log"
        log.touch(mode=0o600, exist_ok=False)
        selector = output_dir / "selected-task.txt"
        selector_sha256 = shared.materialize_selector(
            workflow_dir / "configs/eval/mobius_valid_tasks_2500.txt",
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
            "standard",
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
        remaining = max(1.0, ORCHESTRATOR_WALL_SECONDS - (time.monotonic() - started))
        shared._run_logged_with_environment(command, log, min(SUPERVISOR_WALL_SECONDS, remaining), environment)
        run_state = shared.read_private_json(output_dir / "run-private.json")
        cleanup = shared._cleanup_passed(output_dir / "sandoq_cleanup_audit.json")
        router_stats = read_router_stats(router_stats_url)
        shared.publish_private(
            output_dir / "control/direct-router-stats.private.json",
            router_stats,
        )
        router = router_audit(router_stats, int(run_state.get("model_calls", 0)))
        receipt = public_receipt(run_state, cleanup=cleanup, router=router)
        if time.monotonic() - started > ORCHESTRATOR_WALL_SECONDS:
            receipt = public_receipt(
                shared.failed_run_state(),
                cleanup=cleanup,
                router=router,
            )
        shared.publish_private(output_dir / "receipt.json", receipt)
    except Exception:
        if output_dir is not None and output_dir.is_dir() and not os.path.lexists(output_dir / "receipt.json"):
            with contextlib.suppress(Exception):
                shared.publish_private(output_dir / "receipt.json", receipt)
    print(shared.canonical_json(receipt).decode(), end="")
    return 0 if receipt["status"] == "strict_passed" else 2


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
    execute.add_argument("--wall-seconds", type=int, default=EXECUTION_WALL_SECONDS)
    supervised.add_argument("--workflow-dir", type=Path, required=True)
    supervised.add_argument("--log", type=Path, required=True)
    supervised.add_argument("--drain-marker", type=Path, required=True)
    orchestrate = commands.add_parser("orchestrate")
    orchestrate.add_argument("--project-root", type=Path, required=True)
    orchestrate.add_argument("--expected-revision", required=True)
    orchestrate.add_argument("--base-url", required=True)
    orchestrate.add_argument("--router-stats-url", required=True)
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
