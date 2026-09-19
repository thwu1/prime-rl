"""Private, resumable VMVM discovery proof for source-wheel policies."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import re
import stat
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import unquote, urlsplit

import source_wheel_proof_bootstrap as proof_bootstrap
from verifiers.v1.runtimes import ProgramResult, Runtime, VMVMConfig, make_runtime

from terminal_bench_vmvm.source_wheels import (
    MAX_SOURCE_INPUT_BYTES,
    MAX_WHEEL_BYTES,
    MAX_WHEEL_FILES,
    MAX_WHEELHOUSE_BYTES,
    SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
    BinaryWheelPolicy,
    SourceArtifactPolicy,
    SourceWheelPolicy,
    SourceWheelPolicyEntry,
    WheelEvidence,
    atomic_write_bytes,
    canonical_distribution_name,
    canonical_json,
    extract_static_setup_requires,
    inspect_source_distribution,
    inspect_wheel,
    inspect_wheelhouse,
    is_digest_pinned_image,
    load_source_wheel_policy,
    pack_wheelhouse,
    regular_private_file,
    sha256_bytes,
    source_build_argv,
    source_build_dependency_install_argv,
    source_build_env_attest_argv,
    source_build_env_create_argv,
    source_build_environment_record,
    strict_json_loads,
    validate_policy_wheel_closure,
    validate_source_build_environment,
    validate_source_build_environment_record,
    validate_static_build_dependency_closure,
    wheel_evidence_dicts,
)
from terminal_bench_vmvm.taskset import _SOURCE_WHEEL_CLOSURE_CODE, _SOURCE_WHEEL_DOWNLOAD_CODE

DISCOVERY_INPUT_SCHEMA_VERSION = 1
PROOF_SCHEMA_VERSION = 4
STATE_SCHEMA_VERSION = 3
RUN_IDENTITY_SCHEMA_VERSION = 2
CANDIDATE_SCHEMA_VERSION = 2
ATTEMPT_JOURNAL_SCHEMA_VERSION = 1
POST_RUN_VALIDATION_SCHEMA_VERSION = 1
FINALIZATION_SCHEMA_VERSION = 2
APPROVED_BASE_RUNTIME_COMMIT = "ceb9356c98c72e51568e7bb4658a540cb1492254"
REQUIRED_DISCOVERY_ENTRIES = 9
MAX_CONCURRENT_ENTRIES = 3
RUNTIMES_PER_ENTRY = 3
MAX_PIP_REPORT_BYTES = 16 * 1024 * 1024
MAX_DISCOVERY_INPUT_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")
SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()

INPUT_DIR = "/tmp/terminal-bench-source-inputs"
BINARY_DIR = "/tmp/terminal-bench-source-binaries"
BUILD_DEP_DIR = "/tmp/terminal-bench-source-build-deps"
BUILD_ENV_DIR = "/tmp/terminal-bench-source-build-env"
WHEEL_DIR = "/tmp/terminal-bench-source-wheels"
RESOLVER_DIR = "/tmp/terminal-bench-source-resolver"
SITE_DIR = "/tmp/terminal-bench-source-site"
PIP_REPORT_PATH = "/tmp/terminal-bench-source-resolution.json"
BUILD_PIP_REPORT_PATH = "/tmp/terminal-bench-source-build-deps-resolution.json"
TARGET_ARCHIVE = "/tmp/terminal-bench-source-wheel-proof.tar"
TARGET_WHEEL_DIR = "/tmp/terminal-bench-source-wheel-proof-wheels"
TARGET_SITE_DIR = "/tmp/terminal-bench-source-wheel-proof-site"

FINGERPRINT_PROBE = """
import importlib.metadata as metadata
import json, os, pip, platform, sys, sysconfig

def full_version(info):
    value = f"{info.major}.{info.minor}.{info.micro}"
    if info.releaselevel != "final":
        value += info.releaselevel[0] + str(info.serial)
    return value

marker_environment = {
    "implementation_name": sys.implementation.name,
    "implementation_version": full_version(sys.implementation.version),
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version_tuple()[:2]),
    "sys_platform": sys.platform,
}
wheel_compatibility = [
    sys.implementation.name,
    list(sys.version_info[:2]),
    sysconfig.get_config_var("SOABI"),
    sysconfig.get_platform(),
    platform.machine(),
]
build_tools = {}
for distribution in ("pip", "setuptools", "wheel"):
    try:
        build_tools[distribution] = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        build_tools[distribution] = "<missing>"
print(json.dumps({
    "marker_environment": marker_environment,
    "pip_version": pip.__version__,
    "wheel_compatibility": wheel_compatibility,
    "build_tools": build_tools,
}, separators=(",", ":"), sort_keys=True))
""".strip()

WHEEL_DIRECTORY_PROBE = """
import hashlib, json, os, stat, sys

root = sys.argv[1]
records = []
for name in sorted(os.listdir(root)):
    path = os.path.join(root, name)
    status = os.lstat(path)
    if not stat.S_ISREG(status.st_mode) or not name.endswith(".whl"):
        raise RuntimeError("unexpected wheel directory member")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    records.append({"filename": name, "size": status.st_size, "sha256": digest.hexdigest()})
print(json.dumps(records, separators=(",", ":"), sort_keys=True))
""".strip()

DISCOVERY_DOWNLOAD_CODE = """
import hashlib, os, sys, urllib.request
from urllib.parse import urlsplit

url, destination, maximum_size, expected_sha256 = sys.argv[1:]
maximum_size = int(maximum_size)
temporary = destination + ".partial"
digest = hashlib.sha256()
size = 0
try:
    with urllib.request.urlopen(url, timeout=300) as response, open(temporary, "xb") as output:
        final_url = urlsplit(response.geturl())
        requested_url = urlsplit(url)
        if final_url.scheme != "https" or final_url.hostname != requested_url.hostname:
            raise RuntimeError("download redirected outside the approved HTTPS host")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum_size:
                raise RuntimeError("download exceeded size bound")
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if size < 1 or digest.hexdigest() != expected_sha256:
        raise RuntimeError("download integrity mismatch")
    os.replace(temporary, destination)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
""".strip()

MARKER_ENVIRONMENT_KEYS = {
    "implementation_name",
    "implementation_version",
    "os_name",
    "platform_machine",
    "platform_release",
    "platform_system",
    "platform_version",
    "python_full_version",
    "platform_python_implementation",
    "python_version",
    "sys_platform",
}


class SourceWheelProofError(RuntimeError):
    """A fail-closed proof error with an aggregate-safe public code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProofRuntime(Protocol):
    config: VMVMConfig
    backend: object

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult: ...

    async def read(self, path: str) -> bytes: ...

    async def write(self, path: str, data: bytes) -> None: ...

    async def configure_network_policy(self, mode: str) -> None: ...

    async def activate_network_policy(self) -> None: ...


RuntimeFactory = Callable[[VMVMConfig, str], ProofRuntime]


@dataclass(frozen=True)
class SourceWheelProofConfig:
    input_path: Path
    input_sha256: str
    output_dir: Path
    expected_entry_count: int
    expected_missing_evidence_sha256: str
    project_dir: Path
    canonical_launcher_path: Path
    executed_launcher_path: Path
    uv_path: Path
    python_path: Path
    python_stdlib_path: Path
    site_packages_path: Path
    vacli_path: Path
    launcher_sha256: str
    uv_sha256: str
    python_sha256: str
    python_runtime_manifest_sha256: str
    site_packages_manifest_sha256: str
    base_runtime_commit: str
    source_commit: str
    source_git_tree: str
    source_tree_sha256: str
    verifiers_commit: str
    renderers_commit: str
    pydantic_config_commit: str
    vmvm_tb_v2_sha256: str
    vacli_binary_sha256: str
    invocation_host: str
    slurm_job_id: str
    resume_state_sha256: str | None = None
    max_concurrent_entries: int = 2
    session_timeout: float = 10_800.0
    tunnel_ready_timeout: float = 120.0
    sshd_ready_timeout: float = 180.0
    max_session_buffer_size: int = 67_108_864
    tenant_id: str = "async_2347641"
    lease_ttl: str = "60s"
    vacli_lease_retries: int = 1
    vacli_max_concurrent_leases: int = 6
    vacli_max_pull_retries: int = 20
    vacli_image_pull_timeout_seconds: int = 3_600
    vacli_container_privileged: int = 1

    def validate(self) -> None:
        if self.expected_entry_count != REQUIRED_DISCOVERY_ENTRIES:
            raise SourceWheelProofError("expected_entry_count_invalid")
        if SHA256_RE.fullmatch(self.input_sha256) is None:
            raise SourceWheelProofError("input_sha256_invalid")
        if self.resume_state_sha256 is not None and SHA256_RE.fullmatch(self.resume_state_sha256) is None:
            raise SourceWheelProofError("resume_state_sha256_invalid")
        revisions = (
            self.base_runtime_commit,
            self.source_commit,
            self.source_git_tree,
            self.verifiers_commit,
            self.renderers_commit,
            self.pydantic_config_commit,
        )
        if any(REVISION_RE.fullmatch(revision) is None for revision in revisions):
            raise SourceWheelProofError("source_revision_invalid")
        if self.base_runtime_commit != APPROVED_BASE_RUNTIME_COMMIT:
            raise SourceWheelProofError("base_runtime_revision_invalid")
        if self.source_tree_sha256 != CLEAN_TREE_SHA256:
            raise SourceWheelProofError("source_tree_not_clean")
        bound_hashes = (
            self.expected_missing_evidence_sha256,
            self.launcher_sha256,
            self.uv_sha256,
            self.python_sha256,
            self.python_runtime_manifest_sha256,
            self.site_packages_manifest_sha256,
            self.vmvm_tb_v2_sha256,
            self.vacli_binary_sha256,
        )
        if any(SHA256_RE.fullmatch(digest) is None for digest in bound_hashes):
            raise SourceWheelProofError("runtime_source_sha256_invalid")
        if not self.invocation_host.strip() or not self.slurm_job_id.isdigit() or int(self.slurm_job_id) < 1:
            raise SourceWheelProofError("invocation_identity_invalid")
        if not 1 <= self.max_concurrent_entries <= MAX_CONCURRENT_ENTRIES:
            raise SourceWheelProofError("entry_concurrency_invalid")
        if min(self.session_timeout, self.tunnel_ready_timeout, self.sshd_ready_timeout) <= 0:
            raise SourceWheelProofError("runtime_timeout_invalid")
        if self.max_session_buffer_size < 1:
            raise SourceWheelProofError("runtime_buffer_invalid")
        if not self.tenant_id or not self.lease_ttl:
            raise SourceWheelProofError("runtime_identity_invalid")
        if self.vacli_lease_retries != 1 or self.vacli_max_pull_retries < 0:
            raise SourceWheelProofError("vacli_retry_invalid")
        if self.vacli_max_concurrent_leases < 1 or self.vacli_image_pull_timeout_seconds < 1:
            raise SourceWheelProofError("vacli_limit_invalid")
        if self.vacli_max_concurrent_leases > self.max_live_runtimes:
            raise SourceWheelProofError("vacli_lease_concurrency_exceeds_runtime_cap")
        if self.vacli_container_privileged not in {0, 1}:
            raise SourceWheelProofError("vacli_privilege_invalid")

    @property
    def max_live_runtimes(self) -> int:
        return self.max_concurrent_entries * RUNTIMES_PER_ENTRY

    def runtime_config(self, image: str) -> VMVMConfig:
        return VMVMConfig(
            image=image,
            fallback_image=None,
            workdir="/",
            session_timeout=self.session_timeout,
            tenant_id=self.tenant_id,
            lease_ttl=self.lease_ttl,
            tunnel_ready_timeout=self.tunnel_ready_timeout,
            sshd_ready_timeout=self.sshd_ready_timeout,
            max_session_buffer_size=self.max_session_buffer_size,
        )


@dataclass(frozen=True)
class DiscoverySource:
    distribution: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str

    def policy(self, wheel: WheelEvidence, build_dependencies: tuple[BinaryWheelPolicy, ...]) -> SourceArtifactPolicy:
        return SourceArtifactPolicy(
            distribution=self.distribution,
            version=self.version,
            filename=self.filename,
            url=self.url,
            size=self.size,
            sha256=self.sha256,
            wheel_filename=wheel.filename,
            wheel_size=wheel.size,
            wheel_sha256=wheel.sha256,
            build_dependencies=build_dependencies,
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryEntry:
    entry_identity_sha256: str
    input_entry_sha256: str
    task_binding_sha256: str
    requirements: tuple[str, ...]
    image: str
    source: DiscoverySource


@dataclass(frozen=True)
class DiscoveryManifest:
    path: Path
    sha256: str
    missing_required_evidence_sha256: str
    allowed_hosts: tuple[str, ...]
    provenance_sha256: str
    entries: tuple[DiscoveryEntry, ...]


@dataclass(frozen=True)
class RuntimeFingerprint:
    image: str
    resolution_sha256: str
    compatibility_sha256: str
    toolchain_sha256: str
    build_tools: tuple[tuple[str, str], ...]
    evidence: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "image": self.image,
            "resolution_sha256": self.resolution_sha256,
            "compatibility_sha256": self.compatibility_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "build_tools": dict(self.build_tools),
            "evidence": self.evidence,
            "evidence_sha256": sha256_bytes(canonical_json(self.evidence)),
        }


@dataclass(frozen=True)
class SourceBuild:
    filename: str
    payload: bytes
    evidence: WheelEvidence
    build_argv_sha256: str
    build_environment: dict[str, object]
    setup_requires: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveredResolution:
    report_sha256: str
    resolver_argv_sha256: str
    binary_policies: tuple[BinaryWheelPolicy, ...]
    binary_payloads: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class BuildDependencyResolution:
    requirements: tuple[str, ...]
    report_sha256: str
    resolver_argv_sha256: str
    binary_policies: tuple[BinaryWheelPolicy, ...]
    binary_payloads: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class BuildResult:
    wheels: dict[str, bytes]
    wheel_evidence: tuple[WheelEvidence, ...]
    closure: tuple[tuple[str, str], ...]
    wheelhouse: bytes
    input_artifacts: tuple[tuple[str, int, str], ...]
    build_dependency_artifacts: tuple[tuple[str, int, str], ...]
    build_environment: dict[str, object]
    build_argv_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "network": "no-network",
            "build_isolation": False,
            "dependency_resolution": "discovered-wheel-only-closure",
            "build_environment": self.build_environment,
            "input_artifacts": [
                {"filename": filename, "size": size, "sha256": digest}
                for filename, size, digest in self.input_artifacts
            ],
            "build_dependency_artifacts": [
                {"filename": filename, "size": size, "sha256": digest}
                for filename, size, digest in self.build_dependency_artifacts
            ],
            "build_argv_sha256": self.build_argv_sha256,
            "wheels": wheel_evidence_dicts(self.wheel_evidence),
            "closure": [list(item) for item in self.closure],
            "closure_sha256": sha256_bytes(canonical_json([list(item) for item in self.closure])),
            "wheelhouse": {"size": len(self.wheelhouse), "sha256": sha256_bytes(self.wheelhouse)},
        }


@dataclass
class RuntimeTelemetry:
    starting: int = 0
    active: int = 0
    successful_starts: int = 0
    peak_starting: int = 0
    peak_active: int = 0
    _started: set[int] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self, runtime: ProofRuntime) -> None:
        async with self._lock:
            self.starting += 1
            self.peak_starting = max(self.peak_starting, self.starting)
        try:
            await runtime.start()
        finally:
            async with self._lock:
                self.starting -= 1
        async with self._lock:
            self.active += 1
            self.successful_starts += 1
            self.peak_active = max(self.peak_active, self.active)
            self._started.add(id(runtime))

    async def stop(self, runtime: ProofRuntime) -> None:
        await runtime.stop()
        async with self._lock:
            if id(runtime) in self._started:
                self._started.remove(id(runtime))
                self.active -= 1

    def as_dict(self) -> dict[str, int]:
        return {
            "successful_runtime_starts": self.successful_starts,
            "peak_starting_runtimes": self.peak_starting,
            "peak_live_runtimes": self.peak_active,
        }


def _runtime_factory(config: VMVMConfig, name: str) -> ProofRuntime:
    runtime = make_runtime(config, name=name)
    if not isinstance(runtime, Runtime):
        raise SourceWheelProofError("runtime_factory_invalid")
    return runtime


def _lease_identity_sha256(runtime: ProofRuntime) -> str:
    try:
        identity = getattr(runtime.backend, "lease_identity_sha256")
    except Exception as error:
        raise SourceWheelProofError("runtime_lease_identity_missing") from error
    if not isinstance(identity, str) or SHA256_RE.fullmatch(identity) is None:
        raise SourceWheelProofError("runtime_lease_identity_missing")
    return identity


def _private_regular_file(path: Path) -> bool:
    return regular_private_file(path) and stat.S_IMODE(path.parent.lstat().st_mode) == 0o700


def _read_private(path: Path, error_code: str) -> bytes:
    if not _private_regular_file(path):
        raise SourceWheelProofError(error_code)
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise SourceWheelProofError(error_code) from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise SourceWheelProofError(error_code)
    return payload


def validate_execution_environment(config: SourceWheelProofConfig) -> None:
    config.validate()
    try:
        proof_bootstrap.validate_execution_bindings(
            proof_bootstrap.ExecutionBindings(
                project_dir=config.project_dir,
                canonical_launcher_path=config.canonical_launcher_path,
                executed_launcher_path=config.executed_launcher_path,
                uv_path=config.uv_path,
                python_path=config.python_path,
                python_stdlib_path=config.python_stdlib_path,
                site_packages_path=config.site_packages_path,
                vacli_path=config.vacli_path,
                launcher_sha256=config.launcher_sha256,
                uv_sha256=config.uv_sha256,
                python_sha256=config.python_sha256,
                python_runtime_manifest_sha256=config.python_runtime_manifest_sha256,
                site_packages_manifest_sha256=config.site_packages_manifest_sha256,
                base_runtime_commit=config.base_runtime_commit,
                source_commit=config.source_commit,
                source_git_tree=config.source_git_tree,
                source_tree_sha256=config.source_tree_sha256,
                verifiers_commit=config.verifiers_commit,
                renderers_commit=config.renderers_commit,
                pydantic_config_commit=config.pydantic_config_commit,
                vmvm_tb_v2_sha256=config.vmvm_tb_v2_sha256,
                vacli_binary_sha256=config.vacli_binary_sha256,
            ),
            require_attestation=True,
        )
    except proof_bootstrap.BindingError as error:
        raise SourceWheelProofError(error.code) from error


def _require_exact_keys(value: object, keys: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SourceWheelProofError(code)
    return value


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _valid_size(value: object, maximum: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= maximum


def _valid_wheelhouse_record(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"size", "sha256"}
        and _valid_size(value["size"], MAX_WHEELHOUSE_BYTES)
        and _valid_sha256(value["sha256"])
    )


def _validate_https_url(value: object, allowed_hosts: set[str], code: str) -> str:
    if not isinstance(value, str):
        raise SourceWheelProofError(code)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise SourceWheelProofError(code) from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise SourceWheelProofError(code)
    return value


def _parse_discovery_source(raw: object, allowed_hosts: set[str]) -> DiscoverySource:
    value = _require_exact_keys(
        raw,
        {
            "distribution",
            "version",
            "filename",
            "url",
            "size",
            "sha256",
            "source_spec",
            "source_spec_exact",
            "version_selection",
            "pkg_info_records",
            "pkg_info_identity_agreement",
        },
        "discovery_source_invalid",
    )
    distribution = value["distribution"]
    version = value["version"]
    filename = value["filename"]
    source_spec = value["source_spec"]
    if (
        not isinstance(distribution, str)
        or canonical_distribution_name(distribution) != distribution
        or not isinstance(version, str)
        or not version
        or any(character.isspace() for character in version)
        or not isinstance(filename, str)
        or SAFE_FILENAME_RE.fullmatch(filename) is None
        or not filename.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".zip"))
        or not _valid_size(value["size"], MAX_SOURCE_INPUT_BYTES)
        or not _valid_sha256(value["sha256"])
        or not isinstance(source_spec, str)
        or not source_spec
        or any(character in source_spec for character in "\r\n\x00")
        or not isinstance(value["source_spec_exact"], bool)
        or not isinstance(value["version_selection"], str)
        or not value["version_selection"]
        or isinstance(value["pkg_info_records"], bool)
        or not isinstance(value["pkg_info_records"], int)
        or value["pkg_info_records"] < 1
        or value["pkg_info_identity_agreement"] is not True
    ):
        raise SourceWheelProofError("discovery_source_invalid")
    if value["source_spec_exact"]:
        source_name, separator, source_version = source_spec.partition("==")
        if separator != "==" or canonical_distribution_name(source_name) != distribution or source_version != version:
            raise SourceWheelProofError("discovery_source_invalid")
    return DiscoverySource(
        distribution=distribution,
        version=version,
        filename=filename,
        url=_validate_https_url(value["url"], allowed_hosts, "discovery_source_invalid"),
        size=value["size"],
        sha256=value["sha256"],
    )


def load_private_discovery_input(config: SourceWheelProofConfig) -> tuple[DiscoveryManifest, bytes]:
    config.validate()
    path = config.input_path.resolve()
    payload = _read_private(path, "discovery_input_not_private")
    if len(payload) < 1 or len(payload) > MAX_DISCOVERY_INPUT_BYTES:
        raise SourceWheelProofError("discovery_input_size_invalid")
    if sha256_bytes(payload) != config.input_sha256:
        raise SourceWheelProofError("discovery_input_sha256_mismatch")
    try:
        raw = strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceWheelProofError("discovery_input_invalid") from error
    value = _require_exact_keys(
        raw,
        {
            "schema_version",
            "kind",
            "complete",
            "missing_required_evidence",
            "provenance",
            "allowed_hosts",
            "entries",
        },
        "discovery_input_invalid",
    )
    hosts = value["allowed_hosts"]
    missing = value["missing_required_evidence"]
    provenance = _require_exact_keys(
        value["provenance"],
        {"dataset_revision", "image_manifest_sha256", "oracle_results_sha256"},
        "discovery_input_invalid",
    )
    if (
        value["schema_version"] != DISCOVERY_INPUT_SCHEMA_VERSION
        or value["kind"] != "source-wheel-policy-probe-input"
        or value["complete"] is not False
        or not isinstance(missing, list)
        or not missing
        or not all(isinstance(item, str) and item for item in missing)
        or len(missing) != len(set(missing))
        or not isinstance(hosts, list)
        or not hosts
        or not all(isinstance(host, str) and host and host == host.lower() for host in hosts)
        or len(hosts) != len(set(hosts))
        or not isinstance(provenance["dataset_revision"], str)
        or REVISION_RE.fullmatch(provenance["dataset_revision"]) is None
        or not _valid_sha256(provenance["image_manifest_sha256"])
        or not _valid_sha256(provenance["oracle_results_sha256"])
        or sha256_bytes(canonical_json(missing)) != config.expected_missing_evidence_sha256
        or not isinstance(value["entries"], list)
        or len(value["entries"]) != config.expected_entry_count
    ):
        raise SourceWheelProofError("discovery_input_invalid")
    allowed_hosts = set(hosts)
    entries: list[DiscoveryEntry] = []
    tasks: set[str] = set()
    identities: set[str] = set()
    requirement_images: set[tuple[tuple[str, ...], str]] = set()
    for raw_entry in value["entries"]:
        entry = _require_exact_keys(
            raw_entry,
            {
                "task",
                "entry_identity_sha256",
                "requirements",
                "image",
                "source",
                "build_tools",
                "built_source_wheel",
                "binary_wheels",
                "reproducibility",
                "ready_for_policy",
            },
            "discovery_entry_invalid",
        )
        requirements = entry["requirements"]
        if (
            not isinstance(entry["task"], str)
            or not entry["task"]
            or not _valid_sha256(entry["entry_identity_sha256"])
            or not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(item, str) and REQUIREMENT_RE.fullmatch(item) for item in requirements)
            or len(requirements) != len(set(requirements))
            or not isinstance(entry["image"], str)
            or not is_digest_pinned_image(entry["image"])
            or entry["build_tools"] is not None
            or entry["built_source_wheel"] is not None
            or entry["binary_wheels"] is not None
            or entry["reproducibility"] is not None
            or entry["ready_for_policy"] is not False
        ):
            raise SourceWheelProofError("discovery_entry_invalid")
        requirement_tuple = tuple(requirements)
        key = (requirement_tuple, entry["image"])
        if entry["task"] in tasks or entry["entry_identity_sha256"] in identities or key in requirement_images:
            raise SourceWheelProofError("discovery_entry_duplicate")
        tasks.add(entry["task"])
        identities.add(entry["entry_identity_sha256"])
        requirement_images.add(key)
        entries.append(
            DiscoveryEntry(
                entry_identity_sha256=entry["entry_identity_sha256"],
                input_entry_sha256=sha256_bytes(canonical_json(entry)),
                task_binding_sha256=sha256_bytes(entry["task"].encode()),
                requirements=requirement_tuple,
                image=entry["image"],
                source=_parse_discovery_source(entry["source"], allowed_hosts),
            )
        )
    return (
        DiscoveryManifest(
            path=path,
            sha256=config.input_sha256,
            missing_required_evidence_sha256=config.expected_missing_evidence_sha256,
            allowed_hosts=tuple(hosts),
            provenance_sha256=sha256_bytes(canonical_json(provenance)),
            entries=tuple(entries),
        ),
        payload,
    )


def entry_key_sha256(input_sha256: str, entry: DiscoveryEntry) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "input_sha256": input_sha256,
                "entry_identity_sha256": entry.entry_identity_sha256,
                "input_entry_sha256": entry.input_entry_sha256,
            }
        )
    )


def parse_runtime_fingerprint(image: str, payload: str) -> RuntimeFingerprint:
    try:
        probe = strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceWheelProofError("runtime_fingerprint_invalid") from error
    if not isinstance(probe, dict) or set(probe) != {
        "build_tools",
        "marker_environment",
        "pip_version",
        "wheel_compatibility",
    }:
        raise SourceWheelProofError("runtime_fingerprint_invalid")
    marker_environment = probe["marker_environment"]
    pip_version = probe["pip_version"]
    compatibility = probe["wheel_compatibility"]
    build_tools = probe["build_tools"]
    if (
        not isinstance(marker_environment, dict)
        or set(marker_environment) != MARKER_ENVIRONMENT_KEYS
        or not all(isinstance(value, str) for value in marker_environment.values())
        or not isinstance(pip_version, str)
        or not pip_version
        or not isinstance(build_tools, dict)
        or set(build_tools) != {"pip", "setuptools", "wheel"}
        or not all(isinstance(value, str) and value and value != "<missing>" for value in build_tools.values())
        or build_tools.get("pip") != pip_version
        or not isinstance(compatibility, list)
        or len(compatibility) != 5
        or not isinstance(compatibility[0], str)
        or not compatibility[0]
        or not isinstance(compatibility[1], list)
        or len(compatibility[1]) != 2
        or not all(not isinstance(value, bool) and isinstance(value, int) and value >= 0 for value in compatibility[1])
        or not all(isinstance(value, str) and value for value in compatibility[2:])
    ):
        raise SourceWheelProofError("runtime_fingerprint_invalid")
    return RuntimeFingerprint(
        image=image,
        resolution_sha256=sha256_bytes(canonical_json([marker_environment, pip_version])),
        compatibility_sha256=sha256_bytes(
            canonical_json([image, marker_environment, pip_version, compatibility, build_tools])
        ),
        toolchain_sha256=sha256_bytes(canonical_json([image, build_tools])),
        build_tools=tuple(sorted((str(key), str(value)) for key, value in build_tools.items())),
        evidence=probe,
    )


def _source_build_argv(source: SourceArtifactPolicy) -> list[str]:
    return source_build_argv(
        source,
        input_dir=INPUT_DIR,
        wheel_dir=WHEEL_DIR,
        build_env_dir=BUILD_ENV_DIR,
    )


def _resolver_argv(entry: DiscoveryEntry) -> list[str]:
    return [
        "python3",
        "-I",
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--dry-run",
        "--ignore-installed",
        "--only-binary=:all:",
        "--report",
        PIP_REPORT_PATH,
        "--find-links",
        RESOLVER_DIR,
        *entry.requirements,
        f"{entry.source.distribution}=={entry.source.version}",
    ]


def _build_dependency_resolver_argv(requirements: tuple[str, ...]) -> list[str]:
    return [
        "python3",
        "-I",
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--dry-run",
        "--ignore-installed",
        "--only-binary=:all:",
        "--report",
        BUILD_PIP_REPORT_PATH,
        *requirements,
    ]


def _expected_closure(entry: SourceWheelPolicyEntry) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((distribution, version) for distribution, version, *_ in entry.expected_wheels))


def _parse_closure(stdout: str, entry: SourceWheelPolicyEntry) -> tuple[tuple[str, str], ...]:
    try:
        raw = strict_json_loads(stdout)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceWheelProofError("closure_report_invalid") from error
    if not isinstance(raw, list) or not all(
        isinstance(item, list) and len(item) == 2 and all(isinstance(value, str) and value for value in item)
        for item in raw
    ):
        raise SourceWheelProofError("closure_report_invalid")
    closure = tuple((item[0], item[1]) for item in raw)
    if closure != _expected_closure(entry):
        raise SourceWheelProofError("closure_policy_mismatch")
    return closure


def _require_success(result: ProgramResult, code: str) -> None:
    if result.exit_code != 0:
        raise SourceWheelProofError(code)


async def _gather_cancel_on_error(*awaitables: Awaitable[object]) -> list[object]:
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class AttemptJournal:
    """Immutable, hash-chained write-ahead records for every runtime start."""

    _EVENTS = {
        "start_intent",
        "start_succeeded",
        "start_failed",
        "start_indeterminate",
        "stop_succeeded",
        "stop_failed",
    }

    def __init__(self, path: Path, run_identity_sha256: str) -> None:
        self.path = path
        self.run_identity_sha256 = run_identity_sha256
        self.records: list[dict[str, object]] = []
        if self.path.exists():
            status = self.path.lstat()
            if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
                raise SourceWheelProofError("attempt_journal_not_private")
        else:
            self.path.mkdir(mode=0o700)
            self.path.chmod(0o700)
        self._load()

    def _load(self) -> None:
        for child in self.path.iterdir():
            if re.fullmatch(r"\.[0-9]{8}\.json\.\d+\.[0-9a-f]{32}\.tmp", child.name):
                if regular_private_file(child):
                    child.unlink()
                    continue
            if re.fullmatch(r"[0-9]{8}\.json", child.name) is None:
                raise SourceWheelProofError("attempt_journal_invalid")
        paths = sorted(self.path.glob("*.json"))
        previous = "0" * 64
        for sequence, path in enumerate(paths, 1):
            if path.name != f"{sequence:08d}.json" or stat.S_IMODE(path.lstat().st_mode) != 0o400:
                raise SourceWheelProofError("attempt_journal_invalid")
            payload = _read_private(path, "attempt_journal_invalid")
            try:
                record = strict_json_loads(payload)
            except (UnicodeDecodeError, ValueError, RecursionError) as error:
                raise SourceWheelProofError("attempt_journal_invalid") from error
            fields = {
                "schema_version",
                "sequence",
                "previous_record_sha256",
                "run_identity_sha256",
                "event",
                "attempt_sha256",
                "entry_key_sha256",
                "role",
                "lease_identity_sha256",
                "record_sha256",
            }
            if not isinstance(record, dict) or set(record) != fields:
                raise SourceWheelProofError("attempt_journal_invalid")
            core = {name: value for name, value in record.items() if name != "record_sha256"}
            event = record["event"]
            lease_identity = record["lease_identity_sha256"]
            if (
                record["schema_version"] != ATTEMPT_JOURNAL_SCHEMA_VERSION
                or record["sequence"] != sequence
                or record["previous_record_sha256"] != previous
                or record["run_identity_sha256"] != self.run_identity_sha256
                or event not in self._EVENTS
                or not _valid_sha256(record["attempt_sha256"])
                or not _valid_sha256(record["entry_key_sha256"])
                or record["role"] not in {"target", "builder_a", "builder_b"}
                or (lease_identity is not None and not _valid_sha256(lease_identity))
                or (event == "start_succeeded" and lease_identity is None)
                or (event in {"start_intent", "start_failed", "start_indeterminate"} and lease_identity is not None)
                or record["record_sha256"] != sha256_bytes(canonical_json(core))
                or payload != canonical_json(record) + b"\n"
            ):
                raise SourceWheelProofError("attempt_journal_invalid")
            previous = record["record_sha256"]
            self.records.append(record)

    def _append(
        self,
        event: str,
        attempt_sha256: str,
        entry_key_sha256: str,
        role: str,
        lease_identity_sha256: str | None,
    ) -> None:
        sequence = len(self.records) + 1
        core = {
            "schema_version": ATTEMPT_JOURNAL_SCHEMA_VERSION,
            "sequence": sequence,
            "previous_record_sha256": (self.records[-1]["record_sha256"] if self.records else "0" * 64),
            "run_identity_sha256": self.run_identity_sha256,
            "event": event,
            "attempt_sha256": attempt_sha256,
            "entry_key_sha256": entry_key_sha256,
            "role": role,
            "lease_identity_sha256": lease_identity_sha256,
        }
        record = {**core, "record_sha256": sha256_bytes(canonical_json(core))}
        path = self.path / f"{sequence:08d}.json"
        atomic_write_bytes(path, canonical_json(record) + b"\n", mode=0o400)
        path.chmod(0o400)
        self.records.append(record)

    def begin_start(self, entry_key_sha256: str, role: str) -> str:
        attempt_sha256 = sha256_bytes(os.urandom(32))
        self._append("start_intent", attempt_sha256, entry_key_sha256, role, None)
        return attempt_sha256

    def finish_start(
        self,
        attempt_sha256: str,
        entry_key_sha256: str,
        role: str,
        *,
        outcome: str,
        lease_identity_sha256: str | None,
    ) -> None:
        if outcome not in {"start_succeeded", "start_failed", "start_indeterminate"}:
            raise SourceWheelProofError("attempt_journal_invalid")
        self._append(outcome, attempt_sha256, entry_key_sha256, role, lease_identity_sha256)

    def finish_stop(
        self,
        attempt_sha256: str,
        entry_key_sha256: str,
        role: str,
        lease_identity_sha256: str | None,
        *,
        succeeded: bool,
    ) -> None:
        self._append(
            "stop_succeeded" if succeeded else "stop_failed",
            attempt_sha256,
            entry_key_sha256,
            role,
            lease_identity_sha256,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "record_count": len(self.records),
            "head_sha256": self.records[-1]["record_sha256"] if self.records else "0" * 64,
            "start_intents": sum(record["event"] == "start_intent" for record in self.records),
            "successful_starts": sum(record["event"] == "start_succeeded" for record in self.records),
        }

    def validate_exact(self, completed: dict[str, dict[str, object]]) -> None:
        attempts: dict[str, list[dict[str, object]]] = {}
        for record in self.records:
            attempts.setdefault(str(record["attempt_sha256"]), []).append(record)
        expected: dict[tuple[str, str], str] = {}
        for key, proof in completed.items():
            for role, lease_identity in proof["lease_identity_sha256s"].items():
                expected[(key, role)] = lease_identity
        observed: dict[tuple[str, str], str] = {}
        for records in attempts.values():
            if len(records) != 3:
                raise SourceWheelProofError("attempt_journal_incomplete")
            intent, started, stopped = records
            identity = (intent["entry_key_sha256"], intent["role"])
            if (
                intent["event"] != "start_intent"
                or started["event"] != "start_succeeded"
                or stopped["event"] != "stop_succeeded"
                or any(
                    record["entry_key_sha256"] != identity[0]
                    or record["role"] != identity[1]
                    or record["attempt_sha256"] != intent["attempt_sha256"]
                    for record in records
                )
                or started["lease_identity_sha256"] != stopped["lease_identity_sha256"]
                or identity in observed
            ):
                raise SourceWheelProofError("attempt_journal_prevents_exact_start_count")
            observed[identity] = str(started["lease_identity_sha256"])
        if observed != expected:
            raise SourceWheelProofError("attempt_journal_prevents_exact_start_count")


async def _start_runtimes_uninterruptibly(
    runtimes: list[tuple[str, ProofRuntime, str]],
    telemetry: RuntimeTelemetry,
    journal: AttemptJournal,
    entry_key_sha256: str,
) -> dict[str, str]:
    identities: dict[str, str] = {}

    async def start_one(role: str, runtime: ProofRuntime, attempt_sha256: str) -> None:
        try:
            await telemetry.start(runtime)
        except BaseException:
            journal.finish_start(
                attempt_sha256,
                entry_key_sha256,
                role,
                outcome="start_failed",
                lease_identity_sha256=None,
            )
            raise
        try:
            identity = _lease_identity_sha256(runtime)
        except BaseException:
            journal.finish_start(
                attempt_sha256,
                entry_key_sha256,
                role,
                outcome="start_indeterminate",
                lease_identity_sha256=None,
            )
            raise
        journal.finish_start(
            attempt_sha256,
            entry_key_sha256,
            role,
            outcome="start_succeeded",
            lease_identity_sha256=identity,
        )
        identities[role] = identity

    async def start_all() -> list[object]:
        return await asyncio.gather(
            *(start_one(role, runtime, attempt) for role, runtime, attempt in runtimes),
            return_exceptions=True,
        )

    task = asyncio.create_task(start_all())
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = error
    results = task.result()
    if cancellation is not None:
        raise cancellation
    if any(isinstance(result, BaseException) for result in results):
        raise SourceWheelProofError("runtime_start_failed")
    return identities


async def _stop_runtimes_uninterruptibly(
    runtimes: list[tuple[str, ProofRuntime, str]],
    telemetry: RuntimeTelemetry,
    journal: AttemptJournal,
    entry_key_sha256: str,
) -> bool:
    async def stop_one(role: str, runtime: ProofRuntime, attempt_sha256: str) -> None:
        lease_identity = None
        try:
            lease_identity = _lease_identity_sha256(runtime)
        except SourceWheelProofError:
            pass
        try:
            await telemetry.stop(runtime)
        except BaseException:
            journal.finish_stop(
                attempt_sha256,
                entry_key_sha256,
                role,
                lease_identity,
                succeeded=False,
            )
            raise
        journal.finish_stop(
            attempt_sha256,
            entry_key_sha256,
            role,
            lease_identity,
            succeeded=True,
        )

    async def stop_all() -> list[object]:
        return await asyncio.gather(
            *(stop_one(role, runtime, attempt) for role, runtime, attempt in runtimes),
            return_exceptions=True,
        )

    task = asyncio.create_task(stop_all())
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = error
    results = task.result()
    if cancellation is not None:
        raise cancellation
    return not any(isinstance(result, BaseException) for result in results)


def _policy_entry_dict(entry: SourceWheelPolicyEntry) -> dict[str, object]:
    def binary_policy_dict(wheel: BinaryWheelPolicy) -> dict[str, object]:
        return {
            "distribution": wheel.distribution,
            "version": wheel.version,
            "filename": wheel.filename,
            "url": wheel.url,
            "size": wheel.size,
            "sha256": wheel.sha256,
        }

    def source_policy_dict(source: SourceArtifactPolicy) -> dict[str, object]:
        return {
            "distribution": source.distribution,
            "version": source.version,
            "filename": source.filename,
            "url": source.url,
            "size": source.size,
            "sha256": source.sha256,
            "wheel_filename": source.wheel_filename,
            "wheel_size": source.wheel_size,
            "wheel_sha256": source.wheel_sha256,
            "build_dependencies": [binary_policy_dict(wheel) for wheel in source.build_dependencies],
        }

    return {
        "requirements": list(entry.requirements),
        "image": entry.image,
        "build_tools": dict(entry.build_tools),
        "sources": [source_policy_dict(item) for item in entry.sources],
        "binary_wheels": [binary_policy_dict(item) for item in entry.binary_wheels],
    }


def compare_build_payloads(first: BuildResult, second: BuildResult) -> dict[str, object]:
    filenames_equal = set(first.wheels) == set(second.wheels)
    byte_equal = filenames_equal and all(first.wheels[name] == second.wheels[name] for name in first.wheels)
    wheelhouses_equal = first.wheelhouse == second.wheelhouse
    closures_equal = first.closure == second.closure
    if not (byte_equal and wheelhouses_equal and closures_equal):
        raise SourceWheelProofError("cross_builder_reproducibility_failed")
    payload_hashes = {name: sha256_bytes(first.wheels[name]) for name in sorted(first.wheels)}
    return {
        "wheel_filenames_equal": filenames_equal,
        "wheel_bytes_equal": byte_equal,
        "wheelhouse_bytes_equal": wheelhouses_equal,
        "closures_equal": closures_equal,
        "wheel_payloads_sha256": sha256_bytes(canonical_json(payload_hashes)),
        "wheelhouse_sha256": sha256_bytes(first.wheelhouse),
    }


class SourceWheelProofRunner:
    def __init__(
        self,
        config: SourceWheelProofConfig,
        discovery: DiscoveryManifest,
        journal: AttemptJournal,
        *,
        runtime_factory: RuntimeFactory = _runtime_factory,
    ) -> None:
        self.config = config
        self.discovery = discovery
        self.journal = journal
        self.runtime_factory = runtime_factory
        self.telemetry = RuntimeTelemetry()
        self._entry_semaphore = asyncio.Semaphore(config.max_concurrent_entries)
        self._active_entries = 0
        self._peak_entries = 0
        self._entry_lock = asyncio.Lock()

    async def _download_source(self, runtime: ProofRuntime, source: DiscoverySource) -> bytes:
        destination = f"{INPUT_DIR}/{source.filename}"
        result = await runtime.run(
            [
                "python3",
                "-I",
                "-c",
                _SOURCE_WHEEL_DOWNLOAD_CODE,
                source.url,
                destination,
                str(source.size),
                source.sha256,
            ],
            {},
        )
        _require_success(result, "source_download_failed")
        payload = await runtime.read(destination)
        if len(payload) != source.size or sha256_bytes(payload) != source.sha256:
            raise SourceWheelProofError("source_integrity_failed")
        inspect_source_distribution(source, payload)  # type: ignore[arg-type]
        return payload

    async def _stage_builder(self, runtime: ProofRuntime, entry: DiscoveryEntry) -> tuple[str, ...]:
        removable_paths = (INPUT_DIR, BINARY_DIR, BUILD_DEP_DIR, BUILD_ENV_DIR, WHEEL_DIR, RESOLVER_DIR, SITE_DIR)
        staging_paths = (INPUT_DIR, BINARY_DIR, BUILD_DEP_DIR, WHEEL_DIR, RESOLVER_DIR, SITE_DIR)
        prepared = await runtime.run(
            [
                "sh",
                "-c",
                f"rm -rf {' '.join(removable_paths)} {PIP_REPORT_PATH} {BUILD_PIP_REPORT_PATH} && "
                f"mkdir -p {' '.join(staging_paths)} && chmod 1777 {' '.join(staging_paths)}",
            ],
            {},
        )
        _require_success(prepared, "builder_prepare_failed")
        payload = await self._download_source(runtime, entry.source)
        return extract_static_setup_requires(
            entry.source.policy(
                WheelEvidence(
                    distribution=entry.source.distribution,
                    version=entry.source.version,
                    filename=entry.source.filename,
                    size=entry.source.size,
                    sha256=entry.source.sha256,
                    universal=False,
                ),
                (),
            ),
            payload,
        )

    async def _activate_no_network(self, runtime: ProofRuntime) -> None:
        await runtime.configure_network_policy("no-network")
        await runtime.activate_network_policy()

    async def _fingerprint(self, runtime: ProofRuntime, image: str) -> RuntimeFingerprint:
        result = await runtime.run(["python3", "-I", "-c", FINGERPRINT_PROBE], {})
        _require_success(result, "runtime_fingerprint_failed")
        return parse_runtime_fingerprint(image, result.stdout.strip())

    async def _wheel_directory(self, runtime: ProofRuntime) -> dict[str, bytes]:
        result = await runtime.run(["python3", "-I", "-c", WHEEL_DIRECTORY_PROBE, WHEEL_DIR], {})
        _require_success(result, "wheel_directory_probe_failed")
        try:
            records = strict_json_loads(result.stdout)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise SourceWheelProofError("wheel_directory_report_invalid") from error
        if not isinstance(records, list) or not records or len(records) > MAX_WHEEL_FILES:
            raise SourceWheelProofError("wheel_directory_report_invalid")
        wheels: dict[str, bytes] = {}
        total_size = 0
        for raw in records:
            record = _require_exact_keys(raw, {"filename", "size", "sha256"}, "wheel_directory_report_invalid")
            filename = record["filename"]
            if (
                not isinstance(filename, str)
                or SAFE_FILENAME_RE.fullmatch(filename) is None
                or not filename.lower().endswith(".whl")
                or filename in wheels
                or not _valid_size(record["size"], MAX_WHEEL_BYTES)
                or not _valid_sha256(record["sha256"])
            ):
                raise SourceWheelProofError("wheel_directory_report_invalid")
            payload = await runtime.read(f"{WHEEL_DIR}/{filename}")
            if len(payload) != record["size"] or sha256_bytes(payload) != record["sha256"]:
                raise SourceWheelProofError("wheel_directory_integrity_failed")
            total_size += len(payload)
            if total_size > MAX_WHEELHOUSE_BYTES:
                raise SourceWheelProofError("wheel_directory_size_invalid")
            wheels[filename] = payload
        return wheels

    async def _create_source_build_environment(
        self,
        runtime: ProofRuntime,
        expected_build_tools: tuple[tuple[str, str], ...],
    ) -> dict[str, object]:
        _require_success(
            await runtime.run(source_build_env_create_argv(BUILD_ENV_DIR), {}),
            "source_build_environment_create_failed",
        )
        result = await runtime.run(source_build_env_attest_argv(BUILD_ENV_DIR), {})
        _require_success(result, "source_build_environment_attest_failed")
        try:
            attestation = validate_source_build_environment(
                result.stdout.strip(),
                build_env_dir=BUILD_ENV_DIR,
                expected_build_tools=expected_build_tools,
            )
        except RuntimeError as error:
            raise SourceWheelProofError("source_build_environment_attest_failed") from error
        return source_build_environment_record(
            build_env_dir=BUILD_ENV_DIR,
            expected_build_tools=expected_build_tools,
            attestation=attestation,
        )

    async def _build_source(
        self,
        runtime: ProofRuntime,
        source: SourceArtifactPolicy,
        expected_build_tools: tuple[tuple[str, str], ...],
        existing_wheels: set[str],
    ) -> SourceBuild:
        build_environment = await self._create_source_build_environment(runtime, expected_build_tools)
        if source.build_dependencies:
            _require_success(
                await runtime.run(
                    source_build_dependency_install_argv(
                        build_env_dir=BUILD_ENV_DIR,
                        build_dependency_dir=BUILD_DEP_DIR,
                        build_dependencies=source.build_dependencies,
                    ),
                    {"PIP_NO_INDEX": "1"},
                ),
                "build_dependency_offline_install_failed",
            )
            post_install = await runtime.run(source_build_env_attest_argv(BUILD_ENV_DIR), {})
            _require_success(post_install, "source_build_environment_attest_failed")
            try:
                build_environment = source_build_environment_record(
                    build_env_dir=BUILD_ENV_DIR,
                    expected_build_tools=expected_build_tools,
                    attestation=validate_source_build_environment(
                        post_install.stdout.strip(),
                        build_env_dir=BUILD_ENV_DIR,
                        expected_build_tools=expected_build_tools,
                    ),
                )
            except RuntimeError as error:
                raise SourceWheelProofError("source_build_environment_attest_failed") from error
        source_payload = await runtime.read(f"{INPUT_DIR}/{source.filename}")
        inspect_source_distribution(source, source_payload)
        setup_requires = extract_static_setup_requires(source, source_payload)
        try:
            validate_static_build_dependency_closure(setup_requires, source.build_dependencies)
        except RuntimeError as error:
            raise SourceWheelProofError("build_dependency_policy_missing") from error
        argv = _source_build_argv(source)
        _require_success(await runtime.run(argv, {}), "source_build_failed")
        wheels = await self._wheel_directory(runtime)
        new_names = set(wheels) - existing_wheels
        if set(wheels) != existing_wheels | new_names or len(new_names) != 1:
            raise SourceWheelProofError("source_build_output_invalid")
        filename = next(iter(new_names))
        evidence = inspect_wheel(filename, wheels[filename])
        if evidence.distribution != source.distribution or evidence.version != source.version:
            raise SourceWheelProofError("source_build_output_invalid")
        return SourceBuild(
            filename=filename,
            payload=wheels[filename],
            evidence=evidence,
            build_argv_sha256=sha256_bytes(canonical_json(argv)),
            build_environment=build_environment,
            setup_requires=setup_requires,
        )

    def _parse_resolution_report(
        self,
        payload: bytes,
        entry: DiscoveryEntry,
        source_build: SourceBuild,
    ) -> list[tuple[str, str, str, str, str]]:
        if len(payload) < 1 or len(payload) > MAX_PIP_REPORT_BYTES:
            raise SourceWheelProofError("resolution_report_invalid")
        try:
            report = strict_json_loads(payload)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise SourceWheelProofError("resolution_report_invalid") from error
        if (
            not isinstance(report, dict)
            or not isinstance(report.get("install"), list)
            or not report["install"]
            or len(report["install"]) > MAX_WHEEL_FILES
        ):
            raise SourceWheelProofError("resolution_report_invalid")
        binaries: list[tuple[str, str, str, str, str]] = []
        distributions: set[str] = set()
        source_seen = 0
        for raw_item in report["install"]:
            if not isinstance(raw_item, dict):
                raise SourceWheelProofError("resolution_report_invalid")
            metadata = raw_item.get("metadata")
            download = raw_item.get("download_info")
            if not isinstance(metadata, dict) or not isinstance(download, dict):
                raise SourceWheelProofError("resolution_report_invalid")
            name = metadata.get("name")
            version = metadata.get("version")
            url = download.get("url")
            archive = download.get("archive_info")
            if (
                not isinstance(name, str)
                or not isinstance(version, str)
                or not version
                or any(character.isspace() for character in version)
                or not isinstance(url, str)
                or not isinstance(archive, dict)
            ):
                raise SourceWheelProofError("resolution_report_invalid")
            distribution = canonical_distribution_name(name)
            if not distribution or distribution in distributions:
                raise SourceWheelProofError("resolution_report_invalid")
            distributions.add(distribution)
            hashes = archive.get("hashes")
            digest = hashes.get("sha256") if isinstance(hashes, dict) else None
            if not _valid_sha256(digest):
                raise SourceWheelProofError("resolution_report_invalid")
            parsed = urlsplit(url)
            if distribution == entry.source.distribution:
                expected_path = f"{RESOLVER_DIR}/{source_build.filename}"
                if (
                    version != entry.source.version
                    or parsed.scheme != "file"
                    or parsed.netloc
                    or unquote(parsed.path) != expected_path
                    or digest != source_build.evidence.sha256
                ):
                    raise SourceWheelProofError("resolution_source_seed_mismatch")
                source_seen += 1
                continue
            approved_url = _validate_https_url(url, set(self.discovery.allowed_hosts), "binary_url_invalid")
            filename = PurePosixPath(unquote(urlsplit(approved_url).path)).name
            if SAFE_FILENAME_RE.fullmatch(filename) is None or not filename.lower().endswith(".whl"):
                raise SourceWheelProofError("binary_url_invalid")
            binaries.append((distribution, version, filename, digest, approved_url))
        if source_seen != 1:
            raise SourceWheelProofError("resolution_source_seed_missing")
        return binaries

    def _parse_build_dependency_report(
        self,
        payload: bytes,
    ) -> list[tuple[str, str, str, str, str]]:
        if len(payload) < 1 or len(payload) > MAX_PIP_REPORT_BYTES:
            raise SourceWheelProofError("build_dependency_resolution_report_invalid")
        try:
            report = strict_json_loads(payload)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise SourceWheelProofError("build_dependency_resolution_report_invalid") from error
        if (
            not isinstance(report, dict)
            or not isinstance(report.get("install"), list)
            or not report["install"]
            or len(report["install"]) > MAX_WHEEL_FILES
        ):
            raise SourceWheelProofError("build_dependency_resolution_report_invalid")
        records: list[tuple[str, str, str, str, str]] = []
        distributions: set[str] = set()
        for raw_item in report["install"]:
            if not isinstance(raw_item, dict):
                raise SourceWheelProofError("build_dependency_resolution_report_invalid")
            metadata = raw_item.get("metadata")
            download = raw_item.get("download_info")
            if not isinstance(metadata, dict) or not isinstance(download, dict):
                raise SourceWheelProofError("build_dependency_resolution_report_invalid")
            name = metadata.get("name")
            version = metadata.get("version")
            url = download.get("url")
            archive = download.get("archive_info")
            if (
                not isinstance(name, str)
                or not isinstance(version, str)
                or not version
                or any(character.isspace() for character in version)
                or not isinstance(url, str)
                or not isinstance(archive, dict)
            ):
                raise SourceWheelProofError("build_dependency_resolution_report_invalid")
            distribution = canonical_distribution_name(name)
            if not distribution or distribution in distributions:
                raise SourceWheelProofError("build_dependency_resolution_report_invalid")
            distributions.add(distribution)
            hashes = archive.get("hashes")
            digest = hashes.get("sha256") if isinstance(hashes, dict) else None
            if not _valid_sha256(digest):
                raise SourceWheelProofError("build_dependency_resolution_report_invalid")
            approved_url = _validate_https_url(url, set(self.discovery.allowed_hosts), "build_dependency_url_invalid")
            filename = PurePosixPath(unquote(urlsplit(approved_url).path)).name
            if SAFE_FILENAME_RE.fullmatch(filename) is None or not filename.lower().endswith(".whl"):
                raise SourceWheelProofError("build_dependency_url_invalid")
            records.append((distribution, version, filename, digest, approved_url))
        return records

    async def _discover_build_dependencies(
        self,
        runtime: ProofRuntime,
        setup_requires: tuple[str, ...],
    ) -> BuildDependencyResolution:
        if not setup_requires:
            return BuildDependencyResolution((), "", "", (), ())
        argv = _build_dependency_resolver_argv(setup_requires)
        _require_success(await runtime.run(argv, {}), "build_dependency_resolution_failed")
        report_payload = await runtime.read(BUILD_PIP_REPORT_PATH)
        records = self._parse_build_dependency_report(report_payload)
        policies: list[BinaryWheelPolicy] = []
        payloads: list[tuple[str, bytes]] = []
        filenames: set[str] = set()
        total_size = 0
        for distribution, version, filename, digest, url in records:
            if filename in filenames:
                raise SourceWheelProofError("build_dependency_filename_duplicate")
            filenames.add(filename)
            destination = f"{BUILD_DEP_DIR}/{filename}"
            _require_success(
                await runtime.run(
                    [
                        "python3",
                        "-I",
                        "-c",
                        DISCOVERY_DOWNLOAD_CODE,
                        url,
                        destination,
                        str(MAX_WHEEL_BYTES),
                        digest,
                    ],
                    {},
                ),
                "build_dependency_download_failed",
            )
            payload = await runtime.read(destination)
            if not _valid_size(len(payload), MAX_WHEEL_BYTES) or sha256_bytes(payload) != digest:
                raise SourceWheelProofError("build_dependency_integrity_failed")
            total_size += len(payload)
            if total_size > MAX_WHEELHOUSE_BYTES:
                raise SourceWheelProofError("build_dependency_closure_size_invalid")
            evidence = inspect_wheel(filename, payload)
            if evidence.distribution != distribution or evidence.version != version:
                raise SourceWheelProofError("build_dependency_metadata_mismatch")
            policies.append(
                BinaryWheelPolicy(
                    distribution=distribution,
                    version=version,
                    filename=filename,
                    url=url,
                    size=len(payload),
                    sha256=digest,
                )
            )
            payloads.append((filename, payload))
        sorted_policies = tuple(sorted(policies, key=lambda item: item.filename))
        try:
            validate_static_build_dependency_closure(setup_requires, sorted_policies)
        except RuntimeError as error:
            raise SourceWheelProofError("build_dependency_resolution_missing_direct_requirement") from error
        return BuildDependencyResolution(
            requirements=setup_requires,
            report_sha256=sha256_bytes(report_payload),
            resolver_argv_sha256=sha256_bytes(canonical_json(argv)),
            binary_policies=sorted_policies,
            binary_payloads=tuple(sorted(payloads)),
        )

    async def _discover_resolution(
        self,
        runtime: ProofRuntime,
        entry: DiscoveryEntry,
        source_build: SourceBuild,
    ) -> DiscoveredResolution:
        await runtime.write(f"{RESOLVER_DIR}/{source_build.filename}", source_build.payload)
        argv = _resolver_argv(entry)
        _require_success(await runtime.run(argv, {}), "binary_resolution_failed")
        report_payload = await runtime.read(PIP_REPORT_PATH)
        binary_records = self._parse_resolution_report(report_payload, entry, source_build)
        policies: list[BinaryWheelPolicy] = []
        payloads: list[tuple[str, bytes]] = []
        filenames: set[str] = {source_build.filename}
        total_size = 0
        for distribution, version, filename, digest, url in binary_records:
            if filename in filenames:
                raise SourceWheelProofError("binary_filename_duplicate")
            filenames.add(filename)
            destination = f"{BINARY_DIR}/{filename}"
            _require_success(
                await runtime.run(
                    [
                        "python3",
                        "-I",
                        "-c",
                        DISCOVERY_DOWNLOAD_CODE,
                        url,
                        destination,
                        str(MAX_WHEEL_BYTES),
                        digest,
                    ],
                    {},
                ),
                "binary_download_failed",
            )
            payload = await runtime.read(destination)
            if not _valid_size(len(payload), MAX_WHEEL_BYTES) or sha256_bytes(payload) != digest:
                raise SourceWheelProofError("binary_integrity_failed")
            total_size += len(payload)
            if total_size > MAX_WHEELHOUSE_BYTES:
                raise SourceWheelProofError("binary_closure_size_invalid")
            evidence = inspect_wheel(filename, payload)
            if evidence.distribution != distribution or evidence.version != version:
                raise SourceWheelProofError("binary_metadata_mismatch")
            policies.append(
                BinaryWheelPolicy(
                    distribution=distribution,
                    version=version,
                    filename=filename,
                    url=url,
                    size=len(payload),
                    sha256=digest,
                )
            )
            payloads.append((filename, payload))
        return DiscoveredResolution(
            report_sha256=sha256_bytes(report_payload),
            resolver_argv_sha256=sha256_bytes(canonical_json(argv)),
            binary_policies=tuple(sorted(policies, key=lambda item: item.filename)),
            binary_payloads=tuple(sorted(payloads)),
        )

    async def _complete_builder(
        self,
        runtime: ProofRuntime,
        entry: DiscoveryEntry,
        policy_entry: SourceWheelPolicyEntry,
        source_build: SourceBuild,
    ) -> BuildResult:
        wheels = await self._wheel_directory(runtime)
        evidence = validate_policy_wheel_closure(policy_entry, wheels)
        _require_success(
            await runtime.run(
                [
                    "sh",
                    "-c",
                    f"PIP_NO_INDEX=1 python3 -m pip install --quiet --disable-pip-version-check "
                    f"--no-cache-dir --no-index --no-deps --target {SITE_DIR} {WHEEL_DIR}/*.whl",
                ],
                {},
            ),
            "builder_offline_install_failed",
        )
        closure_result = await runtime.run(
            ["python3", "-I", "-c", _SOURCE_WHEEL_CLOSURE_CODE, SITE_DIR, *entry.requirements],
            {},
        )
        _require_success(closure_result, "builder_closure_failed")
        closure = _parse_closure(closure_result.stdout, policy_entry)
        wheelhouse = pack_wheelhouse(wheels)
        if inspect_wheelhouse(wheelhouse) != evidence:
            raise SourceWheelProofError("wheelhouse_repack_failed")
        inputs = [(entry.source.filename, entry.source.size, entry.source.sha256)]
        inputs.extend((wheel.filename, wheel.size, wheel.sha256) for wheel in policy_entry.binary_wheels)
        build_dependency_inputs = [
            (wheel.filename, wheel.size, wheel.sha256)
            for source in policy_entry.sources
            for wheel in source.build_dependencies
        ]
        return BuildResult(
            wheels=wheels,
            wheel_evidence=evidence,
            closure=closure,
            wheelhouse=wheelhouse,
            input_artifacts=tuple(inputs),
            build_dependency_artifacts=tuple(sorted(build_dependency_inputs)),
            build_environment=source_build.build_environment,
            build_argv_sha256=source_build.build_argv_sha256,
        )

    async def _validate_target(
        self,
        runtime: ProofRuntime,
        entry: DiscoveryEntry,
        policy_entry: SourceWheelPolicyEntry,
        wheelhouse: bytes,
    ) -> dict[str, object]:
        try:
            if inspect_wheelhouse(wheelhouse) != validate_policy_wheel_closure(
                policy_entry, _wheelhouse_payloads(wheelhouse)
            ):
                raise SourceWheelProofError("target_wheelhouse_invalid")
            await runtime.write(TARGET_ARCHIVE, wheelhouse)
            _require_success(
                await runtime.run(
                    [
                        "sh",
                        "-c",
                        f"rm -rf {TARGET_WHEEL_DIR} {TARGET_SITE_DIR} && "
                        f"mkdir -p {TARGET_WHEEL_DIR} {TARGET_SITE_DIR} && "
                        f"tar -C {TARGET_WHEEL_DIR} -xf {TARGET_ARCHIVE}",
                    ],
                    {},
                ),
                "target_stage_failed",
            )
            _require_success(
                await runtime.run(
                    [
                        "sh",
                        "-c",
                        f"PIP_NO_INDEX=1 python3 -m pip install --quiet --disable-pip-version-check "
                        f"--no-cache-dir --no-index --no-deps --target {TARGET_SITE_DIR} "
                        f"{TARGET_WHEEL_DIR}/*.whl",
                    ],
                    {},
                ),
                "target_offline_install_failed",
            )
            closure_result = await runtime.run(
                ["python3", "-I", "-c", _SOURCE_WHEEL_CLOSURE_CODE, TARGET_SITE_DIR, *entry.requirements],
                {},
            )
            _require_success(closure_result, "target_closure_failed")
            closure = _parse_closure(closure_result.stdout, policy_entry)
            return {
                "network": "no-network",
                "install": "offline-no-index-no-deps",
                "closure": [list(item) for item in closure],
                "closure_sha256": sha256_bytes(canonical_json([list(item) for item in closure])),
                "wheelhouse": {"size": len(wheelhouse), "sha256": sha256_bytes(wheelhouse)},
            }
        finally:
            cleaned = await runtime.run(
                ["sh", "-c", f"rm -rf {TARGET_ARCHIVE} {TARGET_WHEEL_DIR} {TARGET_SITE_DIR}"],
                {},
            )
            _require_success(cleaned, "target_cleanup_failed")

    async def _cleanup_builder(self, runtime: ProofRuntime) -> None:
        paths = (INPUT_DIR, BINARY_DIR, BUILD_DEP_DIR, BUILD_ENV_DIR, WHEEL_DIR, RESOLVER_DIR, SITE_DIR)
        result = await runtime.run(
            ["sh", "-c", f"rm -rf {' '.join(paths)} {PIP_REPORT_PATH} {BUILD_PIP_REPORT_PATH}"],
            {},
        )
        _require_success(result, "builder_cleanup_failed")

    async def _prove_entry(self, entry: DiscoveryEntry) -> tuple[str, dict[str, object]]:
        async with self._entry_semaphore:
            async with self._entry_lock:
                self._active_entries += 1
                self._peak_entries = max(self._peak_entries, self._active_entries)
            key = entry_key_sha256(self.discovery.sha256, entry)
            runtime_config = self.config.runtime_config(entry.image)
            runtimes: list[ProofRuntime] = []
            attempts: list[tuple[str, ProofRuntime, str]] = []
            error: BaseException | None = None
            result: dict[str, object] | None = None
            try:
                for role in ("target", "builder-a", "builder-b"):
                    runtimes.append(self.runtime_factory(runtime_config, f"source-proof-{key[:12]}-{role}"))
                target, builder_a, builder_b = runtimes
                for role, runtime in zip(("target", "builder_a", "builder_b"), runtimes, strict=True):
                    attempts.append((role, runtime, self.journal.begin_start(key, role)))
                lease_identities = await _start_runtimes_uninterruptibly(
                    attempts,
                    self.telemetry,
                    self.journal,
                    key,
                )
                if len(set(lease_identities.values())) != RUNTIMES_PER_ENTRY:
                    raise SourceWheelProofError("runtime_lease_identity_duplicate")
                stage_results = await _gather_cancel_on_error(
                    self._stage_builder(builder_a, entry),
                    self._stage_builder(builder_b, entry),
                )
                if (
                    len(stage_results) != 2
                    or not all(isinstance(item, tuple) for item in stage_results)
                    or stage_results[0] != stage_results[1]
                ):
                    raise SourceWheelProofError("build_dependency_setup_requires_mismatch")
                setup_requires = stage_results[0]
                assert isinstance(setup_requires, tuple)
                build_dependency_resolution = await self._discover_build_dependencies(builder_b, setup_requires)
                for filename, payload in build_dependency_resolution.binary_payloads:
                    await _gather_cancel_on_error(
                        builder_a.write(f"{BUILD_DEP_DIR}/{filename}", payload),
                        builder_b.write(f"{BUILD_DEP_DIR}/{filename}", payload),
                    )
                build_source_policy = entry.source.policy(
                    WheelEvidence(
                        distribution=entry.source.distribution,
                        version=entry.source.version,
                        filename=entry.source.filename,
                        size=entry.source.size,
                        sha256=entry.source.sha256,
                        universal=False,
                    ),
                    build_dependency_resolution.binary_policies,
                )
                await _gather_cancel_on_error(
                    self._activate_no_network(builder_a),
                    self._activate_no_network(target),
                )
                first_fingerprints = await _gather_cancel_on_error(
                    self._fingerprint(builder_a, entry.image),
                    self._fingerprint(target, entry.image),
                )
                fingerprint_a, target_fingerprint = first_fingerprints
                if not isinstance(fingerprint_a, RuntimeFingerprint) or not isinstance(
                    target_fingerprint, RuntimeFingerprint
                ):
                    raise SourceWheelProofError("runtime_fingerprint_invalid")
                source_a = await self._build_source(
                    builder_a, build_source_policy, target_fingerprint.build_tools, set()
                )
                if source_a.setup_requires != build_dependency_resolution.requirements:
                    raise SourceWheelProofError("build_dependency_setup_requires_mismatch")
                resolution = await self._discover_resolution(builder_b, entry, source_a)
                binary_names = {wheel.filename for wheel in resolution.binary_policies}
                for filename, payload in resolution.binary_payloads:
                    await _gather_cancel_on_error(
                        builder_a.write(f"{WHEEL_DIR}/{filename}", payload),
                        builder_b.write(f"{WHEEL_DIR}/{filename}", payload),
                    )
                await self._activate_no_network(builder_b)
                fingerprint_b = await self._fingerprint(builder_b, entry.image)
                if not (fingerprint_a == fingerprint_b == target_fingerprint):
                    raise SourceWheelProofError("runtime_fingerprint_mismatch")
                source_policy = entry.source.policy(source_a.evidence, build_dependency_resolution.binary_policies)
                source_b = await self._build_source(
                    builder_b,
                    source_policy,
                    target_fingerprint.build_tools,
                    binary_names,
                )
                if source_b.setup_requires != build_dependency_resolution.requirements:
                    raise SourceWheelProofError("build_dependency_setup_requires_mismatch")
                if source_a.filename != source_b.filename or source_a.payload != source_b.payload:
                    raise SourceWheelProofError("source_wheel_reproducibility_failed")
                policy_entry = SourceWheelPolicyEntry(
                    requirements=entry.requirements,
                    image=entry.image,
                    build_tools=target_fingerprint.build_tools,
                    sources=(source_policy,),
                    binary_wheels=resolution.binary_policies,
                )
                build_results = await _gather_cancel_on_error(
                    self._complete_builder(builder_a, entry, policy_entry, source_a),
                    self._complete_builder(builder_b, entry, policy_entry, source_b),
                )
                build_a, build_b = build_results
                if not isinstance(build_a, BuildResult) or not isinstance(build_b, BuildResult):
                    raise SourceWheelProofError("builder_result_invalid")
                cross_builder = compare_build_payloads(build_a, build_b)
                target_validation = await self._validate_target(target, entry, policy_entry, build_a.wheelhouse)
                await _gather_cancel_on_error(
                    self._cleanup_builder(builder_a),
                    self._cleanup_builder(builder_b),
                )
                core = {
                    "schema_version": PROOF_SCHEMA_VERSION,
                    "entry_key_sha256": key,
                    "input_sha256": self.discovery.sha256,
                    "input_entry_sha256": entry.input_entry_sha256,
                    "entry_identity_sha256": entry.entry_identity_sha256,
                    "task_binding_sha256": entry.task_binding_sha256,
                    "final_policy_entry": _policy_entry_dict(policy_entry),
                    "runtime": target_fingerprint.as_dict(),
                    "lease_identity_sha256s": lease_identities,
                    "resolution": {
                        "network": "public-wheel-only",
                        "source_seed_sha256": source_a.evidence.sha256,
                        "report_sha256": resolution.report_sha256,
                        "resolver_argv_sha256": resolution.resolver_argv_sha256,
                        "binary_artifact_count": len(resolution.binary_policies),
                        "build_dependencies": {
                            "setup_requires": list(build_dependency_resolution.requirements),
                            "network": "public-wheel-only",
                            "report_sha256": build_dependency_resolution.report_sha256,
                            "resolver_argv_sha256": build_dependency_resolution.resolver_argv_sha256,
                            "binary_artifact_count": len(build_dependency_resolution.binary_policies),
                        },
                    },
                    "builders": [build_a.as_dict(), build_b.as_dict()],
                    "cross_builder": cross_builder,
                    "target_validation": target_validation,
                    "runtime_starts": {"target": 1, "builder_a": 1, "builder_b": 1},
                }
                result = {**core, "proof_sha256": sha256_bytes(canonical_json(core))}
            except BaseException as caught:
                error = caught
            try:
                cleanup_ok = await _stop_runtimes_uninterruptibly(
                    attempts,
                    self.telemetry,
                    self.journal,
                    key,
                )
            finally:
                async with self._entry_lock:
                    self._active_entries -= 1
            if not cleanup_ok:
                raise SourceWheelProofError("runtime_cleanup_failed")
            if error is not None:
                if isinstance(error, (SourceWheelProofError, asyncio.CancelledError)):
                    raise error
                raise SourceWheelProofError("entry_proof_failed") from error
            assert result is not None
            return key, result

    async def run_pending(
        self,
        completed: dict[str, dict[str, object]],
        publish: Callable[[str, dict[str, object], dict[str, int]], None],
    ) -> None:
        pending = [
            entry for entry in self.discovery.entries if entry_key_sha256(self.discovery.sha256, entry) not in completed
        ]
        active: set[asyncio.Task[tuple[str, dict[str, object]]]] = set()
        iterator = iter(pending)

        def fill() -> None:
            while len(active) < self.config.max_concurrent_entries:
                try:
                    entry = next(iterator)
                except StopIteration:
                    return
                active.add(asyncio.create_task(self._prove_entry(entry)))

        fill()
        try:
            while active:
                done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                successes: list[tuple[str, dict[str, object]]] = []
                failure: BaseException | None = None
                for task in done:
                    try:
                        successes.append(task.result())
                    except BaseException as error:
                        failure = failure or error
                for key, proof in sorted(successes):
                    publish(
                        key,
                        proof,
                        {
                            **self.telemetry.as_dict(),
                            "peak_concurrent_entries": self.peak_entries,
                        },
                    )
                    completed[key] = proof
                if failure is None:
                    fill()
                    continue
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
                raise failure
        finally:
            if active:
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)

    @property
    def peak_entries(self) -> int:
        return self._peak_entries


def _wheelhouse_payloads(payload: bytes) -> dict[str, bytes]:
    import io
    import tarfile

    wheels: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive.getmembers():
            handle = archive.extractfile(member)
            if handle is None:
                raise SourceWheelProofError("wheelhouse_member_invalid")
            wheels[member.name] = handle.read()
    return wheels


def _expected_entry_keys(discovery: DiscoveryManifest) -> dict[str, DiscoveryEntry]:
    entries = {entry_key_sha256(discovery.sha256, entry): entry for entry in discovery.entries}
    if len(entries) != len(discovery.entries):
        raise SourceWheelProofError("discovery_entry_key_duplicate")
    return entries


def _validate_entry_proof(
    key: str,
    proof: object,
    discovery: DiscoveryManifest,
    entry: DiscoveryEntry,
) -> dict[str, object]:
    fields = {
        "schema_version",
        "entry_key_sha256",
        "input_sha256",
        "input_entry_sha256",
        "entry_identity_sha256",
        "task_binding_sha256",
        "final_policy_entry",
        "runtime",
        "lease_identity_sha256s",
        "resolution",
        "builders",
        "cross_builder",
        "target_validation",
        "runtime_starts",
        "proof_sha256",
    }
    if not isinstance(proof, dict) or set(proof) != fields:
        raise SourceWheelProofError("proof_state_entry_invalid")
    core = {name: value for name, value in proof.items() if name != "proof_sha256"}
    if (
        proof["schema_version"] != PROOF_SCHEMA_VERSION
        or proof["entry_key_sha256"] != key
        or key != entry_key_sha256(discovery.sha256, entry)
        or proof["input_sha256"] != discovery.sha256
        or proof["input_entry_sha256"] != entry.input_entry_sha256
        or proof["entry_identity_sha256"] != entry.entry_identity_sha256
        or proof["task_binding_sha256"] != entry.task_binding_sha256
        or not isinstance(proof["lease_identity_sha256s"], dict)
        or set(proof["lease_identity_sha256s"]) != {"target", "builder_a", "builder_b"}
        or not all(_valid_sha256(value) for value in proof["lease_identity_sha256s"].values())
        or len(set(proof["lease_identity_sha256s"].values())) != RUNTIMES_PER_ENTRY
        or proof["runtime_starts"] != {"target": 1, "builder_a": 1, "builder_b": 1}
        or proof["proof_sha256"] != sha256_bytes(canonical_json(core))
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    policy_entry = _require_exact_keys(
        proof["final_policy_entry"],
        {"requirements", "image", "build_tools", "sources", "binary_wheels"},
        "proof_state_entry_invalid",
    )
    if (
        policy_entry["requirements"] != list(entry.requirements)
        or policy_entry["image"] != entry.image
        or not isinstance(policy_entry["build_tools"], dict)
        or set(policy_entry["build_tools"]) != {"pip", "setuptools", "wheel"}
        or not isinstance(policy_entry["sources"], list)
        or len(policy_entry["sources"]) != 1
        or not isinstance(policy_entry["binary_wheels"], list)
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    source = _require_exact_keys(
        policy_entry["sources"][0],
        {
            "distribution",
            "version",
            "filename",
            "url",
            "size",
            "sha256",
            "wheel_filename",
            "wheel_size",
            "wheel_sha256",
            "build_dependencies",
        },
        "proof_state_entry_invalid",
    )
    if any(source[name] != value for name, value in entry.source.as_dict().items()):
        raise SourceWheelProofError("proof_state_entry_invalid")
    if (
        not isinstance(source["wheel_filename"], str)
        or SAFE_FILENAME_RE.fullmatch(source["wheel_filename"]) is None
        or not source["wheel_filename"].lower().endswith(".whl")
        or not _valid_size(source["wheel_size"], MAX_WHEEL_BYTES)
        or not _valid_sha256(source["wheel_sha256"])
        or not all(
            isinstance(value, str) and value and not any(character.isspace() for character in value)
            for value in policy_entry["build_tools"].values()
        )
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    raw_build_dependencies = source["build_dependencies"]
    if not isinstance(raw_build_dependencies, list):
        raise SourceWheelProofError("proof_state_entry_invalid")
    build_dependencies: list[dict[str, object]] = []
    build_dependency_distributions: set[object] = set()
    build_dependency_filenames: set[object] = set()
    for wheel in raw_build_dependencies:
        if not isinstance(wheel, dict) or set(wheel) != {
            "distribution",
            "version",
            "filename",
            "url",
            "size",
            "sha256",
        }:
            raise SourceWheelProofError("proof_state_entry_invalid")
        distribution = wheel["distribution"]
        filename = wheel["filename"]
        if (
            not isinstance(distribution, str)
            or canonical_distribution_name(distribution) != distribution
            or distribution in build_dependency_distributions
            or not isinstance(wheel["version"], str)
            or not wheel["version"]
            or any(character.isspace() for character in wheel["version"])
            or not isinstance(filename, str)
            or SAFE_FILENAME_RE.fullmatch(filename) is None
            or not filename.lower().endswith(".whl")
            or filename in build_dependency_filenames
            or not _valid_size(wheel["size"], MAX_WHEEL_BYTES)
            or not _valid_sha256(wheel["sha256"])
        ):
            raise SourceWheelProofError("proof_state_entry_invalid")
        _validate_https_url(wheel["url"], set(discovery.allowed_hosts), "proof_state_entry_invalid")
        build_dependency_distributions.add(distribution)
        build_dependency_filenames.add(filename)
        build_dependencies.append(wheel)
    binary_distributions = {entry.source.distribution}
    binary_filenames = {source["wheel_filename"]}
    for wheel in policy_entry["binary_wheels"]:
        if not isinstance(wheel, dict) or set(wheel) != {
            "distribution",
            "version",
            "filename",
            "url",
            "size",
            "sha256",
        }:
            raise SourceWheelProofError("proof_state_entry_invalid")
        distribution = wheel["distribution"]
        filename = wheel["filename"]
        if (
            not isinstance(distribution, str)
            or canonical_distribution_name(distribution) != distribution
            or distribution in binary_distributions
            or not isinstance(wheel["version"], str)
            or not wheel["version"]
            or any(character.isspace() for character in wheel["version"])
            or not isinstance(filename, str)
            or SAFE_FILENAME_RE.fullmatch(filename) is None
            or not filename.lower().endswith(".whl")
            or filename in binary_filenames
            or not _valid_size(wheel["size"], MAX_WHEEL_BYTES)
            or not _valid_sha256(wheel["sha256"])
        ):
            raise SourceWheelProofError("proof_state_entry_invalid")
        _validate_https_url(wheel["url"], set(discovery.allowed_hosts), "proof_state_entry_invalid")
        binary_distributions.add(distribution)
        binary_filenames.add(filename)
    if build_dependency_filenames & binary_filenames:
        raise SourceWheelProofError("proof_state_entry_invalid")
    runtime = proof["runtime"]
    if not isinstance(runtime, dict):
        raise SourceWheelProofError("proof_state_entry_invalid")
    try:
        parsed_runtime = parse_runtime_fingerprint(entry.image, canonical_json(runtime["evidence"]).decode())
    except (KeyError, TypeError, UnicodeDecodeError, SourceWheelProofError) as error:
        raise SourceWheelProofError("proof_state_entry_invalid") from error
    if runtime != parsed_runtime.as_dict() or dict(parsed_runtime.build_tools) != policy_entry["build_tools"]:
        raise SourceWheelProofError("proof_state_entry_invalid")
    builders = proof["builders"]
    cross_builder = proof["cross_builder"]
    target = proof["target_validation"]
    resolution = proof["resolution"]
    if (
        not isinstance(builders, list)
        or len(builders) != 2
        or not isinstance(cross_builder, dict)
        or set(cross_builder)
        != {
            "wheel_filenames_equal",
            "wheel_bytes_equal",
            "wheelhouse_bytes_equal",
            "closures_equal",
            "wheel_payloads_sha256",
            "wheelhouse_sha256",
        }
        or cross_builder.get("wheel_filenames_equal") is not True
        or cross_builder.get("wheel_bytes_equal") is not True
        or cross_builder.get("wheelhouse_bytes_equal") is not True
        or cross_builder.get("closures_equal") is not True
        or not isinstance(target, dict)
        or set(target) != {"network", "install", "closure", "closure_sha256", "wheelhouse"}
        or target.get("network") != "no-network"
        or target.get("install") != "offline-no-index-no-deps"
        or not isinstance(resolution, dict)
        or set(resolution)
        != {
            "network",
            "source_seed_sha256",
            "report_sha256",
            "resolver_argv_sha256",
            "binary_artifact_count",
            "build_dependencies",
        }
        or resolution.get("network") != "public-wheel-only"
        or not _valid_sha256(resolution.get("report_sha256"))
        or resolution.get("resolver_argv_sha256") != sha256_bytes(canonical_json(_resolver_argv(entry)))
        or not _valid_sha256(resolution.get("source_seed_sha256"))
        or resolution.get("source_seed_sha256") != source.get("wheel_sha256")
        or isinstance(resolution.get("binary_artifact_count"), bool)
        or resolution.get("binary_artifact_count") != len(policy_entry["binary_wheels"])
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    build_dependency_resolution = resolution["build_dependencies"]
    setup_requires = (
        build_dependency_resolution.get("setup_requires") if isinstance(build_dependency_resolution, dict) else None
    )
    if (
        not isinstance(build_dependency_resolution, dict)
        or set(build_dependency_resolution)
        != {"setup_requires", "network", "report_sha256", "resolver_argv_sha256", "binary_artifact_count"}
        or not isinstance(setup_requires, list)
        or not all(isinstance(item, str) and item for item in setup_requires)
        or build_dependency_resolution.get("network") != "public-wheel-only"
        or isinstance(build_dependency_resolution.get("binary_artifact_count"), bool)
        or build_dependency_resolution.get("binary_artifact_count") != len(build_dependencies)
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    parsed_build_dependencies = tuple(
        BinaryWheelPolicy(
            distribution=str(wheel["distribution"]),
            version=str(wheel["version"]),
            filename=str(wheel["filename"]),
            url=str(wheel["url"]),
            size=int(wheel["size"]),
            sha256=str(wheel["sha256"]),
        )
        for wheel in build_dependencies
    )
    if build_dependencies:
        if not _valid_sha256(build_dependency_resolution.get("report_sha256")) or build_dependency_resolution.get(
            "resolver_argv_sha256"
        ) != sha256_bytes(canonical_json(_build_dependency_resolver_argv(tuple(setup_requires)))):
            raise SourceWheelProofError("proof_state_entry_invalid")
    elif (
        build_dependency_resolution.get("report_sha256") != ""
        or build_dependency_resolution.get("resolver_argv_sha256") != ""
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    try:
        validate_static_build_dependency_closure(tuple(setup_requires), parsed_build_dependencies)
    except RuntimeError as error:
        raise SourceWheelProofError("proof_state_entry_invalid") from error
    expected_wheels = sorted(
        [
            {
                "distribution": source["distribution"],
                "version": source["version"],
                "filename": source["wheel_filename"],
                "size": source["wheel_size"],
                "sha256": source["wheel_sha256"],
            }
        ]
        + [
            {name: wheel[name] for name in ("distribution", "version", "filename", "size", "sha256")}
            for wheel in policy_entry["binary_wheels"]
            if isinstance(wheel, dict)
            and set(wheel) == {"distribution", "version", "filename", "url", "size", "sha256"}
        ],
        key=lambda item: item["filename"],
    )
    if len(expected_wheels) != len(policy_entry["binary_wheels"]) + 1:
        raise SourceWheelProofError("proof_state_entry_invalid")
    expected_closure = sorted([[wheel["distribution"], wheel["version"]] for wheel in expected_wheels])
    expected_closure_sha256 = sha256_bytes(canonical_json(expected_closure))
    expected_inputs = [
        {"filename": entry.source.filename, "size": entry.source.size, "sha256": entry.source.sha256}
    ] + [{name: wheel[name] for name in ("filename", "size", "sha256")} for wheel in policy_entry["binary_wheels"]]
    expected_build_dependency_inputs = [
        {name: wheel[name] for name in ("filename", "size", "sha256")} for wheel in build_dependencies
    ]
    source_policy = SourceArtifactPolicy(
        distribution=str(source["distribution"]),
        version=str(source["version"]),
        filename=str(source["filename"]),
        url=str(source["url"]),
        size=int(source["size"]),
        sha256=str(source["sha256"]),
        wheel_filename=str(source["wheel_filename"]),
        wheel_size=int(source["wheel_size"]),
        wheel_sha256=str(source["wheel_sha256"]),
        build_dependencies=parsed_build_dependencies,
    )
    for builder in builders:
        if (
            not isinstance(builder, dict)
            or set(builder)
            != {
                "network",
                "build_isolation",
                "dependency_resolution",
                "build_environment",
                "input_artifacts",
                "build_dependency_artifacts",
                "build_argv_sha256",
                "wheels",
                "closure",
                "closure_sha256",
                "wheelhouse",
            }
            or builder.get("network") != "no-network"
            or builder.get("build_isolation") is not False
            or builder.get("dependency_resolution") != "discovered-wheel-only-closure"
            or builder.get("input_artifacts") != expected_inputs
            or builder.get("build_dependency_artifacts") != expected_build_dependency_inputs
            or builder.get("build_argv_sha256") != sha256_bytes(canonical_json(_source_build_argv(source_policy)))
            or builder.get("closure") != expected_closure
            or builder.get("closure_sha256") != expected_closure_sha256
            or not isinstance(builder.get("wheels"), list)
            or len(builder["wheels"]) != len(expected_wheels)
            or not _valid_wheelhouse_record(builder.get("wheelhouse"))
        ):
            raise SourceWheelProofError("proof_state_entry_invalid")
        try:
            validate_source_build_environment_record(
                builder["build_environment"],
                build_env_dir=BUILD_ENV_DIR,
                expected_build_tools=parsed_runtime.build_tools,
            )
        except RuntimeError as error:
            raise SourceWheelProofError("proof_state_entry_invalid") from error
        observed = [
            {name: wheel[name] for name in ("distribution", "version", "filename", "size", "sha256")}
            for wheel in builder["wheels"]
            if isinstance(wheel, dict)
            and set(wheel) == {"distribution", "version", "filename", "size", "sha256", "universal"}
            and isinstance(wheel["universal"], bool)
        ]
        if observed != expected_wheels:
            raise SourceWheelProofError("proof_state_entry_invalid")
    first_builder, second_builder = builders
    wheelhouse = first_builder["wheelhouse"]
    if not _valid_wheelhouse_record(wheelhouse) or not _valid_wheelhouse_record(target.get("wheelhouse")):
        raise SourceWheelProofError("proof_state_entry_invalid")
    expected_payload_hashes = sha256_bytes(
        canonical_json({wheel["filename"]: wheel["sha256"] for wheel in expected_wheels})
    )
    if (
        first_builder["wheels"] != second_builder["wheels"]
        or first_builder["wheelhouse"] != second_builder["wheelhouse"]
        or target.get("wheelhouse") != wheelhouse
        or target.get("closure") != expected_closure
        or target.get("closure_sha256") != expected_closure_sha256
        or cross_builder.get("wheel_payloads_sha256") != expected_payload_hashes
        or cross_builder.get("wheelhouse_sha256") != wheelhouse.get("sha256")
    ):
        raise SourceWheelProofError("proof_state_entry_invalid")
    return proof


class ProofStore:
    def __init__(
        self,
        config: SourceWheelProofConfig,
        discovery: DiscoveryManifest,
    ) -> None:
        self.config = config
        self.discovery = discovery
        self.output_dir = config.output_dir.resolve()
        self.identity_path = self.output_dir / "run_identity.json"
        self.candidate_path = self.output_dir / "source_wheel_candidate.json"
        self.state_path = self.output_dir / "proof_state.json"
        self.journal_path = self.output_dir / "attempt_journal"
        self.post_validation_path = self.output_dir / "post_run_validation.json"
        self.finalization_path = self.output_dir / "finalization.json"
        self.proof_path = self.output_dir / "source_wheel_proof.json"
        self.final_policy_path = self.output_dir / "source_wheel_policy.json"
        self.lock_path = self.output_dir / ".writer.lock"
        self._lock_handle: object | None = None
        self.identity = self._run_identity()
        self.identity_payload = canonical_json(self.identity) + b"\n"
        self.identity_sha256 = sha256_bytes(self.identity_payload)
        self.entry_map = _expected_entry_keys(discovery)
        self.entries_sha256 = sha256_bytes(canonical_json(sorted(self.entry_map)))
        self.state: dict[str, object] = {}
        self.journal: AttemptJournal | None = None

    def _run_identity(self) -> dict[str, object]:
        implementation = Path(__file__).read_bytes()
        source_contract = Path(__file__).with_name("source_wheels.py").read_bytes()
        return {
            "schema_version": RUN_IDENTITY_SCHEMA_VERSION,
            "discovery_input_sha256": self.discovery.sha256,
            "expected_entry_count": self.config.expected_entry_count,
            "missing_required_evidence_sha256": self.discovery.missing_required_evidence_sha256,
            "discovery_provenance_sha256": self.discovery.provenance_sha256,
            "discovery_entries_sha256": sha256_bytes(
                canonical_json([entry.input_entry_sha256 for entry in self.discovery.entries])
            ),
            "entry_count": len(self.discovery.entries),
            "source": {
                "approved_base_runtime_commit": self.config.base_runtime_commit,
                "commit": self.config.source_commit,
                "git_tree": self.config.source_git_tree,
                "clean_tree_sha256": self.config.source_tree_sha256,
                "implementation_sha256": sha256_bytes(implementation),
                "source_wheel_contract_sha256": sha256_bytes(source_contract),
                "verifiers_commit": self.config.verifiers_commit,
                "renderers_commit": self.config.renderers_commit,
                "pydantic_config_commit": self.config.pydantic_config_commit,
                "vmvm_tb_v2_sha256": self.config.vmvm_tb_v2_sha256,
            },
            "execution": {
                "canonical_launcher_sha256": self.config.launcher_sha256,
                "uv_sha256": self.config.uv_sha256,
                "python_executable_sha256": self.config.python_sha256,
                "python_runtime_manifest_sha256": self.config.python_runtime_manifest_sha256,
                "site_packages_manifest_sha256": self.config.site_packages_manifest_sha256,
                "vacli_binary_sha256": self.config.vacli_binary_sha256,
            },
            "runtime": {
                "type": "vmvm",
                "tenant_id": self.config.tenant_id,
                "lease_ttl": self.config.lease_ttl,
                "session_timeout": self.config.session_timeout,
                "tunnel_ready_timeout": self.config.tunnel_ready_timeout,
                "sshd_ready_timeout": self.config.sshd_ready_timeout,
                "max_session_buffer_size": self.config.max_session_buffer_size,
                "fallback_image": None,
                "workdir": "/",
                "runtimes_per_entry": RUNTIMES_PER_ENTRY,
                "max_concurrent_entries": self.config.max_concurrent_entries,
                "max_live_runtimes": self.config.max_live_runtimes,
                "vacli_lease_retries": self.config.vacli_lease_retries,
                "vacli_max_concurrent_leases": self.config.vacli_max_concurrent_leases,
                "vacli_max_pull_retries": self.config.vacli_max_pull_retries,
                "vacli_image_pull_timeout_seconds": self.config.vacli_image_pull_timeout_seconds,
                "vacli_container_privileged": self.config.vacli_container_privileged,
            },
        }

    def _candidate_payload(self) -> bytes:
        candidate = {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "kind": "source-wheel-policy-discovery-candidate",
            "runnable": False,
            "run_identity_sha256": self.identity_sha256,
            "discovery_input_sha256": self.discovery.sha256,
            "missing_required_evidence_sha256": self.discovery.missing_required_evidence_sha256,
            "entries_sha256": self.entries_sha256,
            "entry_count": len(self.entry_map),
            "required_runtime_starts": len(self.entry_map) * RUNTIMES_PER_ENTRY,
            "required_proofs": [
                "two_independent_no_network_builds",
                "byte_identical_wheels",
                "clean_target_offline_install",
            ],
        }
        return canonical_json(candidate) + b"\n"

    def _ensure_exact_artifact(self, path: Path, payload: bytes, *, mode: int = 0o400) -> None:
        if path.exists():
            if (
                not regular_private_file(path)
                or stat.S_IMODE(path.lstat().st_mode) != mode
                or path.read_bytes() != payload
            ):
                raise SourceWheelProofError("output_artifact_mismatch")
            return
        atomic_write_bytes(path, payload, mode=mode)
        path.chmod(mode)

    def _validate_output_contents(self) -> None:
        artifact_names = {
            self.identity_path.name,
            self.candidate_path.name,
            self.state_path.name,
            self.post_validation_path.name,
            self.proof_path.name,
            self.final_policy_path.name,
            self.finalization_path.name,
            self.journal_path.name,
            self.lock_path.name,
        }
        temporary_pattern = re.compile(
            rf"\.({'|'.join(re.escape(name) for name in sorted(artifact_names))})\.\d+\.[0-9a-f]{{32}}\.tmp"
        )
        validation_pattern = re.compile(r"\.source_wheel_policy\.validation\.\d+\.[0-9a-f]{32}\.tmp")
        for child in self.output_dir.iterdir():
            if child.name in artifact_names:
                if child == self.journal_path and (not child.is_dir() or stat.S_IMODE(child.lstat().st_mode) != 0o700):
                    raise SourceWheelProofError("attempt_journal_not_private")
                continue
            if (
                temporary_pattern.fullmatch(child.name) or validation_pattern.fullmatch(child.name)
            ) and regular_private_file(child):
                child.unlink()
                continue
            raise SourceWheelProofError("output_directory_contains_unknown_artifact")

    def __enter__(self) -> ProofStore:
        if self.output_dir.exists():
            status = self.output_dir.lstat()
            if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
                raise SourceWheelProofError("output_directory_not_private")
        else:
            try:
                self.output_dir.mkdir(mode=0o700)
                self.output_dir.chmod(0o700)
            except OSError as error:
                raise SourceWheelProofError("output_directory_create_failed") from error
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as error:
            raise SourceWheelProofError("output_lock_invalid") from error
        try:
            lock_status = os.fstat(descriptor)
            if not stat.S_ISREG(lock_status.st_mode) or lock_status.st_nlink != 1:
                raise SourceWheelProofError("output_lock_invalid")
            os.fchmod(descriptor, 0o600)
        except (OSError, SourceWheelProofError) as error:
            os.close(descriptor)
            raise SourceWheelProofError("output_lock_invalid") from error
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise SourceWheelProofError("output_writer_active") from error
        self._lock_handle = handle
        try:
            self._validate_output_contents()
            self._ensure_exact_artifact(self.identity_path, self.identity_payload)
            self._ensure_exact_artifact(self.candidate_path, self._candidate_payload())
            self.journal = AttemptJournal(self.journal_path, self.identity_sha256)
            self.state = self._load_or_create_state()
        except BaseException:
            handle.close()
            self._lock_handle = None
            raise
        return self

    def __exit__(self, *_: object) -> None:
        if self._lock_handle is not None:
            self._lock_handle.close()  # type: ignore[union-attr]
            self._lock_handle = None

    def _initial_state(self) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "run_identity_sha256": self.identity_sha256,
            "discovery_input_sha256": self.discovery.sha256,
            "entries_sha256": self.entries_sha256,
            "entry_count": len(self.entry_map),
            "invocations": [{"host": self.config.invocation_host, "slurm_job_id": self.config.slurm_job_id}],
            "completed": {},
            "attempt_journal": self._journal().snapshot(),
            "post_run_validation": None,
            "telemetry": {
                "attested_runtime_starts": 0,
                "peak_starting_runtimes": 0,
                "peak_live_runtimes": 0,
                "peak_concurrent_entries": 0,
            },
        }

    def _validate_state(self, state: object) -> dict[str, object]:
        fields = {
            "schema_version",
            "run_identity_sha256",
            "discovery_input_sha256",
            "entries_sha256",
            "entry_count",
            "invocations",
            "completed",
            "attempt_journal",
            "post_run_validation",
            "telemetry",
        }
        if not isinstance(state, dict) or set(state) != fields:
            raise SourceWheelProofError("proof_state_invalid")
        completed = state["completed"]
        post_validation = state["post_run_validation"]
        telemetry = state["telemetry"]
        if (
            state["schema_version"] != STATE_SCHEMA_VERSION
            or state["run_identity_sha256"] != self.identity_sha256
            or state["discovery_input_sha256"] != self.discovery.sha256
            or state["entries_sha256"] != self.entries_sha256
            or state["entry_count"] != len(self.entry_map)
            or not isinstance(state["invocations"], list)
            or not state["invocations"]
            or not all(
                isinstance(invocation, dict)
                and set(invocation) == {"host", "slurm_job_id"}
                and isinstance(invocation["host"], str)
                and bool(invocation["host"].strip())
                and isinstance(invocation["slurm_job_id"], str)
                and invocation["slurm_job_id"].isdigit()
                and int(invocation["slurm_job_id"]) > 0
                for invocation in state["invocations"]
            )
            or len({invocation["slurm_job_id"] for invocation in state["invocations"]}) != len(state["invocations"])
            or not isinstance(completed, dict)
            or not set(completed).issubset(self.entry_map)
            or (
                post_validation is not None
                and (
                    not isinstance(post_validation, dict)
                    or set(post_validation)
                    != {
                        "prevalidation_state_sha256",
                        "record_sha256",
                        "validation_id_sha256",
                    }
                    or not all(_valid_sha256(value) for value in post_validation.values())
                )
            )
            or not isinstance(telemetry, dict)
            or set(telemetry)
            != {
                "attested_runtime_starts",
                "peak_starting_runtimes",
                "peak_live_runtimes",
                "peak_concurrent_entries",
            }
            or not all(
                not isinstance(value, bool) and isinstance(value, int) and value >= 0 for value in telemetry.values()
            )
            or telemetry.get("attested_runtime_starts") != len(completed) * RUNTIMES_PER_ENTRY
            or telemetry.get("peak_starting_runtimes", 0) > self.config.max_live_runtimes
            or telemetry.get("peak_live_runtimes", 0) > self.config.max_live_runtimes
            or telemetry.get("peak_concurrent_entries", 0) > self.config.max_concurrent_entries
        ):
            raise SourceWheelProofError("proof_state_invalid")
        if state["attempt_journal"] != self._journal().snapshot():
            raise SourceWheelProofError("attempt_journal_state_mismatch")
        for key, proof in completed.items():
            _validate_entry_proof(key, proof, self.discovery, self.entry_map[key])
        lease_hashes = [digest for proof in completed.values() for digest in proof["lease_identity_sha256s"].values()]
        if len(lease_hashes) != len(set(lease_hashes)):
            raise SourceWheelProofError("proof_state_lease_identity_duplicate")
        self._journal().validate_exact(completed)
        return state

    def _load_or_create_state(self) -> dict[str, object]:
        if self.state_path.exists():
            if self.config.resume_state_sha256 is None:
                raise SourceWheelProofError("resume_state_sha256_required")
            payload = _read_private(self.state_path, "proof_state_not_private")
            if sha256_bytes(payload) != self.config.resume_state_sha256:
                raise SourceWheelProofError("resume_state_sha256_mismatch")
            try:
                state = self._validate_state(strict_json_loads(payload))
            except (UnicodeDecodeError, ValueError, RecursionError) as error:
                raise SourceWheelProofError("proof_state_invalid") from error
            completed = set(state["completed"])
            post_validation_exists = self.post_validation_path.exists()
            if state["post_run_validation"] is not None and not post_validation_exists:
                raise SourceWheelProofError("post_run_validation_record_missing")
            if post_validation_exists:
                if completed != set(self.entry_map):
                    raise SourceWheelProofError("post_run_validation_record_invalid")
                self.state = state
                self._reconcile_post_run_validation()
                state = self.state
            elif completed == set(self.entry_map):
                raise SourceWheelProofError("completed_state_not_post_validated")
            if self.finalization_path.exists():
                if completed != set(self.entry_map) or state["post_run_validation"] is None:
                    raise SourceWheelProofError("finalization_record_invalid")
                return state
            if self.proof_path.exists() or self.final_policy_path.exists():
                raise SourceWheelProofError("finalization_record_missing")
            if state["post_run_validation"] is not None:
                return state
            invocations = list(state["invocations"])
            if any(invocation["slurm_job_id"] == self.config.slurm_job_id for invocation in invocations):
                raise SourceWheelProofError("invocation_already_recorded")
            invocations.append({"host": self.config.invocation_host, "slurm_job_id": self.config.slurm_job_id})
            state["invocations"] = invocations
            self._write_state(state)
            return state
        if self.config.resume_state_sha256 is not None:
            raise SourceWheelProofError("resume_state_missing")
        if self._journal().records:
            raise SourceWheelProofError("attempt_journal_incomplete")
        state = self._initial_state()
        self._write_state(state)
        return state

    def _write_state(self, state: dict[str, object]) -> None:
        state["attempt_journal"] = self._journal().snapshot()
        atomic_write_bytes(
            self.state_path,
            canonical_json(state) + b"\n",
            mode=0o600,
            replace=self.state_path.exists(),
        )
        self.state_path.chmod(0o600)

    @property
    def completed(self) -> dict[str, dict[str, object]]:
        value = self.state["completed"]
        assert isinstance(value, dict)
        return value  # type: ignore[return-value]

    def _journal(self) -> AttemptJournal:
        if self.journal is None:
            raise SourceWheelProofError("attempt_journal_invalid")
        return self.journal

    def publish_entry(self, key: str, proof: dict[str, object], telemetry: dict[str, int]) -> None:
        if self.state["post_run_validation"] is not None or self.post_validation_path.exists():
            raise SourceWheelProofError("post_run_validation_already_recorded")
        if key in self.completed:
            if self.completed[key] != proof:
                raise SourceWheelProofError("completed_entry_changed")
            return
        _validate_entry_proof(key, proof, self.discovery, self.entry_map[key])
        prior_lease_hashes = {
            digest
            for completed_proof in self.completed.values()
            for digest in completed_proof["lease_identity_sha256s"].values()
        }
        if prior_lease_hashes.intersection(proof["lease_identity_sha256s"].values()):
            raise SourceWheelProofError("proof_state_lease_identity_duplicate")
        completed = dict(self.completed)
        completed[key] = proof
        prior = self.state["telemetry"]
        assert isinstance(prior, dict)
        self.state["completed"] = completed
        self.state["telemetry"] = {
            "attested_runtime_starts": len(completed) * RUNTIMES_PER_ENTRY,
            "peak_starting_runtimes": max(int(prior["peak_starting_runtimes"]), telemetry["peak_starting_runtimes"]),
            "peak_live_runtimes": max(int(prior["peak_live_runtimes"]), telemetry["peak_live_runtimes"]),
            "peak_concurrent_entries": max(int(prior["peak_concurrent_entries"]), telemetry["peak_concurrent_entries"]),
        }
        self._write_state(self.state)

    def record_peak_entries(self, peak: int) -> None:
        if self.state["post_run_validation"] is not None or self.post_validation_path.exists():
            if peak > int(self.state["telemetry"]["peak_concurrent_entries"]):  # type: ignore[index]
                raise SourceWheelProofError("post_run_validation_already_recorded")
            return
        prior = self.state["telemetry"]
        assert isinstance(prior, dict)
        previous = int(prior["peak_concurrent_entries"])
        if peak > previous:
            prior["peak_concurrent_entries"] = peak
            self._write_state(self.state)

    def _post_validation_core(self, prevalidation_state: dict[str, object]) -> dict[str, object]:
        if prevalidation_state.get("post_run_validation") is not None:
            raise SourceWheelProofError("post_run_validation_record_invalid")
        if set(self.completed) != set(self.entry_map):
            raise SourceWheelProofError("proof_incomplete")
        self._journal().validate_exact(self.completed)
        journal = self._journal().snapshot()
        if prevalidation_state.get("attempt_journal") != journal:
            raise SourceWheelProofError("attempt_journal_state_mismatch")
        invocations = prevalidation_state.get("invocations")
        if not isinstance(invocations, list) or not invocations:
            raise SourceWheelProofError("post_run_validation_record_invalid")
        return {
            "schema_version": POST_RUN_VALIDATION_SCHEMA_VERSION,
            "kind": "source-wheel-proof-post-run-validation",
            "validation_result": "passed",
            "run_identity_sha256": self.identity_sha256,
            "discovery_input_sha256": self.discovery.sha256,
            "entries_sha256": self.entries_sha256,
            "entry_count": len(self.entry_map),
            "prevalidation_state_sha256": sha256_bytes(canonical_json(prevalidation_state) + b"\n"),
            "completed_sha256": sha256_bytes(canonical_json(prevalidation_state["completed"])),
            "attempt_journal": journal,
            "validation_invocation_sha256": sha256_bytes(canonical_json(invocations[-1])),
            "environment_binding_sha256": sha256_bytes(
                canonical_json(
                    {
                        "source": self.identity["source"],
                        "execution": self.identity["execution"],
                    }
                )
            ),
        }

    def _validated_post_run_record(
        self,
        prevalidation_state: dict[str, object],
    ) -> tuple[dict[str, object], bytes, dict[str, str]]:
        core = self._post_validation_core(prevalidation_state)
        validation_id_sha256 = sha256_bytes(canonical_json(core))
        record = {**core, "validation_id_sha256": validation_id_sha256}
        payload = canonical_json(record) + b"\n"
        receipt = {
            "prevalidation_state_sha256": core["prevalidation_state_sha256"],
            "record_sha256": sha256_bytes(payload),
            "validation_id_sha256": validation_id_sha256,
        }
        return record, payload, receipt  # type: ignore[return-value]

    def _reconcile_post_run_validation(self) -> None:
        if not self.post_validation_path.exists():
            raise SourceWheelProofError("post_run_validation_record_missing")
        current_receipt = self.state["post_run_validation"]
        prevalidation_state = dict(self.state)
        prevalidation_state["post_run_validation"] = None
        _, expected_payload, expected_receipt = self._validated_post_run_record(prevalidation_state)
        observed_payload = _read_private(
            self.post_validation_path,
            "post_run_validation_record_not_private",
        )
        if stat.S_IMODE(self.post_validation_path.lstat().st_mode) != 0o400 or observed_payload != expected_payload:
            raise SourceWheelProofError("post_run_validation_record_invalid")
        if current_receipt is None:
            self.state["post_run_validation"] = expected_receipt
            self._write_state(self.state)
        elif current_receipt != expected_receipt:
            raise SourceWheelProofError("post_run_validation_record_invalid")

    def record_post_run_validation(self) -> None:
        if set(self.completed) != set(self.entry_map):
            raise SourceWheelProofError("proof_incomplete")
        if self.post_validation_path.exists():
            self._reconcile_post_run_validation()
            return
        if self.state["post_run_validation"] is not None:
            raise SourceWheelProofError("post_run_validation_record_missing")
        prevalidation_state = dict(self.state)
        _, payload, receipt = self._validated_post_run_record(prevalidation_state)
        self._ensure_exact_artifact(self.post_validation_path, payload)
        self.state["post_run_validation"] = receipt
        self._write_state(self.state)

    def _final_policy_payload(self) -> bytes:
        entries = [
            self.completed[entry_key_sha256(self.discovery.sha256, entry)]["final_policy_entry"]
            for entry in self.discovery.entries
        ]
        return (
            canonical_json(
                {
                    "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                    "allowed_hosts": list(self.discovery.allowed_hosts),
                    "entries": entries,
                }
            )
            + b"\n"
        )

    def _validate_final_policy(self, payload: bytes) -> SourceWheelPolicy:
        path = self.output_dir / f".source_wheel_policy.validation.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            return load_source_wheel_policy(path, sha256_bytes(payload))
        finally:
            path.unlink(missing_ok=True)

    def publish_final(self) -> dict[str, object]:
        if set(self.completed) != set(self.entry_map):
            raise SourceWheelProofError("proof_incomplete")
        self._journal().validate_exact(self.completed)
        if self.state["attempt_journal"] != self._journal().snapshot():
            raise SourceWheelProofError("attempt_journal_state_mismatch")
        self._reconcile_post_run_validation()
        post_validation = self.state["post_run_validation"]
        if not isinstance(post_validation, dict):
            raise SourceWheelProofError("post_run_validation_record_missing")
        policy_payload = self._final_policy_payload()
        try:
            policy = self._validate_final_policy(policy_payload)
        except (OSError, RuntimeError, ValueError) as error:
            raise SourceWheelProofError("final_policy_invalid") from error
        if len(policy.entries) != len(self.discovery.entries):
            raise SourceWheelProofError("final_policy_invalid")
        policy_sha256 = sha256_bytes(policy_payload)
        state_payload = canonical_json(self.state) + b"\n"
        state_sha256 = sha256_bytes(state_payload)
        ordered = [self.completed[key] for key in sorted(self.completed)]
        telemetry = self.state["telemetry"]
        assert isinstance(telemetry, dict)
        finalization_core = {
            "schema_version": FINALIZATION_SCHEMA_VERSION,
            "kind": "source-wheel-proof-finalization",
            "run_identity_sha256": self.identity_sha256,
            "discovery_input_sha256": self.discovery.sha256,
            "missing_required_evidence_sha256": self.discovery.missing_required_evidence_sha256,
            "state_sha256": state_sha256,
            "source_wheel_policy_sha256": policy_sha256,
            "entry_count": len(ordered),
            "attempt_journal": self._journal().snapshot(),
            "post_run_validation": post_validation,
        }
        finalization_id_sha256 = sha256_bytes(canonical_json(finalization_core))
        core = {
            "schema_version": PROOF_SCHEMA_VERSION,
            "kind": "source-wheel-reproducibility-proof",
            "run_identity_sha256": self.identity_sha256,
            "discovery_input_sha256": self.discovery.sha256,
            "missing_required_evidence_sha256": self.discovery.missing_required_evidence_sha256,
            "entries_sha256": self.entries_sha256,
            "state_sha256": state_sha256,
            "source_wheel_policy_sha256": policy_sha256,
            "finalization_id_sha256": finalization_id_sha256,
            "post_run_validation": post_validation,
            "entry_count": len(ordered),
            "proof_runtime_starts": len(ordered) * RUNTIMES_PER_ENTRY,
            "runtime_roles_per_entry": ["target", "builder_a", "builder_b"],
            "max_concurrent_entries": self.config.max_concurrent_entries,
            "max_live_runtimes": self.config.max_live_runtimes,
            "telemetry": telemetry,
            "source": self.identity["source"],
            "execution": self.identity["execution"],
            "entries": ordered,
        }
        proof = {**core, "proof_sha256": sha256_bytes(canonical_json(core))}
        proof_payload = canonical_json(proof) + b"\n"
        finalization = {
            **finalization_core,
            "finalization_id_sha256": finalization_id_sha256,
            "proof_file_sha256": sha256_bytes(proof_payload),
        }
        finalization_payload = canonical_json(finalization) + b"\n"
        self._ensure_exact_artifact(self.finalization_path, finalization_payload)
        self._ensure_exact_artifact(self.proof_path, proof_payload)
        self._ensure_exact_artifact(self.final_policy_path, policy_payload)
        return {
            "entries": len(ordered),
            "runtime_starts": len(ordered) * RUNTIMES_PER_ENTRY,
            "input_sha256": self.discovery.sha256,
            "missing_evidence_sha256": self.discovery.missing_required_evidence_sha256,
            "policy_sha256": policy_sha256,
            "proof_sha256": sha256_bytes(proof_payload),
            "finalization_sha256": sha256_bytes(finalization_payload),
            "post_validation_sha256": post_validation["record_sha256"],
            "state_sha256": state_sha256,
            "peak_live_runtimes": int(telemetry["peak_live_runtimes"]),
            "peak_concurrent_entries": int(telemetry["peak_concurrent_entries"]),
        }


def validate_vacli_environment(config: SourceWheelProofConfig) -> None:
    expected = {
        "VACLI_LEASE_RETRIES": str(config.vacli_lease_retries),
        "VACLI_MAX_CONCURRENT_LEASES": str(config.vacli_max_concurrent_leases),
        "VACLI_MAX_PULL_RETRIES": str(config.vacli_max_pull_retries),
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": str(config.vacli_image_pull_timeout_seconds),
        "VACLI_CONTAINER_PRIVILEGED": str(config.vacli_container_privileged),
    }
    if any(os.environ.get(name) != value for name, value in expected.items()):
        raise SourceWheelProofError("vacli_environment_mismatch")
    vacli_path = Path(os.environ.get("VACLI_BIN", ""))
    if vacli_path != config.vacli_path:
        raise SourceWheelProofError("vacli_binary_invalid")
    try:
        digest = hashlib.sha256()
        with vacli_path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise SourceWheelProofError("vacli_binary_invalid") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or not os.access(vacli_path, os.X_OK)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or digest.hexdigest() != config.vacli_binary_sha256
    ):
        raise SourceWheelProofError("vacli_binary_invalid")


async def run_source_wheel_proof(
    config: SourceWheelProofConfig,
    *,
    runtime_factory: RuntimeFactory = _runtime_factory,
) -> dict[str, object]:
    if runtime_factory is _runtime_factory:
        validate_execution_environment(config)
        validate_vacli_environment(config)
    discovery, _ = load_private_discovery_input(config)
    with ProofStore(config, discovery) as store:
        runner = SourceWheelProofRunner(
            config,
            discovery,
            store._journal(),
            runtime_factory=runtime_factory,
        )

        def publish(key: str, proof: dict[str, object], telemetry: dict[str, int]) -> None:
            store.publish_entry(key, proof, telemetry)

        await runner.run_pending(store.completed, publish)
        store.record_peak_entries(runner.peak_entries)
        if runtime_factory is _runtime_factory:
            validate_execution_environment(config)
            validate_vacli_environment(config)
        store.record_post_run_validation()
        return store.publish_final()


def aggregate_failure(output_dir: Path, code: str) -> dict[str, object]:
    summary: dict[str, object] = {"status": "failed", "error_code": code}
    state_path = output_dir / "proof_state.json"
    if regular_private_file(state_path):
        payload = state_path.read_bytes()
        summary["state_sha256"] = sha256_bytes(payload)
        try:
            state = strict_json_loads(payload)
        except (UnicodeDecodeError, ValueError, RecursionError):
            return summary
        if isinstance(state, dict) and isinstance(state.get("completed"), dict):
            summary["completed_entries"] = len(state["completed"])
    return summary
