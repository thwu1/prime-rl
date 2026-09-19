import asyncio
import gc
import hashlib
import io
import json
import os
import subprocess
import sys
import sysconfig
import tarfile
from pathlib import Path
from types import SimpleNamespace
from weakref import ref
from zipfile import ZipFile

import pytest
import terminal_bench_vmvm.taskset as taskset_module
from terminal_bench_vmvm.source_wheels import (
    canonical_json,
    inspect_source_distribution,
    load_source_wheel_policy,
    pack_wheelhouse,
    sha256_bytes,
    validate_policy_wheel_closure,
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
from verifiers.v1.runtimes import ProgramResult, VMVMConfig, VMVMRuntime
from vmvm_tb_v2._vacli import backend as vacli_backend
from vmvm_tb_v2._vacli.backend import (
    VacliHostTunnel,
    VacliVMVMBackend,
    _setup_bridge_proxy,
    _VacliNetworkIsolation,
)
from vmvm_tb_v2._vacli.types import BackendInitError


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


def wheel_file(filename: str) -> bytes:
    distribution, version, *_ = filename.removesuffix(".whl").split("-")
    tag = "-".join(filename.removesuffix(".whl").split("-")[-3:])
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{distribution}-{version}.dist-info"
        wheel.writestr(
            f"{metadata_dir}/METADATA",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n",
        )
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n",
        )
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


class SourceBuilderRuntime(DependencyRuntime):
    def __init__(
        self,
        source_payload: bytes,
        built_wheel: bytes,
        *,
        image: str = "registry.invalid/task@sha256:" + "a" * 64,
        lifecycle: list[str] | None = None,
    ) -> None:
        super().__init__(image=image)
        self.source_payload = source_payload
        self.built_wheel = built_wheel
        self.files: dict[str, bytes] = {}
        self.lifecycle = lifecycle if lifecycle is not None else []

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
            self.files[destination] = self.source_payload
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:5] == ["python3", "-I", "-m", "pip", "wheel"] and "--no-build-isolation" in argv:
            self.argvs.append(list(argv))
            self.events.append("source-build")
            wheel_dir = argv[argv.index("--wheel-dir") + 1]
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
) -> tuple[dict[str, object], bytes, bytes]:
    source_output = io.BytesIO()
    source_metadata = b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 1.0\n"
    with tarfile.open(fileobj=source_output, mode="w:gz") as archive:
        member = tarfile.TarInfo("verifier_helper-1.0/PKG-INFO")
        member.size = len(source_metadata)
        archive.addfile(member, io.BytesIO(source_metadata))
    source = source_output.getvalue()
    wheel = wheel_file("verifier_helper-1.0-py3-none-any.whl")
    entry = {
        "requirements": [requirement],
        "image": image,
        "build_tools": {
            "pip": "24.3.1",
            "setuptools": "75.6.0",
            "wheel": "0.45.1",
        },
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
        "schema_version": 1,
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
        "schema_version": 1,
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


def test_source_wheel_policy_rejects_duplicate_json_keys_and_nonfinite_values(tmp_path: Path) -> None:
    entry, _, _ = source_policy_entry()
    policy = {
        "schema_version": 1,
        "allowed_hosts": ["files.example.invalid"],
        "entries": [entry],
    }
    canonical = json.dumps(policy, sort_keys=True)
    for payload in (
        canonical.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
        canonical.replace('"size": ', '"size": NaN, "ignored_size": ', 1),
    ):
        path = tmp_path / f"policy-{hashlib.sha256(payload.encode()).hexdigest()}.json"
        path.write_text(payload + "\n")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_source_wheel_policy(path, sha256_bytes(path.read_bytes()))


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
        json.dumps({"schema_version": 1, "allowed_hosts": ["files.example.invalid"], "entries": [entry]})
    )
    loaded = load_source_wheel_policy(policy_path, sha256_bytes(policy_path.read_bytes()))
    inspect_source_distribution(loaded.entries[0].sources[0], matching)

    mismatched = archive(b"Metadata-Version: 2.1\nName: verifier-helper\nVersion: 2.0\n")
    source["size"] = len(mismatched)
    source["sha256"] = sha256_bytes(mismatched)
    policy_path.write_text(
        json.dumps({"schema_version": 1, "allowed_hosts": ["files.example.invalid"], "entries": [entry]})
    )
    loaded = load_source_wheel_policy(policy_path, sha256_bytes(policy_path.read_bytes()))
    with pytest.raises(RuntimeError, match="metadata does not match"):
        inspect_source_distribution(loaded.entries[0].sources[0], mismatched)


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
    source_build_argv = next(argv for argv in builder.argvs if "--no-build-isolation" in argv)
    assert "--no-index" in source_build_argv
    assert "--no-deps" in source_build_argv
    assert source_build_argv[-1] == (
        "verifier-helper @ file:///tmp/terminal-bench-source-inputs/"
        f"verifier_helper-1.0.tar.gz#sha256={sha256_bytes(source_payload)}"
    )
    assert builder.events.count("download") == 1
    assert builder.events.index("download") < builder.events.index("network-isolated")
    assert builder.events.index("network-isolated") < builder.events.index("source-build")
    manifest_path = tmp_path / "source_wheel_attestations.json"
    manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
    manifest = json.loads(manifest_path.read_text())
    assert manifest["policy_sha256"] == taskset.source_wheel_policy_sha256
    assert manifest["entries"][0]["build_contract"]["build_isolation"] is False
    assert manifest["entries"][0]["build_contract"]["isolated_python"] is True
    assert manifest["entries"][0]["build_contract"]["build_network"] == "no-network"
    assert manifest["entries"][0]["sources"][0]["policy"]["sha256"] == sha256_bytes(source_payload)
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
        value = value.replace('"schema_version":1', '"schema_version":1,"schema_version":1', 1)
    else:
        value = value.replace('"schema_version":1', '"schema_version":NaN', 1)
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
    ) -> tuple[dict[str, bytes], tuple[tuple[str, str], ...]]:
        build_started.set()
        await release_build.wait()
        return {"verifier_helper-1.0-py3-none-any.whl": built_wheel}, (("verifier-helper", "1.0"),)

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
        return ProgramResult(exit_code=0, stdout="", stderr="")

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
    class RecordingBoundedSemaphore:
        def __init__(self) -> None:
            self.held = 0
            self.acquisitions = 0

        def acquire(self) -> None:
            assert self.held == 0
            self.held = 1
            self.acquisitions += 1

        def release(self) -> None:
            assert self.held == 1
            self.held = 0

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            self.release()

    semaphore = RecordingBoundedSemaphore()
    monkeypatch.setattr(vacli_backend, "_lease_concurrency", semaphore)
    backend = object.__new__(VacliVMVMBackend)
    backend._destroyed = False
    backend._container_id = "a" * 12
    tunnel = VacliHostTunnel("10.89.0.1", 42000, 1234, 99)

    def succeed(local_port: int) -> tuple[VacliHostTunnel, str]:
        assert semaphore.held == 1
        return tunnel, f"http://10.89.0.1:{local_port}"

    backend._open_host_tunnel = succeed
    assert backend.open_host_tunnel(1234) == (tunnel, "http://10.89.0.1:1234")
    assert semaphore.held == 0

    def fail(local_port: int) -> tuple[VacliHostTunnel, str]:
        assert semaphore.held == 1
        raise BackendInitError(f"failed to expose {local_port}")

    backend._open_host_tunnel = fail
    with pytest.raises(BackendInitError, match="failed to expose"):
        backend.open_host_tunnel(1234)
    assert semaphore.held == 0

    backend._open_host_tunnel = succeed
    assert backend.open_host_tunnel(1234)[0] is tunnel
    assert semaphore.held == 0
    assert semaphore.acquisitions == 3


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
