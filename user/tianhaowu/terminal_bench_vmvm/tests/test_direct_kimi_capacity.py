from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import direct_kimi_capacity as capacity
import pytest
from direct_kimi_workers import _atomic_write


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _capacity_certificate(tmp_path: Path, *, queue_overflow_rejections: int = 0) -> tuple[Path, str]:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    artifact_names = {
        "results",
        "eval_run_identity",
        "config_source",
        "config_resolved",
        "task_file",
        "worker_manifest",
        "capacity_probe",
        "router_receipt",
        "cleanup_audit",
    }
    artifacts: dict[str, dict[str, str]] = {}
    for name in sorted(artifact_names):
        path = root / f"{name}.data"
        path.write_bytes(f"{name}\n".encode())
        path.chmod(0o600)
        artifacts[name] = _artifact(path)
    unsigned = {
        "schema_version": 1,
        "kind": "direct-kimi-sandoq-capacity",
        "state": "passed",
        "model": "Kimi-K3",
        "capacity_profile": "sandoq-c64-v1",
        "qualified_concurrency": 64,
        "endpoint_identifier": "cpu-132-021_8103",
        "eval_run_identity_sha256": "1" * 64,
        "worker_manifest_sha256": artifacts["worker_manifest"]["sha256"],
        "endpoint_bundle_sha256": "3" * 64,
        "source": {
            "prime_rl_commit": "4" * 40,
            "prime_rl_tree_sha256": "5" * 64,
            "router_implementation_sha256": "6" * 64,
            "sandoq_provider_commit": "7" * 40,
            "sandoq_provider_tree": "8" * 40,
        },
        "config": {
            "source_sha256": artifacts["config_source"]["sha256"],
            "resolved_sha256": artifacts["config_resolved"]["sha256"],
        },
        "selection": {
            "task_file_sha256": artifacts["task_file"]["sha256"],
            "task_count": 64,
            "agent_no_network_count": 64,
            "verifier_no_network_count": 64,
            "compose_task_count": 0,
            "selection_scope": "operator-approved-non-sensitive",
        },
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "retries": 0,
            "configured_capacity": 64,
            "max_active_requests": 64,
            "max_active_chat_requests": 64,
            "capacity_rejections": queue_overflow_rejections,
            "queue_overflow_rejections": queue_overflow_rejections,
            "route_tracking_overflows": 0,
            "cross_route_anomalies": 0,
            "tracked_sessions": 64,
        },
        "probe": {
            "rounds": 2,
            "client_parallelism": 64,
            "successful_requests": 128,
            "receipt_sha256": artifacts["capacity_probe"]["sha256"],
        },
        "sandoq": {
            "assignment_event_order_high_water": 64,
            "assignment_measured_high_water": 64,
            "outer_session_high_water": 64,
            "assignments_acquired": 64,
            "assignments_cleanup_verified": 64,
            "outer_sessions_deleted": 64,
            "cleanup_gateway_retry_count": 0,
            "gateway_close_warnings": 0,
            "recovered_poisoned_assignments": 0,
            "failures": 0,
            "cleanup_audit_sha256": artifacts["cleanup_audit"]["sha256"],
        },
        "traces": {
            "count": 64,
            "model_io_turns": 64,
            "sampled_tokens": 64,
            "trace_failures": 0,
            "global_problem_count": 0,
            "results_sha256": artifacts["results"]["sha256"],
        },
        "artifacts": artifacts,
    }
    certificate = {
        **unsigned,
        "capacity_certificate_payload_sha256": hashlib.sha256(capacity._canonical_json(unsigned)).hexdigest(),
    }
    output = root / capacity.CAPACITY_FILENAME
    _atomic_write(output, capacity._canonical_json(certificate) + b"\n", exclusive=True)
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def test_capacity_certificate_validator_accepts_exact_c64_evidence(tmp_path: Path) -> None:
    path, digest = _capacity_certificate(tmp_path)

    certificate = capacity.validate_capacity_certificate(
        path,
        expected_sha256=digest,
        required_concurrency=64,
        expected_endpoint_identifier="cpu-132-021_8103",
        expected_worker_manifest_sha256=hashlib.sha256(
            (tmp_path / "private/worker_manifest.data").read_bytes()
        ).hexdigest(),
        expected_config_sha256=hashlib.sha256((tmp_path / "private/config_source.data").read_bytes()).hexdigest(),
    )

    assert certificate["qualified_concurrency"] == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_capacity_certificate_validator_rejects_any_queue_overflow(tmp_path: Path) -> None:
    path, digest = _capacity_certificate(tmp_path, queue_overflow_rejections=1)

    with pytest.raises(capacity.DirectKimiCapacityError, match="capacity_certificate_not_qualified"):
        capacity.validate_capacity_certificate(path, expected_sha256=digest)


def test_materialize_capacity_config_keeps_selector_private_and_aggregate_only(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    selector_root = tmp_path / "selector"
    selector_root.mkdir(mode=0o700)
    selector = selector_root / "tasks.txt"
    names = [f"task-{index:02d}" for index in range(64)]
    selector.write_text("\n".join(names) + "\n")
    selector.chmod(0o600)
    for name in names:
        task = dataset / name
        (task / "environment").mkdir(parents=True)
        (task / "task.toml").write_text(
            '[environment]\nnetwork_mode = "no-network"\n'
            '[agent]\nnetwork_mode = "no-network"\n'
            '[verifier]\nnetwork_mode = "no-network"\n'
        )

    source_template = (
        Path(capacity.__file__).parent
        / "configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_sandoq_capacity64.example.toml"
    )
    template = tmp_path / "template.toml"
    template.write_text(
        source_template.read_text().replace(
            "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9",
            str(dataset),
        )
    )
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output = output_root / "capacity.toml"

    summary = capacity.materialize_config(template.resolve(), selector.resolve(), output.resolve())

    assert summary["task_count"] == 64
    assert summary["agent_no_network_count"] == 64
    assert summary["verifier_no_network_count"] == 64
    assert summary["compose_task_count"] == 0
    rendered = output.read_text()
    assert str(selector.resolve()) in rendered
    assert summary["task_file_sha256"] in rendered
    assert not names[0] in json.dumps(summary)
