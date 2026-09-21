from __future__ import annotations

import asyncio
import time
from dataclasses import fields
from types import SimpleNamespace

import pytest
from prime_sandboxes.exceptions import APIError
from sandoq_provider.ecr import ECRConfig, ECRCredentialCache, authenticated_ecr_registry
from sandoq_provider.gateway import SandoqHttpResponse
from sandoq_provider.oci_client import (
    CommandResponse,
    OCIRunnerAsyncSandboxClient,
    OCIRunnerStageError,
    _image_mounts,
    get_oci_config,
)


@pytest.mark.parametrize("key", ["ECR_CREDENTIAL", "REGISTRY_AUTH"])
def test_outer_exec_redacts_failures_for_credential_environment_keys(key: str) -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(exec_timeout_ceiling_s=270)
    client._auth_headers = lambda: {}

    async def request_json(*args: object, **kwargs: object) -> SandoqHttpResponse:
        return SandoqHttpResponse(status_code=500, body={"echoed_secret": "do-not-log"})

    client._request_json = request_json
    info = SimpleNamespace(session_id="session-1")

    with pytest.raises(APIError, match="response omitted") as raised:
        asyncio.run(client._outer_exec(info, "false", 10, env={key: "do-not-log"}))

    assert "do-not-log" not in str(raised.value)


@pytest.mark.parametrize("task_network", ["none", "host"])
def test_nested_run_command_quotes_fallback_image(task_network: str) -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        require_resource_limits=False,
        task_network=task_network,
    )
    info = SimpleNamespace(metadata={}, environment="oci-runner-firecracker")

    command = client._nested_run_command(info, "registry.example/image:tag; echo unsafe")

    assert f"--network {task_network}" in command
    assert "'registry.example/image:tag; echo unsafe'" in command
    assert command.endswith("'trap : TERM INT; sleep infinity & wait' >/dev/null")


def test_nested_run_command_mounts_auxiliary_image_read_only() -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        require_resource_limits=False,
        task_network="host",
    )
    info = SimpleNamespace(
        metadata={
            "image_mounts": [
                {
                    "source_image": "registry.example/toolbox@sha256:" + "a" * 64,
                    "image": "registry.example/toolbox@sha256:" + "a" * 64,
                    "target": "/opt/prime-agent-toolbox",
                }
            ]
        },
        environment="oci-runner-firecracker",
    )

    command = client._nested_run_command(info, "registry.example/task:latest")

    assert (
        "--mount type=image,source=registry.example/toolbox@sha256:" + "a" * 64 + ",target=/opt/prime-agent-toolbox"
    ) in command


def test_image_mounts_resolve_docker_hub_and_reject_root_target() -> None:
    ecr = ECRConfig(
        registry="123456789012.dkr.ecr.us-east-2.amazonaws.com",
        region="us-east-2",
        pull_through_prefix="pt_dockerio",
        token_file=None,
        client_cert_path=None,
        ucloud_executable="ucloud",
        refresh_interval_s=3600,
        command_timeout_s=60,
    )

    mounts = _image_mounts(
        [{"image": "docker.io/example/tools:1", "target": "/opt/tools"}],
        ecr,
    )
    assert mounts == [
        {
            "source_image": "docker.io/example/tools:1",
            "image": "123456789012.dkr.ecr.us-east-2.amazonaws.com/pt_dockerio/example/tools:1",
            "target": "/opt/tools",
        }
    ]

    with pytest.raises(APIError, match="below root"):
        _image_mounts([{"image": "example/tools:1", "target": "/"}], ecr)

    with pytest.raises(APIError, match="unsupported characters"):
        _image_mounts(
            [{"image": "example/tools:1,target=/escape", "target": "/opt/tools"}],
            ecr,
        )


def test_auxiliary_ecr_registry_uses_its_own_read_only_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = "168653207203.dkr.ecr.us-east-2.amazonaws.com"
    auxiliary = "588845226011.dkr.ecr.us-east-2.amazonaws.com"
    monkeypatch.setenv("OCI_RUNNER_ECR_REGISTRY", primary)
    monkeypatch.setenv("OCI_RUNNER_ECR_AUXILIARY_REGISTRIES", f"{auxiliary},{auxiliary}")
    config = ECRConfig.from_env()

    assert config.authenticated_registries == (primary, auxiliary)
    assert authenticated_ecr_registry(f"{auxiliary}/team/toolbox@sha256:{'a' * 64}", config) == auxiliary
    assert authenticated_ecr_registry("registry.example/team/toolbox:1", config) is None

    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="short-lived-password\n")

    monkeypatch.setattr("sandoq_provider.ecr.subprocess.run", run)
    credential = ECRCredentialCache(config, auxiliary).get()

    assert credential["password"] == "short-lived-password"
    assert commands == [
        [
            "ucloud",
            "ecr",
            "get-credentials",
            "--account",
            "588845226011",
            "--region",
            "us-east-2",
            "--role",
            "SSOContainerRegistryReadOnly",
            "--log-level",
            "error",
        ]
    ]


def test_auxiliary_ecr_registry_must_be_an_aws_ecr_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCI_RUNNER_ECR_AUXILIARY_REGISTRIES", "registry.example")

    with pytest.raises(APIError, match="AWS ECR hostnames"):
        ECRConfig.from_env()


def test_task_network_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "bridge")

    with pytest.raises(APIError, match="must be 'none' or 'host'"):
        get_oci_config()


def test_host_task_network_requires_firecracker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "host")
    monkeypatch.setenv("OCI_RUNNER_ENVIRONMENT", "oci-runner")

    with pytest.raises(APIError, match="supported only by Firecracker"):
        get_oci_config()


def test_direct_dockerhub_fallback_is_enabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK", raising=False)

    assert get_oci_config().allow_dockerhub_fallback is True


def test_oci_config_preserves_legacy_positional_constructor() -> None:
    observed = get_oci_config()
    legacy_values = [
        getattr(observed, field.name)
        for field in fields(observed)
        if field.name not in {"allow_dockerhub_fallback", "managed_shell_recovery"}
    ]

    reconstructed = type(observed)(*legacy_values)

    assert reconstructed.allow_dockerhub_fallback is True
    assert reconstructed.managed_shell_recovery is False


def test_direct_dockerhub_fallback_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK", "0")

    assert get_oci_config().allow_dockerhub_fallback is False


def test_direct_dockerhub_fallback_rejects_ambiguous_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK", "false")

    with pytest.raises(APIError, match="must be '0' or '1'"):
        get_oci_config()


def test_managed_shell_recovery_is_derived_from_sealed_lease_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANDOQ_LEASE_PROFILE", "kimi-tb4-long")
    monkeypatch.setenv("OCI_RUNNER_MANAGED_SHELL_RECOVERY", "1")

    assert get_oci_config().managed_shell_recovery is True

    monkeypatch.setenv("OCI_RUNNER_MANAGED_SHELL_RECOVERY", "0")
    with pytest.raises(APIError, match="disagrees"):
        get_oci_config()


@pytest.mark.parametrize("missing_status", [404, 410])
def test_definitive_missing_managed_shell_is_recovered_once(
    monkeypatch: pytest.MonkeyPatch,
    missing_status: int,
) -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        exec_timeout_ceiling_s=270,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
        managed_shell_recovery=True,
    )
    client._auth_headers = lambda: {}
    info = SimpleNamespace(
        session_id="assignment-1",
        shell_id="shell-old",
        session_reuse=True,
        env_vars={"OCI_EXPECTED_WORKDIR": "/testbed"},
        metadata={},
        assignment_poisoned=False,
        assignment_poison_reason=None,
        shell_failure_status=None,
    )
    calls: list[tuple[str, str, object]] = []
    responses = iter(
        [
            SandoqHttpResponse(status_code=missing_status, body={}),
            SandoqHttpResponse(status_code=200, body={"status": "ok"}),
            SandoqHttpResponse(status_code=200, body={"shells": []}),
            SandoqHttpResponse(
                status_code=200,
                body={"stdout": "ok", "stderr": "", "exitCode": 0, "timedOut": False},
            ),
        ]
    )

    async def request_json(_info: object, method: str, path: str, **kwargs: object) -> SandoqHttpResponse:
        calls.append((method, path, kwargs.get("body")))
        return next(responses)

    client._request_json = request_json

    class Pool:
        def __init__(self) -> None:
            self.operations: list[tuple[str, str]] = []
            self.recoveries = 0

        def begin_shell_command(
            self,
            assignment_id: str,
            shell_id: str,
            *,
            timeout_seconds: float,
        ) -> dict[str, object]:
            del assignment_id, timeout_seconds
            operation_id = f"operation-{len(self.operations)}"
            self.operations.append(("begin", shell_id))
            return {"status": "authorized", "operation_id": operation_id, "shell_id": shell_id}

        def complete_shell_command(self, assignment_id: str, operation_id: str) -> dict[str, object]:
            del assignment_id
            self.operations.append(("complete", operation_id))
            return {"completed": True}

        def recover_managed_shell(
            self,
            assignment_id: str,
            expected_shell_id: str,
            *,
            workdir: str,
        ) -> dict[str, object]:
            del assignment_id
            assert expected_shell_id == "shell-old"
            assert workdir == "/testbed"
            self.recoveries += 1
            return {"status": "recovered", "shell_id": "shell-new", "shell_generation": 1}

    pool = Pool()
    monkeypatch.setattr("sandoq_provider.pool.get_pool_client", lambda: pool)

    result = asyncio.run(client._nested_exec_argv(info, ["bash", "-c", "true"]))

    assert result == CommandResponse(stdout="ok", stderr="", exit_code=0)
    assert info.shell_id == "shell-new"
    assert info.metadata["managed_shell_recovery_count"] == 1
    assert pool.recoveries == 1
    assert [call[:2] for call in calls] == [
        ("POST", "v1/exec"),
        ("GET", "healthz"),
        ("GET", "v1/shells"),
        ("POST", "v1/exec"),
    ]
    assert pool.operations[0] == ("begin", "shell-old")
    assert pool.operations[2] == ("begin", "shell-new")


def test_ambiguous_managed_shell_failure_is_not_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        exec_timeout_ceiling_s=270,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
        managed_shell_recovery=True,
    )
    client._auth_headers = lambda: {}
    info = SimpleNamespace(
        session_id="assignment-1",
        shell_id="shell-old",
        session_reuse=True,
        env_vars={"OCI_EXPECTED_WORKDIR": "/testbed"},
        metadata={},
        assignment_poisoned=False,
        assignment_poison_reason=None,
        shell_failure_status=None,
    )
    responses = iter(
        [
            SandoqHttpResponse(status_code=502, body={}),
            SandoqHttpResponse(status_code=200, body={"status": "ok"}),
            SandoqHttpResponse(status_code=200, body={"shells": []}),
        ]
    )

    async def request_json(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        return next(responses)

    client._request_json = request_json

    class Pool:
        recoveries = 0

        def begin_shell_command(self, *args: object, **kwargs: object) -> dict[str, object]:
            del args, kwargs
            return {"status": "authorized", "operation_id": "operation-1", "shell_id": "shell-old"}

        def complete_shell_command(self, *args: object, **kwargs: object) -> dict[str, object]:
            del args, kwargs
            return {"completed": True}

        def recover_managed_shell(self, *args: object, **kwargs: object) -> dict[str, object]:
            del args, kwargs
            self.recoveries += 1
            return {"status": "recovered", "shell_id": "shell-new"}

    pool = Pool()
    monkeypatch.setattr("sandoq_provider.pool.get_pool_client", lambda: pool)

    with pytest.raises(OCIRunnerStageError) as raised:
        asyncio.run(client._nested_exec_argv(info, ["bash", "-c", "true"]))

    assert raised.value.failure_reason == "gateway_command_outcome_unknown"
    assert pool.recoveries == 0


def test_replacement_shell_failure_is_not_recovered_twice() -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        exec_timeout_ceiling_s=270,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
        managed_shell_recovery=True,
    )
    info = SimpleNamespace(
        session_id="assignment-1",
        shell_id="shell-old",
        session_reuse=True,
        env_vars={"OCI_EXPECTED_WORKDIR": "/testbed"},
        metadata={},
        assignment_poisoned=False,
        assignment_poison_reason=None,
        shell_failure_status=None,
    )
    recoveries: list[str] = []

    async def request(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        return SandoqHttpResponse(status_code=404, body={})

    async def diagnostics(_info: object) -> dict[str, object]:
        return {"health_http_status": 200, "shell_http_status": 200}

    async def recover(_info: object, expected_shell_id: str) -> None:
        recoveries.append(expected_shell_id)
        info.shell_id = "shell-new"

    client._managed_shell_request = request
    client._collect_terminal_diagnostics = diagnostics
    client._recover_managed_shell = recover

    with pytest.raises(OCIRunnerStageError) as raised:
        asyncio.run(client._nested_exec_argv(info, ["bash", "-c", "true"]))

    assert raised.value.failure_reason == "managed_shell_lost"
    assert recoveries == ["shell-old"]


def test_standard_profile_never_recovers_missing_managed_shell() -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        exec_timeout_ceiling_s=270,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
        managed_shell_recovery=False,
    )
    info = SimpleNamespace(
        session_id="assignment-1",
        shell_id="shell-old",
        session_reuse=True,
        env_vars={"OCI_EXPECTED_WORKDIR": "/testbed"},
        metadata={},
        assignment_poisoned=False,
        assignment_poison_reason=None,
        shell_failure_status=None,
    )

    async def request(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        return SandoqHttpResponse(status_code=404, body={})

    async def diagnostics(_info: object) -> dict[str, object]:
        return {"health_http_status": 200, "shell_http_status": 200}

    client._managed_shell_request = request
    client._collect_terminal_diagnostics = diagnostics

    with pytest.raises(OCIRunnerStageError) as raised:
        asyncio.run(client._nested_exec_argv(info, ["bash", "-c", "true"]))

    assert raised.value.failure_reason == "outer_session_lost"


@pytest.mark.parametrize("allow_fallback", [False, True])
def test_ecr_upstream_auth_failure_obeys_direct_fallback_policy(
    allow_fallback: bool,
) -> None:
    registry = "123456789012.dkr.ecr.us-east-2.amazonaws.com"
    ecr = ECRConfig(
        registry=registry,
        region="us-east-2",
        pull_through_prefix="pt_dockerio",
        token_file=None,
        client_cert_path=None,
        ucloud_executable="ucloud",
        refresh_interval_s=3600,
        command_timeout_s=60,
    )
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    client._oci_cfg = SimpleNamespace(
        allow_dockerhub_fallback=allow_fallback,
        ecr=ecr,
        podman_ignore_chown_errors=False,
        pull_poll_max_errors=1,
        pull_timeout_s=30,
    )
    client._podman_pull_command = lambda *_args, **_kwargs: "podman pull image"
    responses = iter(
        [
            CommandResponse(stdout="LAUNCHED:123\n", stderr="", exit_code=0),
            CommandResponse(
                stdout=("FINISHED:1\nauthentication to the upstream registry failed"),
                stderr="",
                exit_code=0,
            ),
            CommandResponse(stdout="", stderr="", exit_code=0),
        ]
    )

    async def outer_exec(*_args: object, **_kwargs: object) -> CommandResponse:
        return next(responses)

    fallback_calls: list[str] = []

    async def pull_image(
        _info: object,
        image: str,
        **_kwargs: object,
    ) -> None:
        fallback_calls.append(image)

    async def ensure_auth(*_args: object, **_kwargs: object) -> None:
        return None

    client._outer_exec_idempotent = outer_exec
    client._pull_image = pull_image
    client._ensure_dockerhub_authentication = ensure_auth
    info = SimpleNamespace(
        metadata={},
        session_id="session-1",
        source_image="docker.io/example/task@sha256:" + "a" * 64,
    )
    requested = f"{registry}/pt_dockerio/example/task@sha256:" + "a" * 64

    operation = client._pull_image_once(
        info,
        requested,
        deadline=time.monotonic() + 30,
        pull_id="0123456789abcdef0123456789abcdef",
        allow_ecr_fallback=True,
    )
    if allow_fallback:
        asyncio.run(operation)
        assert fallback_calls == [info.source_image]
        assert info.metadata["image_pull_fallback"] == "direct_dockerhub"
    else:
        with pytest.raises(APIError, match="podman pull failed"):
            asyncio.run(operation)
        assert fallback_calls == []
        assert "image_pull_fallback" not in info.metadata


def test_background_job_paths_reject_untrusted_job_id() -> None:
    info = SimpleNamespace(session_id="assignment-1")

    with pytest.raises(APIError, match="invalid background job id"):
        OCIRunnerAsyncSandboxClient._background_job_paths(info, "../../outside")


def test_background_job_status_uses_idempotent_exec() -> None:
    client = object.__new__(OCIRunnerAsyncSandboxClient)
    info = SimpleNamespace(session_id="assignment-1")
    client._info = lambda sandbox_id: info
    calls: list[dict[str, object]] = []

    async def outer_exec_idempotent(*args: object, **kwargs: object) -> CommandResponse:
        calls.append(kwargs)
        return CommandResponse(stdout="RUNNING\n", stderr="", exit_code=0)

    client._outer_exec_idempotent = outer_exec_idempotent

    status = asyncio.run(
        client.get_background_job(
            "sandbox-1",
            {"job_id": "job-0123456789abcdef0123456789abcdef"},
        )
    )

    assert status.completed is False
    assert calls == [{"timeout": 30, "operation": "background_job_status"}]
