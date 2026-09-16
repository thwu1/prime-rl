import asyncio
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from terminal_bench_vmvm.taskset import (
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    _compose_path,
    _declared_test_requirements,
    _dockerfile_startup_command,
    _environment_workdir,
    _network_modes,
    _parse_verifier_reward,
)
from verifiers.v1.runtimes import ProgramResult
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


def wheel_archive(*names: str) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name in names:
            payload = b"wheel"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


class DependencyRuntime:
    def __init__(
        self,
        *,
        installed: bool = True,
        wheel_failure: bool = False,
        image: str = "registry.invalid/task@sha256:" + "a" * 64,
        wheel_names: tuple[str, ...] = ("verifier_helper-1.0-py3-none-any.whl",),
    ) -> None:
        self.installed = installed
        self.wheel_failure = wheel_failure
        self.config = SimpleNamespace(image=image)
        self.wheel_archive = wheel_archive(*wheel_names)
        self.events: list[str] = []
        self.commands: list[str] = []

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        command = subprocess.list2cmdline(argv)
        self.commands.append(command)
        if argv[:2] == ["python3", "-c"] and "importlib.metadata" in argv[2]:
            self.events.append("probe")
            output = "" if self.installed else "verifier-helper==1.0\n"
            return ProgramResult(exit_code=0, stdout=output, stderr="")
        if argv[:2] == ["python3", "-c"] and "sysconfig.get_config_var" in argv[2]:
            self.events.append("fingerprint")
            return ProgramResult(
                exit_code=0,
                stdout='["cpython",[3,12],"cpython-312-x86_64-linux-gnu","linux-x86_64","x86_64"]\n',
                stderr="",
            )
        if argv[:4] == ["python3", "-m", "pip", "wheel"]:
            self.events.append("wheel")
            return ProgramResult(
                exit_code=1 if self.wheel_failure else 0,
                stdout="wheel failed" if self.wheel_failure else "",
                stderr="",
            )
        if "PIP_NO_INDEX=1" in command:
            self.events.append("install")
            self.installed = True
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def read(self, path: str) -> bytes:
        self.events.append("archive-read")
        return self.wheel_archive

    async def write(self, path: str, data: bytes) -> None:
        self.events.append("archive-write")
        assert data == self.wheel_archive


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
    return SimpleNamespace(name="task-a", task_dir=str(tmp_path))


def test_verifier_dependencies_prefetch_all_then_install_offline_after_solution(
    tmp_path: Path,
) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=True)

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
    assert "--no-deps" not in wheel_command
    assert "--only-binary" not in wheel_command

    runtime.events.append("solution")
    runtime.installed = False
    asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))

    assert runtime.events == [
        "fingerprint",
        "wheel",
        "archive-read",
        "solution",
        "probe",
        "archive-write",
        "install",
        "probe",
    ]
    install_command = next(command for command in runtime.commands if "PIP_NO_INDEX=1" in command)
    assert "--no-index" in install_command
    assert "--find-links" in install_command
    assert "verifier-helper==1.0" in install_command
    assert controller_archive.exists() is True
    assert runtime not in taskset._prefetched_test_dependencies
    taskset._cleanup_wheelhouse_cache()
    assert controller_archive.exists() is False


def test_verifier_dependency_wheel_failure_is_fail_closed(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=True, wheel_failure=True)

    with pytest.raises(RuntimeError, match="wheel prefetch failed"):
        asyncio.run(taskset._prefetch_test_dependencies(task, runtime))

    assert runtime.events == ["fingerprint", "wheel"]
    assert runtime not in taskset._prefetched_test_dependencies


def test_verifier_dependency_archive_tampering_is_fail_closed(tmp_path: Path) -> None:
    taskset = dependency_taskset(tmp_path)
    task = dependency_task(tmp_path)
    runtime = DependencyRuntime(installed=True)
    asyncio.run(taskset._prefetch_test_dependencies(task, runtime))
    prefetched = taskset._prefetched_test_dependencies[runtime]
    assert prefetched.archive_path is not None
    controller_archive = prefetched.archive_path
    controller_archive.chmod(0o600)
    controller_archive.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="integrity check"):
        asyncio.run(taskset._install_prefetched_test_dependencies(task, runtime))

    assert "install" not in runtime.events
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
