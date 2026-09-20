"""``SandoqAsyncSandboxClient`` — a drop-in for ``prime_sandboxes.AsyncSandboxClient``
backed by sandoq's session-lease + per-session ``/exec`` API.

``install()`` rebinds ``verifiers.utils.threaded_sandbox_client.AsyncSandboxClient``
to this class; ``ThreadedAsyncSandboxClient`` then constructs one per worker thread
and dispatches each method onto it inside a thread-local event loop. Because those
per-thread instances are distinct, session connection info lives in the
process-global :mod:`sandoq_provider.registry`.

Return types are the real ``prime_sandboxes`` models and errors are the real
``prime_sandboxes`` exceptions, so verifiers' ``except``/attribute access is unchanged.
The client prefers the sandoq server's native endpoints (``/upload``, ``/start_job``,
``/job/{id}``) and falls back to base64-over-``/exec`` where they're absent.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shlex
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from prime_sandboxes import (
    BackgroundJob,
    BackgroundJobStatus,
    CommandResponse,
    FileUploadResponse,
    ReadFileResponse,
)
from prime_sandboxes.exceptions import (
    APIError,
    CommandTimeoutError,
    SandboxFileNotFoundError,
)

from sandoq_provider import registry
from sandoq_provider.config import get_config, is_trivial_start_command
from sandoq_provider.gateway import get_gateway_adapter

_UPLOAD_CHUNK = 60_000  # base64 chars per /exec append in the fallback path


@dataclass
class _Sandbox:
    """create() return. v0 reads ``.id``; v1 PrimeRuntime.start also reads
    ``.pending_image_build_id`` (None => image already cached, no auto-build wait)."""

    id: str
    pending_image_build_id: str | None = None


@dataclass
class _Exposed:
    """expose() return — v1 PrimeRuntime reads ``.url``."""

    url: str


def _read_local_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def wrap_command(command: str, working_dir: str | None, env: dict | None) -> str:
    """Prefix ``cd``/``export`` so cwd + per-call env apply. The exec server writes
    the payload to a script and ``source``s it, so embedded newlines are fine."""
    pre = ""
    if working_dir:
        pre += f"cd {shlex.quote(working_dir)} || exit 127\n"
    if env:
        for k, v in env.items():
            pre += f"export {k}={shlex.quote(str(v))}\n"
    return pre + command if pre else command


# ── background lease renewer (one daemon per process) ────────────────────────────


_renewer_started = False
_renewer_lock = threading.Lock()


def _ensure_renewer(base_url: str, owner: str, lease_duration: str, margin_s: float) -> None:
    global _renewer_started
    with _renewer_lock:
        if _renewer_started:
            return
        _renewer_started = True
        threading.Thread(
            target=_renew_loop,
            args=(base_url, owner, lease_duration, margin_s),
            daemon=True,
            name="sandoq-lease-renewer",
        ).start()


def _renew_loop(base_url: str, owner: str, lease_duration: str, margin_s: float) -> None:
    interval = max(30.0, margin_s)
    gateway = get_gateway_adapter(base_url, owner)
    while True:
        time.sleep(interval)
        for sid in registry.all_ids():
            try:
                # Non-ok results are deliberately best-effort here; an
                # authoritative missing session is raised by the client and a
                # dropped lease surfaces on its next operation.
                gateway.renew_lease(sid, lease_duration, timeout=30.0)
            except Exception:
                pass  # best-effort; a dropped session surfaces on next exec


# ── the client ───────────────────────────────────────────────────────────────────


class SandoqAsyncSandboxClient:
    def __init__(
        self,
        api_key: str | None = None,
        max_connections: int = 1000,
        max_keepalive_connections: int = 200,
        **kwargs,
    ) -> None:
        # kwargs above mirror prime_sandboxes.AsyncSandboxClient / the values
        # ThreadedAsyncSandboxClient passes through; sandoq needs none of them.
        self._cfg = get_config()
        self._base = self._cfg.base_url

    # -- lifecycle -----------------------------------------------------------------

    async def create(self, request) -> _Sandbox:
        cfg = self._cfg
        env = cfg.resolve_environment(getattr(request, "docker_image", None))
        env_vars = dict(getattr(request, "environment_vars", None) or {})
        start_command = getattr(request, "start_command", None)
        request_id = uuid.uuid4().hex  # stable across 429 retries -> claims reserved pod
        gateway = get_gateway_adapter(self._base, cfg.owner)
        try:
            session = await gateway.create_session_async(
                env,
                cfg.lease_duration,
                request_id,
                timeout=cfg.create_deadline_s,
            )
        except TimeoutError as exc:
            raise APIError(
                f"environment '{env}' was not leased within {cfg.create_deadline_s:.0f}s — "
                "is it deployed and is /healthz green?"
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise APIError(f"sandoq create-session failed for '{env}': {exc}") from exc
        return self._on_created(env, env_vars, start_command, session)

    def _on_created(self, env, env_vars, start_command, session) -> _Sandbox:
        session_id = session.session_id
        port_urls = session.port_urls
        exec_url = port_urls.get("exec")
        if not session_id or not exec_url:
            raise APIError(f"sandoq create returned no sessionId/exec portUrl: {session.raw}")
        names = {port.name for port in session.ports} if session.ports else set(port_urls)
        if names and "exec" not in names:
            raise APIError(f"environment '{env}' does not expose an 'exec' port: {sorted(names)}")
        if not exec_url.endswith("/"):
            exec_url += "/"
        registry.register(
            registry.SessionInfo(
                session_id=session_id,
                exec_url=exec_url,
                environment=env,
                env_vars=env_vars,
                start_command=start_command,
                lease_duration=self._cfg.lease_duration,
                port_urls=dict(port_urls),
                outer_base_url=self._base,
                metadata={
                    "sandoq_session": dict(session.raw),
                    "sandoq_expires_at": session.expires_at,
                },
            )
        )
        _ensure_renewer(self._base, self._cfg.owner, self._cfg.lease_duration, self._cfg.renew_margin_s)
        return _Sandbox(id=session_id)

    async def wait_for_creation(self, sandbox_id: str, max_attempts: int = 120, **kwargs) -> None:
        info = self._info(sandbox_id)
        deadline = time.monotonic() + self._cfg.create_deadline_s
        healthy = False
        while time.monotonic() < deadline:
            try:
                response = await self._request_json(info, "GET", "healthz", timeout=5.0)
                if response.status_code == 200 and response.body.get("status") == "ok":
                    healthy = True
                    break
            except Exception:
                pass  # pod networking not up yet
            await asyncio.sleep(1.0)
        if not healthy:
            raise APIError(f"sandbox {sandbox_id} exec API /healthz not ready in time")
        await self._maybe_replay_start_command(info)

    async def _maybe_replay_start_command(self, info: registry.SessionInfo) -> None:
        """sandoq ignores CreateSandboxRequest.start_command (the CRD fixes the
        entrypoint). Replay a non-trivial one as a detached job — this is what boots
        PythonEnv's persistent worker."""
        if info.start_replayed or is_trivial_start_command(info.start_command):
            return
        info.start_replayed = True
        payload = {"cmd": info.start_command}
        if info.env_vars:
            payload["env"] = info.env_vars
        response = await self._request_json(info, "POST", "start_job", body=payload, timeout=30.0)
        if response.status_code in (200, 201):
            return
        # native /start_job absent -> detach via /exec
        fallback = f"nohup bash -lc {shlex.quote(info.start_command or '')} >/tmp/_sandoq_start.log 2>&1 &"
        await self._request_json(info, "POST", "exec", body={"cmd": fallback, "timeout": 30}, timeout=45.0)

    async def delete(self, sandbox_id: str, timeout: float | None = None) -> dict:
        request_timeout = float(timeout) if timeout else 30.0
        info = registry.get(sandbox_id)
        base_url = info.outer_base_url if info and info.outer_base_url else self._base
        try:
            deletion = await get_gateway_adapter(base_url, self._cfg.owner).delete_session_async(
                sandbox_id,
                timeout=request_timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise APIError(f"session {sandbox_id} deletion was not confirmed by typed HTTP 404: {exc}") from exc
        registry.unregister(sandbox_id)
        print(f"Sandoq session deleted: {sandbox_id} verified_http_status=404", flush=True)
        return {
            "status": "deleted",
            "sandbox_id": sandbox_id,
            "verified_http_status": deletion.verified_http_status,
        }

    async def bulk_delete(self, sandbox_ids=None, **kwargs) -> dict:
        ids = list(sandbox_ids or [])
        succeeded: list[str] = []
        failed: list[str] = []
        for sid in ids:
            try:
                await self.delete(sid)
                succeeded.append(sid)
            except Exception:
                failed.append(sid)
        return {"succeeded": succeeded, "failed": failed, "total": len(ids)}

    # -- exec ----------------------------------------------------------------------

    async def execute_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        env: dict | None = None,
        timeout: int | None = None,
    ) -> CommandResponse:
        info = self._info(sandbox_id)
        t = int(timeout) if timeout else 60
        response = await self._request_json(
            info,
            "POST",
            "exec",
            body={"cmd": wrap_command(command, working_dir, env), "timeout": t},
            timeout=float(t) + 30.0,
        )
        body = response.body
        if response.status_code != 200:
            raise APIError(f"/exec failed on {sandbox_id}: HTTP {response.status_code}: {body}")
        if body.get("timed_out"):
            raise CommandTimeoutError(sandbox_id, command, t)
        exit_code = body.get("exit_code")
        return CommandResponse(
            stdout=body.get("stdout") or "",
            stderr=body.get("stderr") or "",
            exit_code=exit_code if isinstance(exit_code, int) else -1,
        )

    # -- files ---------------------------------------------------------------------

    async def read_file(self, sandbox_id: str, file_path: str, timeout: int | None = None) -> ReadFileResponse:
        # base64-over-/exec: unambiguous (exit code distinguishes missing file) and
        # works on any exec env. read_file is not on the hot path for these envs.
        res = await self.execute_command(sandbox_id, f"base64 -w0 {shlex.quote(file_path)}", timeout=timeout or 30)
        if res.exit_code != 0:
            raise SandboxFileNotFoundError(f"file not found in {sandbox_id}: {file_path}")
        try:
            content = base64.b64decode(res.stdout).decode(errors="replace")
        except Exception:
            content = ""
        return ReadFileResponse(content=content, size=len(content))

    async def upload_bytes(
        self,
        sandbox_id: str,
        file_path: str,
        file_bytes: bytes,
        filename: str | None = None,
        timeout: int | None = None,
    ) -> FileUploadResponse:
        info = self._info(sandbox_id)
        content_b64 = base64.b64encode(file_bytes).decode()
        response = await self._request_json(
            info,
            "POST",
            "upload",
            body={"path": file_path, "content_b64": content_b64},
            timeout=float(timeout) if timeout else 120.0,
        )
        if response.status_code in (200, 201):
            return _upload_ok(file_path, len(file_bytes))
        if response.status_code in (404, 405, 501):  # native endpoint absent -> fallback
            await self._upload_via_exec(info, file_path, content_b64)
            return _upload_ok(file_path, len(file_bytes))
        raise APIError(f"/upload failed on {sandbox_id}: HTTP {response.status_code}: {response.body}")

    async def upload_file(
        self,
        sandbox_id: str,
        file_path: str,
        local_file_path: str,
        timeout: int | None = None,
    ) -> FileUploadResponse:
        data = await asyncio.to_thread(_read_local_bytes, local_file_path)
        return await self.upload_bytes(sandbox_id, file_path, data, timeout=timeout)

    async def _upload_via_exec(self, info: registry.SessionInfo, file_path: str, content_b64: str) -> None:
        q = shlex.quote(file_path)
        parent = os.path.dirname(file_path)
        setup = (f"mkdir -p {shlex.quote(parent)}; " if parent else "") + f": > {q}.b64"
        await self._request_json(info, "POST", "exec", body={"cmd": setup, "timeout": 30}, timeout=45.0)
        for i in range(0, len(content_b64), _UPLOAD_CHUNK):
            chunk = content_b64[i : i + _UPLOAD_CHUNK]
            await self._request_json(
                info,
                "POST",
                "exec",
                body={"cmd": f"printf %s {shlex.quote(chunk)} >> {q}.b64", "timeout": 30},
                timeout=45.0,
            )
        response = await self._request_json(
            info,
            "POST",
            "exec",
            body={"cmd": f"base64 -d {q}.b64 > {q} && rm -f {q}.b64", "timeout": 60},
            timeout=90.0,
        )
        body = response.body
        if body.get("timed_out") or body.get("exit_code") not in (0, None):
            raise APIError(f"base64 upload fallback failed for {file_path}: {body}")

    async def download_file(
        self,
        sandbox_id: str,
        file_path: str,
        local_file_path: str,
        timeout: int | None = None,
    ) -> None:
        """Download a (possibly binary) sandbox file to a local path — v1
        PrimeRuntime.read uses this. Reads raw bytes via base64-over-/exec so binary
        content survives (unlike read_file, which decodes to text)."""
        res = await self.execute_command(sandbox_id, f"base64 -w0 {shlex.quote(file_path)}", timeout=timeout or 60)
        if res.exit_code != 0:
            raise SandboxFileNotFoundError(f"file not found in {sandbox_id}: {file_path}")
        data = base64.b64decode(res.stdout or "")

        def _write() -> None:
            parent = os.path.dirname(local_file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(local_file_path, "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write)

    async def expose(self, sandbox_id: str, port: int, name: str | None = None, protocol: str = "HTTP") -> _Exposed:
        """Return the public URL for a sandbox port (v1 PrimeRuntime.expose reads
        ``.url``). sandoq exposes only the ports declared in the Environment CRD
        (surfaced as the session's ``portUrls``); there is no runtime arbitrary-port
        exposure. Map ``port`` to a declared portUrl by name, else raise — in-sandbox
        server exposure / interception is agent-inside (Phase 2)."""
        info = self._info(sandbox_id)
        urls = info.port_urls or {}
        if name and name in urls:
            return _Exposed(url=urls[name])
        wellknown = {8000: "exec", 7681: "terminal"}.get(int(port))
        if wellknown and wellknown in urls:
            return _Exposed(url=urls[wellknown])
        raise APIError(
            f"sandoq exposes only CRD-declared ports {sorted(urls)} on {sandbox_id}; "
            f"cannot expose port {port} at runtime (in-sandbox server exposure / "
            f"interception is agent-inside / Phase 2)."
        )

    # -- background jobs -----------------------------------------------------------

    async def start_background_job(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        env: dict | None = None,
    ) -> BackgroundJob:
        info = self._info(sandbox_id)
        payload: dict = {"cmd": command}
        merged_env = {**info.env_vars, **(env or {})}
        if merged_env:
            payload["env"] = merged_env
        if working_dir:
            payload["cwd"] = working_dir
        response = await self._request_json(info, "POST", "start_job", body=payload, timeout=30.0)
        body = response.body
        if response.status_code not in (200, 201) or "job_id" not in body:
            raise APIError(f"/start_job failed on {sandbox_id}: HTTP {response.status_code}: {body}")
        job_id = body["job_id"]
        return BackgroundJob(
            job_id=job_id,
            sandbox_id=sandbox_id,
            stdout_log_file=f"{job_id}.out",
            stderr_log_file=f"{job_id}.err",
            exit_file=f"{job_id}.rc",
        )

    async def get_background_job(self, sandbox_id: str, job, timeout: int | None = None) -> BackgroundJobStatus:
        info = self._info(sandbox_id)
        job_id = getattr(job, "job_id", None)
        if job_id is None and isinstance(job, dict):
            job_id = job.get("job_id")
        response = await self._request_json(
            info,
            "GET",
            f"job/{job_id}",
            timeout=float(timeout) if timeout else 60.0,
        )
        body = response.body
        if response.status_code != 200:
            raise APIError(f"/job failed on {sandbox_id}: HTTP {response.status_code}: {body}")
        return BackgroundJobStatus(
            job_id=body.get("job_id", job_id),
            completed=bool(body.get("completed")),
            exit_code=body.get("exit_code"),
            stdout=body.get("stdout"),
            stderr=body.get("stderr"),
        )

    async def run_background_job(
        self,
        sandbox_id: str,
        command: str,
        timeout: int | None = None,
        working_dir: str | None = None,
        env: dict | None = None,
        poll_interval: int = 3,
    ) -> CommandResponse:
        """Start and poll a job, matching the convenience API used by v0 SWE scorers."""
        job = await self.start_background_job(
            sandbox_id,
            command,
            working_dir=working_dir,
            env=env,
        )
        deadline = time.monotonic() + timeout if timeout is not None else None
        max_poll_delay = max(float(poll_interval), 0.0)
        delay = min(0.1, max_poll_delay)
        while True:
            result = await self.get_background_job(sandbox_id, job)
            if result.completed:
                return CommandResponse(
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    exit_code=result.exit_code if result.exit_code is not None else -1,
                )
            if deadline is not None and time.monotonic() >= deadline:
                raise CommandTimeoutError(sandbox_id, command, timeout)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_poll_delay)

    # -- misc no-ops present on the prime client ----------------------------------

    async def aclose(self) -> None:
        return None

    async def clear_auth_cache(self) -> None:
        return None

    # -- helpers -------------------------------------------------------------------

    async def _request_json(
        self,
        info: registry.SessionInfo,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ):
        base_url = info.outer_base_url or self._base
        return await get_gateway_adapter(base_url, self._cfg.owner).request_json_async(
            method,
            info.exec_url + path,
            body=body,
            headers=headers,
            timeout=timeout,
        )

    def _info(self, sandbox_id: str) -> registry.SessionInfo:
        info = registry.get(sandbox_id)
        if info is None:
            raise APIError(f"unknown sandbox_id {sandbox_id} (not leased by this process)")
        return info


def _upload_ok(path: str, size: int) -> FileUploadResponse:
    return FileUploadResponse(success=True, path=path, size=size, timestamp=datetime.now(timezone.utc))
