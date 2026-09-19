"""Fail-closed policy and artifact validation for oracle source-wheel recovery."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import uuid
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

try:
    from packaging.markers import UndefinedComparison, UndefinedEnvironmentName
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name
except ModuleNotFoundError:  # pragma: no cover - exercised inside minimal verifier images.
    from pip._vendor.packaging.markers import UndefinedComparison, UndefinedEnvironmentName
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement
    from pip._vendor.packaging.utils import canonicalize_name

SOURCE_WHEEL_POLICY_SCHEMA_VERSION = 3
SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION = 4
SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION = 2
SOURCE_WHEEL_RECOVERY_SCHEMA_VERSION = 2
MAX_SOURCE_INPUT_BYTES = 256 * 1024 * 1024
MAX_WHEEL_BYTES = 256 * 1024 * 1024
MAX_WHEELHOUSE_BYTES = 1024 * 1024 * 1024
MAX_WHEEL_FILES = 256
MAX_WHEEL_MEMBERS = 20_000
MAX_WHEEL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_SDIST_MEMBERS = 20_000
MAX_SDIST_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_SETUP_PY_BYTES = 2 * 1024 * 1024
SOURCE_BUILD_HOME_DIR = "/tmp/terminal-bench-source-build-home"
SOURCE_BUILD_TMP_DIR = "/tmp/terminal-bench-source-build-tmp"
SOURCE_BUILD_UMASK = 0o022
SOURCE_BUILD_ENVIRONMENT = {
    "HOME": SOURCE_BUILD_HOME_DIR,
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "SOURCE_DATE_EPOCH": "315532800",
    "TMPDIR": SOURCE_BUILD_TMP_DIR,
    "TZ": "UTC",
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST_RE = re.compile(r"[^\s@]+(?:[:][^\s@]+)?@sha256:[0-9a-f]{64}")
_SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
_EXACT_REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")
_SDIST_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".zip")


def canonical_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def strict_json_loads(payload: bytes | str) -> object:
    """Decode JSON while rejecting ambiguous keys and non-finite numbers."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        payload,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_digest_pinned_image(image: str) -> bool:
    return _IMAGE_DIGEST_RE.fullmatch(image) is not None


@dataclass(frozen=True)
class SourceArtifactPolicy:
    distribution: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str
    wheel_filename: str
    wheel_size: int
    wheel_sha256: str
    build_dependencies: tuple[BinaryWheelPolicy, ...] = ()


@dataclass(frozen=True)
class BinaryWheelPolicy:
    distribution: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceWheelPolicyEntry:
    requirements: tuple[str, ...]
    image: str
    build_tools: tuple[tuple[str, str], ...]
    sources: tuple[SourceArtifactPolicy, ...]
    binary_wheels: tuple[BinaryWheelPolicy, ...]

    @property
    def expected_wheels(self) -> tuple[tuple[str, str, str, int, str], ...]:
        wheels = [
            (
                source.distribution,
                source.version,
                source.wheel_filename,
                source.wheel_size,
                source.wheel_sha256,
            )
            for source in self.sources
        ]
        wheels.extend(
            (wheel.distribution, wheel.version, wheel.filename, wheel.size, wheel.sha256)
            for wheel in self.binary_wheels
        )
        return tuple(sorted(wheels, key=lambda item: item[2]))

    @property
    def build_dependency_wheels(self) -> tuple[BinaryWheelPolicy, ...]:
        return tuple(
            sorted(
                (wheel for source in self.sources for wheel in source.build_dependencies),
                key=lambda item: item.filename,
            )
        )


@dataclass(frozen=True)
class SourceWheelPolicy:
    path: Path
    sha256: str
    allowed_hosts: tuple[str, ...]
    entries: tuple[SourceWheelPolicyEntry, ...]

    def entry_for(
        self,
        requirements: tuple[str, ...],
        image: str,
        build_tools: tuple[tuple[str, str], ...],
    ) -> SourceWheelPolicyEntry:
        candidates = [entry for entry in self.entries if entry.requirements == requirements and entry.image == image]
        if not candidates:
            raise RuntimeError("source-wheel recovery is not allowlisted for this requirement/image pair")
        entry = candidates[0]
        if entry.build_tools != build_tools:
            raise RuntimeError("source-wheel builder tools do not match the approved image-pinned toolchain")
        return entry


@dataclass(frozen=True)
class WheelEvidence:
    distribution: str
    version: str
    filename: str
    size: int
    sha256: str
    universal: bool


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}")


def _validated_filename(value: object, label: str, *, suffixes: tuple[str, ...]) -> str:
    if not isinstance(value, str) or _SAFE_FILENAME_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe basename")
    if not value.lower().endswith(suffixes):
        raise ValueError(f"{label} has an unsupported artifact suffix")
    return value


def _validated_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _validated_size(value: object, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} bytes")
    return value


def _validated_distribution(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or canonical_distribution_name(value) != value:
        raise ValueError(f"{label} must be a canonical distribution name")
    return value


def _validated_version(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be a nonempty version without whitespace")
    return value


def _validated_url(value: object, allowed_hosts: set[str], label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{label} must be an HTTPS URL") from error
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
        raise ValueError(f"{label} must be a credential-free HTTPS URL on an approved host")
    return value


def validate_legacy_setup_requirement(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} must be a static requirement string")
    requirement_text = value.strip()
    if not requirement_text:
        raise RuntimeError(f"{label} must be nonempty")
    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement as error:
        raise RuntimeError(f"{label} is not a valid requirement") from error
    if requirement.url is not None or requirement.marker is not None:
        raise RuntimeError(f"{label} must not use direct URLs or environment markers")
    if canonicalize_name(requirement.name) != canonical_distribution_name(requirement.name):
        raise RuntimeError(f"{label} must use a canonical distribution name")
    return requirement_text


def validate_static_build_dependency_closure(
    setup_requires: tuple[str, ...],
    build_dependencies: tuple[BinaryWheelPolicy, ...],
    expected_build_tools: tuple[tuple[str, str], ...],
) -> None:
    if not build_dependencies:
        raise RuntimeError("source build dependency policy omits the isolated build-tool closure")
    available = {wheel.distribution: wheel.version for wheel in build_dependencies}
    if len(available) != len(build_dependencies):
        raise RuntimeError("source build dependency policy contains duplicate distributions")
    for index, requirement_text in enumerate(build_dependency_root_requirements(setup_requires, expected_build_tools)):
        requirement = Requirement(requirement_text)
        name = canonical_distribution_name(requirement.name)
        version = available.get(name)
        if version is None or (requirement.specifier and not requirement.specifier.contains(version, prereleases=True)):
            raise RuntimeError("source build dependency policy does not satisfy its exact roots")


def build_tool_requirements(expected_build_tools: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    tools = dict(expected_build_tools)
    if set(tools) != {"pip", "setuptools", "wheel"}:
        raise RuntimeError("source build tools must pin pip, setuptools, and wheel")
    requirements = tuple(f"{name}=={tools[name]}" for name in ("pip", "setuptools", "wheel"))
    if any(_EXACT_REQUIREMENT_RE.fullmatch(requirement) is None for requirement in requirements):
        raise RuntimeError("source build tools must use exact requirement-safe versions")
    return requirements


def build_dependency_root_requirements(
    setup_requires: tuple[str, ...],
    expected_build_tools: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    validated_setup = tuple(
        validate_legacy_setup_requirement(requirement, f"setup_requires[{index}]")
        for index, requirement in enumerate(setup_requires)
    )
    return (*build_tool_requirements(expected_build_tools), *validated_setup)


def build_dependency_artifact_records(
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> list[dict[str, object]]:
    return [
        {
            "distribution": wheel.distribution,
            "version": wheel.version,
            "filename": wheel.filename,
            "size": wheel.size,
            "sha256": wheel.sha256,
        }
        for wheel in sorted(build_dependencies, key=lambda item: item.filename)
    ]


def source_build_environment_variables(
    build_env_dir: str = "/tmp/terminal-bench-source-build-env",
) -> dict[str, str]:
    environment = dict(SOURCE_BUILD_ENVIRONMENT)
    environment["HOME"] = f"{build_env_dir}-home"
    environment["TMPDIR"] = f"{build_env_dir}-tmp"
    return environment


def _clean_build_environment_prefix(build_env_dir: str) -> list[str]:
    return [
        "/usr/bin/env",
        "-i",
        *[f"{name}={value}" for name, value in sorted(source_build_environment_variables(build_env_dir).items())],
    ]


SOURCE_BUILD_ENV_ATTEST_CODE = """
import hashlib, importlib.metadata as metadata, json, os, re, stat, sys, sysconfig

build_env = os.path.realpath(sys.argv[1])
expected_artifacts = json.loads(sys.argv[2])
expected_python = os.path.join(build_env, "bin", "python")
if os.path.abspath(sys.executable) != expected_python:
    raise RuntimeError("source build environment python mismatch")
if os.path.realpath(sys.prefix) != os.path.realpath(sys.base_prefix) or os.path.realpath(sys.base_prefix) == build_env:
    raise RuntimeError("source build environment prefix mismatch")
if not sys.flags.isolated or not sys.flags.ignore_environment or not sys.flags.no_user_site or not sys.flags.no_site:
    raise RuntimeError("source build environment is not isolated")
config_path = os.path.join(build_env, "pyvenv.cfg")
with open(config_path, "rb") as handle:
    config_payload = handle.read()
config = {}
for raw_line in config_payload.decode("utf-8").splitlines():
    if "=" not in raw_line:
        continue
    key, value = raw_line.split("=", 1)
    config[key.strip().casefold()] = value.strip().casefold()
if config.get("include-system-site-packages") != "false":
    raise RuntimeError("source build environment includes system site-packages")
path_variables = {"base": build_env, "platbase": build_env}
site_paths = sorted({
    os.path.realpath(sysconfig.get_path(name, scheme="venv", vars=path_variables))
    for name in ("purelib", "platlib")
})
if not site_paths or any(os.path.commonpath((build_env, path)) != build_env for path in site_paths):
    raise RuntimeError("source build environment site path escaped the venv")
stdlib = os.path.realpath(sysconfig.get_path("stdlib"))
stdlib_zip = os.path.join(
    os.path.dirname(stdlib),
    f"python{sys.version_info.major}{sys.version_info.minor}.zip",
)
allowed_import_roots = {stdlib, os.path.join(stdlib, "lib-dynload"), stdlib_zip, *site_paths}
sys.prefix = build_env
sys.exec_prefix = build_env
sys.path.extend(site_paths)
resolved_sys_path = []
for raw_path in sys.path:
    if not raw_path:
        raise RuntimeError("source build environment has an implicit current-directory import root")
    path = os.path.realpath(raw_path)
    if path not in allowed_import_roots:
        raise RuntimeError("source build environment has an unbound import root")
    resolved_sys_path.append(path)
if len(resolved_sys_path) != len(set(resolved_sys_path)):
    raise RuntimeError("source build environment has duplicate import roots")
if not isinstance(expected_artifacts, list) or not expected_artifacts:
    raise RuntimeError("source build dependency closure is empty")
expected_versions = {}
for artifact in expected_artifacts:
    if not isinstance(artifact, dict) or set(artifact) != {
        "distribution", "version", "filename", "size", "sha256"
    }:
        raise RuntimeError("source build dependency artifact record is invalid")
    distribution = artifact["distribution"]
    if (
        not isinstance(distribution, str)
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", distribution) is None
        or distribution in expected_versions
        or not isinstance(artifact["version"], str)
        or not artifact["version"]
        or not isinstance(artifact["filename"], str)
        or not artifact["filename"].endswith(".whl")
        or isinstance(artifact["size"], bool)
        or not isinstance(artifact["size"], int)
        or artifact["size"] < 1
        or not isinstance(artifact["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
    ):
        raise RuntimeError("source build dependency artifact record is invalid")
    expected_versions[distribution] = artifact["version"]
observed_versions = {}
installed_distributions = []
claimed_files = set()
installed_file_count = 0
installed_file_bytes = 0
for distribution in metadata.distributions(path=site_paths):
    names = distribution.metadata.get_all("Name", [])
    versions = distribution.metadata.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        raise RuntimeError("source build environment distribution metadata is ambiguous")
    name = re.sub(r"[-_.]+", "-", names[0].strip()).lower()
    version = versions[0].strip()
    location = os.path.realpath(distribution.locate_file(""))
    if (
        not name
        or not version
        or name in observed_versions
        or not any(os.path.commonpath((site_path, location)) == site_path for site_path in site_paths)
    ):
        raise RuntimeError("source build environment distribution closure is invalid")
    observed_versions[name] = version
    files = distribution.files
    if files is None or not files:
        raise RuntimeError("source build environment distribution has no installed-file manifest")
    file_records = []
    for relative in files:
        unresolved_path = os.path.abspath(distribution.locate_file(relative))
        path = os.path.realpath(unresolved_path)
        if (
            unresolved_path != path
            or os.path.commonpath((build_env, path)) != build_env
            or path in claimed_files
        ):
            raise RuntimeError("source build environment distribution file escaped or overlapped")
        status = os.lstat(unresolved_path)
        if not stat.S_ISREG(status.st_mode):
            raise RuntimeError("source build environment distribution file is not regular")
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        claimed_files.add(path)
        installed_file_count += 1
        installed_file_bytes += status.st_size
        if installed_file_count > 100000 or installed_file_bytes > 2147483648:
            raise RuntimeError("source build environment file manifest exceeds its bound")
        file_records.append({
            "path": os.path.relpath(path, build_env),
            "mode": stat.S_IMODE(status.st_mode),
            "size": status.st_size,
            "sha256": digest.hexdigest(),
        })
    file_records.sort(key=lambda item: item["path"])
    installed_distributions.append({
        "distribution": name,
        "version": version,
        "location": os.path.relpath(location, build_env),
        "file_count": len(file_records),
        "files_sha256": hashlib.sha256(
            json.dumps(file_records, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    })
if observed_versions != expected_versions:
    raise RuntimeError("source build environment distribution closure mismatch")
observed_site_files = set()
for site_path in site_paths:
    for current, directories, files in os.walk(site_path, followlinks=False):
        directories.sort()
        files.sort()
        for name in directories:
            if stat.S_ISLNK(os.lstat(os.path.join(current, name)).st_mode):
                raise RuntimeError("source build environment site closure contains a symlink")
        for name in files:
            unresolved_path = os.path.abspath(os.path.join(current, name))
            path = os.path.realpath(unresolved_path)
            if unresolved_path != path or not stat.S_ISREG(os.lstat(unresolved_path).st_mode):
                raise RuntimeError("source build environment site closure contains a non-regular file")
            observed_site_files.add(path)
if observed_site_files != {path for path in claimed_files if any(
    os.path.commonpath((site_path, path)) == site_path for site_path in site_paths
)}:
    raise RuntimeError("source build environment site closure contains unclaimed files")
build_tools = {name: observed_versions.get(name, "<missing>") for name in ("pip", "setuptools", "wheel")}
artifact_payload = json.dumps(expected_artifacts, separators=(",", ":"), sort_keys=True).encode()
print(json.dumps({
    "schema_version": 2,
    "executable": os.path.abspath(sys.executable),
    "prefix": os.path.realpath(sys.prefix),
    "base_prefix": os.path.realpath(sys.base_prefix),
    "isolated": True,
    "system_site_packages": False,
    "site_packages": site_paths,
    "sys_path_sha256": hashlib.sha256(
        json.dumps(resolved_sys_path, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest(),
    "pyvenv_cfg_sha256": hashlib.sha256(config_payload).hexdigest(),
    "artifact_closure_sha256": hashlib.sha256(artifact_payload).hexdigest(),
    "installed_distributions": sorted(installed_distributions, key=lambda item: item["distribution"]),
    "build_tools": build_tools,
}, separators=(",", ":"), sort_keys=True))
""".strip()


def source_build_environment_record(
    *,
    build_env_dir: str,
    expected_build_tools: tuple[tuple[str, str], ...],
    build_dependencies: tuple[BinaryWheelPolicy, ...],
    attestation: dict[str, object],
) -> dict[str, object]:
    artifacts = build_dependency_artifact_records(build_dependencies)
    return {
        "schema_version": SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION,
        "kind": "venv-no-system-site-exact-wheel-closure",
        "path": os.path.realpath(build_env_dir),
        "create_argv_sha256": sha256_bytes(canonical_json(source_build_env_create_argv(build_env_dir))),
        "install_argv_sha256": sha256_bytes(
            canonical_json(
                source_build_dependency_install_argv(
                    build_env_dir=build_env_dir,
                    build_dependency_dir="/tmp/terminal-bench-source-build-deps",
                    build_dependencies=build_dependencies,
                )
            )
        ),
        "attest_argv_sha256": sha256_bytes(
            canonical_json(source_build_env_attest_argv(build_env_dir, build_dependencies))
        ),
        "expected_build_tools": dict(expected_build_tools),
        "environment": source_build_environment_variables(build_env_dir),
        "environment_sha256": sha256_bytes(canonical_json(source_build_environment_variables(build_env_dir))),
        "umask": f"{SOURCE_BUILD_UMASK:04o}",
        "build_dependency_artifacts": artifacts,
        "build_dependency_closure_sha256": sha256_bytes(canonical_json(artifacts)),
        "attestation": attestation,
        "attestation_sha256": sha256_bytes(canonical_json(attestation)),
    }


def source_build_env_create_argv(build_env_dir: str) -> list[str]:
    return [
        "python3",
        "-I",
        "-B",
        "-m",
        "venv",
        "--clear",
        "--without-pip",
        build_env_dir,
    ]


def source_build_env_python(build_env_dir: str) -> str:
    return f"{build_env_dir}/bin/python"


def source_build_env_attest_argv(
    build_env_dir: str,
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> list[str]:
    return [
        source_build_env_python(build_env_dir),
        "-I",
        "-S",
        "-B",
        "-c",
        SOURCE_BUILD_ENV_ATTEST_CODE,
        build_env_dir,
        canonical_json(build_dependency_artifact_records(build_dependencies)).decode(),
    ]


def validate_source_build_environment(
    payload: bytes | str,
    *,
    build_env_dir: str,
    expected_build_tools: tuple[tuple[str, str], ...],
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> dict[str, object]:
    try:
        value = strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise RuntimeError("source build environment attestation is invalid") from error
    expected_tools = dict(expected_build_tools)
    expected_artifacts = build_dependency_artifact_records(build_dependencies)
    expected_versions = {
        wheel.distribution: wheel.version for wheel in sorted(build_dependencies, key=lambda item: item.distribution)
    }
    expected_env = os.path.realpath(build_env_dir)
    expected_python = os.path.join(expected_env, "bin", "python")
    site_packages = value.get("site_packages") if isinstance(value, dict) else None
    installed_distributions = value.get("installed_distributions") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "executable",
            "prefix",
            "base_prefix",
            "isolated",
            "system_site_packages",
            "site_packages",
            "sys_path_sha256",
            "pyvenv_cfg_sha256",
            "artifact_closure_sha256",
            "installed_distributions",
            "build_tools",
        }
        or value.get("schema_version") != SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION
        or value.get("executable") != expected_python
        or value.get("prefix") != expected_env
        or not isinstance(value.get("base_prefix"), str)
        or value.get("base_prefix") == expected_env
        or value.get("isolated") is not True
        or value.get("system_site_packages") is not False
        or not isinstance(site_packages, list)
        or not site_packages
        or len(site_packages) != len(set(site_packages))
        or not all(
            isinstance(path, str)
            and os.path.isabs(path)
            and os.path.commonpath((expected_env, os.path.realpath(path))) == expected_env
            and os.path.basename(path) in {"site-packages", "dist-packages"}
            for path in site_packages
        )
        or not isinstance(value.get("sys_path_sha256"), str)
        or _SHA256_RE.fullmatch(value["sys_path_sha256"]) is None
        or not isinstance(value.get("pyvenv_cfg_sha256"), str)
        or _SHA256_RE.fullmatch(value["pyvenv_cfg_sha256"]) is None
        or value.get("artifact_closure_sha256") != sha256_bytes(canonical_json(expected_artifacts))
        or not isinstance(installed_distributions, list)
        or len(installed_distributions) != len(expected_versions)
        or not all(
            isinstance(distribution, dict)
            and set(distribution)
            == {
                "distribution",
                "version",
                "location",
                "file_count",
                "files_sha256",
            }
            and isinstance(distribution.get("distribution"), str)
            and expected_versions.get(distribution["distribution"]) == distribution.get("version")
            and isinstance(distribution.get("location"), str)
            and bool(distribution["location"])
            and not os.path.isabs(distribution["location"])
            and ".." not in PurePosixPath(distribution["location"]).parts
            and any(
                os.path.commonpath(
                    (
                        os.path.realpath(path),
                        os.path.realpath(os.path.join(expected_env, distribution["location"])),
                    )
                )
                == os.path.realpath(path)
                for path in site_packages
            )
            and not isinstance(distribution.get("file_count"), bool)
            and isinstance(distribution.get("file_count"), int)
            and distribution["file_count"] > 0
            and isinstance(distribution.get("files_sha256"), str)
            and _SHA256_RE.fullmatch(distribution["files_sha256"]) is not None
            for distribution in installed_distributions
        )
        or [distribution["distribution"] for distribution in installed_distributions] != sorted(expected_versions)
        or value.get("build_tools") != expected_tools
    ):
        raise RuntimeError("source build environment attestation is invalid")
    return value


def validate_source_build_environment_record(
    value: object,
    *,
    build_env_dir: str,
    expected_build_tools: tuple[tuple[str, str], ...],
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "path",
        "create_argv_sha256",
        "install_argv_sha256",
        "attest_argv_sha256",
        "expected_build_tools",
        "environment",
        "environment_sha256",
        "umask",
        "build_dependency_artifacts",
        "build_dependency_closure_sha256",
        "attestation",
        "attestation_sha256",
    }:
        raise RuntimeError("source build environment record is invalid")
    attestation = value.get("attestation")
    if not isinstance(attestation, dict):
        raise RuntimeError("source build environment record is invalid")
    expected = source_build_environment_record(
        build_env_dir=build_env_dir,
        expected_build_tools=expected_build_tools,
        build_dependencies=build_dependencies,
        attestation=validate_source_build_environment(
            canonical_json(attestation),
            build_env_dir=build_env_dir,
            expected_build_tools=expected_build_tools,
            build_dependencies=build_dependencies,
        ),
    )
    if value != expected:
        raise RuntimeError("source build environment record is invalid")
    return expected


def source_build_dependency_install_argv(
    *,
    build_env_dir: str,
    build_dependency_dir: str,
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> list[str]:
    return [
        "python3",
        "-I",
        "-B",
        "-m",
        "pip",
        "--isolated",
        "--python",
        source_build_env_python(build_env_dir),
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--force-reinstall",
        "--no-compile",
        "--no-index",
        "--no-deps",
        *[
            f"{build_dependency_dir}/{wheel.filename}"
            for wheel in sorted(build_dependencies, key=lambda item: item.filename)
        ],
    ]


SOURCE_BUILD_RUNNER_CODE = """
import hashlib, io, json, os, runpy, shutil, stat, sys, sysconfig, tarfile, zipfile
from pathlib import PurePosixPath

build_env, source_path, work_dir, wheel_dir, expected_size, expected_sha256, max_members, max_bytes, expected_env, umask = sys.argv[1:]
build_env = os.path.realpath(build_env)
expected_size, max_members, max_bytes = int(expected_size), int(max_members), int(max_bytes)
if (
    os.path.abspath(sys.executable) != os.path.join(build_env, "bin", "python")
    or os.path.realpath(sys.prefix) != os.path.realpath(sys.base_prefix)
    or os.path.realpath(sys.base_prefix) == build_env
    or not sys.flags.isolated
    or not sys.flags.ignore_environment
    or not sys.flags.no_user_site
    or not sys.flags.no_site
):
    raise RuntimeError("source build backend python is not isolated")
expected_env = json.loads(expected_env)
if os.environ != expected_env:
    raise RuntimeError("source build backend environment is not the fixed allowlist")
os.umask(int(umask, 8))
path_variables = {"base": build_env, "platbase": build_env}
site_paths = sorted({
    os.path.realpath(sysconfig.get_path(name, scheme="venv", vars=path_variables))
    for name in ("purelib", "platlib")
})
if not site_paths or any(
    not os.path.isdir(path) or os.path.commonpath((build_env, path)) != build_env
    for path in site_paths
):
    raise RuntimeError("source build backend site path escaped the isolated environment")
for site_path in site_paths:
    for current, directories, files in os.walk(site_path, followlinks=False):
        if any(stat.S_ISLNK(os.lstat(os.path.join(current, name)).st_mode) for name in directories):
            raise RuntimeError("source build backend site closure contains a symlink")
        if any(not stat.S_ISREG(os.lstat(os.path.join(current, name)).st_mode) for name in files):
            raise RuntimeError("source build backend site closure contains a non-regular file")
sys.prefix = build_env
sys.exec_prefix = build_env
sys.path.extend(site_paths)
if os.path.exists(work_dir):
    raise RuntimeError("source build workspace already exists")
os.mkdir(work_dir, 0o700)
with open(source_path, "rb") as handle:
    source_payload = handle.read(max(expected_size + 1, 1))
if len(source_payload) != expected_size or hashlib.sha256(source_payload).hexdigest() != expected_sha256:
    raise RuntimeError("source build input integrity mismatch")
seen = set()
total_size = 0

def destination(name):
    if "\\\\" in name:
        raise RuntimeError("source build archive member is unsafe")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise RuntimeError("source build archive member is unsafe")
    normalized = "/".join(path.parts)
    if normalized in seen:
        raise RuntimeError("source build archive contains duplicate members")
    seen.add(normalized)
    output = os.path.realpath(os.path.join(work_dir, *path.parts))
    if os.path.commonpath((os.path.realpath(work_dir), output)) != os.path.realpath(work_dir):
        raise RuntimeError("source build archive member escaped its workspace")
    return output

def write_file(path, source, size, mode):
    global total_size
    if size < 0 or size > max_bytes:
        raise RuntimeError("source build archive member exceeds its bound")
    total_size += size
    if total_size > max_bytes:
        raise RuntimeError("source build archive exceeds its expansion bound")
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "xb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    if os.path.getsize(path) != size:
        raise RuntimeError("source build archive member size mismatch")
    os.chmod(path, 0o600 | (mode & 0o100))

if zipfile.is_zipfile(io.BytesIO(source_payload)):
    with zipfile.ZipFile(io.BytesIO(source_payload)) as archive:
        members = archive.infolist()
        if not members or len(members) > max_members:
            raise RuntimeError("source build archive member count is invalid")
        for member in members:
            mode = member.external_attr >> 16
            if member.flag_bits & 0x1 or stat.S_ISLNK(mode):
                raise RuntimeError("source build archive member is unsafe")
            path = destination(member.filename)
            if member.is_dir():
                os.makedirs(path, mode=0o700, exist_ok=True)
                continue
            with archive.open(member, "r") as source:
                write_file(path, source, member.file_size, mode)
else:
    with tarfile.open(fileobj=io.BytesIO(source_payload), mode="r:*") as archive:
        members = archive.getmembers()
        if not members or len(members) > max_members:
            raise RuntimeError("source build archive member count is invalid")
        for member in members:
            if not (member.isdir() or member.isfile()):
                raise RuntimeError("source build archive member is unsafe")
            path = destination(member.name)
            if member.isdir():
                os.makedirs(path, mode=0o700, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("source build archive member is unreadable")
            with source:
                write_file(path, source, member.size, member.mode)
roots = set()
for current, directories, files in os.walk(work_dir, followlinks=False):
    directories.sort()
    files.sort()
    relative = os.path.relpath(current, work_dir)
    parts = () if relative == "." else PurePosixPath(relative).parts
    if "PKG-INFO" in files and len(parts) <= 1:
        roots.add(os.path.realpath(current))
if len(roots) != 1:
    raise RuntimeError("source build archive root is ambiguous")
source_root = next(iter(roots))
setup_path = os.path.join(source_root, "setup.py")
if not stat.S_ISREG(os.lstat(setup_path).st_mode):
    raise RuntimeError("source build archive lacks a regular setup.py")
if os.path.exists(os.path.join(source_root, "pyproject.toml")) or os.path.exists(
    os.path.join(source_root, "setup.cfg")
):
    raise RuntimeError("source build archive has an unsupported build declaration")
os.chdir(source_root)
sys.path.insert(0, source_root)
sys.argv = [setup_path, "--quiet", "bdist_wheel", "--dist-dir", os.path.realpath(wheel_dir)]
runpy.run_path(setup_path, run_name="__main__")
""".strip()


def source_build_argv(
    source: SourceArtifactPolicy,
    *,
    input_dir: str,
    wheel_dir: str,
    build_env_dir: str,
) -> list[str]:
    source_path = f"{input_dir}/{source.filename}"
    return [
        *_clean_build_environment_prefix(build_env_dir),
        source_build_env_python(build_env_dir),
        "-I",
        "-S",
        "-B",
        "-c",
        SOURCE_BUILD_RUNNER_CODE,
        build_env_dir,
        source_path,
        f"{build_env_dir}-work",
        wheel_dir,
        str(source.size),
        source.sha256,
        str(MAX_SDIST_MEMBERS),
        str(MAX_SDIST_UNCOMPRESSED_BYTES),
        canonical_json(source_build_environment_variables(build_env_dir)).decode(),
        f"{SOURCE_BUILD_UMASK:04o}",
    ]


def _parse_source(
    raw: object,
    allowed_hosts: set[str],
    label: str,
) -> SourceArtifactPolicy:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_keys(
        raw,
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
        label,
    )
    raw_build_dependencies = raw["build_dependencies"]
    if not isinstance(raw_build_dependencies, list):
        raise ValueError(f"{label}.build_dependencies must be a list")
    build_dependencies = tuple(
        _parse_binary_wheel(wheel, allowed_hosts, f"{label}.build_dependencies[{index}]")
        for index, wheel in enumerate(raw_build_dependencies)
    )
    build_dependency_filenames = [wheel.filename for wheel in build_dependencies]
    build_dependency_distributions = [wheel.distribution for wheel in build_dependencies]
    if len(build_dependency_filenames) != len(set(build_dependency_filenames)):
        raise ValueError(f"{label}.build_dependencies has duplicate filenames")
    if len(build_dependency_distributions) != len(set(build_dependency_distributions)):
        raise ValueError(f"{label}.build_dependencies has duplicate distributions")
    return SourceArtifactPolicy(
        distribution=_validated_distribution(raw["distribution"], f"{label}.distribution"),
        version=_validated_version(raw["version"], f"{label}.version"),
        filename=_validated_filename(raw["filename"], f"{label}.filename", suffixes=_SDIST_SUFFIXES),
        url=_validated_url(raw["url"], allowed_hosts, f"{label}.url"),
        size=_validated_size(raw["size"], f"{label}.size", MAX_SOURCE_INPUT_BYTES),
        sha256=_validated_sha256(raw["sha256"], f"{label}.sha256"),
        wheel_filename=_validated_filename(
            raw["wheel_filename"],
            f"{label}.wheel_filename",
            suffixes=(".whl",),
        ),
        wheel_size=_validated_size(raw["wheel_size"], f"{label}.wheel_size", MAX_WHEEL_BYTES),
        wheel_sha256=_validated_sha256(raw["wheel_sha256"], f"{label}.wheel_sha256"),
        build_dependencies=build_dependencies,
    )


def _parse_binary_wheel(
    raw: object,
    allowed_hosts: set[str],
    label: str,
) -> BinaryWheelPolicy:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_keys(raw, {"distribution", "version", "filename", "url", "size", "sha256"}, label)
    return BinaryWheelPolicy(
        distribution=_validated_distribution(raw["distribution"], f"{label}.distribution"),
        version=_validated_version(raw["version"], f"{label}.version"),
        filename=_validated_filename(raw["filename"], f"{label}.filename", suffixes=(".whl",)),
        url=_validated_url(raw["url"], allowed_hosts, f"{label}.url"),
        size=_validated_size(raw["size"], f"{label}.size", MAX_WHEEL_BYTES),
        sha256=_validated_sha256(raw["sha256"], f"{label}.sha256"),
    )


def load_source_wheel_policy(path: Path, expected_sha256: str) -> SourceWheelPolicy:
    payload = path.read_bytes()
    observed_sha256 = sha256_bytes(payload)
    if observed_sha256 != expected_sha256:
        raise ValueError("source-wheel policy SHA-256 mismatch")

    try:
        raw = strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ValueError("source-wheel policy is not valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("source-wheel policy must be an object")
    _require_exact_keys(raw, {"schema_version", "allowed_hosts", "entries"}, "source-wheel policy")
    if raw["schema_version"] != SOURCE_WHEEL_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported source-wheel policy schema")
    hosts = raw["allowed_hosts"]
    if (
        not isinstance(hosts, list)
        or not hosts
        or not all(isinstance(host, str) and host and host == host.lower() for host in hosts)
        or len(hosts) != len(set(hosts))
    ):
        raise ValueError("source-wheel policy allowed_hosts must be unique lowercase hostnames")
    allowed_hosts = set(hosts)
    raw_entries = raw["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("source-wheel policy entries must be a nonempty list")
    entries: list[SourceWheelPolicyEntry] = []
    keys: set[tuple[tuple[str, ...], str]] = set()
    for entry_index, raw_entry in enumerate(raw_entries):
        label = f"source-wheel policy entry {entry_index}"
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{label} must be an object")
        _require_exact_keys(
            raw_entry,
            {"requirements", "image", "build_tools", "sources", "binary_wheels"},
            label,
        )
        requirements = raw_entry["requirements"]
        if (
            not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(item, str) and _EXACT_REQUIREMENT_RE.fullmatch(item) for item in requirements)
            or len(requirements) != len(set(requirements))
        ):
            raise ValueError(f"{label}.requirements must contain unique exact pins")
        requirement_tuple = tuple(requirements)
        image = raw_entry["image"]
        if not isinstance(image, str) or not is_digest_pinned_image(image):
            raise ValueError(f"{label}.image must be an immutable digest-pinned reference")
        tools = raw_entry["build_tools"]
        if not isinstance(tools, dict) or set(tools) != {"pip", "setuptools", "wheel"}:
            raise ValueError(f"{label}.build_tools must pin pip, setuptools, and wheel")
        if not all(
            isinstance(value, str) and value and not any(c.isspace() for c in value) for value in tools.values()
        ):
            raise ValueError(f"{label}.build_tools values must be exact nonempty versions")
        build_tools = tuple(sorted((str(key), str(value)) for key, value in tools.items()))
        raw_sources = raw_entry["sources"]
        raw_binary_wheels = raw_entry["binary_wheels"]
        if not isinstance(raw_sources, list) or len(raw_sources) != 1:
            raise ValueError(f"{label}.sources must contain exactly one source artifact")
        if not isinstance(raw_binary_wheels, list):
            raise ValueError(f"{label}.binary_wheels must be a list")
        sources = tuple(
            _parse_source(source, allowed_hosts, f"{label}.sources[{index}]")
            for index, source in enumerate(raw_sources)
        )
        for source in sources:
            try:
                validate_static_build_dependency_closure((), source.build_dependencies, build_tools)
            except RuntimeError as error:
                raise ValueError(f"{label} has an invalid isolated build-tool closure") from error
        binary_wheels = tuple(
            _parse_binary_wheel(wheel, allowed_hosts, f"{label}.binary_wheels[{index}]")
            for index, wheel in enumerate(raw_binary_wheels)
        )
        input_filenames = [source.filename for source in sources]
        input_filenames.extend(wheel.filename for source in sources for wheel in source.build_dependencies)
        input_filenames.extend(wheel.filename for wheel in binary_wheels)
        output_filenames = [source.wheel_filename for source in sources]
        output_filenames.extend(wheel.filename for wheel in binary_wheels)
        wheel_filenames = list(output_filenames)
        wheel_filenames.extend(wheel.filename for source in sources for wheel in source.build_dependencies)
        if len(input_filenames) != len(set(input_filenames)):
            raise ValueError(f"{label} has duplicate input filenames")
        if len(output_filenames) != len(set(output_filenames)):
            raise ValueError(f"{label} has duplicate wheel filenames")
        if len(wheel_filenames) != len(set(wheel_filenames)):
            raise ValueError(f"{label} has duplicate build/runtime wheel filenames")
        closure = {(source.distribution, source.version) for source in sources} | {
            (wheel.distribution, wheel.version) for wheel in binary_wheels
        }
        if len(closure) != len(output_filenames):
            raise ValueError(f"{label} has duplicate distributions in its wheel closure")
        for requirement in requirement_tuple:
            name, _, version = requirement.partition("==")
            name = name.partition("[")[0]
            if (canonical_distribution_name(name), version) not in closure:
                raise ValueError(f"{label} omits a root requirement from its wheel closure")
        key = (requirement_tuple, image)
        if key in keys:
            raise ValueError(f"{label} duplicates a requirement/image policy entry")
        keys.add(key)
        entries.append(
            SourceWheelPolicyEntry(
                requirements=requirement_tuple,
                image=image,
                build_tools=build_tools,
                sources=sources,
                binary_wheels=binary_wheels,
            )
        )
    return SourceWheelPolicy(
        path=path.resolve(),
        sha256=observed_sha256,
        allowed_hosts=tuple(hosts),
        entries=tuple(entries),
    )


def _safe_archive_member(name: str) -> bool:
    if "\\" in name:
        return False
    path = PurePosixPath(name)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def _inspect_wheel(filename: str, payload: bytes) -> tuple[WheelEvidence, tuple[str, ...]]:
    if len(payload) < 1 or len(payload) > MAX_WHEEL_BYTES:
        raise RuntimeError("wheel payload exceeds the bounded size contract")
    digest = sha256_bytes(payload)
    try:
        with ZipFile(io.BytesIO(payload)) as wheel:
            members = wheel.infolist()
            if not members or len(members) > MAX_WHEEL_MEMBERS:
                raise RuntimeError("wheel has an invalid member count")
            total_size = 0
            metadata_members = []
            wheel_members = []
            for member in members:
                member_mode = member.external_attr >> 16
                if not _safe_archive_member(member.filename) or member.flag_bits & 0x1 or stat.S_ISLNK(member_mode):
                    raise RuntimeError("wheel contains an unsafe archive member")
                if member.file_size < 0 or member.file_size > MAX_WHEEL_UNCOMPRESSED_BYTES:
                    raise RuntimeError("wheel member exceeds the bounded size contract")
                total_size += member.file_size
                if total_size > MAX_WHEEL_UNCOMPRESSED_BYTES:
                    raise RuntimeError("wheel exceeds the bounded expansion contract")
                if member.filename.endswith(".dist-info/METADATA"):
                    metadata_members.append(member)
                elif member.filename.endswith(".dist-info/WHEEL"):
                    wheel_members.append(member)
            if len(metadata_members) != 1 or len(wheel_members) != 1:
                raise RuntimeError("wheel must contain exactly one WHEEL and METADATA record")
            metadata_member = metadata_members[0]
            wheel_member = wheel_members[0]
            if PurePosixPath(metadata_member.filename).parent != PurePosixPath(wheel_member.filename).parent:
                raise RuntimeError("wheel metadata records belong to different distributions")
            if metadata_member.file_size > MAX_METADATA_BYTES or wheel_member.file_size > MAX_METADATA_BYTES:
                raise RuntimeError("wheel metadata exceeds the bounded size contract")
            metadata = BytesParser().parsebytes(wheel.read(metadata_member))
            wheel_metadata = BytesParser().parsebytes(wheel.read(wheel_member))
    except RuntimeError:
        raise
    except (BadZipFile, OSError) as error:
        raise RuntimeError("wheel archive validation failed") from error
    except Exception as error:
        raise RuntimeError("wheel archive validation failed") from error
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    wheel_versions = wheel_metadata.get_all("Wheel-Version", [])
    tags = wheel_metadata.get_all("Tag", [])
    if len(names) != 1 or len(versions) != 1 or len(wheel_versions) != 1 or not tags:
        raise RuntimeError("wheel metadata is incomplete or ambiguous")
    distribution = canonical_distribution_name(names[0].strip())
    version = versions[0].strip()
    if not distribution or not version or not wheel_versions[0].startswith("1."):
        raise RuntimeError("wheel metadata is invalid")
    raw_requirements = metadata.get_all("Requires-Dist", [])
    if not all(isinstance(requirement, str) and requirement.strip() for requirement in raw_requirements):
        raise RuntimeError("wheel dependency metadata is invalid")
    return (
        WheelEvidence(
            distribution=distribution,
            version=version,
            filename=filename,
            size=len(payload),
            sha256=digest,
            universal=all(tag.strip().endswith("-none-any") for tag in tags),
        ),
        tuple(requirement.strip() for requirement in raw_requirements),
    )


def inspect_wheel(filename: str, payload: bytes) -> WheelEvidence:
    return _inspect_wheel(filename, payload)[0]


def validate_build_dependency_payload_closure(
    setup_requires: tuple[str, ...],
    expected_build_tools: tuple[tuple[str, str], ...],
    build_dependencies: tuple[BinaryWheelPolicy, ...],
    payloads: dict[str, bytes],
    marker_environment: dict[str, str],
) -> str:
    validate_static_build_dependency_closure(
        setup_requires,
        build_dependencies,
        expected_build_tools,
    )
    if (
        not marker_environment
        or "extra" in marker_environment
        or not all(isinstance(key, str) and key and isinstance(value, str) for key, value in marker_environment.items())
    ):
        raise RuntimeError("source build dependency marker environment is invalid")
    if set(payloads) != {wheel.filename for wheel in build_dependencies}:
        raise RuntimeError("source build dependency payload closure does not match policy")
    policies = {wheel.distribution: wheel for wheel in build_dependencies}
    requirements_by_distribution: dict[str, tuple[Requirement, ...]] = {}
    for wheel in build_dependencies:
        evidence, raw_requirements = _inspect_wheel(wheel.filename, payloads[wheel.filename])
        if (
            evidence.distribution != wheel.distribution
            or evidence.version != wheel.version
            or evidence.size != wheel.size
            or evidence.sha256 != wheel.sha256
        ):
            raise RuntimeError("source build dependency wheel does not match policy")
        parsed: list[Requirement] = []
        for raw_requirement in raw_requirements:
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as error:
                raise RuntimeError("source build dependency metadata contains an invalid requirement") from error
            if requirement.url is not None:
                raise RuntimeError("source build dependency metadata contains a direct URL")
            parsed.append(requirement)
        requirements_by_distribution[wheel.distribution] = tuple(parsed)

    active_extras: dict[str, set[str]] = {}
    processed_extras: dict[str, frozenset[str]] = {}
    pending: list[str] = []

    def include(requirement: Requirement) -> None:
        distribution = canonical_distribution_name(requirement.name)
        policy = policies.get(distribution)
        if policy is None or (
            requirement.specifier and not requirement.specifier.contains(policy.version, prereleases=True)
        ):
            raise RuntimeError("source build dependency closure does not satisfy a requirement")
        extras = {extra.casefold() for extra in requirement.extras}
        previous = active_extras.setdefault(distribution, set())
        if distribution not in processed_extras or not extras.issubset(previous):
            previous.update(extras)
            pending.append(distribution)

    for requirement_text in build_dependency_root_requirements(setup_requires, expected_build_tools):
        include(Requirement(requirement_text))

    while pending:
        distribution = pending.pop()
        extras = frozenset(active_extras[distribution])
        if processed_extras.get(distribution) == extras:
            continue
        processed_extras[distribution] = extras
        marker_extras = extras or frozenset({""})
        for requirement in requirements_by_distribution[distribution]:
            if requirement.marker is not None:
                try:
                    applies = any(
                        requirement.marker.evaluate({**marker_environment, "extra": extra}) for extra in marker_extras
                    )
                except (KeyError, TypeError, UndefinedComparison, UndefinedEnvironmentName, ValueError) as error:
                    raise RuntimeError("source build dependency marker cannot be evaluated") from error
                if not applies:
                    continue
            include(requirement)
    if set(active_extras) != set(policies):
        raise RuntimeError("source build dependency policy contains an unreachable distribution")
    return sha256_bytes(canonical_json(build_dependency_artifact_records(build_dependencies)))


def inspect_source_distribution(
    source: SourceArtifactPolicy,
    payload: bytes,
) -> None:
    if len(payload) != source.size or sha256_bytes(payload) != source.sha256:
        raise RuntimeError("source distribution does not match its approved size and SHA-256")
    metadata_payloads: list[bytes] = []
    total_size = 0
    if source.filename.lower().endswith(".zip"):
        try:
            with ZipFile(io.BytesIO(payload)) as archive:
                members = archive.infolist()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    member_mode = member.external_attr >> 16
                    if not _safe_archive_member(member.filename) or member.flag_bits & 0x1 or stat.S_ISLNK(member_mode):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    total_size += member.file_size
                    if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
                        raise RuntimeError("source distribution exceeds the bounded expansion contract")
                    if member.filename.endswith("/PKG-INFO") or member.filename == "PKG-INFO":
                        if member.file_size > MAX_METADATA_BYTES:
                            raise RuntimeError("source distribution metadata exceeds the bounded size contract")
                        metadata_payloads.append(archive.read(member))
        except BadZipFile as error:
            raise RuntimeError("source distribution is not a valid ZIP archive") from error
    else:
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
                members = archive.getmembers()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    if member.isdir() and not PurePosixPath(member.name).parts:
                        continue
                    if not _safe_archive_member(member.name) or not (member.isdir() or member.isfile()):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    if member.isfile():
                        total_size += member.size
                        if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
                            raise RuntimeError("source distribution exceeds the bounded expansion contract")
                    if member.name.endswith("/PKG-INFO") or member.name == "PKG-INFO":
                        if not member.isfile() or member.size > MAX_METADATA_BYTES:
                            raise RuntimeError("source distribution metadata exceeds the bounded size contract")
                        handle = archive.extractfile(member)
                        if handle is None:
                            raise RuntimeError("source distribution metadata could not be read")
                        metadata_payloads.append(handle.read())
        except tarfile.TarError as error:
            raise RuntimeError("source distribution is not a valid tar archive") from error
    if not metadata_payloads:
        raise RuntimeError("source distribution must contain at least one PKG-INFO record")
    for metadata_payload in metadata_payloads:
        metadata = BytesParser().parsebytes(metadata_payload)
        names = metadata.get_all("Name", [])
        versions = metadata.get_all("Version", [])
        if (
            len(names) != 1
            or len(versions) != 1
            or canonical_distribution_name(names[0].strip()) != source.distribution
            or versions[0].strip() != source.version
        ):
            raise RuntimeError("source distribution metadata does not match the approved policy")


def _source_archive_named_payloads(source: SourceArtifactPolicy, payload: bytes, wanted: set[str]) -> dict[str, bytes]:
    if len(payload) != source.size or sha256_bytes(payload) != source.sha256:
        raise RuntimeError("source distribution does not match its approved size and SHA-256")
    found: dict[str, bytes] = {}
    canonical_roots: set[tuple[str, ...]] = set()
    candidate_members: list[tuple[str, bytes]] = []
    total_size = 0

    def consider(name: str, size: int, reader: object) -> None:
        nonlocal total_size
        total_size += size
        if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
            raise RuntimeError("source distribution exceeds the bounded expansion contract")
        parts = PurePosixPath(name).parts
        if not parts:
            return
        basename = parts[-1]
        if basename == "PKG-INFO" and len(parts) in {1, 2}:
            canonical_roots.add(parts[:-1])
        if basename not in wanted:
            return
        if size > MAX_SETUP_PY_BYTES:
            raise RuntimeError("source distribution setup metadata exceeds the bounded size contract")
        candidate_members.append((name, reader()))  # type: ignore[operator]

    if source.filename.lower().endswith(".zip"):
        try:
            with ZipFile(io.BytesIO(payload)) as archive:
                members = archive.infolist()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    member_mode = member.external_attr >> 16
                    if not _safe_archive_member(member.filename) or member.flag_bits & 0x1 or stat.S_ISLNK(member_mode):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    consider(member.filename, member.file_size, lambda member=member: archive.read(member))
        except BadZipFile as error:
            raise RuntimeError("source distribution is not a valid ZIP archive") from error
    else:
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
                members = archive.getmembers()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    if member.isdir() and not PurePosixPath(member.name).parts:
                        continue
                    if not _safe_archive_member(member.name) or not (member.isdir() or member.isfile()):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    if not member.isfile():
                        continue

                    def read_member(member: tarfile.TarInfo = member) -> bytes:
                        handle = archive.extractfile(member)
                        if handle is None:
                            raise RuntimeError("source distribution metadata could not be read")
                        return handle.read()

                    consider(member.name, member.size, read_member)
        except tarfile.TarError as error:
            raise RuntimeError("source distribution is not a valid tar archive") from error
    if len(canonical_roots) != 1:
        raise RuntimeError("source distribution contains ambiguous setup metadata")
    canonical_root = next(iter(canonical_roots))
    for name, payload in candidate_members:
        parts = PurePosixPath(name).parts
        basename = parts[-1]
        if parts[:-1] != canonical_root:
            continue
        if basename in found:
            raise RuntimeError("source distribution contains ambiguous setup metadata")
        found[basename] = payload
    return found


def extract_static_setup_requires(source: SourceArtifactPolicy, payload: bytes) -> tuple[str, ...]:
    inspect_source_distribution(source, payload)
    named = _source_archive_named_payloads(source, payload, {"setup.py", "setup.cfg", "pyproject.toml"})
    if "pyproject.toml" in named or "setup.cfg" in named:
        raise RuntimeError("source-wheel proof supports only self-contained legacy setup.py declarations")
    setup_payload = named.get("setup.py")
    if setup_payload is None:
        raise RuntimeError("legacy source distribution is missing setup.py")
    try:
        tree = ast.parse(setup_payload.decode("utf-8"), filename="setup.py")
    except (SyntaxError, UnicodeDecodeError) as error:
        raise RuntimeError("legacy setup.py cannot be parsed safely") from error
    direct_imports = 0
    module_imports = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.partition(".")[0]
                if alias.name == "setuptools" and alias.asname is None:
                    module_imports += 1
                elif bound_name in {"setup", "setuptools"}:
                    raise RuntimeError("legacy setup.py has an ambiguous setup import")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    raise RuntimeError("legacy setup.py must not use wildcard imports")
                bound_name = alias.asname or alias.name
                if node.module == "setuptools" and alias.name == "setup" and alias.asname is None:
                    direct_imports += 1
                elif bound_name in {"setup", "setuptools"}:
                    raise RuntimeError("legacy setup.py has an ambiguous setup import")
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and node.id
            in {
                "setup",
                "setuptools",
            }
        ):
            raise RuntimeError("legacy setup.py must not rebind its setup callable")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in {
            "setup",
            "setuptools",
        }:
            raise RuntimeError("legacy setup.py must not rebind its setup callable")

    top_level_calls = [
        statement.value
        for statement in tree.body
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    ]
    direct_calls = [call for call in top_level_calls if isinstance(call.func, ast.Name) and call.func.id == "setup"]
    module_calls = [
        call
        for call in top_level_calls
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "setuptools"
        and call.func.attr == "setup"
    ]
    if len(direct_calls) == 1 and not module_calls and direct_imports == 1 and module_imports == 0:
        setup_call = direct_calls[0]
    elif len(module_calls) == 1 and not direct_calls and module_imports == 1 and direct_imports == 0:
        setup_call = module_calls[0]
    else:
        raise RuntimeError("legacy setup.py must contain one unaliased top-level setuptools setup() call")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if node is setup_call:
                continue
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "setup"
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "setup"
                or any(isinstance(item, ast.Constant) and item.value == "setup" for item in ast.walk(node.func))
            ):
                raise RuntimeError("legacy setup.py contains an ambiguous setup call")
        elif isinstance(node, ast.Name) and node.id == "setup" and isinstance(node.ctx, ast.Load):
            if node is not setup_call.func:
                raise RuntimeError("legacy setup.py contains an ambiguous setup reference")
        elif isinstance(node, ast.Attribute) and node.attr == "setup":
            if node is not setup_call.func:
                raise RuntimeError("legacy setup.py contains an ambiguous setup reference")
    if setup_call.args or any(keyword.arg is None for keyword in setup_call.keywords):
        raise RuntimeError("legacy setup.py setup() arguments must be explicit keywords")
    matches = [keyword for keyword in setup_call.keywords if keyword.arg == "setup_requires"]
    if len(matches) > 1:
        raise RuntimeError("legacy setup.py has ambiguous setup_requires")
    if not matches:
        return ()
    value = matches[0].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        raw_requirements: list[object] = [value.value]
    elif isinstance(value, (ast.List, ast.Tuple)):
        raw_requirements = [item.value if isinstance(item, ast.Constant) else item for item in value.elts]
    else:
        raise RuntimeError("legacy setup_requires must be a static literal")
    requirements = tuple(
        validate_legacy_setup_requirement(item, f"setup_requires[{index}]")
        for index, item in enumerate(raw_requirements)
    )
    if len(requirements) != len(set(requirements)):
        raise RuntimeError("legacy setup_requires contains duplicate requirements")
    return requirements


def inspect_wheelhouse(wheel_archive: bytes) -> tuple[WheelEvidence, ...]:
    if len(wheel_archive) < 1 or len(wheel_archive) > MAX_WHEELHOUSE_BYTES:
        raise RuntimeError("prefetched verifier wheelhouse exceeds the bounded size contract")
    evidence: list[WheelEvidence] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(wheel_archive), mode="r:") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_WHEEL_FILES:
                raise RuntimeError("prefetched verifier wheelhouse has an invalid member count")
            for member in members:
                parts = PurePosixPath(member.name).parts
                if member.isdir() and not parts:
                    continue
                if (
                    not member.isfile()
                    or len(parts) != 1
                    or not _safe_archive_member(member.name)
                    or not member.name.lower().endswith(".whl")
                    or member.size < 1
                    or member.size > MAX_WHEEL_BYTES
                ):
                    raise RuntimeError("prefetched verifier wheelhouse contained an invalid archive member")
                handle = archive.extractfile(member)
                if handle is None:
                    raise RuntimeError("prefetched verifier wheelhouse member could not be read")
                evidence.append(inspect_wheel(parts[0], handle.read()))
    except (tarfile.TarError, OSError) as error:
        raise RuntimeError("prefetched verifier wheelhouse is not a valid tar archive") from error
    if not evidence:
        raise RuntimeError("prefetched verifier wheelhouse archive was empty")
    filenames = [item.filename for item in evidence]
    distributions = [(item.distribution, item.version) for item in evidence]
    if len(filenames) != len(set(filenames)) or len(distributions) != len(set(distributions)):
        raise RuntimeError("prefetched verifier wheelhouse contains duplicate artifacts")
    return tuple(sorted(evidence, key=lambda item: item.filename))


def pack_wheelhouse(wheels: dict[str, bytes]) -> bytes:
    if not wheels or len(wheels) > MAX_WHEEL_FILES:
        raise RuntimeError("source-built verifier wheelhouse has an invalid file count")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for filename in sorted(wheels):
            payload = wheels[filename]
            _validated_filename(filename, "wheel filename", suffixes=(".whl",))
            if len(payload) < 1 or len(payload) > MAX_WHEEL_BYTES:
                raise RuntimeError("source-built wheel exceeds the bounded size contract")
            member = tarfile.TarInfo(filename)
            member.size = len(payload)
            member.mode = 0o444
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    payload = output.getvalue()
    if len(payload) > MAX_WHEELHOUSE_BYTES:
        raise RuntimeError("source-built verifier wheelhouse exceeds the bounded size contract")
    return payload


def validate_policy_wheel_closure(
    entry: SourceWheelPolicyEntry,
    wheels: dict[str, bytes],
) -> tuple[WheelEvidence, ...]:
    expected = {
        filename: (distribution, version, size, sha256)
        for distribution, version, filename, size, sha256 in entry.expected_wheels
    }
    if set(wheels) != set(expected):
        raise RuntimeError("source-built wheel closure does not match the explicit policy allowlist")
    evidence = tuple(
        sorted((inspect_wheel(filename, payload) for filename, payload in wheels.items()), key=lambda x: x.filename)
    )
    for item in evidence:
        distribution, version, size, digest = expected[item.filename]
        if item.distribution != distribution or item.version != version or item.size != size or item.sha256 != digest:
            raise RuntimeError("source-built wheel closure does not match the approved artifact evidence")
    return evidence


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not replace:
            raise FileExistsError(path)
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def regular_private_file(path: Path) -> bool:
    try:
        status = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(status.st_mode) and stat.S_IMODE(status.st_mode) in {0o400, 0o600}


def wheel_evidence_dicts(evidence: tuple[WheelEvidence, ...]) -> list[dict[str, object]]:
    return [asdict(item) for item in evidence]
