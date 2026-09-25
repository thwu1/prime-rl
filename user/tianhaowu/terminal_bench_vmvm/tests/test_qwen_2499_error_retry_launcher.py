from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import direct_qwen_workers as direct
import eval_run_identity as identity
import pytest
import qwen_2499_error_retry as retry


def _retry_config(tmp_path: Path) -> tuple[Path, Path, str]:
    workflow = Path(__file__).parents[1]
    template = (
        workflow
        / "configs"
        / "eval"
        / "shared_qwen38_2p4t"
        / "qwen_2499_error_retry_sandoq_firecracker.template.toml"
    ).read_text()
    task_file = tmp_path / "retry_tasks.txt"
    task_file.write_text("".join(f"approved-{index:02d}\n" for index in range(64)))
    task_sha256 = hashlib.sha256(task_file.read_bytes()).hexdigest()
    config = tmp_path / "retry.toml"
    config.write_text(
        template.replace("__QWEN_RETRY_TASK_FILE__", str(task_file)).replace(
            "__QWEN_RETRY_TASK_FILE_SHA256__",
            task_sha256,
        )
    )
    return config, task_file, task_sha256


def _retry_config_value(tmp_path: Path) -> dict:
    config, _task_file, _task_sha256 = _retry_config(tmp_path)
    value = tomllib.loads(config.read_text())
    value["client"]["headers"] = {}
    return value


def _retry_identity(tmp_path: Path) -> dict:
    config = _retry_config_value(tmp_path)
    contract, execution = identity._contract(
        config,
        "Qwen3.8-2.4T-A95B",
        role=identity.QWEN_ERROR_RETRY_ROLE,
        sandbox_provider="sandoq",
    )
    execution["sandoq_environment"] = {
        "environment": identity.QWEN_ERROR_RETRY_FIRECRACKER_ENVIRONMENT,
        "task_network": "public",
        "provider_task_network": "host",
        "provider_profile_sha256": identity.QWEN_ERROR_RETRY_FIRECRACKER_PROFILE_SHA256,
        "pool_size": 64,
        "pool_min_size": 0,
        "tunnel_policy": "native-sandoq-reverse-tunnel",
        "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "owner": "test-user",
        "transport_proxy_policy": "official-client-auto",
        "pool_socket_scope": "job-node-local",
        "pool_wal": "/run/control/sandoq-pool.wal.jsonl",
        "pool_event_log": "/run/pool_events.jsonl",
        "use_ecr": True,
        "ecr_registry": "168653207203.dkr.ecr.us-east-2.amazonaws.com",
        "ecr_region": "us-east-2",
        "ecr_pull_through_prefix": "pt_dockerio",
        "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
        "ecr_auth_policy": "private-token-file-mode-0600",
        "allow_dockerhub_fallback": False,
        "create_deadline": "30m",
        "pull_timeout": "1200s",
        "pull_poll_max_errors": "10",
        "gateway_retry_attempts": "15",
        "gateway_retry_interval": "2s",
        "podman_ignore_chown_errors": "1",
        "require_resource_limits": "1",
        "exec_timeout_ceiling": "270",
        "task_pids_limit": "512",
        "observability": "1",
        "pool_heartbeat_timeout": "45s",
        "pool_create_workers": "4",
        "pool_bootstrap_workers": "64",
        "pool_bootstrap_per_image": "8",
        "pool_drain_workers": "32",
        "pool_drain_timeout": "240",
        "pool_renew_workers": "16",
        "session_reuse": "1",
        "pool_max_reuse_count": "1",
        "pool_reuse_jitter": "0",
        "image_cache_max_entries": "0",
        "secret_cache_ttl": "5s",
        "lease_profile": "standard",
        "lease_duration": "1h",
        "pool_renew_interval": "5m",
        "managed_shell_recovery": "disabled",
    }
    empty_tree = hashlib.sha256(b"").hexdigest()
    artifact = "a" * 64
    return {
        "schema_version": 1,
        "role": identity.QWEN_ERROR_RETRY_ROLE,
        "source": {
            "project_root": "/pinned/project",
            "prime_rl_commit": "1" * 40,
            "prime_rl_tree_sha256": empty_tree,
            "verifiers_commit": "2" * 40,
            "verifiers_tree_sha256": empty_tree,
            "renderers_commit": "3" * 40,
            "renderers_tree_sha256": empty_tree,
            "sandbox_provider": "sandoq",
            "sandoq_provider_commit": "4" * 40,
            "sandoq_provider_tree": "5" * 40,
            "sandoq_client_version": "pinned-client",
            "sandoq_site": "/pinned/sandoq-site",
            "sandoq_site_sha256": "6" * 64,
            "sandoq_host_harness_sha256": "7" * 64,
            "derived_image_manifest_sha256": "8" * 64,
        },
        "config": {
            "source": {"path": "/run/inputs/source_config.toml", "sha256": artifact},
            "resolved": {"path": "/run/config.toml", "sha256": artifact},
        },
        "inputs": {
            "manifest": {"path": "/run/inputs/manifest.json", "sha256": artifact},
            "task_file": {"path": "/run/inputs/task_file.txt", "sha256": artifact, "count": 64},
            "image_manifest": {"path": "/run/inputs/image_manifest.json", "sha256": "8" * 64},
        },
        "dataset": {
            "kind": "git_revision",
            "path": "/pinned/dataset",
            "revision": "9" * 40,
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
        },
        "deployment": {
            "kind": "direct_qwen",
            "worker_manifest": {"path": "/run/direct_workers.json", "sha256": artifact},
            "spec_sha256": "b" * 64,
            "endpoint_bundle_sha256": "c" * 64,
            "base_url": "http://127.0.0.1:12345/v1",
            "router": {
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "provider_concurrency": 32,
            },
        },
        "contract": contract,
        "execution": execution,
    }


def test_firecracker_retry_config_requires_explicit_validation_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, task_file, task_sha256 = _retry_config(tmp_path)
    monkeypatch.setattr(direct, "sandoq_compose_task_count", lambda *_args: 0)

    with pytest.raises(direct.DirectWorkerError, match="eval_sandoq_runtime_invalid"):
        direct.validate_eval_config(
            config,
            approved_task_file=task_file,
            approved_task_file_sha256=task_sha256,
        )

    assert (
        direct.validate_eval_config(
            config,
            approved_task_file=task_file,
            approved_task_file_sha256=task_sha256,
            allow_sandoq_firecracker_retry=True,
        )
        == task_sha256
    )


@pytest.mark.parametrize(
    ("before", "after", "error"),
    [
        ('reasoning_effort = "medium"', 'reasoning_effort = "max"', "reasoning_effort"),
        (
            'expected_environment = "oci-runner-firecracker-small"',
            'expected_environment = "oci-runner"',
            "sandoq_runtime_invalid",
        ),
        ("max_connections = 32", "max_connections = 64", "provider_concurrency"),
        (
            "[retries.rollout]\nmax_retries = 0",
            "[retries.rollout]\nmax_retries = 1",
            "rollout_retry_policy",
        ),
        ("max_total_tokens = 262144", "max_total_tokens = 262143", "firecracker_retry_contract"),
    ],
)
def test_firecracker_retry_config_rejects_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: str,
    after: str,
    error: str,
) -> None:
    config, task_file, task_sha256 = _retry_config(tmp_path)
    monkeypatch.setattr(direct, "sandoq_compose_task_count", lambda *_args: 0)
    config.write_text(config.read_text().replace(before, after, 1))

    with pytest.raises(direct.DirectWorkerError, match=error):
        direct.validate_eval_config(
            config,
            approved_task_file=task_file,
            approved_task_file_sha256=task_sha256,
            allow_sandoq_firecracker_retry=True,
        )


def test_error_retry_identity_contract_is_exact(tmp_path: Path) -> None:
    value = _retry_identity(tmp_path)

    assert identity._validate_identity_shape(value) == value
    assert value["contract"]["reasoning_effort"] == "medium"
    assert value["contract"]["harness"] == {
        "id": "mini-swe-agent",
        "version": "2.4.6",
        "placement": "sandbox",
        "step_limit": 200,
        "request_timeout_seconds": 15_000,
        "request_max_retries": 0,
    }
    assert value["execution"]["rollout_concurrency"] == 64
    assert value["execution"]["http_max_connections"] == 32


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("contract", "reasoning_effort"), "max"),
        (("contract", "sampling_max_tokens"), 32_767),
        (("contract", "harness", "version"), "2.4.5"),
        (("contract", "harness", "request_timeout_seconds"), 14_999),
        (("inputs", "task_file", "count"), 63),
        (("deployment", "router", "policy"), "round_robin"),
        (("deployment", "router", "provider_concurrency"), 31),
        (("execution", "rollout_concurrency"), 63),
        (("execution", "http_max_connections"), 64),
        (("execution", "runtime", "expected_environment"), "oci-runner"),
        (("execution", "sandoq_environment", "provider_task_network"), "none"),
        (("execution", "sandoq_environment", "provider_profile_sha256"), "d" * 64),
        (("execution", "sandoq_environment", "allow_dockerhub_fallback"), True),
    ],
)
def test_error_retry_identity_rejects_drift(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    observed = json.loads(json.dumps(_retry_identity(tmp_path)))
    target = observed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(identity.EvalIdentityError, match="schema_invalid"):
        identity._validate_identity_shape(observed)


def test_inner_driver_binds_retry_contract_and_native_tunnel() -> None:
    workflow = Path(__file__).parents[1]
    driver = (workflow / "run_direct_qwen_eval_driver.sh").read_text()

    for required in (
        "QWEN_2499_ERROR_RETRY_CONTRACT",
        "qwen_2499_error_retry.py\" verify-launch",
        "--allow-wrapper-artifacts",
        "qwen-direct-error-retry-2499",
        "native-sandoq-reverse-tunnel",
        "oci-runner-firecracker-small",
        "--approved-config-sha256",
    ):
        assert required in driver


def test_outer_retry_always_propagates_child_failure() -> None:
    workflow = Path(__file__).parents[1]
    launcher = (workflow / "run_qwen_direct_eval.sbatch").read_text()

    assert 'if [[ "$eval_status" -ne 0 ]]; then' in launcher
    assert 'if [[ "$eval_status" -ne 0 &&' not in launcher


def test_retry_certifier_requires_the_dedicated_identity_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    value = _retry_identity(tmp_path)
    value["config"]["source"]["path"] = str(run / "inputs/source_config.toml")
    value["config"]["resolved"]["path"] = str(run / "config.toml")
    value["inputs"]["task_file"]["path"] = str(run / "inputs/task_file.txt")
    value["deployment"]["worker_manifest"]["path"] = str(run / "direct_workers.json")
    monkeypatch.setattr(identity, "load_eval_run_identity", lambda *_args, **_kwargs: {"identity": value})

    assert retry._validate_run_identity(
        run,
        task_sha256=value["inputs"]["task_file"]["sha256"],
        config_sha256=value["config"]["source"]["sha256"],
    )["identity"]["role"] == retry.RETRY_RUN_IDENTITY_ROLE

    value["role"] = "qwen-direct"
    with pytest.raises(retry.QwenRetryError, match="^run_identity_invalid$"):
        retry._validate_run_identity(
            run,
            task_sha256=value["inputs"]["task_file"]["sha256"],
            config_sha256=value["config"]["source"]["sha256"],
        )


def test_error_retry_effective_environment_binds_small_profile_without_foreign_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "run"
    (output / "control").mkdir(parents=True)
    ecr_token = tmp_path / "ecr-token"
    ecr_token.write_text("opaque\n")
    ecr_token.chmod(0o600)
    pool_socket = tmp_path / f"oci-runner-pool-{__import__('os').getuid()}" / "123.sock"
    pool_socket.parent.mkdir()
    arguments = SimpleNamespace(
        role=identity.QWEN_ERROR_RETRY_ROLE,
        expected_model="Qwen3.8-2.4T-A95B",
        slurm_job_id="123",
        sandoq_environment=identity.QWEN_ERROR_RETRY_FIRECRACKER_ENVIRONMENT,
        sandoq_task_network="public",
        sandoq_pool_size="64",
        sandoq_pool_min_size="0",
        sandoq_tunnel_policy="native-sandoq-reverse-tunnel",
        sandoq_base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
        sandoq_owner="test-user",
        sandoq_transport_proxy_policy="official-client-auto",
        sandoq_pool_socket=str(pool_socket),
        sandoq_pool_wal=str(output / "control/sandoq-pool.wal.jsonl"),
        sandoq_pool_event_log=str(output / "pool_events.jsonl"),
        sandoq_use_ecr="1",
        sandoq_ecr_registry="168653207203.dkr.ecr.us-east-2.amazonaws.com",
        sandoq_ecr_region="us-east-2",
        sandoq_ecr_pull_through_prefix="pt_dockerio",
        sandoq_ecr_token_file=str(ecr_token),
        sandoq_allow_dockerhub_fallback="0",
        sandoq_create_deadline="30m",
        sandoq_pull_timeout="1200s",
        sandoq_pull_poll_max_errors="10",
        sandoq_gateway_retry_attempts="15",
        sandoq_gateway_retry_interval="2s",
        sandoq_podman_ignore_chown_errors="1",
        sandoq_require_resource_limits="1",
        sandoq_exec_timeout_ceiling="270",
        sandoq_task_pids_limit="512",
        sandoq_observability="1",
        sandoq_pool_heartbeat_timeout="45s",
        sandoq_pool_create_workers="4",
        sandoq_pool_bootstrap_workers="64",
        sandoq_pool_bootstrap_per_image="8",
        sandoq_pool_drain_workers="32",
        sandoq_pool_drain_timeout="240",
        sandoq_pool_renew_workers="16",
        sandoq_session_reuse="1",
        sandoq_pool_max_reuse_count="1",
        sandoq_pool_reuse_jitter="0",
        sandoq_image_cache_max_entries="0",
        sandoq_secret_cache_ttl="5s",
        sandoq_lease_profile="standard",
        sandoq_lease_duration="1h",
        sandoq_pool_renew_interval="5m",
        sandoq_managed_shell_recovery="disabled",
    )
    environment = {
        "SLURM_TMPDIR": str(tmp_path),
        "OCI_RUNNER_TASK_NETWORK": "host",
        "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "0",
        "SANDOQ_PROVIDER_PROFILE_SHA256": identity.QWEN_ERROR_RETRY_FIRECRACKER_PROFILE_SHA256,
        "OCI_RUNNER_ECR_TOKEN_FILE": str(ecr_token),
        "OCI_RUNNER_POOL_SOCKET": str(pool_socket),
        "OCI_RUNNER_POOL_WAL": str(output / "control/sandoq-pool.wal.jsonl"),
        "OCI_RUNNER_POOL_EVENT_LOG": str(output / "pool_events.jsonl"),
        "PRIME_RL_OUTPUT_DIR": str(output),
        "SANDOQ_LEASE_PROFILE": "standard",
        "OCI_RUNNER_LEASE_DURATION": "1h",
        "OCI_RUNNER_POOL_RENEW_INTERVAL": "5m",
        "OCI_RUNNER_MANAGED_SHELL_RECOVERY": "0",
    }
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "SANDOQ_TUNNEL_HTTPS_PROXY",
        "SANDOQ_RUNTIME_SMOKE_RECEIPT",
        "SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256",
        "SANDOQ_RUNTIME_RESOURCE_RECEIPT",
        "SANDOQ_RUNTIME_RESOURCE_RECEIPT_SHA256",
        "DIRECT_KIMI_MINISWE_COMPATIBILITY_RECEIPT_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    observed = identity._effective_sandoq_environment(arguments, 64, output)
    assert observed["provider_profile_sha256"] == identity.QWEN_ERROR_RETRY_FIRECRACKER_PROFILE_SHA256
    assert observed["provider_task_network"] == "host"
    assert observed["allow_dockerhub_fallback"] is False
    assert "runtime_tunnel_receipt_sha256" not in observed

    monkeypatch.setenv("SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256", "f" * 64)
    with pytest.raises(identity.EvalIdentityError, match="sandoq_transport_policy_invalid"):
        identity._effective_sandoq_environment(arguments, 64, output)
