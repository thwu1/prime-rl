"""Harbor taskset with faithful VMVM execution and verifier isolation.

The repository-root Mobius corpus uses Harbor's shared verifier mode.  The
same adapter also supports Terminal-Bench 4's separate verifier containers by
capturing the declared artifacts once and replaying those exact bytes into a
fresh verifier VMVM.  Infrastructure failures are never converted into reward
zero: shared-mode failures propagate so the framework can retry the rollout,
while separate verifier failures retry only the verifier against the captured
artifacts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import shlex
import subprocess
import tarfile
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Literal
from weakref import WeakKeyDictionary

import verifiers.v1 as vf
from pydantic import Field
from verifiers.v1.decorators import reward
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import ProgramResult, Runtime, VMVMRuntime, make_runtime
from verifiers.v1.task import TaskResources, TaskTimeout
from verifiers.v1.tasksets.harbor_v1 import HarborConfig, HarborTask, HarborTaskset
from verifiers.v1.tasksets.harbor_v1.taskset import Author, make_tar, parse_resources

logger = logging.getLogger("terminal_bench_vmvm")

DEFAULT_DATASET_REVISION = "9b6988a3faf0"
DEFAULT_IMAGE_PREFIX = "vmvm-registry.fbinfra.net/terminal_bench"
VERIFIER_TIMEOUT_MARKER = "__TERMINAL_BENCH_VERIFIER_TIMEOUT__"
TEST_DEPENDENCY_MARKER = "Test dependencies prebaked so the verifier runs offline"
_EXACT_PIP_REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")
_PIP_EXECUTABLE_RE = re.compile(r"pip(?:3(?:\.[0-9]+)?)?")
_PYTHON_EXECUTABLE_RE = re.compile(r"python(?:3(?:\.[0-9]+)?)?")
_SHELL_CONTROL_TOKENS = {"if", "then", "elif", "do", "!", "command", "exec", "time", "env"}

# Reference-solution-only compatibility constraints. These never enter model
# rollouts or verifier containers. build123d 0.10.0 permits ocp_gordon>=0.1.17,
# but ocp_gordon 0.2+ moved to OCP 7.9/8 while build123d pins OCP 7.8. The
# unconstrained TB4 cad-model oracle therefore broke when 0.3.0 shipped.
ORACLE_PIP_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "cad-model": ("ocp_gordon==0.1.18",),
}


class OracleFailure(RuntimeError):
    """The task or its reference solution failed, rather than VMVM transport."""


class UnsupportedTaskError(ValueError):
    """The task requires a Harbor feature the single-container VMVM cannot supply."""


class TerminalBenchVMVMConfig(HarborConfig):
    dataset_dir: Path = Path(".")
    """Directory whose immediate children are Harbor tasks."""

    dataset_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    """Optional exact Git commit required for a clean dataset worktree."""

    task_file: Path | None = None
    """Optional newline-delimited task slugs, useful for large oracle-qualified subsets."""

    task_file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    """Optional exact SHA-256 required for ``task_file`` before task loading."""

    image_prefix: str = DEFAULT_IMAGE_PREFIX
    image_tag: str = f"mobius-{DEFAULT_DATASET_REVISION}"
    verifier_image_suffix: str = "-verifier"
    image_manifest: Path | None = None
    """Optional JSON mapping task slugs to immutable agent/verifier image refs."""
    image_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    """Optional exact SHA-256 required for ``image_manifest`` before task loading."""
    use_declared_images: bool = False
    """Prefer task.toml docker_image fields over deterministic built image names."""
    enable_compose: bool = False
    """Run an environment/docker-compose.yaml as infrastructure for this dataset."""

    verifier_runtime_retries: int = Field(2, ge=0)
    capture_convention_artifacts: bool = True
    """Also preserve Harbor's conventional /logs/artifacts directory when present."""

    oracle_solution_network_mode: Literal["declared", "public"] = "declared"
    """Network policy for trusted reference solutions; model rollouts always use the declared policy."""


class ArtifactSpec(vf.StrictBaseModel):
    source: str
    destination: str | None = None
    exclude: list[str] = Field(default_factory=list)
    service: str | None = None


class CollectHook(vf.StrictBaseModel):
    command: str
    service: str = "main"
    timeout_sec: float = Field(60.0, gt=0)
    user: str | int | None = None


@dataclass(frozen=True)
class PrefetchedTestDependencies:
    requirements: tuple[str, ...]
    archive_path: Path | None
    sha256: str | None
    universal: bool
    compatibility_fingerprint: str | None

    @classmethod
    def store(
        cls,
        cache_directory: Path,
        requirements: tuple[str, ...],
        wheel_archive: bytes,
        compatibility_fingerprint: str,
    ) -> "PrefetchedTestDependencies":
        archive_path = cache_directory / f"{uuid.uuid4().hex}.tar"
        try:
            archive_path.touch(mode=0o600, exist_ok=False)
            archive_path.write_bytes(wheel_archive)
            wheel_names: list[str] = []
            with tarfile.open(archive_path, mode="r:") as archive:
                for member in archive.getmembers():
                    parts = PurePosixPath(member.name).parts
                    if member.isdir() and not parts:
                        continue
                    if not member.isfile() or len(parts) != 1 or not parts[0].lower().endswith(".whl"):
                        raise RuntimeError("prefetched verifier wheelhouse contained an invalid archive member")
                    wheel_names.append(parts[0])
            if not wheel_names:
                raise RuntimeError("prefetched verifier wheelhouse archive was empty")
            archive_path.chmod(0o400)
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
        return cls(
            requirements=requirements,
            archive_path=archive_path,
            sha256=hashlib.sha256(wheel_archive).hexdigest(),
            universal=all(name.lower().endswith("-none-any.whl") for name in wheel_names),
            compatibility_fingerprint=compatibility_fingerprint,
        )

    def verify(self) -> None:
        if self.archive_path is None or self.sha256 is None:
            raise RuntimeError("prefetched verifier wheelhouse was missing")
        digest = hashlib.sha256()
        try:
            with self.archive_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise RuntimeError("prefetched verifier wheelhouse was missing") from error
        if self.sha256 != digest.hexdigest():
            raise RuntimeError("prefetched verifier wheelhouse failed integrity check")

    def read_verified(self) -> bytes:
        self.verify()
        assert self.archive_path is not None
        wheel_archive = self.archive_path.read_bytes()
        if self.sha256 != hashlib.sha256(wheel_archive).hexdigest():
            raise RuntimeError("prefetched verifier wheelhouse failed integrity check")
        return wheel_archive


class TerminalBenchTask(HarborTask):
    slug: str = Field(exclude=True)
    verifier_mode: Literal["shared", "separate"] = Field(exclude=True)
    verifier_image: str | None = Field(default=None, exclude=True)
    verifier_workdir: str = Field(default="/app", exclude=True)
    verifier_resources: TaskResources = Field(default_factory=TaskResources, exclude=True)
    verifier_timeout_sec: float = Field(gt=0, exclude=True)
    verifier_env: dict[str, str] = Field(default_factory=dict, exclude=True)
    solution_env: dict[str, str] = Field(default_factory=dict, exclude=True)
    artifacts: list[ArtifactSpec] = Field(default_factory=list, exclude=True)
    collect_hooks: list[CollectHook] = Field(default_factory=list, exclude=True)
    verifier_tests_baked: bool = Field(default=False, exclude=True)
    agent_network_mode: Literal["public", "no-network"] = Field(default="public", exclude=True)
    verifier_network_mode: Literal["public", "no-network"] = Field(default="public", exclude=True)


def _environment_workdir(dockerfile: Path, default: str = "/app") -> str:
    """Return the final literal WORKDIR, matching Harbor's container semantics."""
    if not dockerfile.is_file():
        return default
    workdir = PurePosixPath(default)
    for raw in dockerfile.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, separator, value = line.partition(" ")
        if not separator or head.upper() != "WORKDIR":
            continue
        candidate = value.strip()
        if not candidate:
            continue
        if "$" in candidate:
            raise ValueError(f"{dockerfile}: variable WORKDIR is not supported: {candidate!r}")
        path = PurePosixPath(candidate)
        workdir = path if path.is_absolute() else workdir / path
    return str(workdir)


def _compose_path(task_dir: Path) -> Path | None:
    """Return the first conventional Compose file in Harbor precedence order."""
    environment = task_dir / "environment"
    for filename in (
        "docker-compose.yaml",
        "docker-compose.yml",
        "compose.yaml",
        "compose.yml",
    ):
        candidate = environment / filename
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=None)
def _declared_test_requirements(task_dir: str) -> tuple[str, ...]:
    """Read the reproducible test-only pip layer from a task Dockerfile.

    The repository's current Dockerfiles contain this layer, while the older
    immutable Mobius images predate it. Replaying only explicitly marked
    requirements repairs those images without guessing from verifier failures.
    """
    dockerfile = Path(task_dir) / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        return ()
    lines = dockerfile.read_text(errors="replace").splitlines()
    try:
        marker_index = next(index for index, line in enumerate(lines) if TEST_DEPENDENCY_MARKER in line)
    except StopIteration:
        return ()

    logical_lines: list[str] = []
    current = ""
    for raw in lines[marker_index + 1 :]:
        stripped = raw.strip()
        if not stripped and not current:
            continue
        continuation = stripped.endswith("\\")
        piece = stripped[:-1].rstrip() if continuation else stripped
        current = f"{current} {piece}".strip()
        if continuation:
            continue
        logical_lines.append(current)
        current = ""
    if current:
        logical_lines.append(current)

    for line in logical_lines:
        if not line.startswith("RUN "):
            continue
        match = re.search(
            r"(?:^|\s)(?:(?:python|python3)\s+-m\s+)?pip3?\s+install\s+(.+)$",
            line[4:],
        )
        if match is None:
            continue
        requirements: list[str] = []
        for token in shlex.split(match.group(1)):
            if token in {"&&", "||", "|", ";"}:
                break
            if token.startswith("-"):
                continue
            if re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?"
                r"(?:==[^\s;]+)?",
                token,
            ):
                requirements.append(token)
        return tuple(requirements)
    return ()


@lru_cache(maxsize=None)
def _test_script_requirements(task_dir: str) -> tuple[str, ...]:
    """Extract reproducible literal pip requirements from the verifier script.

    Older immutable Mobius images predate some test-only dependency layers.
    The verifier scripts still declare exact pins, so those wheels can be
    fetched during trusted setup without staging or executing the hidden tests.
    Dynamic requirements, local paths, URLs, and unpinned packages are ignored.
    """
    test_script = Path(task_dir) / "tests" / "test.sh"
    if not test_script.is_file():
        return ()
    source = test_script.read_text(errors="replace").replace("\\\n", " ")
    requirements: list[str] = []
    for line in source.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError:
            continue
        commands: list[list[str]] = []
        command: list[str] = []
        for token in tokens:
            if token and set(token) <= set(";&|<>"):
                if command:
                    commands.append(command)
                    command = []
            else:
                command.append(token)
        if command:
            commands.append(command)
        for command in commands:
            while command and (
                command[0] in _SHELL_CONTROL_TOKENS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", command[0])
            ):
                command = command[1:]
            if not command:
                continue
            executable = PurePosixPath(command[0]).name
            requirement_start = None
            if _PIP_EXECUTABLE_RE.fullmatch(executable) and len(command) > 1 and command[1] == "install":
                requirement_start = 2
            elif _PYTHON_EXECUTABLE_RE.fullmatch(executable) and command[1:4] == [
                "-m",
                "pip",
                "install",
            ]:
                requirement_start = 4
            if requirement_start is None:
                continue
            for requirement in command[requirement_start:]:
                if _EXACT_PIP_REQUIREMENT_RE.fullmatch(requirement):
                    requirements.append(requirement)
    return tuple(dict.fromkeys(requirements))


def _requirement_name(requirement: str) -> str:
    name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _merge_test_requirements(*groups: tuple[str, ...]) -> tuple[str, ...]:
    requirements: dict[str, str] = {}
    for group in groups:
        for requirement in group:
            normalized_name = _requirement_name(requirement)
            previous = requirements.get(normalized_name)
            if previous is not None and previous != requirement:
                raise ValueError(f"conflicting verifier requirements: {previous!r} and {requirement!r}")
            requirements[normalized_name] = requirement
    return tuple(requirements.values())


@lru_cache(maxsize=None)
def _dockerfile_startup_command(task_dir: str) -> tuple[str, ...]:
    """Return the final explicit ENTRYPOINT+CMD declared by a task image.

    The vacli backend replaces PID 1 with a keepalive so it can reliably attach
    a persistent shell. Harbor images that declare a service process still need
    that process started inside the live container.
    """
    dockerfile = Path(task_dir) / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        return ()

    entrypoint: tuple[str, ...] | None = None
    command: tuple[str, ...] | None = None
    entrypoint_is_shell = False
    for raw in dockerfile.read_text(errors="replace").splitlines():
        line = raw.strip()
        instruction, separator, value = line.partition(" ")
        instruction = instruction.upper()
        if not separator or instruction not in {"ENTRYPOINT", "CMD"}:
            continue
        value = value.strip()
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ValueError(f"{dockerfile}: invalid {instruction} {value!r}")
            parsed_command = tuple(parsed)
            shell_form = False
        else:
            parsed_command = ("/bin/sh", "-c", value)
            shell_form = True
        if instruction == "ENTRYPOINT":
            entrypoint = parsed_command
            entrypoint_is_shell = shell_form
        else:
            command = parsed_command

    if entrypoint:
        return entrypoint if entrypoint_is_shell else entrypoint + (command or ())
    return command or ()


def _image_ref(prefix: str, slug: str, tag: str, suffix: str = "") -> str:
    prefix = prefix.rstrip("/")
    if not prefix or not tag or tag == "latest":
        raise ValueError("image_prefix and an immutable, non-'latest' image_tag are required")
    return f"{prefix}/{slug}{suffix}:{tag}"


def _load_image_manifest(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text())
    images = raw.get("images", raw)
    if not isinstance(images, dict):
        raise ValueError(f"{path}: image manifest must contain an object named 'images'")
    normalized: dict[str, dict[str, str]] = {}
    for slug, entry in images.items():
        if isinstance(entry, str):
            normalized[str(slug)] = {"agent": entry}
        elif isinstance(entry, dict):
            normalized[str(slug)] = {
                str(role): str(reference) for role, reference in entry.items() if isinstance(reference, str)
            }
        else:
            raise ValueError(f"{path}: invalid image entry for {slug!r}")
    return normalized


def _string_env(raw: dict | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in (raw or {}).items()}


def _network_policy_mode(
    task_name: str,
    role: str,
    raw: dict,
    *,
    default: Literal["public", "no-network"],
    phase_override: bool = False,
) -> Literal["public", "no-network"]:
    """Resolve Harbor's baseline/phase network mode without weakening it."""
    declared = raw.get("network_mode")
    if declared is None:
        if phase_override and "allowed_hosts" in raw:
            raise ValueError(f"{task_name}: {role}.allowed_hosts requires network_mode='allowlist'")
        if not phase_override and "allow_internet" in raw:
            allow_internet = raw["allow_internet"]
            if not isinstance(allow_internet, bool):
                raise ValueError(f"{task_name}: {role}.allow_internet must be a boolean")
            declared = "public" if allow_internet else "no-network"
        else:
            declared = default
    if declared == "allowlist":
        raise UnsupportedTaskError(f"{task_name}: {role} network_mode='allowlist' is not supported by VMVM")
    if declared not in ("public", "no-network"):
        raise UnsupportedTaskError(f"{task_name}: unknown {role} network_mode {declared!r}")
    if raw.get("allowed_hosts"):
        raise ValueError(f"{task_name}: {role}.allowed_hosts is only valid with network_mode='allowlist'")
    return declared


def _network_modes(
    task_name: str,
    raw: dict,
    verifier_mode: Literal["shared", "separate"],
) -> tuple[Literal["public", "no-network"], Literal["public", "no-network"]]:
    environment = raw.get("environment", {})
    agent = raw.get("agent", {})
    verifier = raw.get("verifier", {})
    environment_mode = _network_policy_mode(
        task_name,
        "environment",
        environment,
        default="public",
    )
    agent_mode = _network_policy_mode(
        task_name,
        "agent",
        agent,
        default=environment_mode,
        phase_override=True,
    )
    if environment_mode == "no-network" and agent_mode == "public":
        raise UnsupportedTaskError(
            f"{task_name}: VMVM cannot relax the no-network environment baseline for the agent phase"
        )

    verifier_environment = verifier.get("environment")
    if verifier_mode == "separate" and verifier_environment is not None:
        if not isinstance(verifier_environment, dict):
            raise ValueError(f"{task_name}: verifier.environment must be a table")
        verifier_baseline = _network_policy_mode(
            task_name,
            "verifier.environment",
            verifier_environment,
            default="public",
        )
    else:
        verifier_baseline = environment_mode
    verifier_mode_resolved = _network_policy_mode(
        task_name,
        "verifier",
        verifier,
        default=verifier_baseline,
        phase_override=True,
    )
    if verifier_baseline == "no-network" and verifier_mode_resolved == "public":
        raise UnsupportedTaskError(
            f"{task_name}: VMVM cannot relax the no-network verifier baseline for the verifier phase"
        )
    if verifier_mode == "shared" and agent_mode == "no-network" and verifier_mode_resolved == "public":
        raise UnsupportedTaskError(
            f"{task_name}: VMVM cannot restore public networking after an isolated "
            "agent phase in a shared verifier environment"
        )
    return agent_mode, verifier_mode_resolved


def _parse_verifier_reward(
    task_name: str,
    kind: Literal["json", "text"],
    payload: bytes,
) -> tuple[float, dict[str, float]]:
    value = payload.decode().strip()
    if kind == "json":
        raw = json.loads(value)
        if not isinstance(raw, dict) or not raw:
            raise ValueError(f"{task_name}: reward.json must be a non-empty object")
        rewards = {str(key): float(item) for key, item in raw.items()}
    else:
        rewards = {"reward": float(value)}

    for key, reward_value in rewards.items():
        if not math.isfinite(reward_value):
            raise ValueError(f"{task_name}: reward value for {key!r} must be finite, got {reward_value!r}")
    if "reward" in rewards:
        score = rewards["reward"]
    elif len(rewards) == 1:
        score = next(iter(rewards.values()))
    else:
        raise ValueError(f"{task_name}: multi-key reward.json has no 'reward' key: {sorted(rewards)}")
    return score, rewards


def _artifact_specs(raw: list) -> list[ArtifactSpec]:
    specs = []
    for entry in raw:
        specs.append(ArtifactSpec(source=entry) if isinstance(entry, str) else ArtifactSpec(**entry))
    return specs


def _authors(task_config: dict, metadata: dict) -> list[Author]:
    declared = task_config.get("authors", [])
    if declared:
        return [Author(**author) for author in declared]
    names = metadata.get("author_name")
    emails = metadata.get("author_email")
    if names is None:
        return []
    names = names if isinstance(names, list) else [names]
    emails = emails if isinstance(emails, list) else [emails] * len(names)
    emails = [*emails, *([None] * max(0, len(names) - len(emails)))]
    return [
        Author(name=str(name), email=None if emails[index] is None else str(emails[index]))
        for index, name in enumerate(names)
    ]


def _base_task(task_dir: Path, idx: int, raw: dict, config: TerminalBenchVMVMConfig) -> HarborTask:
    task_config = raw.get("task", {})
    metadata = raw.get("metadata", {})
    environment = raw.get("environment", {})
    harness_timeout = raw.get("agent", {}).get("timeout_sec")
    scoring_timeout = raw.get("verifier", {}).get("timeout_sec")
    return HarborTask(
        idx=idx,
        name=task_config.get("name") or task_dir.name,
        description=task_config.get("description"),
        prompt=(task_dir / "instruction.md").read_text().strip(),
        image=None,
        timeout=TaskTimeout(
            harness=harness_timeout * config.timeout_multiplier if harness_timeout is not None else None,
            scoring=scoring_timeout * config.timeout_multiplier if scoring_timeout is not None else None,
        ),
        resources=parse_resources(environment, config.resource_multiplier),
        keywords=task_config.get("keywords", []),
        authors=_authors(task_config, metadata),
        difficulty=metadata.get("difficulty"),
        category=metadata.get("category"),
        tags=metadata.get("tags", []),
        task_dir=str(task_dir),
    )


@lru_cache(maxsize=1)
def _solution_tar(task_dir: str) -> bytes:
    solution = Path(task_dir) / "solution"
    if not solution.is_dir():
        raise FileNotFoundError(f"{solution}: no Harbor solution directory")
    return make_tar(solution)


class TerminalBenchVMVMTaskset(
    HarborTaskset,
    vf.Taskset[TerminalBenchTask, TerminalBenchVMVMConfig],
):
    NEEDS_CONTAINER = True

    def __init__(self, config: TerminalBenchVMVMConfig) -> None:
        super().__init__(config)
        self._artifact_payloads: dict[str, dict[str, bytes]] = {}
        self._prefetched_test_dependencies: WeakKeyDictionary[Runtime, PrefetchedTestDependencies] = WeakKeyDictionary()
        self._runtime_wheel_fingerprints: WeakKeyDictionary[Runtime, str] = WeakKeyDictionary()
        self._universal_wheelhouse_cache: dict[tuple[str, ...], PrefetchedTestDependencies] = {}
        self._compatible_wheelhouse_cache: dict[tuple[tuple[str, ...], str], PrefetchedTestDependencies] = {}
        self._nonuniversal_wheelhouse_requirements: set[tuple[str, ...]] = set()
        self._wheelhouse_discovery_flights: dict[tuple[str, ...], asyncio.Task[PrefetchedTestDependencies]] = {}
        self._wheelhouse_compatibility_flights: dict[
            tuple[tuple[str, ...], str], asyncio.Task[PrefetchedTestDependencies]
        ] = {}
        self._wheelhouse_flight_runtimes: dict[asyncio.Task[PrefetchedTestDependencies], Runtime] = {}
        self._wheelhouse_cache_lock = asyncio.Lock()
        self._wheelhouse_cache_directory: tempfile.TemporaryDirectory[str] | None = None
        self._wheelhouse_cache_closed = False

    def _wheelhouse_cache_path(self) -> Path:
        if self._wheelhouse_cache_closed:
            raise RuntimeError("verifier wheelhouse cache is closed")
        if self._wheelhouse_cache_directory is None:
            self._wheelhouse_cache_directory = tempfile.TemporaryDirectory(
                prefix="terminal-bench-verifier-wheelhouse-cache-"
            )
        return Path(self._wheelhouse_cache_directory.name)

    def _cleanup_wheelhouse_cache(self) -> None:
        self._prefetched_test_dependencies.clear()
        self._runtime_wheel_fingerprints.clear()
        self._universal_wheelhouse_cache.clear()
        self._compatible_wheelhouse_cache.clear()
        self._nonuniversal_wheelhouse_requirements.clear()
        self._wheelhouse_discovery_flights.clear()
        self._wheelhouse_compatibility_flights.clear()
        self._wheelhouse_flight_runtimes.clear()
        directory = self._wheelhouse_cache_directory
        self._wheelhouse_cache_directory = None
        if directory is not None:
            directory.cleanup()

    async def cleanup(self, task: TerminalBenchTask, trace: vf.Trace | None, runtime: Runtime) -> None:
        """Detach per-rollout state and quiesce cache work owned by this runtime."""
        async with self._wheelhouse_cache_lock:
            flights = [flight for flight, owner in self._wheelhouse_flight_runtimes.items() if owner is runtime]
        for flight in flights:
            flight.cancel()
        try:
            if flights:
                await asyncio.gather(*flights, return_exceptions=True)
        finally:
            self._prefetched_test_dependencies.pop(runtime, None)
            self._runtime_wheel_fingerprints.pop(runtime, None)
            if trace is not None:
                self._artifact_payloads.pop(trace.id, None)

    async def close(self) -> None:
        """Cancel cache builders and deterministically release the shared cache."""
        async with self._wheelhouse_cache_lock:
            self._wheelhouse_cache_closed = True
            flights = set(self._wheelhouse_discovery_flights.values())
            flights.update(self._wheelhouse_compatibility_flights.values())
        for flight in flights:
            flight.cancel()
        if flights:
            await asyncio.gather(*flights, return_exceptions=True)
        await asyncio.to_thread(self._cleanup_wheelhouse_cache)

    def _validate_dataset_revision(self, root: Path) -> None:
        expected = self.config.dataset_revision
        if expected is None:
            return
        try:
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f"cannot verify Harbor dataset revision at {root}") from error
        if head != expected:
            raise ValueError(f"Harbor dataset revision mismatch: expected {expected}, observed {head or '<empty>'}")
        if status.strip():
            raise ValueError(f"Harbor dataset worktree is not clean: {root}")

    @staticmethod
    def _validate_input_sha256(
        path: Path | None,
        expected: str | None,
        field: str,
    ) -> None:
        if expected is None:
            return
        if path is None:
            raise ValueError(f"{field}_sha256 requires {field}")
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise ValueError(f"cannot verify {field} SHA-256: {path}") from error
        observed = digest.hexdigest()
        if observed != expected:
            raise ValueError(f"{field} SHA-256 mismatch: expected {expected}, observed {observed}")

    def load_tasks(self) -> list[TerminalBenchTask]:
        root = self.config.dataset_dir.resolve()
        if not root.is_dir():
            raise ValueError(f"Harbor dataset directory does not exist: {root}")
        self._validate_dataset_revision(root)
        self._validate_input_sha256(
            self.config.task_file,
            self.config.task_file_sha256,
            "task_file",
        )
        self._validate_input_sha256(
            self.config.image_manifest,
            self.config.image_manifest_sha256,
            "image_manifest",
        )
        requested = set(self.config.tasks or [])
        if self.config.task_file is not None:
            requested.update(
                line.strip().split("\t", 1)[0]
                for line in self.config.task_file.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
        task_filter = requested or None
        task_dirs = [
            path
            for path in sorted(root.iterdir())
            if path.is_dir()
            and (path / "task.toml").is_file()
            and (path / "instruction.md").is_file()
            and (task_filter is None or path.name in task_filter)
        ]
        if not task_dirs:
            raise ValueError(f"no immediate-child Harbor tasks found in {root}")
        if task_filter is not None:
            found = {path.name for path in task_dirs}
            if missing := sorted(task_filter - found):
                raise ValueError(f"requested Harbor tasks not found in {root}: {missing[:20]}")

        image_manifest = _load_image_manifest(self.config.image_manifest)
        tasks: list[TerminalBenchTask] = []
        for idx, task_dir in enumerate(task_dirs):
            raw = tomllib.loads((task_dir / "task.toml").read_text())
            parsed = _base_task(task_dir, idx, raw, self.config)
            environment = raw.get("environment", {})
            verifier = raw.get("verifier", {})
            verifier_environment = verifier.get("environment") or environment
            mode = verifier.get("environment_mode")
            if mode is None:
                mode = "separate" if verifier.get("environment") is not None else "shared"
            if mode not in ("shared", "separate"):
                raise ValueError(f"{task_dir.name}: unknown verifier environment_mode {mode!r}")
            agent_network_mode, verifier_network_mode = _network_modes(
                task_dir.name,
                raw,
                mode,
            )

            agent_dockerfile = task_dir / "environment" / "Dockerfile"
            tests_dockerfile = task_dir / "tests" / "Dockerfile"
            declared_agent = environment.get("docker_image")
            manifested = image_manifest.get(task_dir.name, {})
            if image_manifest and "agent" not in manifested:
                raise ValueError(f"{task_dir.name}: missing agent image in {self.config.image_manifest}")
            image = manifested.get("agent")
            if image is None:
                image = (
                    declared_agent
                    if self.config.use_declared_images and declared_agent
                    else _image_ref(self.config.image_prefix, task_dir.name, self.config.image_tag)
                )
            if image_manifest and "@sha256:" not in image:
                raise ValueError(f"{task_dir.name}: manifest agent image is not digest-pinned: {image}")

            verifier_image = None
            verifier_workdir = "/app"
            verifier_tests_baked = False
            if mode == "separate":
                declared_verifier = verifier_environment.get("docker_image")
                verifier_tests_baked = tests_dockerfile.is_file()
                if manifested.get("verifier"):
                    verifier_image = manifested["verifier"]
                elif self.config.use_declared_images and declared_verifier:
                    verifier_image = declared_verifier
                elif verifier_tests_baked:
                    verifier_image = _image_ref(
                        self.config.image_prefix,
                        task_dir.name,
                        self.config.image_tag,
                        self.config.verifier_image_suffix,
                    )
                else:
                    verifier_image = image
                verifier_workdir = _environment_workdir(tests_dockerfile if verifier_tests_baked else agent_dockerfile)

            task_data = parsed.model_dump()
            task_data.update(
                task_dir=str(task_dir),
                slug=task_dir.name,
                image=image,
                workdir=_environment_workdir(agent_dockerfile),
                verifier_mode=mode,
                verifier_image=verifier_image,
                verifier_workdir=verifier_workdir,
                verifier_resources=parse_resources(
                    verifier_environment,
                    self.config.resource_multiplier,
                ),
                verifier_timeout_sec=float(verifier.get("timeout_sec", 600.0)) * self.config.timeout_multiplier,
                verifier_env=_string_env(verifier.get("env")),
                solution_env=_string_env(raw.get("solution", {}).get("env")),
                artifacts=_artifact_specs(raw.get("artifacts", [])),
                collect_hooks=[CollectHook(**hook) for hook in verifier.get("collect", [])],
                verifier_tests_baked=verifier_tests_baked,
                agent_network_mode=agent_network_mode,
                verifier_network_mode=verifier_network_mode,
            )
            tasks.append(TerminalBenchTask(**task_data))
        return tasks

    @staticmethod
    async def _configure_network_policy(
        task: TerminalBenchTask,
        runtime: Runtime,
        mode: Literal["public", "no-network"],
        *,
        activate: bool,
    ) -> None:
        if not isinstance(runtime, VMVMRuntime):
            if mode == "no-network":
                raise UnsupportedTaskError(f"{task.name}: network_mode='no-network' requires VMVMRuntime")
            return
        await runtime.configure_network_policy(mode)
        if activate:
            await runtime.activate_network_policy()

    async def setup(self, task: TerminalBenchTask, runtime: Runtime) -> None:
        # Model rollouts always use the task's declared network policy.  The
        # oracle compatibility option is intentionally invisible here.
        await self._setup(task, runtime, oracle_solution_network_mode="declared")

    async def setup_oracle(self, task: TerminalBenchTask, runtime: Runtime) -> None:
        """Prepare a trusted reference run without changing model setup semantics."""
        await self._setup(
            task,
            runtime,
            oracle_solution_network_mode=self.config.oracle_solution_network_mode,
        )

    async def _setup(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        *,
        oracle_solution_network_mode: Literal["declared", "public"],
    ) -> None:
        if isinstance(runtime, VMVMRuntime) and task.resources.gpu:
            raise UnsupportedTaskError(f"{task.name}: requests GPU resources, but the current VMVM tenant is CPU-only")
        compose_started = False
        if self.config.enable_compose:
            compose_path = _compose_path(Path(task.task_dir))
            if compose_path is not None:
                if not isinstance(runtime, VMVMRuntime):
                    raise UnsupportedTaskError(f"{task.name}: Docker Compose currently requires VMVMRuntime")
                try:
                    runtime._descriptor = await asyncio.to_thread(
                        runtime.backend.start_compose,
                        compose_path.read_bytes(),
                    )
                    compose_started = True
                except Exception as error:
                    raise SandboxError(f"VMVM compose provisioning failed: {error}") from error

        await self._configure_network_policy(
            task,
            runtime,
            task.agent_network_mode,
            activate=False,
        )

        # Some upstream task archives contain macOS AppleDouble resource forks.
        # They are packaging metadata, not benchmark inputs, and can break scripts
        # that enumerate source files by extension.
        cleaned = await self._run_root(
            runtime,
            f"find {shlex.quote(task.workdir or '/app')} -type f -name '._*' -delete; "
            "if test -d /etc/postgresql; then "
            "find /etc/postgresql -type f -name pg_hba.conf -exec chmod a+r {} +; "
            "fi",
        )
        if cleaned.exit_code != 0:
            raise RuntimeError(f"{task.name}: AppleDouble cleanup failed: {(cleaned.stdout + cleaned.stderr)[-2000:]}")

        if task.verifier_mode == "shared" and task.verifier_network_mode == "no-network":
            await self._prefetch_test_dependencies(task, runtime)

        if not compose_started:
            startup = _dockerfile_startup_command(task.task_dir)
            if startup:
                startup_log = "/tmp/terminal-bench-image-startup.log"
                startup_argv = [
                    "sh",
                    "-c",
                    f"nohup {shlex.join(startup)} >{startup_log} 2>&1 </dev/null &",
                ]
                if task.agent_network_mode == "no-network" and oracle_solution_network_mode != "public":
                    if not isinstance(runtime, VMVMRuntime):
                        raise UnsupportedTaskError(f"{task.name}: deferred no-network startup requires VMVMRuntime")
                    runtime.defer_until_network_isolated(startup_argv)
                    launched = ProgramResult(exit_code=0, stdout="", stderr="")
                else:
                    launched = await runtime.run(startup_argv, {})
                if launched.exit_code != 0:
                    raise RuntimeError(
                        f"{task.name}: image startup command failed: {(launched.stdout + launched.stderr)[-2000:]}"
                    )

    @staticmethod
    async def _run_service(
        runtime: Runtime,
        service: str,
        argv: list[str],
        env: dict[str, str],
        *,
        user: str | int | None = None,
    ) -> ProgramResult:
        if service in ("", "main"):
            return await runtime.run(argv, env)
        if not isinstance(runtime, VMVMRuntime):
            raise UnsupportedTaskError(f"service {service!r} requires a compose-capable VMVMRuntime")
        command = shlex.join(argv)
        try:
            result = await asyncio.to_thread(
                runtime.backend.run_service_bash,
                service,
                command,
                runtime.config.session_timeout,
                env,
                user,
            )
        except Exception as error:
            raise SandboxError(f"VMVM service exec failed: {error}") from error
        if result["exit_code"] < 0:
            raise SandboxError(f"VMVM service exec failed ({result['error_type']}): {result['output']}")
        return ProgramResult(exit_code=result["exit_code"], stdout=result["output"], stderr="")

    @staticmethod
    async def _read_service(runtime: Runtime, service: str, path: str) -> bytes:
        if service in ("", "main"):
            return await runtime.read(path)
        if not isinstance(runtime, VMVMRuntime):
            raise UnsupportedTaskError(f"service {service!r} requires a compose-capable VMVMRuntime")
        try:
            return await asyncio.to_thread(
                runtime.backend.read_service_file,
                service,
                path,
            )
        except Exception as error:
            raise SandboxError(f"read {path!r} from service {service!r}: {error}") from error

    @staticmethod
    async def _run_root(runtime: Runtime, command: str) -> ProgramResult:
        """Run harness-owned setup as root without changing the agent user."""
        if not isinstance(runtime, VMVMRuntime):
            return await runtime.run(["sh", "-c", command], {})
        try:
            result = await asyncio.to_thread(
                runtime.backend.run_root_bash,
                command,
                runtime.config.session_timeout,
            )
        except Exception as error:
            raise SandboxError(f"VMVM root command failed: {error}") from error
        if result["exit_code"] < 0:
            raise SandboxError(f"VMVM root command failed ({result['error_type']}): {result['output']}")
        return ProgramResult(
            exit_code=result["exit_code"],
            stdout=result["output"],
            stderr="",
        )

    async def _stage_directory(self, runtime: Runtime, source: Path, target: str, label: str) -> None:
        if not source.is_dir():
            raise FileNotFoundError(f"missing {label} directory: {source}")
        archive = make_tar(source)
        archive_path = f"/tmp/terminal-bench-{label}.tgz"
        await runtime.write(archive_path, archive)
        command = (
            f"rm -rf {shlex.quote(target)} && mkdir -p {shlex.quote(target)} "
            f"&& tar -xzf {shlex.quote(archive_path)} -C {shlex.quote(target)} "
            f"&& find {shlex.quote(target)} -type f -name '._*' -delete "
            f"&& chmod -R a+rX {shlex.quote(target)}"
        )
        result = await self._run_root(runtime, command)
        if result.exit_code != 0:
            raise RuntimeError(f"staging {label} failed: {(result.stdout + result.stderr)[-4000:]}")

    async def _run_collect_hooks(self, task: TerminalBenchTask, runtime: Runtime) -> list[dict]:
        outcomes = []
        for hook in task.collect_hooks:
            seconds = f"{hook.timeout_sec:g}s"
            # Sidecars are frequently Alpine/BusyBox images. Use timeout's
            # portable short options rather than GNU-only long spellings.
            command = f"timeout -s TERM -k 10s {seconds} sh -c {shlex.quote(hook.command)}"
            result = None
            attempts = self.config.verifier_runtime_retries + 1
            for attempt in range(1, attempts + 1):
                result = await self._run_service(
                    runtime,
                    hook.service,
                    ["sh", "-c", command],
                    {},
                    user=hook.user,
                )
                if result.exit_code == 0:
                    break
                output_tail = (result.stdout + result.stderr)[-2000:]
                logger.warning(
                    "%s collect hook for %s exited %s on attempt %s/%s: %s",
                    task.name,
                    hook.service,
                    result.exit_code,
                    attempt,
                    attempts,
                    output_tail,
                )
                if attempt < attempts:
                    await asyncio.sleep(min(8.0, 2.0**attempt))
            assert result is not None
            outcomes.append(
                {
                    "service": hook.service,
                    "attempts": attempt,
                    "exit_code": result.exit_code,
                    "output_tail": (result.stdout + result.stderr)[-2000:],
                }
            )
        return outcomes

    @staticmethod
    def _runtime_artifact_path(task: TerminalBenchTask, source: str) -> str:
        path = PurePosixPath(source)
        if ".." in path.parts:
            raise ValueError(f"{task.name}: artifact source contains '..': {source!r}")
        if not path.is_absolute():
            path = PurePosixPath(task.workdir or "/app") / path
        return str(path)

    async def _capture_artifacts(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
    ) -> tuple[dict[str, bytes], dict]:
        collect = await self._run_collect_hooks(task, runtime)
        specs = list(task.artifacts)
        if self.config.capture_convention_artifacts:
            specs.append(ArtifactSpec(source="/logs/artifacts", service="main"))

        paths: dict[str, list[str]] = {}
        excludes: dict[str, list[str]] = {}
        missing: list[dict[str, str]] = []
        for spec in specs:
            service = spec.service or "main"
            source = self._runtime_artifact_path(task, spec.source)
            exists = await self._run_service(
                runtime,
                service,
                ["sh", "-c", f"test -e {shlex.quote(source)}"],
                {},
            )
            if exists.exit_code == 0:
                paths.setdefault(service, []).append(source)
                excludes.setdefault(service, []).extend(spec.exclude)
            else:
                missing.append({"service": service, "source": spec.source})

        payloads: dict[str, bytes] = {}
        for service, service_paths in sorted(paths.items()):
            suffix = hashlib.sha256(service.encode()).hexdigest()[:12]
            archive_path = f"/tmp/terminal-bench-artifacts-{suffix}.tgz"
            tar_args = ["tar", "-czf", archive_path]
            for pattern in excludes.get(service, []):
                tar_args.append(f"--exclude={pattern}")
            tar_args.extend(["-C", "/", "--", *(path.lstrip("/") for path in service_paths)])
            captured = await self._run_service(runtime, service, tar_args, {})
            if captured.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: artifact capture from {service!r} failed: "
                    f"{(captured.stdout + captured.stderr)[-4000:]}"
                )
            payloads[service] = await self._read_service(runtime, service, archive_path)
        if not payloads:
            # A valid empty gzip tar, generated in the runtime to keep tar behavior uniform.
            archive_path = "/tmp/terminal-bench-artifacts-empty.tgz"
            captured = await runtime.run(
                ["sh", "-c", f"tar -czf {archive_path} --files-from=/dev/null"],
                {},
            )
            if captured.exit_code != 0:
                raise RuntimeError(f"{task.name}: creating empty artifact archive failed")
            payloads["main"] = await runtime.read(archive_path)

        digest = hashlib.sha256()
        for service, payload in sorted(payloads.items()):
            digest.update(service.encode())
            digest.update(b"\0")
            digest.update(payload)
        metadata = {
            "bytes": sum(len(payload) for payload in payloads.values()),
            "sha256": digest.hexdigest(),
            "captured": paths,
            "missing": missing,
            "collect": collect,
        }
        return payloads, metadata

    async def finalize(self, task: TerminalBenchTask, trace: vf.Trace, runtime: Runtime) -> None:
        if task.verifier_mode != "separate":
            return
        payload, metadata = await self._capture_artifacts(task, runtime)
        self._artifact_payloads[trace.id] = payload
        trace.info["terminal_bench_artifacts"] = metadata

    @staticmethod
    def _test_requirements(task: TerminalBenchTask) -> tuple[str, ...]:
        test_script = (Path(task.task_dir) / "tests" / "test.sh").read_text(errors="replace")
        requirements = _merge_test_requirements(
            _declared_test_requirements(task.task_dir),
            _test_script_requirements(task.task_dir),
        )
        if "pytest" in test_script and not any(
            _requirement_name(requirement) == "pytest" for requirement in requirements
        ):
            requirements = (*requirements, "pytest==8.3.4")
        return requirements

    async def _missing_test_dependencies(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        if requirements is None:
            requirements = self._test_requirements(task)
        if not requirements:
            return ()
        probe_code = """
import importlib.metadata as metadata
import re
import sys

for requirement in sys.argv[1:]:
    name = re.split(r"[<>=!~;\\[]", requirement, maxsplit=1)[0]
    expected = requirement.split("==", 1)[1] if "==" in requirement else None
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        print(requirement)
    else:
        if expected is not None and installed != expected:
            print(requirement)
""".strip()
        # Distribution names are not always import names (for example,
        # psycopg2-binary), so probe package metadata rather than imports.
        available = await runtime.run(
            ["python3", "-c", probe_code, *requirements],
            {},
        )
        if available.exit_code != 0:
            return requirements
        declared = set(requirements)
        missing = tuple(line for line in available.stdout.splitlines() if line in declared)
        unexpected = [line for line in available.stdout.splitlines() if line and line not in declared]
        if unexpected:
            raise RuntimeError(f"{task.name}: dependency probe returned unexpected values: {unexpected}")
        return missing

    async def _ensure_test_dependencies(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
    ) -> None:
        missing = await self._missing_test_dependencies(task, runtime)
        if not missing:
            return
        command = (
            "python3 -m pip install -q --ignore-installed "
            "--break-system-packages "
            f"{shlex.join(missing)} || "
            "python3 -m pip install -q --ignore-installed "
            f"{shlex.join(missing)}"
        )
        installed = await runtime.run(["sh", "-c", command], {})
        if installed.exit_code != 0:
            raise RuntimeError(
                f"{task.name}: verifier dependency bootstrap failed for "
                f"{missing}: {(installed.stdout + installed.stderr)[-4000:]}"
            )

    async def _runtime_wheel_fingerprint(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
    ) -> str:
        cached = self._runtime_wheel_fingerprints.get(runtime)
        if cached is not None:
            return cached
        image = getattr(getattr(runtime, "config", None), "image", None)
        if not isinstance(image, str) or not image:
            raise RuntimeError(f"{task.name}: verifier wheel caching requires an exact runtime image reference")
        probe_code = (
            "import json, platform, sys, sysconfig; "
            "print(json.dumps([sys.implementation.name, list(sys.version_info[:2]), "
            "sysconfig.get_config_var('SOABI'), sysconfig.get_platform(), platform.machine()], "
            "separators=(',', ':')))"
        )
        probed = await runtime.run(["python3", "-c", probe_code], {})
        if probed.exit_code != 0 or not probed.stdout.strip():
            raise RuntimeError(
                f"{task.name}: verifier wheel compatibility probe failed: {(probed.stdout + probed.stderr)[-2000:]}"
            )
        try:
            compatibility = json.loads(probed.stdout.strip())
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{task.name}: verifier wheel compatibility probe returned invalid JSON") from error
        if not isinstance(compatibility, list) or len(compatibility) != 5:
            raise RuntimeError(f"{task.name}: verifier wheel compatibility probe returned an invalid fingerprint")
        fingerprint = hashlib.sha256(
            json.dumps([image, compatibility], separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        self._runtime_wheel_fingerprints[runtime] = fingerprint
        return fingerprint

    async def _build_test_dependency_wheelhouse(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...],
        compatibility_fingerprint: str,
    ) -> PrefetchedTestDependencies:
        digest = hashlib.sha256("\0".join(requirements).encode()).hexdigest()[:16]
        wheel_dir = f"/tmp/terminal-bench-verifier-wheels-{digest}-{uuid.uuid4().hex[:12]}"
        archive_path = f"{wheel_dir}.tar"
        try:
            prepared = await self._run_root(
                runtime,
                f"rm -rf {shlex.quote(wheel_dir)} {shlex.quote(archive_path)} && "
                f"mkdir -p {shlex.quote(wheel_dir)} && chmod 1777 {shlex.quote(wheel_dir)}",
            )
            if prepared.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: preparing verifier wheelhouse failed: {(prepared.stdout + prepared.stderr)[-4000:]}"
                )

            # Resolve only published wheels. Building an sdist would execute
            # package-controlled build hooks during trusted setup, which is not
            # a non-mutating prefetch even when pip uses build isolation.
            built = await runtime.run(
                [
                    "python3",
                    "-m",
                    "pip",
                    "wheel",
                    "--quiet",
                    "--no-cache-dir",
                    "--only-binary=:all:",
                    "--wheel-dir",
                    wheel_dir,
                    *requirements,
                ],
                {},
            )
            if built.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: verifier wheel prefetch failed for {requirements}: "
                    f"{(built.stdout + built.stderr)[-4000:]}"
                )
            archived = await self._run_root(
                runtime,
                f'test "$(find {shlex.quote(wheel_dir)} -maxdepth 1 -type f '
                "-name '*.whl' | wc -l)\" -gt 0 && "
                f'test -z "$(find {shlex.quote(wheel_dir)} -mindepth 1 -maxdepth 1 '
                "! -type f -o -type f ! -name '*.whl')\" && "
                f"tar -C {shlex.quote(wheel_dir)} -cf {shlex.quote(archive_path)} .",
            )
            if archived.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: verifier wheelhouse was empty or contained "
                    f"non-wheel artifacts: {(archived.stdout + archived.stderr)[-4000:]}"
                )
            wheel_archive = await runtime.read(archive_path)
            if not wheel_archive:
                raise RuntimeError(f"{task.name}: verifier wheelhouse archive was empty")
        finally:
            cleaned = await self._run_root(
                runtime,
                f"rm -rf {shlex.quote(wheel_dir)} {shlex.quote(archive_path)}",
            )
            if cleaned.exit_code != 0:
                logger.warning(
                    "%s verifier wheelhouse cleanup failed: %s",
                    task.name,
                    (cleaned.stdout + cleaned.stderr)[-2000:],
                )

        return await asyncio.to_thread(
            PrefetchedTestDependencies.store,
            self._wheelhouse_cache_path(),
            requirements,
            wheel_archive,
            compatibility_fingerprint,
        )

    @staticmethod
    def _consume_wheelhouse_flight_result(task: asyncio.Task[PrefetchedTestDependencies]) -> None:
        if not task.cancelled():
            task.exception()

    async def _publish_discovered_wheelhouse(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...],
    ) -> PrefetchedTestDependencies:
        try:
            fingerprint = await self._runtime_wheel_fingerprint(task, runtime)
            wheelhouse = await self._build_test_dependency_wheelhouse(
                task,
                runtime,
                requirements,
                fingerprint,
            )
            async with self._wheelhouse_cache_lock:
                if wheelhouse.universal:
                    self._universal_wheelhouse_cache[requirements] = wheelhouse
                else:
                    self._nonuniversal_wheelhouse_requirements.add(requirements)
                    self._compatible_wheelhouse_cache[(requirements, fingerprint)] = wheelhouse
            return wheelhouse
        finally:
            current = asyncio.current_task()
            async with self._wheelhouse_cache_lock:
                if self._wheelhouse_discovery_flights.get(requirements) is current:
                    self._wheelhouse_discovery_flights.pop(requirements, None)
                if current is not None:
                    self._wheelhouse_flight_runtimes.pop(current, None)

    async def _publish_compatible_wheelhouse(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...],
        compatibility_fingerprint: str,
    ) -> PrefetchedTestDependencies:
        key = (requirements, compatibility_fingerprint)
        try:
            wheelhouse = await self._build_test_dependency_wheelhouse(
                task,
                runtime,
                requirements,
                compatibility_fingerprint,
            )
            async with self._wheelhouse_cache_lock:
                if wheelhouse.universal:
                    self._universal_wheelhouse_cache[requirements] = wheelhouse
                else:
                    self._nonuniversal_wheelhouse_requirements.add(requirements)
                    self._compatible_wheelhouse_cache[key] = wheelhouse
            return wheelhouse
        finally:
            current = asyncio.current_task()
            async with self._wheelhouse_cache_lock:
                if self._wheelhouse_compatibility_flights.get(key) is current:
                    self._wheelhouse_compatibility_flights.pop(key, None)
                if current is not None:
                    self._wheelhouse_flight_runtimes.pop(current, None)

    async def _verified_wheelhouse(
        self,
        task: TerminalBenchTask,
        wheelhouse: PrefetchedTestDependencies,
    ) -> PrefetchedTestDependencies:
        try:
            await asyncio.to_thread(wheelhouse.verify)
        except RuntimeError as error:
            raise RuntimeError(f"{task.name}: {error}") from error
        return wheelhouse

    async def _compatible_wheelhouse(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...],
        compatibility_fingerprint: str | None = None,
    ) -> PrefetchedTestDependencies:
        fingerprint = compatibility_fingerprint or await self._runtime_wheel_fingerprint(task, runtime)
        key = (requirements, fingerprint)
        async with self._wheelhouse_cache_lock:
            if self._wheelhouse_cache_closed:
                raise RuntimeError(f"{task.name}: verifier wheelhouse cache is closed")
            cached = self._universal_wheelhouse_cache.get(requirements)
            if cached is None:
                cached = self._compatible_wheelhouse_cache.get(key)
            flight = self._wheelhouse_compatibility_flights.get(key)
            if cached is None and flight is None:
                flight = asyncio.create_task(
                    self._publish_compatible_wheelhouse(
                        task,
                        runtime,
                        requirements,
                        fingerprint,
                    )
                )
                flight.add_done_callback(self._consume_wheelhouse_flight_result)
                self._wheelhouse_compatibility_flights[key] = flight
                self._wheelhouse_flight_runtimes[flight] = runtime
        if cached is not None:
            return await self._verified_wheelhouse(task, cached)
        assert flight is not None
        try:
            return await asyncio.shield(flight)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return await self._compatible_wheelhouse(task, runtime, requirements, fingerprint)

    async def _cached_test_dependency_wheelhouse(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        requirements: tuple[str, ...],
    ) -> PrefetchedTestDependencies:
        async with self._wheelhouse_cache_lock:
            if self._wheelhouse_cache_closed:
                raise RuntimeError(f"{task.name}: verifier wheelhouse cache is closed")
            cached = self._universal_wheelhouse_cache.get(requirements)
            flight = self._wheelhouse_discovery_flights.get(requirements)
            has_nonuniversal = requirements in self._nonuniversal_wheelhouse_requirements
            if cached is None and flight is None and not has_nonuniversal:
                flight = asyncio.create_task(self._publish_discovered_wheelhouse(task, runtime, requirements))
                flight.add_done_callback(self._consume_wheelhouse_flight_result)
                self._wheelhouse_discovery_flights[requirements] = flight
                self._wheelhouse_flight_runtimes[flight] = runtime
        if cached is not None:
            return await self._verified_wheelhouse(task, cached)
        if has_nonuniversal and flight is None:
            return await self._compatible_wheelhouse(task, runtime, requirements)
        assert flight is not None
        try:
            discovered = await asyncio.shield(flight)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return await self._cached_test_dependency_wheelhouse(task, runtime, requirements)
        if discovered.universal:
            return discovered
        fingerprint = await self._runtime_wheel_fingerprint(task, runtime)
        if discovered.compatibility_fingerprint == fingerprint:
            return discovered
        return await self._compatible_wheelhouse(
            task,
            runtime,
            requirements,
            fingerprint,
        )

    async def _prefetch_test_dependencies(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
    ) -> None:
        """Cache a complete wheelhouse without mutating the task environment."""
        self._prefetched_test_dependencies.pop(runtime, None)
        declared = _declared_test_requirements(task.task_dir)
        scripted = _test_script_requirements(task.task_dir)
        merged = _merge_test_requirements(declared, scripted)
        declared_names = {_requirement_name(requirement) for requirement in declared}
        scripted_extras = tuple(
            requirement for requirement in scripted if _requirement_name(requirement) not in declared_names
        )
        missing_scripted = await self._missing_test_dependencies(task, runtime, scripted_extras)
        requirements = _merge_test_requirements(declared, missing_scripted)
        if "pytest" in (Path(task.task_dir) / "tests" / "test.sh").read_text(errors="replace") and not any(
            _requirement_name(requirement) == "pytest" for requirement in merged
        ):
            requirements = _merge_test_requirements(requirements, ("pytest==8.3.4",))
        if not requirements:
            self._prefetched_test_dependencies[runtime] = PrefetchedTestDependencies(
                requirements=(),
                archive_path=None,
                sha256=None,
                universal=True,
                compatibility_fingerprint=None,
            )
            return
        self._prefetched_test_dependencies[runtime] = await self._cached_test_dependency_wheelhouse(
            task,
            runtime,
            requirements,
        )

    async def _install_prefetched_test_dependencies(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
    ) -> None:
        prefetched = self._prefetched_test_dependencies.pop(runtime, None)
        if prefetched is None:
            raise RuntimeError(f"{task.name}: isolated verifier dependencies were not prefetched")
        if not prefetched.requirements:
            return
        try:
            try:
                await asyncio.to_thread(prefetched.verify)
            except RuntimeError as error:
                raise RuntimeError(f"{task.name}: {error}") from error

            # Probe after the solution/agent so dependency changes made there
            # remain observable, matching the historical verifier ordering.
            missing = await self._missing_test_dependencies(
                task,
                runtime,
                prefetched.requirements,
            )
            if not missing:
                return

            try:
                wheel_archive = await asyncio.to_thread(prefetched.read_verified)
            except RuntimeError as error:
                raise RuntimeError(f"{task.name}: {error}") from error

            nonce = uuid.uuid4().hex[:16]
            archive_path = f"/tmp/terminal-bench-verifier-wheels-{nonce}.tar"
            wheel_dir = f"/tmp/terminal-bench-verifier-wheels-{nonce}"
            await runtime.write(archive_path, wheel_archive)
            prepared = await self._run_root(
                runtime,
                f"rm -rf {shlex.quote(wheel_dir)} && mkdir -p {shlex.quote(wheel_dir)} && "
                f"tar -xf {shlex.quote(archive_path)} -C {shlex.quote(wheel_dir)} && "
                f'test "$(find {shlex.quote(wheel_dir)} -maxdepth 1 -type f '
                "-name '*.whl' | wc -l)\" -gt 0 && "
                f'test -z "$(find {shlex.quote(wheel_dir)} -mindepth 1 -maxdepth 1 '
                "! -type f -o -type f ! -name '*.whl')\"",
            )
            if prepared.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: restoring verifier wheelhouse failed: {(prepared.stdout + prepared.stderr)[-4000:]}"
                )
            install_command = (
                "if python3 -m pip install --help 2>/dev/null | "
                "grep -q -- --break-system-packages; then "
                "break_system=--break-system-packages; else break_system=; fi; "
                f"PIP_NO_INDEX=1 python3 -m pip install -q --no-cache-dir "
                f"--no-index --find-links {shlex.quote(wheel_dir)} "
                f"$break_system {shlex.join(missing)}"
            )
            installed = await self._run_root(runtime, install_command)
            if installed.exit_code != 0:
                raise RuntimeError(
                    f"{task.name}: offline verifier dependency install failed for "
                    f"{missing}: "
                    f"{(installed.stdout + installed.stderr)[-4000:]}"
                )
            remaining = await self._missing_test_dependencies(
                task,
                runtime,
                missing,
            )
            if remaining:
                raise RuntimeError(
                    f"{task.name}: offline verifier dependency install left requirements unsatisfied: {remaining}"
                )
        finally:
            if "wheel_dir" in locals() and "archive_path" in locals():
                cleaned = await self._run_root(
                    runtime,
                    f"rm -rf {shlex.quote(wheel_dir)} {shlex.quote(archive_path)}",
                )
                if cleaned.exit_code != 0:
                    logger.warning(
                        "%s restored verifier wheelhouse cleanup failed: %s",
                        task.name,
                        (cleaned.stdout + cleaned.stderr)[-2000:],
                    )

    async def _run_verifier(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        *,
        stage_tests: bool,
    ) -> tuple[ProgramResult, bool, float, dict[str, float]]:
        isolated_staged_tests = stage_tests and task.verifier_network_mode == "no-network"
        if isolated_staged_tests and runtime not in self._prefetched_test_dependencies:
            raise RuntimeError(
                f"{task.name}: isolated verifier dependencies were not prefetched before the untrusted phase"
            )
        if task.verifier_network_mode == "no-network":
            await self._configure_network_policy(
                task,
                runtime,
                task.verifier_network_mode,
                activate=True,
            )
        if stage_tests:
            await self._stage_directory(runtime, Path(task.task_dir) / "tests", "/tests", "tests")
        prepared = await self._run_root(
            runtime,
            f"mkdir -p /logs/verifier; chmod 1777 /logs/verifier; chmod a+rwx {shlex.quote(task.verifier_workdir)}",
        )
        if prepared.exit_code != 0:
            raise RuntimeError(
                f"{task.name}: preparing verifier paths failed: {(prepared.stdout + prepared.stderr)[-4000:]}"
            )
        # Official separate-verifier images own their sealed test dependencies.
        # Only shared-mode/staged tests need repair for the older Mobius image set.
        if stage_tests:
            if isolated_staged_tests:
                await self._install_prefetched_test_dependencies(task, runtime)
            else:
                await self._ensure_test_dependencies(task, runtime)
        if task.verifier_network_mode == "public":
            await self._configure_network_policy(
                task,
                runtime,
                task.verifier_network_mode,
                activate=True,
            )
        timeout = f"{task.verifier_timeout_sec:g}s"
        command = (
            "mkdir -p /logs/verifier; "
            "rm -f /logs/verifier/reward.txt /logs/verifier/reward.json; "
            "set +e; "
            f"timeout --signal=TERM --kill-after=30s {timeout} sh -c "
            f"{shlex.quote('cd /tests && bash test.sh')}; "
            "status=$?; "
            f'if [ "$status" -eq 124 ]; then printf "\\n{VERIFIER_TIMEOUT_MARKER}\\n"; fi; '
            'exit "$status"'
        )
        verifier_env = dict(task.verifier_env)
        if not stage_tests:
            # TB4's sealed verifier images are self-contained and frequently
            # alias local helper services in /etc/hosts after the shell starts.
            # A static proxy bypass list cannot see those late aliases, while
            # Chromium and other subprocesses inherit the bridge proxy and send
            # the local request off-VM. Keep the proxy variables available, but
            # bypass them for all verifier traffic in these offline images.
            verifier_env.setdefault("no_proxy", "*")
            verifier_env.setdefault("NO_PROXY", "*")
        result = await runtime.run(["sh", "-c", command], verifier_env)
        output = result.stdout + result.stderr
        timed_out = VERIFIER_TIMEOUT_MARKER in output
        if timed_out:
            return result, True, 0.0, {"reward": 0.0}

        present = await runtime.run(
            [
                "sh",
                "-c",
                "if test -s /logs/verifier/reward.json; then printf json; "
                "elif test -s /logs/verifier/reward.txt; then printf text; else exit 2; fi",
            ],
            {},
        )
        if present.exit_code != 0:
            raise RuntimeError(f"{task.name}: verifier wrote no non-empty reward file; output: {output[-4000:]}")
        kind = present.stdout.strip().splitlines()[-1]
        if kind == "json":
            payload = await runtime.read("/logs/verifier/reward.json")
        else:
            payload = await runtime.read("/logs/verifier/reward.txt")
        score, rewards = _parse_verifier_reward(task.name, kind, payload)
        return result, False, score, rewards

    @staticmethod
    def _verifier_runtime(task: TerminalBenchTask, runtime: Runtime, name: str) -> Runtime:
        if not isinstance(runtime, VMVMRuntime):
            raise RuntimeError("separate Terminal-Bench verification currently requires VMVMRuntime")
        updates = {
            "image": task.verifier_image,
            "workdir": task.verifier_workdir,
        }
        for field, value in task.verifier_resources.model_dump(exclude_none=True).items():
            if field in type(runtime.config).model_fields:
                updates[field] = value
        return make_runtime(runtime.config.model_copy(update=updates), name=name)

    async def _score_separate(
        self,
        task: TerminalBenchTask,
        runtime: Runtime,
        payloads: dict[str, bytes],
        trace_id: str,
    ) -> tuple[ProgramResult, bool, float, dict[str, float], str | None, int, list[str]]:
        failures: list[str] = []
        for attempt in range(1, self.config.verifier_runtime_retries + 2):
            verifier = self._verifier_runtime(task, runtime, f"{trace_id}-verifier-{attempt}")
            outcome = None
            descriptor = None
            failure = None
            try:
                await verifier.start()
                descriptor = verifier.descriptor
                stage_tests = not task.verifier_tests_baked
                if stage_tests and task.verifier_network_mode == "no-network":
                    # Cache wheels while this verifier runtime is still pristine,
                    # before restoring any agent-produced artifact into it.
                    await self._prefetch_test_dependencies(task, verifier)
                for index, (service, payload) in enumerate(sorted(payloads.items())):
                    archive_path = f"/tmp/terminal-bench-artifacts-{index}.tgz"
                    await verifier.write(archive_path, payload)
                    restored = await self._run_root(
                        verifier,
                        f"tar -xzf {archive_path} -C /",
                    )
                    if restored.exit_code != 0:
                        raise RuntimeError(
                            f"{task.name}: restoring artifacts from {service!r} failed: "
                            f"{(restored.stdout + restored.stderr)[-4000:]}"
                        )
                outcome = await self._run_verifier(
                    task,
                    verifier,
                    stage_tests=stage_tests,
                )
            except SandboxError as error:
                failure = str(error)
            finally:
                try:
                    try:
                        await self.cleanup(task, None, verifier)
                    except Exception as cleanup_error:
                        if outcome is None:
                            failure = (
                                f"{failure}; taskset cleanup failed: {cleanup_error}" if failure else str(cleanup_error)
                            )
                        else:
                            logger.warning("%s verifier taskset cleanup failed: %s", task.name, cleanup_error)
                finally:
                    try:
                        await verifier.stop()
                    except Exception as cleanup_error:
                        if outcome is None:
                            failure = f"{failure}; cleanup failed: {cleanup_error}" if failure else str(cleanup_error)
                        else:
                            logger.warning("%s verifier cleanup failed: %s", task.name, cleanup_error)
            if outcome is not None:
                return (*outcome, descriptor, attempt, failures)
            failures.append(failure or "verifier failed without an error")
            if attempt <= self.config.verifier_runtime_retries:
                logger.warning(
                    "%s verifier VMVM failed; retrying the same artifact bytes (%d/%d): %s",
                    task.name,
                    attempt + 1,
                    self.config.verifier_runtime_retries + 1,
                    failures[-1],
                )
        raise SandboxError(
            f"{task.name}: verifier VMVM failed after {self.config.verifier_runtime_retries + 1} attempts"
        )

    @reward(weight=1.0)
    async def solved(self, task: TerminalBenchTask, trace: vf.Trace, runtime: Runtime) -> float:
        if task.verifier_mode == "shared":
            result, timed_out, score, rewards = await self._run_verifier(task, runtime, stage_tests=True)
            descriptor = runtime.descriptor
            attempts = 1
            failures: list[str] = []
        else:
            try:
                payloads = self._artifact_payloads.pop(trace.id)
            except KeyError as error:
                raise RuntimeError(f"{task.name}: captured verifier artifacts are missing") from error
            result, timed_out, score, rewards, descriptor, attempts, failures = await self._score_separate(
                task,
                runtime,
                payloads,
                trace.id,
            )
        trace.info["terminal_bench_verifier"] = {
            "runtime": descriptor,
            "attempts": attempts,
            "infrastructure_failures": failures,
            "exit_code": result.exit_code,
            "timed_out": timed_out,
            "timeout_sec": task.verifier_timeout_sec,
            "rewards": rewards,
            "output_tail": (result.stdout + result.stderr)[-8000:] if score != 1.0 else "",
        }
        return score

    async def _run_solution(self, task: TerminalBenchTask, runtime: Runtime) -> ProgramResult:
        await runtime.write("/tmp/terminal-bench-solution.tgz", _solution_tar(task.task_dir))
        staged = await self._run_root(
            runtime,
            "mkdir -p /solution && "
            "tar -xzf /tmp/terminal-bench-solution.tgz -C /solution && "
            "find /solution -type f -name '._*' -delete && "
            "chmod -R a+rX /solution",
        )
        if staged.exit_code != 0:
            raise OracleFailure(f"{task.name}: staging oracle solution failed: {staged.stdout[-4000:]}")
        solution_env = dict(task.solution_env)
        constraints = ORACLE_PIP_CONSTRAINTS.get(task.slug)
        if constraints and "PIP_CONSTRAINT" not in solution_env:
            constraint_path = "/tmp/terminal-bench-oracle-constraints.txt"
            await runtime.write(constraint_path, ("\n".join(constraints) + "\n").encode())
            solution_env["PIP_CONSTRAINT"] = constraint_path
        solution = await runtime.run(["bash", "/solution/solve.sh"], solution_env)
        if solution.exit_code != 0:
            # Oracle correctness is defined by the benchmark verifier, not the
            # shell status. Some separate-mode reference scripts deliberately
            # write the submitted artifact before an optional self-check that
            # depends on harness code available only in the verifier image.
            logger.warning(
                "%s oracle solution exited %s; continuing to verifier: %s",
                task.name,
                solution.exit_code,
                (solution.stdout + solution.stderr)[-2000:],
            )
        return solution

    async def validate(self, task: TerminalBenchTask, runtime: Runtime) -> bool:
        # Reference solutions sometimes invoke public tests as a self-check.
        # Stage them before the solution, then stage a fresh copy for scoring.
        solution_dir = Path(task.task_dir) / "solution"
        solution_uses_tests = any(b"/tests" in path.read_bytes() for path in solution_dir.iterdir() if path.is_file())
        if task.verifier_mode == "shared" or solution_uses_tests:
            await self._stage_directory(runtime, Path(task.task_dir) / "tests", "/tests", "tests")
        defer_declared_network = (
            self.config.oracle_solution_network_mode == "public" and task.agent_network_mode == "no-network"
        )
        if not defer_declared_network:
            await self._configure_network_policy(
                task,
                runtime,
                task.agent_network_mode,
                activate=True,
            )
        solution = await self._run_solution(task, runtime)
        if defer_declared_network:
            # This compatibility path is opt-in and applies only to the trusted
            # reference solution used by validate().  Activate the task's real
            # policy before artifact collection or verifier execution; model
            # rollouts never call validate() and cannot enter this path.
            await self._configure_network_policy(
                task,
                runtime,
                task.agent_network_mode,
                activate=True,
            )
        if task.verifier_mode == "shared":
            result, timed_out, score, rewards = await self._run_verifier(task, runtime, stage_tests=True)
        else:
            payloads, _ = await self._capture_artifacts(task, runtime)
            result, timed_out, score, rewards, _, _, _ = await self._score_separate(
                task,
                runtime,
                payloads,
                f"validate-{task.idx}",
            )
        if timed_out:
            raise OracleFailure(f"{task.name}: oracle verifier timed out after {task.verifier_timeout_sec:g}s")
        if score != 1.0:
            output = (result.stdout + result.stderr)[-8000:]
            solution_detail = ""
            if solution.exit_code != 0:
                solution_detail = (
                    f"; solution exited {solution.exit_code}: {(solution.stdout + solution.stderr)[-4000:]}"
                )
            raise OracleFailure(
                f"{task.name}: oracle reward is {rewards!r}; verifier output: {output}{solution_detail}"
            )
        return True


__all__ = [
    "OracleFailure",
    "TerminalBenchTask",
    "TerminalBenchVMVMConfig",
    "TerminalBenchVMVMTaskset",
    "UnsupportedTaskError",
]
