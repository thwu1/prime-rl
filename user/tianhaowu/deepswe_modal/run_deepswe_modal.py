import argparse
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import modal
from pier_runner import run_pier_job

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
CADDY = Path("/home/tianhaowu/bin/caddy")
CADDYFILE = PROJECT_DIR / "user/tianhaowu/deepswe_modal/Caddyfile"
THINKING_VERIFIER = PROJECT_DIR / "user/tianhaowu/deepswe_modal/verify_mini_swe_thinking.py"
DRIVER_ROOT = Path("/checkpoint/ram/tianhaowu/deepswe_eval/driver")
RELAY_REMOTE_PORT = 18000
DEFAULT_MODEL_NAME = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--inference-job-id", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--mini-swe-version", default="2.2.8")
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


def request_json(url: str, api_key: str | None = None) -> dict:
    headers = {}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
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


def relay_image() -> modal.Image:
    return modal.Image.debian_slim().apt_install("openssh-server").run_commands(
        "mkdir -p /run/sshd /root/.ssh /etc/ssh/sshd_config.d",
        "chmod 700 /root/.ssh",
        "printf 'PermitRootLogin prohibit-password\\nPasswordAuthentication no\\nAllowTcpForwarding yes\\nGatewayPorts clientspecified\\n' > /etc/ssh/sshd_config.d/deepswe-relay.conf",
    )


def create_relay_sandbox(public_key: str, name: str) -> modal.Sandbox:
    app = modal.App.lookup("__deepswe_relay__", create_if_missing=True)
    return modal.Sandbox.create(
        "bash",
        "-lc",
        "printf '%s\\n' \"$RELAY_AUTHORIZED_KEY\" > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys && ssh-keygen -A && exec /usr/sbin/sshd -D -e",
        app=app,
        image=relay_image(),
        name=name,
        timeout=24 * 60 * 60,
        encrypted_ports=[22, RELAY_REMOTE_PORT],
        secrets=[modal.Secret.from_dict({"RELAY_AUTHORIZED_KEY": public_key})],
        readiness_probe=modal.sandbox.Probe.with_tcp(22),
    )


def start_reverse_ssh(
    private_key: Path,
    relay_host: str,
    relay_port: int,
    local_port: int,
    log_path: Path,
) -> tuple[subprocess.Popen, object]:
    proxy_command = (
        f"openssl s_client -quiet -connect {relay_host}:{relay_port} "
        f"-servername {relay_host}"
    )
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [
            "ssh",
            "-F",
            "/dev/null",
            "-N",
            "-T",
            "-i",
            str(private_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            f"ProxyCommand={proxy_command}",
            "-R",
            f"0.0.0.0:{RELAY_REMOTE_PORT}:127.0.0.1:{local_port}",
            "root@deepswe-relay",
        ],
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


def run_pier(config: Path, job_name: str, base_url: str, api_key: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "MODAL_DISABLE_API_PROXY": "1",
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": f"{base_url}/v1",
        }
    )
    run_pier_job(config, job_name, env=env)


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
    private_key = driver_dir / "relay_ed25519"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
    )
    public_key = private_key.with_suffix(".pub").read_text().strip()

    caddy_process = None
    caddy_log = None
    ssh_process = None
    ssh_log = None
    relay = None
    try:
        caddy_process, caddy_log = start_caddy(
            router,
            local_port,
            api_key,
            driver_dir / "caddy.log",
        )
        wait_for_endpoint(
            f"http://127.0.0.1:{local_port}/v1/models",
            api_key=api_key,
            timeout_sec=60,
        )

        relay = create_relay_sandbox(
            public_key,
            f"deepswe-relay-{slurm_job_id}",
        )
        tunnels = relay.tunnels(timeout=10 * 60)
        relay_host, relay_port = tunnels[22].tls_socket
        public_url = tunnels[RELAY_REMOTE_PORT].url
        ssh_process, ssh_log = start_reverse_ssh(
            private_key,
            relay_host,
            relay_port,
            local_port,
            driver_dir / "ssh.log",
        )
        wait_for_endpoint(
            f"{public_url}/v1/models",
            api_key=api_key,
            timeout_sec=5 * 60,
        )
        print(f"Authenticated Modal relay ready at {public_url}", flush=True)
        verify_mini_swe_thinking(
            public_url,
            api_key,
            args.model_name,
            args.mini_swe_version,
            driver_dir / "thinking_preflight.json",
        )
        run_pier(args.config.resolve(), args.job_name, public_url, api_key)
    finally:
        stop_process(ssh_process)
        if ssh_log is not None:
            ssh_log.close()
        if relay is not None:
            relay.terminate()
        stop_process(caddy_process)
        if caddy_log is not None:
            caddy_log.close()


if __name__ == "__main__":
    main()
