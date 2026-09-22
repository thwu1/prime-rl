from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from terminal_bench_vmvm import sandoq_provider_context as context


def _arguments(tmp_path: Path) -> dict[str, object]:
    return {
        "cluster_identifier": "synthetic_cluster",
        "transport_mode": "loopback",
        "proxy_url": "http://127.0.0.1:43123",
        "concurrency": 64,
        "lease_create_cap": 4,
        "startup_timeout_seconds": 3600,
        "provider_token_file": tmp_path / "provider-token",
        "ecr_token_file": tmp_path / "ecr-token",
        "ecr_token_metadata": tmp_path / "ecr-token.metadata.json",
        "project_root": tmp_path / "project",
        "sandoq_site": tmp_path / "sandoq-site",
    }


def _runtime_smoke_receipt(tmp_path: Path) -> tuple[Path, str]:
    path = (tmp_path / "runtime-smoke.json").resolve()
    body = context._canonical_json(
        {
            "schema_version": 1,
            "kind": "kimi-firecracker-nonnetwork-smoke",
            "state": "passed",
            "environment": "oci-runner-firecracker",
            "network_access": False,
            "loopback_only_verified": True,
            "execution_passed": True,
            "cleanup_verified": True,
            "cleanup_failures": 0,
            "slurm_job_id": "123",
        }
    )
    path.write_bytes(body)
    path.chmod(0o600)
    return path, context._sha256(body)


def _runtime_tunnel_receipt(tmp_path: Path) -> tuple[Path, str]:
    path = (tmp_path / "runtime-tunnel.json").resolve()
    body = context._canonical_json(
        {
            "schema_version": 1,
            "kind": "sandoq-firecracker-tunnel-capability",
            "state": "passed",
            "environment": "oci-runner-firecracker",
            "port_names": ["exec", "tunnel"],
            "create_session_verified": True,
            "tunnel_available": True,
            "cleanup_verified": True,
            "slurm_job_id": "123",
        }
    )
    path.write_bytes(body)
    path.chmod(0o600)
    return path, context._sha256(body)


def _runtime_resource_receipt(tmp_path: Path) -> tuple[Path, str]:
    path = (tmp_path / "runtime-resource.json").resolve()
    body = context._canonical_json(
        {
            "schema_version": 1,
            "kind": "sandoq-full-resource-tunnel-capability",
            "state": "passed",
            "environment": "oci-runner-firecracker",
            "requested_cpu": 2,
            "requested_memory_gb": 4,
            "requested_disk_gb": 10,
            "sandbox_started": True,
            "tunnel_roundtrip_verified": True,
            "command_exit_code": 0,
            "runtime_stop_completed": True,
            "elapsed_seconds": 1.5,
            "slurm_job_id": "123",
        }
    )
    path.write_bytes(body)
    path.chmod(0o600)
    return path, context._sha256(body)


def test_build_provider_environment_matches_sc3_context_without_reading_tokens(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    environment = context.build_provider_environment(
        {
            "USER": "synthetic-user",
            "HTTP_PROXY": "http://inherited.invalid",
            "HTTPS_PROXY": "http://inherited.invalid",
            "all_proxy": "http://inherited.invalid",
            "VF_SANDBOX_PROVIDER": "wrong",
            "FIRECRACKER_KEY": "must-not-survive",
            "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "0",
            "OCI_RUNNER_LEASE_DURATION": "99h",
            "SANDOQ_LEASE_PROFILE": "ambient-invalid",
            "PYTHONPATH": "/existing",
        },
        **arguments,
    )

    assert environment["OCI_RUNNER_BASE_URL"] == context.BASE_URL
    assert environment["OCI_RUNNER_ENVIRONMENT"] == "oci-runner"
    assert environment["SANDOQ_EFFECTIVE_TASK_NETWORK"] == "public"
    assert "OCI_RUNNER_TASK_NETWORK" not in environment
    assert environment["OCI_RUNNER_POOL_SIZE"] == "64"
    assert environment["OCI_RUNNER_POOL_CREATE_WORKERS"] == "4"
    assert environment["OCI_RUNNER_SESSION_REUSE"] == "1"
    assert environment["OCI_RUNNER_POOL_MAX_REUSE_COUNT"] == "1"
    assert environment["SANDOQ_LEASE_PROFILE"] == "standard"
    assert environment["OCI_RUNNER_LEASE_DURATION"] == "1h"
    assert environment["OCI_RUNNER_POOL_RENEW_INTERVAL"] == "5m"
    assert environment["OCI_RUNNER_MANAGED_SHELL_RECOVERY"] == "0"
    assert environment["OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES"] == "0"
    assert environment["OCI_RUNNER_PODMAN_FUSE_OVERLAYFS"] == "1"
    assert environment["OCI_RUNNER_PULL_TIMEOUT"] == "3600s"
    assert environment["OCI_RUNNER_PULL_POLL_MAX_ERRORS"] == "20"
    assert environment["HTTPS_PROXY"] == arguments["proxy_url"]
    assert environment["https_proxy"] == arguments["proxy_url"]
    assert "HTTP_PROXY" not in environment
    assert "all_proxy" not in environment
    assert "VF_SANDBOX_PROVIDER" not in environment
    assert "FIRECRACKER_KEY" not in environment
    assert "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK" not in environment
    assert not Path(arguments["provider_token_file"]).exists()


def test_auto_transport_clears_proxy_environment(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    arguments.update({"transport_mode": "auto", "proxy_url": None})

    environment = context.build_provider_environment(
        {
            "USER": "synthetic-user",
            "HTTP_PROXY": "http://inherited.invalid",
            "HTTPS_PROXY": "http://inherited.invalid",
            "all_proxy": "http://inherited.invalid",
        },
        **arguments,
    )

    assert environment["SANDOQ_TRANSPORT_MODE"] == "auto"
    assert all(name not in environment for name in context.PROXY_ENVIRONMENT_NAMES)


def test_firecracker_profile_sets_isolated_network_and_scrubs_ambient_tokens(
    tmp_path: Path,
) -> None:
    profile_path = (
        Path(__file__).parents[1] / "configs/provider_context/use2/kimi_sandoq_firecracker_no_network.json"
    ).resolve()
    profile = context.load_provider_profile(
        profile_path,
        context._sha256(profile_path.read_bytes()),
    )
    arguments = _arguments(tmp_path)
    arguments["provider_token_file"] = profile.provider_token_file
    runtime_smoke_receipt, runtime_smoke_sha256 = _runtime_smoke_receipt(tmp_path)
    environment = context.build_provider_environment(
        {
            "USER": "synthetic-user",
            "FIRECRACKER_KEY": "must-not-survive",
            "SANDOQ_AUTH_TOKEN": "must-not-survive",
            "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "1",
        },
        **arguments,
        provider_environment=profile.environment,
        effective_task_network=profile.effective_task_network,
        task_network=profile.task_network,
        runtime_smoke_receipt=runtime_smoke_receipt,
        runtime_smoke_receipt_sha256=runtime_smoke_sha256,
        provider_profile_sha256=profile.sha256,
    )

    assert profile.environment == "oci-runner-firecracker"
    assert profile.task_network == "none"
    assert environment["OCI_RUNNER_ENVIRONMENT"] == "oci-runner-firecracker"
    assert environment["OCI_RUNNER_TASK_NETWORK"] == "none"
    assert environment["SANDOQ_EFFECTIVE_TASK_NETWORK"] == "none"
    assert environment["OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK"] == "0"
    assert environment["OCI_RUNNER_PULL_TIMEOUT"] == "1200s"
    assert environment["OCI_RUNNER_PULL_POLL_MAX_ERRORS"] == "10"
    assert environment["OCI_RUNNER_TOKEN_FILE"] == str(profile.provider_token_file)
    assert environment["SANDOQ_RUNTIME_SMOKE_RECEIPT"] == str(runtime_smoke_receipt)
    assert environment["SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256"] == runtime_smoke_sha256
    assert environment[context.CONTEXT_PROFILE_SHA256] == profile.sha256
    assert "FIRECRACKER_KEY" not in environment
    assert "SANDOQ_AUTH_TOKEN" not in environment


def test_full_firecracker_profile_requires_bound_native_tunnel_receipt(tmp_path: Path) -> None:
    profile_path = (
        Path(__file__).parents[1] / "configs/provider_context/use2/kimi_sandoq_firecracker_host.json"
    ).resolve()
    profile = context.load_provider_profile(profile_path, context._sha256(profile_path.read_bytes()))
    receipt, receipt_sha256 = _runtime_tunnel_receipt(tmp_path)
    resource_receipt, resource_receipt_sha256 = _runtime_resource_receipt(tmp_path)
    arguments = _arguments(tmp_path)
    arguments.update(
        {
            "transport_mode": "auto",
            "proxy_url": None,
            "provider_token_file": profile.provider_token_file,
        }
    )

    context._validate_runtime_smoke_receipt(
        receipt,
        receipt_sha256,
        environment=profile.environment,
        effective_task_network=profile.effective_task_network,
        task_network=profile.task_network,
    )
    environment = context.build_provider_environment(
        {"USER": "synthetic-user", "HTTPS_PROXY": "http://ambient.invalid"},
        **arguments,
        provider_environment=profile.environment,
        effective_task_network=profile.effective_task_network,
        task_network=profile.task_network,
        runtime_smoke_receipt=receipt,
        runtime_smoke_receipt_sha256=receipt_sha256,
        runtime_resource_receipt=resource_receipt,
        runtime_resource_receipt_sha256=resource_receipt_sha256,
        provider_profile_sha256=profile.sha256,
    )

    assert profile.environment == "oci-runner-firecracker"
    assert profile.effective_task_network == "public"
    assert profile.task_network == "host"
    assert environment["OCI_RUNNER_TASK_NETWORK"] == "host"
    assert environment["SANDOQ_RUNTIME_SMOKE_RECEIPT_SHA256"] == receipt_sha256
    assert environment["SANDOQ_RUNTIME_RESOURCE_RECEIPT_SHA256"] == resource_receipt_sha256
    assert environment["OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK"] == "0"
    assert all(name not in environment for name in context.PROXY_ENVIRONMENT_NAMES)


def test_long_kimi_profile_sets_exact_twelve_hour_initial_lease(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    arguments.update({"transport_mode": "auto", "proxy_url": None, "lease_profile": "kimi-tb4-long"})

    environment = context.build_provider_environment(
        {
            "USER": "synthetic-user",
            "OCI_RUNNER_LEASE_DURATION": "1h",
            "SANDOQ_LEASE_PROFILE": "standard",
        },
        **arguments,
    )

    assert environment["SANDOQ_LEASE_PROFILE"] == "kimi-tb4-long"
    assert environment["OCI_RUNNER_LEASE_DURATION"] == "12h"
    assert environment["OCI_RUNNER_POOL_RENEW_INTERVAL"] == "5m"
    assert environment["OCI_RUNNER_MANAGED_SHELL_RECOVERY"] == "1"

    arguments["lease_profile"] = "arbitrary"
    with pytest.raises(context.ProviderContextError, match="provider_context_configuration_invalid"):
        context.build_provider_environment({"USER": "synthetic-user"}, **arguments)


def test_firecracker_supervisor_receipt_binds_isolated_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = tmp_path / "firecracker-result.json"
    profile_path = (
        Path(__file__).parents[1] / "configs/provider_context/use2/kimi_sandoq_firecracker_no_network.json"
    ).resolve()
    profile = context.load_provider_profile(
        profile_path,
        context._sha256(profile_path.read_bytes()),
    )
    arguments = _arguments(tmp_path)
    runtime_smoke_receipt, runtime_smoke_sha256 = _runtime_smoke_receipt(tmp_path)
    monkeypatch.setenv("SLURM_TMPDIR", str(tmp_path))
    monkeypatch.setenv("SANDOQ_AUTH_TOKEN", "must-not-survive")
    code = (
        "import json, os, runpy; from pathlib import Path; "
        f"module = runpy.run_path({str(Path(context.__file__))!r}); "
        "provider_context_is_active = module['provider_context_is_active']; "
        "snapshot_provider_context = module['snapshot_provider_context']; "
        f"snapshot = snapshot_provider_context(os.environ, Path({str(tmp_path / 'sandoq-provider-context.json')!r})); "
        "payload = dict(active=provider_context_is_active(os.environ), "
        "environment=os.environ.get('OCI_RUNNER_ENVIRONMENT'), "
        "effective_network=os.environ.get('SANDOQ_EFFECTIVE_TASK_NETWORK'), "
        "task_network=os.environ.get('OCI_RUNNER_TASK_NETWORK'), "
        "fallback=os.environ.get('OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK'), "
        "ambient_token_present='SANDOQ_AUTH_TOKEN' in os.environ, "
        "profile_sha256=snapshot['provider_profile_sha256'], "
        "runtime_smoke_sha256=snapshot['runtime_smoke_receipt_sha256']); "
        f"Path({str(result)!r}).write_text(json.dumps(payload))"
    )

    return_code = context.supervise(
        [sys.executable, "-c", code],
        cluster_identifier=profile.cluster_identifier,
        transport_mode="auto",
        concurrency=64,
        lease_create_cap=4,
        startup_timeout_seconds=3600,
        provider_token_file=profile.provider_token_file,
        ecr_token_file=Path(arguments["ecr_token_file"]),
        ecr_token_metadata=Path(arguments["ecr_token_metadata"]),
        project_root=Path(arguments["project_root"]),
        sandoq_site=Path(arguments["sandoq_site"]),
        provider_environment=profile.environment,
        effective_task_network=profile.effective_task_network,
        task_network=profile.task_network,
        runtime_smoke_receipt=runtime_smoke_receipt,
        runtime_smoke_receipt_sha256=runtime_smoke_sha256,
        provider_profile_sha256=profile.sha256,
    )

    assert return_code == 0
    assert json.loads(result.read_text()) == {
        "active": True,
        "ambient_token_present": False,
        "effective_network": "none",
        "environment": "oci-runner-firecracker",
        "fallback": "0",
        "profile_sha256": profile.sha256,
        "runtime_smoke_sha256": runtime_smoke_sha256,
        "task_network": "none",
    }
    snapshot = json.loads((tmp_path / "sandoq-provider-context.json").read_bytes())
    assert snapshot["provider_environment"] == "oci-runner-firecracker"
    assert snapshot["effective_task_network"] == "none"
    assert snapshot["task_network"] == "none"
    assert snapshot["network_access"] is False
    assert snapshot["allow_dockerhub_fallback"] is False
    assert snapshot["provider_context_contract_sha256"]
    assert (tmp_path / "sandoq-provider-context.json").stat().st_mode & 0o777 == 0o600


def test_firecracker_contract_rejects_smoke_tamper(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    runtime_smoke_receipt, runtime_smoke_sha256 = _runtime_smoke_receipt(tmp_path)
    runtime_smoke_receipt.write_text("{}\n")

    with pytest.raises(
        context.ProviderContextError,
        match="provider_context_runtime_smoke_invalid",
    ):
        context.supervise(
            ["/bin/true"],
            cluster_identifier=str(arguments["cluster_identifier"]),
            transport_mode="auto",
            concurrency=64,
            lease_create_cap=4,
            startup_timeout_seconds=3600,
            provider_token_file=Path(arguments["provider_token_file"]),
            ecr_token_file=Path(arguments["ecr_token_file"]),
            ecr_token_metadata=Path(arguments["ecr_token_metadata"]),
            project_root=Path(arguments["project_root"]),
            sandoq_site=Path(arguments["sandoq_site"]),
            provider_environment=context.FIRECRACKER_ENVIRONMENT,
            effective_task_network="none",
            task_network="none",
            runtime_smoke_receipt=runtime_smoke_receipt,
            runtime_smoke_receipt_sha256=runtime_smoke_sha256,
            provider_profile_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    "proxy_url",
    [
        "https://127.0.0.1:1",
        "http://localhost:1",
        "http://user@127.0.0.1:1",
        "http://127.0.0.1:1/path",
        "http://127.0.0.1:1?secret=value",
    ],
)
def test_build_provider_environment_rejects_non_loopback_proxy(tmp_path: Path, proxy_url: str) -> None:
    arguments = _arguments(tmp_path)
    arguments["proxy_url"] = proxy_url
    with pytest.raises(context.ProviderContextError, match="provider_proxy_invalid"):
        context.build_provider_environment({"USER": "synthetic-user"}, **arguments)


def test_proxy_rejects_unapproved_connect_target() -> None:
    with context.DirectConnectProxy() as proxy:
        worker = threading.Thread(target=proxy.serve_once)
        worker.start()
        host, port = context._parse_loopback_proxy(proxy.url)
        with socket.create_connection((host, port), timeout=2) as client:
            client.sendall(b"CONNECT example.invalid:443 HTTP/1.1\r\n\r\n")
            response = client.recv(4096)
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert response == b"HTTP/1.1 403 Forbidden\r\n\r\n"


@pytest.mark.parametrize(
    ("lease_profile", "lease_duration"),
    (("standard", "1h"), ("kimi-tb4-long", "12h")),
)
def test_supervisor_keeps_private_context_live_for_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lease_profile: str,
    lease_duration: str,
) -> None:
    result = tmp_path / "result.json"
    arguments = _arguments(tmp_path)
    monkeypatch.setenv("SLURM_TMPDIR", str(tmp_path))
    code = (
        "import json, os, runpy; from pathlib import Path; "
        f"module = runpy.run_path({str(Path(context.__file__))!r}); "
        "provider_context_is_active = module['provider_context_is_active']; "
        "active = provider_context_is_active(os.environ); "
        "os.environ['OCI_RUNNER_PULL_TIMEOUT'] = '1s'; "
        "payload = dict(active=active, drift_rejected=not provider_context_is_active(os.environ), "
        "environment=os.environ.get('OCI_RUNNER_ENVIRONMENT'), "
        "effective_network=os.environ.get('SANDOQ_EFFECTIVE_TASK_NETWORK'), "
        "task_network_present='OCI_RUNNER_TASK_NETWORK' in os.environ, "
        "lease_profile=os.environ.get('SANDOQ_LEASE_PROFILE'), "
        "lease_duration=os.environ.get('OCI_RUNNER_LEASE_DURATION'), "
        "renew_interval=os.environ.get('OCI_RUNNER_POOL_RENEW_INTERVAL'), "
        "managed_shell_recovery=os.environ.get('OCI_RUNNER_MANAGED_SHELL_RECOVERY'), "
        "proxy_equal=os.environ.get('HTTPS_PROXY') == os.environ.get('https_proxy')); "
        f"Path({str(result)!r}).write_text(json.dumps(payload))"
    )
    return_code = context.supervise(
        [sys.executable, "-c", code],
        cluster_identifier=str(arguments["cluster_identifier"]),
        transport_mode=str(arguments["transport_mode"]),
        concurrency=int(arguments["concurrency"]),
        lease_create_cap=int(arguments["lease_create_cap"]),
        startup_timeout_seconds=int(arguments["startup_timeout_seconds"]),
        lease_profile=lease_profile,
        provider_token_file=Path(arguments["provider_token_file"]),
        ecr_token_file=Path(arguments["ecr_token_file"]),
        ecr_token_metadata=Path(arguments["ecr_token_metadata"]),
        project_root=Path(arguments["project_root"]),
        sandoq_site=Path(arguments["sandoq_site"]),
    )

    assert return_code == 0
    assert json.loads(result.read_text()) == {
        "active": True,
        "drift_rejected": True,
        "environment": "oci-runner",
        "effective_network": "public",
        "lease_profile": lease_profile,
        "lease_duration": lease_duration,
        "renew_interval": "5m",
        "managed_shell_recovery": "1" if lease_profile == "kimi-tb4-long" else "0",
        "task_network_present": False,
        "proxy_equal": True,
    }
    assert not list(tmp_path.glob("sandoq-provider-context-*"))


def test_process_group_cleanup_reaches_descendants(tmp_path: Path) -> None:
    marker = tmp_path / "child-pid"
    prior_subreaper = context._set_child_subreaper(True)
    try:
        leader = subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                f"sleep 300 & printf '%s' $! > {marker}; wait",
            ],
            start_new_session=True,
        )
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        descendant = int(marker.read_text())

        assert context._terminate_group(leader, grace_seconds=1)
        with pytest.raises(ProcessLookupError):
            os.kill(descendant, 0)
    finally:
        context._set_child_subreaper(prior_subreaper)


def test_supervisor_sigterm_extinguishes_child_group(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-pid"
    profile = tmp_path / "profile.json"
    profile_body = context._canonical_json(
        {
            "schema_version": 1,
            "cluster_identifier": "synthetic_cluster",
            "transport_mode": "loopback",
            "effective_task_network": "public",
            "base_url": context.BASE_URL,
            "environment": context.ENVIRONMENT,
            "provider_token_file": str(tmp_path / "provider-token"),
        }
    )
    profile.write_bytes(profile_body)
    environment = dict(os.environ)
    environment["SLURM_TMPDIR"] = str(tmp_path)
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(context.__file__)),
            "supervise",
            "--profile",
            str(profile),
            "--profile-sha256",
            context._sha256(profile_body),
            "--concurrency",
            "64",
            "--lease-create-cap",
            "4",
            "--startup-timeout-seconds",
            "3600",
            "--ecr-token-file",
            str(tmp_path / "ecr-token"),
            "--ecr-token-metadata",
            str(tmp_path / "ecr-token.metadata.json"),
            "--project-root",
            str(tmp_path / "project"),
            "--sandoq-site",
            str(tmp_path / "site"),
            "--",
            "/bin/sh",
            "-c",
            f"sleep 300 & printf '%s' $! > {marker}; wait",
        ],
        env=environment,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()
    descendant = int(marker.read_text())
    process.terminate()
    assert process.wait(timeout=5) == 128 + signal.SIGTERM
    with pytest.raises(ProcessLookupError):
        os.kill(descendant, 0)
    assert not list(tmp_path.glob("sandoq-provider-context-*"))


def test_launchers_wrap_sandoq_in_one_full_lifetime_context() -> None:
    workflow = Path(__file__).parents[1]
    generic = (workflow / "run_eval.sbatch").read_text()
    direct = (workflow / "run_qwen_direct_eval.sbatch").read_text()
    direct_driver = (workflow / "run_direct_qwen_eval_driver.sh").read_text()

    for script in (generic, direct):
        assert "sandoq_provider_context.py" in script
        assert "SANDOQ_PROVIDER_CONTEXT_ACTIVE" in script
        assert "SANDOQ_PROVIDER_CONTEXT_RECEIPT" in script
        assert 'python3 "$provider_context" verify' in script
        assert 'python3 "$provider_context" supervise' in script
        assert "configs/provider_context/use2/qwen_sandoq.json" in script
        assert context._sha256((workflow / "configs/provider_context/use2/qwen_sandoq.json").read_bytes()) in script
        assert "--profile-sha256" in script
        assert "--lease-create-cap" in script
        assert "--startup-timeout-seconds 3600" in script
        assert "oci-runner-firecracker" not in script
        assert "firecracker-token" not in script
    assert direct.index('python3 "$provider_context" supervise') < direct.index("approved clean source closure")
    assert '--sandoq-lease-profile "$SANDOQ_LEASE_PROFILE"' in generic
    assert '--sandoq-lease-profile "$SANDOQ_LEASE_PROFILE"' in direct_driver
    assert '"$eval_run_role" == mobius' in generic
    assert '--lease-profile "$sandoq_lease_profile"' in generic
    assert "--lease-profile standard" in direct
    assert 'if [[ "$sandbox_provider" != sandoq ]]; then\n    unset HTTP_PROXY' in generic


def test_cluster_profiles_are_separate_and_canonical() -> None:
    root = Path(__file__).parents[1] / "configs/provider_context"
    use2_path = (root / "use2/qwen_sandoq.json").resolve()
    sc3_path = (root / "sc3/qwen_sandoq.json").resolve()
    firecracker_path = (root / "use2/kimi_sandoq_firecracker_no_network.json").resolve()
    use2 = context.load_provider_profile(use2_path, context._sha256(use2_path.read_bytes()))
    sc3 = context.load_provider_profile(sc3_path, context._sha256(sc3_path.read_bytes()))
    firecracker = context.load_provider_profile(
        firecracker_path,
        context._sha256(firecracker_path.read_bytes()),
    )

    assert use2.cluster_identifier == "use2"
    assert use2.transport_mode == "auto"
    assert sc3.cluster_identifier == "sc3"
    assert sc3.transport_mode == "loopback"
    assert firecracker.environment == "oci-runner-firecracker"
    assert firecracker.effective_task_network == "none"
    assert firecracker.task_network == "none"
    assert use2.sha256 != sc3.sha256
