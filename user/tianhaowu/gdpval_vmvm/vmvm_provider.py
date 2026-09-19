from __future__ import annotations

import json
import logging
import math
import shlex
import subprocess
import sys
import threading
import types
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any

import anyio
from asset_fetch import AssetManifestError, public_asset_record, verify_staged_assets
from stirrup.core.models import ImageContentBlock, Tool, ToolUseCountMetadata
from stirrup.tools.code_backends.base import (
    SHELL_TIMEOUT,
    CodeExecToolProvider,
    CodeExecutionParams,
    CommandResult,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VMVM_PACKAGE = REPO_ROOT / "environments" / "vmvm_tb_v2" / "vmvm_tb_v2"
# Import the standalone backend without executing vmvm_tb_v2.__init__, whose
# environment registration depends on the full prime-rl evaluator stack.
if "vmvm_tb_v2" not in sys.modules:
    package = types.ModuleType("vmvm_tb_v2")
    package.__path__ = [str(VMVM_PACKAGE)]  # type: ignore[attr-defined]
    sys.modules["vmvm_tb_v2"] = package

from vmvm_tb_v2._vacli import backend as vacli_backend
from vmvm_tb_v2._vacli.backend import VacliVMVMBackend, VacliVMVMConfig

logger = logging.getLogger(__name__)
_LEASE_CLASS_LOCK = threading.Lock()


class _PreloadedImageLease(vacli_backend.VacliLease):
    def start(self) -> None:
        vacli_backend._lease_concurrency.acquire()
        self._concurrency_held = True
        command = [
            "stdbuf",
            "-oL",
            vacli_backend.VACLI_BIN,
            "--x2p",
            "--tiername",
            "vmaas.repo_rlef",
            "--faas-tenant-id",
            self.tenant_id,
            "lease",
            "--ttl",
            self.lease_ttl,
            "--auto-renew",
            "--tunnel-ports",
            "22",
            "--release-on-exit",
        ]
        if self._image_url:
            command.extend(["--tier-overrides", f"img:{self._image_url}"])
        logger.info("vacli: leasing GDPval VM with preloaded image %s", self._image_url)
        try:
            with self.log_path.open("wb") as log:
                popen_kwargs: dict[str, Any] = {
                    "stdout": log,
                    "stderr": self._sp.STDOUT,
                    "process_group": 0,
                }
                if self._sp is subprocess:
                    popen_kwargs["preexec_fn"] = vacli_backend._child_pdeathsig
                self.proc = self._sp.Popen(command, **popen_kwargs)
        except Exception:
            self._release_concurrency_slot()
            raise


class _PreloadedImageBackend(VacliVMVMBackend):
    def __init__(self, config: VacliVMVMConfig) -> None:
        image_url = config.image_url

        class BoundLease(_PreloadedImageLease):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, image_url=image_url, **kwargs)

        with _LEASE_CLASS_LOCK:
            original = vacli_backend.VacliLease
            vacli_backend.VacliLease = BoundLease
            try:
                super().__init__(config)
            finally:
                vacli_backend.VacliLease = original

    def _start_container(self) -> str:
        self._ensure_host_memory()
        image = self.config.image_url
        exists = self._ssh_call_raw(f"podman image exists {shlex.quote(image)}", timeout=30)
        if exists.returncode != 0:
            image = vacli_backend._resolve_image_in_vm(
                self._sp,
                self._ssh_port,
                self._control_path,
                self.config.image_url,
                self.config.fallback_image_url,
            )
        run_argv = ["podman", "run", "-d", "--pull=never", "--network", "bridge"]
        if self.config.cpu is not None:
            run_argv.extend(["--cpus", str(self.config.cpu)])
            run_argv.extend(["--env", f"GOMAXPROCS={math.ceil(self.config.cpu)}"])
        if self.config.memory_gb is not None:
            run_argv.extend(["--memory", f"{self.config.memory_gb}g"])
        run_argv.extend(["--entrypoint", "/bin/bash", image, "-c", "tail -f /dev/null"])
        run = self._ssh_call_raw(shlex.join(run_argv), timeout=int(self.config.session_timeout))
        if run.returncode != 0:
            raise vacli_backend.BackendInitError(f"podman run failed: rc={run.returncode} stderr={run.stderr!r}")
        container_id = run.stdout.decode("utf-8", errors="replace").strip()
        if not container_id:
            raise vacli_backend.BackendInitError(f"podman run returned empty container id; stderr={run.stderr!r}")
        container_id = vacli_backend._validate_container_id(container_id)
        vacli_backend._ensure_python_in_container(
            self._sp,
            self._ssh_port,
            self._control_path,
            container_id,
        )
        self._proxy_gateway = vacli_backend._setup_bridge_proxy(
            self._sp,
            self._ssh_port,
            self._control_path,
            container_id,
        )
        return container_id


class VMVMInfrastructureLost(RuntimeError):
    """The sandbox or its exact-once command state was irrecoverably lost."""


class VMVMFatalError(RuntimeError):
    """The VMVM configuration or sandbox image is deterministically invalid."""


def _looks_fatal_startup(error: BaseException) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "manifest unknown",
            "name unknown",
            "unauthorized",
            "authentication required",
            "invalid image",
            "unsupported image",
        )
    )


class VMVMCodeExecToolProvider(CodeExecToolProvider):
    """Stirrup code-execution provider backed by one VMVM container."""

    def __init__(
        self,
        *,
        image: str,
        fallback_image: str | None = None,
        tenant_id: str,
        lease_ttl: str,
        cpu: float,
        memory_gb: float,
        command_timeout_seconds: int,
        max_connection_drops: int = 5,
        allowed_commands: list[str] | None = None,
        bootstrap_assets: list[dict[str, Any]] | None = None,
        asset_cache_dir: str | Path,
        preload_image: bool = True,
    ) -> None:
        super().__init__(
            allowed_commands=allowed_commands,
            shell_timeout=command_timeout_seconds,
        )
        self._config = VacliVMVMConfig(
            image_url=image,
            fallback_image_url=fallback_image or None,
            work_dir="/workspace",
            session_timeout=command_timeout_seconds,
            tenant_id=tenant_id,
            lease_ttl=lease_ttl,
            cpu=cpu,
            memory_gb=memory_gb,
            max_session_buffer_size=32 * 1024 * 1024,
        )
        self._max_connection_drops = max_connection_drops
        self._backend: VacliVMVMBackend | None = None
        self._transport_drops = 0
        self._bootstrap_assets = list(bootstrap_assets or [])
        self._asset_cache_dir = Path(asset_cache_dir).expanduser().resolve()
        self._preload_image = preload_image
        self.staged_assets: list[dict[str, Any]] = []
        self.render_history: list[dict[str, Any]] = []

    @property
    def temp_dir(self) -> None:
        return None

    @property
    def debugging_info(self) -> dict[str, Any]:
        backend = self._backend
        return {
            "transport_drops": self._transport_drops,
            "backend": backend.get_debugging_info() if backend is not None else None,
        }

    async def __aenter__(self) -> Tool[CodeExecutionParams, ToolUseCountMetadata]:
        try:
            backend_class = _PreloadedImageBackend if self._preload_image else VacliVMVMBackend
            self._backend = await anyio.to_thread.run_sync(lambda: backend_class(self._config))
        except Exception as error:
            if _looks_fatal_startup(error):
                raise VMVMFatalError(f"VMVM startup failed: {error}") from error
            raise VMVMInfrastructureLost(f"VMVM startup failed: {error}") from error
        try:
            probe = await self._run_exactly_once(
                "set -o pipefail\ncd /workspace\n"
                "command -v bash >/dev/null && command -v python >/dev/null && "
                "command -v libreoffice >/dev/null",
                timeout=120,
                safe_replay=True,
            )
            if probe.exit_code != 0:
                raise VMVMFatalError("GDPval image is missing bash, python, or LibreOffice: " + probe.stdout[-4000:])
            if self._bootstrap_assets:
                self.staged_assets = await self.stage_assets(self._bootstrap_assets)
        except Exception:
            await self._destroy()
            raise
        return self.get_code_exec_tool(name="run_shell")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._destroy()

    async def _destroy(self) -> None:
        backend, self._backend = self._backend, None
        if backend is not None:
            await anyio.to_thread.run_sync(backend.destroy)

    def _require_backend(self) -> VacliVMVMBackend:
        if self._backend is None:
            raise RuntimeError("VMVM sandbox is not running")
        return self._backend

    @staticmethod
    def _resolve_path(path: str) -> str:
        pure = PurePosixPath(path)
        if pure.is_absolute():
            parts = pure.parts
            if len(parts) < 2 or parts[1] not in {"workspace", "working_dir"}:
                raise ValueError(f"Path must be under /workspace: {path!r}")
            relative = PurePosixPath(*parts[2:])
        else:
            relative = pure
        if ".." in relative.parts:
            raise ValueError(f"Path escapes /workspace: {path!r}")
        return str(PurePosixPath("/workspace") / relative)

    def _recover_sync(self, *, safe_replay: bool, command: str, timeout: int) -> dict[str, Any]:
        backend = self._require_backend()
        for _ in range(self._max_connection_drops):
            self._transport_drops += 1
            if not backend.restart_session():
                raise VMVMInfrastructureLost("VMVM session and container could not be recovered")
            recovered = backend.recover_last()
            if recovered is None:
                if safe_replay:
                    result = backend.run_bash(command, timeout=timeout)
                else:
                    raise VMVMInfrastructureLost(
                        "VMVM persistent shell was reset before the in-flight command reached a durable result"
                    )
            else:
                result = recovered
            if not (result["exit_code"] < 0 and result["error_type"] == "broken_pipe"):
                return result
        raise VMVMInfrastructureLost(
            f"VMVM connection dropped more than {self._max_connection_drops} times during one command"
        )

    def _run_exactly_once_sync(self, command: str, timeout: int, *, safe_replay: bool) -> dict[str, Any]:
        result = self._require_backend().run_bash(command, timeout=timeout)
        if result["exit_code"] < 0 and result["error_type"] == "broken_pipe":
            result = self._recover_sync(safe_replay=safe_replay, command=command, timeout=timeout)
        return result

    async def _run_exactly_once(
        self,
        command: str,
        timeout: int,
        *,
        safe_replay: bool = False,
    ) -> CommandResult:
        result = await anyio.to_thread.run_sync(
            lambda: self._run_exactly_once_sync(command, timeout, safe_replay=safe_replay)
        )
        error_type = str(result["error_type"])
        exit_code = int(result["exit_code"])
        output = str(result["output"])
        if exit_code < 0 and error_type not in {"none", "exit"}:
            if error_type == "timeout":
                return CommandResult(
                    exit_code=124,
                    stdout="",
                    stderr=output,
                    error_kind="timeout",
                    advice="The command exceeded its sandbox timeout. Split the work into shorter commands.",
                )
            if error_type == "too_long":
                return CommandResult(
                    exit_code=1,
                    stdout="",
                    stderr=output,
                    error_kind="output_too_large",
                    advice="The command produced too much output. Redirect it to a file or request a smaller slice.",
                )
            raise VMVMInfrastructureLost(
                f"VMVM command ended without a terminal exit code: error_type={error_type}: {output[-4000:]}"
            )
        return CommandResult(exit_code=exit_code, stdout=output, stderr="")

    async def run_command(self, cmd: str, *, timeout: int | None = None) -> CommandResult:
        if not self._check_allowed(cmd):
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Command not allowed: {cmd!r}",
                error_kind="invalid_argument",
            )
        command_timeout = int(timeout if timeout is not None else self._shell_timeout or SHELL_TIMEOUT)
        wrapped = "set -o pipefail\ncd /workspace\n(\n" + cmd + "\n)"
        return await self._run_exactly_once(wrapped, command_timeout)

    @staticmethod
    def _json_result(output: str, operation: str) -> dict[str, Any]:
        for line in reversed(output.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise VMVMFatalError(f"{operation} returned no JSON result: {output[-4000:]}")

    async def stage_assets(
        self,
        assets: list[dict[str, Any]],
        *,
        destination: str = "/workspace",
    ) -> list[dict[str, Any]]:
        if not assets:
            return []
        destination_path = self._resolve_path(destination)
        manifest_path = "/workspace/.gdpval-assets.json"
        script_path = "/workspace/.gdpval-asset-verify.py"
        try:
            expected = verify_staged_assets(assets, self._asset_cache_dir)
        except (AssetManifestError, OSError) as error:
            raise VMVMFatalError(f"GDPval host asset cache validation failed: {error}") from error
        for item in assets:
            relative = PurePosixPath(str(item["path"]))
            local_path = (self._asset_cache_dir / Path(*relative.parts)).resolve()
            if not local_path.is_relative_to(self._asset_cache_dir):
                raise VMVMFatalError(f"GDPval cached asset escapes its root: {item['path']}")
            remote_path = str(PurePosixPath(destination_path) / relative)
            await self.write_file_bytes(remote_path, local_path.read_bytes())
        await self.write_file_bytes(manifest_path, json.dumps(expected, sort_keys=True).encode())
        await self.write_file_bytes(script_path, Path(__file__).with_name("asset_fetch.py").read_bytes())
        command = (
            f"python {shlex.quote(script_path)} verify {shlex.quote(manifest_path)} {shlex.quote(destination_path)}"
        )
        try:
            result = await self._run_exactly_once(command, timeout=1800, safe_replay=True)
            payload = self._json_result(result.stdout or result.stderr, "asset staging")
        finally:
            await self._run_exactly_once(
                "rm -f /workspace/.gdpval-assets.json /workspace/.gdpval-asset-verify.py",
                timeout=30,
                safe_replay=True,
            )
        if result.exit_code == 2 or payload.get("status") == "fatal":
            raise VMVMFatalError(f"GDPval asset staging failed: {payload.get('error')}")
        if result.exit_code != 0 or payload.get("status") != "ok":
            raise VMVMInfrastructureLost(f"GDPval asset staging failed: {payload.get('error') or result.stderr}")
        observed = list(payload.get("assets") or [])
        if observed != [public_asset_record(item) for item in assets]:
            raise VMVMFatalError("GDPval staged asset manifest differs from the pinned host cache")
        return observed

    async def render_office(self, root: str = "/workspace", *, paths: list[str] | None = None) -> list[str]:
        root_path = self._resolve_path(root)
        script_path = "/workspace/.gdpval-office-render.py"
        await self.write_file_bytes(script_path, Path(__file__).with_name("office_render.py").read_bytes())
        selection = ""
        if paths is not None:
            selection = " --selected" + "".join(f" {shlex.quote(f'--path={path}')}" for path in paths)
        result = await self._run_exactly_once(
            f"python {shlex.quote(script_path)} {shlex.quote(root_path)}{selection}",
            timeout=1800,
            safe_replay=True,
        )
        payload = self._json_result(result.stdout or result.stderr, "Office rendering")
        if result.exit_code != 0 or payload.get("errors"):
            raise VMVMFatalError(
                "GDPval Office rendering failed: " + "; ".join(str(item) for item in payload.get("errors", []))
            )
        self.render_history.append({"root": root_path, "selected_paths": paths, **payload})
        return [str(path) for path in payload.get("rendered", [])]

    async def _restart_for_idempotent_io(self, operation: str) -> None:
        backend = self._require_backend()
        self._transport_drops += 1
        if self._transport_drops > self._max_connection_drops or not await anyio.to_thread.run_sync(
            backend.restart_session
        ):
            raise VMVMInfrastructureLost(f"VMVM connection lost during {operation}")

    async def read_file_bytes(self, path: str) -> bytes:
        resolved = self._resolve_path(path)
        if not await self.file_exists(path):
            raise FileNotFoundError(path)
        backend = self._require_backend()
        for attempt in range(2):
            try:
                return await anyio.to_thread.run_sync(lambda: backend.read_file(resolved))
            except RuntimeError:
                if attempt:
                    raise
                await self._restart_for_idempotent_io("file read")
        raise AssertionError("unreachable")

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        resolved = self._resolve_path(path)
        backend = self._require_backend()
        for attempt in range(2):
            try:
                await anyio.to_thread.run_sync(lambda: backend.transfer_file(content, resolved))
                return
            except RuntimeError:
                if attempt:
                    raise
                await self._restart_for_idempotent_io("idempotent file transfer")

    async def file_exists(self, path: str) -> bool:
        try:
            resolved = self._resolve_path(path)
        except ValueError:
            return False
        result = await self._run_exactly_once(
            f"test -f {shlex.quote(resolved)}",
            timeout=30,
            safe_replay=True,
        )
        return result.exit_code == 0

    async def is_directory(self, path: str) -> bool:
        try:
            resolved = self._resolve_path(path)
        except ValueError:
            return False
        result = await self._run_exactly_once(
            f"test -d {shlex.quote(resolved)}",
            timeout=30,
            safe_replay=True,
        )
        return result.exit_code == 0

    async def list_files(self, path: str) -> list[str]:
        resolved = self._resolve_path(path)
        result = await self._run_exactly_once(
            f"test -d {shlex.quote(resolved)} && find {shlex.quote(resolved)} -type f -printf '%P\\n' | sort",
            timeout=60,
            safe_replay=True,
        )
        if result.exit_code != 0:
            return []
        return [line for line in result.stdout.splitlines() if line]

    async def view_image(self, path: str) -> ImageContentBlock:
        data = await self.read_file_bytes(path)
        return ImageContentBlock(data=data)
