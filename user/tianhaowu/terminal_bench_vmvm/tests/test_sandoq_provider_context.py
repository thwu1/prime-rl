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
def test_build_provider_environment_rejects_non_loopback_proxy(
    tmp_path: Path, proxy_url: str
) -> None:
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


def test_supervisor_keeps_private_context_live_for_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tmp_path / "result.json"
    arguments = _arguments(tmp_path)
    monkeypatch.setenv("SLURM_TMPDIR", str(tmp_path))
    code = (
        "import json, os; from pathlib import Path; "
        "from terminal_bench_vmvm.sandoq_provider_context import provider_context_is_active; "
        "active = provider_context_is_active(os.environ); "
        "os.environ['OCI_RUNNER_PULL_TIMEOUT'] = '1s'; "
        "payload = dict(active=active, drift_rejected=not provider_context_is_active(os.environ), "
        "environment=os.environ.get('OCI_RUNNER_ENVIRONMENT'), "
        "effective_network=os.environ.get('SANDOQ_EFFECTIVE_TASK_NETWORK'), "
        "task_network_present='OCI_RUNNER_TASK_NETWORK' in os.environ, "
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

    for script in (generic, direct):
        assert "sandoq_provider_context.py" in script
        assert "SANDOQ_PROVIDER_CONTEXT_ACTIVE" in script
        assert "SANDOQ_PROVIDER_CONTEXT_RECEIPT" in script
        assert 'python3 "$provider_context" verify' in script
        assert 'python3 "$provider_context" supervise' in script
        assert "configs/provider_context/use2/qwen_sandoq.json" in script
        assert context._sha256(
            (
                workflow / "configs/provider_context/use2/qwen_sandoq.json"
            ).read_bytes()
        ) in script
        assert "--profile-sha256" in script
        assert "--lease-create-cap" in script
        assert "--startup-timeout-seconds 3600" in script
        assert "oci-runner-firecracker" not in script
        assert "firecracker-token" not in script
    assert direct.index('python3 "$provider_context" supervise') < direct.index(
        "approved clean source closure"
    )
    assert 'if [[ "$sandbox_provider" != sandoq ]]; then\n    unset HTTP_PROXY' in generic


def test_cluster_profiles_are_separate_and_canonical() -> None:
    root = Path(__file__).parents[1] / "configs/provider_context"
    use2_path = (root / "use2/qwen_sandoq.json").resolve()
    sc3_path = (root / "sc3/qwen_sandoq.json").resolve()
    use2 = context.load_provider_profile(use2_path, context._sha256(use2_path.read_bytes()))
    sc3 = context.load_provider_profile(sc3_path, context._sha256(sc3_path.read_bytes()))

    assert use2.cluster_identifier == "use2"
    assert use2.transport_mode == "auto"
    assert sc3.cluster_identifier == "sc3"
    assert sc3.transport_mode == "loopback"
    assert use2.sha256 != sc3.sha256
