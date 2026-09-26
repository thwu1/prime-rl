#!/usr/bin/env python3
"""Run and aggregate one content-blind Mini-SWE 2.4.6 Sandoq smoke."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import verifiers.v1 as vf
from aiohttp import ClientSession, ClientTimeout, TCPConnector, web
from deployment_endpoint import load_deployment_endpoint
from sandoq_provider.buffered_chat import BufferedChatCompletionsProxy
from terminal_bench_vmvm.taskset import (
    TerminalBenchTask,
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
)
from verifiers.v1.harnesses.mini_swe_agent.harness import PROGRAM_SOURCE
from verifiers.v1.runtimes.sandoq import SandoqConfig, SandoqRuntime

MODEL = "Qwen3.8-2.4T-A95B"
DEPLOYMENT_ID = "shared_qwen38_2p4t"
MARKER_COMMAND = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MAX_MODEL_CALLS = 3
MAX_BODY_BYTES = 32 * 1024 * 1024
APPROVED_TASK_FILE_SHA256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
SELECTED_LINE_SHA256 = "3e85139526ef240267f820a530ecb121638a7aa912e4f35120f0ac602fe30939"
IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
EVAL_CONFIG_SHA256 = "275d9bb4f0cd495455470caf4865c396626f5ca9f7274d2ad1db2afeb49962cf"
SANDOQ_SITE_NAME = "sandoq_x86_64_sdk1_82068"
SANDOQ_SITE_SHA256 = "df69cadb16edc799fcb62ea4fc144ee5d5572fe58fcd3e2bd6d165c607e02962"
SANDOQ_CLIENT_VERSION = "1.0.0.2026.9.23.82068.0+hg1a1d394e50c5"
REFERENCE_TUNNEL_SHA256 = "6bdb26e3676e161eb0a7cd57f42d4975c72ec51ba2fbb9ba1351c29eab4674bb"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SECURITY_LABEL_RE = re.compile(
    r"(?:^|[^a-z])(?:secur(?:ity|e)|cyber(?:security)?|"
    r"exploit(?:s|ation|able)?|malware|vulnerab(?:ility|ilities|le)?|"
    r"penetration|forensics?|ctf|credentials?|passwords?|secrets?|"
    r"attacks?|injections?|crypt(?:o|ography|ographic)?|devsecops|"
    r"infosec|appsec|secops|red[-_ ]?team|pwn(?:ing)?|cve(?:-[0-9]+)?|xss)(?:[^a-z]|$)",
    re.IGNORECASE,
)


class SmokeError(RuntimeError):
    """A smoke contract failed; callers expose only aggregate booleans."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_sandoq_site(path: Path) -> None:
    resolved = path.resolve(strict=True)
    if (
        resolved != path
        or path.is_symlink()
        or not resolved.is_dir()
        or path.name != SANDOQ_SITE_NAME
    ):
        raise SmokeError("sandoq_site_invalid")
    digest = hashlib.sha256()
    files = sorted(
        (
            item
            for item in resolved.rglob("*")
            if item.is_file() and item.suffix != ".pyc" and not item.name.startswith(".")
        ),
        key=lambda item: item.relative_to(resolved).as_posix(),
    )
    for item in files:
        relative = item.relative_to(resolved).as_posix()
        digest.update(f"{sha256_file(item)}  {relative}\n".encode())
    distributions = [
        distribution
        for distribution in importlib.metadata.distributions(path=[str(resolved)])
        if distribution.metadata["Name"].lower().replace("_", "-") == "sandoq-client"
    ]
    if (
        digest.hexdigest() != SANDOQ_SITE_SHA256
        or len(distributions) != 1
        or distributions[0].version != SANDOQ_CLIENT_VERSION
    ):
        raise SmokeError("sandoq_site_invalid")


def publish_private_bytes(path: Path, payload: bytes) -> None:
    parent = path.parent.resolve(strict=True)
    metadata = parent.lstat()
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise SmokeError("private_output_invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_private(path: Path, value: object) -> None:
    publish_private_bytes(path, canonical_json(value))


def read_private_json(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    metadata = resolved.lstat()
    if (
        resolved != path
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > MAX_BODY_BYTES
    ):
        raise SmokeError("private_input_invalid")
    value = json.loads(resolved.read_bytes())
    if not isinstance(value, dict):
        raise SmokeError("private_input_invalid")
    return value


def _security_metadata_is_absent(raw: dict[str, Any]) -> bool:
    if not isinstance(raw.get("metadata"), dict):
        return False
    if raw.get("task") is not None and not isinstance(raw.get("task"), dict):
        return False
    task = raw.get("task") if isinstance(raw.get("task"), dict) else {}
    metadata = raw["metadata"]
    values: list[str] = []
    for value in (metadata.get("category"), metadata.get("tags"), task.get("keywords")):
        if value is None:
            continue
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values.extend(value)
        else:
            return False
    return bool(values) and all(value.strip() for value in values) and not any(
        _SECURITY_LABEL_RE.search(value) for value in values
    )


def materialize_selector(
    approved_task_file: Path,
    dataset_dir: Path,
    destination: Path,
) -> str:
    """Resolve a preselected historical-positive row without exposing its identifier."""

    if sha256_file(approved_task_file) != APPROVED_TASK_FILE_SHA256:
        raise SmokeError("approved_selection_changed")
    matches: list[str] = []
    for line in approved_task_file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        slug = line.strip().split("\t", 1)[0]
        if hashlib.sha256(f"{slug}\n".encode()).hexdigest() == SELECTED_LINE_SHA256:
            matches.append(slug)
    if len(matches) != 1 or _SLUG_RE.fullmatch(matches[0]) is None:
        raise SmokeError("content_blind_selection_invalid")
    slug = matches[0]
    root = dataset_dir.resolve(strict=True)
    task_dir = (root / slug).resolve(strict=True)
    if task_dir.parent != root or task_dir.name != slug:
        raise SmokeError("content_blind_selection_invalid")
    try:
        raw = tomllib.loads((task_dir / "task.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SmokeError("content_blind_selection_invalid") from error
    environment = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    verifier = raw.get("verifier") if isinstance(raw.get("verifier"), dict) else {}
    if (
        not _security_metadata_is_absent(raw)
        or environment.get("network_mode") != "no-network"
        or verifier.get("network_mode") != "no-network"
        or verifier.get("environment") is not None
    ):
        raise SmokeError("content_blind_selection_invalid")
    payload = f"{slug}\n".encode()
    publish_private_bytes(destination, payload)
    return hashlib.sha256(payload).hexdigest()


def nonempty_reasoning_content(message: dict[str, Any]) -> bool:
    value = message.get("reasoning_content")
    return isinstance(value, str) and bool(value.strip())


def normalize_reasoning_content(message: dict[str, Any]) -> None:
    """Copy the Kimi wire alias into the canonical training field."""

    canonical = message.get("reasoning_content")
    alternate = message.get("reasoning")
    if (not isinstance(canonical, str) or not canonical.strip()) and isinstance(alternate, str):
        if alternate.strip():
            message["reasoning_content"] = alternate


class ModelRelay:
    def __init__(
        self,
        upstream: str,
        secret: str,
        session_id: str,
        *,
        model: str = MODEL,
        max_output_tokens: int = 8192,
        request_timeout_seconds: int = 90,
        reasoning_effort: str | None = None,
    ) -> None:
        self.upstream = upstream.rstrip("/") + "/chat/completions"
        self.secret = secret
        self.session_id = session_id
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.request_timeout_seconds = request_timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.reasoning: list[bool] = []
        self.prior_reasoning: list[int] = []
        self._runner: web.AppRunner | None = None
        self._session: ClientSession | None = None
        self.port = 0

    async def start(self) -> None:
        self._session = ClientSession(
            connector=TCPConnector(limit=1, limit_per_host=1, ttl_dns_cache=300),
            timeout=ClientTimeout(total=self.request_timeout_seconds, connect=15),
            trust_env=False,
        )
        app = web.Application(client_max_size=MAX_BODY_BYTES)
        app.router.add_post("/v1/chat/completions", self.handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        if site._server is None or not site._server.sockets:
            raise SmokeError("relay_start_failed")
        self.port = int(site._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def handle(self, request: web.Request) -> web.Response:
        raw_request = await request.read()
        if len(raw_request) > MAX_BODY_BYTES:
            return web.json_response({"error": {"type": "request_too_large"}}, status=413)
        try:
            body = json.loads(raw_request)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return web.json_response({"error": {"type": "invalid_json"}}, status=400)
        if not isinstance(body, dict) or body.get("model") != self.model:
            return web.json_response({"error": {"type": "invalid_request"}}, status=400)
        requested_stream = bool(body.get("stream"))
        for name in ("logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"):
            body.pop(name, None)
        body["stream"] = False
        body.pop("stream_options", None)
        body["max_tokens"] = min(
            int(body.get("max_tokens") or self.max_output_tokens),
            self.max_output_tokens,
        )
        body.setdefault("temperature", 0.7)
        body.setdefault("top_p", 0.95)
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        body.setdefault(
            "chat_template_kwargs",
            {"enable_thinking": True, "preserve_thinking": True},
        )
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        self.prior_reasoning.append(
            sum(
                nonempty_reasoning_content(message)
                for message in messages
                if isinstance(message, dict) and message.get("role") == "assistant"
            )
        )
        # There is no await between this check and append, so reservation is
        # atomic with respect to other aiohttp handlers on the event loop.
        if len(self.requests) >= MAX_MODEL_CALLS:
            self.prior_reasoning.pop()
            return web.json_response({"error": {"type": "step_limit"}}, status=429)
        self.requests.append(body)
        if self._session is None:
            raise SmokeError("relay_not_started")
        async with self._session.post(
            self.upstream,
            json=body,
            headers={
                "Authorization": f"Bearer {self.secret}",
                "Content-Type": "application/json",
                "X-Session-ID": self.session_id,
            },
        ) as response:
            raw_response = await response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "application/json").split(";", 1)[0]
        if len(raw_response) > MAX_BODY_BYTES:
            return web.json_response({"error": {"type": "response_too_large"}}, status=502)
        try:
            response_body = json.loads(raw_response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response_body = {"error": {"type": "invalid_upstream_json"}}
            status = 502
        self.responses.append(response_body)
        choices = response_body.get("choices") if isinstance(response_body, dict) else None
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        normalize_reasoning_content(message)
        self.reasoning.append(status == 200 and nonempty_reasoning_content(message))
        if status < 200 or status >= 300:
            return web.Response(body=raw_response, status=status, content_type=content_type)
        if not requested_stream:
            return web.Response(body=canonical_json(response_body), status=200, content_type=content_type)
        try:
            events = BufferedChatCompletionsProxy._chat_events(response_body)
        except (AttributeError, TypeError, ValueError):
            return web.json_response({"error": {"type": "invalid_upstream_completion"}}, status=502)
        return web.Response(
            body=b"".join(events),
            status=200,
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )


def trajectory_audit(payload: bytes, model_calls: int) -> dict[str, Any]:
    trajectory = json.loads(payload)
    if not isinstance(trajectory, dict):
        raise SmokeError("trajectory_invalid")
    info = trajectory.get("info") if isinstance(trajectory.get("info"), dict) else {}
    model_stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
    messages = trajectory.get("messages") if isinstance(trajectory.get("messages"), list) else []
    marker_action_ids: list[str] = []
    action_ids: list[str] = []
    assistant_reasoning = 0
    tool_results: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            assistant_reasoning += int(nonempty_reasoning_content(message))
            extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
            actions = extra.get("actions") if isinstance(extra.get("actions"), list) else []
            for action in actions:
                if not isinstance(action, dict) or not isinstance(action.get("tool_call_id"), str):
                    continue
                action_ids.append(action["tool_call_id"])
                if action.get("command") == MARKER_COMMAND:
                    marker_action_ids.append(action["tool_call_id"])
        elif message.get("role") == "tool":
            extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
            call_id = message.get("tool_call_id")
            returncode = extra.get("returncode")
            if isinstance(call_id, str) and isinstance(returncode, int) and not isinstance(returncode, bool):
                tool_results[call_id] = returncode
    shell_execution = (
        bool(action_ids)
        and len(action_ids) == len(tool_results)
        and len(action_ids) == len(set(action_ids))
        and all(tool_results.get(call_id) == 0 for call_id in action_ids)
    )
    return {
        "model_calls": model_calls,
        "api_calls_match": model_stats.get("api_calls") == model_calls,
        "mini_version_match": info.get("mini_version") == "2.4.6",
        "submitted": info.get("exit_status") == "Submitted",
        "shell_execution": shell_execution,
        "exact_native_submission_marker": (len(marker_action_ids) == 1 and tool_results.get(marker_action_ids[0]) == 0),
        "trajectory_reasoning_retained": assistant_reasoning == model_calls,
    }


def load_selected_task(
    selector: Path,
    selector_sha256: str,
    dataset_dir: Path,
    image_manifest: Path,
) -> tuple[TerminalBenchVMVMTaskset, TerminalBenchTask]:
    if _SHA256_RE.fullmatch(selector_sha256) is None or sha256_file(selector) != selector_sha256:
        raise SmokeError("selected_task_invalid")
    config = TerminalBenchVMVMConfig(
        dataset_dir=dataset_dir,
        dataset_revision=DATASET_REVISION,
        task_file=selector,
        task_file_sha256=selector_sha256,
        image_manifest=image_manifest,
        image_manifest_sha256=IMAGE_MANIFEST_SHA256,
        ignore_dockerfile=True,
        verifier_runtime_retries=0,
        timeout_multiplier=0.1,
    )
    taskset = TerminalBenchVMVMTaskset(config)
    tasks = taskset.load_tasks()
    if len(tasks) != 1:
        raise SmokeError("selected_task_invalid")
    task = tasks[0]
    if (
        task.verifier_mode != "shared"
        or task.agent_network_mode != "no-network"
        or task.verifier_network_mode != "no-network"
        or task.image is None
        or "@sha256:" not in task.image
    ):
        raise SmokeError("selected_task_invalid")
    return taskset, task


async def execute_smoke(args: argparse.Namespace) -> dict[str, Any]:
    taskset, task = load_selected_task(
        args.selector,
        args.selector_sha256,
        args.dataset_dir,
        args.image_manifest,
    )
    endpoint = load_deployment_endpoint(
        args.proxy_info,
        deployment_id=DEPLOYMENT_ID,
        expected_model=MODEL,
        deployment_spec=args.deployment_spec,
    )
    relay = ModelRelay(endpoint.client_base_url, endpoint.api_key, os.urandom(16).hex())
    runtime = SandoqRuntime(
        SandoqConfig(
            image=task.image,
            workdir=task.workdir or "/app",
            network_access=True,
            mode="oci-runner",
            session_timeout=240,
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
        name=f"qwen-miniswe246-{os.urandom(6).hex()}",
    )
    trace = vf.Trace(task=task)
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
                if PROGRAM_SOURCE.count(dependency) != 1:
                    raise SmokeError("mini_swe_program_contract_changed")
                source = PROGRAM_SOURCE.replace(dependency, replacement).replace("{version}", "2.4.6")
                program = await runtime.prepare_uv_script(source, {})
                trajectory_path = "/tmp/qwen-miniswe246-smoke.traj.json"
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
                    "agent.wall_time_limit_seconds=180",
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
        raise SmokeError("agent_result_missing")
    audit = trajectory_audit(trajectory_bytes, len(relay.requests))
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
    publish_private(args.output_dir / "raw-trace.json", raw)
    publish_private(args.output_dir / "run-private.json", run_state)
    return run_state


def failed_run_state() -> dict[str, Any]:
    return {
        "sandbox_lifecycle": False,
        "model_calls": 0,
        "shell_execution": False,
        "exact_native_submission_marker": False,
        "reasoning_content_retained": False,
        "reward": None,
        "program_exit_ok": False,
        "api_calls_match": False,
        "mini_version_match": False,
    }


def execute_command(args: argparse.Namespace) -> int:
    try:
        state = asyncio.run(execute_smoke(args))
    except Exception:
        with contextlib.suppress(Exception):
            publish_private(args.output_dir / "run-private.json", failed_run_state())
        return 2
    return 0 if state["program_exit_ok"] else 2


def _run_logged(command: list[str], log: Path, timeout: float) -> int:
    with log.open("ab", buffering=0) as stream:
        process = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            return 124


def supervised_command(args: argparse.Namespace) -> int:
    execute = [
        "/usr/bin/timeout",
        "--foreground",
        "--signal=TERM",
        "--kill-after=10s",
        "220s",
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
        "--proxy-info",
        str(args.proxy_info),
        "--deployment-spec",
        str(args.deployment_spec),
        "--output-dir",
        str(args.output_dir),
        "--wall-seconds",
        "200",
    ]
    eval_status = _run_logged(execute, args.log, 230)
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
    _run_logged(cleanup, args.log, 30)
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
    cleanup_evidence_status = _run_logged(sanitize, args.log, 10)
    return 0 if eval_status == 0 and cleanup_evidence_status == 0 else 2


def _clean_source(project_root: Path, expected_revision: str) -> None:
    if _REVISION_RE.fullmatch(expected_revision) is None:
        raise SmokeError("source_revision_invalid")
    commands = (
        ["git", "rev-parse", "HEAD"],
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    )
    outputs = [
        subprocess.run(command, cwd=project_root, check=True, capture_output=True).stdout.decode().strip()
        for command in commands
    ]
    if outputs != [expected_revision, ""]:
        raise SmokeError("source_revision_invalid")
    nested = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root / "deps/verifiers",
        check=True,
        capture_output=True,
    ).stdout
    if nested:
        raise SmokeError("source_revision_invalid")


def _cleanup_passed(path: Path) -> bool:
    try:
        value = read_private_json(path)
    except (OSError, ValueError, SmokeError):
        return False
    return (
        value.get("kind") == "sandoq-pool-cleanup"
        and value.get("state") == "passed"
        and value.get("failures") == 0
        and value.get("assignments_acquired") == 1
        and value.get("assignments_cleanup_verified") == 1
        and value.get("outer_sessions_created") == value.get("outer_sessions_deleted") == 1
    )


def public_receipt(run_state: dict[str, Any], cleanup: bool) -> dict[str, Any]:
    expected = set(failed_run_state())
    if set(run_state) != expected:
        run_state = failed_run_state()
    model_calls = run_state["model_calls"]
    reward = run_state["reward"]
    valid = (
        run_state["sandbox_lifecycle"] is True
        and isinstance(model_calls, int)
        and not isinstance(model_calls, bool)
        and 1 <= model_calls <= MAX_MODEL_CALLS
        and run_state["shell_execution"] is True
        and run_state["reasoning_content_retained"] is True
        and run_state["program_exit_ok"] is True
        and run_state["api_calls_match"] is True
        and run_state["mini_version_match"] is True
        and isinstance(reward, (int, float))
        and not isinstance(reward, bool)
        and cleanup
    )
    strict = valid and run_state["exact_native_submission_marker"] is True and reward > 0
    status = "strict_passed" if strict else "infrastructure_only" if valid else "failed"
    return {
        "schema_version": 1,
        "kind": "qwen-miniswe246-sandoq-smoke",
        "sandbox_lifecycle": bool(run_state["sandbox_lifecycle"]),
        "model_calls": model_calls if isinstance(model_calls, int) else 0,
        "shell_execution": bool(run_state["shell_execution"]),
        "exact_native_submission_marker": bool(run_state["exact_native_submission_marker"]),
        "reasoning_content_retained": bool(run_state["reasoning_content_retained"]),
        "reward": float(reward) if isinstance(reward, (int, float)) and not isinstance(reward, bool) else None,
        "status": status,
        "cleanup": cleanup,
    }


def orchestrate_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output_dir: Path | None = None
    receipt = public_receipt(failed_run_state(), False)
    try:
        project_root = args.project_root.resolve(strict=True)
        workflow_dir = project_root / "user/tianhaowu/terminal_bench_vmvm"
        _clean_source(project_root, args.expected_revision)
        expected_files = {
            workflow_dir / "configs/eval/qwen_miniswe246_sandoq_firecracker_smoke.toml": EVAL_CONFIG_SHA256,
            workflow_dir / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json": PROVIDER_PROFILE_SHA256,
            workflow_dir / "configs/eval/mobius_valid_tasks_2500.txt": APPROVED_TASK_FILE_SHA256,
            project_root / "extensions/sandoq/sandoq_provider/tunnel.py": REFERENCE_TUNNEL_SHA256,
            args.image_manifest: IMAGE_MANIFEST_SHA256,
        }
        if any(sha256_file(path.resolve(strict=True)) != digest for path, digest in expected_files.items()):
            raise SmokeError("frozen_input_changed")
        validate_sandoq_site(args.sandoq_site)
        job_id = os.environ.get("SLURM_JOB_ID", "")
        if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
            raise SmokeError("slurm_job_invalid")
        if not args.output_root.is_absolute() or args.output_root != Path(os.path.normpath(args.output_root)):
            raise SmokeError("output_root_invalid")
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
            raise SmokeError("output_root_invalid")
        output_dir = output_root / f"run-{job_id}"
        output_dir.mkdir(mode=0o700)
        (output_dir / "control").mkdir(mode=0o700)
        log = output_dir / "execution.log"
        log.touch(mode=0o600, exist_ok=False)
        selector = output_dir / "selected-task.txt"
        selector_sha256 = materialize_selector(
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
            os.path.lexists(path) for path in (pool_socket, pool_socket.with_suffix(".sock.owner.json"), drain_marker)
        ):
            raise SmokeError("pool_state_not_fresh")
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
                "SANDOQ_OWNER": f"{environment.get('USER', 'runner')}-qwen-mswe246-{job_id}",
                "OCI_RUNNER_POOL_SOCKET": str(pool_socket),
                "OCI_RUNNER_POOL_WAL": str(output_dir / "control/sandoq-pool.wal.jsonl"),
                "OCI_RUNNER_POOL_EVENT_LOG": str(output_dir / "pool_events.jsonl"),
            }
        )
        profile = workflow_dir / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json"
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
            "--proxy-info",
            str(args.proxy_info),
            "--deployment-spec",
            str(args.deployment_spec),
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
        remaining = max(1.0, 280.0 - (time.monotonic() - started))
        _run_logged_with_environment(command, log, min(260.0, remaining), environment)
        run_state = read_private_json(output_dir / "run-private.json")
        cleanup = _cleanup_passed(output_dir / "sandoq_cleanup_audit.json")
        receipt = public_receipt(run_state, cleanup)
        if time.monotonic() - started > 295:
            receipt = public_receipt(failed_run_state(), cleanup)
        publish_private(output_dir / "receipt.json", receipt)
    except Exception:
        if output_dir is not None and output_dir.is_dir() and not os.path.lexists(output_dir / "receipt.json"):
            with contextlib.suppress(Exception):
                publish_private(output_dir / "receipt.json", receipt)
    print(canonical_json(receipt).decode(), end="")
    return 0 if receipt["status"] == "strict_passed" else 2


def _run_logged_with_environment(
    command: list[str],
    log: Path,
    timeout: float,
    environment: dict[str, str],
) -> int:
    with log.open("ab", buffering=0) as stream:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            return 124


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
        command.add_argument("--proxy-info", type=Path, required=True)
        command.add_argument("--deployment-spec", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--wall-seconds", type=int, default=200)
    supervised.add_argument("--workflow-dir", type=Path, required=True)
    supervised.add_argument("--log", type=Path, required=True)
    supervised.add_argument("--drain-marker", type=Path, required=True)
    orchestrate = commands.add_parser("orchestrate")
    orchestrate.add_argument("--project-root", type=Path, required=True)
    orchestrate.add_argument("--expected-revision", required=True)
    orchestrate.add_argument(
        "--output-root",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/qwen-miniswe246-sandoq"),
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
        "--proxy-info",
        type=Path,
        default=Path("/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t/proxy_info.json"),
    )
    orchestrate.add_argument(
        "--deployment-spec",
        type=Path,
        default=Path("/checkpoint/ram/shared/vllm_deployments_v2/shared_qwen38_2p4t/spec.yaml"),
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
