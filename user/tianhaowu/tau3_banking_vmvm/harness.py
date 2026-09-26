from __future__ import annotations

import json
import logging
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
VMVM_PACKAGE = REPO_ROOT / "environments" / "vmvm_tb_v2"
if str(VMVM_PACKAGE) not in sys.path:
    sys.path.insert(0, str(VMVM_PACKAGE))

from vmvm_tb_v2._vacli.backend import VacliHostTunnel, VacliVMVMBackend, VacliVMVMConfig

logger = logging.getLogger(__name__)


class VMVMCommandLost(RuntimeError):
    pass


class VMVMCommandFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class HarnessConfig:
    image: str
    fallback_image: str | None
    tenant_id: str
    lease_ttl: str
    cpu: float
    memory_gb: float
    setup_timeout_seconds: int
    command_timeout_seconds: int
    max_connection_drops: int
    uv_version: str


class Tau3VMVMHarness:
    def __init__(
        self,
        config: HarnessConfig,
        proxy_port: int,
        source_archive: Path,
        worker_path: Path,
        project_path: Path,
    ) -> None:
        self.config = config
        self.proxy_port = proxy_port
        self.source_archive = source_archive
        self.worker_path = worker_path
        self.project_path = project_path
        self.backend: VacliVMVMBackend | None = None
        self.tunnel: VacliHostTunnel | None = None
        self.tunnel_url: str | None = None
        self.tunnel_stale = False
        self.transport_drops = 0

    def start(self) -> None:
        backend_config = VacliVMVMConfig(
            image_url=self.config.image,
            fallback_image_url=self.config.fallback_image,
            work_dir="/opt/tau3",
            session_timeout=self.config.command_timeout_seconds,
            tenant_id=self.config.tenant_id,
            lease_ttl=self.config.lease_ttl,
            cpu=self.config.cpu,
            memory_gb=self.config.memory_gb,
            max_session_buffer_size=2 * 1024 * 1024,
        )
        self.backend = VacliVMVMBackend(backend_config)
        self._open_tunnel()
        self._transfer(self.source_archive.read_bytes(), "/tmp/tau2-banking.tar.gz")
        self._transfer(self.worker_path.read_bytes(), "/opt/tau3/worker.py")
        self._transfer(self.project_path.read_bytes(), "/opt/tau3/pyproject.toml")
        setup = f"""
set -euo pipefail
rm -rf /opt/tau2 /opt/tau3/.venv
mkdir -p /opt/tau2 /opt/tau3
tar -xzf /tmp/tau2-banking.tar.gz -C /opt/tau2
if ! command -v uv >/dev/null 2>&1; then
  python -m pip install --disable-pip-version-check --no-cache-dir uv=={shlex.quote(self.config.uv_version)}
fi
uv venv --python python3 /opt/tau3/.venv
uv pip install --python /opt/tau3/.venv/bin/python --link-mode copy '/opt/tau2[knowledge]'
TAU2_DATA_DIR=/opt/tau2/data uv run --project /opt/tau3 --no-sync python -c 'from tau2.runner.helpers import get_tasks; tasks=get_tasks("banking_knowledge", task_split_name=None); assert len(tasks) == 97, len(tasks)'
""".strip()
        result = self._run_exactly_once(setup, timeout=self.config.setup_timeout_seconds)
        if result["exit_code"] != 0:
            raise VMVMCommandFailed(f"VMVM setup failed: {result['output'][-8000:]}")

    def run_trial(self, request: dict[str, Any], attempt: int) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        task_id = str(request["task_id"])
        trial = int(request["trial"])
        stem = f"{task_id}-{trial}-attempt-{attempt}"
        remote_request = f"/opt/tau3/requests/{stem}.json"
        remote_result = f"/opt/tau3/results/{stem}.json"
        while True:
            self._ensure_tunnel()
            assert self.tunnel_url is not None
            trial_request = request | {
                "attempt": attempt,
                "policy_base_url": f"{self.tunnel_url}/policy/v1",
                "user_base_url": f"{self.tunnel_url}/user/v1",
                "judge_base_url": f"{self.tunnel_url}/judge/v1",
                "tau2_data_dir": "/opt/tau2/data",
            }
            self._transfer(json.dumps(trial_request, sort_keys=True).encode(), remote_request)
            if not self.tunnel_stale:
                break
        command = (
            "set -o pipefail; "
            "TAU2_DATA_DIR=/opt/tau2/data "
            "uv run --project /opt/tau3 --no-sync python /opt/tau3/worker.py "
            f"--request {shlex.quote(remote_request)} --result {shlex.quote(remote_result)}"
        )
        result = self._run_exactly_once(command, timeout=self.config.command_timeout_seconds)
        if result["error_type"] == "timeout":
            return (
                {
                    "schema_version": 1,
                    "status": "model_timeout",
                    "task_id": task_id,
                    "trial": trial,
                    "seed": trial_request["seed"],
                    "reward": 0.0,
                    "source_commit": trial_request["source_commit"],
                    "config_fingerprint": trial_request["config_fingerprint"],
                    "error": {"type": "VMVMCommandTimeout", "message": result["output"][-4000:]},
                },
                self._command_metadata(result),
            )
        if result["exit_code"] < 0:
            raise VMVMCommandLost(
                f"VMVM command could not be recovered: error_type={result['error_type']} output={result['output'][-4000:]}"
            )
        try:
            payload = json.loads(self._read(remote_result))
        except Exception as error:
            raise VMVMCommandFailed(
                f"Worker exited {result['exit_code']} without a readable result: {result['output'][-4000:]}"
            ) from error
        if result["exit_code"] not in {0, 70}:
            raise VMVMCommandFailed(f"Unexpected worker exit code {result['exit_code']}: {result['output'][-4000:]}")
        return payload, self._command_metadata(result)

    def debugging_info(self) -> dict[str, Any]:
        if self.backend is None:
            return {"started": False}
        return self.backend.get_debugging_info() | {
            "transport_drops": self.transport_drops,
            "tunnel_url": self.tunnel_url,
            "tunnel_stale": self.tunnel_stale,
        }

    def close(self) -> None:
        if self.backend is not None:
            self.backend.destroy()
        self.backend = None
        self.tunnel = None
        self.tunnel_url = None

    def _command_metadata(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "exit_code": result["exit_code"],
            "error_type": result["error_type"],
            "output_tail": result["output"][-4000:],
            "transport_drops": self.transport_drops,
        }

    def _run_exactly_once(self, command: str, timeout: float) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        result = self.backend.run_bash(command, timeout=timeout)
        drops = 0
        while result["exit_code"] < 0 and result["error_type"] == "broken_pipe":
            drops += 1
            self.transport_drops += 1
            self.tunnel_stale = True
            if drops > self.config.max_connection_drops or not self.backend.restart_session():
                return result
            recovered = self.backend.recover_last()
            if recovered is None:
                return result
            result = recovered
        return result

    def _transfer(self, content: bytes, destination: str) -> None:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        last_error: Exception | None = None
        for _ in range(self.config.max_connection_drops + 1):
            try:
                self.backend.transfer_file(content, destination)
                return
            except Exception as error:
                last_error = error
                self.transport_drops += 1
                self.tunnel_stale = True
                if not self.backend.restart_session():
                    break
        raise VMVMCommandLost(f"Could not transfer {destination}: {last_error}")

    def _read(self, remote_path: str) -> bytes:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        last_error: Exception | None = None
        for _ in range(self.config.max_connection_drops + 1):
            try:
                return self.backend.read_file(remote_path)
            except Exception as error:
                last_error = error
                self.transport_drops += 1
                self.tunnel_stale = True
                if not self.backend.restart_session():
                    break
        raise VMVMCommandLost(f"Could not read {remote_path}: {last_error}")

    def _ensure_tunnel(self) -> None:
        if self.tunnel_url is None or self.tunnel_stale:
            self._open_tunnel()

    def _open_tunnel(self) -> None:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        if self.tunnel is not None:
            try:
                self.backend.close_host_tunnel(self.tunnel)
            except Exception:
                logger.warning("Could not close stale VMVM host tunnel", exc_info=True)
        self.tunnel, self.tunnel_url = self.backend.open_host_tunnel(self.proxy_port)
        self.tunnel_stale = False


def make_harness_config(runtime: dict[str, Any]) -> HarnessConfig:
    return HarnessConfig(
        image=runtime["image"],
        fallback_image=runtime.get("fallback_image"),
        tenant_id=runtime["tenant_id"],
        lease_ttl=runtime["lease_ttl"],
        cpu=float(runtime["cpu"]),
        memory_gb=float(runtime["memory_gb"]),
        setup_timeout_seconds=int(runtime["setup_timeout_seconds"]),
        command_timeout_seconds=int(runtime["command_timeout_seconds"]),
        max_connection_drops=int(runtime["max_connection_drops"]),
        uv_version=runtime["uv_version"],
    )
