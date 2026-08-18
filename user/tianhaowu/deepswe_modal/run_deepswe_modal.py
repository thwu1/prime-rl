import argparse
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from pier_runner import run_pier_job
from provider_env import provider_environment_context
from request_capture import (
    audit_captured_requests,
    start_capture_proxy,
    stop_capture_proxy,
)

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
CADDY = Path("/home/tianhaowu/bin/caddy")
CADDYFILE = PROJECT_DIR / "user/tianhaowu/deepswe_modal/Caddyfile"
THINKING_VERIFIER = PROJECT_DIR / "user/tianhaowu/deepswe_modal/verify_mini_swe_thinking.py"
DRIVER_ROOT = Path("/checkpoint/ram/tianhaowu/deepswe_eval/driver")
DEFAULT_MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
GATEWAY_INTERNAL_URL = "http://fair-sc-3-ingress-slurm-ingress"
GATEWAY_PUBLIC_URL = "https://ram-inference-gateway.ingress.fair-sc-3.metahpc.aws.metafb.cloud"
GATEWAY_HOST_HEADER = "ram-inference-gateway.ingress."
GATEWAY_REGISTER_TOKEN = os.environ.get(
    "GATEWAY_REGISTER_TOKEN",
    "ram_secret_dont_share",
)
GATEWAY_REGISTER_TTL_SEC = 45
GATEWAY_HEARTBEAT_SEC = 15
GATEWAY_REGISTER_SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--inference-job-id", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--gateway-model-name", required=True)
    parser.add_argument("--mini-swe-version", default="2.2.8")
    parser.add_argument("--provider", choices=("modal", "vmvm", "sandoq"), required=True)
    parser.add_argument("--sandbox-startup-timeout-sec", type=int, default=3600)
    return parser.parse_args()


def run_output(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def inference_router(job_id: str) -> str:
    node_list = run_output(["squeue", "-j", job_id, "-h", "-o", "%N"])
    if not node_list:
        raise RuntimeError(f"Inference job {job_id} is not running")
    node = run_output(["scontrol", "show", "hostnames", node_list]).splitlines()[0]
    return f"http://{node}:8000"


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request_json(
    url: str,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    request_headers = dict(headers or {})
    if api_key is not None:
        request_headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=request_headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def wait_for_endpoint(
    url: str,
    *,
    api_key: str | None = None,
    timeout_sec: int,
) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            return request_json(url, api_key)
        except OSError:
            time.sleep(10)
    raise TimeoutError(f"Endpoint did not become ready: {url}")


class GatewayRegistration:
    def __init__(
        self,
        *,
        deployment: str,
        model: str,
        upstream_url: str,
        api_key: str,
        job_id: str,
        provider: str,
    ) -> None:
        self.deployment = deployment
        self.model = model
        self.upstream_url = upstream_url
        self.api_key = api_key
        self.job_id = job_id
        self.provider = provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{GATEWAY_INTERNAL_URL}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {GATEWAY_REGISTER_TOKEN}",
                "Content-Type": "application/json",
                "Host": GATEWAY_HOST_HEADER,
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=20) as response:
            return json.load(response)

    def register(self) -> None:
        response = self._post(
            "/register",
            {
                "schema_version": GATEWAY_REGISTER_SCHEMA_VERSION,
                "deployment": self.deployment,
                "model": self.model,
                "url": self.upstream_url,
                "api_key": self.api_key,
                "extras": {
                    "proxy_type": "deepswe-capture",
                    "provider": self.provider,
                },
                "jobid": self.job_id,
                "ttl": GATEWAY_REGISTER_TTL_SEC,
            },
        )
        if response.get("ok") is not True:
            raise RuntimeError(f"RAM inference gateway rejected registration: {response}")

    def _heartbeat(self) -> None:
        while not self._stop.wait(GATEWAY_HEARTBEAT_SEC):
            try:
                self.register()
            except Exception as error:
                print(f"RAM inference gateway heartbeat failed: {error}", flush=True)

    def start(self) -> None:
        self.register()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=GATEWAY_HEARTBEAT_SEC + 5)
        try:
            self._post(
                "/deregister",
                {
                    "schema_version": GATEWAY_REGISTER_SCHEMA_VERSION,
                    "deployment": self.deployment,
                },
            )
        except Exception as error:
            print(f"RAM inference gateway deregistration failed: {error}", flush=True)


def start_caddy(
    router: str,
    local_port: int,
    api_key: str,
    log_path: Path,
) -> tuple[subprocess.Popen, object]:
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env.update(
        {
            "NEMOTRON_ROUTER": router,
            "OPENAI_API_KEY": api_key,
            "RELAY_LOCAL_PORT": str(local_port),
        }
    )
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [str(CADDY), "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        cwd=PROJECT_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_file


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_pier(
    config: Path,
    job_name: str,
    base_url: str,
    api_key: str,
    provider: str,
    sandbox_startup_timeout_sec: int,
) -> Path:
    config_data = json.loads(config.read_text())
    n_concurrent = config_data.get("n_concurrent_trials")
    if not isinstance(n_concurrent, int) or isinstance(n_concurrent, bool) or n_concurrent <= 0:
        raise ValueError("Pier config n_concurrent_trials must be a positive integer")
    with provider_environment_context(
        provider,
        n_concurrent=n_concurrent,
        startup_timeout_sec=sandbox_startup_timeout_sec,
    ) as env:
        env.update(
            {
                "OPENAI_API_KEY": api_key,
                "OPENAI_BASE_URL": f"{base_url}/v1",
            }
        )
        return run_pier_job(config, job_name, env=env)


def verify_mini_swe_thinking(
    base_url: str,
    api_key: str,
    model_name: str,
    mini_swe_version: str,
    log_path: Path,
) -> None:
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env.update(
        {
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "NO_PROXY": "127.0.0.1,localhost",
            "OPENAI_API_KEY": api_key,
        }
    )
    command = [
        "uv",
        "run",
        "--offline",
        "--no-sync",
        "--with",
        f"mini-swe-agent=={mini_swe_version}",
        "python",
        str(THINKING_VERIFIER),
        "--base-url",
        base_url,
        "--model-name",
        model_name,
        "--log-path",
        str(log_path),
    ]
    subprocess.run(command, cwd=PROJECT_DIR, env=env, check=True)


def main() -> None:
    args = parse_args()
    slurm_job_id = os.environ.get("SLURM_JOB_ID", str(os.getpid()))
    driver_dir = DRIVER_ROOT / slurm_job_id
    driver_dir.mkdir(parents=True, exist_ok=True)

    router = inference_router(args.inference_job_id)
    print(f"Waiting for inference router {router}", flush=True)
    model_response = wait_for_endpoint(
        f"{router}/v1/models",
        timeout_sec=2 * 60 * 60,
    )
    served_models = [item["id"] for item in model_response.get("data", [])]
    if args.model_name not in served_models:
        raise RuntimeError(f"Expected {args.model_name}, got {served_models}")

    api_key = secrets.token_urlsafe(32)
    local_port = available_port()

    caddy_process = None
    caddy_log = None
    gateway_registration = None
    capture_server = None
    capture_thread = None
    capture_dir = driver_dir / "latest_requests"
    try:
        capture_server, capture_thread, capture_url = start_capture_proxy(
            router,
            capture_dir,
            driver_dir / "request_capture.jsonl",
            upstream_model=args.model_name,
        )
        caddy_process, caddy_log = start_caddy(
            capture_url,
            local_port,
            api_key,
            driver_dir / "caddy.log",
        )
        wait_for_endpoint(
            f"http://127.0.0.1:{local_port}/v1/models",
            api_key=api_key,
            timeout_sec=60,
        )

        gateway_registration = GatewayRegistration(
            deployment=f"deepswe-{slurm_job_id}",
            model=args.gateway_model_name,
            upstream_url=f"http://{socket.gethostname()}:{local_port}",
            api_key=api_key,
            job_id=slurm_job_id,
            provider=args.provider,
        )
        gateway_registration.start()
        gateway_models = request_json(
            f"{GATEWAY_INTERNAL_URL}/v1/models",
            headers={"Host": GATEWAY_HOST_HEADER},
        )
        registered_models = {item["id"] for item in gateway_models.get("data", [])}
        if args.gateway_model_name not in registered_models:
            raise RuntimeError(f"RAM inference gateway did not list {args.gateway_model_name}: {registered_models}")
        print(
            f"RAM inference gateway route ready for {args.gateway_model_name} via {socket.gethostname()}:{local_port}",
            flush=True,
        )
        local_url = f"http://127.0.0.1:{local_port}"
        verify_mini_swe_thinking(
            local_url,
            api_key,
            args.model_name,
            args.mini_swe_version,
            driver_dir / "thinking_preflight.json",
        )
        run_pier(
            args.config.resolve(),
            args.job_name,
            GATEWAY_PUBLIC_URL,
            api_key,
            args.provider,
            args.sandbox_startup_timeout_sec,
        )
        audit_captured_requests(
            router,
            capture_dir,
            driver_dir / "request_capture.jsonl",
            driver_dir / "thinking_trajectory_audit.json",
        )
    finally:
        if gateway_registration is not None:
            gateway_registration.stop()
        stop_process(caddy_process)
        if caddy_log is not None:
            caddy_log.close()
        if capture_server is not None and capture_thread is not None:
            stop_capture_proxy(capture_server, capture_thread)


if __name__ == "__main__":
    main()
