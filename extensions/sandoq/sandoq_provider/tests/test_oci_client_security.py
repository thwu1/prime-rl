from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from prime_sandboxes.exceptions import APIError
from sandoq_provider.ecr import ECRConfig, ECRCredentialCache, authenticated_ecr_registry
from sandoq_provider.gateway import SandoqHttpResponse
from sandoq_provider.oci_client import (
    CommandResponse,
    OCIRunnerAsyncSandboxClient,
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
