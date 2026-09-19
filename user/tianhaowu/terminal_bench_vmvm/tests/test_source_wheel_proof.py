from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import stat
import struct
import subprocess
import sys
import sysconfig
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import prove_source_wheel_policy as proof_cli
import pytest
import source_wheel_proof_bootstrap as proof_bootstrap
import terminal_bench_vmvm.source_wheel_proof as source_wheel_proof
from terminal_bench_vmvm.source_wheel_proof import (
    APPROVED_BASE_RUNTIME_COMMIT,
    BINARY_DIR,
    BUILD_DEP_DIR,
    BUILD_ENV_DIR,
    BUILD_PIP_REPORT_PATH,
    CLEAN_TREE_SHA256,
    DISCOVERY_DOWNLOAD_CODE,
    FINGERPRINT_PROBE,
    INPUT_DIR,
    PIP_REPORT_PATH,
    RESOLVER_DIR,
    TARGET_SITE_DIR,
    WHEEL_DIR,
    WHEEL_DIRECTORY_PROBE,
    BuildResult,
    ProofStore,
    SourceWheelProofConfig,
    SourceWheelProofError,
    SourceWheelProofRunner,
    aggregate_diagnostic_failure,
    aggregate_failure,
    compare_build_payloads,
    load_private_discovery_input,
    run_source_wheel_proof,
    validate_execution_environment,
    validate_vacli_environment,
)
from terminal_bench_vmvm.source_wheels import (
    SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION,
    SOURCE_BUILD_RUNNER_CODE,
    WHEEL_SEMANTIC_DIGEST_KIND,
    WHEEL_SEMANTIC_DIGEST_SCHEMA_VERSION,
    WHEEL_SEMANTIC_NORMALIZED_FIELDS,
    BinaryWheelPolicy,
    SourceArtifactPolicy,
    SourceWheelContractError,
    build_dependency_artifact_records,
    canonical_json,
    extract_static_build_requirements,
    inspect_source_distribution,
    inspect_wheel,
    pack_wheelhouse,
    sha256_bytes,
    source_build_dependency_install_argv,
    source_build_env_attest_argv,
    source_build_env_create_argv,
    source_build_environment_record,
    validate_source_build_environment,
    wheel_semantic_sha256,
)
from terminal_bench_vmvm.taskset import _SOURCE_WHEEL_CLOSURE_CODE, _SOURCE_WHEEL_DOWNLOAD_CODE
from verifiers.v1.runtimes import ProgramResult, VMVMConfig
from vmvm_tb_v2._vacli.backend import (
    BackendInitError,
    VacliVMVMBackend,
    _extract_vacli_lease_response,
    _vacli_lease_identity_sha256,
)

BUILD_TOOLS = {"pip": "24.3.1", "setuptools": "75.6.0", "wheel": "0.45.1"}
DIAGNOSTIC_FAILURE_COUNT_KEYS = {
    "candidate_failures",
    "entries_checked",
    "peak_concurrent_entries",
    "peak_live_runtimes",
    "runtime_starts",
    "successful_entries",
}
DIAGNOSTIC_OUTPUT_MODES = {
    ".writer.lock": 0o600,
    "attempt_journal": 0o700,
    "candidate_diagnostics_state.json": 0o600,
    "run_identity.json": 0o400,
    "source_wheel_candidate.json": 0o400,
}


def _wheel_file(distribution: str, version: str, *requirements: str) -> bytes:
    wheel_distribution = distribution.replace("-", "_")
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{wheel_distribution}-{version}.dist-info"
        metadata = ["Metadata-Version: 2.1", f"Name: {distribution}", f"Version: {version}"]
        metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
        wheel.writestr(f"{metadata_dir}/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: proof-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return output.getvalue()


def _retime_wheel(payload: bytes, timestamp: tuple[int, int, int, int, int, int]) -> bytes:
    output = io.BytesIO()
    with ZipFile(io.BytesIO(payload)) as source, ZipFile(output, mode="w") as destination:
        for member in source.infolist():
            info = ZipInfo(member.filename, timestamp)
            info.compress_type = member.compress_type
            info.external_attr = member.external_attr
            destination.writestr(info, source.read(member))
    return output.getvalue()


def _baseline_build_dependencies() -> tuple[tuple[str, str, str, str, bytes], ...]:
    records = (
        ("pip", BUILD_TOOLS["pip"], ()),
        ("setuptools", BUILD_TOOLS["setuptools"], ()),
        ("wheel", BUILD_TOOLS["wheel"], ("packaging>=24",)),
        ("packaging", "24.2", ()),
    )
    return tuple(
        (
            distribution,
            version,
            f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
            f"https://files.example.invalid/{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
            _wheel_file(distribution, version, *requirements),
        )
        for distribution, version, requirements in records
    )


def _source_file(
    distribution: str,
    *setup_requires: str,
    setup_cfg_requires: tuple[str, ...] = (),
    pyproject_requires: tuple[str, ...] = (),
) -> bytes:
    source_distribution = distribution.replace("-", "_")
    metadata = f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n".encode()
    setup_requires_clause = f", setup_requires={list(setup_requires)!r}" if setup_requires else ""
    setup = (
        f"from setuptools import setup\nsetup(name={distribution!r}, version='1.0'{setup_requires_clause})\n"
    ).encode()
    members = [
        (f"{source_distribution}-1.0/PKG-INFO", metadata),
        (f"{source_distribution}-1.0/setup.py", setup),
    ]
    if setup_cfg_requires:
        members.append(
            (
                f"{source_distribution}-1.0/setup.cfg",
                ("[options]\nsetup_requires =\n" + "".join(f"    {item}\n" for item in setup_cfg_requires)).encode(),
            )
        )
    if pyproject_requires:
        members.append(
            (
                f"{source_distribution}-1.0/pyproject.toml",
                (
                    f"[build-system]\nrequires = {list(pyproject_requires)!r}\n"
                    "build-backend = 'setuptools.build_meta'\n"
                ).encode(),
            )
        )
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, payload in members:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def _source_file_with_configuration(
    distribution: str,
    setup_py: bytes,
    *,
    setup_cfg: bytes | None = None,
    pyproject: bytes | None = None,
) -> bytes:
    source_distribution = distribution.replace("-", "_")
    members = [
        (
            f"{source_distribution}-1.0/PKG-INFO",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n".encode(),
        ),
        (f"{source_distribution}-1.0/setup.py", setup_py),
    ]
    if setup_cfg is not None:
        members.append((f"{source_distribution}-1.0/setup.cfg", setup_cfg))
    if pyproject is not None:
        members.append((f"{source_distribution}-1.0/pyproject.toml", pyproject))
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, payload in members:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def _source_zip_with_corrupt_setup_member(
    distribution: str,
    *,
    unsupported_compression: bool = False,
) -> bytes:
    source_distribution = distribution.replace("-", "_")
    root = f"{source_distribution}-1.0"
    output = io.BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr(
            f"{root}/PKG-INFO",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n",
            compress_type=8,
        )
        archive.writestr(
            f"{root}/setup.py",
            b"from setuptools import setup\nsetup(name='broken')\n# " + b"padding" * 256,
            compress_type=8,
        )
    payload = bytearray(output.getvalue())
    with ZipFile(io.BytesIO(payload)) as archive:
        member = archive.getinfo(f"{root}/setup.py")
        name_size, extra_size = struct.unpack_from("<HH", payload, member.header_offset + 26)
        data_start = member.header_offset + 30 + name_size + extra_size
        if unsupported_compression:
            central_name = payload.find(f"{root}/setup.py".encode(), archive.start_dir)
            assert central_name >= archive.start_dir + 46
            struct.pack_into("<H", payload, member.header_offset + 8, 99)
            struct.pack_into("<H", payload, central_name - 46 + 10, 99)
        else:
            payload[data_start + member.compress_size // 2] ^= 0xFF
    return bytes(payload)


def _source_zip_with_negative_member_offset(distribution: str) -> bytes:
    source_distribution = distribution.replace("-", "_")
    root = f"{source_distribution}-1.0"
    output = io.BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr(
            f"{root}/PKG-INFO",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n",
        )
        archive.writestr(
            f"{root}/setup.py",
            b"from setuptools import setup\nsetup(name='offset-test', version='1.0')\n",
        )
    payload = bytearray(output.getvalue())
    with ZipFile(io.BytesIO(payload)) as archive:
        member = archive.getinfo(f"{root}/setup.py")
        name_size, extra_size = struct.unpack_from("<HH", payload, member.header_offset + 26)
        data_start = member.header_offset + 30 + name_size + extra_size
    del payload[data_start]
    return bytes(payload)


@dataclass(frozen=True)
class FakeArtifacts:
    source_distribution: str
    source_filename: str
    source: bytes
    source_wheel_filename: str
    source_wheel: bytes
    binary_distribution: str
    binary_filename: str
    binary_url: str
    binary_wheel: bytes
    build_dependencies: tuple[tuple[str, str, str, str, bytes], ...] = ()

    @property
    def closure(self) -> list[list[str]]:
        return sorted([[self.source_distribution, "1.0"], [self.binary_distribution, "2.0"]])


def _discovery_payload(entry_count: int) -> tuple[bytes, dict[str, FakeArtifacts]]:
    entries = []
    artifacts = {}
    for index in range(entry_count):
        source_distribution = f"proof-package-{index}"
        binary_distribution = f"proof-helper-{index}"
        source_stem = source_distribution.replace("-", "_")
        binary_stem = binary_distribution.replace("-", "_")
        setup_requires = (
            ("build-helper-one==0.1", "build-helper-two==0.2")
            if index == 0
            else ("build-helper-three==0.3",)
            if index == 1
            else ()
        )
        if index == 0:
            source = _source_file(
                source_distribution,
                setup_cfg_requires=setup_requires[:1],
                pyproject_requires=setup_requires[1:],
            )
        else:
            source = _source_file(source_distribution, *setup_requires)
        source_wheel = _wheel_file(source_distribution, "1.0")
        source_is_transitive = index % 3 == 0
        binary_wheel = _wheel_file(
            binary_distribution,
            "2.0",
            *([f"{source_distribution}>=1.0"] if source_is_transitive else []),
        )
        source_filename = f"{source_stem}-1.0.tar.gz"
        source_wheel_filename = f"{source_stem}-1.0-py3-none-any.whl"
        binary_filename = f"{binary_stem}-2.0-py3-none-any.whl"
        binary_url = f"https://files.example.invalid/{binary_filename}"
        declared_build_dependencies = tuple(
            (
                requirement.partition("==")[0],
                requirement.partition("==")[2],
                f"{requirement.partition('==')[0].replace('-', '_')}-{requirement.partition('==')[2]}-py3-none-any.whl",
                f"https://files.example.invalid/"
                f"{requirement.partition('==')[0].replace('-', '_')}-{requirement.partition('==')[2]}-py3-none-any.whl",
                _wheel_file(requirement.partition("==")[0], requirement.partition("==")[2]),
            )
            for requirement in setup_requires
        )
        build_dependencies = (*_baseline_build_dependencies(), *declared_build_dependencies)
        image_digest = hashlib.sha256(f"image-{index}".encode()).hexdigest()
        image = f"registry.example.invalid/proof@sha256:{image_digest}"
        source_record = {
            "distribution": source_distribution,
            "version": "1.0",
            "filename": source_filename,
            "url": f"https://files.example.invalid/{source_filename}",
            "size": len(source),
            "sha256": sha256_bytes(source),
            "source_spec": (f"{source_distribution}>=1.0" if source_is_transitive else f"{source_distribution}==1.0"),
            "source_spec_exact": not source_is_transitive,
            "version_selection": "exact",
            "pkg_info_records": 1,
            "pkg_info_identity_agreement": True,
        }
        identity = sha256_bytes(canonical_json([index, image, source_record]))
        entries.append(
            {
                "task": f"private-task-{index}",
                "entry_identity_sha256": identity,
                "requirements": (
                    [f"{binary_distribution}==2.0"]
                    if source_is_transitive
                    else [f"{source_distribution}==1.0", f"{binary_distribution}==2.0"]
                ),
                "image": image,
                "source": source_record,
                "build_tools": None,
                "built_source_wheel": None,
                "binary_wheels": None,
                "reproducibility": None,
                "ready_for_policy": False,
            }
        )
        artifacts[image] = FakeArtifacts(
            source_distribution=source_distribution,
            source_filename=source_filename,
            source=source,
            source_wheel_filename=source_wheel_filename,
            source_wheel=source_wheel,
            binary_distribution=binary_distribution,
            binary_filename=binary_filename,
            binary_url=binary_url,
            binary_wheel=binary_wheel,
            build_dependencies=build_dependencies,
        )
    discovery = {
        "schema_version": 1,
        "kind": "source-wheel-policy-probe-input",
        "complete": False,
        "missing_required_evidence": ["runtime", "toolchain", "wheel", "closure"],
        "provenance": {
            "dataset_revision": "d" * 40,
            "image_manifest_sha256": "e" * 64,
            "oracle_results_sha256": "f" * 64,
        },
        "allowed_hosts": ["files.example.invalid"],
        "entries": entries,
    }
    return canonical_json(discovery) + b"\n", artifacts


def _write_discovery(
    tmp_path: Path,
    entry_count: int,
) -> tuple[Path, dict[str, FakeArtifacts]]:
    private = tmp_path / "private"
    private.mkdir(mode=0o700, parents=True)
    private.chmod(0o700)
    payload, artifacts = _discovery_payload(entry_count)
    path = private / "discovery.json"
    path.write_bytes(payload)
    path.chmod(0o600)
    return path, artifacts


def _replace_discovery_sources(
    discovery: Path,
    artifacts: dict[str, FakeArtifacts],
    replacements: dict[str, bytes],
    filenames: dict[str, str] | None = None,
) -> None:
    value = json.loads(discovery.read_bytes())
    for entry in value["entries"]:
        image = entry["image"]
        if image not in replacements:
            continue
        payload = replacements[image]
        entry["source"]["size"] = len(payload)
        entry["source"]["sha256"] = sha256_bytes(payload)
        filename = filenames.get(image, artifacts[image].source_filename) if filenames is not None else None
        if filename is not None:
            entry["source"]["filename"] = filename
        artifacts[image] = replace(
            artifacts[image],
            source=payload,
            source_filename=filename or artifacts[image].source_filename,
        )
    discovery.write_bytes(canonical_json(value) + b"\n")


def _config(discovery: Path, output: Path, **changes: object) -> SourceWheelProofConfig:
    missing = json.loads(discovery.read_bytes())["missing_required_evidence"]
    project = Path.cwd().resolve()
    config = SourceWheelProofConfig(
        input_path=discovery,
        input_sha256=sha256_bytes(discovery.read_bytes()),
        output_dir=output,
        expected_entry_count=9,
        expected_missing_evidence_sha256=sha256_bytes(canonical_json(missing)),
        project_dir=project,
        canonical_launcher_path=project / "unused-launcher",
        executed_launcher_path=project / "unused-launcher",
        uv_path=project / "unused-uv",
        python_path=Path(sys.executable).resolve(),
        python_stdlib_path=Path(sysconfig.get_path("stdlib")).resolve(),
        site_packages_path=project / "unused-site-packages",
        vacli_path=project / "unused-vacli",
        launcher_sha256="6" * 64,
        uv_sha256="7" * 64,
        python_sha256="8" * 64,
        python_runtime_manifest_sha256="9" * 64,
        site_packages_manifest_sha256="0" * 64,
        base_runtime_commit=APPROVED_BASE_RUNTIME_COMMIT,
        source_commit="a" * 40,
        source_git_tree="1" * 40,
        source_tree_sha256=CLEAN_TREE_SHA256,
        verifiers_commit="b" * 40,
        renderers_commit="c" * 40,
        pydantic_config_commit="d" * 40,
        vmvm_tb_v2_sha256="e" * 64,
        vacli_binary_sha256="f" * 64,
        invocation_host="worker.example.invalid",
        slurm_job_id="12345",
    )
    return replace(config, **changes)


def _proof_cli_args(config: SourceWheelProofConfig) -> SimpleNamespace:
    values = dict(config.__dict__)
    values.update(
        discovery_input=config.input_path,
        discovery_input_sha256=config.input_sha256,
    )
    return SimpleNamespace(**values)


def _diagnostic_failure_state_payload() -> bytes:
    return (
        canonical_json(
            {
                "schema_version": 1,
                "kind": "source-wheel-candidate-diagnostics-state",
                "outcomes": {
                    "private-entry-identity": {
                        "status": "candidate_rejected",
                        "error_code": "wheel_zip_structure_invalid",
                    },
                    "second-private-entry-identity": {"status": "passed", "error_code": None},
                },
                "run_identity_sha256": "a" * 64,
                "discovery_input_sha256": "b" * 64,
                "entries_sha256": "c" * 64,
                "entry_count": 9,
                "invocation": {"host": "/private/diagnostic/path"},
                "status": "aborted",
                "failure_counts": {"wheel_zip_structure_invalid": 1},
                "attempt_journal": {
                    "record_count": 18,
                    "head_sha256": "d" * 64,
                    "start_intents": 6,
                    "successful_starts": 6,
                },
                "telemetry": {
                    "attested_runtime_starts": 6,
                    "peak_starting_runtimes": 2,
                    "peak_live_runtimes": 3,
                    "peak_concurrent_entries": 1,
                },
            }
        )
        + b"\n"
    )


def _fingerprint_payload() -> str:
    return json.dumps(
        {
            "marker_environment": {
                "implementation_name": "cpython",
                "implementation_version": "3.12.0",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_release": "6.8.0",
                "platform_system": "Linux",
                "platform_version": "proof-runtime",
                "python_full_version": "3.12.0",
                "platform_python_implementation": "CPython",
                "python_version": "3.12",
                "sys_platform": "linux",
            },
            "pip_version": BUILD_TOOLS["pip"],
            "wheel_compatibility": [
                "cpython",
                [3, 12],
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
                "x86_64",
            ],
            "build_tools": BUILD_TOOLS,
        },
        sort_keys=True,
    )


def _build_dependency_policies(artifact: FakeArtifacts) -> tuple[BinaryWheelPolicy, ...]:
    return tuple(
        BinaryWheelPolicy(
            distribution=distribution,
            version=version,
            filename=filename,
            url=url,
            size=len(payload),
            sha256=sha256_bytes(payload),
        )
        for distribution, version, filename, url, payload in artifact.build_dependencies
    )


def _build_environment_attestation(
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> str:
    build_env = os.path.realpath(BUILD_ENV_DIR)
    artifacts = build_dependency_artifact_records(build_dependencies)
    bin_entries = [
        {
            "name": name,
            "kind": "regular",
            "mode": 0o755,
            "size": 1,
            "sha256": "4" * 64,
            "claimed": False,
        }
        for name in ("python", "python3")
    ]
    return json.dumps(
        {
            "schema_version": SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION,
            "executable": f"{build_env}/bin/python",
            "prefix": build_env,
            "base_prefix": "/usr",
            "isolated": True,
            "system_site_packages": False,
            "site_packages": [f"{build_env}/lib/python3.12/site-packages"],
            "sys_path_sha256": "1" * 64,
            "pyvenv_cfg_sha256": "2" * 64,
            "artifact_closure_sha256": sha256_bytes(canonical_json(artifacts)),
            "installed_distributions": [
                {
                    "distribution": wheel.distribution,
                    "version": wheel.version,
                    "location": "lib/python3.12/site-packages",
                    "file_count": 1,
                    "files_sha256": "3" * 64,
                }
                for wheel in sorted(build_dependencies, key=lambda item: item.distribution)
            ],
            "bin_path": f"{build_env}/bin",
            "bin_mode": 0o755,
            "bin_entries": bin_entries,
            "bin_executables": ["python", "python3"],
            "bin_sha256": sha256_bytes(canonical_json(bin_entries)),
            "build_tools": BUILD_TOOLS,
        },
        sort_keys=True,
    )


def _build_environment_record(
    build_dependencies: tuple[BinaryWheelPolicy, ...],
) -> dict[str, object]:
    return source_build_environment_record(
        build_env_dir=BUILD_ENV_DIR,
        expected_build_tools=tuple(sorted(BUILD_TOOLS.items())),
        build_dependencies=build_dependencies,
        attestation=json.loads(_build_environment_attestation(build_dependencies)),
    )


@pytest.mark.parametrize(
    "mutation",
    ("nul_resolved_path", "surrogate_target", "control_target", "format_target", "unhashable_site_path"),
)
def test_source_build_attestation_rejects_path_encoding_without_builtin_escape(mutation: str) -> None:
    _, artifacts = _discovery_payload(9)
    build_dependencies = _build_dependency_policies(next(iter(artifacts.values())))
    attestation = json.loads(_build_environment_attestation(build_dependencies))
    if mutation == "unhashable_site_path":
        attestation["site_packages"] = [[]]
    else:
        attestation["bin_entries"][0] = {
            "name": "python",
            "kind": "python-symlink",
            "mode": 0o777,
            "target": {
                "surrogate_target": "\ud800",
                "control_target": "python\u0085",
                "format_target": "python\u202e",
            }.get(mutation, "python3"),
            "resolved_path": "/usr/bin/python3\0hidden" if mutation == "nul_resolved_path" else "/usr/bin/python3",
            "sha256": "4" * 64,
        }

    with pytest.raises(RuntimeError, match="^source build environment attestation is invalid$"):
        validate_source_build_environment(
            json.dumps(attestation),
            build_env_dir=BUILD_ENV_DIR,
            expected_build_tools=tuple(sorted(BUILD_TOOLS.items())),
            build_dependencies=build_dependencies,
        )


class FakeFleet:
    def __init__(
        self,
        artifacts: dict[str, FakeArtifacts],
        *,
        block_builds: bool = False,
        block_starts: bool = False,
        duplicate_descriptors: bool = False,
        alternate_builder_wheels: dict[str, bytes] | None = None,
        fail_stops: bool = False,
        corrupt_source_reads: bool = False,
    ) -> None:
        self.artifacts = artifacts
        self.block_builds = block_builds
        self.block_starts = block_starts
        self.duplicate_descriptors = duplicate_descriptors
        self.alternate_builder_wheels = alternate_builder_wheels or {}
        self.fail_stops = fail_stops
        self.corrupt_source_reads = corrupt_source_reads
        self.release_builds = asyncio.Event()
        self.release_starts = asyncio.Event()
        self.two_builds_entered = asyncio.Event()
        self.all_starts_entered = asyncio.Event()
        self.builds_entered = 0
        self.starts_entered = 0
        self.runtimes: list[FakeRuntime] = []
        self.start_count = 0
        self.source_download_count = 0
        self.binary_download_count = 0
        self.build_dependency_download_count = 0
        self.resolution_count = 0
        self.build_dependency_resolution_count = 0
        self.live = 0
        self.peak_live = 0

    def factory(self, config: VMVMConfig, name: str) -> FakeRuntime:
        runtime = FakeRuntime(self, config, name)
        self.runtimes.append(runtime)
        return runtime


class FakeRuntime:
    def __init__(self, fleet: FakeFleet, config: VMVMConfig, name: str) -> None:
        self.fleet = fleet
        self.config = config
        self.name = name
        raw_identity = "duplicate-lease" if fleet.duplicate_descriptors else f"lease-{name}"
        self.descriptor = "container-id-must-not-be-used"
        self.backend = SimpleNamespace(
            lease_identity_sha256=sha256_bytes(canonical_json(["vacli-session-identity-v1", raw_identity]))
        )
        self.files: dict[str, bytes] = {}
        self.started = False
        self.stopped = False
        self.network_mode: str | None = None
        self.network_active = False
        self.build_count = 0

    @property
    def artifact(self) -> FakeArtifacts:
        return self.fleet.artifacts[self.config.image]

    async def start(self) -> None:
        self.fleet.starts_entered += 1
        if self.fleet.starts_entered >= 3:
            self.fleet.all_starts_entered.set()
        if self.fleet.block_starts:
            await self.fleet.release_starts.wait()
        self.started = True
        self.fleet.start_count += 1
        self.fleet.live += 1
        self.fleet.peak_live = max(self.fleet.peak_live, self.fleet.live)
        await asyncio.sleep(0)

    async def stop(self) -> None:
        if self.started and not self.stopped:
            if self.fleet.fail_stops:
                raise RuntimeError("synthetic private stop detail")
            self.stopped = True
            self.fleet.live -= 1
        await asyncio.sleep(0)

    async def configure_network_policy(self, mode: str) -> None:
        assert mode == "no-network"
        self.network_mode = mode

    async def activate_network_policy(self) -> None:
        assert self.network_mode == "no-network"
        self.network_active = True

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        assert self.started and not self.stopped
        if argv[:4] == ["python3", "-I", "-c", _SOURCE_WHEEL_DOWNLOAD_CODE]:
            assert env == {}
            assert not self.network_active
            self.fleet.source_download_count += 1
            self.files[argv[5]] = self.artifact.source
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:4] == ["python3", "-I", "-c", DISCOVERY_DOWNLOAD_CODE]:
            assert env == {}
            assert not self.network_active
            destination = argv[5]
            build_dependency_payloads = {
                filename: payload for _, _, filename, _, payload in self.artifact.build_dependencies
            }
            filename = Path(destination).name
            if destination.startswith(f"{BUILD_DEP_DIR}/"):
                self.fleet.build_dependency_download_count += 1
                self.files[destination] = build_dependency_payloads[filename]
            else:
                self.fleet.binary_download_count += 1
                self.files[destination] = self.artifact.binary_wheel
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv == ["python3", "-I", "-c", FINGERPRINT_PROBE]:
            assert env == {}
            assert self.network_active
            return ProgramResult(exit_code=0, stdout=_fingerprint_payload(), stderr="")
        if argv == source_build_env_create_argv(BUILD_ENV_DIR):
            assert env == {}
            assert self.network_active
            return ProgramResult(exit_code=0, stdout="", stderr="")
        build_dependency_policies = _build_dependency_policies(self.artifact)
        if argv == source_build_env_attest_argv(BUILD_ENV_DIR, build_dependency_policies):
            assert env == {}
            assert self.network_active
            return ProgramResult(
                exit_code=0,
                stdout=_build_environment_attestation(build_dependency_policies),
                stderr="",
            )
        if argv == source_build_dependency_install_argv(
            build_env_dir=BUILD_ENV_DIR,
            build_dependency_dir=BUILD_DEP_DIR,
            build_dependencies=build_dependency_policies,
        ):
            assert env == {"PIP_NO_INDEX": "1"}
            assert self.network_active
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if SOURCE_BUILD_RUNNER_CODE in argv:
            assert env == {}
            assert self.network_active
            runner_index = argv.index(SOURCE_BUILD_RUNNER_CODE)
            assert argv[runner_index - 5 : runner_index] == [
                f"{BUILD_ENV_DIR}/bin/python",
                "-I",
                "-S",
                "-B",
                "-c",
            ]
            self.build_count += 1
            self.fleet.builds_entered += 1
            if self.fleet.builds_entered >= 2:
                self.fleet.two_builds_entered.set()
            if self.fleet.block_builds and self.fleet.builds_entered >= 2:
                await self.fleet.release_builds.wait()
            source_wheel = self.artifact.source_wheel
            if self.name.endswith("builder-b"):
                source_wheel = self.fleet.alternate_builder_wheels.get(self.config.image, source_wheel)
            self.files[f"{WHEEL_DIR}/{self.artifact.source_wheel_filename}"] = source_wheel
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:5] == ["python3", "-I", "-m", "pip", "install"] and "--dry-run" in argv:
            assert env == {}
            assert not self.network_active
            report_path = argv[argv.index("--report") + 1]
            if report_path == BUILD_PIP_REPORT_PATH:
                self.fleet.build_dependency_resolution_count += 1
                report = {
                    "version": "1",
                    "install": [
                        {
                            "download_info": {
                                "url": url,
                                "archive_info": {"hashes": {"sha256": sha256_bytes(payload)}},
                            },
                            "metadata": {"name": distribution, "version": version},
                        }
                        for distribution, version, _, url, payload in self.artifact.build_dependencies
                    ],
                }
                self.files[BUILD_PIP_REPORT_PATH] = canonical_json(report)
                return ProgramResult(exit_code=0, stdout="", stderr="")
            self.fleet.resolution_count += 1
            report = {
                "version": "1",
                "install": [
                    {
                        "download_info": {
                            "url": f"file://{RESOLVER_DIR}/{self.artifact.source_wheel_filename}",
                            "archive_info": {"hashes": {"sha256": sha256_bytes(self.artifact.source_wheel)}},
                        },
                        "metadata": {"name": self.artifact.source_distribution, "version": "1.0"},
                    },
                    {
                        "download_info": {
                            "url": self.artifact.binary_url,
                            "archive_info": {"hashes": {"sha256": sha256_bytes(self.artifact.binary_wheel)}},
                        },
                        "metadata": {"name": self.artifact.binary_distribution, "version": "2.0"},
                    },
                ],
            }
            self.files[PIP_REPORT_PATH] = canonical_json(report)
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:4] == ["python3", "-I", "-c", WHEEL_DIRECTORY_PROBE]:
            assert env == {}
            prefix = f"{WHEEL_DIR}/"
            records = [
                {"filename": path.removeprefix(prefix), "size": len(payload), "sha256": sha256_bytes(payload)}
                for path, payload in sorted(self.files.items())
                if path.startswith(prefix)
            ]
            return ProgramResult(exit_code=0, stdout=json.dumps(records), stderr="")
        if argv[:4] == ["python3", "-I", "-c", _SOURCE_WHEEL_CLOSURE_CODE]:
            assert env == {}
            assert self.network_active
            return ProgramResult(exit_code=0, stdout=json.dumps(self.artifact.closure), stderr="")
        if argv[:2] == ["sh", "-c"]:
            assert env == {}
            command = argv[2]
            if command.startswith(f"rm -rf {INPUT_DIR} {BINARY_DIR} {BUILD_DEP_DIR}"):
                if "mkdir -p" not in command:
                    self.files.clear()
                return ProgramResult(exit_code=0, stdout="", stderr="")
            if "PIP_NO_INDEX=1" in command:
                assert self.network_active
                return ProgramResult(exit_code=0, stdout="", stderr="")
            if TARGET_SITE_DIR in command:
                assert self.network_active
                return ProgramResult(exit_code=0, stdout="", stderr="")
        raise AssertionError("unexpected fake-runtime command")

    async def read(self, path: str) -> bytes:
        if self.fleet.corrupt_source_reads and path == f"{INPUT_DIR}/{self.artifact.source_filename}":
            return b"synthetic-corrupt-source"
        return self.files[path]

    async def write(self, path: str, data: bytes) -> None:
        self.files[path] = data


def test_nine_entry_discovery_emits_policy_with_exactly_twenty_seven_starts(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts)

    result = asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=fleet.factory))

    assert result["entries"] == 9
    assert result["runtime_starts"] == 27
    assert result["peak_live_runtimes"] == 6
    assert result["peak_concurrent_entries"] == 2
    assert fleet.start_count == 27
    assert fleet.peak_live == 6
    assert fleet.live == 0
    assert len(fleet.runtimes) == 27
    assert all(runtime.stopped and runtime.network_active for runtime in fleet.runtimes)
    assert sum(runtime.build_count for runtime in fleet.runtimes) == 18
    assert fleet.source_download_count == 18
    assert fleet.binary_download_count == 9
    assert fleet.build_dependency_download_count == 39
    assert fleet.resolution_count == 9
    assert fleet.build_dependency_resolution_count == 9
    assert all(runtime.build_count == 0 for runtime in fleet.runtimes if runtime.name.endswith("-target"))
    assert all(runtime.build_count == 1 for runtime in fleet.runtimes if "-builder-" in runtime.name)

    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    expected_modes = {
        ".writer.lock": 0o600,
        "attempt_journal": 0o700,
        "finalization.json": 0o400,
        "post_run_validation.json": 0o400,
        "proof_state.json": 0o600,
        "run_identity.json": 0o400,
        "source_wheel_candidate.json": 0o400,
        "source_wheel_policy.json": 0o400,
        "source_wheel_proof.json": 0o400,
    }
    assert {path.name for path in output.iterdir()} == set(expected_modes)
    assert {path.name: stat.S_IMODE(path.stat().st_mode) for path in output.iterdir()} == expected_modes
    candidate = json.loads((output / "source_wheel_candidate.json").read_bytes())
    identity_payload = (output / "run_identity.json").read_bytes()
    identity = json.loads(identity_payload)
    proof = json.loads((output / "source_wheel_proof.json").read_bytes())
    policy = json.loads((output / "source_wheel_policy.json").read_bytes())
    state = json.loads((output / "proof_state.json").read_bytes())
    assert candidate["runnable"] is False
    assert candidate["schema_version"] == 5
    assert "diagnostic_only" not in candidate
    assert candidate["required_runtime_starts"] == 27
    assert "schema_bound_semantically_identical_wheels" in candidate["required_proofs"]
    assert identity["contract_schemas"]["source_build_environment"] == SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION
    assert identity["schema_version"] == 5
    assert "mode" not in identity
    assert "candidate_diagnostics_state" not in identity["contract_schemas"]
    assert identity["contract_schemas"]["candidate"] == 5
    assert identity["contract_schemas"]["wheel_semantic_digest"] == WHEEL_SEMANTIC_DIGEST_SCHEMA_VERSION
    assert identity["reproducibility"]["kind"] == WHEEL_SEMANTIC_DIGEST_KIND
    assert identity["reproducibility"]["normalized_zip_fields"] == list(WHEEL_SEMANTIC_NORMALIZED_FIELDS)
    assert identity["reproducibility"]["all_other_wheel_bytes_bound"] is True
    assert identity["source_build_execution"]["child_process_path"] == "venv-bin-only"
    assert identity["source_build_execution"]["source_import_precedence"] == "stdlib-attested-sites-source-root"
    assert proof["proof_runtime_starts"] == 27
    assert state["telemetry"]["attested_runtime_starts"] == 27
    assert state["attempt_journal"]["start_intents"] == 27
    assert state["attempt_journal"]["successful_starts"] == 27
    assert state["attempt_journal"]["record_count"] == 81
    journal_files = sorted((output / "attempt_journal").iterdir())
    assert len(journal_files) == 81
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in journal_files)
    assert proof["source"]["approved_base_runtime_commit"] == APPROVED_BASE_RUNTIME_COMMIT
    assert proof["source"]["commit"] == "a" * 40
    assert proof["source"]["git_tree"] == "1" * 40
    assert proof["source"] == identity["source"]
    assert proof["run_identity_sha256"] == sha256_bytes(identity_payload)
    assert proof["discovery_input_sha256"] == sha256_bytes(discovery.read_bytes())
    assert proof["source"]["verifiers_commit"] == "b" * 40
    assert proof["source"]["renderers_commit"] == "c" * 40
    assert proof["source"]["pydantic_config_commit"] == "d" * 40
    assert proof["source"]["vmvm_tb_v2_sha256"] == "e" * 64
    assert proof["execution"]["vacli_binary_sha256"] == "f" * 64
    assert proof["execution"] == identity["execution"]
    assert proof["source_wheel_policy_sha256"] == sha256_bytes((output / "source_wheel_policy.json").read_bytes())
    finalization_payload = (output / "finalization.json").read_bytes()
    finalization = json.loads(finalization_payload)
    post_validation_payload = (output / "post_run_validation.json").read_bytes()
    post_validation = json.loads(post_validation_payload)
    assert result["finalization_sha256"] == sha256_bytes(finalization_payload)
    assert finalization["proof_file_sha256"] == sha256_bytes((output / "source_wheel_proof.json").read_bytes())
    assert finalization["source_wheel_policy_sha256"] == proof["source_wheel_policy_sha256"]
    assert finalization["post_run_validation"] == state["post_run_validation"]
    assert proof["post_run_validation"] == state["post_run_validation"]
    assert state["post_run_validation"]["record_sha256"] == sha256_bytes(post_validation_payload)
    assert post_validation["validation_id_sha256"] == state["post_run_validation"]["validation_id_sha256"]
    prevalidation_state = dict(state)
    prevalidation_state["post_run_validation"] = None
    assert post_validation["prevalidation_state_sha256"] == sha256_bytes(canonical_json(prevalidation_state) + b"\n")
    assert post_validation["attempt_journal"] == state["attempt_journal"]
    assert len(policy["entries"]) == 9
    assert all(entry["build_tools"] == BUILD_TOOLS for entry in policy["entries"])
    assert all(len(entry["binary_wheels"]) == 1 for entry in policy["entries"])
    assert sum(len(entry["sources"][0]["build_dependencies"]) for entry in policy["entries"]) == 39
    assert sum(entry["resolution"]["build_dependencies"]["binary_artifact_count"] for entry in proof["entries"]) == 39
    assert (
        sum(len(entry["resolution"]["build_dependencies"]["declared_build_requirements"]) for entry in proof["entries"])
        == 3
    )
    assert all(entry["cross_builder"]["wheel_bytes_equal"] for entry in proof["entries"])
    assert all(entry["cross_builder"]["wheel_semantics_equal"] for entry in proof["entries"])
    assert all(len(set(entry["lease_identity_sha256s"].values())) == 3 for entry in proof["entries"])
    assert len({digest for entry in proof["entries"] for digest in entry["lease_identity_sha256s"].values()}) == 27
    assert b"lease-source-proof" not in (output / "source_wheel_proof.json").read_bytes()
    assert b"lease-source-proof" not in b"".join(path.read_bytes() for path in journal_files)
    assert b"container-id-must-not-be-used" not in (output / "source_wheel_proof.json").read_bytes()

    state_sha256 = sha256_bytes((output / "proof_state.json").read_bytes())
    resumed_fleet = FakeFleet(artifacts)
    resumed = _config(
        discovery,
        output,
        resume_state_sha256=state_sha256,
        slurm_job_id="12346",
    )
    assert asyncio.run(run_source_wheel_proof(resumed, runtime_factory=resumed_fleet.factory)) == result
    assert resumed_fleet.start_count == 0


def test_candidate_diagnostics_aggregate_only_candidate_local_failures(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    images = list(artifacts)
    replacements = {
        images[0]: _source_file_with_configuration(
            artifacts[images[0]].source_distribution,
            b"import setuptools\nsetuptools.setup(name='static-module-form', version='1.0')\n",
        ),
        images[1]: _source_file_with_configuration(
            artifacts[images[1]].source_distribution,
            b"from setuptools import setup\nNAME = 'dynamic'\nsetup(name=NAME, version='1.0')\n",
        ),
        images[2]: _source_file_with_configuration(
            artifacts[images[2]].source_distribution,
            b"from setuptools import setup\nsetup(name='static-project-table', version='1.0')\n",
            pyproject=(
                b"[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
                b"[project]\nname = 'static-project-table'\nversion = '1.0'\n"
            ),
        ),
    }
    _replace_discovery_sources(discovery, artifacts, replacements)
    artifacts[images[3]] = replace(artifacts[images[3]], source_wheel=b"not-a-wheel")
    output = tmp_path / "diagnostics"
    config = _config(discovery, output, candidate_diagnostics_only=True)
    fleet = FakeFleet(artifacts)

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=fleet.factory))

    assert result == {
        "diagnostic_only": True,
        "entries_checked": 9,
        "candidate_failures": 4,
        "successful_entries": 5,
        "failure_counts": {
            "source_pyproject_unsupported_static_form": 1,
            "source_setup_py_dynamic_or_ambiguous": 1,
            "source_setup_py_unsupported_static_form": 1,
            "wheel_zip_structure_invalid": 1,
        },
        "runtime_starts": 27,
        "peak_live_runtimes": 6,
        "peak_concurrent_entries": 2,
    }
    assert fleet.start_count == 27
    state = json.loads((output / "candidate_diagnostics_state.json").read_bytes())
    assert state["status"] == "complete"
    assert len(state["outcomes"]) == 9
    assert state["failure_counts"] == result["failure_counts"]
    assert state["attempt_journal"] == {
        "record_count": 81,
        "head_sha256": state["attempt_journal"]["head_sha256"],
        "start_intents": 27,
        "successful_starts": 27,
    }
    assert state["telemetry"]["attested_runtime_starts"] == 27
    assert not (output / "proof_state.json").exists()
    assert not (output / "post_run_validation.json").exists()
    assert not (output / "finalization.json").exists()
    assert not (output / "source_wheel_proof.json").exists()
    assert not (output / "source_wheel_policy.json").exists()
    assert json.loads((output / "source_wheel_candidate.json").read_bytes())["diagnostic_only"] is True
    diagnostic_identity = json.loads((output / "run_identity.json").read_bytes())
    assert diagnostic_identity["schema_version"] == 6
    assert diagnostic_identity["mode"] == "candidate-diagnostics"
    assert diagnostic_identity["contract_schemas"]["candidate"] == 6
    assert diagnostic_identity["contract_schemas"]["candidate_diagnostics_state"] == 1
    assert stat.S_ISDIR(output.lstat().st_mode)
    assert stat.S_IMODE(output.lstat().st_mode) == 0o700
    assert {path.name: stat.S_IMODE(path.lstat().st_mode) for path in output.iterdir()} == DIAGNOSTIC_OUTPUT_MODES

    public_summary = proof_cli.diagnostic_public_summary(
        result,
        source_wheel_proof.SOURCE_WHEEL_CANDIDATE_ERROR_CODES,
    )
    assert set(public_summary) == {"status", "counts", "failure_counts"}
    serialized_summary = json.dumps(public_summary, sort_keys=True)
    assert "private-task" not in serialized_summary
    assert "entry_key_sha256" not in serialized_summary
    assert "lease_identity" not in serialized_summary
    assert "static-module-form" not in serialized_summary

    with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_output_not_fresh$"):
        asyncio.run(run_source_wheel_proof(config, runtime_factory=FakeFleet(artifacts).factory))
    with pytest.raises(SourceWheelProofError, match="^output_directory_contains_unknown_artifact$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, output),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )
    with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_resume_forbidden$"):
        asyncio.run(
            run_source_wheel_proof(
                replace(config, output_dir=tmp_path / "resume-forbidden", resume_state_sha256="a" * 64),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )


@pytest.mark.parametrize(
    "failure_kind",
    ("candidate_declaration", "source_wheel", "build_dependency_wheel", "binary_wheel"),
)
def test_normal_proof_keeps_legacy_generic_contract_rejections(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    first_image = next(iter(artifacts))
    if failure_kind == "candidate_declaration":
        replacement = _source_file_with_configuration(
            artifacts[first_image].source_distribution,
            b"from setuptools import setup\nNAME = 'dynamic'\nsetup(name=NAME, version='1.0')\n",
        )
        _replace_discovery_sources(discovery, artifacts, {first_image: replacement})
    elif failure_kind == "source_wheel":
        artifacts[first_image] = replace(artifacts[first_image], source_wheel=b"not-a-wheel")
    elif failure_kind == "build_dependency_wheel":
        dependencies = list(artifacts[first_image].build_dependencies)
        distribution, version, filename, url, _ = dependencies[0]
        dependencies[0] = (distribution, version, filename, url, b"not-a-wheel")
        artifacts[first_image] = replace(artifacts[first_image], build_dependencies=tuple(dependencies))
    else:
        artifacts[first_image] = replace(artifacts[first_image], binary_wheel=b"not-a-wheel")

    with pytest.raises(SourceWheelProofError, match="^entry_proof_failed$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    tmp_path / "proof",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )


def test_concurrent_candidate_failure_cannot_mask_infrastructure_failure() -> None:
    async def exercise() -> None:
        gate = asyncio.Event()
        arrivals = 0

        async def fail(error: BaseException) -> None:
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                gate.set()
            await gate.wait()
            raise error

        await source_wheel_proof._gather_cancel_on_error(
            fail(source_wheel_proof._CandidateSourceWheelProofError("wheel_zip_structure_invalid")),
            fail(SourceWheelProofError("source_integrity_failed")),
        )

    with pytest.raises(SourceWheelProofError, match="^source_integrity_failed$"):
        asyncio.run(exercise())


def test_gather_preserves_original_non_candidate_failure_after_cancellation() -> None:
    async def exercise() -> None:
        first_started = asyncio.Event()

        async def first() -> None:
            first_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as error:
                raise SourceWheelProofError("first_after_cancel") from error

        async def second() -> None:
            await first_started.wait()
            raise SourceWheelProofError("second_original")

        await source_wheel_proof._gather_cancel_on_error(first(), second())

    with pytest.raises(SourceWheelProofError, match="^second_original$"):
        asyncio.run(exercise())


@pytest.mark.parametrize(
    "preseeded_variant",
    (
        "empty_directory",
        ".writer.lock",
        "attempt_journal",
        "candidate_diagnostics_state.json",
        "finalization.json",
        "post_run_validation.json",
        "proof_state.json",
        "run_identity.json",
        "source_wheel_candidate.json",
        "source_wheel_proof.json",
        "source_wheel_policy.json",
        "unknown.json",
        "regular_file",
        "symlink",
        "symlink_to_file",
        "broken_symlink",
    ),
)
def test_candidate_diagnostics_require_a_wholly_absent_output_root(
    tmp_path: Path,
    preseeded_variant: str,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "diagnostics"
    if preseeded_variant == "regular_file":
        output.write_text("not a directory\n")
        output.chmod(0o600)
    elif preseeded_variant in {"symlink", "symlink_to_file", "broken_symlink"}:
        target = tmp_path / "diagnostics-target"
        if preseeded_variant == "symlink":
            target.mkdir(mode=0o700)
        elif preseeded_variant == "symlink_to_file":
            target.write_text("not a directory\n")
        output.symlink_to(target, target_is_directory=True)
    else:
        output.mkdir(mode=0o700)
        output.chmod(0o700)
        if preseeded_variant != "empty_directory":
            artifact = output / preseeded_variant
            if preseeded_variant == "attempt_journal":
                artifact.mkdir(mode=0o700)
            else:
                artifact.write_text("{}\n")
                artifact.chmod(
                    0o600
                    if preseeded_variant in {".writer.lock", "candidate_diagnostics_state.json", "proof_state.json"}
                    else 0o400
                )
    fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_output_not_fresh$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, output, candidate_diagnostics_only=True),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 0
    failure = aggregate_diagnostic_failure(output, "candidate_diagnostics_output_not_fresh")
    assert set(failure) == {"status", "error_code", "counts"}
    assert set(failure["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    assert all(type(value) is int and value == 0 for value in failure["counts"].values())


@pytest.mark.parametrize(
    "forbidden_artifact",
    (
        "finalization.json",
        "post_run_validation.json",
        "source_wheel_policy.json",
        "source_wheel_proof.json",
    ),
)
def test_candidate_diagnostics_reject_proof_artifacts_added_during_run(
    tmp_path: Path,
    forbidden_artifact: str,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        forbidden = config.output_dir / forbidden_artifact
        forbidden.write_text("{}\n")
        forbidden.chmod(0o400)
        with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_proof_artifact_forbidden$"):
            store.record_diagnostic_abort(
                {
                    "successful_runtime_starts": 0,
                    "peak_starting_runtimes": 0,
                    "peak_live_runtimes": 0,
                    "peak_concurrent_entries": 0,
                }
            )


def test_candidate_diagnostics_reject_nonprivate_final_output_root(tmp_path: Path) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        config.output_dir.chmod(0o755)
        with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_output_invalid$"):
            store.record_diagnostic_abort(
                {
                    "successful_runtime_starts": 0,
                    "peak_starting_runtimes": 0,
                    "peak_live_runtimes": 0,
                    "peak_concurrent_entries": 0,
                }
            )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("delete_candidate", "candidate_diagnostics_output_invalid"),
        ("delete_identity", "candidate_diagnostics_output_invalid"),
        ("delete_journal", "candidate_diagnostics_output_invalid"),
        ("delete_lock", "candidate_diagnostics_output_invalid"),
        ("delete_state", "candidate_diagnostics_output_invalid"),
        ("identity_directory", "candidate_diagnostics_output_invalid"),
        ("identity_symlink", "candidate_diagnostics_output_invalid"),
        ("identity_wrong_mode", "candidate_diagnostics_output_invalid"),
        ("unknown_artifact", "output_directory_contains_unknown_artifact"),
    ),
)
def test_candidate_diagnostics_enforce_exact_final_membership(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        if mutation == "delete_candidate":
            store.candidate_path.unlink()
        elif mutation == "delete_identity":
            store.identity_path.unlink()
        elif mutation == "delete_journal":
            store.journal_path.rmdir()
        elif mutation == "delete_lock":
            store.lock_path.unlink()
        elif mutation == "delete_state":
            store.state_path.unlink()
        elif mutation == "identity_directory":
            store.identity_path.unlink()
            store.identity_path.mkdir(mode=0o700)
        elif mutation == "identity_symlink":
            store.identity_path.unlink()
            store.identity_path.symlink_to(store.candidate_path)
        elif mutation == "identity_wrong_mode":
            store.identity_path.chmod(0o600)
        else:
            unknown = store.output_dir / "unknown.json"
            unknown.write_text("{}\n")
            unknown.chmod(0o400)
        with pytest.raises(SourceWheelProofError, match=f"^{expected_code}$"):
            store._validate_exact_diagnostic_output()


def test_candidate_diagnostics_reject_replaced_final_output_root(tmp_path: Path) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        moved_output = tmp_path / "moved-diagnostics"
        store.output_dir.rename(moved_output)
        store.output_dir.symlink_to(moved_output, target_is_directory=True)
        with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_output_invalid$"):
            store._validate_exact_diagnostic_output()


@pytest.mark.parametrize(
    ("artifact_name", "mutation"),
    (
        ("run_identity.json", "bytes"),
        ("source_wheel_candidate.json", "bytes"),
        ("candidate_diagnostics_state.json", "bytes"),
        (".writer.lock", "bytes"),
        ("attempt_journal", "bytes"),
        ("run_identity.json", "hardlink"),
        ("source_wheel_candidate.json", "hardlink"),
        ("candidate_diagnostics_state.json", "hardlink"),
        (".writer.lock", "hardlink"),
        ("attempt_journal", "hardlink"),
    ),
)
def test_candidate_diagnostics_validate_exact_final_bytes_and_link_counts(
    tmp_path: Path,
    artifact_name: str,
    mutation: str,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        attempt = store._journal().begin_start(next(iter(store.entry_map)), "target")
        store._journal().finish_start(
            attempt,
            next(iter(store.entry_map)),
            "target",
            outcome="start_failed",
            lease_identity_sha256=None,
        )
        store._journal().finish_stop(
            attempt,
            next(iter(store.entry_map)),
            "target",
            None,
            succeeded=True,
        )
        store.record_diagnostic_abort(
            {
                "successful_runtime_starts": 0,
                "peak_starting_runtimes": 1,
                "peak_live_runtimes": 0,
                "peak_concurrent_entries": 1,
            }
        )
        artifact = (
            next(iter(sorted(store.journal_path.iterdir())))
            if artifact_name == "attempt_journal"
            else store.output_dir / artifact_name
        )
        if mutation == "hardlink":
            os.link(artifact, tmp_path / f"{artifact.name}.alias")
        else:
            original_mode = stat.S_IMODE(artifact.lstat().st_mode)
            artifact.chmod(0o600)
            artifact.write_bytes(artifact.read_bytes() + b" ")
            artifact.chmod(original_mode)
        with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_output_invalid$"):
            store._validate_exact_diagnostic_output()


@pytest.mark.parametrize("mutation", ("provenance", "zero_peak_starting"))
def test_candidate_diagnostics_validate_final_state_semantics(tmp_path: Path, mutation: str) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    parsed, _ = load_private_discovery_input(config)

    with ProofStore(config, parsed) as store:
        key = next(iter(store.entry_map))
        attempt = store._journal().begin_start(key, "target")
        store._journal().finish_start(
            attempt,
            key,
            "target",
            outcome="start_failed",
            lease_identity_sha256=None,
        )
        store._journal().finish_stop(attempt, key, "target", None, succeeded=True)
        store.record_diagnostic_abort(
            {
                "successful_runtime_starts": 0,
                "peak_starting_runtimes": 1,
                "peak_live_runtimes": 0,
                "peak_concurrent_entries": 1,
            }
        )
        if mutation == "provenance":
            store.state["run_identity_sha256"] = "f" * 64
        else:
            store.state["telemetry"]["peak_starting_runtimes"] = 0  # type: ignore[index]
        store.state_path.write_bytes(canonical_json(store.state) + b"\n")
        store.state_path.chmod(0o600)
        with pytest.raises(SourceWheelProofError, match="^candidate_diagnostics_state_invalid$"):
            store._validate_exact_diagnostic_output()


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    (
        ("public_dependency", "build_dependency_wheel_invalid"),
        ("source_integrity", "source_integrity_failed"),
        ("corrupt_source_archive", "source_distribution_invalid"),
        ("unsupported_source_zip", "source_distribution_invalid"),
        ("malformed_source_zip_offset", "source_distribution_invalid"),
        ("unknown_declaration", "source_build_declaration_validation_failed"),
        ("cleanup", "runtime_cleanup_failed"),
    ),
)
def test_candidate_diagnostics_abort_non_candidate_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: str,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    first_image = next(iter(artifacts))
    fleet_options: dict[str, bool] = {}
    if failure_kind == "public_dependency":
        dependencies = list(artifacts[first_image].build_dependencies)
        distribution, version, filename, url, _ = dependencies[0]
        dependencies[0] = (distribution, version, filename, url, b"not-a-wheel")
        artifacts[first_image] = replace(artifacts[first_image], build_dependencies=tuple(dependencies))
    elif failure_kind == "source_integrity":
        fleet_options["corrupt_source_reads"] = True
    elif failure_kind in {
        "corrupt_source_archive",
        "unsupported_source_zip",
        "malformed_source_zip_offset",
    }:
        corrupt_source = (
            _source_zip_with_negative_member_offset(artifacts[first_image].source_distribution)
            if failure_kind == "malformed_source_zip_offset"
            else _source_zip_with_corrupt_setup_member(
                artifacts[first_image].source_distribution,
                unsupported_compression=failure_kind == "unsupported_source_zip",
            )
        )
        zip_filename = artifacts[first_image].source_filename.removesuffix(".tar.gz") + ".zip"
        source_policy = SourceArtifactPolicy(
            distribution=artifacts[first_image].source_distribution,
            version="1.0",
            filename=zip_filename,
            url=f"https://files.example.invalid/{zip_filename}",
            size=len(corrupt_source),
            sha256=sha256_bytes(corrupt_source),
            wheel_filename=artifacts[first_image].source_wheel_filename,
            wheel_size=1,
            wheel_sha256="0" * 64,
        )
        if failure_kind == "malformed_source_zip_offset":
            with pytest.raises(RuntimeError, match="not a valid ZIP archive"):
                inspect_source_distribution(source_policy, corrupt_source)
        else:
            inspect_source_distribution(source_policy, corrupt_source)
            with pytest.raises(SourceWheelContractError) as archive_error:
                extract_static_build_requirements(source_policy, corrupt_source)
            assert archive_error.value.code == "source_distribution_invalid"
        _replace_discovery_sources(
            discovery,
            artifacts,
            {first_image: corrupt_source},
            {first_image: zip_filename},
        )
    elif failure_kind == "unknown_declaration":

        def fail_declaration(*_: object) -> tuple[str, ...]:
            raise RuntimeError("synthetic private parser detail")

        monkeypatch.setattr(source_wheel_proof, "extract_static_build_requirements", fail_declaration)
    elif failure_kind == "cleanup":
        fleet_options["fail_stops"] = True
    output = tmp_path / f"diagnostics-{failure_kind}"
    fleet = FakeFleet(artifacts, **fleet_options)

    with pytest.raises(SourceWheelProofError, match=f"^{expected_code}$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, output, candidate_diagnostics_only=True),
                runtime_factory=fleet.factory,
            )
        )

    state = json.loads((output / "candidate_diagnostics_state.json").read_bytes())
    assert state["status"] == "aborted"
    assert state["attempt_journal"]["record_count"] == len(list((output / "attempt_journal").iterdir()))
    assert stat.S_ISDIR(output.lstat().st_mode)
    assert stat.S_IMODE(output.lstat().st_mode) == 0o700
    assert {path.name: stat.S_IMODE(path.lstat().st_mode) for path in output.iterdir()} == DIAGNOSTIC_OUTPUT_MODES
    public_failure = aggregate_diagnostic_failure(output, expected_code)
    assert set(public_failure) == {"status", "error_code", "counts"}
    assert public_failure["error_code"] == expected_code
    assert isinstance(public_failure["counts"], dict)
    assert set(public_failure["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    assert all(type(value) is int for value in public_failure["counts"].values())
    serialized_failure = json.dumps(public_failure, sort_keys=True)
    assert "state_sha256" not in serialized_failure
    assert "synthetic private" not in serialized_failure
    assert (
        proof_cli.failure_public_summary(
            SimpleNamespace(candidate_diagnostics_only=True, output_dir=output),
            source_wheel_proof,
            expected_code,
        )
        == public_failure
    )


@pytest.mark.parametrize("malformed_state", (False, True))
def test_candidate_diagnostics_failure_stdout_has_only_public_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    malformed_state: bool,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    state = json.loads(_diagnostic_failure_state_payload())
    if malformed_state:
        state["outcomes"]["private-entry-identity"]["error_code"] = ["/private/error/code"]
    state_path.write_bytes(canonical_json(state) + b"\n")
    state_path.chmod(0o600)
    config = _config(discovery, output, candidate_diagnostics_only=True)

    async def fail_diagnostics(*_: object) -> dict[str, object]:
        raise SourceWheelProofError("runtime_cleanup_failed")

    monkeypatch.setattr(proof_cli, "_require_bootstrap", lambda: None)
    monkeypatch.setattr(proof_cli, "_parse_args", lambda: _proof_cli_args(config))
    monkeypatch.setattr(proof_cli, "_run", fail_diagnostics)
    monkeypatch.setattr(proof_cli.logging, "disable", lambda _: None)

    assert proof_cli.main() == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert set(summary) == {"status", "error_code", "counts"}
    assert summary["status"] == "failed"
    assert summary["error_code"] == "runtime_cleanup_failed"
    assert set(summary["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    expected_counts = (
        {name: 0 for name in DIAGNOSTIC_FAILURE_COUNT_KEYS}
        if malformed_state
        else {
            "candidate_failures": 1,
            "entries_checked": 2,
            "peak_concurrent_entries": 1,
            "peak_live_runtimes": 3,
            "runtime_starts": 6,
            "successful_entries": 1,
        }
    )
    assert summary["counts"] == expected_counts
    assert all(type(value) is int for value in summary["counts"].values())
    assert "private-entry-identity" not in captured.out
    assert "/private/diagnostic/path" not in captured.out
    assert "/private/error/code" not in captured.out
    assert "a" * 64 not in captured.out


def test_candidate_diagnostic_failure_ignores_untrusted_counts(tmp_path: Path) -> None:
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    state_path.write_bytes(
        canonical_json(
            {
                "outcomes": {"private-entry-identity": {"status": "candidate_rejected"}},
                "telemetry": {"attested_runtime_starts": 10**100},
                "private_path": "/private/diagnostic/path",
            }
        )
        + b"\n"
    )
    state_path.chmod(0o600)

    summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")

    assert set(summary) == {"status", "error_code", "counts"}
    assert set(summary["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    assert "private-entry-identity" not in json.dumps(summary, sort_keys=True)
    assert "/private/diagnostic/path" not in json.dumps(summary, sort_keys=True)

    for private_code in ("/private/error/code", "private_task_identity"):
        unstable_code = aggregate_diagnostic_failure(output, private_code)
        assert unstable_code["error_code"] == "unexpected_failure"
        assert private_code not in json.dumps(unstable_code, sort_keys=True)

    for mutation in (
        "unhashable_status",
        "boolean_schema_version",
        "inconsistent_complete",
        "boolean_failure_count",
        "impossible_peaks",
        "peak_exceeds_entry_capacity",
        "peak_exceeds_starts",
        "zero_concurrency",
        "zero_starting_with_intents",
        "peak_starting_exceeds_intents",
        "journal_mismatch",
    ):
        state = json.loads(_diagnostic_failure_state_payload())
        if mutation == "unhashable_status":
            state["status"] = ["/private/status"]
        elif mutation == "boolean_schema_version":
            state["schema_version"] = True
        elif mutation == "inconsistent_complete":
            state["status"] = "complete"
        elif mutation == "boolean_failure_count":
            state["failure_counts"]["wheel_zip_structure_invalid"] = True
        elif mutation == "impossible_peaks":
            state["telemetry"]["peak_live_runtimes"] = 0
        elif mutation == "peak_exceeds_entry_capacity":
            state["telemetry"]["peak_live_runtimes"] = 4
        elif mutation == "peak_exceeds_starts":
            state["telemetry"]["peak_live_runtimes"] = 7
            state["telemetry"]["peak_concurrent_entries"] = 3
        elif mutation == "zero_concurrency":
            state["telemetry"]["peak_concurrent_entries"] = 0
        elif mutation == "zero_starting_with_intents":
            state["telemetry"]["peak_starting_runtimes"] = 0
        elif mutation == "peak_starting_exceeds_intents":
            state["telemetry"]["peak_starting_runtimes"] = 9
        else:
            state["attempt_journal"]["successful_starts"] = 5
        state_path.write_bytes(canonical_json(state) + b"\n")
        summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")
        assert all(type(value) is int and value == 0 for value in summary["counts"].values())


def test_candidate_diagnostic_failure_state_open_is_nonblocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    os.mkfifo(state_path, mode=0o600)
    original_open = os.open
    observed_nonblocking = False

    def checked_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal observed_nonblocking
        if Path(path) == state_path:
            observed_nonblocking = True
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(source_wheel_proof.os, "open", checked_open)

    summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")

    assert observed_nonblocking
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())


def test_candidate_diagnostic_failure_state_close_error_is_contained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    state_path.write_bytes(_diagnostic_failure_state_payload())
    state_path.chmod(0o600)
    original_open = os.open
    original_close = os.close
    diagnostic_descriptors: set[int] = set()

    def tracked_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == state_path:
            diagnostic_descriptors.add(descriptor)
        return descriptor

    def failing_close(descriptor: int) -> None:
        original_close(descriptor)
        if descriptor in diagnostic_descriptors:
            raise OSError("synthetic private close detail")

    monkeypatch.setattr(source_wheel_proof.os, "open", tracked_open)
    monkeypatch.setattr(source_wheel_proof.os, "close", failing_close)

    summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")

    assert diagnostic_descriptors
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    assert "synthetic private" not in json.dumps(summary, sort_keys=True)


@pytest.mark.parametrize("fault", ("fstat_final", "fstat_initial", "open", "read", "short_read"))
def test_candidate_diagnostic_failure_state_read_errors_are_contained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    valid_payload = _diagnostic_failure_state_payload()
    state_path.write_bytes(valid_payload + (b" " if fault == "short_read" else b""))
    state_path.chmod(0o600)
    original_open = os.open
    original_fstat = os.fstat
    original_read = os.read
    diagnostic_descriptors: set[int] = set()
    fstat_calls: dict[int, int] = {}

    def faulting_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        if Path(path) == state_path and fault == "open":
            raise OSError("synthetic private open detail")
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == state_path:
            diagnostic_descriptors.add(descriptor)
        return descriptor

    def faulting_fstat(descriptor: int) -> os.stat_result:
        if descriptor in diagnostic_descriptors:
            fstat_calls[descriptor] = fstat_calls.get(descriptor, 0) + 1
            if fault == "fstat_initial" and fstat_calls[descriptor] == 1:
                raise OSError("synthetic private initial fstat detail")
            if fault == "fstat_final" and fstat_calls[descriptor] == 2:
                raise OSError("synthetic private final fstat detail")
        return original_fstat(descriptor)

    def faulting_read(descriptor: int, size: int) -> bytes:
        if descriptor in diagnostic_descriptors:
            if fault == "read":
                raise OSError("synthetic private read detail")
            if fault == "short_read":
                return original_read(descriptor, len(valid_payload))
        return original_read(descriptor, size)

    monkeypatch.setattr(source_wheel_proof.os, "open", faulting_open)
    monkeypatch.setattr(source_wheel_proof.os, "fstat", faulting_fstat)
    monkeypatch.setattr(source_wheel_proof.os, "read", faulting_read)

    summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")

    assert set(summary) == {"status", "error_code", "counts"}
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    assert "synthetic private" not in json.dumps(summary, sort_keys=True)


@pytest.mark.parametrize("state_kind", ("hardlink", "oversize", "symlink"))
def test_candidate_diagnostic_failure_rejects_untrusted_state_file(
    tmp_path: Path,
    state_kind: str,
) -> None:
    output = tmp_path / "diagnostics"
    output.mkdir(mode=0o700)
    state_path = output / "candidate_diagnostics_state.json"
    if state_kind == "oversize":
        payload = _diagnostic_failure_state_payload()
        state_path.write_bytes(payload + b" " * (source_wheel_proof.MAX_DIAGNOSTIC_STATE_BYTES + 1 - len(payload)))
    else:
        target = tmp_path / "diagnostic-state-target.json"
        target.write_bytes(_diagnostic_failure_state_payload())
        target.chmod(0o600)
        if state_kind == "hardlink":
            os.link(target, state_path)
        else:
            state_path.symlink_to(target)
    if state_kind == "oversize":
        state_path.chmod(0o600)

    summary = aggregate_diagnostic_failure(output, "runtime_cleanup_failed")

    assert set(summary) == {"status", "error_code", "counts"}
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())


def test_candidate_diagnostic_failure_uses_runtime_output_path(tmp_path: Path) -> None:
    physical_parent = tmp_path / "physical"
    physical_child = physical_parent / "child"
    physical_child.mkdir(parents=True)
    lexical_parent = tmp_path / "lexical"
    lexical_parent.mkdir()
    link = lexical_parent / "link"
    link.symlink_to(physical_child, target_is_directory=True)
    output = physical_parent / "diagnostics"
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    state_path = output / "candidate_diagnostics_state.json"
    state_path.write_bytes(_diagnostic_failure_state_payload())
    state_path.chmod(0o600)

    reported_output = link / ".." / "diagnostics"
    summary = aggregate_diagnostic_failure(reported_output, "runtime_cleanup_failed")

    assert summary["counts"]["entries_checked"] == 2
    assert summary["counts"]["runtime_starts"] == 6


def test_candidate_diagnostics_failure_stdout_contains_summary_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)

    async def fail_diagnostics(*_: object) -> dict[str, object]:
        raise SourceWheelProofError("runtime_cleanup_failed")

    def fail_summary(*_: object) -> dict[str, object]:
        raise RuntimeError("synthetic private summary detail")

    monkeypatch.setattr(proof_cli, "_require_bootstrap", lambda: None)
    monkeypatch.setattr(proof_cli, "_parse_args", lambda: _proof_cli_args(config))
    monkeypatch.setattr(proof_cli, "_run", fail_diagnostics)
    monkeypatch.setattr(proof_cli.logging, "disable", lambda _: None)
    monkeypatch.setattr(source_wheel_proof, "aggregate_diagnostic_failure", fail_summary)

    assert proof_cli.main() == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert set(summary) == {"status", "error_code", "counts"}
    assert summary["error_code"] == "unexpected_failure"
    assert set(summary["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    assert "synthetic private summary detail" not in captured.out


@pytest.mark.parametrize(
    "mutation",
    (
        "boolean_count",
        "string_count",
        "private_failure_code",
        "boolean_failure_count",
        "inconsistent_counts",
    ),
)
def test_candidate_diagnostics_success_stdout_rejects_untrusted_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)
    result: dict[str, object] = {
        "diagnostic_only": True,
        "entries_checked": 9,
        "candidate_failures": 1,
        "successful_entries": 8,
        "failure_counts": {"wheel_zip_structure_invalid": 1},
        "runtime_starts": 27,
        "peak_live_runtimes": 6,
        "peak_concurrent_entries": 2,
    }
    if mutation == "boolean_count":
        result["runtime_starts"] = True
    elif mutation == "string_count":
        result["entries_checked"] = "/private/count"
    elif mutation == "private_failure_code":
        result["failure_counts"] = {"/private/failure/code": 1}
    elif mutation == "boolean_failure_count":
        result["failure_counts"] = {"wheel_zip_structure_invalid": True}
    else:
        result["candidate_failures"] = 2

    async def return_malformed_result(*_: object) -> dict[str, object]:
        return result

    monkeypatch.setattr(proof_cli, "_require_bootstrap", lambda: None)
    monkeypatch.setattr(proof_cli, "_parse_args", lambda: _proof_cli_args(config))
    monkeypatch.setattr(proof_cli, "_run", return_malformed_result)
    monkeypatch.setattr(proof_cli.logging, "disable", lambda _: None)

    assert proof_cli.main() == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary == proof_cli.empty_diagnostic_failure("unexpected_failure")
    assert all(type(value) is int for value in summary["counts"].values())
    assert "/private" not in captured.out


def test_candidate_diagnostics_success_summary_construction_is_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    discovery, _ = _write_discovery(tmp_path, 9)
    config = _config(discovery, tmp_path / "diagnostics", candidate_diagnostics_only=True)

    async def return_result(*_: object) -> dict[str, object]:
        return {"diagnostic_only": True}

    def fail_summary(*_: object) -> dict[str, object]:
        raise RuntimeError("synthetic private success-summary detail")

    monkeypatch.setattr(proof_cli, "_require_bootstrap", lambda: None)
    monkeypatch.setattr(proof_cli, "_parse_args", lambda: _proof_cli_args(config))
    monkeypatch.setattr(proof_cli, "_run", return_result)
    monkeypatch.setattr(proof_cli, "diagnostic_public_summary", fail_summary)
    monkeypatch.setattr(proof_cli.logging, "disable", lambda _: None)

    assert proof_cli.main() == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == proof_cli.empty_diagnostic_failure("unexpected_failure")
    assert "synthetic private" not in captured.out


@pytest.mark.parametrize("diagnostic_only", (False, True))
def test_bootstrap_failure_stdout_preserves_mode_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    diagnostic_only: bool,
) -> None:
    monkeypatch.delenv("SOURCE_WHEEL_PROOF_BOOTSTRAP_ATTESTATION_SHA256", raising=False)
    argv = ["prove_source_wheel_policy.py"]
    if diagnostic_only:
        argv.append("--candidate-diagnostics-only")
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit, match="^1$"):
        proof_cli._require_bootstrap()

    captured = capsys.readouterr()
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert summary["status"] == "failed"
    assert summary["error_code"] == "bootstrap_required"
    if diagnostic_only:
        assert set(summary) == {"status", "error_code", "counts"}
        assert set(summary["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
        assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    else:
        assert summary == {"status": "failed", "error_code": "bootstrap_required"}


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        ("allowlisted", "runtime_manifest_invalid"),
        ("unallowlisted", "unexpected_failure"),
        ("unexpected", "unexpected_failure"),
    ),
)
def test_bootstrap_outer_diagnostic_failures_have_safe_integer_count_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["source_wheel_proof_bootstrap.py", "run", "--candidate-diagnostics-only"],
    )

    def fail_parse() -> argparse.Namespace:
        if failure == "allowlisted":
            raise proof_bootstrap.BindingError("runtime_manifest_invalid")
        if failure == "unallowlisted":
            raise proof_bootstrap.BindingError("/private/bootstrap/code")
        raise RuntimeError("synthetic private bootstrap detail")

    monkeypatch.setattr(proof_bootstrap, "_parse_args", fail_parse)

    assert proof_bootstrap.main() == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    summary = json.loads(captured.out)
    assert set(summary) == {"status", "error_code", "counts"}
    assert summary["status"] == "failed"
    assert summary["error_code"] == expected_code
    assert set(summary["counts"]) == DIAGNOSTIC_FAILURE_COUNT_KEYS
    assert all(type(value) is int and value == 0 for value in summary["counts"].values())
    assert "/private" not in captured.out
    assert "synthetic private" not in captured.out


def test_failure_public_summary_preserves_production_aggregate(tmp_path: Path) -> None:
    output = tmp_path / "proof"
    output.mkdir(mode=0o700)
    state_path = output / "proof_state.json"
    payload = canonical_json({"completed": {"private-entry-identity": {}}}) + b"\n"
    state_path.write_bytes(payload)
    state_path.chmod(0o600)

    assert proof_cli.failure_public_summary(
        SimpleNamespace(candidate_diagnostics_only=False, output_dir=output),
        source_wheel_proof,
        "runtime_cleanup_failed",
    ) == {
        "status": "failed",
        "error_code": "runtime_cleanup_failed",
        "state_sha256": sha256_bytes(payload),
        "completed_entries": 1,
    }


def test_aggregate_failure_does_not_escape_state_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "failure"
    output.mkdir(mode=0o700)
    state_path = output / "proof_state.json"
    state_path.write_text("{}\n")
    state_path.chmod(0o600)
    original_read_bytes = Path.read_bytes

    def fail_state_read(path: Path) -> bytes:
        if path == state_path:
            raise OSError("synthetic private path detail")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_state_read)

    assert aggregate_failure(output, "runtime_cleanup_failed") == {
        "status": "failed",
        "error_code": "runtime_cleanup_failed",
    }


def test_semantically_equal_timestamp_variants_publish_and_resume(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    first_image = next(iter(artifacts))
    alternate = _retime_wheel(artifacts[first_image].source_wheel, (2024, 4, 4, 4, 4, 4))
    assert alternate != artifacts[first_image].source_wheel
    fleet = FakeFleet(artifacts, alternate_builder_wheels={first_image: alternate})
    output = tmp_path / "proof"

    result = asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=fleet.factory))

    assert result["runtime_starts"] == 27
    proof = json.loads((output / "source_wheel_proof.json").read_bytes())
    changed_entry = next(entry for entry in proof["entries"] if entry["final_policy_entry"]["image"] == first_image)
    assert changed_entry["cross_builder"]["wheel_semantics_equal"] is True
    assert changed_entry["cross_builder"]["wheel_bytes_equal"] is False
    assert changed_entry["cross_builder"]["wheelhouse_semantics_equal"] is True
    assert changed_entry["cross_builder"]["wheelhouse_bytes_equal"] is False
    assert changed_entry["builders"][0]["wheel_semantics"] == changed_entry["builders"][1]["wheel_semantics"]
    assert changed_entry["builders"][0]["wheels"] != changed_entry["builders"][1]["wheels"]

    parsed, _ = load_private_discovery_input(_config(discovery, tmp_path / "validation-only"))
    parsed_entry = next(
        entry
        for entry in parsed.entries
        if source_wheel_proof.entry_key_sha256(parsed.sha256, entry) == changed_entry["entry_key_sha256"]
    )
    tampered = json.loads(canonical_json(changed_entry))
    tampered["builders"][1]["wheel_semantics"][0]["sha256"] = "0" * 64
    tampered_core = {name: value for name, value in tampered.items() if name != "proof_sha256"}
    tampered["proof_sha256"] = sha256_bytes(canonical_json(tampered_core))
    with pytest.raises(SourceWheelProofError, match="^proof_state_entry_invalid$"):
        source_wheel_proof._validate_entry_proof(changed_entry["entry_key_sha256"], tampered, parsed, parsed_entry)

    resume_fleet = FakeFleet(artifacts)
    resumed = _config(
        discovery,
        output,
        resume_state_sha256=sha256_bytes((output / "proof_state.json").read_bytes()),
        slurm_job_id="12346",
    )
    resumed_result = asyncio.run(run_source_wheel_proof(resumed, runtime_factory=resume_fleet.factory))
    assert resumed_result["runtime_starts"] == 27
    assert resume_fleet.start_count == 0

    aggregate = json.dumps(aggregate_failure(output, "synthetic_failure"), sort_keys=True)
    assert "private-task" not in aggregate
    assert "https://" not in aggregate


@pytest.mark.parametrize(
    "retained",
    [
        frozenset(),
        frozenset({"source_wheel_proof.json"}),
        frozenset({"source_wheel_policy.json"}),
    ],
)
def test_finalization_record_reconciles_every_partial_publication(
    tmp_path: Path,
    retained: frozenset[str],
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    original = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    for name in {"source_wheel_proof.json", "source_wheel_policy.json"} - retained:
        (output / name).unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    result = asyncio.run(
        run_source_wheel_proof(
            _config(
                discovery,
                output,
                resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                slurm_job_id="12346",
            ),
            runtime_factory=resumed_fleet.factory,
        )
    )

    assert result == original
    assert resumed_fleet.start_count == 0
    assert (output / "finalization.json").is_file()
    assert (output / "source_wheel_proof.json").is_file()
    assert (output / "source_wheel_policy.json").is_file()


def test_final_artifacts_without_finalization_record_fail_closed(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory))
    (output / "finalization.json").unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^finalization_record_missing$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_fleet.factory,
            )
        )
    assert resumed_fleet.start_count == 0


def test_completed_state_without_post_validation_cannot_launder_zero_start_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    initial_fleet = FakeFleet(artifacts)
    initial_factory = initial_fleet.factory
    validation_calls = 0

    def fail_post_validation(_: SourceWheelProofConfig) -> None:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise SourceWheelProofError("synthetic_post_validation_failure")

    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", initial_factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", fail_post_validation)
    monkeypatch.setattr(source_wheel_proof, "validate_vacli_environment", lambda _: None)
    with pytest.raises(SourceWheelProofError, match="^synthetic_post_validation_failure$"):
        asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=initial_factory))

    assert initial_fleet.start_count == 27
    assert validation_calls == 2
    assert not (output / "post_run_validation.json").exists()
    state_path = output / "proof_state.json"
    state = json.loads(state_path.read_bytes())
    assert state["post_run_validation"] is None
    assert len(state["completed"]) == 9
    resumed_fleet = FakeFleet(artifacts)
    resumed_factory = resumed_fleet.factory
    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", resumed_factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", lambda _: None)

    with pytest.raises(SourceWheelProofError, match="^completed_state_not_post_validated$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_factory,
            )
        )
    assert resumed_fleet.start_count == 0
    assert not (output / "finalization.json").exists()
    assert not (output / "source_wheel_policy.json").exists()


def test_post_validation_record_reconciles_state_update_crash(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    original = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    for name in ("finalization.json", "source_wheel_proof.json", "source_wheel_policy.json"):
        (output / name).unlink()
    state_path = output / "proof_state.json"
    state = json.loads(state_path.read_bytes())
    state["post_run_validation"] = None
    state_path.write_bytes(canonical_json(state) + b"\n")
    state_path.chmod(0o600)
    resumed_fleet = FakeFleet(artifacts)

    result = asyncio.run(
        run_source_wheel_proof(
            _config(
                discovery,
                output,
                resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                slurm_job_id="12346",
            ),
            runtime_factory=resumed_fleet.factory,
        )
    )

    assert result == original
    assert resumed_fleet.start_count == 0


def test_post_validation_state_without_immutable_record_fails_closed(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory))
    for name in (
        "finalization.json",
        "source_wheel_proof.json",
        "source_wheel_policy.json",
        "post_run_validation.json",
    ):
        (output / name).unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^post_run_validation_record_missing$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_fleet.factory,
            )
        )
    assert resumed_fleet.start_count == 0


def test_cancellation_stops_every_started_runtime_and_leaves_resumable_state(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_builds=True)
        proof = asyncio.create_task(
            run_source_wheel_proof(
                _config(discovery, output, max_concurrent_entries=1, vacli_max_concurrent_leases=3),
                runtime_factory=fleet.factory,
            )
        )
        await asyncio.wait_for(fleet.two_builds_entered.wait(), timeout=2)
        proof.cancel()
        with pytest.raises(asyncio.CancelledError):
            await proof
        return fleet

    fleet = asyncio.run(scenario())

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)
    state = output / "proof_state.json"
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert json.loads(state.read_bytes())["completed"] == {}
    with pytest.raises(SourceWheelProofError, match="^attempt_journal_state_mismatch$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state.read_bytes()),
                    slurm_job_id="12346",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )
    journal_records = [json.loads(path.read_bytes()) for path in sorted((output / "attempt_journal").iterdir())]
    state_payload = json.loads(state.read_bytes())
    state_payload["attempt_journal"] = {
        "record_count": len(journal_records),
        "head_sha256": journal_records[-1]["record_sha256"],
        "start_intents": sum(record["event"] == "start_intent" for record in journal_records),
        "successful_starts": sum(record["event"] == "start_succeeded" for record in journal_records),
    }
    state.write_bytes(canonical_json(state_payload) + b"\n")
    state.chmod(0o600)
    with pytest.raises(SourceWheelProofError, match="^attempt_journal_prevents_exact_start_count$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state.read_bytes()),
                    slurm_job_id="12346",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )


def test_cancellation_drains_runtime_start_before_stopping_leases(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_starts=True)
        proof = asyncio.create_task(
            run_source_wheel_proof(
                _config(
                    discovery,
                    tmp_path / "proof",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=fleet.factory,
            )
        )
        await asyncio.wait_for(fleet.all_starts_entered.wait(), timeout=2)
        proof.cancel()
        await asyncio.sleep(0)
        assert not any(runtime.stopped for runtime in fleet.runtimes)
        fleet.release_starts.set()
        with pytest.raises(asyncio.CancelledError):
            await proof
        return fleet

    fleet = asyncio.run(scenario())

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.started and runtime.stopped for runtime in fleet.runtimes)


def test_duplicate_resolved_lease_identity_fails_and_stops_all_runtimes(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts, duplicate_descriptors=True)

    with pytest.raises(SourceWheelProofError, match="^runtime_lease_identity_duplicate$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    tmp_path / "proof",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)


def test_real_vacli_session_shape_produces_stable_secret_independent_identity() -> None:
    first = json.dumps(
        {
            "sessionId": {"cell": "synthetic", "id": "session-a"},
            "auth_token": {"token": "secret-a"},
        }
    )
    rotated_token = json.dumps(
        {
            "sessionId": {"id": "session-a", "cell": "synthetic"},
            "auth_token": {"token": "secret-b"},
        }
    )
    different_session = json.dumps(
        {
            "sessionId": {"cell": "synthetic", "id": "session-b"},
            "auth_token": {"token": "secret-a"},
        }
    )

    assert _vacli_lease_identity_sha256(first) == _vacli_lease_identity_sha256(rotated_token)
    assert _vacli_lease_identity_sha256(first) != _vacli_lease_identity_sha256(different_session)
    extracted = _extract_vacli_lease_response(f"prefix {rotated_token} trailing diagnostics")
    assert extracted is not None
    assert extracted[1] == _vacli_lease_identity_sha256(first)
    backend = object.__new__(VacliVMVMBackend)
    backend._lease = SimpleNamespace(session_identity_sha256=extracted[1])
    assert backend.lease_identity_sha256 == extracted[1]
    backend._lease = SimpleNamespace(session_identity_sha256=None)
    with pytest.raises(BackendInitError, match="session identity is unavailable"):
        _ = backend.lease_identity_sha256
    with pytest.raises(BackendInitError, match="session identity"):
        _vacli_lease_identity_sha256(
            json.dumps({"sessionId": "container-like-fallback", "auth_token": {"token": "secret"}})
        )


def test_discovery_requires_external_exact_nine_entry_and_missing_evidence_bindings(tmp_path: Path) -> None:
    short_discovery, _ = _write_discovery(tmp_path / "short", 8)
    with pytest.raises(SourceWheelProofError, match="^discovery_input_invalid$"):
        load_private_discovery_input(_config(short_discovery, tmp_path / "short-output"))

    discovery, _ = _write_discovery(tmp_path / "exact", 9)
    config = _config(discovery, tmp_path / "exact-output")
    payload = json.loads(discovery.read_bytes())
    payload["missing_required_evidence"].append("unexpected-evidence-field")
    discovery.write_bytes(canonical_json(payload) + b"\n")
    discovery.chmod(0o600)
    with pytest.raises(SourceWheelProofError, match="^discovery_input_invalid$"):
        load_private_discovery_input(replace(config, input_sha256=sha256_bytes(discovery.read_bytes())))
    with pytest.raises(SourceWheelProofError, match="^expected_entry_count_invalid$"):
        replace(config, expected_entry_count=8).validate()


def test_reproducibility_and_concurrency_contracts_fail_closed(tmp_path: Path) -> None:
    wheel_a = _wheel_file("proof-package", "1.0")
    wheel_b = wheel_a + b"different"
    evidence = (inspect_wheel("proof_package-1.0-py3-none-any.whl", wheel_a),)
    first = BuildResult(
        wheels={evidence[0].filename: wheel_a},
        wheel_evidence=evidence,
        wheel_semantics=((evidence[0].filename, wheel_semantic_sha256(evidence[0].filename, wheel_a)),),
        closure=(("proof-package", "1.0"),),
        wheelhouse=pack_wheelhouse({evidence[0].filename: wheel_a}),
        input_artifacts=(("proof_package-1.0.tar.gz", 1, "a" * 64),),
        build_dependency_artifacts=(),
        build_environment=_build_environment_record(()),
        build_argv_sha256="b" * 64,
    )
    second = replace(
        first,
        wheels={evidence[0].filename: wheel_b},
        wheelhouse=pack_wheelhouse({evidence[0].filename: wheel_b}),
    )
    with pytest.raises(SourceWheelProofError, match="^cross_builder_reproducibility_failed$"):
        compare_build_payloads(first, second)

    def timestamped_wheel(timestamp: tuple[int, int, int, int, int, int], module: bytes) -> bytes:
        output = io.BytesIO()
        metadata_dir = "proof_package-1.0.dist-info"
        members = (
            (
                f"{metadata_dir}/METADATA",
                b"Metadata-Version: 2.1\nName: proof-package\nVersion: 1.0\n",
            ),
            (
                f"{metadata_dir}/WHEEL",
                b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            ),
            ("proof_package.py", module),
        )
        with ZipFile(output, mode="w") as archive:
            for name, payload in members:
                info = ZipInfo(name, timestamp)
                info.external_attr = 0o600 << 16
                archive.writestr(info, payload)
        return output.getvalue()

    timestamp_a = timestamped_wheel((2020, 1, 1, 0, 0, 0), b"VALUE = 1\n")
    timestamp_b = timestamped_wheel((2021, 2, 2, 0, 0, 0), b"VALUE = 1\n")
    timestamp_name = "proof_package-1.0-py3-none-any.whl"

    def result(payload: bytes) -> BuildResult:
        item = inspect_wheel(timestamp_name, payload)
        return replace(
            first,
            wheels={timestamp_name: payload},
            wheel_evidence=(item,),
            wheel_semantics=((timestamp_name, wheel_semantic_sha256(timestamp_name, payload)),),
            wheelhouse=pack_wheelhouse({timestamp_name: payload}),
        )

    comparison = compare_build_payloads(result(timestamp_a), result(timestamp_b))
    assert comparison["wheel_semantics_equal"] is True
    assert comparison["wheel_bytes_equal"] is False
    assert comparison["wheelhouse_semantics_equal"] is True
    assert comparison["wheelhouse_bytes_equal"] is False

    changed_payload = timestamped_wheel((2021, 2, 2, 0, 0, 0), b"VALUE = 2\n")
    with pytest.raises(SourceWheelProofError, match="^cross_builder_reproducibility_failed$"):
        compare_build_payloads(result(timestamp_a), result(changed_payload))

    discovery, _ = _write_discovery(tmp_path, 1)
    with pytest.raises(SourceWheelProofError, match="^entry_concurrency_invalid$"):
        _config(discovery, tmp_path / "proof", max_concurrent_entries=4).validate()
    with pytest.raises(SourceWheelProofError, match="^base_runtime_revision_invalid$"):
        _config(discovery, tmp_path / "proof", base_runtime_commit="f" * 40).validate()
    with pytest.raises(SourceWheelProofError, match="^vacli_retry_invalid$"):
        _config(discovery, tmp_path / "proof", vacli_lease_retries=2).validate()
    with pytest.raises(
        SourceWheelProofError,
        match="^vacli_lease_concurrency_exceeds_runtime_cap$",
    ):
        _config(
            discovery,
            tmp_path / "proof",
            max_concurrent_entries=1,
            vacli_max_concurrent_leases=4,
        ).validate()


def test_hard_cap_runs_three_entries_with_at_most_nine_live_runtimes(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        tmp_path / "proof",
        max_concurrent_entries=3,
        vacli_max_concurrent_leases=9,
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=fleet.factory))

    assert result["runtime_starts"] == 27
    assert result["peak_live_runtimes"] == 9
    assert result["peak_concurrent_entries"] == 3
    assert fleet.peak_live == 9


def test_vacli_environment_and_binary_are_exactly_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 1)
    binary = tmp_path / "vacli"
    binary.write_bytes(b"pinned-runtime")
    binary.chmod(0o700)
    for name, value in {
        "VACLI_BIN": str(binary),
        "VACLI_LEASE_RETRIES": "1",
        "VACLI_MAX_CONCURRENT_LEASES": "6",
        "VACLI_MAX_PULL_RETRIES": "20",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "3600",
        "VACLI_CONTAINER_PRIVILEGED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    config = _config(
        discovery,
        tmp_path / "proof",
        vacli_path=binary,
        vacli_binary_sha256=sha256_bytes(binary.read_bytes()),
    )

    validate_vacli_environment(config)
    binary.write_bytes(b"changed-runtime")
    with pytest.raises(SourceWheelProofError, match="^vacli_binary_invalid$"):
        validate_vacli_environment(config)


def test_execution_environment_rejects_tool_site_and_inherited_python_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _ = _write_discovery(tmp_path / "input", 9)
    project = (tmp_path / "project").resolve()
    launcher = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch"
    vmvm_source = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    site_packages = (tmp_path / "site-packages").resolve()
    launcher.parent.mkdir(parents=True)
    vmvm_source.mkdir(parents=True)
    site_packages.mkdir()
    launcher.write_bytes(b"pinned launcher\n")
    (vmvm_source / "backend.py").write_bytes(b"pinned runtime\n")
    (site_packages / "dependency.py").write_bytes(b"pinned dependency\n")
    for relative in ("deps/verifiers", "deps/renderers", "deps/pydantic-config"):
        dependency = project / relative
        dependency.mkdir(parents=True)
        (dependency / ".git").write_text("gitdir: synthetic\n")
    (project / "deps/pydantic-config/src").mkdir()
    uv_path = tmp_path / "uv"
    vacli_path = tmp_path / "vacli"
    for path, payload in ((uv_path, b"pinned uv\n"), (vacli_path, b"pinned vacli\n")):
        path.write_bytes(payload)
        path.chmod(0o700)
    python_path = Path(sys.executable).resolve()
    python_stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    config = replace(
        _config(discovery, tmp_path / "proof"),
        project_dir=project,
        canonical_launcher_path=launcher,
        executed_launcher_path=launcher,
        uv_path=uv_path.resolve(),
        python_path=python_path,
        python_stdlib_path=python_stdlib,
        site_packages_path=site_packages,
        vacli_path=vacli_path.resolve(),
        launcher_sha256=sha256_bytes(launcher.read_bytes()),
        uv_sha256=sha256_bytes(uv_path.read_bytes()),
        python_sha256=sha256_bytes(python_path.read_bytes()),
        python_runtime_manifest_sha256="9" * 64,
        site_packages_manifest_sha256=proof_bootstrap.canonical_tree_manifest_sha256(site_packages),
        vmvm_tb_v2_sha256=proof_bootstrap.python_sources_sha256(vmvm_source),
        vacli_binary_sha256=sha256_bytes(vacli_path.read_bytes()),
    )
    dependency_commits = {
        "deps/verifiers": config.verifiers_commit,
        "deps/renderers": config.renderers_commit,
        "deps/pydantic-config": config.pydantic_config_commit,
    }

    def fake_git(path: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--verify", "HEAD"):
            if path == project:
                return config.source_commit
            return dependency_commits[str(path.relative_to(project))]
        if arguments == ("rev-parse", "--verify", "HEAD^{tree}"):
            return config.source_git_tree
        if arguments[0] == "status":
            return ""
        if arguments[0] == "merge-base":
            return config.base_runtime_commit
        if arguments[:2] == ("ls-tree", "HEAD"):
            relative = arguments[2]
            return f"160000 commit {dependency_commits[relative]}\t{relative}"
        raise AssertionError("unexpected Git probe")

    monkeypatch.setattr(proof_bootstrap, "git_output", fake_git)
    monkeypatch.setattr(proof_bootstrap, "_validate_bootstrap_flags", lambda: None)
    for name in tuple(os.environ):
        if name.startswith("PYTHON") or name.startswith("BASH_FUNC_") or name.startswith("LD_"):
            monkeypatch.delenv(name, raising=False)
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    monkeypatch.setenv("VACLI_BIN", str(vacli_path.resolve()))
    import_roots = proof_bootstrap.expected_import_roots(project, site_packages)
    zip_path = python_stdlib.parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    stdlib_sys_path = [str(zip_path), str(python_stdlib)]
    lib_dynload = python_stdlib / "lib-dynload"
    if lib_dynload.is_dir():
        stdlib_sys_path.append(str(lib_dynload))
    monkeypatch.setattr(sys, "path", [*(str(path) for path in import_roots), *stdlib_sys_path])
    bindings = proof_bootstrap.ExecutionBindings(
        **{field: getattr(config, field) for field in proof_bootstrap.ExecutionBindings.__dataclass_fields__}
    )
    runtime_manifest = proof_bootstrap.python_runtime_manifest_sha256(
        python_path,
        python_stdlib,
        import_roots,
        proof_bootstrap._import_root_bindings(bindings, import_roots),
    )
    config = replace(config, python_runtime_manifest_sha256=runtime_manifest)
    bindings = replace(bindings, python_runtime_manifest_sha256=runtime_manifest)
    monkeypatch.setenv(
        proof_bootstrap.BOOTSTRAP_ATTESTATION_ENV,
        proof_bootstrap.bootstrap_attestation_sha256(bindings, runtime_manifest),
    )

    validate_execution_environment(config)
    noncanonical_launchers = {
        "copied": tmp_path / "copied_launcher.sbatch",
        "symlinked": tmp_path / "symlinked_launcher.sbatch",
        "spooled": tmp_path / "slurm_spool" / "job_script",
    }
    noncanonical_launchers["copied"].write_bytes(launcher.read_bytes())
    noncanonical_launchers["copied"].chmod(0o600)
    noncanonical_launchers["symlinked"].symlink_to(launcher)
    noncanonical_launchers["spooled"].parent.mkdir()
    noncanonical_launchers["spooled"].write_bytes(launcher.read_bytes())
    noncanonical_launchers["spooled"].chmod(0o600)
    for noncanonical_launcher in noncanonical_launchers.values():
        with pytest.raises(SourceWheelProofError, match="^execution_binding_invalid$"):
            validate_execution_environment(replace(config, executed_launcher_path=noncanonical_launcher))
    for field in ("launcher_sha256", "uv_sha256", "python_sha256", "vacli_binary_sha256"):
        with pytest.raises(SourceWheelProofError, match="^execution_tool_sha256_mismatch$"):
            validate_execution_environment(replace(config, **{field: "a" * 64}))
    with pytest.raises(SourceWheelProofError, match="^python_runtime_manifest_mismatch$"):
        validate_execution_environment(replace(config, python_runtime_manifest_sha256="a" * 64))
    with pytest.raises(SourceWheelProofError, match="^site_packages_manifest_mismatch$"):
        validate_execution_environment(replace(config, site_packages_manifest_sha256="a" * 64))
    with pytest.raises(SourceWheelProofError, match="^vmvm_runtime_source_mismatch$"):
        validate_execution_environment(replace(config, vmvm_tb_v2_sha256="a" * 64))
    monkeypatch.setenv("PYTHONHOME", "/untrusted")
    with pytest.raises(SourceWheelProofError, match="^execution_environment_not_sanitized$"):
        validate_execution_environment(config)
    monkeypatch.delenv("PYTHONHOME")
    (site_packages / "dependency.py").write_bytes(b"changed dependency\n")
    with pytest.raises(SourceWheelProofError, match="^site_packages_manifest_mismatch$"):
        validate_execution_environment(config)


def test_resume_requires_exact_external_state_hash(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    result = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    assert result["runtime_starts"] == 27

    resumed = _config(
        discovery,
        output,
        resume_state_sha256="d" * 64,
        slurm_job_id="12346",
    )
    with pytest.raises(SourceWheelProofError, match="^resume_state_sha256_mismatch$"):
        asyncio.run(run_source_wheel_proof(resumed, runtime_factory=FakeFleet(artifacts).factory))


def test_resume_revalidates_completed_entries_and_runs_only_missing_work(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    initial_config = _config(
        discovery,
        output,
        max_concurrent_entries=1,
        vacli_max_concurrent_leases=3,
    )
    parsed, _ = load_private_discovery_input(initial_config)
    initial_fleet = FakeFleet(artifacts)
    with ProofStore(initial_config, parsed) as store:
        runner = SourceWheelProofRunner(
            initial_config,
            parsed,
            store._journal(),
            runtime_factory=initial_fleet.factory,
        )
        key, proof = asyncio.run(runner._prove_entry(parsed.entries[0]))
        store.publish_entry(
            key,
            proof,
            {
                **runner.telemetry.as_dict(),
                "peak_concurrent_entries": runner.peak_entries,
            },
        )

    assert initial_fleet.start_count == 3
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        output,
        resume_state_sha256=sha256_bytes(state_path.read_bytes()),
        slurm_job_id="12346",
        max_concurrent_entries=1,
        vacli_max_concurrent_leases=3,
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=resumed_fleet.factory))

    assert result["runtime_starts"] == 27
    assert resumed_fleet.start_count == 24
    assert len(json.loads((output / "source_wheel_policy.json").read_bytes())["entries"]) == 9


def test_readme_uses_exact_clean_tmux_wrap_launcher_form() -> None:
    workflow = Path(__file__).resolve().parents[1]
    readme = (workflow / "README.md").read_text()
    launcher = (workflow / "run_source_wheel_proof.sbatch").read_text()
    runtime_skill = (Path(__file__).resolve().parents[4] / "skills/vmvm-runtime/SKILL.md").read_text()

    assert "tmux send-keys -t source-wheel-proof" in readme
    assert '"/usr/bin/env -i PATH=/usr/bin:/bin' in readme
    assert "/usr/bin/sbatch --parsable --export=ALL" in readme
    assert (
        "--wrap='exec /bin/bash --noprofile --norc "
        "/path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/"
        "run_source_wheel_proof.sbatch'\" C-m"
    ) in readme
    assert 'exec "$python_bin" -I -S -B' in launcher
    assert '"$workflow_dir/source_wheel_proof_bootstrap.py" run' in launcher
    assert "uv run --no-project" not in launcher
    for rejected in ("BASH_ENV", "LD_PRELOAD"):
        assert rejected in (launcher + readme)
    assert "declare -F" in launcher
    assert "`PATH` contains only the attested venv's `bin`" in readme
    assert "complete raw ZIP" in readme
    assert "local and central DOS" in readme and "time/date fields zeroed" in readme
    assert "`setup.cfg`" in readme and "`pyproject.toml`" in readme
    assert "SOURCE_WHEEL_PROOF_CANDIDATE_DIAGNOSTICS_ONLY=1" in readme
    assert "never resumes" in readme
    assert "Exit status zero means that this non-certifying diagnostic" in readme
    assert "candidate_diagnostics_only" in launcher
    assert "SOURCE_WHEEL_PROOF_CANDIDATE_DIAGNOSTICS_ONLY=1" in runtime_skill
    assert "publish no proof or policy" in runtime_skill


def test_bootstrap_requires_isolated_no_site_python_before_import_roots() -> None:
    bootstrap = Path(__file__).resolve().parents[1] / "source_wheel_proof_bootstrap.py"
    probe = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("proof_bootstrap_probe", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module._validate_bootstrap_flags()
except module.BindingError:
    raise SystemExit(17)
raise SystemExit(0)
"""
    clean_environment = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "/untrusted/import/root"}

    isolated = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", probe, str(bootstrap)],
        check=False,
        capture_output=True,
        env=clean_environment,
    )
    unsafe = subprocess.run(
        [sys.executable, "-S", "-B", "-c", probe, str(bootstrap)],
        check=False,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert isolated.returncode == 0
    assert unsafe.returncode == 17


def test_execution_validation_precedes_private_input_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts)
    factory = fleet.factory
    private_input_loaded = False

    def reject_environment(_: SourceWheelProofConfig) -> None:
        raise SourceWheelProofError("synthetic_pre_import_rejection")

    def observe_private_input(_: SourceWheelProofConfig) -> None:
        nonlocal private_input_loaded
        private_input_loaded = True
        raise AssertionError("private input loaded before environment validation")

    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", reject_environment)
    monkeypatch.setattr(source_wheel_proof, "load_private_discovery_input", observe_private_input)

    with pytest.raises(SourceWheelProofError, match="^synthetic_pre_import_rejection$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, tmp_path / "proof"),
                runtime_factory=factory,
            )
        )
    assert private_input_loaded is False
    assert fleet.start_count == 0
