"""Pier environment adapter for Verifiers v1 sandbox runtimes."""

import asyncio
import io
import re
import shlex
import shutil
import tarfile
import tempfile
import uuid
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pier.environments.base import BaseEnvironment, ExecResult
from pier.environments.capabilities import EnvironmentCapabilities
from pier.models.agent.install import InstallStep
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import (
    ModalConfig,
    SandoqConfig,
    VMVMConfig,
    make_runtime,
)

Provider = Literal["modal", "vmvm", "sandoq"]
_AGENT_NETWORK_MARKER = "PIER_RUNTIME_AGENT_NETWORK"
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)
_UV_INSTALLER = re.compile(
    r"^curl -LsSf https://astral\.sh/uv/[^/]+/install\.sh \| sh$",
    re.MULTILINE,
)
_STAGED_UV_ARCHIVE = "/tmp/pier-host-uv.tgz"
_STAGED_UV_PATH = "/opt/pier-tools/uv"
_USE_STAGED_UV = f"""
mkdir -p "$HOME/.local/bin"
ln -sf {_STAGED_UV_PATH} "$HOME/.local/bin/uv"
ln -sf {_STAGED_UV_PATH} "$HOME/.local/bin/uvx"
printf '%s\n' 'export PATH="$HOME/.local/bin:$PATH"' > "$HOME/.local/bin/env"
""".strip()


@cache
def _host_uv_archive() -> bytes | None:
    uv = shutil.which("uv")
    if uv is None:
        return None
    data = Path(uv).resolve().read_bytes()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("uv")
        member.mode = 0o755
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


class PierRuntimeEnvironment(BaseEnvironment):
    """Run Pier trials through the same Runtime contract used by prime-rl evals."""

    def __init__(
        self,
        *args,
        provider: Provider,
        runtime_options: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        self.provider = provider
        self.runtime_options = dict(runtime_options or {})
        self._runtime = None
        self._runtime_image = ""
        self._sandbox_error: SandboxError | None = None
        self._bootstrap_copies: list[tuple[Path, str]] = []
        self._bootstrap_commands: list[str] = []
        self._capabilities = EnvironmentCapabilities(
            disable_internet=True,
            filtered_egress=True,
            preinstall_agents=True,
        )
        super().__init__(*args, **kwargs)

    @staticmethod
    def type() -> str:
        return "prime-runtime"

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return self._capabilities

    def _validate_definition(self) -> None:
        if self.task_env_config.docker_image:
            self._runtime_image = self.task_env_config.docker_image
            return

        dockerfile = self.environment_dir / "Dockerfile"
        if not dockerfile.is_file():
            raise FileNotFoundError(
                "Runtime-backed Pier environments require environment.docker_image "
                f"or a Dockerfile: {dockerfile}"
            )
        self._runtime_image, self._bootstrap_copies, self._bootstrap_commands = (
            self._parse_simple_dockerfile(dockerfile)
        )

    @staticmethod
    def _parse_simple_dockerfile(
        dockerfile: Path,
    ) -> tuple[str, list[tuple[Path, str]], list[str]]:
        image = ""
        copies: list[tuple[Path, str]] = []
        commands: list[str] = []
        context = dockerfile.parent.resolve()
        for line_number, raw_line in enumerate(dockerfile.read_text().splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            instruction, separator, value = line.partition(" ")
            instruction = instruction.upper()
            value = value.strip()
            if not separator or not value:
                raise ValueError(f"invalid Dockerfile instruction at {dockerfile}:{line_number}")
            if instruction == "FROM":
                if image or len(shlex.split(value)) != 1:
                    raise ValueError(
                        f"only one plain FROM image is supported at {dockerfile}:{line_number}"
                    )
                image = value
                continue
            if instruction == "COPY":
                parts = shlex.split(value)
                if len(parts) != 2 or parts[0].startswith("--"):
                    raise ValueError(
                        f"only COPY SOURCE DEST is supported at {dockerfile}:{line_number}"
                    )
                source = (context / parts[0]).resolve()
                if not source.is_relative_to(context) or not source.is_file():
                    raise ValueError(
                        f"Dockerfile COPY source must be a file in {context}: {parts[0]!r}"
                    )
                destination = PurePosixPath(parts[1])
                if not destination.is_absolute() or ".." in destination.parts:
                    raise ValueError(
                        f"Dockerfile COPY destination must be absolute: {parts[1]!r}"
                    )
                copies.append((source, str(destination)))
                continue
            if instruction == "RUN":
                commands.append(value)
                continue
            raise ValueError(
                f"unsupported Dockerfile instruction {instruction!r} at "
                f"{dockerfile}:{line_number}"
            )
        if not image:
            raise ValueError(f"Dockerfile has no FROM image: {dockerfile}")
        return image, copies, commands

    def _runtime_config(self):
        workdir = self.task_env_config.workdir or "/app"
        resources = {
            "image": self._runtime_image,
            "workdir": workdir,
            "network_access": True,
            "cpu": float(self._effective_cpus or 1),
            "memory": float(self._effective_memory_mb or 2048) / 1024,
            "disk": float(self._effective_storage_mb or 5120) / 1024,
            **self.runtime_options,
        }
        if self.provider == "modal":
            return ModalConfig(**resources)
        if self.provider == "vmvm":
            resources.pop("network_access", None)
            return VMVMConfig(**resources)
        if self.provider == "sandoq":
            return SandoqConfig(**resources)
        raise ValueError(f"unsupported Runtime provider: {self.provider}")

    async def start(self, force_build: bool) -> None:
        if force_build:
            self.logger.warning("force_build is ignored for prebuilt Runtime images")
        self._runtime = make_runtime(self._runtime_config(), name=self.session_id)
        try:
            await self._runtime.start()
            await self._materialize_dockerfile()
            await self._install_agent()
            paths = self.env_paths
            result = await self.exec(
                "mkdir -p "
                + " ".join(
                    shlex.quote(str(path))
                    for path in (
                        paths.agent_dir,
                        paths.verifier_dir,
                        paths.artifacts_dir,
                        paths.tests_dir,
                    )
                )
                + " && chmod 777 "
                + " ".join(
                    shlex.quote(str(path))
                    for path in (paths.agent_dir, paths.verifier_dir, paths.artifacts_dir)
                ),
                user="root",
            )
            if result.return_code != 0:
                raise RuntimeError(
                    result.stderr or result.stdout or "failed to initialize Pier paths"
                )
        except BaseException:
            await asyncio.shield(self._runtime.stop())
            self._runtime = None
            raise
        if not self.task_env_config.allow_internet:
            self.logger.warning(
                "%s Runtime keeps provider networking enabled for model access; "
                "trajectory parity must audit agent network commands",
                self.provider,
            )

    async def _materialize_dockerfile(self) -> None:
        for source, destination in self._bootstrap_copies:
            await self.runtime.write(
                destination,
                await asyncio.to_thread(source.read_bytes),
            )
        for command in self._bootstrap_commands:
            result = await self.runtime.run(["sh", "-lc", command], {})
            if result.exit_code != 0:
                detail = result.stderr or result.stdout or "no output"
                raise RuntimeError(
                    f"Dockerfile RUN failed with code {result.exit_code}: {detail[-2000:]}"
                )

    async def _install_agent(self) -> None:
        install = self.agent_install_spec
        if install is None:
            return
        use_staged_uv = await self._stage_host_uv(install.steps)
        for step in install.steps:
            user = "root" if step.user == "root" else self.default_user
            command = step.run
            if use_staged_uv:
                command = _UV_INSTALLER.sub(_USE_STAGED_UV, command, count=1)
            result = await self.exec(
                command,
                env={**(step.env or {}), _AGENT_NETWORK_MARKER: "1"},
                timeout_sec=int(self.task_env_config.build_timeout_sec),
                user=user,
            )
            if result.return_code != 0:
                detail = result.stderr or result.stdout or "no output"
                raise RuntimeError(
                    f"agent install step failed with code {result.return_code}: {detail[-2000:]}"
                )
        if install.verification_command:
            result = await self.exec(
                install.verification_command,
                env={_AGENT_NETWORK_MARKER: "1"},
                timeout_sec=120,
                user=self.default_user,
            )
            if result.return_code != 0:
                raise RuntimeError(
                    "agent installation verification failed: "
                    + (result.stderr or result.stdout or "no output")[-2000:]
                )

    async def _stage_host_uv(self, steps: list[InstallStep]) -> bool:
        if not any(_UV_INSTALLER.search(step.run) for step in steps):
            return False
        archive = await asyncio.to_thread(_host_uv_archive)
        if archive is None:
            return False
        await self.runtime.write(_STAGED_UV_ARCHIVE, archive)
        result = await self.runtime.run(
            [
                "sh",
                "-c",
                "mkdir -p /opt/pier-tools && "
                f"tar -xzf {_STAGED_UV_ARCHIVE} -C /opt/pier-tools && "
                f"rm -f {_STAGED_UV_ARCHIVE} && "
                f"{_STAGED_UV_PATH} --version",
            ],
            {},
        )
        if result.exit_code != 0:
            detail = result.stderr or result.stdout or "no output"
            raise RuntimeError(f"failed to stage host uv: {detail[-2000:]}")
        self.logger.info(
            "Staged evaluator uv for %s agent setup: %s",
            self.provider,
            result.stdout.strip(),
        )
        return True

    async def stop(self, delete: bool) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        if not delete:
            self.logger.info(
                "Runtime provider %s is ephemeral and will release %s regardless of "
                "delete=False",
                self.provider,
                runtime.descriptor,
            )
        self._runtime = None
        await runtime.stop()
        if self._sandbox_error is not None:
            raise self._sandbox_error

    async def _remember_sandbox_error(self, awaitable):
        try:
            return await awaitable
        except SandboxError as error:
            if self._sandbox_error is None:
                self._sandbox_error = error
            raise

    @property
    def runtime(self):
        if self._runtime is None:
            raise RuntimeError("Pier Runtime environment is not running")
        return self._runtime

    def agent_process_env(self, env: dict[str, str] | None) -> dict[str, str]:
        return {**(env or {}), _AGENT_NETWORK_MARKER: "1"}

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        user = self._resolve_user(user)
        merged_env = self._merge_env(env) or {}
        agent_network = merged_env.pop(_AGENT_NETWORK_MARKER, None) == "1"
        if user is not None:
            if isinstance(user, int):
                user_arg = f"$(getent passwd {user} | cut -d: -f1)"
            else:
                user_arg = shlex.quote(str(user))
            command = f"su -m {user_arg} -s /bin/bash -c {shlex.quote(command)}"
        effective_cwd = cwd or self.task_env_config.workdir or "/app"
        command = f"cd {shlex.quote(effective_cwd)} && {command}"
        if not agent_network:
            command = "unset " + " ".join(_PROXY_ENV_KEYS) + "; " + command
        if timeout_sec is not None:
            command = f"timeout --signal=TERM {int(timeout_sec)}s bash -c {shlex.quote(command)}"
        result = await self._remember_sandbox_error(
            self.runtime.run(["bash", "-c", command], merged_env)
        )
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.exit_code,
        )

    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        source = Path(source_path)
        await self._remember_sandbox_error(
            self.runtime.write(target_path, await asyncio.to_thread(source.read_bytes))
        )

    async def upload_dir(self, source_dir: Path | str, target_dir: str) -> None:
        source = Path(source_dir)
        archive_path = f"/tmp/pier-upload-{uuid.uuid4().hex}.tar.gz"
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "upload.tar.gz"

            def build_archive() -> None:
                with tarfile.open(archive, "w:gz") as handle:
                    for child in source.iterdir():
                        handle.add(child, arcname=child.name)

            await asyncio.to_thread(build_archive)
        await self._remember_sandbox_error(
            self.runtime.write(archive_path, await asyncio.to_thread(archive.read_bytes))
        )
        result = await self._remember_sandbox_error(
            self.runtime.run(
                [
                    "bash",
                    "-lc",
                    f"mkdir -p {shlex.quote(target_dir)} && "
                    f"tar -xzf {shlex.quote(archive_path)} -C {shlex.quote(target_dir)} && "
                    f"rm -f {shlex.quote(archive_path)}",
                ],
                {},
            )
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or result.stdout or "directory upload failed")

    async def download_file(self, source_path: str, target_path: Path | str) -> None:
        target = Path(target_path)
        data = await self._remember_sandbox_error(self.runtime.read(source_path))

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(write)

    async def download_dir(self, source_dir: str, target_dir: Path | str) -> None:
        archive_path = f"/tmp/pier-download-{uuid.uuid4().hex}.tar.gz"
        result = await self._remember_sandbox_error(
            self.runtime.run(
                [
                    "bash",
                    "-lc",
                    f"tar -czf {shlex.quote(archive_path)} -C {shlex.quote(source_dir)} .",
                ],
                {},
            )
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or result.stdout or "directory download failed")
        data = await self._remember_sandbox_error(self.runtime.read(archive_path))
        await self._remember_sandbox_error(
            self.runtime.run(["rm", "-f", archive_path], {})
        )
        target = Path(target_dir)

        def extract() -> None:
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "download.tar.gz"
                archive.write_bytes(data)
                with tarfile.open(archive, "r:gz") as handle:
                    handle.extractall(target, filter="data")

        await asyncio.to_thread(extract)
