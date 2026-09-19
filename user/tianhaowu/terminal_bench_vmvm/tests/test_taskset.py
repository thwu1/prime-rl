import asyncio
import base64
import gc
import hashlib
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import sysconfig
import tarfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from weakref import ref
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
import terminal_bench_vmvm.taskset as taskset_module
from terminal_bench_vmvm.source_wheels import (
    SOURCE_BUILD_ENV_ATTEST_CODE,
    SOURCE_BUILD_ENVIRONMENT_SCHEMA_VERSION,
    SOURCE_BUILD_RUNNER_CODE,
    SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION,
    SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
    BinaryWheelPolicy,
    SourceArtifactPolicy,
    build_dependency_artifact_records,
    canonical_distribution_name,
    canonical_json,
    extract_static_build_requirements,
    extract_static_setup_requires,
    inspect_source_distribution,
    inspect_wheel,
    load_source_wheel_policy,
    pack_wheelhouse,
    sha256_bytes,
    source_build_argv,
    source_build_dependency_install_argv,
    source_build_env_attest_argv,
    source_build_env_create_argv,
    source_build_environment_record,
    validate_build_dependency_payload_closure,
    validate_policy_wheel_closure,
    validate_source_build_environment,
    wheel_semantic_sha256,
)
from terminal_bench_vmvm.taskset import (
    RuntimeWheelFingerprints,
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    _binary_distribution_unavailable,
    _compose_path,
    _declared_test_requirements,
    _dockerfile_startup_command,
    _environment_workdir,
    _merge_test_requirements,
    _network_modes,
    _parse_verifier_reward,
    _test_script_requirements,
    _verifier_site_bootstrap,
)
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import ProgramResult, VMVMConfig, VMVMRuntime
from vmvm_tb_v2._vacli import backend as vacli_backend
from vmvm_tb_v2._vacli.backend import (
    VacliHostTunnel,
    VacliVMVMBackend,
    _setup_bridge_proxy,
    _VacliNetworkIsolation,
)
from vmvm_tb_v2._vacli.concurrency_telemetry import LeaseStartConcurrencyLimiter
from vmvm_tb_v2._vacli.types import BackendInitError


class _VerifierRuntime:
    def __init__(self, attempt: int, *, stop_error: str | None = None) -> None:
        self.attempt = attempt
        self.descriptor = f"verifier-{attempt}"
        self.stop_error = stop_error

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        if self.stop_error is not None:
            raise RuntimeError(self.stop_error)


def test_environment_workdir_defaults_and_tracks_relative_updates(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\nWORKDIR /workspace\nWORKDIR project\n")
    assert _environment_workdir(dockerfile) == "/workspace/project"
    assert _environment_workdir(tmp_path / "missing") == "/app"


def test_compose_path_accepts_standard_names_in_precedence_order(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    fallback = environment / "compose.yml"
    fallback.write_text("services: {}\n")
    assert _compose_path(tmp_path) == fallback

    preferred = environment / "docker-compose.yaml"
    preferred.write_text("services: {}\n")
    assert _compose_path(tmp_path) == preferred


def test_declared_test_requirements_parses_marked_pip_layer(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    (environment / "Dockerfile").write_text(
        "FROM python:3.12\n"
        "RUN pip3 install unrelated==1\n"
        "# Test dependencies prebaked so the verifier runs offline\n"
        "RUN python3 -m pip install -q pytest==8.3.4 \\\n"
        "    psycopg2-binary==2.9.10 | tail\n"
    )
    assert _declared_test_requirements(str(tmp_path)) == (
        "pytest==8.3.4",
        "psycopg2-binary==2.9.10",
    )


def test_test_script_requirements_extracts_only_literal_exact_pins(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test.sh").write_text(
        "# pip install commented-out==1.0\n"
        "echo 'pip install quoted==1.0'\n"
        "python3 -m pip install -q pytest==8.3.5 numpy[typing,test-extra]==2.1.3 \\\n"
        "  --disable-pip-version-check && pytest -q\n"
        "pip --quiet install packaging==24.2\n"
        "pip install redirected==1.0 >/dev/null 2>&1\n"
        ">/dev/null pip install prefix-redirected==1.0\n"
        "(pip install grouped==1.0); true\n"
    )

    assert _test_script_requirements(str(tmp_path)) == (
        "pytest==8.3.5",
        "numpy[typing,test-extra]==2.1.3",
        "packaging==24.2",
        "redirected==1.0",
        "prefix-redirected==1.0",
        "grouped==1.0",
    )


def test_test_script_requirements_normalizes_only_bare_pytest_compatibility_rule(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test.sh").write_text("pip install pytest\n")

    assert _test_script_requirements(str(tmp_path)) == ("pytest==8.3.4",)


@pytest.mark.parametrize(
    "command",
    [
        "pip install unpinned",
        "pip install ./local-package",
        "pip install https://example.invalid/package.whl",
        "pip install -r requirements.txt",
        "pip install --constraint constraint==1 package==1.0",
        "pip install --extra-index-url https://example.invalid/simple package==1.0",
        "pip install --no-deps package==1.0",
        "pip --index-url https://example.invalid/simple install package==1.0",
        "python3 -m pip --index-url https://example.invalid/simple install package==1.0",
        "python3 -I -m pip install package==1.0",
        "/opt/venv/bin/pip install package==1.0",
        "python3.11 -m pip install package==1.0",
        "pip install \"package==1.0; python_version < '3.13'\"",
        "PIP_INDEX_URL=https://example.invalid/simple pip install package==1.0",
        "$PIP install package==1.0",
        "sudo pip install package==1.0",
        "uv pip install package==1.0",
        "sh -c 'pip install package==1.0'",
        "pip install package==1.0 | tee install.log",
        "pip install package==1.0 >",
        "pip install package==1.0 < requirements.txt",
        "pip install 'package==1.0",
    ],
)
def test_test_script_requirements_rejects_nonreplayable_commands(tmp_path: Path, command: str) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test.sh").write_text(f"{command}\n")

    with pytest.raises(ValueError, match="pip install"):
        _test_script_requirements(str(tmp_path))


def test_merge_test_requirements_rejects_conflicting_canonical_names() -> None:
    with pytest.raises(ValueError, match="conflicting verifier requirements"):
        _merge_test_requirements(("example_pkg==1.0",), ("example-pkg==2.0",))


def test_merge_test_requirements_preserves_compatible_extras() -> None:
    assert _merge_test_requirements(("example_pkg[first]==1.0",), ("example-pkg[second]==1.0",)) == (
        "example_pkg[first]==1.0",
        "example-pkg[second]==1.0",
    )


def test_verifier_site_bootstrap_processes_overlay_pth_files(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    site = tmp_path / "site"
    extension = tmp_path / "extension"
    bootstrap.mkdir()
    site.mkdir()
    extension.mkdir()
    (bootstrap / "sitecustomize.py").write_bytes(_verifier_site_bootstrap(str(site)))
    (site / "extension.pth").write_text(f"{extension}\n")
    (extension / "overlay_extension.py").write_text("VALUE = 7\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = f"{bootstrap}:{site}"

    completed = subprocess.run(
        [sys.executable, "-c", "import overlay_extension; assert overlay_extension.VALUE == 7"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


BUILD_TOOLS = {"pip": "24.3.1", "setuptools": "75.6.0", "wheel": "0.45.1"}


def wheel_file(filename: str, *requirements: str) -> bytes:
    distribution, version, *_ = filename.removesuffix(".whl").split("-")
    tag = "-".join(filename.removesuffix(".whl").split("-")[-3:])
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{distribution}-{version}.dist-info"
        metadata = ["Metadata-Version: 2.1", f"Name: {distribution}", f"Version: {version}"]
        metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
        wheel.writestr(f"{metadata_dir}/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n",
        )
    return output.getvalue()


def baseline_build_dependency_wheels() -> tuple[tuple[str, str, str, str, bytes], ...]:
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
            wheel_file(
                f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
                *requirements,
            ),
        )
        for distribution, version, requirements in records
    )


def wheel_file_with_module(
    filename: str,
    module: str,
    module_source: bytes,
    *,
    console_script: str | None = None,
) -> bytes:
    distribution, version, *_ = filename.removesuffix(".whl").split("-")
    tag = "-".join(filename.removesuffix(".whl").split("-")[-3:])
    records: list[tuple[str, bytes]] = [
        (f"{module}/__init__.py", module_source),
        (
            f"{distribution}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n".encode(),
        ),
        (
            f"{distribution}-{version}.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n".encode(),
        ),
    ]
    if console_script is not None:
        records.append(
            (
                f"{distribution}-{version}.dist-info/entry_points.txt",
                f"[console_scripts]\n{console_script} = {module}:main\n".encode(),
            )
        )
    record_path = f"{distribution}-{version}.dist-info/RECORD"
    record_lines = []
    for path, payload in records:
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        record_lines.append(f"{path},sha256={digest},{len(payload)}")
    record_lines.append(f"{record_path},,")
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        for path, payload in records:
            wheel.writestr(path, payload)
        wheel.writestr(record_path, "\n".join(record_lines) + "\n")
    return output.getvalue()


def wheel_archive(*names: str) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for filename in names:
            payload = wheel_file(filename)
            member = tarfile.TarInfo(filename)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


class DependencyRuntime:
    def __init__(
        self,
        *,
        installed: bool = True,
        wheel_failure: bool = False,
        source_only: bool = False,
        image: str = "registry.invalid/task@sha256:" + "a" * 64,
        wheel_names: tuple[str, ...] = ("verifier_helper-1.0-py3-none-any.whl",),
        python_version: tuple[int, int, int] = (3, 12, 0),
        pip_version: str = "24.3.1",
    ) -> None:
        self.installed = installed
        self.overlay_installed = False
        self.wheel_failure = wheel_failure
        self.source_only = source_only
        self.config = SimpleNamespace(image=image)
        self.wheel_archive = wheel_archive(*wheel_names)
        self.python_version = python_version
        self.pip_version = pip_version
        self.events: list[str] = []
        self.argvs: list[list[str]] = []
        self.commands: list[str] = []
        self.environments: list[dict[str, str]] = []

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        self.argvs.append(list(argv))
        command = subprocess.list2cmdline(argv)
        self.commands.append(command)
        self.environments.append(env)
        if argv[:3] == ["python3", "-I", "-c"] and "resolved = set()" in argv[3]:
            self.events.append("clean-target-closure-probe")
            return ProgramResult(exit_code=0, stdout='[["verifier-helper","1.0"]]', stderr="")
        if argv[:2] == ["python3", "-c"] and "metadata.distributions" in argv[2]:
            overlay_probe = "TERMINAL_BENCH_VERIFIER_SITE" in env
            self.events.append("overlay-probe" if overlay_probe else "probe")
            available = self.overlay_installed if overlay_probe else self.installed
            output = "" if available else "".join(f"{requirement}\n" for requirement in argv[3:])
            return ProgramResult(exit_code=0, stdout=output, stderr="")
        if argv[:2] == ["python3", "-c"] and "sysconfig.get_config_var" in argv[2]:
            self.events.append("fingerprint")
            major, minor, micro = self.python_version
            marker_environment = {
                "implementation_name": "cpython",
                "implementation_version": f"{major}.{minor}.{micro}",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_release": "6.8.0",
                "platform_system": "Linux",
                "platform_version": "synthetic-runtime",
                "python_full_version": f"{major}.{minor}.{micro}",
                "platform_python_implementation": "CPython",
                "python_version": f"{major}.{minor}",
                "sys_platform": "linux",
            }
            return ProgramResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "marker_environment": marker_environment,
                        "pip_version": self.pip_version,
                        "build_tools": {
                            "pip": self.pip_version,
                            "setuptools": "75.6.0",
                            "wheel": "0.45.1",
                        },
                        "wheel_compatibility": [
                            "cpython",
                            [major, minor],
                            f"cpython-{major}{minor}-x86_64-linux-gnu",
                            "linux-x86_64",
                            "x86_64",
                        ],
                    }
                ),
                stderr="",
            )
        if argv[:4] == ["python3", "-m", "pip", "wheel"]:
            self.events.append("wheel")
            source_rejected = self.source_only and "--only-binary=:all:" in argv
            return ProgramResult(
                exit_code=1 if self.wheel_failure or source_rejected else 0,
                stdout=(
                    "ERROR: Could not find a version that satisfies the requirement verifier-helper==1.0\n"
                    "ERROR: No matching distribution found for verifier-helper==1.0\n"
                    if source_rejected
                    else "wheel failed"
                    if self.wheel_failure
                    else ""
                ),
                stderr="",
            )
        if "PIP_NO_INDEX=1" in command:
            self.events.append("overlay-install")
            self.overlay_installed = True
        if argv[:2] == ["sh", "-c"] and argv[2].startswith("rm -rf /tmp/terminal-bench-verifier-site-"):
            self.events.append("overlay-cleanup")
            self.overlay_installed = False
        if "timeout --signal=TERM" in command:
            self.events.append("verifier")
        if "if test -s /logs/verifier/reward.json" in command:
            return ProgramResult(exit_code=0, stdout="text", stderr="")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def read(self, path: str) -> bytes:
        if path == "/logs/verifier/reward.txt":
            return b"1\n"
        self.events.append("archive-read")
        return self.wheel_archive

    async def write(self, path: str, data: bytes) -> None:
        if path.endswith("/sitecustomize.py"):
            self.events.append("bootstrap-write")
            assert data.startswith(b"import site\nsite.addsitedir('/tmp/terminal-bench-verifier-site-")
            return
        if path.startswith("/tmp/terminal-bench-source-wheel-validation-"):
            self.events.append("clean-target-archive-write")
            return
        self.events.append("archive-write")
        assert data == self.wheel_archive


def build_dependency_policies(
    wheels: tuple[tuple[str, str, str, str, bytes], ...] | None = None,
) -> tuple[BinaryWheelPolicy, ...]:
    return tuple(
        BinaryWheelPolicy(
            distribution=distribution,
            version=version,
            filename=filename,
            url=url,
            size=len(payload),
            sha256=sha256_bytes(payload),
        )
        for distribution, version, filename, url, payload in (
            wheels if wheels is not None else baseline_build_dependency_wheels()
        )
    )


def source_build_environment_attestation(
    build_env_dir: str = "/tmp/terminal-bench-source-build-env",
    *,
    build_tools: dict[str, str] | None = None,
    build_dependencies: tuple[BinaryWheelPolicy, ...] | None = None,
) -> str:
    build_env = os.path.realpath(build_env_dir)
    dependencies = build_dependencies if build_dependencies is not None else build_dependency_policies()
    artifacts = build_dependency_artifact_records(dependencies)
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
                for wheel in sorted(dependencies, key=lambda item: item.distribution)
            ],
            "bin_path": f"{build_env}/bin",
            "bin_mode": 0o755,
            "bin_entries": bin_entries,
            "bin_executables": ["python", "python3"],
            "bin_sha256": sha256_bytes(canonical_json(bin_entries)),
            "build_tools": build_tools or BUILD_TOOLS,
        },
        sort_keys=True,
    )


def source_build_environment_fixture(
    build_env_dir: str = "/tmp/terminal-bench-source-build-env",
    *,
    build_tools: dict[str, str] | None = None,
    build_dependencies: tuple[BinaryWheelPolicy, ...] | None = None,
) -> dict[str, object]:
    tools = build_tools or BUILD_TOOLS
    dependencies = build_dependencies if build_dependencies is not None else build_dependency_policies()
    return source_build_environment_record(
        build_env_dir=build_env_dir,
        expected_build_tools=tuple(sorted(tools.items())),
        build_dependencies=dependencies,
        attestation=json.loads(
            source_build_environment_attestation(
                build_env_dir,
                build_tools=tools,
                build_dependencies=dependencies,
            )
        ),
    )


class SourceBuilderRuntime(DependencyRuntime):
    def __init__(
        self,
        source_payload: bytes,
        built_wheel: bytes,
        *,
        image: str = "registry.invalid/task@sha256:" + "a" * 64,
        lifecycle: list[str] | None = None,
        build_dependency_payloads: dict[str, bytes] | None = None,
    ) -> None:
        super().__init__(image=image)
        self.source_payload = source_payload
        self.built_wheel = built_wheel
        self.files: dict[str, bytes] = {}
        self.lifecycle = lifecycle if lifecycle is not None else []
        self.build_dependency_payloads = {
            filename: payload for _, _, filename, _, payload in baseline_build_dependency_wheels()
        }
        self.build_dependency_payloads.update(build_dependency_payloads or {})

    async def start(self) -> None:
        self.lifecycle.append("start")

    async def stop(self) -> None:
        self.lifecycle.append("stop")

    async def configure_network_policy(self, mode: str) -> None:
        assert mode == "no-network"
        self.events.append("network-prepared")

    async def activate_network_policy(self) -> None:
        self.events.append("network-isolated")

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        if argv[:3] == ["python3", "-I", "-c"] and "resolved = set()" in argv[3]:
            self.argvs.append(list(argv))
            self.events.append("closure-probe")
            return ProgramResult(exit_code=0, stdout='[["verifier-helper","1.0"]]', stderr="")
        if argv[:3] == ["python3", "-I", "-c"] and "urllib.request.urlopen" in argv[3]:
            self.argvs.append(list(argv))
            self.events.append("download")
            destination = argv[5]
            filename = Path(destination).name
            self.files[destination] = self.build_dependency_payloads.get(filename, self.source_payload)
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv == source_build_env_create_argv("/tmp/terminal-bench-source-build-env"):
            assert env == {}
            self.argvs.append(list(argv))
            self.events.append("build-env-create")
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if SOURCE_BUILD_ENV_ATTEST_CODE in argv:
            assert env == {}
            self.argvs.append(list(argv))
            self.events.append("build-env-attest")
            records = json.loads(argv[-1])
            dependencies = tuple(
                BinaryWheelPolicy(
                    distribution=record["distribution"],
                    version=record["version"],
                    filename=record["filename"],
                    url=f"https://files.example.invalid/{record['filename']}",
                    size=record["size"],
                    sha256=record["sha256"],
                )
                for record in records
            )
            return ProgramResult(
                exit_code=0,
                stdout=source_build_environment_attestation(build_dependencies=dependencies),
                stderr="",
            )
        if (
            argv[:7]
            == [
                "python3",
                "-I",
                "-B",
                "-m",
                "pip",
                "--isolated",
                "--python",
            ]
            and "install" in argv
        ):
            assert env == {"PIP_NO_INDEX": "1"}
            self.argvs.append(list(argv))
            self.events.append("build-dependency-install")
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if SOURCE_BUILD_RUNNER_CODE in argv:
            assert env == {}
            self.argvs.append(list(argv))
            self.events.append("source-build")
            wheel_dir = argv[argv.index(SOURCE_BUILD_RUNNER_CODE) + 4]
            self.files[f"{wheel_dir}/verifier_helper-1.0-py3-none-any.whl"] = self.built_wheel
            return ProgramResult(exit_code=0, stdout="", stderr="")
        return await super().run(argv, env)

    async def read(self, path: str) -> bytes:
        if path in self.files:
            return self.files[path]
        return await super().read(path)

    async def write(self, path: str, data: bytes) -> None:
        self.files[path] = data


class LocalMetadataRuntime:
    def __init__(self, site: Path) -> None:
        self.site = site

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        process_env = os.environ.copy()
        process_env.update(env)
        process_env["PYTHONPATH"] = str(self.site)
        completed = subprocess.run(
            [sys.executable, *argv[1:]],
            capture_output=True,
            check=False,
            env=process_env,
            text=True,
        )
        return ProgramResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def dependency_taskset(tmp_path: Path) -> TerminalBenchVMVMTaskset:
    return TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            image_prefix="registry.invalid/terminal_bench",
            image_tag="test-revision",
            ignore_dockerfile=True,
        )
    )


def dependency_task(tmp_path: Path) -> SimpleNamespace:
    environment = tmp_path / "environment"
    tests = tmp_path / "tests"
    environment.mkdir(parents=True)
    tests.mkdir()
    (environment / "Dockerfile").write_text(
        "FROM python:3.12\n"
        "# Test dependencies prebaked so the verifier runs offline\n"
        "RUN pip install verifier-helper==1.0\n"
    )
    (tests / "test.sh").write_text("#!/bin/sh\n")
    return SimpleNamespace(name="task-a", slug="task-a", task_dir=str(tmp_path))


def source_policy_entry(
    requirement: str = "verifier-helper==1.0",
    *,
    image: str = "registry.invalid/task@sha256:" + "a" * 64,
    setup_requires: tuple[str, ...] = (),
    build_dependency_wheels: tuple[tuple[str, str, str, str, bytes], ...] = (),
) -> tuple[dict[str, object], bytes, bytes]:
    source_output = io.BytesIO()
    source_metadata = b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 1.0\n"
    setup_requires_clause = f", setup_requires={list(setup_requires)!r}" if setup_requires else ""
    setup_py = (
        f"from setuptools import setup\nsetup(name='verifier-helper', version='1.0'{setup_requires_clause})\n"
    ).encode()
    with tarfile.open(fileobj=source_output, mode="w:gz") as archive:
        for name, payload in (
            ("verifier_helper-1.0/PKG-INFO", source_metadata),
            ("verifier_helper-1.0/setup.py", setup_py),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    source = source_output.getvalue()
    wheel = wheel_file("verifier_helper-1.0-py3-none-any.whl")
    entry = {
        "requirements": [requirement],
        "image": image,
        "build_tools": dict(BUILD_TOOLS),
        "sources": [
            {
                "distribution": "verifier-helper",
                "version": "1.0",
                "filename": "verifier_helper-1.0.tar.gz",
                "url": "https://files.example.invalid/verifier_helper-1.0.tar.gz",
                "size": len(source),
                "sha256": sha256_bytes(source),
                "wheel_filename": "verifier_helper-1.0-py3-none-any.whl",
                "wheel_size": len(wheel),
                "wheel_sha256": sha256_bytes(wheel),
                "build_dependencies": [
                    {
                        "distribution": distribution,
                        "version": version,
                        "filename": filename,
                        "url": url,
                        "size": len(payload),
                        "sha256": sha256_bytes(payload),
                    }
                    for distribution, version, filename, url, payload in (
                        *baseline_build_dependency_wheels(),
                        *build_dependency_wheels,
                    )
                ],
            }
        ],
        "binary_wheels": [],
    }
    return entry, source, wheel


def source_dependency_taskset(
    tmp_path: Path,
    entries: list[dict[str, object]],
    *,
    expected_attestation_sha256: str | None = None,
    enable_compose: bool = False,
) -> TerminalBenchVMVMTaskset:
    policy_path = tmp_path / "source-wheel-policy.json"
    policy = {
        "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
        "allowed_hosts": ["files.example.invalid"],
        "entries": entries,
    }
    policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n")
    return TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            image_prefix="registry.invalid/terminal_bench",
            image_tag="test-revision",
            ignore_dockerfile=True,
            enable_compose=enable_compose,
            oracle_source_wheel_policy=policy_path,
            oracle_source_wheel_policy_sha256=sha256_bytes(policy_path.read_bytes()),
            oracle_source_wheel_attestation_path=tmp_path / "source_wheel_attestations.json",
            oracle_source_wheel_attestation_sha256=expected_attestation_sha256,
        )
    )


def synthetic_fingerprints(image: str) -> RuntimeWheelFingerprints:
    marker_environment = {
        "implementation_name": "cpython",
        "implementation_version": "3.12.0",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_release": "6.8.0",
        "platform_system": "Linux",
        "platform_version": "synthetic-runtime",
        "python_full_version": "3.12.0",
        "platform_python_implementation": "CPython",
        "python_version": "3.12",
        "sys_platform": "linux",
    }
    build_tools = {"pip": "24.3.1", "setuptools": "75.6.0", "wheel": "0.45.1"}
    wheel_compatibility = ["cpython", [3, 12], "cpython-312-x86_64-linux-gnu", "linux-x86_64", "x86_64"]
    evidence = {
        "marker_environment": marker_environment,
        "pip_version": "24.3.1",
        "wheel_compatibility": wheel_compatibility,
        "build_tools": build_tools,
    }
    return RuntimeWheelFingerprints(
        image=image,
        resolution=sha256_bytes(canonical_json([marker_environment, "24.3.1"])),
        compatibility=sha256_bytes(
            canonical_json([image, marker_environment, "24.3.1", wheel_compatibility, build_tools])
        ),
        build_tools=tuple(sorted(build_tools.items())),
        toolchain=sha256_bytes(canonical_json([image, build_tools])),
        evidence=canonical_json(evidence).decode(),
    )


def write_distribution(site: Path, name: str, version: str, *requirements: str) -> None:
    metadata_dir = site / f"{name.replace('-', '_')}-{version}.dist-info"
    metadata_dir.mkdir()
    metadata = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    (metadata_dir / "METADATA").write_text("\n".join(metadata) + "\n")


def test_missing_dependency_probe_honors_versions_extras_and_dependency_closure(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    write_distribution(site, "root-package", "1.0", 'extra-package>=2; extra == "feature"')
    runtime = LocalMetadataRuntime(site)
    taskset = dependency_taskset(tmp_path / "taskset")
    task = SimpleNamespace(name="task-a")

    assert asyncio.run(taskset._missing_test_dependencies(task, runtime, ("root-package==1.0.0",))) == ()
    assert asyncio.run(taskset._missing_test_dependencies(task, runtime, ("root-package[feature]==1.0.0",))) == (
        "root-package[feature]==1.0.0",
    )

    write_distribution(site, "extra-package", "2.1")
    assert asyncio.run(taskset._missing_test_dependencies(task, runtime, ("root-package[feature]==1.0.0",))) == ()

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    write_distribution(overlay, "root-package", "1.0", 'extra-package>=2; extra == "feature"')
    assert asyncio.run(
        taskset._missing_test_dependencies(
            task,
            runtime,
            ("root-package[feature]==1.0.0",),
            site_path=str(overlay),
        )
    ) == ("root-package[feature]==1.0.0",)
    write_distribution(overlay, "extra-package", "2.1")
    assert (
        asyncio.run(
            taskset._missing_test_dependencies(
                task,
                runtime,
                ("root-package[feature]==1.0.0",),
                site_path=str(overlay),
            )
        )
        == ()
    )
    taskset._cleanup_wheelhouse_cache()


@pytest.mark.parametrize(
    ("solution_network_mode", "agent_network_mode", "expected_events"),
    [
        ("declared", "no-network", ["network:no-network", "solution", "verifier"]),
        ("public", "no-network", ["solution", "network:no-network", "verifier"]),
        ("public", "public", ["network:public", "solution", "verifier"]),
    ],
)
def test_oracle_solution_network_mode_only_defers_declared_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    solution_network_mode: str,
    agent_network_mode: str,
    expected_events: list[str],
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            oracle_solution_network_mode=solution_network_mode,
        )
    )
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "solve.sh").write_text("#!/bin/sh\n")
    events: list[str] = []

    async def stage_directory(*args: object, **kwargs: object) -> None:
        return None

    async def configure_network(
        task: object,
        runtime: object,
        mode: str,
        *,
        activate: bool,
    ) -> None:
        assert activate is True
        events.append(f"network:{mode}")

    async def run_solution(task: object, runtime: object) -> ProgramResult:
        events.append("solution")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def run_verifier(
        task: object,
        runtime: object,
        *,
        stage_tests: bool,
    ) -> tuple[ProgramResult, bool, float, dict[str, float]]:
        assert stage_tests is True
        events.append("verifier")
        return ProgramResult(exit_code=0, stdout="", stderr=""), False, 1.0, {"solved": 1.0}

    monkeypatch.setattr(taskset, "_stage_directory", stage_directory)
    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network)
    monkeypatch.setattr(taskset, "_run_solution", run_solution)
    monkeypatch.setattr(taskset, "_run_verifier", run_verifier)
    task = SimpleNamespace(
        task_dir=str(tmp_path),
        agent_network_mode=agent_network_mode,
        verifier_mode="shared",
    )

    assert asyncio.run(taskset.validate(task, object())) is True
    assert events == expected_events


def test_model_setup_ignores_oracle_solution_network_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            oracle_solution_network_mode="public",
        )
    )
    events: list[str] = []

    async def setup(
        task: object,
        runtime: object,
        *,
        oracle_solution_network_mode: str,
    ) -> None:
        events.append(oracle_solution_network_mode)

    monkeypatch.setattr(taskset, "_setup", setup)
    asyncio.run(taskset.setup(object(), object()))
    asyncio.run(taskset.setup_oracle(object(), object()))

    assert events == ["declared", "public"]


def test_setup_prefetches_shared_isolated_verifier_before_public_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = dependency_taskset(tmp_path)
    events: list[str] = []

    async def run_root(*args: object, **kwargs: object) -> ProgramResult:
        events.append("trusted-setup")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def configure_network(*args: object, **kwargs: object) -> None:
        events.append("prepare-agent-network")

    async def prefetch(*args: object, **kwargs: object) -> None:
        events.append("prefetch-before-agent")

    monkeypatch.setattr(taskset, "_run_root", run_root)
    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network)
    monkeypatch.setattr(taskset, "_prefetch_test_dependencies", prefetch)
    monkeypatch.setattr(taskset_module, "_dockerfile_startup_command", lambda task_dir: None)
    task = SimpleNamespace(
        name="task-a",
        task_dir=str(tmp_path),
        resources=SimpleNamespace(gpu=0),
        workdir="/app",
        verifier_mode="shared",
        agent_network_mode="public",
        verifier_network_mode="no-network",
    )

    asyncio.run(taskset.setup(task, object()))

    assert events == ["prepare-agent-network", "trusted-setup", "prefetch-before-agent"]


@pytest.mark.parametrize(
    ("solution_network_mode", "last_event"),
    [("declared", "deferred-startup"), ("public", "public-startup")],
)
def test_oracle_setup_preserves_startup_before_public_solution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    solution_network_mode: str,
    last_event: str,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            oracle_solution_network_mode=solution_network_mode,
        )
    )
    runtime = VMVMRuntime(VMVMConfig(image="registry.invalid/task:latest", workdir="/app"))
    events: list[str] = []

    async def run_root(*args: object, **kwargs: object) -> ProgramResult:
        events.append("trusted-setup")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def configure_network(*args: object, **kwargs: object) -> None:
        events.append("prepare-isolation")

    async def run(*args: object, **kwargs: object) -> ProgramResult:
        events.append("public-startup")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    def defer(*args: object, **kwargs: object) -> None:
        events.append("deferred-startup")

    monkeypatch.setattr(taskset, "_run_root", run_root)
    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network)
    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr(runtime, "defer_until_network_isolated", defer)
    monkeypatch.setattr(taskset_module, "_dockerfile_startup_command", lambda task_dir: ["start-server"])
    task = SimpleNamespace(
        name="task-a",
        task_dir=str(tmp_path),
        resources=SimpleNamespace(gpu=0),
        workdir="/app",
        verifier_mode="separate",
        agent_network_mode="no-network",
    )

    asyncio.run(taskset.setup_oracle(task, runtime))

    assert events == ["prepare-isolation", "trusted-setup", last_event]


def test_public_oracle_isolation_failure_prevents_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            oracle_solution_network_mode="public",
        )
    )
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "solve.sh").write_text("#!/bin/sh\n")
    events: list[str] = []

    async def stage_directory(*args: object, **kwargs: object) -> None:
        return None

    async def configure_network(*args: object, **kwargs: object) -> None:
        events.append("isolation")
        raise RuntimeError("isolation failed")

    async def run_solution(*args: object, **kwargs: object) -> ProgramResult:
        events.append("solution")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def run_verifier(*args: object, **kwargs: object) -> tuple[ProgramResult, bool, float, dict[str, float]]:
        events.append("verifier")
        return ProgramResult(exit_code=0, stdout="", stderr=""), False, 1.0, {"solved": 1.0}

    monkeypatch.setattr(taskset, "_stage_directory", stage_directory)
    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network)
    monkeypatch.setattr(taskset, "_run_solution", run_solution)
    monkeypatch.setattr(taskset, "_run_verifier", run_verifier)
    task = SimpleNamespace(
        task_dir=str(tmp_path),
        agent_network_mode="no-network",
        verifier_mode="shared",
    )

    with pytest.raises(RuntimeError, match="isolation failed"):
        asyncio.run(taskset.validate(task, object()))
    assert events == ["solution", "isolation"]


def test_public_oracle_isolates_before_separate_artifact_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            oracle_solution_network_mode="public",
        )
    )
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "solve.sh").write_text("#!/bin/sh\n")
    events: list[str] = []

    async def configure_network(*args: object, **kwargs: object) -> None:
        events.append("isolation")

    async def run_solution(*args: object, **kwargs: object) -> ProgramResult:
        events.append("solution")
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def capture_artifacts(*args: object, **kwargs: object) -> tuple[dict[str, bytes], list[dict[str, str]]]:
        events.append("artifacts")
        return {}, []

    async def score_separate(
        *args: object, **kwargs: object
    ) -> tuple[ProgramResult, bool, float, dict[str, float], str, int, list[str]]:
        events.append("verifier")
        return ProgramResult(exit_code=0, stdout="", stderr=""), False, 1.0, {"solved": 1.0}, "vm", 1, []

    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network)
    monkeypatch.setattr(taskset, "_run_solution", run_solution)
    monkeypatch.setattr(taskset, "_capture_artifacts", capture_artifacts)
    monkeypatch.setattr(taskset, "_score_separate", score_separate)
    task = SimpleNamespace(
        idx=1,
        task_dir=str(tmp_path),
        agent_network_mode="no-network",
        verifier_mode="separate",
        verifier_timeout_sec=60.0,
    )

    assert asyncio.run(taskset.validate(task, object())) is True
    assert events == ["solution", "isolation", "artifacts", "verifier"]


def test_separate_verifier_retries_successful_score_after_teardown_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            verifier_runtime_retries=1,
        )
    )
    verifiers = [
        _VerifierRuntime(1, stop_error="stop boom"),
        _VerifierRuntime(2),
    ]
    events: list[str] = []

    def verifier_runtime(task, runtime, name):
        verifier = verifiers.pop(0)
        events.append(f"start-attempt-{verifier.attempt}")
        return verifier

    async def run_verifier(*args, **kwargs):
        return ProgramResult(exit_code=0, stdout="", stderr=""), False, 1.0, {"solved": 1.0}

    async def cleanup(task, trace, verifier) -> None:
        assert trace is None
        events.append(f"cleanup-attempt-{verifier.attempt}")
        if verifier.attempt == 1:
            raise RuntimeError("cleanup boom")

    monkeypatch.setattr(taskset, "_verifier_runtime", verifier_runtime)
    monkeypatch.setattr(taskset, "_run_verifier", run_verifier)
    monkeypatch.setattr(taskset, "cleanup", cleanup)
    task = SimpleNamespace(name="test", verifier_tests_baked=True)

    outcome = asyncio.run(taskset._score_separate(task, object(), {}, "trace"))

    assert outcome[2:6] == (1.0, {"solved": 1.0}, "verifier-2", 2)
    assert len(outcome[6]) == 1
    assert "taskset cleanup RuntimeError: cleanup boom" in outcome[6][0]
    assert "runtime stop RuntimeError: stop boom" in outcome[6][0]
    assert events == [
        "start-attempt-1",
        "cleanup-attempt-1",
        "start-attempt-2",
        "cleanup-attempt-2",
    ]


def test_separate_verifier_teardown_failure_exhaustion_is_sandbox_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            verifier_runtime_retries=0,
        )
    )
    verifier = _VerifierRuntime(1)

    async def run_verifier(*args, **kwargs):
        return ProgramResult(exit_code=0, stdout="", stderr=""), False, 1.0, {"solved": 1.0}

    async def cleanup(task, trace, runtime) -> None:
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(taskset, "_verifier_runtime", lambda task, runtime, name: verifier)
    monkeypatch.setattr(taskset, "_run_verifier", run_verifier)
    monkeypatch.setattr(taskset, "cleanup", cleanup)
    task = SimpleNamespace(name="test", verifier_tests_baked=True)

    with pytest.raises(SandboxError) as error:
        asyncio.run(taskset._score_separate(task, object(), {}, "trace"))

    assert "attempt 1: taskset cleanup RuntimeError: cleanup boom" in str(error.value)


def test_verifier_dependencies_prefetch_all_then_install_offline_after_solution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False)
    root_commands: list[str] = []
    run_root = taskset._run_root

    async def record_root(runtime: object, command: str) -> ProgramResult:
        root_commands.append(command)
        return await run_root(runtime, command)

    monkeypatch.setattr(taskset, "_run_root", record_root)

    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    prefetched = taskset._prefetched_test_dependencies[runtime]
    assert prefetched.requirements == ("verifier-helper==1.0",)
    assert prefetched.archive_path is not None
    controller_archive = prefetched.archive_path
    assert controller_archive.stat().st_mode & 0o777 == 0o400
    assert controller_archive.parent.stat().st_mode & 0o777 == 0o700
    assert runtime.events == ["fingerprint", "wheel", "archive-read"]
    assert not any("pip install" in command for command in runtime.commands)
    wheel_command = next(command for command in runtime.commands if " pip wheel " in command)
    wheel_argv = next(argv for argv in runtime.argvs if argv[:4] == ["python3", "-m", "pip", "wheel"])
    assert "--no-deps" not in wheel_command
    assert "--ignore-installed" not in wheel_command
    assert "--only-binary=:all:" in wheel_command

    bundled_pips = sorted((Path(sysconfig.get_path("stdlib")) / "ensurepip" / "_bundled").glob("pip-*.whl"))
    if bundled_pips:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(bundled_pips[-1]), environment.get("PYTHONPATH", ""))).rstrip(
            os.pathsep
        )
        parsed = subprocess.run(
            [sys.executable, *wheel_argv[1:], "--help"],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        assert parsed.returncode == 0, parsed.stderr

    runtime.events.append("solution")
    runtime.installed = False
    verifier_site = asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))

    assert runtime.events == [
        "fingerprint",
        "wheel",
        "archive-read",
        "solution",
        "probe",
        "archive-write",
        "overlay-install",
        "bootstrap-write",
        "overlay-probe",
    ]
    assert verifier_site is not None
    assert verifier_site.site_path.startswith("/tmp/terminal-bench-verifier-site-")
    assert verifier_site.bootstrap_path.startswith("/tmp/terminal-bench-verifier-bootstrap-")
    install_command = next(command for command in runtime.commands if "PIP_NO_INDEX=1" in command)
    assert "--no-index" in install_command
    assert "--no-deps" in install_command
    assert "--target" in install_command
    assert "--ignore-installed" not in install_command
    assert "--break-system-packages" not in install_command
    assert "/*.whl" in install_command
    assert "--find-links" not in install_command
    assert "/sitecustomize.py" in install_command
    assert "/usercustomize.py" in install_command
    assert runtime.installed is False
    assert runtime.overlay_installed is True
    overlay_probe_envs = [
        environment for environment in runtime.environments if "TERMINAL_BENCH_VERIFIER_SITE" in environment
    ]
    assert overlay_probe_envs == [{"TERMINAL_BENCH_VERIFIER_SITE": verifier_site.site_path}]
    assert any("PIP_NO_INDEX=1" in command for command in root_commands)
    assert controller_archive.exists() is True
    assert runtime not in taskset._prefetched_test_dependencies
    taskset._cleanup_wheelhouse_cache()
    assert controller_archive.exists() is False


def test_scripted_dependencies_prefetch_full_set_and_restore_post_agent_drift(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    (Path(task.task_dir) / "environment" / "Dockerfile").write_text("FROM python:3.12\n")
    (Path(task.task_dir) / "tests" / "test.sh").write_text("pip install verifier-helper==1.0\n")

    runtime = DependencyRuntime(installed=True)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    assert taskset._prefetched_test_dependencies[runtime].requirements == ("verifier-helper==1.0",)
    assert runtime.events == ["fingerprint", "wheel", "archive-read"]

    runtime.events.append("agent")
    runtime.installed = False
    verifier_site = asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))
    assert runtime.events == [
        "fingerprint",
        "wheel",
        "archive-read",
        "agent",
        "probe",
        "archive-write",
        "overlay-install",
        "bootstrap-write",
        "overlay-probe",
    ]
    assert verifier_site is not None
    assert runtime.installed is False
    assert runtime.overlay_installed is True
    taskset._cleanup_wheelhouse_cache()


def test_wheelhouse_cache_cleans_when_taskset_is_released(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    cache_path = taskset._wheelhouse_cache_path()
    assert cache_path.exists()
    taskset_ref = ref(taskset)

    del taskset
    gc.collect()

    assert taskset_ref() is None
    assert cache_path.exists() is False


def test_verifier_dependency_wheel_failure_is_fail_closed(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False, wheel_failure=True)

    with pytest.raises(RuntimeError, match="wheel prefetch failed"):
        asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    assert runtime.events == ["fingerprint", "wheel"]
    assert runtime not in taskset._prefetched_test_dependencies


def test_verifier_dependency_source_distribution_is_fail_closed(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(source_only=True)

    with pytest.raises(RuntimeError, match="wheel prefetch failed"):
        asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    wheel_command = next(command for command in runtime.commands if " pip wheel " in command)
    assert "--only-binary=:all:" in wheel_command
    assert runtime not in taskset._prefetched_test_dependencies


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        (
            "ERROR: Could not find a version that satisfies the requirement example==1\n"
            "ERROR: No matching distribution found for example==1\n",
            "",
            True,
        ),
        ("ERROR: No matching distribution found for example==1\n", "", False),
        (
            "ERROR: Could not find a version that satisfies the requirement example==1\n"
            "ERROR: No matching distribution found for example==1\n",
            "Read timed out",
            False,
        ),
        ("", "", False),
    ],
)
def test_binary_distribution_unavailable_classifier_is_narrow(
    stdout: str,
    stderr: str,
    expected: bool,
) -> None:
    result = ProgramResult(exit_code=1, stdout=stdout, stderr=stderr)
    assert _binary_distribution_unavailable(result) is expected


def test_source_wheel_policy_rejects_mutable_image_and_unapproved_closure(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    policy = {
        "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
        "allowed_hosts": ["files.example.invalid"],
        "entries": [entry],
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy) + "\n")
    loaded = load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))
    assert loaded.entries[0].image.endswith("a" * 64)

    entry["image"] = "registry.invalid/task:latest"
    path.write_text(json.dumps(policy) + "\n")
    with pytest.raises(ValueError, match="digest-pinned"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))

    entry, _, _ = source_policy_entry()
    entry["sources"] = []
    path.write_text(json.dumps({**policy, "entries": [entry]}) + "\n")
    with pytest.raises(ValueError, match="exactly one"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))

    entry, _, _ = source_policy_entry()
    entry["sources"] = [entry["sources"][0], dict(entry["sources"][0])]
    path.write_text(json.dumps({**policy, "entries": [entry]}) + "\n")
    with pytest.raises(ValueError, match="exactly one"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))

    entry, _, _ = source_policy_entry()
    entry["sources"][0]["build_dependencies"] = [
        wheel for wheel in entry["sources"][0]["build_dependencies"] if wheel["distribution"] != "setuptools"
    ]
    path.write_text(json.dumps({**policy, "entries": [entry]}) + "\n")
    with pytest.raises(ValueError, match="isolated build-tool closure"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))

    entry, _, _ = source_policy_entry()
    path.write_text(json.dumps({**policy, "schema_version": 2, "entries": [entry]}) + "\n")
    with pytest.raises(ValueError, match="unsupported source-wheel policy schema"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))


def test_source_wheel_policy_rejects_duplicate_json_keys_and_nonfinite_values(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    policy = {
        "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
        "allowed_hosts": ["files.example.invalid"],
        "entries": [entry],
    }
    canonical = json.dumps(policy, sort_keys=True)
    for payload in (
        canonical.replace(
            f'"schema_version": {SOURCE_WHEEL_POLICY_SCHEMA_VERSION}',
            f'"schema_version": {SOURCE_WHEEL_POLICY_SCHEMA_VERSION}, '
            f'"schema_version": {SOURCE_WHEEL_POLICY_SCHEMA_VERSION}',
            1,
        ),
        canonical.replace('"size": ', '"size": NaN, "ignored_size": ', 1),
    ):
        path = tmp_path / f"policy-{hashlib.sha256(payload.encode()).hexdigest()}.json"
        path.write_text(payload + "\n")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))


def test_source_wheel_policy_rejects_build_dependency_filename_collisions(tmp_path: Path) -> None:
    dependency = wheel_file("legacy_backend-0.1-py3-none-any.whl")
    entry, _, _ = source_policy_entry(
        setup_requires=("legacy-backend==0.1",),
        build_dependency_wheels=(
            (
                "legacy-backend",
                "0.1",
                "verifier_helper-1.0-py3-none-any.whl",
                "https://files.example.invalid/verifier_helper-1.0-py3-none-any.whl",
                dependency,
            ),
        ),
    )
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                "allowed_hosts": ["files.example.invalid"],
                "entries": [entry],
            }
        )
    )
    with pytest.raises(ValueError, match="duplicate build/runtime wheel filenames"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))

    entry, _, _ = source_policy_entry(
        setup_requires=("legacy-backend==0.1",),
        build_dependency_wheels=(
            (
                "legacy-backend",
                "0.1",
                "runtime_helper-0.1-py3-none-any.whl",
                "https://files.example.invalid/runtime_helper-0.1-py3-none-any.whl",
                dependency,
            ),
        ),
    )
    entry["binary_wheels"] = [
        {
            "distribution": "runtime-helper",
            "version": "0.1",
            "filename": "runtime_helper-0.1-py3-none-any.whl",
            "url": "https://files.example.invalid/runtime_helper-0.1-py3-none-any.whl",
            "size": len(dependency),
            "sha256": sha256_bytes(dependency),
        }
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                "allowed_hosts": ["files.example.invalid"],
                "entries": [entry],
            }
        )
    )
    with pytest.raises(ValueError, match="duplicate input filenames"):
        load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))


def test_source_build_venv_reaches_setup_child_process_with_isolated_python(tmp_path: Path) -> None:
    build_env = tmp_path / "build-env"
    build_dep_dir = tmp_path / "build-deps"
    input_dir = tmp_path / "inputs"
    wheel_dir = tmp_path / "wheels"
    build_dep_dir.mkdir()
    input_dir.mkdir()
    wheel_dir.mkdir()

    build_dependency = wheel_file_with_module(
        "child_build_dep-0.1-py3-none-any.whl",
        "child_build_dep",
        (
            b"VALUE = 'bound-build-dependency'\n"
            b"def main():\n"
            b"    import os, sys\n"
            b"    assert os.path.basename(sys.prefix) == 'build-env'\n"
            b"    print(VALUE)\n"
        ),
        console_script="child-build-tool",
    )
    build_dependency_path = build_dep_dir / "child_build_dep-0.1-py3-none-any.whl"
    build_dependency_path.write_bytes(build_dependency)
    build_dependency_policy = BinaryWheelPolicy(
        distribution="child-build-dep",
        version="0.1",
        filename=build_dependency_path.name,
        url="https://files.example.invalid/child_build_dep-0.1-py3-none-any.whl",
        size=len(build_dependency),
        sha256=sha256_bytes(build_dependency),
    )

    setup_py = (
        "from setuptools import setup\n"
        "import os, shutil, subprocess, sys\n"
        "import child_build_dep\n"
        "import child_project\n"
        "import wheel\n"
        "assert sys.flags.isolated == 1\n"
        "assert sys.flags.ignore_environment == 1\n"
        "assert sys.flags.no_user_site == 1\n"
        "assert sys.flags.no_site == 1\n"
        "assert child_build_dep.VALUE == 'bound-build-dependency'\n"
        "assert child_project.__version__ == '1.0'\n"
        "assert os.path.commonpath((sys.prefix, os.path.realpath(wheel.__file__))) == sys.prefix\n"
        "assert os.environ['SOURCE_DATE_EPOCH'] == '315532800'\n"
        "assert os.environ['TZ'] == 'UTC'\n"
        "assert os.environ['PATH'] == os.path.join(sys.prefix, 'bin')\n"
        "assert shutil.which('sh') is None\n"
        "for command in ('python3', 'child-build-tool'):\n"
        "    resolved = os.path.abspath(shutil.which(command))\n"
        "    assert os.path.commonpath((sys.prefix, resolved)) == sys.prefix\n"
        "child = subprocess.run(['python3', '-I', '-c', "
        "'import child_build_dep,sys; assert sys.flags.isolated; print(child_build_dep.VALUE)'], "
        "check=True, capture_output=True, text=True)\n"
        "assert child.stdout.strip() == 'bound-build-dependency'\n"
        "tool = subprocess.run(['child-build-tool'], check=True, capture_output=True, text=True)\n"
        "assert tool.stdout.strip() == 'bound-build-dependency'\n"
        "setup(name='child-project', version=child_project.__version__, packages=[])\n"
    ).encode()
    source_buffer = io.BytesIO()
    with tarfile.open(fileobj=source_buffer, mode="w:gz") as archive:
        for name, payload in (
            ("child_project-1.0/PKG-INFO", b"Metadata-Version: 2.1\nName: child-project\nVersion: 1.0\n"),
            ("child_project-1.0/setup.py", setup_py),
            ("child_project-1.0/setup.cfg", b"[options]\nsetup_requires = child-build-dep==0.1\n"),
            (
                "child_project-1.0/pyproject.toml",
                b"[build-system]\nrequires = ['setuptools', 'wheel']\nbuild-backend = 'setuptools.build_meta'\n",
            ),
            (
                "child_project-1.0/child_project/__init__.py",
                b"__version__ = '1.0'\nraise RuntimeError('initializer must not execute')\n",
            ),
            ("child_project-1.0/wheel.py", b"raise RuntimeError('source shadow loaded')\n"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    source_payload = source_buffer.getvalue()
    source_path = input_dir / "child_project-1.0.tar.gz"
    source_path.write_bytes(source_payload)
    source = SourceArtifactPolicy(
        distribution="child-project",
        version="1.0",
        filename=source_path.name,
        url="https://files.example.invalid/child_project-1.0.tar.gz",
        size=len(source_payload),
        sha256=sha256_bytes(source_payload),
        wheel_filename="child_project-1.0-py3-none-any.whl",
        wheel_size=1,
        wheel_sha256="0" * 64,
        build_dependencies=(build_dependency_policy,),
    )
    subprocess.run(source_build_env_create_argv(str(build_env)), check=True)
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is unavailable to seed the public real-backend test environment")
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--python",
            str(build_env / "bin" / "python"),
            "pip",
            "setuptools",
            "wheel",
            str(build_dependency_path),
        ],
        check=True,
    )
    installed = subprocess.run(
        [
            str(build_env / "bin" / "python"),
            "-I",
            "-B",
            "-c",
            (
                "import importlib.metadata as m,json; "
                "print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions())))"
            ),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    installed_policies = tuple(
        BinaryWheelPolicy(
            distribution=canonical_distribution_name(name),
            version=version,
            filename=f"{canonical_distribution_name(name).replace('-', '_')}-{version}-py3-none-any.whl",
            url=(
                "https://files.example.invalid/"
                f"{canonical_distribution_name(name).replace('-', '_')}-{version}-py3-none-any.whl"
            ),
            size=1,
            sha256=sha256_bytes(f"{name}=={version}".encode()),
        )
        for name, version in json.loads(installed.stdout)
    )
    attested = subprocess.run(
        source_build_env_attest_argv(str(build_env), installed_policies),
        capture_output=True,
        check=True,
        text=True,
    )
    attestation = json.loads(attested.stdout)
    validate_source_build_environment(
        attested.stdout,
        build_env_dir=str(build_env),
        expected_build_tools=tuple(sorted(attestation["build_tools"].items())),
        build_dependencies=installed_policies,
    )
    tampered_attestation = json.loads(attested.stdout)
    tampered_attestation["bin_entries"][0]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="attestation is invalid"):
        validate_source_build_environment(
            json.dumps(tampered_attestation),
            build_env_dir=str(build_env),
            expected_build_tools=tuple(sorted(attestation["build_tools"].items())),
            build_dependencies=installed_policies,
        )
    assert all(record["file_count"] > 0 for record in attestation["installed_distributions"])
    missing_private_dirs = subprocess.run(
        source_build_argv(
            source,
            input_dir=str(input_dir),
            wheel_dir=str(wheel_dir),
            build_env_dir=str(build_env),
        ),
        capture_output=True,
        check=False,
    )
    assert missing_private_dirs.returncode != 0
    assert not list(wheel_dir.iterdir())
    Path(f"{build_env}-home").mkdir(mode=0o700)
    Path(f"{build_env}-tmp").mkdir(mode=0o700)
    subprocess.run(
        source_build_argv(
            source,
            input_dir=str(input_dir),
            wheel_dir=str(wheel_dir),
            build_env_dir=str(build_env),
        ),
        check=True,
    )

    built_wheel_path = wheel_dir / "child_project-1.0-py3-none-any.whl"
    assert built_wheel_path.is_file()
    assert inspect_wheel(built_wheel_path.name, built_wheel_path.read_bytes()).distribution == "child-project"

    shutil.rmtree(Path(f"{build_env}-work"))
    shadow_wheel_dir = tmp_path / "shadow-wheels"
    shadow_wheel_dir.mkdir()
    shadow_buffer = io.BytesIO()
    with tarfile.open(fileobj=shadow_buffer, mode="w:gz") as archive:
        for name, payload in (
            (
                "shadow_project-1.0/PKG-INFO",
                b"Metadata-Version: 2.1\nName: shadow-project\nVersion: 1.0\n",
            ),
            (
                "shadow_project-1.0/setup.py",
                b"from setuptools import setup\nsetup(name='shadow-project', version='1.0')\n",
            ),
            ("shadow_project-1.0/setuptools.py", b"raise RuntimeError('shadow loaded')\n"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    shadow_payload = shadow_buffer.getvalue()
    shadow_source_path = input_dir / "shadow_project-1.0.tar.gz"
    shadow_source_path.write_bytes(shadow_payload)
    shadow_source = SourceArtifactPolicy(
        distribution="shadow-project",
        version="1.0",
        filename=shadow_source_path.name,
        url="https://files.example.invalid/shadow_project-1.0.tar.gz",
        size=len(shadow_payload),
        sha256=sha256_bytes(shadow_payload),
        wheel_filename="shadow_project-1.0-py3-none-any.whl",
        wheel_size=1,
        wheel_sha256="0" * 64,
        build_dependencies=(build_dependency_policy,),
    )
    shadowed = subprocess.run(
        source_build_argv(
            shadow_source,
            input_dir=str(input_dir),
            wheel_dir=str(shadow_wheel_dir),
            build_env_dir=str(build_env),
        ),
        capture_output=True,
        check=False,
    )
    assert shadowed.returncode != 0
    assert not list(shadow_wheel_dir.iterdir())

    site_packages = next(build_env.glob("lib/python*/site-packages"))
    ambient_root = tmp_path / "ambient-import-root"
    ambient_root.mkdir()
    path_injection = site_packages / "ambient-import-root.pth"
    path_injection.write_text(f"{ambient_root}\n")
    injected = subprocess.run(
        source_build_env_attest_argv(str(build_env), installed_policies),
        capture_output=True,
        check=False,
        text=True,
    )
    assert injected.returncode != 0
    path_injection.unlink()

    symlink = site_packages / "ambient-file-link"
    symlink.symlink_to(site_packages / "setuptools")
    linked = subprocess.run(
        source_build_env_attest_argv(str(build_env), installed_policies),
        capture_output=True,
        check=False,
        text=True,
    )
    assert linked.returncode != 0


def test_source_builds_are_byte_identical_across_independent_delayed_environments(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is unavailable to seed the public reproducibility test environments")
    setup_py = (
        "from setuptools import setup\n"
        "import sys\n"
        "assert sys.flags.isolated == 1\n"
        "setup(name='delayed-project', version='1.0', py_modules=['delayed_module'])\n"
    ).encode()
    source_buffer = io.BytesIO()
    with tarfile.open(fileobj=source_buffer, mode="w:gz") as archive:
        for name, payload in (
            ("delayed_project-1.0/PKG-INFO", b"Metadata-Version: 2.1\nName: delayed-project\nVersion: 1.0\n"),
            ("delayed_project-1.0/setup.py", setup_py),
            ("delayed_project-1.0/delayed_module.py", b"VALUE = 'deterministic'\n"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    source_payload = source_buffer.getvalue()
    source = SourceArtifactPolicy(
        distribution="delayed-project",
        version="1.0",
        filename="delayed_project-1.0.tar.gz",
        url="https://files.example.invalid/delayed_project-1.0.tar.gz",
        size=len(source_payload),
        sha256=sha256_bytes(source_payload),
        wheel_filename="delayed_project-1.0-py3-none-any.whl",
        wheel_size=1,
        wheel_sha256="0" * 64,
    )

    wheels: list[bytes] = []
    for index in range(2):
        if index:
            time.sleep(1.1)
        build_env = tmp_path / f"build-env-{index}"
        input_dir = tmp_path / f"inputs-{index}"
        wheel_dir = tmp_path / f"wheels-{index}"
        input_dir.mkdir()
        wheel_dir.mkdir()
        (input_dir / source.filename).write_bytes(source_payload)
        subprocess.run(source_build_env_create_argv(str(build_env)), check=True)
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--quiet",
                "--python",
                str(build_env / "bin" / "python"),
                "setuptools",
                "wheel",
            ],
            check=True,
        )
        Path(f"{build_env}-home").mkdir(mode=0o700)
        Path(f"{build_env}-tmp").mkdir(mode=0o700)
        subprocess.run(
            source_build_argv(
                source,
                input_dir=str(input_dir),
                wheel_dir=str(wheel_dir),
                build_env_dir=str(build_env),
            ),
            check=True,
        )
        outputs = list(wheel_dir.iterdir())
        assert len(outputs) == 1
        wheels.append(outputs[0].read_bytes())

    assert wheels[0] == wheels[1]


def test_source_distribution_accepts_matching_duplicate_metadata_only(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    metadata = b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 1.0\n"

    def archive(second: bytes) -> bytes:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            for name, payload in (
                ("verifier_helper-1.0/PKG-INFO", metadata),
                ("verifier_helper-1.0/verifier_helper.egg-info/PKG-INFO", second),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
        return output.getvalue()

    matching = archive(metadata)
    source = entry["sources"][0]
    source["size"] = len(matching)
    source["sha256"] = sha256_bytes(matching)
    policy_path = tmp_path / "matching-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                "allowed_hosts": ["files.example.invalid"],
                "entries": [entry],
            }
        )
    )
    loaded = load_source_wheel_policy(policy_path, sha256_bytes(policy_path.read_bytes()))
    inspect_source_distribution(loaded.entries[0].sources[0], matching)

    mismatched = archive(b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 2.0\n")
    source["size"] = len(mismatched)
    source["sha256"] = sha256_bytes(mismatched)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                "allowed_hosts": ["files.example.invalid"],
                "entries": [entry],
            }
        )
    )
    loaded = load_source_wheel_policy(policy_path, sha256_bytes(policy_path.read_bytes()))
    with pytest.raises(RuntimeError, match="metadata does not match"):
        inspect_source_distribution(loaded.entries[0].sources[0], mismatched)


def test_static_build_requirement_extraction_is_fail_closed(tmp_path: Path) -> None:
    entry, source_payload, _ = source_policy_entry(setup_requires=("legacy-backend==0.1", "cffi>=1.0"))
    policy_path = tmp_path / "policy.json"

    def load_source(payload: bytes):
        source = dict(entry["sources"][0])
        source["size"] = len(payload)
        source["sha256"] = sha256_bytes(payload)
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": SOURCE_WHEEL_POLICY_SCHEMA_VERSION,
                    "allowed_hosts": ["files.example.invalid"],
                    "entries": [{**entry, "sources": [source]}],
                }
            )
            + "\n"
        )
        return load_source_wheel_policy(policy_path, sha256_bytes(policy_path.read_bytes())).entries[0].sources[0]

    assert extract_static_setup_requires(load_source(source_payload), source_payload) == (
        "legacy-backend==0.1",
        "cffi>=1.0",
    )

    def archive(*members: tuple[str, bytes]) -> bytes:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            for name, payload in members:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
        return output.getvalue()

    metadata = b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 1.0\n"
    missing_setup = archive(("verifier_helper-1.0/PKG-INFO", metadata))
    with pytest.raises(RuntimeError, match="missing setup.py"):
        extract_static_setup_requires(load_source(missing_setup), missing_setup)

    dynamic_setup = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nREQS = ['legacy-backend==0.1']\nsetup(name='verifier-helper', version='1.0', setup_requires=REQS)\n",
        ),
    )
    with pytest.raises(RuntimeError, match="static literal"):
        extract_static_setup_requires(load_source(dynamic_setup), dynamic_setup)

    nested_setup = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/example/setup.py", b"from setuptools import setup\nsetup(name='nested')\n"),
    )
    assert extract_static_setup_requires(load_source(nested_setup), nested_setup) == ()

    ambiguous_root = archive(
        ("PKG-INFO", metadata),
        ("setup.py", b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n"),
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
    )
    with pytest.raises(RuntimeError, match="ambiguous setup metadata"):
        extract_static_setup_requires(load_source(ambiguous_root), ambiguous_root)

    invalid_pyproject = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/pyproject.toml", b"[build-system]\n"),
    )
    with pytest.raises(RuntimeError, match="pyproject.toml build-system"):
        extract_static_build_requirements(load_source(invalid_pyproject), invalid_pyproject)

    pyproject = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/pyproject.toml",
            b"[build-system]\nrequires = ['setuptools>=60', 'wheel']\nbuild-backend = 'setuptools.build_meta'\n",
        ),
    )
    assert extract_static_build_requirements(load_source(pyproject), pyproject) == (
        "setuptools>=60",
        "wheel",
    )

    setup_cfg = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/setup.cfg",
            b"[options]\nsetup_requires =\n    hidden-backend>=1\n    cffi>=1\n",
        ),
    )
    assert extract_static_build_requirements(load_source(setup_cfg), setup_cfg) == (
        "hidden-backend>=1",
        "cffi>=1",
    )

    confined_setup_cfg = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/setup.cfg",
            b"[metadata]\n"
            b"name = verifier-helper\n"
            b"license_files = LICENSE*\n"
            b"[options]\n"
            b"packages = verifier_helper\n"
            b"package_dir =\n"
            b"    = src\n"
            b"include_package_data = false\n"
            b"[options.package_data]\n"
            b"verifier_helper = data/*.txt\n"
            b"[bdist_wheel]\n"
            b"universal = 1\n"
            b"[egg_info]\n"
            b"egg_base = metadata\n"
            b"tag_build =\n"
            b"tag_date = 0\n",
        ),
    )
    assert extract_static_build_requirements(load_source(confined_setup_cfg), confined_setup_cfg) == ()

    unsafe_setup_cfgs = (
        b"[options]\ncffi_modules = build.py:ffi\n",
        b"[options]\next_modules = proof.extension\n",
        b"[options]\npackage_dir =\n    = ../../escape\npackages = verifier_helper\n",
        b"[options.package_data]\nverifier_helper = ../../outside/*\n",
        b"[egg_info]\negg_base = ../../escape\n",
        b"[metadata]\nlicense_file = /etc/passwd\n",
        b"[metadata]\nlicense_file = LICENSE, /etc/passwd\n",
        b"[options]\ninclude_package_data = true\n",
        b"[options.data_files]\n/etc = verifier_helper.py\n",
    )
    for setup_cfg_payload in unsafe_setup_cfgs:
        unsafe_setup_cfg = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            (
                "verifier_helper-1.0/setup.py",
                b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
            ),
            ("verifier_helper-1.0/setup.cfg", setup_cfg_payload),
        )
        with pytest.raises(RuntimeError, match="setup.cfg"):
            extract_static_build_requirements(load_source(unsafe_setup_cfg), unsafe_setup_cfg)

    conflicting_config = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', setup_requires=['one-backend'])\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[options]\nsetup_requires = other-backend\n"),
    )
    with pytest.raises(RuntimeError, match="ambiguous setup_requires"):
        extract_static_build_requirements(load_source(conflicting_config), conflicting_config)

    unsupported_backend = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/pyproject.toml",
            b"[build-system]\nrequires = ['custom-backend']\nbuild-backend = 'custom_backend'\n",
        ),
    )
    with pytest.raises(RuntimeError, match="unsupported or ambiguous"):
        extract_static_build_requirements(load_source(unsupported_backend), unsupported_backend)

    in_tree_backend = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/pyproject.toml",
            b"[build-system]\nrequires = ['setuptools']\nbackend-path = ['backend']\n",
        ),
    )
    with pytest.raises(RuntimeError, match="unsupported or ambiguous"):
        extract_static_build_requirements(load_source(in_tree_backend), in_tree_backend)

    default_config = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[DEFAULT]\nsetup_requires = hidden-backend\n[options]\n"),
    )
    with pytest.raises(RuntimeError, match="default options"):
        extract_static_build_requirements(load_source(default_config), default_config)

    dynamic_config = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[metadata]\nversion = attr: package.VERSION\n"),
    )
    with pytest.raises(RuntimeError, match="executable or dynamic option"):
        extract_static_build_requirements(load_source(dynamic_config), dynamic_config)

    command_config = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[options]\ncmdclass = build=package.CustomBuild\n"),
    )
    with pytest.raises(RuntimeError, match="executable or dynamic option"):
        extract_static_build_requirements(load_source(command_config), command_config)

    unsupported_config_section = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[aliases]\nbuild = custom_build\n"),
    )
    with pytest.raises(RuntimeError, match="unsupported command alias"):
        extract_static_build_requirements(load_source(unsupported_config_section), unsupported_config_section)

    pyproject_tool_section = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        (
            "verifier_helper-1.0/pyproject.toml",
            b"[build-system]\nrequires = ['setuptools']\n[tool.setuptools.dynamic]\nversion = {attr = 'pkg.VERSION'}\n",
        ),
    )
    with pytest.raises(RuntimeError, match="unsupported or ambiguous"):
        extract_static_build_requirements(load_source(pyproject_tool_section), pyproject_tool_section)

    module_style = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import setuptools\nsetuptools.setup(name='verifier-helper', version='1.0', "
            b"setup_requires=('legacy-backend==0.1',))\n",
        ),
    )
    assert extract_static_setup_requires(load_source(module_style), module_style) == ("legacy-backend==0.1",)

    literal_containers = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b'"""static package declaration"""\n'
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', version='1.0', packages=[], "
            b"package_data={'': ['*.txt']}, include_package_data=False)\n",
        ),
    )
    assert extract_static_build_requirements(load_source(literal_containers), literal_containers) == ()

    ambiguous_setup_sources = (
        b"from setuptools import setup\nsetup(**{'name': 'verifier-helper'})\n",
        b"from setuptools import setup\nsetup({'name': 'verifier-helper'})\n",
        b"from setuptools import setup as make_setup\nmake_setup(name='verifier-helper')\n",
        b"import setuptools as tools\ntools.setup(name='verifier-helper')\n",
        b"from setuptools import setup\nmake_setup = setup\nmake_setup(name='verifier-helper')\n",
        b"import setuptools\ngetattr(setuptools, 'setup')(name='verifier-helper')\n",
        b"from setuptools import setup\nif True:\n    setup(name='verifier-helper')\n",
        b"from distutils.core import setup\nsetup(name='verifier-helper')\n",
        b"from setuptools import setup\nfrom another_backend import setup\nsetup(name='verifier-helper')\n",
        b"import setuptools\nimport another_backend as setuptools\nsetuptools.setup(name='verifier-helper')\n",
        b"from setuptools import setup\nfrom another_backend import *\nsetup(name='verifier-helper')\n",
        b"from setuptools import setup\ndef setup(**kwargs):\n    return kwargs\nsetup(name='hidden')\n",
        b"import setuptools\nclass setuptools:\n    setup = staticmethod(lambda **kwargs: kwargs)\nsetuptools.setup(name='hidden')\n",
        b"from setuptools import setup\nsetup(name='one')\nsetup(name='two')\n",
        b"from setuptools import setup, setup as hidden_setup\nsetup(name='one')\nhidden_setup(name='two', setup_requires=['hidden-backend'])\n",
        b"from setuptools import setup\ngetattr(__import__('setuptools'), 'set' + 'up')(name='hidden', setup_requires=['hidden-backend'])\nsetup(name='one')\n",
        b"from setuptools import setup\nglobals()['set' + 'up'](name='hidden', setup_requires=['hidden-backend'])\nsetup(name='one')\n",
        b"from setuptools import setup\ndef wrapper(**kwargs):\n    return setup(**kwargs)\nwrapper(name='hidden')\n",
        b"import os\nfrom setuptools import setup\nos.system('external-command')\nsetup(name='one')\n",
        b"from helper import metadata\nfrom setuptools import setup\nsetup(name='one', description=metadata())\n",
        b"from setuptools import setup\nclass Wrapper:\n    def invoke(self):\n        setup(name='hidden')\nWrapper().invoke()\n",
        b"from setuptools import setup\nsetup(name='one', distclass='custom')\n",
        b"from setuptools import setup\nsetup(name='one', version=get_version())\n",
        b"import os\nfrom setuptools import setup\nsetup(name='one', version=os.path.join('dynamic', 'version'))\n",
        b"import os\nfrom setuptools import setup\nVERSION = os.path.join('dynamic', 'version')\nsetup(name='one', version=VERSION)\n",
        b"import os\nfrom setuptools import setup\n__file__ = '/etc'\nsetup(name='one', long_description=open(os.path.join(os.path.dirname(__file__), 'passwd')).read())\n",
        b"import os\nfrom setuptools import setup\ndef read(__file__):\n    return open(os.path.join(os.path.dirname(__file__), 'README')).read()\nsetup(name='one', long_description=read('/etc/passwd'))\n",
        b"from setuptools import setup\ndef metadata():\n    return 'dynamic'\nsetup(name='one', description=metadata())\n",
        b"from setuptools import setup\nsetup(name='one', setup_requires=get_requirements())\n",
        b"from setuptools import setup\nif True:\n    setup(name='one')\n",
    )
    for setup_source in ambiguous_setup_sources:
        ambiguous = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            ("verifier_helper-1.0/setup.py", setup_source),
        )
        with pytest.raises(RuntimeError, match="setup"):
            extract_static_setup_requires(load_source(ambiguous), ambiguous)

    inert_local_metadata = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import verifier_helper\n"
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', version=verifier_helper.__version__, "
            b"author=verifier_helper.__author__, author_email=verifier_helper.__email__, "
            b"description=verifier_helper.__doc__)\n",
        ),
        (
            "verifier_helper-1.0/verifier_helper/__init__.py",
            b'"""Static description."""\n'
            b"__version__ = '1.0'\n"
            b"__author__ = 'Maintainer'\n"
            b"__email__ = 'maintainer@example.invalid'\n"
            b"raise RuntimeError('module body must never execute during the build')\n",
        ),
    )
    assert extract_static_build_requirements(load_source(inert_local_metadata), inert_local_metadata) == ()
    assert "metadata_stub = types.ModuleType(module)" in SOURCE_BUILD_RUNNER_CODE
    assert "sys.modules[module] = metadata_stub" in SOURCE_BUILD_RUNNER_CODE

    helper_import = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import metadata_helper\n"
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', version=metadata_helper.__version__)\n",
        ),
        ("verifier_helper-1.0/metadata_helper/__init__.py", b"__version__ = '1.0'\n"),
    )
    with pytest.raises(RuntimeError, match="unsupported helper import"):
        extract_static_build_requirements(load_source(helper_import), helper_import)

    dynamic_local_metadata = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import verifier_helper\n"
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', version=verifier_helper.__version__)\n",
        ),
        (
            "verifier_helper-1.0/verifier_helper/__init__.py",
            b"__version__ = resolve_version()\n",
        ),
    )
    with pytest.raises(RuntimeError, match="not one static string"):
        extract_static_build_requirements(load_source(dynamic_local_metadata), dynamic_local_metadata)

    ambiguous_local_metadata = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import verifier_helper\n"
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', version=verifier_helper.__version__)\n",
        ),
        ("verifier_helper-1.0/verifier_helper.py", b"__version__ = '1.0'\n"),
        ("verifier_helper-1.0/verifier_helper/__init__.py", b"__version__ = '1.0'\n"),
    )
    with pytest.raises(RuntimeError, match="not statically bound"):
        extract_static_build_requirements(load_source(ambiguous_local_metadata), ambiguous_local_metadata)

    deterministic_alias = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[aliases]\ntest = pytest\n[egg_info]\ntag_build =\n"),
    )
    assert extract_static_build_requirements(load_source(deterministic_alias), deterministic_alias) == ()

    dynamic_config_file = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[metadata]\nlong_description = file: README.rst\n"),
    )
    with pytest.raises(RuntimeError, match="executable or dynamic option"):
        extract_static_build_requirements(load_source(dynamic_config_file), dynamic_config_file)

    dynamic_config_discovery = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
        ),
        ("verifier_helper-1.0/setup.cfg", b"[options]\npackages = find:\n"),
    )
    with pytest.raises(RuntimeError, match="executable or dynamic option"):
        extract_static_build_requirements(load_source(dynamic_config_discovery), dynamic_config_discovery)

    resource_context = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import tempfile\n"
            b"from setuptools import setup\n"
            b"with tempfile.TemporaryDirectory() as directory:\n"
            b"    setup(name='verifier-helper', version='1.0')\n",
        ),
    )
    with pytest.raises(RuntimeError, match="top-level setuptools setup"):
        extract_static_build_requirements(load_source(resource_context), resource_context)

    unsafe_source_paths = (
        b"import os\nfrom setuptools import setup\nsetup(name='verifier-helper', long_description=open(os.path.join(os.path.dirname(__file__), '..', 'passwd')).read())\n",
        b"import os\nfrom setuptools import setup\nsetup(name='verifier-helper', long_description=open(os.path.join(os.path.dirname(__file__), '/etc/passwd')).read())\n",
        b"import os\nfrom setuptools import setup\nMETADATA_PATH = 'README'\nsetup(name='verifier-helper', long_description=open(os.path.join(os.path.dirname(__file__), METADATA_PATH)).read())\n",
        b"import os\nfrom setuptools import setup\ndef read(path):\n    return open(os.path.join(os.path.dirname(__file__), path)).read()\nsetup(name='verifier-helper', long_description=read('/etc/passwd'))\n",
    )
    for setup_source in unsafe_source_paths:
        unsafe_path = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            ("verifier_helper-1.0/setup.py", setup_source),
        )
        with pytest.raises(RuntimeError, match="setup.py"):
            extract_static_build_requirements(load_source(unsafe_path), unsafe_path)

    rejected_executable_build_forms = (
        b"from setuptools import setup\nsetup(name='verifier-helper', cffi_modules=['build.py:ffi'])\n",
        b"from setuptools import Extension, setup\next = Extension('proof.extension', sources=['wrapper.c'])\nsetup(name='verifier-helper', ext_modules=[ext])\n",
        b"import tempfile\nimport urllib.request\nfrom setuptools import setup\nwith tempfile.TemporaryDirectory() as directory:\n    urllib.request.urlopen('https://files.example.invalid/resource.zip')\n    setup(name='verifier-helper')\n",
        b"import tempfile\nimport tarfile\nfrom setuptools import setup\nwith tempfile.TemporaryDirectory() as directory:\n    tarfile.open('payload.tar').extractall(directory)\n    setup(name='verifier-helper')\n",
        b"import tempfile\nimport zipfile\nfrom setuptools import setup\nwith tempfile.TemporaryDirectory() as directory:\n    zipfile.ZipFile('payload.zip').extractall(directory)\n    setup(name='verifier-helper')\n",
    )
    for setup_source in rejected_executable_build_forms:
        executable_build = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            ("verifier_helper-1.0/setup.py", setup_source),
        )
        with pytest.raises(RuntimeError, match="setup.py"):
            extract_static_build_requirements(load_source(executable_build), executable_build)

    safe_package_dir = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nsetup(name='verifier-helper', package_dir={'': 'src'})\n",
        ),
    )
    assert extract_static_build_requirements(load_source(safe_package_dir), safe_package_dir) == ()
    for package_dir in ("/tmp/escape", "../escape"):
        unsafe_package_dir = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            (
                "verifier_helper-1.0/setup.py",
                f"from setuptools import setup\nsetup(name='verifier-helper', package_dir={{'': {package_dir!r}}})\n".encode(),
            ),
        )
        with pytest.raises(RuntimeError, match="package_dir"):
            extract_static_build_requirements(load_source(unsafe_package_dir), unsafe_package_dir)
    dynamic_package_dir = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"from setuptools import setup\nSOURCE_ROOT = 'src'\nsetup(name='verifier-helper', package_dir={'': SOURCE_ROOT})\n",
        ),
    )
    with pytest.raises(RuntimeError, match="package_dir"):
        extract_static_build_requirements(load_source(dynamic_package_dir), dynamic_package_dir)

    unsafe_package_declarations = (
        b"from setuptools import setup\nsetup(name='verifier-helper', packages=['/etc'])\n",
        b"from setuptools import setup\nsetup(name='verifier-helper', packages=['../outside'])\n",
        b"from setuptools import setup\n"
        b"setup(name='verifier-helper', packages=['verifier_helper'], "
        b"package_data={'verifier_helper': ['../../outside/*']})\n",
        b"from setuptools import setup\n"
        b"setup(name='verifier-helper', packages=['verifier_helper'], include_package_data=True)\n",
        b"from setuptools import setup\nsetup(name='verifier-helper', use_scm_version=True)\n",
    )
    for setup_source in unsafe_package_declarations:
        unsafe_package_metadata = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            ("verifier_helper-1.0/setup.py", setup_source),
        )
        with pytest.raises(RuntimeError, match="setup.py"):
            extract_static_build_requirements(load_source(unsafe_package_metadata), unsafe_package_metadata)

    metadata_not_executed = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import pathlib\n"
            b"from setuptools import setup\n"
            b"setup(name='verifier-helper', long_description=pathlib.Path('missing').read_text())\n",
        ),
    )
    assert extract_static_build_requirements(load_source(metadata_not_executed), metadata_not_executed) == ()

    dead_publish_guard = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import os\n"
            b"import sys\n"
            b"from setuptools import setup\n"
            b"if sys.argv[-1] == 'publish':\n"
            b"    os.system('release-command')\n"
            b"    sys.exit()\n"
            b"setup(name='verifier-helper', version='1.0')\n",
        ),
    )
    assert extract_static_build_requirements(load_source(dead_publish_guard), dead_publish_guard) == ()

    reachable_command_guard = archive(
        ("verifier_helper-1.0/PKG-INFO", metadata),
        (
            "verifier_helper-1.0/setup.py",
            b"import os\n"
            b"import sys\n"
            b"from setuptools import setup\n"
            b"if sys.argv[-1] == 'bdist_wheel':\n"
            b"    os.system('build-command')\n"
            b"    sys.exit()\n"
            b"setup(name='verifier-helper', version='1.0')\n",
        ),
    )
    with pytest.raises(RuntimeError, match="control flow"):
        extract_static_build_requirements(load_source(reachable_command_guard), reachable_command_guard)

    for shadow_name in ("setuptools.py", "setuptools.pyc", "setuptools/__init__.py"):
        shadowed = archive(
            ("verifier_helper-1.0/PKG-INFO", metadata),
            (
                "verifier_helper-1.0/setup.py",
                b"from setuptools import setup\nsetup(name='verifier-helper', version='1.0')\n",
            ),
            (f"verifier_helper-1.0/{shadow_name}", b"raise RuntimeError('shadow loaded')\n"),
        )
        with pytest.raises(RuntimeError, match="shadows the attested setuptools"):
            extract_static_build_requirements(load_source(shadowed), shadowed)


def test_wheel_semantic_digest_normalizes_timestamps_and_rejects_unsafe_members() -> None:
    filename = "safe_project-1.0-py3-none-any.whl"
    metadata_dir = "safe_project-1.0.dist-info"
    base_members = (
        (
            f"{metadata_dir}/METADATA",
            b"Metadata-Version: 2.1\nName: safe-project\nVersion: 1.0\n",
        ),
        (
            f"{metadata_dir}/WHEEL",
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        ),
        ("safe_project.py", b"VALUE = 1\n"),
    )

    def wheel(
        timestamp: tuple[int, int, int, int, int, int],
        *,
        members: tuple[tuple[str, bytes], ...] = base_members,
        mode: int = 0o600,
        extra: bytes = b"",
        compression: int = ZIP_STORED,
        member_comment: bytes = b"",
        archive_comment: bytes = b"",
    ) -> bytes:
        output = io.BytesIO()
        with ZipFile(output, mode="w") as archive:
            for name, payload in members:
                info = ZipInfo(name, timestamp)
                info.external_attr = mode << 16
                info.extra = extra
                info.compress_type = compression
                info.comment = member_comment
                archive.writestr(info, payload)
            archive.comment = archive_comment
        return output.getvalue()

    def raw_layout(payload: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
        end_offset = payload.rfind(b"PK\x05\x06")
        end = struct.unpack_from("<4s4H2LH", payload, end_offset)
        count = end[4]
        central_offset = end[6]
        cursor = central_offset
        entries = []
        for _ in range(count):
            central = struct.unpack_from("<4s6H3L5H2L", payload, cursor)
            entries.append((cursor, central[16], central[10]))
            cursor += 46 + central[10] + central[11] + central[12]
        return end_offset, central_offset, entries

    first = wheel((2020, 1, 1, 0, 0, 0))
    delayed = wheel((2024, 4, 4, 4, 4, 4))
    assert first != delayed
    assert wheel_semantic_sha256(filename, first) == wheel_semantic_sha256(filename, delayed)
    _, _, first_entries = raw_layout(first)
    _, _, delayed_entries = raw_layout(delayed)
    first_central, first_local, _ = first_entries[0]
    delayed_central, delayed_local, _ = delayed_entries[0]
    local_timestamp_only = bytearray(first)
    local_timestamp_only[first_local + 10 : first_local + 14] = delayed[delayed_local + 10 : delayed_local + 14]
    assert wheel_semantic_sha256(filename, first) == wheel_semantic_sha256(filename, bytes(local_timestamp_only))
    central_timestamp_only = bytearray(first)
    central_timestamp_only[first_central + 12 : first_central + 16] = delayed[
        delayed_central + 12 : delayed_central + 16
    ]
    assert wheel_semantic_sha256(filename, first) == wheel_semantic_sha256(filename, bytes(central_timestamp_only))
    assert wheel_semantic_sha256(filename, first) != wheel_semantic_sha256(
        filename,
        wheel((2020, 1, 1, 0, 0, 0), compression=ZIP_DEFLATED),
    )
    assert wheel_semantic_sha256(filename, first) != wheel_semantic_sha256(
        filename,
        wheel((2020, 1, 1, 0, 0, 0), members=tuple(reversed(base_members))),
    )

    changed = wheel(
        (2024, 4, 4, 4, 4, 4),
        members=(*base_members[:-1], ("safe_project.py", b"VALUE = 2\n")),
    )
    assert wheel_semantic_sha256(filename, first) != wheel_semantic_sha256(filename, changed)
    assert wheel_semantic_sha256(filename, first) != wheel_semantic_sha256(
        filename, wheel((2020, 1, 1, 0, 0, 0), mode=0o644)
    )

    duplicate_members = (*base_members, ("safe_project.py", b"VALUE = 1\n"))
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = wheel((2020, 1, 1, 0, 0, 0), members=duplicate_members)
    with pytest.raises(RuntimeError, match="duplicate archive members"):
        inspect_wheel(filename, duplicate)

    signed = wheel(
        (2020, 1, 1, 0, 0, 0),
        members=(*base_members, (f"{metadata_dir}/RECORD.jws", b"signature")),
    )
    with pytest.raises(RuntimeError, match="forbidden RECORD signature"):
        inspect_wheel(filename, signed)

    non_regular = wheel((2020, 1, 1, 0, 0, 0), mode=stat.S_IFIFO | 0o600)
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        inspect_wheel(filename, non_regular)
    unreadable_regular = wheel((2020, 1, 1, 0, 0, 0), mode=stat.S_IFREG)
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        inspect_wheel(filename, unreadable_regular)
    world_writable = wheel((2020, 1, 1, 0, 0, 0), mode=stat.S_IFREG | 0o666)
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        inspect_wheel(filename, world_writable)

    with_extra = wheel((2020, 1, 1, 0, 0, 0), extra=b"UT\x01\x00\x00")
    with pytest.raises(RuntimeError, match="central directory entry"):
        inspect_wheel(filename, with_extra)

    member_commented = wheel((2020, 1, 1, 0, 0, 0), member_comment=b"comment")
    with pytest.raises(RuntimeError, match="central directory entry"):
        inspect_wheel(filename, member_commented)
    archive_commented = wheel((2020, 1, 1, 0, 0, 0), archive_comment=b"comment")
    with pytest.raises(RuntimeError, match="ZIP envelope"):
        inspect_wheel(filename, archive_commented)

    ambiguous_path = wheel(
        (2020, 1, 1, 0, 0, 0),
        members=(*base_members, ("package/./hidden.py", b"VALUE = 1\n")),
    )
    with pytest.raises(RuntimeError, match="ambiguous archive member path"):
        inspect_wheel(filename, ambiguous_path)

    local_extra = bytearray(first)
    end_offset, central_offset, entries = raw_layout(first)
    _, last_local_offset, last_name_size = max(entries, key=lambda item: item[1])
    inserted_extra = b"UT\x01\x00\x00"
    insert_at = last_local_offset + 30 + last_name_size
    struct.pack_into("<H", local_extra, last_local_offset + 28, len(inserted_extra))
    local_extra[insert_at:insert_at] = inserted_extra
    struct.pack_into("<L", local_extra, end_offset + len(inserted_extra) + 16, central_offset + len(inserted_extra))
    with pytest.raises(RuntimeError, match="local and central records"):
        inspect_wheel(filename, bytes(local_extra))

    raw_nul = bytearray(first)
    _, _, entries = raw_layout(first)
    central_member, local_member, _ = entries[-1]
    raw_nul[central_member + 46] = 0
    raw_nul[local_member + 30] = 0
    with pytest.raises(RuntimeError, match="unsafe raw archive member name"):
        inspect_wheel(filename, bytes(raw_nul))

    mismatched_name = bytearray(first)
    _, _, entries = raw_layout(first)
    _, local_member, _ = entries[-1]
    mismatched_name[local_member + 30] = ord("x")
    with pytest.raises(RuntimeError, match="local and central records"):
        inspect_wheel(filename, bytes(mismatched_name))

    unsupported_flags = bytearray(first)
    _, _, entries = raw_layout(first)
    central_member, local_member, _ = entries[-1]
    struct.pack_into("<H", unsupported_flags, central_member + 8, 1)
    struct.pack_into("<H", unsupported_flags, local_member + 6, 1)
    with pytest.raises(RuntimeError, match="unsupported ZIP member features"):
        inspect_wheel(filename, bytes(unsupported_flags))

    unterminated_deflate = bytearray(wheel((2020, 1, 1, 0, 0, 0), compression=ZIP_DEFLATED))
    _, _, entries = raw_layout(unterminated_deflate)
    _, local_member, name_size = entries[0]
    unterminated_deflate[local_member + 30 + name_size] &= 0xFE
    with pytest.raises(RuntimeError, match="deflated member payload"):
        inspect_wheel(filename, bytes(unterminated_deflate))

    orphan_gap = bytearray(first)
    end_offset, central_offset, _ = raw_layout(first)
    orphan_gap[central_offset:central_offset] = b"x"
    struct.pack_into("<L", orphan_gap, end_offset + 1 + 16, central_offset + 1)
    with pytest.raises(RuntimeError, match="exactly fill"):
        inspect_wheel(filename, bytes(orphan_gap))


def test_build_dependency_closure_is_exact_transitive_and_marker_conditioned() -> None:
    records = [*baseline_build_dependency_wheels()]
    backend_payload = wheel_file(
        "legacy_backend-1.0-py3-none-any.whl",
        "transitive-helper>=2",
        'inactive-helper>=1; sys_platform == "win32"',
    )
    transitive_payload = wheel_file("transitive_helper-2.1-py3-none-any.whl")
    records.extend(
        [
            (
                "legacy-backend",
                "1.0",
                "legacy_backend-1.0-py3-none-any.whl",
                "https://files.example.invalid/legacy_backend-1.0-py3-none-any.whl",
                backend_payload,
            ),
            (
                "transitive-helper",
                "2.1",
                "transitive_helper-2.1-py3-none-any.whl",
                "https://files.example.invalid/transitive_helper-2.1-py3-none-any.whl",
                transitive_payload,
            ),
        ]
    )
    policies = build_dependency_policies(tuple(records))
    payloads = {filename: payload for _, _, filename, _, payload in records}
    marker_environment = json.loads(synthetic_fingerprints("image").evidence)["marker_environment"]

    assert validate_build_dependency_payload_closure(
        ("legacy-backend>=1",),
        tuple(sorted(BUILD_TOOLS.items())),
        policies,
        payloads,
        marker_environment,
    ) == sha256_bytes(canonical_json(build_dependency_artifact_records(policies)))

    without_transitive = tuple(policy for policy in policies if policy.distribution != "transitive-helper")
    without_transitive_payload = {policy.filename: payloads[policy.filename] for policy in without_transitive}
    with pytest.raises(RuntimeError, match="does not satisfy"):
        validate_build_dependency_payload_closure(
            ("legacy-backend>=1",),
            tuple(sorted(BUILD_TOOLS.items())),
            without_transitive,
            without_transitive_payload,
            marker_environment,
        )

    extra_payload = wheel_file("unreachable_helper-1.0-py3-none-any.whl")
    extra_policy = build_dependency_policies(
        (
            (
                "unreachable-helper",
                "1.0",
                "unreachable_helper-1.0-py3-none-any.whl",
                "https://files.example.invalid/unreachable_helper-1.0-py3-none-any.whl",
                extra_payload,
            ),
        )
    )[0]
    with pytest.raises(RuntimeError, match="unreachable"):
        validate_build_dependency_payload_closure(
            ("legacy-backend>=1",),
            tuple(sorted(BUILD_TOOLS.items())),
            (*policies, extra_policy),
            {**payloads, extra_policy.filename: extra_payload},
            marker_environment,
        )


def test_source_build_environment_rejects_system_site_packages(tmp_path: Path) -> None:
    build_env = tmp_path / "ambient-build-env"
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "venv",
            "--without-pip",
            "--system-site-packages",
            str(build_env),
        ],
        check=True,
    )

    completed = subprocess.run(
        source_build_env_attest_argv(str(build_env), build_dependency_policies()),
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0


def test_oracle_source_wheel_build_is_attested_and_resume_revalidates_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, source_payload, built_wheel = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False, source_only=True)
    lifecycle: list[str] = []
    builder = SourceBuilderRuntime(source_payload, built_wheel, lifecycle=lifecycle)
    monkeypatch.setattr(taskset, "_new_source_builder", lambda *args: builder)

    taskset.begin_task_dependency_attestations(task)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    attestation_refs = taskset.finish_task_dependency_attestations(task)

    prefetched = taskset._prefetched_test_dependencies[runtime]
    assert prefetched.universal is False
    assert prefetched.source_attestation_sha256 in attestation_refs
    assert lifecycle == ["start", "stop"]
    source_build_command = next(argv for argv in builder.argvs if SOURCE_BUILD_RUNNER_CODE in argv)
    runner_index = source_build_command.index(SOURCE_BUILD_RUNNER_CODE)
    assert source_build_command[:2] == ["/usr/bin/env", "-i"]
    assert source_build_command[runner_index - 5 : runner_index] == [
        "/tmp/terminal-bench-source-build-env/bin/python",
        "-I",
        "-S",
        "-B",
        "-c",
    ]
    assert source_build_command[runner_index + 2] == "/tmp/terminal-bench-source-inputs/verifier_helper-1.0.tar.gz"
    assert source_build_command[runner_index + 6] == sha256_bytes(source_payload)
    assert builder.events.count("download") == 5
    assert builder.events.index("download") < builder.events.index("network-isolated")
    assert builder.events.index("network-isolated") < builder.events.index("source-build")
    manifest_path = tmp_path / "source_wheel_attestations.json"
    manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
    manifest = json.loads(manifest_path.read_text())
    assert manifest["policy_sha256"] == taskset.source_wheel_policy_sha256
    assert manifest["entries"][0]["build_contract"]["build_isolation"] is True
    assert manifest["entries"][0]["build_contract"]["isolated_python"] is True
    assert manifest["entries"][0]["build_contract"]["build_network"] == "no-network"
    assert manifest["entries"][0]["build_contract"]["child_process_path"] == "venv-bin-only"
    assert manifest["entries"][0]["sources"][0]["policy"]["sha256"] == sha256_bytes(source_payload)
    assert (
        manifest["entries"][0]["build_contract"]["build_dependency_install"]
        == "no-system-site-venv-offline-exact-wheel-closure"
    )
    assert (
        manifest["entries"][0]["build_contract"]["source_build_python"]
        == "venv-python-isolated-no-site-direct-static-setuptools"
    )
    assert (
        manifest["entries"][0]["build_contract"]["source_declarations"]
        == "static-setup-py-setup-cfg-pyproject-build-requirements"
    )
    assert manifest["entries"][0]["sources"][0]["build_environment"]["path"] == "/tmp/terminal-bench-source-build-env"
    assert manifest["entries"][0]["wheels"][0]["sha256"] == sha256_bytes(built_wheel)
    assert manifest_path.stat().st_mode & 0o777 == 0o400
    archive_path = prefetched.archive_path
    assert archive_path is not None and archive_path.exists()
    assert runtime.events.count("clean-target-closure-probe") == 1

    asyncio.run(taskset.close())
    assert archive_path.exists()
    resumed = source_dependency_taskset(
        tmp_path,
        [entry],
        expected_attestation_sha256=manifest_sha256,
    )
    resumed_runtime = DependencyRuntime(installed=False, source_only=True)
    asyncio.run(resumed._prefetch_test_dependencies(task, resumed_runtime))
    assert resumed_runtime.events == ["fingerprint"]
    assert resumed._prefetched_test_dependencies[resumed_runtime].archive_path == archive_path

    archive_path.chmod(0o600)
    archive_path.write_bytes(b"tampered")
    archive_path.chmod(0o400)
    with pytest.raises(RuntimeError, match="integrity validation"):
        source_dependency_taskset(
            tmp_path,
            [entry],
            expected_attestation_sha256=manifest_sha256,
        )


def test_oracle_source_wheel_build_installs_policy_build_dependencies_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dependency = wheel_file("legacy_backend-0.1-py3-none-any.whl")
    build_dependency_filename = "legacy_backend-0.1-py3-none-any.whl"
    entry, source_payload, built_wheel = source_policy_entry(
        setup_requires=("legacy-backend>=0.1",),
        build_dependency_wheels=(
            (
                "legacy-backend",
                "0.1",
                build_dependency_filename,
                f"https://files.example.invalid/{build_dependency_filename}",
                build_dependency,
            ),
        ),
    )
    taskset = source_dependency_taskset(tmp_path, [entry])
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False, source_only=True)
    builder = SourceBuilderRuntime(
        source_payload,
        built_wheel,
        build_dependency_payloads={build_dependency_filename: build_dependency},
    )
    monkeypatch.setattr(taskset, "_new_source_builder", lambda *args: builder)

    taskset.begin_task_dependency_attestations(task)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    taskset.finish_task_dependency_attestations(task)

    assert builder.events.count("download") == 6
    assert builder.events.index("network-isolated") < builder.events.index("build-dependency-install")
    assert builder.events.index("build-dependency-install") < builder.events.index("source-build")
    manifest = json.loads((tmp_path / "source_wheel_attestations.json").read_text())
    source_evidence = manifest["entries"][0]["sources"][0]
    assert build_dependency_filename in {item["filename"] for item in source_evidence["policy"]["build_dependencies"]}
    build_dependency_install = source_build_dependency_install_argv(
        build_env_dir="/tmp/terminal-bench-source-build-env",
        build_dependency_dir="/tmp/terminal-bench-source-build-deps",
        build_dependencies=taskset._source_wheel_policy.entries[0].sources[0].build_dependencies,
    )
    assert build_dependency_install in builder.argvs
    assert "--no-index" in build_dependency_install
    assert "--no-deps" in build_dependency_install
    assert f"/tmp/terminal-bench-source-build-deps/{build_dependency_filename}" in build_dependency_install


def test_oracle_source_wheel_build_rejects_post_build_environment_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, source_payload, built_wheel = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False, source_only=True)

    class MutatingBuildRuntime(SourceBuilderRuntime):
        attestations = 0

        async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
            result = await super().run(argv, env)
            if SOURCE_BUILD_ENV_ATTEST_CODE in argv:
                self.attestations += 1
                if self.attestations == 2:
                    attestation = json.loads(result.stdout)
                    attestation["sys_path_sha256"] = "4" * 64
                    return ProgramResult(
                        exit_code=0,
                        stdout=json.dumps(attestation, sort_keys=True),
                        stderr="",
                    )
            return result

    builder = MutatingBuildRuntime(source_payload, built_wheel)
    monkeypatch.setattr(taskset, "_new_source_builder", lambda *args: builder)

    taskset.begin_task_dependency_attestations(task)
    with pytest.raises(RuntimeError, match="changed its isolated dependency environment"):
        asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    assert builder.events.index("network-isolated") < builder.events.index("source-build")


def test_oracle_source_wheel_build_rejects_missing_policy_build_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, source_payload, built_wheel = source_policy_entry(setup_requires=("legacy-backend==0.1",))
    taskset = source_dependency_taskset(tmp_path, [entry])
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False, source_only=True)
    builder = SourceBuilderRuntime(source_payload, built_wheel)
    monkeypatch.setattr(taskset, "_new_source_builder", lambda *args: builder)

    taskset.begin_task_dependency_attestations(task)
    with pytest.raises(RuntimeError, match="not an exact transitive closure"):
        asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    assert "network-isolated" not in builder.events
    assert "source-build" not in builder.events


def test_source_wheel_resume_requires_externally_approved_attestation_sha256(tmp_path: Path) -> None:
    entry, _, built_wheel = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    fingerprints = synthetic_fingerprints(entry["image"])
    policy_entry = taskset._source_wheel_policy.entries[0]
    wheels = {policy_entry.sources[0].wheel_filename: built_wheel}
    evidence = validate_policy_wheel_closure(policy_entry, wheels)
    taskset._publish_source_wheel_attestation(
        policy_entry.requirements,
        fingerprints,
        policy_entry,
        pack_wheelhouse(wheels),
        evidence,
        (("verifier-helper", "1.0"),),
        (source_build_environment_fixture(),),
    )

    with pytest.raises(ValueError, match="requires the approved attestation SHA-256"):
        source_dependency_taskset(tmp_path, [entry])


def test_source_wheel_empty_attestation_requires_approval_on_resume(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    taskset.initialize_source_wheel_attestations(allow_create=True)
    manifest = tmp_path / "source_wheel_attestations.json"
    digest = sha256_bytes(manifest.read_bytes())

    assert json.loads(manifest.read_text())["entries"] == []
    assert manifest.stat().st_mode & 0o777 == 0o400
    with pytest.raises(ValueError, match="approved attestation SHA-256"):
        source_dependency_taskset(tmp_path, [entry])

    resumed = source_dependency_taskset(
        tmp_path,
        [entry],
        expected_attestation_sha256=digest,
    )
    resumed.initialize_source_wheel_attestations(allow_create=False)


@pytest.mark.parametrize("malformed", ["duplicate", "nonfinite"])
def test_source_wheel_resume_rejects_ambiguous_manifest_json(tmp_path: Path, malformed: str) -> None:
    entry, _, _ = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    taskset.initialize_source_wheel_attestations(allow_create=True)
    manifest = tmp_path / "source_wheel_attestations.json"
    value = manifest.read_text()
    manifest.chmod(0o600)
    if malformed == "duplicate":
        value = value.replace(
            f'"schema_version":{SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION}',
            f'"schema_version":{SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION},'
            f'"schema_version":{SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION}',
            1,
        )
    else:
        value = value.replace(
            f'"schema_version":{SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION}',
            '"schema_version":NaN',
            1,
        )
    manifest.write_text(value)
    manifest.chmod(0o400)

    with pytest.raises(ValueError, match="not valid JSON"):
        source_dependency_taskset(
            tmp_path,
            [entry],
            expected_attestation_sha256=sha256_bytes(manifest.read_bytes()),
        )


def test_source_wheel_loader_discards_only_safe_orphan_archives(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    cache = tmp_path / "source_wheel_cache"
    cache.mkdir(mode=0o700)
    orphan = cache / ("a" * 64 + ".tar")
    orphan.write_bytes(b"interrupted")
    orphan.chmod(0o400)

    source_dependency_taskset(tmp_path, [entry])

    assert list(cache.iterdir()) == []

    unsafe = cache / "unrelated"
    unsafe.write_bytes(b"preserve")
    unsafe.chmod(0o400)
    with pytest.raises(ValueError, match="unsafe unreferenced artifact"):
        source_dependency_taskset(tmp_path, [entry])
    assert unsafe.read_bytes() == b"preserve"


def test_source_wheel_policy_is_rejected_for_model_setup(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])

    with pytest.raises(RuntimeError, match="trusted oracle"):
        asyncio.run(taskset.setup(dependency_task(tmp_path), object()))


def test_source_wheel_builder_start_is_drained_before_teardown_on_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, _, _ = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry])
    task = dependency_task(tmp_path)
    started = asyncio.Event()
    release_start = asyncio.Event()
    lifecycle: list[str] = []

    class Builder:
        async def start(self) -> None:
            started.set()
            await release_start.wait()
            lifecycle.append("started")

        async def stop(self) -> None:
            lifecycle.append("stopped")

    monkeypatch.setattr(taskset, "_new_source_builder", lambda *args: Builder())

    async def exercise() -> None:
        operation = asyncio.create_task(
            taskset._build_source_dependency_wheelhouse(
                task,
                object(),
                ("verifier-helper==1.0",),
                synthetic_fingerprints(entry["image"]),
            )
        )
        await started.wait()
        operation.cancel()
        await asyncio.sleep(0)
        assert lifecycle == []
        release_start.set()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(exercise())
    assert lifecycle == ["started", "stopped"]
    assert not (tmp_path / "source_wheel_attestations.json").exists()


def test_source_wheel_fallback_rejects_compose_main_image_without_leasing_builder(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    taskset = source_dependency_taskset(tmp_path, [entry], enable_compose=True)
    task = dependency_task(tmp_path)
    (tmp_path / "environment" / "compose.yml").write_text("services:\n  main:\n    image: other:latest\n")
    runtime = object.__new__(VMVMRuntime)
    runtime.config = VMVMConfig(image=entry["image"])
    fingerprints = synthetic_fingerprints(entry["image"])

    with pytest.raises(RuntimeError, match="effective main image is unbound"):
        taskset._new_source_builder(task, runtime, fingerprints, "4" * 64)


def test_source_wheel_builder_lease_is_global_and_cancellation_cannot_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_a = "registry.invalid/task-a@sha256:" + "a" * 64
    image_b = "registry.invalid/task-b@sha256:" + "b" * 64
    entry_a, _, built_wheel = source_policy_entry(image=image_a)
    entry_b, _, _ = source_policy_entry(image=image_b)
    taskset = source_dependency_taskset(tmp_path, [entry_a, entry_b])
    task = dependency_task(tmp_path)
    active = 0
    maximum = 0
    build_started = asyncio.Event()
    release_build = asyncio.Event()

    class Builder:
        def __init__(self, fingerprints: RuntimeWheelFingerprints) -> None:
            self.fingerprints = fingerprints

        async def start(self) -> None:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)

        async def stop(self) -> None:
            nonlocal active
            active -= 1

    async def fingerprint(task: object, runtime: Builder) -> RuntimeWheelFingerprints:
        return runtime.fingerprints

    async def build(
        task: object,
        builder: Builder,
        policy_entry: object,
        fingerprints: RuntimeWheelFingerprints,
    ) -> tuple[dict[str, bytes], tuple[tuple[str, str], ...], tuple[dict[str, object], ...]]:
        build_started.set()
        await release_build.wait()
        return (
            {"verifier_helper-1.0-py3-none-any.whl": built_wheel},
            (("verifier-helper", "1.0"),),
            (source_build_environment_fixture(),),
        )

    monkeypatch.setattr(taskset, "_runtime_wheel_fingerprint", fingerprint)
    monkeypatch.setattr(taskset, "_new_source_builder", lambda task, runtime, fingerprints, key: Builder(fingerprints))
    monkeypatch.setattr(taskset, "_build_policy_wheels_in_builder", build)
    monkeypatch.setattr(
        taskset,
        "_validate_policy_wheels_on_target",
        lambda *args: asyncio.sleep(0, result=(("verifier-helper", "1.0"),)),
    )
    fingerprints_a = synthetic_fingerprints(image_a)
    fingerprints_b = synthetic_fingerprints(image_b)

    async def exercise() -> None:
        first = asyncio.create_task(
            taskset._build_source_dependency_wheelhouse(task, object(), ("verifier-helper==1.0",), fingerprints_a)
        )
        await build_started.wait()
        second = asyncio.create_task(
            taskset._build_source_dependency_wheelhouse(task, object(), ("verifier-helper==1.0",), fingerprints_b)
        )
        await asyncio.sleep(0)
        assert active == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not (tmp_path / "source_wheel_attestations.json").exists()
        release_build.set()
        await second

    asyncio.run(exercise())
    assert maximum == 1
    assert active == 0
    assert (tmp_path / "source_wheel_attestations.json").is_file()


@pytest.mark.parametrize("failure", [RuntimeError("prepare failed"), asyncio.CancelledError()])
def test_verifier_wheelhouse_preparation_always_attempts_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: BaseException,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime()
    fingerprints = asyncio.run(taskset._runtime_wheel_fingerprint(task, runtime))
    root_commands: list[str] = []

    async def run_root(runtime: object, command: str) -> ProgramResult:
        root_commands.append(command)
        if len(root_commands) == 1:
            raise failure
        return ProgramResult(exit_code=1, stdout="", stderr="cleanup failed")

    monkeypatch.setattr(taskset, "_run_root", run_root)
    with pytest.raises(type(failure)):
        asyncio.run(
            taskset._build_test_dependency_wheelhouse(
                task,
                runtime,
                ("verifier-helper==1.0",),
                fingerprints.resolution,
                fingerprints.compatibility,
            )
        )

    assert len(root_commands) == 2
    assert "rm -rf" in root_commands[1]
    assert "verifier wheelhouse cleanup failed: cleanup failed" in caplog.text


def test_successful_verifier_wheelhouse_build_rejects_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime()
    fingerprints = asyncio.run(taskset._runtime_wheel_fingerprint(task, runtime))
    run_root = taskset._run_root

    async def fail_cleanup(runtime: object, command: str) -> ProgramResult:
        if command.startswith("rm -rf /tmp/terminal-bench-verifier-wheels-") and " && " not in command:
            return ProgramResult(exit_code=1, stdout="", stderr="cleanup failed")
        return await run_root(runtime, command)

    monkeypatch.setattr(taskset, "_run_root", fail_cleanup)
    with pytest.raises(RuntimeError, match="verifier wheelhouse cleanup failed: cleanup failed"):
        asyncio.run(
            taskset._build_test_dependency_wheelhouse(
                task,
                runtime,
                ("verifier-helper==1.0",),
                fingerprints.resolution,
                fingerprints.compatibility,
            )
        )


def test_successful_verifier_wheelhouse_restore_rejects_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    run_root = taskset._run_root

    async def fail_cleanup(runtime: object, command: str) -> ProgramResult:
        if command.startswith("rm -rf /tmp/terminal-bench-verifier-wheels-") and " && " not in command:
            return ProgramResult(exit_code=1, stdout="", stderr="cleanup failed")
        return await run_root(runtime, command)

    monkeypatch.setattr(taskset, "_run_root", fail_cleanup)
    with pytest.raises(RuntimeError, match="restored verifier wheelhouse cleanup failed: cleanup failed"):
        asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))
    taskset._cleanup_wheelhouse_cache()


@pytest.mark.parametrize("failure", [RuntimeError("restore failed"), asyncio.CancelledError()])
def test_verifier_wheelhouse_restore_preserves_primary_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: BaseException,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    run_root = taskset._run_root

    async def fail_restore_and_cleanup(runtime: object, command: str) -> ProgramResult:
        if "tar -xf" in command:
            raise failure
        if command.startswith("rm -rf /tmp/terminal-bench-verifier-wheels-") and " && " not in command:
            return ProgramResult(exit_code=1, stdout="", stderr="cleanup failed")
        return await run_root(runtime, command)

    monkeypatch.setattr(taskset, "_run_root", fail_restore_and_cleanup)
    with pytest.raises(type(failure)):
        asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))

    assert "restored verifier wheelhouse cleanup failed: cleanup failed" in caplog.text
    taskset._cleanup_wheelhouse_cache()


def test_verifier_dependency_archive_tampering_is_fail_closed(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=False)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    prefetched = taskset._prefetched_test_dependencies[runtime]
    assert prefetched.archive_path is not None
    controller_archive = prefetched.archive_path
    controller_archive.chmod(0o600)
    controller_archive.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="integrity check"):
        asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))

    assert "overlay-install" not in runtime.events
    assert controller_archive.exists() is True
    taskset._cleanup_wheelhouse_cache()
    assert controller_archive.exists() is False


def test_verifier_dependency_universal_cache_is_single_flight_across_images(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtimes = [
        DependencyRuntime(image=f"registry.invalid/task-{index}@sha256:" + str(index) * 64) for index in range(3)
    ]

    async def prefetch() -> None:
        await asyncio.gather(
            taskset._prefetch_test_dependencies(task, runtimes[0]),
            taskset._prefetch_test_dependencies(task, runtimes[1]),
        )
        await taskset._prefetch_test_dependencies(task, runtimes[2])

    asyncio.run(prefetch())

    assert sum(runtime.events.count("wheel") for runtime in runtimes) == 1
    wheelhouses = [taskset._prefetched_test_dependencies[runtime] for runtime in runtimes]
    assert wheelhouses[0] is wheelhouses[1] is wheelhouses[2]
    assert wheelhouses[0].universal is True
    archive_path = wheelhouses[0].archive_path
    assert archive_path is not None and archive_path.exists()

    asyncio.run(taskset.cleanup(task, None, runtimes[0]))
    assert runtimes[0] not in taskset._prefetched_test_dependencies
    assert runtimes[0] not in taskset._runtime_wheel_fingerprints
    assert archive_path.exists()

    asyncio.run(taskset.close())
    assert archive_path.exists() is False
    assert taskset._universal_wheelhouse_cache == {}


def test_verifier_dependency_universal_cache_is_scoped_to_marker_environment(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtimes = [
        DependencyRuntime(
            image="registry.invalid/python-312@sha256:" + "a" * 64,
            python_version=(3, 12, 0),
            wheel_names=(
                "verifier_helper-1.0-py3-none-any.whl",
                "modern_dependency-1.0-py3-none-any.whl",
            ),
        ),
        DependencyRuntime(
            image="registry.invalid/python-311@sha256:" + "b" * 64,
            python_version=(3, 11, 9),
            wheel_names=(
                "verifier_helper-1.0-py3-none-any.whl",
                "legacy_dependency-1.0-py3-none-any.whl",
            ),
        ),
    ]

    async def prefetch() -> None:
        await asyncio.gather(*(taskset._prefetch_test_dependencies(task, runtime) for runtime in runtimes))

    asyncio.run(prefetch())

    assert sum(runtime.events.count("wheel") for runtime in runtimes) == 2
    wheelhouses = [taskset._prefetched_test_dependencies[runtime] for runtime in runtimes]
    assert wheelhouses[0] is not wheelhouses[1]
    assert all(wheelhouse.universal is True for wheelhouse in wheelhouses)
    assert wheelhouses[0].resolution_fingerprint != wheelhouses[1].resolution_fingerprint
    assert len(taskset._universal_wheelhouse_cache) == 2
    taskset._cleanup_wheelhouse_cache()


def test_verifier_dependency_platform_cache_is_scoped_to_runtime_fingerprint(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    image_a = "registry.invalid/task-a@sha256:" + "a" * 64
    runtimes = [
        DependencyRuntime(
            image=image_a if index < 2 else "registry.invalid/task-b@sha256:" + "b" * 64,
            wheel_names=("verifier_helper-1.0-cp312-cp312-linux_x86_64.whl",),
        )
        for index in range(3)
    ]

    async def prefetch() -> None:
        await asyncio.gather(*(taskset._prefetch_test_dependencies(task, runtime) for runtime in runtimes))

    asyncio.run(prefetch())

    assert sum(runtime.events.count("wheel") for runtime in runtimes) == 2
    wheelhouses = [taskset._prefetched_test_dependencies[runtime] for runtime in runtimes]
    assert wheelhouses[0] is wheelhouses[1]
    assert wheelhouses[0] is not wheelhouses[2]
    assert all(wheelhouse.universal is False for wheelhouse in wheelhouses)
    taskset._cleanup_wheelhouse_cache()


def test_verifier_dependency_cache_key_includes_exact_requirement_tuple(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    first_task = dependency_task(tmp_path / "first")
    second_task = dependency_task(tmp_path / "second")
    second_dockerfile = Path(second_task.task_dir) / "environment" / "Dockerfile"
    second_dockerfile.write_text(second_dockerfile.read_text().replace("verifier-helper==1.0", "other-helper==2.0"))
    runtimes = [DependencyRuntime(), DependencyRuntime()]

    async def prefetch() -> None:
        await taskset._prefetch_test_dependencies(first_task, runtimes[0])
        await taskset._prefetch_test_dependencies(second_task, runtimes[1])

    asyncio.run(prefetch())

    assert sum(runtime.events.count("wheel") for runtime in runtimes) == 2
    assert taskset._prefetched_test_dependencies[runtimes[0]].requirements == ("verifier-helper==1.0",)
    assert taskset._prefetched_test_dependencies[runtimes[1]].requirements == ("other-helper==2.0",)
    taskset._cleanup_wheelhouse_cache()


def test_cancelled_wheelhouse_owner_is_quiesced_and_waiter_retries(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    owner = DependencyRuntime()
    waiter = DependencyRuntime()

    async def exercise() -> None:
        wheel_started = asyncio.Event()
        never_finish = asyncio.Event()
        owner_run = owner.run

        async def blocked_run(argv: list[str], env: dict[str, str]) -> ProgramResult:
            if argv[:4] == ["python3", "-m", "pip", "wheel"]:
                owner.events.append("wheel")
                wheel_started.set()
                await never_finish.wait()
            return await owner_run(argv, env)

        owner.run = blocked_run
        owner_prefetch = asyncio.create_task(taskset._prefetch_test_dependencies(task, owner))
        await wheel_started.wait()
        waiter_prefetch = asyncio.create_task(taskset._prefetch_test_dependencies(task, waiter))
        await asyncio.sleep(0)

        owner_prefetch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner_prefetch
        await taskset.cleanup(task, None, owner)
        await waiter_prefetch

        assert waiter.events.count("wheel") == 1
        assert owner not in taskset._runtime_wheel_fingerprints
        assert owner not in taskset._prefetched_test_dependencies
        assert waiter in taskset._prefetched_test_dependencies
        assert taskset._wheelhouse_discovery_flights == {}
        assert taskset._wheelhouse_flight_runtimes == {}
        await taskset.close()

    asyncio.run(exercise())


def test_taskset_close_cancels_inflight_wheelhouse_builder(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime()

    async def exercise() -> None:
        wheel_started = asyncio.Event()
        never_finish = asyncio.Event()
        runtime_run = runtime.run

        async def blocked_run(argv: list[str], env: dict[str, str]) -> ProgramResult:
            if argv[:4] == ["python3", "-m", "pip", "wheel"]:
                runtime.events.append("wheel")
                wheel_started.set()
                await never_finish.wait()
            return await runtime_run(argv, env)

        runtime.run = blocked_run
        prefetch = asyncio.create_task(taskset._prefetch_test_dependencies(task, runtime))
        await wheel_started.wait()
        await taskset.close()
        (outcome,) = await asyncio.gather(prefetch, return_exceptions=True)

        assert isinstance(outcome, RuntimeError)
        assert "cache is closed" in str(outcome)
        assert taskset._wheelhouse_discovery_flights == {}
        assert taskset._wheelhouse_compatibility_flights == {}
        assert taskset._wheelhouse_flight_runtimes == {}
        assert taskset._wheelhouse_cache_directory is None

    asyncio.run(exercise())


def test_taskset_cleanup_drops_unscored_artifacts(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime()
    trace = SimpleNamespace(id="unfinished-trace")
    taskset._artifact_payloads[trace.id] = {"main": b"artifact"}

    asyncio.run(taskset.cleanup(task, trace, runtime))

    assert trace.id not in taskset._artifact_payloads


def test_public_agent_offline_verifier_stages_tests_only_after_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    task.resources = SimpleNamespace(gpu=None)
    task.workdir = "/app"
    task.verifier_workdir = "/app"
    task.verifier_mode = "shared"
    task.agent_network_mode = "public"
    task.verifier_network_mode = "no-network"
    task.verifier_timeout_sec = 30.0
    task.verifier_env = {}
    runtime = DependencyRuntime(installed=True)

    async def configure_network_policy(
        task_arg: SimpleNamespace,
        runtime_arg: DependencyRuntime,
        mode: str,
        *,
        activate: bool,
    ) -> None:
        assert task_arg is task
        assert runtime_arg is runtime
        runtime.events.append(f"network:{mode}:{'active' if activate else 'prepared'}")

    async def stage_tests(
        runtime_arg: DependencyRuntime,
        source: Path,
        target: str,
        label: str,
    ) -> None:
        assert runtime_arg is runtime
        assert source == Path(task.task_dir) / "tests"
        assert (target, label) == ("/tests", "tests")
        runtime.events.append("stage-tests")

    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network_policy)
    monkeypatch.setattr(taskset, "_stage_directory", stage_tests)

    async def run_phases() -> float:
        await taskset.setup(task, runtime)
        runtime.events.append("agent")
        runtime.installed = False
        _, _, score, _ = await taskset._run_verifier(task, runtime, stage_tests=True)
        await taskset.cleanup(task, None, runtime)
        await taskset.close()
        return score

    score = asyncio.run(run_phases())

    assert score == 1.0
    assert runtime.events.count("wheel") == 1
    assert runtime.events.index("wheel") < runtime.events.index("agent")
    assert runtime.events.index("agent") < runtime.events.index("network:no-network:active")
    assert runtime.events.index("network:no-network:active") < runtime.events.index("stage-tests")
    assert runtime.events.index("stage-tests") < runtime.events.index("overlay-install")
    assert runtime.events.index("overlay-install") < runtime.events.index("verifier")
    assert runtime.events.index("verifier") < runtime.events.index("overlay-cleanup")
    verifier_command = next(command for command in runtime.commands if "timeout --signal=TERM" in command)
    assert "terminal-bench-verifier-bootstrap-" in verifier_command
    assert "terminal-bench-verifier-site-" in verifier_command
    assert "PYTHONPATH=" in verifier_command
    assert "PATH=" in verifier_command
    assert runtime.overlay_installed is False


@pytest.mark.parametrize("failure_phase", ["configuration", "verifier"])
def test_verifier_dependency_overlay_cleans_after_pre_run_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    task.verifier_workdir = "/app"
    task.verifier_network_mode = "no-network"
    if failure_phase == "configuration":

        class BrokenTimeout:
            def __format__(self, format_spec: str) -> str:
                raise RuntimeError("verifier configuration failed")

        task.verifier_timeout_sec = BrokenTimeout()
    else:
        task.verifier_timeout_sec = 30.0
    task.verifier_env = {}
    runtime = DependencyRuntime(installed=False)

    async def configure_network_policy(*args: object, **kwargs: object) -> None:
        return None

    async def stage_tests(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(taskset, "_configure_network_policy", configure_network_policy)
    monkeypatch.setattr(taskset, "_stage_directory", stage_tests)

    async def exercise() -> None:
        await taskset._prefetch_test_dependencies(task, runtime)
        original_run = runtime.run

        async def fail_verifier(argv: list[str], env: dict[str, str]) -> ProgramResult:
            if argv[:2] == ["sh", "-c"] and "timeout --signal=TERM" in argv[2]:
                runtime.events.append("verifier")
                raise RuntimeError("verifier transport failed")
            return await original_run(argv, env)

        if failure_phase == "verifier":
            runtime.run = fail_verifier
        with pytest.raises(RuntimeError, match="verifier (?:configuration|transport) failed"):
            await taskset._run_verifier(task, runtime, stage_tests=True)
        await taskset.close()

    asyncio.run(exercise())

    assert runtime.events.index("overlay-install") < runtime.events.index("overlay-cleanup")
    if failure_phase == "verifier":
        assert runtime.events.index("overlay-install") < runtime.events.index("verifier")
        assert runtime.events.index("verifier") < runtime.events.index("overlay-cleanup")
    else:
        assert "verifier" not in runtime.events
    assert runtime.overlay_installed is False


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("json", b'{"reward": NaN}'),
        ("json", b'{"reward": Infinity}'),
        ("text", b"-Infinity\n"),
    ],
)
def test_parse_verifier_reward_rejects_non_finite_values(kind: str, payload: bytes) -> None:
    with pytest.raises(ValueError, match="reward value for 'reward' must be finite"):
        _parse_verifier_reward("task-a", kind, payload)


@pytest.mark.parametrize(
    ("raw", "verifier_mode", "expected"),
    [
        ({}, "shared", ("public", "public")),
        (
            {
                "environment": {"network_mode": "no-network"},
                "agent": {},
                "verifier": {},
            },
            "shared",
            ("no-network", "no-network"),
        ),
        (
            {
                "environment": {"network_mode": "public"},
                "agent": {"network_mode": "public"},
                "verifier": {"network_mode": "no-network"},
            },
            "shared",
            ("public", "no-network"),
        ),
        (
            {
                "environment": {"network_mode": "no-network"},
                "verifier": {
                    "environment_mode": "separate",
                    "environment": {"network_mode": "public"},
                },
            },
            "separate",
            ("no-network", "public"),
        ),
        (
            {"environment": {"allow_internet": False}},
            "shared",
            ("no-network", "no-network"),
        ),
        (
            {
                "environment": {
                    "network_mode": "public",
                    "allow_internet": False,
                }
            },
            "shared",
            ("public", "public"),
        ),
    ],
)
def test_network_modes_resolve_harbor_baselines_and_phase_overrides(
    raw: dict,
    verifier_mode: str,
    expected: tuple[str, str],
) -> None:
    assert _network_modes("task-a", raw, verifier_mode) == expected


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (
            {"environment": {"network_mode": "allowlist", "allowed_hosts": ["example.com"]}},
            "allowlist.*not supported",
        ),
        (
            {"agent": {"network_mode": "private"}},
            "unknown agent network_mode",
        ),
        (
            {
                "environment": {"network_mode": "no-network"},
                "agent": {"network_mode": "public"},
            },
            "cannot relax.*agent phase",
        ),
        (
            {
                "environment": {"network_mode": "public"},
                "agent": {"network_mode": "no-network"},
                "verifier": {"network_mode": "public"},
            },
            "cannot restore public networking",
        ),
    ],
)
def test_network_modes_fail_closed_for_unsupported_policies(
    raw: dict,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _network_modes("task-a", raw, "shared")


def test_dockerfile_startup_command_combines_exec_forms(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    dockerfile = environment / "Dockerfile"
    dockerfile.write_text('FROM ubuntu\nENTRYPOINT ["/entrypoint.sh"]\nCMD ["sleep", "infinity"]\n')
    assert _dockerfile_startup_command(str(tmp_path)) == (
        "/entrypoint.sh",
        "sleep",
        "infinity",
    )

    other = tmp_path / "other" / "environment"
    other.mkdir(parents=True)
    (other / "Dockerfile").write_text("FROM ubuntu\nCMD run-server --port 80\n")
    assert _dockerfile_startup_command(str(other.parent)) == (
        "/bin/sh",
        "-c",
        "run-server --port 80",
    )


def test_repository_mobius_archive_indexes_all_tasks() -> None:
    repository = Path(__file__).resolve().parents[4]
    with ZipFile(repository / "tb_tasks.zip") as archive:
        task_slugs = {
            parts[1]
            for name in archive.namelist()
            if len(parts := name.split("/")) == 3 and parts[0] == "tb_tasks" and parts[2] == "task.toml"
        }
    assert len(task_slugs) == 2538


def test_task_file_selects_exact_tasks(tmp_path: Path) -> None:
    for slug in ("aig-coq-verification", "maxsat-vertex-cover"):
        task_dir = tmp_path / slug
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("")
        (task_dir / "instruction.md").write_text(f"Complete {slug}.\n")
    task_file = tmp_path / "oracle-valid.txt"
    task_file.write_text("aig-coq-verification\t1.0\nmaxsat-vertex-cover\n")
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            task_file=task_file,
            image_prefix="registry.invalid/terminal_bench",
            image_tag="test-revision",
            ignore_dockerfile=True,
        )
    )
    assert [task.slug for task in taskset.load_tasks()] == [
        "aig-coq-verification",
        "maxsat-vertex-cover",
    ]


def test_vmvm_root_exec_classifies_ssh_exit_255_as_transport_failure() -> None:
    backend = object.__new__(VacliVMVMBackend)
    backend._destroyed = False
    backend._container_id = "a" * 12
    backend._ssh_call_raw = lambda command, *, timeout: subprocess.CompletedProcess(
        args=[],
        returncode=255,
        stdout=b"Connection to localhost closed by remote host.\n",
    )

    result = backend.run_root_bash("true")

    assert result == {
        "status": "error",
        "output": "Connection to localhost closed by remote host.\n",
        "error_type": "broken_pipe",
        "exit_code": -1,
    }


def test_vmvm_host_tunnel_setup_uses_and_releases_shared_vacli_slot(monkeypatch) -> None:
    class RecordingTelemetry:
        def __init__(self) -> None:
            self.enters = 0
            self.finishes = 0

        def lease_start_entered(self) -> None:
            self.enters += 1

        def lease_start_finished(self) -> None:
            self.finishes += 1

    telemetry = RecordingTelemetry()
    limiter = LeaseStartConcurrencyLimiter(1, telemetry)
    monkeypatch.setattr(vacli_backend, "_lease_concurrency", limiter)
    backend = object.__new__(VacliVMVMBackend)
    backend._destroyed = False
    backend._container_id = "a" * 12
    tunnel = VacliHostTunnel("10.89.0.1", 42000, 1234, 99)
    probes: list[tuple[threading.Thread, threading.Event]] = []

    def assert_shared_slot_is_held() -> None:
        started = threading.Event()
        acquired = threading.Event()

        def acquire_measured() -> None:
            started.set()
            limiter.acquire()
            acquired.set()
            limiter.release()

        probe = threading.Thread(target=acquire_measured)
        probe.start()
        assert started.wait(timeout=2)
        assert not acquired.wait(timeout=0.05)
        assert (telemetry.enters, telemetry.finishes) == (len(probes), len(probes))
        probes.append((probe, acquired))

    def await_probe() -> None:
        probe, acquired = probes[-1]
        assert acquired.wait(timeout=2)
        probe.join(timeout=2)
        assert not probe.is_alive()

    def succeed(local_port: int) -> tuple[VacliHostTunnel, str]:
        assert_shared_slot_is_held()
        return tunnel, f"http://10.89.0.1:{local_port}"

    backend._open_host_tunnel = succeed
    assert backend.open_host_tunnel(1234) == (tunnel, "http://10.89.0.1:1234")
    await_probe()
    assert (telemetry.enters, telemetry.finishes) == (1, 1)

    def fail(local_port: int) -> tuple[VacliHostTunnel, str]:
        assert_shared_slot_is_held()
        raise BackendInitError(f"failed to expose {local_port}")

    backend._open_host_tunnel = fail
    with pytest.raises(BackendInitError, match="failed to expose"):
        backend.open_host_tunnel(1234)
    await_probe()
    assert (telemetry.enters, telemetry.finishes) == (2, 2)

    backend._open_host_tunnel = succeed
    assert backend.open_host_tunnel(1234)[0] is tunnel
    await_probe()
    assert (telemetry.enters, telemetry.finishes) == (3, 3)


def test_vmvm_sidecar_exec_classifies_ssh_exit_255_as_transport_failure() -> None:
    backend = object.__new__(VacliVMVMBackend)
    backend._compose_command = lambda args, *, timeout: subprocess.CompletedProcess(
        args=[],
        returncode=255,
        stdout=b"ssh: connect to host localhost: Connection refused\n",
    )

    result = backend.run_service_bash("database", "true")

    assert result == {
        "status": "error",
        "output": "ssh: connect to host localhost: Connection refused\n",
        "error_type": "broken_pipe",
        "exit_code": -1,
    }


def test_vmvm_bridge_gateway_uses_container_network_namespace() -> None:
    calls: list[list[str]] = []
    responses = iter(
        [
            subprocess.CompletedProcess(args=[], returncode=0, stdout=b"default via 10.89.3.1 dev eth0\n"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=b""),
        ]
    )

    class FakeSubprocess:
        DEVNULL = subprocess.DEVNULL
        PIPE = subprocess.PIPE

        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            return next(responses)

    gateway = _setup_bridge_proxy(FakeSubprocess, 2222, None, "a" * 64, ("api",))

    assert gateway == "10.89.3.1"
    assert "podman inspect" in calls[0][-1]
    assert "nsenter" in calls[0][-1]
    assert "10.89.3.1" in calls[1][-1]
    assert "api" in calls[1][-1]


def test_vmvm_compose_gateway_detection_fails_closed() -> None:
    responses = iter(
        [
            subprocess.CompletedProcess(args=[], returncode=1, stdout=b""),
            subprocess.CompletedProcess(args=[], returncode=127, stdout=b""),
        ]
    )

    class FakeSubprocess:
        DEVNULL = subprocess.DEVNULL
        PIPE = subprocess.PIPE

        @staticmethod
        def run(argv, **kwargs):
            return next(responses)

    with pytest.raises(BackendInitError, match="Compose container bridge gateway"):
        _setup_bridge_proxy(
            FakeSubprocess,
            2222,
            None,
            "a" * 64,
            ("api",),
            require_detected=True,
        )


def test_vmvm_network_isolation_preserves_internal_network_and_is_idempotent() -> None:
    backend = object.__new__(VacliVMVMBackend)
    isolation = _VacliNetworkIsolation(
        network="vf-internal-test",
        gateway="10.89.0.1",
        subnet="10.89.0.0/24",
        main_address="10.89.0.2",
        firewall_chain="VFNI_TEST",
        containers=("a" * 12,),
    )
    backend._network_isolation = isolation
    backend._host_tunnels = {VacliHostTunnel("10.89.0.1", 41000, 1234, 99)}
    calls: list[str] = []
    network_states = iter(
        [
            {"podman": {}, "vf-internal-test": {}},
            {"vf-internal-test": {}},
        ]
    )
    backend._container_networks = lambda container_id: next(network_states)

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"")

    backend._ssh_call_raw = ssh

    backend.activate_network_isolation()
    call_count = len(calls)
    backend.activate_network_isolation()

    assert isolation.active is True
    assert isolation.allowed_tunnel_ports == {41000}
    assert len(calls) == call_count
    assert "--dport 53" in calls[0]
    assert "-s 10.89.0.2/32 -p tcp --dport 41000" in calls[0]
    assert "-A VFNI_TEST -j REJECT" in calls[0]
    assert any("network disconnect --force podman" in command for command in calls)
    assert not any("network disconnect --force vf-internal-test" in command for command in calls)


def test_vmvm_network_isolation_tunnel_rules_add_remove_and_cleanup() -> None:
    backend = object.__new__(VacliVMVMBackend)
    isolation = _VacliNetworkIsolation(
        network="vf-internal-test",
        gateway="10.89.0.1",
        subnet="10.89.0.0/24",
        main_address="10.89.0.2",
        firewall_chain="VFNI_TEST",
        containers=("a" * 12,),
        active=True,
        firewall_active=True,
    )
    backend._network_isolation = isolation
    calls: list[str] = []

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"")

    backend._ssh_call_raw = ssh

    backend._allow_isolated_tunnel(42000)
    backend._allow_isolated_tunnel(42000)
    backend._remove_isolated_tunnel(42000)
    backend._remove_isolated_tunnel(42000)
    backend._cleanup_network_firewall()
    backend._cleanup_network_firewall()

    assert len(calls) == 3
    assert "-I VFNI_TEST 1 -s 10.89.0.2/32" in calls[0]
    assert "--dport 42000 -j ACCEPT" in calls[0]
    assert "-D VFNI_TEST -s 10.89.0.2/32" in calls[1]
    assert "-C INPUT -s 10.89.0.0/24 -d 10.89.0.1 -j VFNI_TEST" in calls[2]
    assert "-F VFNI_TEST" in calls[2]
    assert "-X VFNI_TEST" in calls[2]
    assert isolation.firewall_active is False
    assert isolation.allowed_tunnel_ports == set()


def test_vmvm_network_targets_include_each_compose_service() -> None:
    backend = object.__new__(VacliVMVMBackend)
    backend._container_id = "a" * 12
    backend._compose_project = "vf-test"
    backend._compose_services = ("main", "database")
    containers = {"main": "a" * 12, "database": "b" * 12}
    backend._compose_container = lambda service: containers[service]

    assert backend._network_targets() == (
        ("main", "a" * 12),
        ("database", "b" * 12),
    )


def test_vmvm_network_prepare_preserves_declared_compose_aliases(monkeypatch) -> None:
    backend = object.__new__(VacliVMVMBackend)
    backend._destroyed = False
    backend._network_isolation = None
    backend._container_id = "a" * 12
    backend._network_targets = lambda: (("main", "a" * 12),)
    calls: list[str] = []
    inspect_calls = 0

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        nonlocal inspect_calls
        calls.append(command)
        if command.startswith("podman network inspect"):
            metadata = [
                {
                    "internal": True,
                    "ipv6_enabled": False,
                    "subnets": [{"subnet": "10.89.0.0/24", "gateway": "10.89.0.1"}],
                }
            ]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(metadata).encode())
        if command.startswith("podman inspect"):
            inspect_calls += 1
            networks = (
                {"old": {"Aliases": ["main", "declared-alias"]}}
                if inspect_calls == 1
                else {"vf-internal-test": {"IPAddress": "10.89.0.2"}}
            )
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(networks).encode())
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"")

    backend._ssh_call_raw = ssh

    monkeypatch.setattr(
        vacli_backend.uuid,
        "uuid4",
        lambda: type("UUID", (), {"hex": "test"})(),
    )
    backend.prepare_network_isolation()

    connect = next(command for command in calls if "network connect" in command)
    assert "--alias declared-alias" in connect
    assert "--alias main" in connect


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "internal": True,
            "ipv6_enabled": True,
            "subnets": [{"subnet": "10.89.0.0/24", "gateway": "10.89.0.1"}],
        },
        {
            "internal": True,
            "ipv6_enabled": False,
            "subnets": [
                {"subnet": "10.89.0.0/24", "gateway": "10.89.0.1"},
                {"subnet": "fd00::/64", "gateway": "fd00::1"},
            ],
        },
    ],
)
def test_vmvm_network_prepare_rejects_additional_address_families(
    metadata: dict,
) -> None:
    backend = object.__new__(VacliVMVMBackend)
    backend._destroyed = False
    backend._network_isolation = None
    calls: list[str] = []

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        calls.append(command)
        output = json.dumps([metadata]).encode() if "network inspect" in command else b""
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=output)

    backend._ssh_call_raw = ssh

    with pytest.raises(BackendInitError, match="IPv6|malformed"):
        backend.prepare_network_isolation()

    assert any("network rm -f" in command for command in calls)


def test_vmvm_network_activation_failure_pauses_and_rolls_back_firewall() -> None:
    backend = object.__new__(VacliVMVMBackend)
    isolation = _VacliNetworkIsolation(
        network="vf-internal-test",
        gateway="10.89.0.1",
        subnet="10.89.0.0/24",
        main_address="10.89.0.2",
        firewall_chain="VFNI_TEST",
        containers=("a" * 12, "b" * 12),
    )
    backend._network_isolation = isolation
    backend._host_tunnels = set()
    calls: list[str] = []
    states = {
        "a" * 12: iter(
            [
                {"podman": {}, "vf-internal-test": {}},
                {"vf-internal-test": {}},
            ]
        ),
        "b" * 12: iter([{"podman": {}, "vf-internal-test": {}}]),
    }
    backend._container_networks = lambda container_id: next(states[container_id])

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        calls.append(command)
        if "network disconnect --force podman" in command and "b" * 12 in command:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"disconnect failed")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"")

    backend._ssh_call_raw = ssh

    with pytest.raises(BackendInitError, match="disconnecting public network"):
        backend.activate_network_isolation()

    assert isolation.active is False
    assert isolation.firewall_active is False
    assert any(command.startswith("podman pause") for command in calls)
    assert any("-C INPUT" in command and "-X VFNI_TEST" in command for command in calls)


def test_vmvm_partial_firewall_install_is_rolled_back() -> None:
    backend = object.__new__(VacliVMVMBackend)
    isolation = _VacliNetworkIsolation(
        network="vf-internal-test",
        gateway="10.89.0.1",
        subnet="10.89.0.0/24",
        main_address="10.89.0.2",
        firewall_chain="VFNI_TEST",
        containers=("a" * 12,),
    )
    backend._network_isolation = isolation
    backend._host_tunnels = set()
    calls: list[str] = []

    def ssh(command: str, *, timeout: int) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(
            args=[],
            returncode=1 if command.startswith("set -e") else 0,
            stdout=b"firewall failed",
        )

    backend._ssh_call_raw = ssh

    with pytest.raises(BackendInitError, match="firewall failed"):
        backend.activate_network_isolation()

    assert isolation.firewall_active is False
    assert any("-C INPUT" in command and "-X VFNI_TEST" in command for command in calls)


def test_dataset_revision_requires_exact_clean_worktree(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-a"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("")
    (task_dir / "instruction.md").write_text("Complete task-a.\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "dataset"], check=True)
    revision = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def taskset(expected: str) -> TerminalBenchVMVMTaskset:
        return TerminalBenchVMVMTaskset(
            TerminalBenchVMVMConfig(
                id="terminal-bench-vmvm",
                dataset_dir=tmp_path,
                dataset_revision=expected,
                image_prefix="registry.invalid/terminal_bench",
                image_tag="test-revision",
                ignore_dockerfile=True,
            )
        )

    assert [task.slug for task in taskset(revision).load_tasks()] == ["task-a"]
    with pytest.raises(ValueError, match="dataset revision mismatch"):
        taskset("0" * 40).load_tasks()

    (task_dir / "instruction.md").write_text("Changed.\n")
    with pytest.raises(ValueError, match="dataset worktree is not clean"):
        taskset(revision).load_tasks()


def test_task_and_image_manifest_sha256_are_enforced(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-a"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("")
    (task_dir / "instruction.md").write_text("Complete task-a.\n")
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("task-a\n")
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text(
        json.dumps(
            {
                "images": {
                    "task-a": {
                        "agent": "registry.invalid/task-a@sha256:" + "a" * 64,
                    }
                }
            }
        )
        + "\n"
    )

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def taskset() -> TerminalBenchVMVMTaskset:
        return TerminalBenchVMVMTaskset(
            TerminalBenchVMVMConfig(
                id="terminal-bench-vmvm",
                dataset_dir=tmp_path,
                task_file=task_file,
                task_file_sha256=sha256(task_file),
                image_manifest=image_manifest,
                image_manifest_sha256=sha256(image_manifest),
                image_prefix="registry.invalid/terminal_bench",
                image_tag="test-revision",
                ignore_dockerfile=True,
            )
        )

    assert [task.slug for task in taskset().load_tasks()] == ["task-a"]

    expected_task_hash = sha256(task_file)
    task_file.write_text("task-a\ntask-b\n")
    mismatched_task_file = taskset()
    mismatched_task_file.config.task_file_sha256 = expected_task_hash
    with pytest.raises(ValueError, match="task_file SHA-256 mismatch"):
        mismatched_task_file.load_tasks()

    task_file.write_text("task-a\n")
    expected_image_hash = sha256(image_manifest)
    image_manifest.write_text('{"images": {}}\n')
    mismatched_image_manifest = taskset()
    mismatched_image_manifest.config.image_manifest_sha256 = expected_image_hash
    with pytest.raises(ValueError, match="image_manifest SHA-256 mismatch"):
        mismatched_image_manifest.load_tasks()
