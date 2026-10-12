from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import tarfile
import tomllib
from pathlib import Path

import eval_run_identity
import finalize_kimi_tb4_sandoq_small_full as finalize
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_sandoq_small_full as small
import prepare_kimi_tb4_sandoq_small_v10_run as v10
import pytest


def _resource(*, gpu: int = 0) -> dict[str, int]:
    return {
        "cpu_count": 4,
        "memory_bytes": 8 * split.GIB,
        "disk_bytes": 20 * split.GIB,
        "gpu_count": gpu,
    }


def _manifest(monkeypatch: pytest.MonkeyPatch) -> tuple[bytes, bytes]:
    digest = "a" * 64
    entries = []
    for index in range(split.TOTAL_TASKS):
        gpu = index >= 63
        compose = 52 <= index < 63
        resources = _resource(gpu=int(gpu))
        entries.append(
            {
                "task_id": f"opaque-case-{index:02d}",
                "images": {
                    "agent": f"registry.example/agent@sha256:{digest}",
                    "verifier": f"registry.example/verifier@sha256:{digest}",
                },
                "agent_resources": resources,
                "verifier_resources": dict(resources),
                "verifier_mode": "shared",
                "runtime_requirements": {"compose": compose},
            }
        )
    selector_body = ("\n".join(entry["task_id"] for entry in entries) + "\n").encode()
    image_body = split.canonical_json(
        {
            "images": {entry["task_id"]: entry["images"] for entry in entries},
            "schema_version": 1,
            "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
        }
    )
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_body).hexdigest())
    value = {
        "schema_version": split.MANIFEST_SCHEMA_VERSION,
        "kind": split.MANIFEST_KIND,
        "source": {
            "dataset_archive_sha256": split.CANONICAL_DATASET_ARCHIVE_SHA256,
            "dataset_content_sha256": split.CANONICAL_DATASET_CONTENT_SHA256,
            "image_manifest_sha256": hashlib.sha256(image_body).hexdigest(),
            "task_file_sha256": hashlib.sha256(selector_body).hexdigest(),
        },
        "entries": entries,
    }
    return split.canonical_json(value), image_body


def test_materialized_small_plan_preserves_full_generation_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    # Validate and retain the sealed base before this synthetic manifest replaces
    # the repository image-manifest digest for the rest of the test.
    sealed_base = small._load_base()
    manifest_body, image_body = _manifest(monkeypatch)
    monkeypatch.setattr(small, "_load_base", lambda held=None: sealed_base)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(manifest_body)
    manifest.chmod(0o600)
    image_manifest = tmp_path / "images.json"
    image_manifest.write_bytes(image_body)
    dataset = tmp_path / "dataset"
    dataset.mkdir(mode=0o700)
    eval_root = tmp_path / "evals"
    eval_root.mkdir(mode=0o700)
    smoke = tmp_path / "smoke.json"
    smoke.write_bytes(
        split.canonical_json(
            {
                "cleanup": True,
                "deployment": {
                    "endpoint_bundle_sha256": small.STOCK_ENDPOINT_BUNDLE_SHA256,
                    "kind": "direct-kimi-smoke-binding",
                    "router": {
                        "capacity_profile": "sandoq-stock-single-c64-v1",
                        "endpoint_identifier": small.STOCK_ENDPOINT_IDENTIFIER,
                        "per_worker_capacity": 64,
                        "worker_count": 1,
                    },
                    "slurm_job_id": "1605262",
                    "source_proxy_config_sha256": small.STOCK_SOURCE_PROXY_SHA256,
                    "source_revision": small.STOCK_SMOKE_SOURCE_REVISION,
                    "source_spec_sha256": small.STOCK_SOURCE_SPEC_SHA256,
                    "worker_manifest_sha256": "b" * 64,
                },
                "harness_version": "2.4.6",
                "kind": "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic",
                "model_calls": 3,
                "reasoning_content_retained": True,
                "router_healthy": True,
                "router_w2_profile_configured": True,
                "sandbox_environment": "oci-runner-firecracker-small",
                "sandbox_lifecycle": True,
                "schema_version": 3,
                "shell_execution": True,
                "status": "diagnostic_passed",
                "sticky_routing": True,
                "task_count": 1,
                "transport": {
                    "schema_version": 1,
                    "kind": "sandoq-buffered-chat-logical-exact-once",
                    "summary_record": {"bytes": 100, "sha256": "a" * 64},
                    "summary": {
                        "schema_version": 1,
                        "source_schema": "logical-exact-once-v1",
                        "summary_records": 1,
                        "exact_once_counters_required": True,
                        "integer_totals": {
                            "requests": 3,
                            "upstream_attempts": 3,
                            "logical_requests": 3,
                            "logical_upstream_attempts": 3,
                            "streamed_requests": 3,
                            "anonymous_upstream_attempts": 0,
                            "coalesced_requests": 0,
                            "replayed_requests": 0,
                            "expired_logical_retries": 0,
                            "downstream_disconnects": 0,
                            "conflicting_requests": 0,
                            "inflight": 0,
                            "error_count": 0,
                            "unknown_path_requests": 0,
                        },
                    },
                },
            }
        )
    )
    smoke.chmod(0o600)
    smoke_sha256 = hashlib.sha256(smoke.read_bytes()).hexdigest()
    monkeypatch.setattr(small, "SMOKE_RECEIPT_SHA256", smoke_sha256)
    smoke_format = tmp_path / "smoke-format.json"
    smoke_format.write_bytes(
        split.canonical_json(
            {
                "capture": {
                    "canonical_trajectory_field": "reasoning_content",
                    "model_calls": 3,
                    "nonstream_provider_requests": 3,
                    "raw_provider_field": "reasoning",
                    "reasoning_exact_parity": 3,
                    "reasoning_nonblank": 3,
                    "request_digest_set_sha256": small.SMOKE_REQUEST_DIGEST_SET_SHA256,
                    "response_digest_set_sha256": small.SMOKE_RESPONSE_DIGEST_SET_SHA256,
                    "response_kind": "exact_provider_json",
                    "tool_call_exact_semantic_parity": 3,
                    "tool_call_turns": 3,
                    "tool_calls_total": 3,
                },
                "kind": "kimi-tb4-miniswe246-sandoq-firecracker-small-smoke-format",
                "schema_version": 3,
                "source": {
                    "raw_trace": {
                        "bytes": 100,
                        "path": "/private/raw-trace.json",
                        "sha256": small.SMOKE_RAW_TRACE_SHA256,
                    },
                    "receipt": {
                        "bytes": len(smoke.read_bytes()),
                        "path": str(smoke),
                        "sha256": smoke_sha256,
                    },
                    "slurm_job_id": "1605262",
                    "source_revision": small.STOCK_FORMAT_SOURCE_REVISION,
                },
                "state": "passed",
            }
        )
    )
    smoke_format.chmod(0o600)
    smoke_format_sha256 = hashlib.sha256(smoke_format.read_bytes()).hexdigest()
    monkeypatch.setattr(small, "SMOKE_FORMAT_ATTESTATION_SHA256", smoke_format_sha256)
    capacity = tmp_path / "capacity.json"
    capacity.write_bytes(
        split.canonical_json(
            {
                "artifacts": {
                    "endpoint_file": {"path": "/private/endpoint.json", "sha256": "3daa2941e88bee4d0435d50687c6f0f95104df119cff1c361263d2053e2a61ae"},
                    "proxy_config": {"path": "/private/proxy.yaml", "sha256": small.STOCK_SOURCE_PROXY_SHA256},
                    "spec": {"path": "/private/spec.yaml", "sha256": small.STOCK_SOURCE_SPEC_SHA256},
                },
                "completions": {
                    "attempted": 64,
                    "http_200": 64,
                    "model_matches": 64,
                    "raw_reasoning_present": 64,
                    "reasoning_content_present": 0,
                    "reasoning_present": 64,
                    "requested": 64,
                    "response_digests_sha256": "c" * 64,
                    "response_errors": 0,
                    "successful": 64,
                    "tool_call_responses": 64,
                    "tool_calls_total": 64,
                    "transport_errors": 0,
                },
                "concurrency": {"client_peak_in_flight": 64, "configured": 64},
                "deployment": {
                    "endpoint_authority_sha256": "510d02d82e3d16f34d69241845275af0b21a48875bc6a0e8ea92129ee88aeb43",
                    "endpoint_job_id": "1593665",
                    "id": small.STOCK_ENDPOINT_IDENTIFIER,
                    "model": "Kimi-K3",
                },
                "endpoint_unchanged": True,
                "kind": "kimi-stock-capacity-probe",
                "metrics": {
                    "in_flight": {
                        "maximum_running": 64,
                        "maximum_waiting": 0,
                        "response_errors": 0,
                        "transport_errors": 0,
                    }
                },
                "model_identity": {
                    "backend_model": "openai/Kimi-K3",
                    "confirmed": True,
                    "response_errors": 0,
                    "served_model": "Kimi-K3",
                    "transport_errors": 0,
                },
                "schema_version": 1,
                "state": "passed",
            }
        )
    )
    capacity.chmod(0o600)
    capacity_sha256 = hashlib.sha256(capacity.read_bytes()).hexdigest()
    monkeypatch.setattr(small, "CAPACITY_RECEIPT_SHA256", capacity_sha256)
    soak = tmp_path / "soak.json"
    soak.write_bytes(
        split.canonical_json(
            {
                "cleanup_failures": 0,
                "client_close_verified": True,
                "create_attempts": 24,
                "create_failure_counts": {"connection_failure": 0, "session_failure": 0},
                "delete_attempts": 24,
                "environment": "oci-runner-firecracker-small",
                "kind": "sandoq-firecracker-small-c24-soak",
                "mtls_available": True,
                "profile_sha256": small.PROVIDER_PROFILE_SHA256,
                "requested_concurrency": 24,
                "schema_version": 1,
                "sessions_returned": 24,
                "simultaneous_ready_verified": 24,
                "state": "passed",
                "transport_mode": "proxy",
                "typed_404_verified": 24,
            }
        )
    )
    soak.chmod(0o600)
    soak_sha256 = hashlib.sha256(soak.read_bytes()).hexdigest()
    monkeypatch.setattr(small, "SANDOQ_SOAK_RECEIPT_SHA256", soak_sha256)
    output = tmp_path / "plan"
    args = argparse.Namespace(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_body).hexdigest(),
        image_manifest=image_manifest,
        dataset_dir=dataset,
        output=output,
        eval_root=eval_root,
        run_label="test",
        smoke_receipt=smoke,
        smoke_receipt_sha256=smoke_sha256,
        smoke_format_attestation=smoke_format,
        smoke_format_attestation_sha256=smoke_format_sha256,
        capacity_receipt=capacity,
        capacity_receipt_sha256=capacity_sha256,
        sandoq_soak_receipt=soak,
        sandoq_soak_receipt_sha256=soak_sha256,
    )

    result = small.materialize(args)
    verified = small.verify(output / small.PLAN, result["plan_sha256"])
    config = tomllib.loads((output / small.CONFIG).read_text())

    assert result == {
        "state": "materialized",
        "executed_tasks": 52,
        "unsupported_tasks": 14,
        "denominator": 66,
        "concurrency": 24,
        "certification_eligible": False,
        "plan_sha256": result["plan_sha256"],
    }
    assert verified["count"] == 52
    assert verified["concurrency"] == 24
    assert Path(verified["full_output_dir"]).parent == Path(verified["output_dir"])
    assert config["max_turns"] == 200
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["max_total_tokens"] == 262_144
    assert config["client"]["max_retries"] == 0
    assert config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "10"
    assert config["harness"]["runtime"]["expected_environment"] == "oci-runner-firecracker-small"
    assert config["taskset"]["resource_cpu_cap"] == 1
    assert config["taskset"]["resource_memory_mb_cap"] == 2_048
    assert config["taskset"]["verifier_runtime_retries"] == 2
    assert config["taskset"]["retry_shared_verifier_scoring"] is True
    assert config["harness"]["runtime"]["provisioning_retries"] == 8
    assert b"opaque-case" not in json.dumps(result, sort_keys=True).encode()
    plan = json.loads((output / small.PLAN).read_bytes())
    assert plan["contracts"]["model_io_response_kind"] == "exact_provider_json"
    assert plan["contracts"]["model_retries"] == 0
    assert plan["contracts"]["zero_model_resume_attempts"] == 0
    assert plan["contracts"]["guest_transport_retry_attempts"] == 10
    assert plan["contracts"]["logical_request_upstream_attempts"] == 1
    assert plan["contracts"]["buffered_proxy_summary_schema"] == "logical-exact-once-v1"
    assert plan["contracts"]["buffered_proxy_summary_records"] == 52
    assert plan["contracts"]["audit_error_model_io"] is True
    assert plan["contracts"]["router_terminal_status_binding_required"] is True
    assert plan["contracts"]["terminal_proxy_exceptions_allowed"] is False
    assert plan["contracts"]["shell_command_timeout_seconds"] == 3_600
    assert plan["contracts"]["verifier_runtime_retries"] == 2
    assert plan["contracts"]["retry_shared_verifier_scoring"] is True
    assert plan["contracts"]["provisioning_retries"] == 8
    assert plan["contracts"]["reasoning_message_parity_required"] is True

    original_verify = small.verify
    replacement = tmp_path / "replacement-plan.json"
    replacement.write_bytes(b"{}\n")
    replacement.chmod(0o600)

    def verify_then_swap(path: Path, expected_sha256: str, **kwargs) -> dict[str, object]:
        value = original_verify(path, expected_sha256, **kwargs)
        os.replace(replacement, path)
        return value

    monkeypatch.setattr(finalize.plan_module, "verify", verify_then_swap)
    held = split._HeldArtifactSet.create()
    try:
        loaded, reverified = finalize._verified_plan(
            output / small.PLAN,
            result["plan_sha256"],
            held,
        )
        assert loaded == plan
        assert reverified == verified
        with pytest.raises(split.KimiProviderSplitError, match="provider_artifact_changed"):
            held.revalidate()
    finally:
        held.close()


def test_unsupported_rows_are_deterministic_explicit_zeroes() -> None:
    first = finalize._unsupported_row("opaque-case", "a" * 64, "compose")
    second = finalize._unsupported_row("opaque-case", "a" * 64, "compose")

    assert first == second
    assert first["rewards"] == {"solved": 0}
    assert first["stop_condition"] == "unsupported"
    assert first["nodes"] == []


def test_identity_validator_seals_small_full_contract() -> None:
    explicit, _body, _path = small._load_base()
    config = eval_run_identity._resolved_config_data(
        eval_run_identity.EvalConfig.model_validate(explicit),
        explicit=explicit,
    )

    assert eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE != "kimi-direct-tb4-diagnostic"

    assert (
        eval_run_identity._direct_kimi_expected_concurrency(
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
            "sandoq",
            52,
            24,
        )
        == 24
    )
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_scope_invalid"):
        eval_run_identity._direct_kimi_expected_concurrency(
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
            "sandoq",
            51,
            24,
        )

    eval_run_identity._validate_direct_kimi_tb4_small_config(
        config,
        eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
    )
    contract, _execution = eval_run_identity._contract(
        config,
        "Kimi-K3",
        role=eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        sandbox_provider="sandoq",
    )
    assert contract["harness"]["request_max_retries"] == 0
    assert contract["harness"]["guest_transport_retry_attempts"] == 10
    assert contract["harness"]["logical_request_upstream_attempts"] == 1
    invalid_cpu = copy.deepcopy(config)
    invalid_cpu["harness"]["runtime"]["cpu"] = 2.0
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            invalid_cpu,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )
    unknown_runtime_field = copy.deepcopy(config)
    unknown_runtime_field["harness"]["runtime"]["unexpected"] = "forbidden"
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            unknown_runtime_field,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )
    config["sampling"]["max_tokens"] = 512
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            config,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )
    explicit, _body, _path = small._load_base()
    config = eval_run_identity._resolved_config_data(
        eval_run_identity.EvalConfig.model_validate(explicit),
        explicit=explicit,
    )
    config["harness"]["runtime"]["expected_environment"] = "oci-runner"
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            config,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )


def test_launchers_bind_small_diagnostic_and_zero_model_only_resume() -> None:
    workflow = Path(small.__file__).resolve().parent
    wrapper = (workflow / "run_kimi_tb4_miniswe246_sandoq_small_full.sbatch").read_text()
    launcher = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()
    stage = (workflow / "run_direct_kimi_sandoq_stage.sh").read_text()
    stock_wrapper = (workflow / "run_kimi_tb4_miniswe246_sandoq_stock_single_full.sbatch").read_text()

    assert "tb4-miniswe246-sandoq-small-full" in wrapper
    assert "small-firecracker-diagnostic" in wrapper
    assert "#SBATCH --time=6-00:00:00" in wrapper
    assert "minimum_job_remaining_seconds=475200" in wrapper
    assert "job_end_epoch" in wrapper
    assert "#SBATCH --time=6-00:00:00" in stock_wrapper
    assert "DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=0" in launcher
    assert "prepare_kimi_tb4_sandoq_small_full.py" in launcher
    assert "finalize_kimi_tb4_sandoq_small_v7.py" in launcher
    assert launcher.index("setsid \"$x86_uv\"") < launcher.index("finalize_kimi_tb4_sandoq_small_v7.py")
    assert launcher.index("direct_kimi_router_final.json") < launcher.rindex(
        "finalize_kimi_tb4_sandoq_small_v7.py"
    )
    assert "prepare_kimi_tb4_sandoq_small_full.py" in stage
    assert "kimi-tb4-miniswe246-sandoq-small-diagnostic-v2" in stage
    assert "kimi-tb4-miniswe246-sandoq-small-diagnostic-v1" not in stage
    assert 'if [[ "$role" == kimi-direct-tb4-small-diagnostic ]]' in stage
    assert "zero_model_resume_forbidden" in stage
    assert 'export SANDOQ_BUFFERED_STATS_DIR="$buffered_stats_dir"' in stage
    assert (
        "approved_verifiers_revision=" + small.VERIFIERS_COMMIT
    ) in stage


def test_small_full_wrapper_reports_insufficient_walltime(tmp_path: Path) -> None:
    workflow = Path(small.__file__).resolve().parent
    wrapper = workflow / "run_kimi_tb4_miniswe246_sandoq_small_full.sbatch"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    squeue = fake_bin / "squeue"
    squeue.write_text("#!/bin/sh\nprintf '%s\\n' '01:00:00|6-00:00:00|2099-01-01T00:00:00'\n")
    squeue.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION": "1" * 40,
            "KIMI_TB4_SANDOQ_SMALL_PLAN": "/private/plan.json",
            "KIMI_TB4_SANDOQ_SMALL_PLAN_SHA256": "2" * 64,
            "KIMI_SMALL_DEPLOYMENT_ROOT": "/private/deployment",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "PROJECT_DIR": str(workflow.parents[2]),
            "SLURM_JOB_ID": "123",
        }
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", str(wrapper)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"code": "job_walltime_insufficient", "state": "blocked"}


def test_v10_c16_config_and_launch_path_are_separate_and_fail_closed() -> None:
    config, _body, _path = v10._load_base()
    workflow = Path(v10.__file__).resolve().parent
    wrapper = (workflow / "run_kimi_tb4_miniswe246_sandoq_small_v10_c16.sbatch").read_text()
    launcher = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()
    stage = (workflow / "run_direct_kimi_sandoq_stage.sh").read_text()

    assert config["max_concurrent"] == 16
    assert config["multiplex"] == 16
    assert config["client"]["max_connections"] == 16
    assert config["client"]["max_keepalive_connections"] == 16
    assert config["taskset"]["persist_verifier_artifacts"] is True
    assert config["harness"]["version"] == "2.4.6"
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["max_total_tokens"] == 262_144
    assert "#SBATCH --time=6-12:00:00" in wrapper
    assert "terminal-bench-sandoq-campaign.lock" in wrapper
    assert "sandoq_activity_check_unavailable" in wrapper
    assert "'%A|%j|%o'" in wrapper
    assert 'case "${active_job_name}|${active_command}"' in wrapper
    assert "KIMI_TB4_V10_NO_CONCURRENT_SANDOQ_LOAD" in wrapper
    assert "--stock-capacity-receipt" in launcher
    assert "--stock-capacity-receipt-sha256" in launcher
    assert "endpoint_minimum_remaining_seconds=583200" in launcher
    assert "prepare_kimi_tb4_sandoq_small_v10_run.py" in launcher
    assert "tb4-extended-c16-stock-single-four-wave-v1" in stage
    assert "small-firecracker-v10" in stage
    certify = launcher.index('python3 "$workflow_dir/direct_kimi_workers.py" certify-router')
    completion = launcher.index("completed-awaiting-v11-certification")
    legacy_finalize = launcher.index("finalize_kimi_tb4_sandoq_small_v7.py")
    assert certify < completion < legacy_finalize


def test_v10_dataset_binding_checks_exact_archive_and_live_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "dataset"
    member = dataset / "synthetic-case"
    member.mkdir(parents=True)
    payload = member / "instruction.md"
    payload.write_text("synthetic\n")
    archive = tmp_path / "dataset.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(dataset, arcname="tasks")

    archive_body = archive.read_bytes()
    content_sha256 = eval_run_identity._tree_digest(dataset)
    monkeypatch.setattr(v10, "CANONICAL_DATASET_ARCHIVE", archive)
    monkeypatch.setattr(
        split,
        "CANONICAL_DATASET_ARCHIVE_SHA256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(split, "CANONICAL_DATASET_CONTENT_SHA256", content_sha256)

    assert v10._validated_dataset(dataset) == dataset

    payload.write_text("tampered\n")
    with pytest.raises(v10.V10PlanError, match="dataset_content_invalid"):
        v10._validated_dataset(dataset)

    with tarfile.open(archive, "w:gz") as handle:
        handle.add(dataset, arcname="tasks")
    monkeypatch.setattr(
        split,
        "CANONICAL_DATASET_ARCHIVE_SHA256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    with pytest.raises(v10.V10PlanError, match="dataset_archive_invalid"):
        v10._validated_dataset(dataset)

    payload.write_text("synthetic\n")
    archive.write_bytes(archive_body)
    monkeypatch.setattr(
        split,
        "CANONICAL_DATASET_ARCHIVE_SHA256",
        hashlib.sha256(archive_body).hexdigest(),
    )
    symlink = tmp_path / "dataset-link"
    symlink.symlink_to(dataset, target_is_directory=True)
    with pytest.raises(v10.V10PlanError, match="dataset_content_invalid"):
        v10._validated_dataset(symlink)
