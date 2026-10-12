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


def _recover_worker_summary(
    output: str,
    request: dict[str, Any],
    read_error: BaseException,
) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        try:
            summary = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(summary, dict):
            continue
        if summary.get("task_id") != request["task_id"]:
            continue
        if summary.get("trial") != request.get("trial", 0):
            continue
        if not {"status", "reward"}.issubset(summary):
            continue
        return summary | {
            "schema_version": 1,
            "config_fingerprint": request["config_fingerprint"],
            "result_recovery": {
                "source": "worker_stdout",
                "error": f"{type(read_error).__name__}: {read_error}",
            },
        }
    return None


@dataclass(frozen=True)
class HarnessConfig:
    image: str
    fallback_image: str | None
    tenant_id: str
    lease_ttl: str
    cpu: float
    memory_gb: float
    command_timeout_seconds: int
    max_connection_drops: int


class ToolathlonVMVMHarness:
    def __init__(
        self,
        config: HarnessConfig,
        proxy_port: int,
        worker_path: Path,
        local_tools_path: Path,
        schemas_path: Path,
    ) -> None:
        self.config = config
        self.proxy_port = proxy_port
        self.worker_path = worker_path
        self.local_tools_path = local_tools_path
        self.schemas_path = schemas_path
        self.backend: VacliVMVMBackend | None = None
        self.tunnel: VacliHostTunnel | None = None
        self.tunnel_url: str | None = None
        self.tunnel_stale = False
        self.transport_drops = 0

    def start(self) -> None:
        self.backend = VacliVMVMBackend(
            VacliVMVMConfig(
                image_url=self.config.image,
                fallback_image_url=self.config.fallback_image,
                work_dir="/workspace",
                session_timeout=self.config.command_timeout_seconds,
                tenant_id=self.config.tenant_id,
                lease_ttl=self.config.lease_ttl,
                cpu=self.config.cpu,
                memory_gb=self.config.memory_gb,
                max_session_buffer_size=8 * 1024 * 1024,
            )
        )
        logger.info("Transferring Toolathlon worker into VMVM")
        self._transfer(self.worker_path.read_bytes(), "/opt/toolathlon/worker.py")
        self._transfer(self.local_tools_path.read_bytes(), "/opt/toolathlon/local_tools.py")
        self._transfer(self.schemas_path.read_bytes(), "/opt/toolathlon/tool_schemas.json")
        logger.info("Validating Toolathlon worker inside VMVM")
        result = self._run_exactly_once(
            "uv run --project /workspace --no-sync python -m py_compile /opt/toolathlon/worker.py",
            timeout=120,
        )
        if result["exit_code"] != 0:
            raise VMVMCommandFailed(f"VMVM worker validation failed: {result['output'][-8000:]}")
        logger.info("Opening VMVM model tunnel")
        self._open_tunnel()

    def run_trial(
        self,
        request: dict[str, Any],
        attempt: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.backend is None:
            raise RuntimeError("VMVM harness has not been started")
        task_id = str(request["task_id"])
        trial = int(request.get("trial", 0))
        stem = f"{task_id}-{trial}-attempt-{attempt}"
        remote_request = f"/opt/toolathlon/requests/{stem}.json"
        remote_result = f"/opt/toolathlon/results/{stem}.json"
        while True:
            self._ensure_tunnel()
            assert self.tunnel_url is not None
            trial_request = request | {
                "attempt": attempt,
                "model": request["model"]
                | {
                    "base_url": f"{self.tunnel_url}/model/v1",
                    "api_key": "vmvm-proxy",
                },
                "tool_schemas_path": "/opt/toolathlon/tool_schemas.json",
            }
            self._transfer(json.dumps(trial_request, sort_keys=True).encode(), remote_request)
            if not self.tunnel_stale:
                break
        command = (
            "set -o pipefail; "
            "uv run --project /workspace --no-sync python /opt/toolathlon/worker.py "
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
                    "reward": 0,
                    "config_fingerprint": trial_request["config_fingerprint"],
                    "error": {
                        "type": "VMVMCommandTimeout",
                        "message": result["output"][-4000:],
                    },
                },
                self._command_metadata(result),
            )
        if result["exit_code"] < 0:
            raise VMVMCommandLost(
                "VMVM command could not be recovered: "
                f"error_type={result['error_type']} output={result['output'][-4000:]}"
            )
        if result["exit_code"] == 137:
            raise VMVMCommandLost(
                f"VMVM worker was killed before persisting a result: output={result['output'][-4000:]}"
            )
        try:
            raw_payload = self._read(remote_result)
            payload = json.loads(raw_payload)
        except Exception as error:
            payload = _recover_worker_summary(result["output"], trial_request, error)
            if payload is None:
                raise VMVMCommandFailed(
                    f"Worker exited {result['exit_code']} without a recoverable result: {result['output'][-4000:]}"
                ) from error
        if result["exit_code"] not in {0, 70, 75}:
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

    def run_command(self, command: str, *, timeout: float) -> dict[str, Any]:
        """Run one command without replaying it after a recoverable tunnel drop."""

        return self._run_exactly_once(command, timeout)

    def transfer(self, content: bytes, destination: str) -> None:
        self._transfer(content, destination)

    def read_file(self, remote_path: str) -> bytes:
        return self._read(remote_path)

    def ensure_model_tunnel(self) -> str:
        self._ensure_tunnel()
        assert self.tunnel_url is not None
        return self.tunnel_url

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
        last_error: BaseException | None = None
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
        last_error: BaseException | None = None
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
        image=str(runtime["image"]),
        fallback_image=runtime.get("fallback_image"),
        tenant_id=str(runtime["tenant_id"]),
        lease_ttl=str(runtime["lease_ttl"]),
        cpu=float(runtime["cpu"]),
        memory_gb=float(runtime["memory_gb"]),
        command_timeout_seconds=int(runtime["command_timeout_seconds"]),
        max_connection_drops=int(runtime["max_connection_drops"]),
    )
