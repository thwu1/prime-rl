#!/usr/bin/env python3
"""Run an agent harness inside one SWE-rebench task over a Sandoq tunnel.

The Muse Code, OpenCode, and Pi binaries come from the immutable agent-toolbox
image. Model API TLS and the caller's client certificate remain outside
Firecracker: the guest sees only the environment's loopback tunnel listener,
while a small local proxy streams requests to the authenticated upstream.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shlex
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import proxy_bypass

from aiohttp import ClientConnectionResetError, ClientSession, ClientTimeout, TCPConnector, web
from sandoq_provider.gateway import get_gateway_adapter
from sandoq_provider.tunnel import SandoqRelayTunnel

DEFAULT_ENVIRONMENT = "oci-runner-firecracker-small"
DEFAULT_GATEWAY = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
DEFAULT_GUEST_MODEL_API = "http://127.0.0.1:8485/v1"
DEFAULT_MODEL_API = "https://metacode-modelapi.ai-gateway.fbinfra.net"
DEFAULT_MODEL = "muse-spark-1.3-internal"
DEFAULT_TOOLBOX = (
    "588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/ram/"
    "prime-agent-toolbox@sha256:ddb5fd956b7cc248c12de137ad75d269f1f4d1088c917887e372e93e3698902a"
)
DEV_ECR_REGISTRY = "588845226011.dkr.ecr.us-east-2.amazonaws.com"
PROD_ECR_REGISTRY = "168653207203.dkr.ecr.us-east-2.amazonaws.com"
REGISTRY_AUTH_FILE = "/dev/shm/muse-registry-auth.json"
SAFE_IMAGE = re.compile(r"[A-Za-z0-9._:/@+-]+")
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_STRIP_HEADERS = HOP_HEADERS | {
    "api-key",
    "authorization",
    "content-length",
    "host",
    "x-api-key",
}


@dataclass
class ProxyStats:
    requests: int = 0
    response_bytes: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, status: int, response_bytes: int) -> None:
        with self._lock:
            self.requests += 1
            self.response_bytes += response_bytes
            key = str(status)
            self.statuses[key] = self.statuses.get(key, 0) + 1

    def record_error(self, error: BaseException) -> None:
        message = f"{type(error).__name__}: {error}"
        with self._lock:
            self.errors.append(message[:1000])
            del self.errors[:-20]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests": self.requests,
                "response_bytes": self.response_bytes,
                "statuses": dict(self.statuses),
                "errors": list(self.errors),
            }


class ModelApiProxy:
    """A caller-local streaming HTTP-to-mTLS Model API proxy."""

    def __init__(self, upstream: str, cert: Path, key: Path, ca: Path) -> None:
        parsed = urlsplit(upstream)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Model API upstream must be an explicit HTTPS URL")
        self._upstream = upstream.rstrip("/")
        self._context = ssl.create_default_context(cafile=str(ca))
        self._context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        self._proxy_url = None
        if not proxy_bypass(parsed.hostname):
            self._proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self.port = 0
        self.stats = ProxyStats()

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        headers = {name: value for name, value in request.headers.items() if name.lower() not in REQUEST_STRIP_HEADERS}
        try:
            body = await request.read()
            session: ClientSession = request.app["upstream_session"]
            async with session.request(
                request.method,
                self._upstream + request.path_qs,
                data=body or None,
                headers=headers,
                proxy=self._proxy_url,
                ssl=self._context,
            ) as upstream:
                response_headers = {
                    name: value
                    for name, value in upstream.headers.items()
                    if name.lower() not in HOP_HEADERS | {"content-length"}
                }
                response = web.StreamResponse(status=upstream.status, headers=response_headers)
                await response.prepare(request)
                byte_count = 0
                try:
                    async for chunk in upstream.content.iter_chunked(65536):
                        byte_count += len(chunk)
                        await response.write(chunk)
                    await response.write_eof()
                except (ClientConnectionResetError, ConnectionResetError):
                    # Some harnesses close an SSE response immediately after
                    # receiving the terminal event. The request was still
                    # successfully served and should not become a proxy 500.
                    pass
                finally:
                    self.stats.record(upstream.status, byte_count)
                return response
        except Exception as error:  # noqa: BLE001 - preserve a bounded proxy diagnostic
            self.stats.record_error(error)
            if request.transport is None or request.transport.is_closing():
                raise
            return web.json_response({"error": "local Model API proxy failure"}, status=502)

    async def _serve(self) -> None:
        connector = TCPConnector(ssl=self._context)
        timeout = ClientTimeout(total=None, connect=120, sock_connect=120, sock_read=None)
        async with ClientSession(
            connector=connector,
            timeout=timeout,
            auto_decompress=False,
        ) as session:
            app = web.Application(client_max_size=32 * 1024**2)
            app["upstream_session"] = session
            app.router.add_route("*", "/{path:.*}", self._handle)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            server = site._server  # aiohttp does not expose the chosen ephemeral port.
            assert server is not None and server.sockets
            self.port = int(server.sockets[0].getsockname()[1])
            self._stop = asyncio.Event()
            self._ready.set()
            try:
                await self._stop.wait()
            finally:
                await runner.cleanup()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._serve())
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
        finally:
            loop.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="muse-model-api-proxy")
        self._thread.start()
        if not self._ready.wait(30):
            raise TimeoutError("local Model API proxy did not start")
        if self._startup_error is not None:
            raise RuntimeError(f"local Model API proxy failed: {self._startup_error}")

    def stop(self) -> None:
        loop = self._loop
        stop = self._stop
        if loop is not None and stop is not None and loop.is_running():
            loop.call_soon_threadsafe(stop.set)
        if self._thread is not None:
            self._thread.join(timeout=10)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "\n" in value or "\r" in value:
        raise RuntimeError(f"{name} must contain one nonempty line")
    return value


def _login_command(registry: str, password: str) -> str:
    encoded = base64.b64encode(password.encode()).decode()
    return (
        "umask 077; "
        f"printf %s {encoded} | base64 -d | "
        f"podman login --authfile {REGISTRY_AUTH_FILE} "
        f"--username AWS --password-stdin {registry} >/dev/null"
    )


def _mirror_image(image: str) -> str:
    prefix = "docker.io/"
    if not image.startswith(prefix):
        raise ValueError(f"expected a docker.io SWE-rebench image, got {image!r}")
    return f"{PROD_ECR_REGISTRY}/pt_dockerio/{image.removeprefix(prefix)}"


def _safe_remote_path(path: str) -> str:
    if not path.startswith("/home/runner/shared/muse-run/"):
        raise ValueError(f"unexpected guest artifact path: {path}")
    return path


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--toolbox-image", default=DEFAULT_TOOLBOX)
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--guest-model-api", default=DEFAULT_GUEST_MODEL_API)
    parser.add_argument("--model-api", default=DEFAULT_MODEL_API)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--harness", choices=("muse", "opencode", "pi"), default="muse")
    parser.add_argument("--max-model-steps", type=int, default=20)
    parser.add_argument("--agent-timeout", type=int, default=1800)
    parser.add_argument("--allocation-timeout", type=int, default=8 * 60 * 60)
    parser.add_argument("--lease", default="45m")
    parser.add_argument(
        "--muse-cert",
        type=Path,
        default=Path("/var/facebook/credentials")
        / os.environ.get("USER", "")
        / "agent_x509"
        / f"muse_{os.environ.get('USER', '')}.pem",
    )
    parser.add_argument("--muse-key", type=Path)
    parser.add_argument("--muse-ca", type=Path, default=Path("/var/facebook/rootcanal/ca.pem"))
    args = parser.parse_args()

    if args.max_model_steps < 1 or args.agent_timeout < 1 or args.allocation_timeout < 1:
        raise ValueError("model steps and timeouts must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    task = json.loads(args.task_json.read_text())
    instance_id = str(task["instance_id"])
    workdir = str(task["working_dir"])
    base_commit = str(task["base_commit"])
    task_image = _mirror_image(str(task["requested_image"]))
    harness_binary = {
        "muse": "/toolbox/opt/prime-agents/muse/muse",
        "opencode": "/toolbox/opt/prime-agents/opencode/opencode",
        "pi": "/toolbox/opt/prime-agents/pi/pi",
    }[args.harness]
    for image in (args.toolbox_image, task_image):
        if not SAFE_IMAGE.fullmatch(image):
            raise ValueError(f"image reference contains unsupported characters: {image!r}")
    if not re.fullmatch(r"/[A-Za-z0-9._/+@-]+", workdir):
        raise ValueError(f"unsupported task working directory: {workdir!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise ValueError(f"unsupported base commit: {base_commit!r}")

    token = _required_env("FIRECRACKER_KEY")
    dev_password = _required_env("DEV_ECR_PASSWORD")
    prod_password = _required_env("PROD_ECR_PASSWORD")
    muse_key = args.muse_key or args.muse_cert
    for path in (args.muse_cert, muse_key, args.muse_ca):
        if not path.is_file():
            raise FileNotFoundError(path)

    allocation_request_id = f"{args.harness}-rebench-" + uuid.uuid4().hex
    summary: dict[str, Any] = {
        "allocation_request_id": allocation_request_id,
        "allocation_timeout_seconds": args.allocation_timeout,
        "instance_id": instance_id,
        "base_commit": base_commit,
        "workdir": workdir,
        "task_image": task_image,
        "toolbox_image": args.toolbox_image,
        "environment": args.environment,
        "harness": args.harness,
        "model": args.model,
        "max_model_steps": args.max_model_steps,
        "model_step_limit_enforced": args.harness == "muse",
        "started_at_unix": time.time(),
        "success": False,
    }
    _write_json(args.output_dir / "summary.json", summary)

    gateway = get_gateway_adapter(args.gateway, os.environ.get("USER", "agent-rebench-probe"))
    session = None
    proxy = ModelApiProxy(args.model_api, args.muse_cert, muse_key, args.muse_ca)
    tunnel: SandoqRelayTunnel | None = None

    def guest(script: str, timeout: int = 270, *, check: bool = True) -> dict[str, Any]:
        assert session is not None
        response = gateway.request_json(
            "POST",
            session.port_urls["exec"].rstrip("/") + "/v1/exec",
            body={"command": ["bash", "-lc", script], "timeout": timeout},
            headers={"Authorization": f"Bearer {token}"},
            timeout=float(timeout + 30),
        )
        if response.status_code != 200:
            raise RuntimeError(f"guest exec failed with HTTP {response.status_code}")
        body = dict(response.body)
        exit_code = body.get("exitCode", body.get("exit_code"))
        if check and exit_code != 0:
            stdout = str(body.get("stdout", ""))[-4000:]
            stderr = str(body.get("stderr", ""))[-4000:]
            raise RuntimeError(f"guest command failed ({exit_code}): stdout={stdout!r} stderr={stderr!r}")
        return body

    def pull_image(image: str, timeout: float = 1200) -> None:
        print(f"pulling={image}", flush=True)
        pull_dir = f"/tmp/muse-pull-{uuid.uuid4().hex}"
        log_path = f"{pull_dir}/pull.log"
        status_path = f"{pull_dir}/status"
        inner = "\n".join(
            [
                "set +e",
                f"podman pull --authfile {REGISTRY_AUTH_FILE} {shlex.quote(image)} >{shlex.quote(log_path)} 2>&1",
                "rc=$?",
                f"printf '%s\\n' \"$rc\" >{shlex.quote(status_path)}.tmp",
                f"mv -f {shlex.quote(status_path)}.tmp {shlex.quote(status_path)}",
            ]
        )
        guest(
            "\n".join(
                [
                    "set -eu",
                    f"rm -rf {shlex.quote(pull_dir)}",
                    f"mkdir -p {shlex.quote(pull_dir)}",
                    f"setsid bash -lc {shlex.quote(inner)} </dev/null >/dev/null 2>&1 &",
                    "echo STARTED",
                ]
            ),
            timeout=30,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            poll = guest(
                "\n".join(
                    [
                        f"if test -f {shlex.quote(status_path)}; then",
                        f"  echo FINISHED:$(cat {shlex.quote(status_path)})",
                        f"  tail -c 4000 {shlex.quote(log_path)} || true",
                        "else",
                        "  echo RUNNING",
                        "fi",
                    ]
                ),
                timeout=30,
            )
            output = str(poll.get("stdout", ""))
            first = output.partition("\n")[0].strip()
            if first.startswith("FINISHED:"):
                exit_code = int(first.removeprefix("FINISHED:"))
                if exit_code:
                    raise RuntimeError(f"podman pull failed for {image}: {output[-4000:]}")
                inspection = guest(f"podman image inspect {shlex.quote(image)} --format '{{{{.Id}}}}'", timeout=30)
                print(f"pulled_id={str(inspection.get('stdout', '')).strip()}", flush=True)
                guest(f"rm -rf {shlex.quote(pull_dir)}", timeout=30)
                return
            time.sleep(5)
        raise TimeoutError(f"timed out pulling {image}")

    def write_guest_file(path: str, content: bytes) -> None:
        path = _safe_remote_path(path)
        encoded = base64.b64encode(content).decode()
        guest(f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}", timeout=60)

    def download_guest_file(path: str, destination: Path) -> bool:
        path = _safe_remote_path(path)
        size_result = guest(
            f"if test -f {shlex.quote(path)}; then wc -c < {shlex.quote(path)}; else echo MISSING; fi",
            timeout=30,
        )
        text = str(size_result.get("stdout", "")).strip()
        if text == "MISSING":
            return False
        size = int(text)
        chunk_size = 512 * 1024
        with destination.open("wb") as stream:
            for offset in range(0, size, chunk_size):
                count = min(chunk_size, size - offset)
                result = guest(
                    "dd "
                    f"if={shlex.quote(path)} iflag=skip_bytes,count_bytes "
                    f"skip={offset} count={count} status=none | base64 -w0",
                    timeout=60,
                )
                stream.write(base64.b64decode(str(result.get("stdout", ""))))
        if destination.stat().st_size != size:
            raise RuntimeError(f"short artifact download for {path}")
        return True

    try:
        session = gateway.create_session(
            args.environment,
            args.lease,
            # The maintained client retries capacity 429s with this exact ID,
            # allowing the elastic pool to satisfy one logical request without
            # duplicate leases.  Keep the outer bound aligned with its 8h cap.
            allocation_request_id,
            timeout=args.allocation_timeout,
        )
        summary["session_id"] = session.session_id
        summary["session_ports"] = sorted(session.port_urls)
        _write_json(args.output_dir / "summary.json", summary)
        print(f"session={session.session_id} ports={','.join(sorted(session.port_urls))}", flush=True)
        if "exec" not in session.port_urls or "tunnel" not in session.port_urls:
            raise RuntimeError("Firecracker session did not expose both exec and tunnel ports")

        guest(_login_command(DEV_ECR_REGISTRY, dev_password), timeout=60)
        guest(_login_command(PROD_ECR_REGISTRY, prod_password), timeout=60)
        pull_image(args.toolbox_image)
        pull_image(task_image)
        guest(f"rm -f {REGISTRY_AUTH_FILE}", timeout=30)

        guest("rm -rf /home/runner/shared/muse-run && mkdir -p /home/runner/shared/muse-run", timeout=30)
        run_arguments = [
            "podman",
            "run",
            "--detach",
            "--name",
            "task",
            "--network",
            "host",
            "--memory",
            "6g",
            "--memory-swap",
            "6g",
            "--pids-limit",
            "512",
            "--env",
            "PYTEST_XDIST_AUTO_NUM_WORKERS=4",
            "--env",
            "OMP_NUM_THREADS=4",
            "--volume",
            "/home/runner/shared:/shared",
            "--mount",
            f"type=image,source={args.toolbox_image},target=/toolbox",
            "--entrypoint",
            "/bin/bash",
            task_image,
            "-lc",
            "trap : TERM INT; sleep infinity & wait",
        ]
        guest("podman rm -f task >/dev/null 2>&1 || true\n" + shlex.join(run_arguments), timeout=180)
        repo_probe = guest(
            "podman exec task bash -lc "
            + shlex.quote(
                f"cd {shlex.quote(workdir)} && "
                "printf 'head=%s\\n' \"$(git rev-parse HEAD)\" && "
                'printf \'dirty=%s\\n\' "$(test -z "$(git status --porcelain)" && echo no || echo yes)" && '
                "printf 'arch=%s\\n' \"$(uname -m)\" && "
                f"printf 'harness={args.harness}\\n' && "
                f"printf 'version=%s\\n' \"$({harness_binary} --version)\""
            ),
            timeout=60,
        )
        probe_output = str(repo_probe.get("stdout", ""))
        print(probe_output.strip(), flush=True)
        if f"head={base_commit}" not in probe_output or "dirty=no" not in probe_output:
            raise RuntimeError("task image repository is not pristine at the expected base commit")

        prompt = "\n".join(
            [
                "You are solving one SWE-rebench task in the repository already open as your workspace.",
                "Inspect the code, implement the smallest robust production fix, and run focused tests.",
                "Do not modify tests. Do not merely describe a patch: edit the working tree and verify it.",
                "When finished, give a concise summary and the tests you ran.",
                "",
                "Task:",
                str(task["problem_statement"]),
            ]
        )
        write_guest_file("/home/runner/shared/muse-run/prompt.txt", prompt.encode())
        write_guest_file("/home/runner/shared/muse-run/test.patch", str(task["test_patch"]).encode())

        proxy.start()
        print(f"local_model_proxy=127.0.0.1:{proxy.port}", flush=True)
        tunnel = SandoqRelayTunnel(
            proxy.port,
            tunnel_url=session.port_urls["tunnel"],
            local_host="127.0.0.1",
            pool_size=4,
            ready_timeout=30,
        )
        tunnel.start()
        print("reverse_tunnel=ready pool=4 guest=127.0.0.1:8485", flush=True)

        trace_name = f"{args.harness}.jsonl"
        stderr_name = f"{args.harness}.stderr"
        agent_prelude = [
            "set +e",
            f"cd {shlex.quote(workdir)} || exit 90",
            "mkdir -p /tmp/agent-home /tmp/agent-tmp",
        ]
        config_names: list[str] = []
        prompt_argument = False
        if args.harness == "muse":
            agent_command = [
                harness_binary,
                "exec",
                "--json",
                "--provider",
                "meta",
                "--model",
                args.model,
                "--base-url",
                args.guest_model_api,
                "--workspace",
                workdir,
                "--max-model-steps",
                str(args.max_model_steps),
                "--reasoning-effort",
                "high",
                "--preset",
                "native-basic",
                "--yolo",
                "--disable-web-tools",
                "--no-foreign-personal-context",
                "--no-session-log",
                "--prompt-file",
                "/shared/muse-run/prompt.txt",
            ]
            # Muse requires a syntactically present provider credential even
            # when the endpoint is an auth-terminating local relay. It is
            # deliberately inert; the caller-side proxy supplies mTLS.
            agent_prelude.append(
                "export HOME=/tmp/agent-home TMPDIR=/tmp/agent-tmp NO_COLOR=1 META_API_KEY=sandoq-local-relay"
            )
        elif args.harness == "opencode":
            opencode_config = {
                "tools": {"webfetch": False, "websearch": False},
                "provider": {
                    "modelapi": {
                        # Use OpenCode's Responses adapter so all three
                        # harnesses speak the same Model API protocol.
                        "npm": "@ai-sdk/openai",
                        "name": "Model API",
                        "options": {
                            "baseURL": args.guest_model_api,
                            "apiKey": "sandoq-local-relay",
                        },
                        "models": {
                            args.model: {
                                "name": "Muse Spark 1.3",
                                "limit": {"context": 200000, "output": 32768},
                                "options": {"reasoningEffort": "high"},
                            }
                        },
                    }
                },
            }
            write_guest_file(
                "/home/runner/shared/muse-run/opencode-config.json",
                (json.dumps(opencode_config, sort_keys=True) + "\n").encode(),
            )
            config_names.append("opencode-config.json")
            agent_prelude.extend(
                [
                    "export HOME=/tmp/agent-home TMPDIR=/tmp/agent-tmp NO_COLOR=1",
                    "export XDG_CONFIG_HOME=/tmp/agent-home/config",
                    "export XDG_DATA_HOME=/tmp/agent-home/data",
                    "export XDG_CACHE_HOME=/tmp/agent-home/cache",
                    "export XDG_STATE_HOME=/tmp/agent-home/state",
                    "export OPENCODE_DISABLE_AUTOUPDATE=1",
                    'export OPENCODE_CONFIG_CONTENT="$(cat /shared/muse-run/opencode-config.json)"',
                    "agent_prompt=$(cat /shared/muse-run/prompt.txt)",
                ]
            )
            agent_command = [
                harness_binary,
                "run",
                "--format",
                "json",
                "--model",
                f"modelapi/{args.model}",
                "--variant",
                "high",
                "--auto",
                "--pure",
                "--dir",
                workdir,
            ]
            prompt_argument = True
        else:
            pi_config = {
                "providers": {
                    "modelapi": {
                        "baseUrl": args.guest_model_api,
                        "api": "openai-responses",
                        "apiKey": "sandoq-local-relay",
                        "models": [
                            {
                                "id": args.model,
                                "name": "Muse Spark 1.3",
                                "reasoning": True,
                                "input": ["text"],
                                "contextWindow": 200000,
                                "maxTokens": 32768,
                                "cost": {
                                    "input": 0,
                                    "output": 0,
                                    "cacheRead": 0,
                                    "cacheWrite": 0,
                                },
                            }
                        ],
                    }
                }
            }
            write_guest_file(
                "/home/runner/shared/muse-run/pi-models.json",
                (json.dumps(pi_config, sort_keys=True) + "\n").encode(),
            )
            config_names.append("pi-models.json")
            agent_prelude.extend(
                [
                    "mkdir -p /tmp/pi-agent",
                    "cp /shared/muse-run/pi-models.json /tmp/pi-agent/models.json",
                    "export HOME=/tmp/agent-home TMPDIR=/tmp/agent-tmp NO_COLOR=1",
                    "export PI_CODING_AGENT_DIR=/tmp/pi-agent PI_TELEMETRY=0",
                    "agent_prompt=$(cat /shared/muse-run/prompt.txt)",
                ]
            )
            agent_command = [
                harness_binary,
                "--provider",
                "modelapi",
                "--model",
                args.model,
                "--api-key",
                "sandoq-local-relay",
                "--mode",
                "json",
                "--print",
                "--no-session",
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-context-files",
                "--approve",
                "--thinking",
                "high",
                "--tools",
                "read,bash,edit,write,grep,find,ls",
            ]
            prompt_argument = True

        agent_shell_command = shlex.join(agent_command)
        if prompt_argument:
            agent_shell_command += ' "$agent_prompt"'
        agent_inner = "\n".join(
            agent_prelude
            + [
                f"setsid {agent_shell_command} > /shared/muse-run/{trace_name} 2> /shared/muse-run/{stderr_name} &",
                "agent_pid=$!",
                "printf '%s\\n' \"$agent_pid\" > /shared/muse-run/agent.pid",
                'wait "$agent_pid"',
                "rc=$?",
                "printf '%s\\n' \"$rc\" > /shared/muse-run/status.tmp",
                "mv -f /shared/muse-run/status.tmp /shared/muse-run/status",
                'exit "$rc"',
            ]
        )
        launch = f"podman exec --detach task bash -lc {shlex.quote(agent_inner)}"
        guest(launch, timeout=30)
        print(f"harness={args.harness} state=started", flush=True)
        deadline = time.monotonic() + args.agent_timeout
        agent_exit: int | None = None
        agent_started = time.monotonic()
        last_report = 0.0
        while time.monotonic() < deadline:
            poll = guest(
                "if test -f /home/runner/shared/muse-run/status; then "
                "echo FINISHED:$(cat /home/runner/shared/muse-run/status); "
                "else echo RUNNING; fi",
                timeout=30,
            )
            output = str(poll.get("stdout", "")).strip()
            if output.startswith("FINISHED:"):
                agent_exit = int(output.removeprefix("FINISHED:"))
                break
            if time.monotonic() - last_report >= 30:
                served, errors = tunnel.stats()
                print(
                    f"harness={args.harness} state=running "
                    f"elapsed={int(time.monotonic() - agent_started)}s "
                    f"tunnel_streams={served} tunnel_errors={len(errors)} "
                    f"proxy_requests={proxy.stats.snapshot()['requests']}",
                    flush=True,
                )
                last_report = time.monotonic()
            time.sleep(5)
        if agent_exit is None:
            guest(
                "pid=$(cat /home/runner/shared/muse-run/agent.pid 2>/dev/null || true); "
                'case "$pid" in \'\'|*[!0-9]*) true ;; *) kill -TERM -- -"$pid" 2>/dev/null || true ;; esac',
                timeout=30,
                check=False,
            )
            raise TimeoutError(f"{args.harness} exceeded {args.agent_timeout}s")
        summary["agent_exit_code"] = agent_exit
        summary["agent_seconds"] = time.monotonic() - agent_started
        print(f"harness={args.harness} state=finished exit={agent_exit}", flush=True)

        capture_and_grade = "\n".join(
            [
                "set +e",
                f"podman exec task bash -lc {shlex.quote(f'cd {workdir} && git status --short')} "
                "> /home/runner/shared/muse-run/repo-status.txt 2>&1",
                f"podman exec task bash -lc {shlex.quote(f'cd {workdir} && git diff --stat')} "
                "> /home/runner/shared/muse-run/agent.stat 2>&1",
                f"podman exec task bash -lc {shlex.quote(f'cd {workdir} && git diff --binary')} "
                "> /home/runner/shared/muse-run/agent.patch 2>&1",
                "podman exec task bash -lc "
                + shlex.quote(
                    "\n".join(
                        [
                            "set +e",
                            f"cd {shlex.quote(workdir)} || exit 80",
                            "git checkout " + shlex.quote(base_commit) + " -- tests/test_web_runner.py || exit 81",
                            "git apply --verbose --3way --recount --ignore-space-change "
                            "--whitespace=nowarn /shared/muse-run/test.patch",
                            "apply_rc=$?",
                            'if [ "$apply_rc" -ne 0 ]; then',
                            "  printf 'SWE_REBENCH_V2_APPLY_EXIT=%s\\n' \"$apply_rc\"",
                            "  exit 82",
                            "fi",
                            "pytest --no-header -rA --tb=line --color=no -p no:cacheprovider "
                            "-W ignore::DeprecationWarning tests/test_web_runner.py",
                            "test_rc=$?",
                            "printf '\\nSWE_REBENCH_V2_TEST_EXIT=%s\\n' \"$test_rc\"",
                            'exit "$test_rc"',
                        ]
                    )
                )
                + " > /home/runner/shared/muse-run/grade.log 2>&1",
                "grade_rc=$?",
                "printf '%s\\n' \"$grade_rc\" > /home/runner/shared/muse-run/grade.status",
                "exit 0",
            ]
        )
        guest(capture_and_grade, timeout=1200)
        grade_result = guest("cat /home/runner/shared/muse-run/grade.status", timeout=30)
        grade_exit = int(str(grade_result.get("stdout", "")).strip())
        summary["grade_exit_code"] = grade_exit
        print(f"grader=finished exit={grade_exit}", flush=True)

        for name in (
            "prompt.txt",
            trace_name,
            stderr_name,
            "repo-status.txt",
            "agent.stat",
            "agent.patch",
            "test.patch",
            "grade.log",
            "grade.status",
            *config_names,
        ):
            download_guest_file(f"/home/runner/shared/muse-run/{name}", args.output_dir / name)

        served, tunnel_errors = tunnel.stats()
        summary["reverse_tunnel"] = {
            "served_streams": served,
            "errors": tunnel_errors,
            "pool_size": 4,
        }
        summary["model_api_proxy"] = proxy.stats.snapshot()
        summary["success"] = agent_exit == 0 and grade_exit == 0
        return 0 if summary["success"] else 1
    except BaseException as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if tunnel is not None:
            tunnel.stop()
            served, tunnel_errors = tunnel.stats()
            summary.setdefault(
                "reverse_tunnel",
                {"served_streams": served, "errors": tunnel_errors, "pool_size": 4},
            )
        proxy.stop()
        summary.setdefault("model_api_proxy", proxy.stats.snapshot())
        if session is not None:
            try:
                guest(
                    f"rm -f {REGISTRY_AUTH_FILE}; podman rm -f task >/dev/null 2>&1 || true",
                    timeout=60,
                    check=False,
                )
            finally:
                deletion = gateway.delete_session(session.session_id, timeout=180, prime=True)
                summary["deleted_session_http_status"] = deletion.verified_http_status
                print(
                    f"deleted={session.session_id} http={deletion.verified_http_status}",
                    flush=True,
                )
        summary["finished_at_unix"] = time.time()
        _write_json(args.output_dir / "summary.json", summary)


if __name__ == "__main__":
    raise SystemExit(main())
