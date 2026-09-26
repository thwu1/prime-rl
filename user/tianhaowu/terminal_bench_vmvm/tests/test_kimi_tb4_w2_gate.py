from __future__ import annotations

import hashlib
import json
from pathlib import Path

import kimi_tb4_w2_gate as gate
import pytest


def _task(dataset: Path, name: str, category: str) -> None:
    root = dataset / name
    root.mkdir()
    (root / "task.toml").write_text(f'[metadata]\ncategory = "{category}"\n')


def test_launch_gate_binds_capacity_sdk_and_emits_aggregate_security_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "tasks"
    dataset.mkdir()
    _task(dataset, "ordinary-task", "systems")
    _task(dataset, "opaque-task", "security")
    selector = tmp_path / "selector.txt"
    selector.write_text("ordinary-task\nopaque-task\n")
    manifest_path = tmp_path / "manifest.json"
    manifest_body = b'{"opaque":"manifest"}\n'
    manifest_path.write_bytes(manifest_body)
    identity_path = tmp_path / "identity.json"
    identity_path.write_text("{}\n")
    revision = "a" * 40
    implementation_sha256 = "b" * 64
    bundle_sha256 = "c" * 64
    manifest = {
        "schema_version": 3,
        "endpoint_bundle_sha256": bundle_sha256,
        "workers": [{} for _ in range(gate.WORKER_COUNT)],
        "router": {
            "capacity_profile": gate.CAPACITY_PROFILE,
            "endpoint_identifier": gate.ENDPOINT_IDENTIFIER,
            "max_concurrent_requests": gate.ROUTER_ADMISSION,
            "per_worker_capacity": gate.PER_WORKER_CAPACITY,
            "implementation_sha256": implementation_sha256,
        },
    }
    certificate = {
        "qualification_scope": "routing-runtime-capacity-only",
        "source": {
            "prime_rl_commit": revision,
            "router_implementation_sha256": implementation_sha256,
        },
        "endpoint_bundle_sha256": bundle_sha256,
        "artifacts": {"eval_run_identity": {"path": str(identity_path), "sha256": "d" * 64}},
    }
    capacity_calls: list[dict[str, object]] = []

    def validate_capacity(*_args, **kwargs):
        capacity_calls.append(kwargs)
        return certificate

    monkeypatch.setattr(gate, "TASK_COUNT", 2)
    monkeypatch.setattr(gate, "SANDOQ_LANE_TASK_COUNT", 2)
    monkeypatch.setattr(gate, "SECURITY_LABELLED_TASK_COUNT", 1)
    monkeypatch.setattr(gate, "OFFICIAL_SELECTOR_SHA256", hashlib.sha256(selector.read_bytes()).hexdigest())
    monkeypatch.setattr(gate, "_validate_sdk_site", lambda _site: None)
    monkeypatch.setattr(gate, "validate_capacity_certificate", validate_capacity)
    monkeypatch.setattr(
        gate,
        "verify_launch_plan",
        lambda *_args, **_kwargs: {
            "count": 2,
            "concurrency": gate.ROLLOUT_CONCURRENCY,
            "provider": "sandoq",
            "certifier_adapter": gate.CERTIFIER_ADAPTER,
            "selector": str(selector),
            "selector_sha256": hashlib.sha256(selector.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setattr(gate, "read_published_file", lambda _path: manifest_body)
    monkeypatch.setattr(gate, "load_saved_manifest", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(
        gate,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "identity": {
                "source": {
                    "prime_rl_commit": revision,
                    "sandoq_site_sha256": gate.SANDOQ_SITE_SHA256,
                    "sandoq_client_version": gate.SANDOQ_CLIENT_VERSION,
                },
                "execution": {
                    "sandoq_environment": {
                        "environment": gate.SANDOQ_ENVIRONMENT,
                        "pool_size": gate.ROUTER_ADMISSION,
                    }
                },
            }
        },
    )

    receipt = gate.validate_launch(
        certificate_path=tmp_path / "capacity.json",
        certificate_sha256="e" * 64,
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_body).hexdigest(),
        selector=selector,
        dataset_dir=dataset,
        expected_revision=revision,
        sandoq_site=tmp_path / gate.SANDOQ_SITE_NAME,
        union_launch_plan=tmp_path / "launch-plan.json",
        union_launch_plan_sha256="f" * 64,
    )

    assert capacity_calls == [
        {
            "expected_sha256": "e" * 64,
            "required_concurrency": gate.ROLLOUT_CONCURRENCY,
            "expected_endpoint_identifier": gate.ENDPOINT_IDENTIFIER,
        }
    ]
    assert receipt["task_count"] == 2
    assert receipt["security_labelled_task_count"] == 1
    assert receipt["security_task_handling"] == "opaque-execution-aggregate-only"
    assert receipt["membership_disclosed"] is False
    assert receipt["capacity_qualification_scope"] == "routing-runtime-capacity-only"
    serialized = json.dumps(receipt)
    assert "ordinary-task" not in serialized
    assert "opaque-task" not in serialized


def test_launch_gate_rejects_changed_security_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "tasks"
    dataset.mkdir()
    _task(dataset, "ordinary-one", "systems")
    _task(dataset, "ordinary-two", "systems")
    selector = tmp_path / "selector.txt"
    selector.write_text("ordinary-one\nordinary-two\n")
    monkeypatch.setattr(gate, "TASK_COUNT", 2)
    monkeypatch.setattr(gate, "SECURITY_LABELLED_TASK_COUNT", 1)
    monkeypatch.setattr(gate, "OFFICIAL_SELECTOR_SHA256", hashlib.sha256(selector.read_bytes()).hexdigest())

    with pytest.raises(gate.KimiTB4W2GateError, match="^security_boundary_changed$"):
        gate._validate_official_selector(selector, dataset)


def test_gate_receipt_is_private_and_exclusive(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "gate.json"
    gate._write_once(output, {"state": "passed"})

    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(gate.KimiTB4W2GateError, match="^output_invalid$"):
        gate._write_once(output, {"state": "passed"})
