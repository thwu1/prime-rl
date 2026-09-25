from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import tomllib
from pathlib import Path

import pytest
import qwen_miniswe246_sandoq_smoke as smoke
from terminal_bench_vmvm import sandoq_provider_context as context
from verifiers.v1.runtimes import SandoqConfig, SandoqRuntime


def test_content_blind_selector_writes_one_private_approved_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    slug = "approved-task"
    approved = tmp_path / "approved.txt"
    approved.write_text(f"{slug}\nsecond-task\n")
    dataset = tmp_path / "dataset"
    task_dir = dataset / slug
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        """
[task]
name = "opaque"
keywords = ["software"]
[metadata]
category = "engineering"
tags = ["debugging"]
[environment]
network_mode = "no-network"
[verifier]
network_mode = "no-network"
""".lstrip()
    )
    monkeypatch.setattr(smoke, "APPROVED_TASK_FILE_SHA256", smoke.sha256_file(approved))
    monkeypatch.setattr(
        smoke,
        "SELECTED_LINE_SHA256",
        hashlib.sha256(f"{slug}\n".encode()).hexdigest(),
    )
    destination = tmp_path / "selection.txt"

    digest = smoke.materialize_selector(approved, dataset, destination)

    assert digest == hashlib.sha256(f"{slug}\n".encode()).hexdigest()
    assert destination.read_text() == f"{slug}\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_content_blind_selector_rejects_security_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    slug = "approved-task"
    approved = tmp_path / "approved.txt"
    approved.write_text(f"{slug}\n")
    task_dir = tmp_path / "dataset" / slug
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        """
[metadata]
category = "security"
[environment]
network_mode = "no-network"
[verifier]
network_mode = "no-network"
""".lstrip()
    )
    monkeypatch.setattr(smoke, "APPROVED_TASK_FILE_SHA256", smoke.sha256_file(approved))
    monkeypatch.setattr(
        smoke,
        "SELECTED_LINE_SHA256",
        hashlib.sha256(f"{slug}\n".encode()).hexdigest(),
    )

    with pytest.raises(smoke.SmokeError, match="content_blind_selection_invalid"):
        smoke.materialize_selector(approved, tmp_path / "dataset", tmp_path / "selection.txt")


def test_trajectory_audit_requires_exact_native_marker() -> None:
    trajectory = {
        "info": {
            "mini_version": "2.4.6",
            "exit_status": "Submitted",
            "model_stats": {"api_calls": 2},
        },
        "messages": [
            {
                "role": "assistant",
                "reasoning_content": "reasoning retained",
                "extra": {"actions": [{"command": "printf first", "tool_call_id": "call-1"}]},
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "done",
                "extra": {"returncode": 0},
            },
            {
                "role": "assistant",
                "reasoning_content": "reasoning retained",
                "extra": {"actions": [{"command": smoke.MARKER_COMMAND, "tool_call_id": "call-2"}]},
            },
            {
                "role": "tool",
                "tool_call_id": "call-2",
                "content": "done",
                "extra": {"returncode": 0},
            },
        ],
    }

    audit = smoke.trajectory_audit(smoke.canonical_json(trajectory), 2)

    assert audit == {
        "model_calls": 2,
        "api_calls_match": True,
        "mini_version_match": True,
        "submitted": True,
        "shell_execution": True,
        "exact_native_submission_marker": True,
        "trajectory_reasoning_retained": True,
    }
    trajectory["messages"][2]["extra"]["actions"][0]["command"] += " "
    assert smoke.trajectory_audit(smoke.canonical_json(trajectory), 2)["exact_native_submission_marker"] is False


def test_public_receipt_separates_infrastructure_from_submission_gate() -> None:
    state = smoke.failed_run_state() | {
        "sandbox_lifecycle": True,
        "model_calls": 3,
        "shell_execution": True,
        "reasoning_content_retained": True,
        "reward": 1.0,
        "program_exit_ok": True,
        "api_calls_match": True,
        "mini_version_match": True,
    }

    assert smoke.public_receipt(state, True)["status"] == "infrastructure_only"
    state["exact_native_submission_marker"] = True
    receipt = smoke.public_receipt(state, True)
    assert receipt["status"] == "strict_passed"
    assert set(receipt) == {
        "schema_version",
        "kind",
        "sandbox_lifecycle",
        "model_calls",
        "shell_execution",
        "exact_native_submission_marker",
        "reasoning_content_retained",
        "reward",
        "status",
        "cleanup",
    }


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [([0, 124, 0], 0), ([0, 124, 2], 2), ([2, 0, 0], 2)],
)
def test_supervised_command_uses_authoritative_cleanup_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    expected: int,
) -> None:
    calls: list[list[str]] = []

    def run_logged(command: list[str], _log: Path, _timeout: float) -> int:
        calls.append(command)
        return statuses[len(calls) - 1]

    monkeypatch.setattr(smoke, "_run_logged", run_logged)
    args = argparse.Namespace(
        selector=tmp_path / "selector",
        selector_sha256="0" * 64,
        dataset_dir=tmp_path / "dataset",
        image_manifest=tmp_path / "images.json",
        proxy_info=tmp_path / "proxy.json",
        deployment_spec=tmp_path / "spec.yaml",
        output_dir=tmp_path / "output",
        workflow_dir=tmp_path / "workflow",
        log=tmp_path / "execution.log",
        drain_marker=tmp_path / "pool.drained.json",
    )

    assert smoke.supervised_command(args) == expected
    assert len(calls) == 3
    assert calls[2][1].endswith("sanitize_sandoq_cleanup_audit.py")


def test_firecracker_host_profile_and_smoke_are_narrowly_pinned(tmp_path: Path) -> None:
    workflow = Path(__file__).parents[1]
    profile_path = (workflow / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json").resolve()
    profile = context.load_provider_profile(profile_path, smoke.PROVIDER_PROFILE_SHA256)
    arguments = {
        "cluster_identifier": profile.cluster_identifier,
        "transport_mode": profile.transport_mode,
        "proxy_url": None,
        "concurrency": 1,
        "lease_create_cap": 1,
        "startup_timeout_seconds": 3600,
        "provider_token_file": profile.provider_token_file,
        "ecr_token_file": tmp_path / "ecr-token",
        "ecr_token_metadata": tmp_path / "ecr-token.metadata.json",
        "project_root": tmp_path / "project",
        "sandoq_site": tmp_path / "site",
        "provider_environment": profile.environment,
        "effective_task_network": profile.effective_task_network,
        "task_network": profile.task_network,
        "provider_profile_sha256": profile.sha256,
    }
    environment = context.build_provider_environment(
        {"USER": "synthetic-user"},
        **arguments,
    )
    runtime = SandoqRuntime(
        SandoqConfig(
            host_tunnel="sandoq",
            network_access=True,
            expected_environment=profile.environment,
            tunnel_pool_size=4,
            tunnel_ready_timeout=30,
            ecr_token_file=Path("/storage/home/tianhaowu/.config/oci-runner/ecr-token"),
        )
    )

    assert profile.environment == context.FIRECRACKER_TUNNEL_ENVIRONMENT
    assert environment["OCI_RUNNER_TASK_NETWORK"] == "host"
    assert environment["SANDOQ_EFFECTIVE_TASK_NETWORK"] == "public"
    assert environment["OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK"] == "0"
    assert environment["OCI_RUNNER_PULL_TIMEOUT"] == "1200s"
    assert environment["OCI_RUNNER_PULL_POLL_MAX_ERRORS"] == "10"
    assert runtime.config.host_tunnel == "sandoq"

    config_path = workflow / "configs/eval/qwen_miniswe246_sandoq_firecracker_smoke.toml"
    assert smoke.sha256_file(config_path) == smoke.EVAL_CONFIG_SHA256
    config = tomllib.loads(config_path.read_text())
    assert config["harness"]["version"] == "2.4.6"
    assert "agent.step_limit=3" in config["harness"]["config_overrides"]
    assert config["harness"]["runtime"]["host_tunnel"] == "sandoq"
    assert config["harness"]["runtime"]["expected_environment"] == profile.environment
    assert config["max_turns"] == 3
    assert config["retries"]["rollout"]["max_retries"] == 0

    batch = (workflow / "run_qwen_miniswe246_sandoq_smoke.sbatch").read_text()
    assert "#SBATCH --time=00:05:00" in batch
    assert "sandoq_x86_64_ram_prime_f7313db4" in batch
    assert (
        "ecr_token_metadata=${OCI_RUNNER_ECR_TOKEN_METADATA_PATH:-"
        "/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json}"
    ) in batch
    assert '--ecr-token-file "$ecr_token_file"' in batch
    assert '--ecr-token-metadata "$ecr_token_metadata"' in batch
    assert "proxy_info.json" not in batch
    assert "sbatch " not in batch

    args = smoke.parser().parse_args(
        [
            "orchestrate",
            "--project-root",
            str(tmp_path / "project"),
            "--expected-revision",
            "0" * 40,
        ]
    )
    assert args.ecr_token_file == Path("/storage/home/tianhaowu/.config/oci-runner/ecr-token")
    assert args.ecr_token_metadata == Path("/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json")


def test_firecracker_host_profile_is_active_under_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    workflow = Path(__file__).parents[1]
    profile_path = (workflow / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json").resolve()
    profile = context.load_provider_profile(profile_path, smoke.PROVIDER_PROFILE_SHA256)
    result = tmp_path / "result.json"
    snapshot = tmp_path / "sandoq-provider-context.json"
    monkeypatch.setenv("SLURM_TMPDIR", str(tmp_path))
    code = (
        "import json, os; from pathlib import Path; "
        "from terminal_bench_vmvm.sandoq_provider_context import "
        "provider_context_is_active, snapshot_provider_context; "
        f"snapshot=snapshot_provider_context(os.environ, Path({str(snapshot)!r})); "
        "payload={'active':provider_context_is_active(os.environ), "
        "'environment':os.environ.get('OCI_RUNNER_ENVIRONMENT'), "
        "'task_network':os.environ.get('OCI_RUNNER_TASK_NETWORK'), "
        "'fallback':os.environ.get('OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK'), "
        "'pull_timeout':os.environ.get('OCI_RUNNER_PULL_TIMEOUT'), "
        "'network_access':snapshot['network_access']}; "
        f"Path({str(result)!r}).write_text(json.dumps(payload))"
    )

    return_code = context.supervise(
        [sys.executable, "-c", code],
        cluster_identifier=profile.cluster_identifier,
        transport_mode=profile.transport_mode,
        concurrency=1,
        lease_create_cap=1,
        startup_timeout_seconds=3600,
        provider_token_file=profile.provider_token_file,
        ecr_token_file=(tmp_path / "ecr-token").resolve(),
        ecr_token_metadata=(tmp_path / "ecr-token.metadata.json").resolve(),
        project_root=(tmp_path / "project").resolve(),
        sandoq_site=(tmp_path / "site").resolve(),
        provider_environment=profile.environment,
        effective_task_network=profile.effective_task_network,
        task_network=profile.task_network,
        provider_profile_sha256=profile.sha256,
    )

    assert return_code == 0
    assert json.loads(result.read_text()) == {
        "active": True,
        "environment": "oci-runner-firecracker-small",
        "fallback": "0",
        "network_access": True,
        "pull_timeout": "1200s",
        "task_network": "host",
    }
