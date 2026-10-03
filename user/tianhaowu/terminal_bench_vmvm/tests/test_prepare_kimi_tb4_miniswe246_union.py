from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import pytest
from verifiers.v1.configs.eval import EvalConfig


def _resource(*, cpu: int = 2, memory_gib: int = 4, disk_gib: int = 10, gpu: int = 0) -> dict[str, int]:
    return {
        "cpu_count": cpu,
        "memory_bytes": memory_gib * split.GIB,
        "disk_bytes": disk_gib * split.GIB,
        "gpu_count": gpu,
    }


def _manifest_value() -> tuple[dict, bytes, bytes]:
    entries = []
    digest = "a" * 64
    for index in range(split.TOTAL_TASKS):
        if index < 28:
            resources = _resource()
        elif index < 34:
            resources = _resource(cpu=4)
        elif index < split.CPU_TASKS:
            resources = _resource(cpu=16, memory_gib=8, disk_gib=50)
        else:
            resources = _resource(gpu=1)
        requires_compose = 25 <= index < 28 or 34 <= index < 42
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
                "runtime_requirements": {"compose": requires_compose},
            }
        )
    selector_body = ("\n".join(entry["task_id"] for entry in entries) + "\n").encode()
    image_manifest = {
        "images": {entry["task_id"]: entry["images"] for entry in entries},
        "schema_version": 1,
        "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
    }
    image_body = split.canonical_json(image_manifest)
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
    return value, selector_body, image_body


def _parsed_entries(monkeypatch: pytest.MonkeyPatch) -> tuple[split.ManifestEntry, ...]:
    value, selector_body, image_body = _manifest_value()
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_body).hexdigest())
    body = split.canonical_json(value)
    _value, entries = split.parse_manifest(body, hashlib.sha256(body).hexdigest())
    return entries


def _private(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    path.chmod(0o600)
    return path.resolve()


def _install_provider_evidence(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700)
    tunnel = {
        "cleanup_verified": True,
        "create_session_verified": True,
        "environment": "oci-runner-firecracker",
        "kind": "sandoq-firecracker-tunnel-capability",
        "port_names": ["exec", "tunnel"],
        "schema_version": 1,
        "slurm_job_id": "123",
        "state": "passed",
        "tunnel_available": True,
    }
    resource = {
        "command_exit_code": 0,
        "elapsed_seconds": 1.0,
        "environment": "oci-runner-firecracker",
        "kind": "sandoq-full-resource-tunnel-capability",
        "requested_cpu": 2,
        "requested_disk_gb": 10,
        "requested_memory_gb": 4,
        "runtime_stop_completed": True,
        "sandbox_started": True,
        "schema_version": 1,
        "slurm_job_id": "124",
        "state": "passed",
        "tunnel_roundtrip_verified": True,
    }
    tunnel_path = _private(evidence / "tunnel.json", split.canonical_json(tunnel))
    resource_path = _private(evidence / "resource.json", split.canonical_json(resource))
    tunnel_sha256 = hashlib.sha256(tunnel_path.read_bytes()).hexdigest()
    resource_sha256 = hashlib.sha256(resource_path.read_bytes()).hexdigest()
    monkeypatch.setattr(union, "FULL_TUNNEL_RECEIPT", tunnel_path)
    monkeypatch.setattr(union, "FULL_TUNNEL_RECEIPT_SHA256", tunnel_sha256)
    monkeypatch.setattr(union, "FULL_RESOURCE_RECEIPT", resource_path)
    monkeypatch.setattr(union, "FULL_RESOURCE_RECEIPT_SHA256", resource_sha256)
    profile = {
        "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "cluster_identifier": "use2",
        "effective_task_network": "public",
        "environment": "oci-runner-firecracker",
        "provider_token_file": "/home/tianhaowu/.config/oci-runner/firecracker-token",
        "runtime_resource_receipt": str(resource_path),
        "runtime_resource_receipt_sha256": resource_sha256,
        "runtime_tunnel_receipt": str(tunnel_path),
        "runtime_tunnel_receipt_sha256": tunnel_sha256,
        "schema_version": 4,
        "task_network": "host",
        "transport_mode": "auto",
    }
    profile_path = evidence / "profile.json"
    profile_path.write_bytes(split.canonical_json(profile))
    profile_path.chmod(0o644)
    monkeypatch.setattr(union, "PROVIDER_PROFILE_SHA256", hashlib.sha256(profile_path.read_bytes()).hexdigest())
    monkeypatch.setattr(union, "_provider_profile_path", lambda: profile_path.resolve())


def _install_base_config(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_sha256: str,
) -> Path:
    value = tomllib.loads(union._base_config_path().read_text())
    value["taskset"]["image_manifest_sha256"] = image_sha256
    base = root / "union-base.toml"
    base.write_bytes(union._render_toml(value))
    monkeypatch.setattr(union, "BASE_CONFIG_SHA256", hashlib.sha256(base.read_bytes()).hexdigest())
    monkeypatch.setattr(union, "_base_config_path", lambda: base.resolve())
    return base.resolve()


def test_partition_is_exact_52_11_3_and_keeps_compose_off_sandoq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _parsed_entries(monkeypatch)

    partition = union.derive_union_partition(entries)

    assert (
        len(partition.sandoq_firecracker),
        len(partition.vmvm_cpu),
        len(partition.gpu_unsupported),
    ) == (52, 11, 3)
    assert set(partition.compose_required).isdisjoint(partition.sandoq_firecracker)
    assert set(partition.compose_required).issubset(partition.vmvm_cpu)
    receipt = union._partition_receipt("f" * 64, partition)
    assert b"opaque-case" not in split.canonical_json(receipt)


def test_partition_clamps_oversized_noncompose_tasks_to_sandoq_supply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, selector_body, image_body = _manifest_value()
    moved_index = 50
    value["entries"][moved_index]["agent_resources"] = _resource(cpu=4, disk_gib=60)
    value["entries"][moved_index]["verifier_resources"] = _resource(cpu=4, disk_gib=60)
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_body).hexdigest())
    body = split.canonical_json(value)
    _value, entries = split.parse_manifest(body, hashlib.sha256(body).hexdigest())

    partition = union.derive_union_partition(entries)

    assert value["entries"][moved_index]["task_id"] in partition.sandoq_firecracker


def test_smoke_selector_must_be_one_member_of_certified_sandoq_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    value, selector_body, image_body = _manifest_value()
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_body).hexdigest())
    manifest_body = split.canonical_json(value)
    manifest = _private(tmp_path / "manifest.json", manifest_body)
    entries = _parsed_entries(monkeypatch)
    partition = union.derive_union_partition(entries)
    smoke_body = union._selector_payload(partition.sandoq_firecracker[:1])
    smoke = _private(tmp_path / "smoke.tasks", smoke_body)

    result = union.verify_smoke_selector(
        manifest,
        hashlib.sha256(manifest_body).hexdigest(),
        smoke,
        hashlib.sha256(smoke_body).hexdigest(),
    )

    assert result == {
        "state": "passed",
        "count": 1,
        "selector_sha256": hashlib.sha256(smoke_body).hexdigest(),
        "resource_policy": "non-compose-clamped-full-firecracker-v1",
    }
    unsupported_body = union._selector_payload(partition.vmvm_cpu[:1])
    unsupported = _private(tmp_path / "unsupported.tasks", unsupported_body)
    with pytest.raises(union.UnionPreparationError, match="smoke_selector_invalid"):
        union.verify_smoke_selector(
            manifest,
            hashlib.sha256(manifest_body).hexdigest(),
            unsupported,
            hashlib.sha256(unsupported_body).hexdigest(),
        )


def test_lane_configs_are_native_miniswe_and_provider_isolated() -> None:
    base, _body = union._base_config(union._base_config_path().resolve())
    sandoq = union._lane_config(
        base,
        role=union.SANDOQ_ROLE,
        selector=Path("/private/sandoq.tasks"),
        selector_sha256="a" * 64,
        image_manifest=Path("/private/images.json"),
        dataset_dir=Path("/private/dataset"),
        concurrency=48,
    )
    vmvm = union._lane_config(
        base,
        role=union.VMVM_ROLE,
        selector=Path("/private/vmvm.tasks"),
        selector_sha256="b" * 64,
        image_manifest=Path("/private/images.json"),
        dataset_dir=Path("/private/dataset"),
        concurrency=11,
    )

    assert sandoq["num_tasks"] == 52
    assert sandoq["taskset"]["resource_multiplier"] == 1.0
    assert sandoq["taskset"]["enable_compose"] is False
    assert sandoq["taskset"]["resource_cpu_cap"] == 2
    assert sandoq["taskset"]["resource_memory_mb_cap"] == 4096
    assert sandoq["taskset"]["resource_storage_mb_cap"] == 10240
    assert sandoq["harness"]["id"] == "mini-swe-agent"
    assert sandoq["harness"]["version"] == "2.4.6"
    assert sandoq["harness"]["runtime"] == {
        "type": "sandoq",
        "mode": "oci-runner",
        "session_timeout": union.SESSION_TIMEOUT_SECONDS,
        "network_access": True,
        "host_tunnel": "sandoq",
        "buffered_chat_completions": True,
        "guest_tunnel_url": "http://127.0.0.1:8485",
        "tunnel_pool_size": 4,
        "tunnel_ready_timeout": 30,
        "provisioning_retries": union.SANDOQ_PROVISIONING_RETRIES,
        "expected_environment": "oci-runner-firecracker",
        "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
    }
    assert vmvm["num_tasks"] == 11
    assert vmvm["max_concurrent"] == vmvm["multiplex"] == 11
    assert vmvm["client"]["max_connections"] == vmvm["client"]["max_keepalive_connections"] == 11
    assert vmvm["taskset"]["resource_multiplier"] == 2.0
    assert vmvm["taskset"]["enable_compose"] is True
    assert vmvm["harness"]["runtime"]["type"] == "vmvm"
    assert union._provider_neutral_config(sandoq) == union._provider_neutral_config(vmvm)
    assert sandoq["client"]["timeout"] == union.REQUEST_TIMEOUT_SECONDS
    assert sandoq["timeout"]["rollout"] == union.ROLLOUT_TIMEOUT_SECONDS
    EvalConfig.model_validate(sandoq)
    EvalConfig.model_validate(vmvm)


def test_legacy_base_is_rejected_for_new_union_materialization() -> None:
    with pytest.raises(union.UnionPreparationError, match="base_config_path_invalid"):
        union._base_config(union._legacy_base_config_path().resolve())


@pytest.mark.parametrize("provisioning_retries", [True, 0, 2, 4])
def test_lane_config_rejects_unapproved_provisioning_retry_counts(
    provisioning_retries: int,
) -> None:
    base, _body = union._base_config(union._base_config_path().resolve())

    with pytest.raises(
        union.UnionPreparationError,
        match="sandoq_provisioning_retry_contract_invalid",
    ):
        union._lane_config(
            base,
            role=union.SANDOQ_ROLE,
            selector=Path("/private/sandoq.tasks"),
            selector_sha256="a" * 64,
            image_manifest=Path("/private/images.json"),
            dataset_dir=Path("/private/dataset"),
            concurrency=24,
            sandoq_provisioning_retries=provisioning_retries,
        )


def test_materialized_plan_is_opaque_and_requires_separate_certifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    value, selector_body, image_body = _manifest_value()
    image_sha256 = hashlib.sha256(image_body).hexdigest()
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", image_sha256)
    manifest_body = split.canonical_json(value)
    manifest = _private(tmp_path / "manifest.json", manifest_body)
    image_manifest = tmp_path / "images.json"
    image_manifest.write_bytes(image_body)
    base = _install_base_config(tmp_path, monkeypatch, image_sha256)
    _install_provider_evidence(tmp_path, monkeypatch)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    eval_root = tmp_path / "evals"
    eval_root.mkdir()
    output = tmp_path / "union"

    summary = union.materialize(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_body).hexdigest(),
        image_manifest=image_manifest.resolve(),
        dataset_dir=dataset.resolve(),
        base_config=base,
        output=output.resolve(),
        eval_root=eval_root.resolve(),
        run_label="bounded",
    )

    assert summary[union.SANDOQ_ROLE] == 52
    assert summary[union.VMVM_ROLE] == 11
    assert summary[union.GPU_ROLE] == 3
    assert summary["all_sandoq_allowed"] is False
    assert summary["certifier_adapter_required"] is True
    plan_path = (output / union.LAUNCH_PLAN).resolve()
    plan_body = plan_path.read_bytes()
    assert b"opaque-case" not in plan_body
    assert b"opaque-case" not in (output / union.PARTITION_RECEIPT).read_bytes()
    plan_value = split._json_object(plan_body, code="test", canonical=True)
    assert plan_value["evaluation"]["certification_eligible"] is True
    assert plan_value["evaluation"]["blocked_on"] == []
    assert plan_value["contracts"]["timeouts"] == {
        "request_seconds": union.REQUEST_TIMEOUT_SECONDS,
        "rollout_seconds": union.ROLLOUT_TIMEOUT_SECONDS,
        "session_seconds": union.SESSION_TIMEOUT_SECONDS,
    }
    assert plan_value["contracts"]["sandoq_provisioning_retries"] == union.SANDOQ_PROVISIONING_RETRIES
    for role, count in ((union.SANDOQ_ROLE, 52), (union.VMVM_ROLE, 11)):
        verified = union.verify_launch_plan(plan_path, hashlib.sha256(plan_body).hexdigest(), role)
        assert verified["count"] == count
        assert verified["certifier_adapter"] == union.CERTIFIER_ADAPTER

    # Plans materialized before the retry hardening omitted the explicit
    # contract and relied on SandoqConfig's historical default of one retry.
    # Keep those immutable bundles independently re-verifiable.
    sandoq_config_path = output / union.SANDOQ_CONFIG
    legacy_config = tomllib.loads(sandoq_config_path.read_text())
    legacy_config["harness"]["runtime"]["provisioning_retries"] = union.LEGACY_SANDOQ_PROVISIONING_RETRIES
    legacy_config_body = union._render_toml(legacy_config)
    sandoq_config_path.write_bytes(legacy_config_body)
    plan_value["contracts"].pop("sandoq_provisioning_retries")
    plan_value["lanes"][union.SANDOQ_ROLE]["config"] = union._artifact(
        sandoq_config_path.resolve(),
        legacy_config_body,
    )
    legacy_plan_body = split.canonical_json(plan_value)
    plan_path.write_bytes(legacy_plan_body)
    bundle_files = {entry.name: entry.read_bytes() for entry in output.iterdir() if entry.name != split.BUNDLE_COMMIT}
    complete = split._committed_bundle_files(bundle_files)[split.BUNDLE_COMMIT]
    (output / split.BUNDLE_COMMIT).write_bytes(complete)

    legacy_verified = union.verify_launch_plan(
        plan_path,
        hashlib.sha256(legacy_plan_body).hexdigest(),
        union.SANDOQ_ROLE,
    )
    assert legacy_verified["count"] == union.SANDOQ_TASKS
    assert (
        tomllib.loads(Path(str(legacy_verified["config"])).read_text())["harness"]["runtime"]["provisioning_retries"]
        == union.LEGACY_SANDOQ_PROVISIONING_RETRIES
    )


def test_cli_redacts_failures(capsys: pytest.CaptureFixture[str]) -> None:
    code = union.main(
        [
            "verify",
            "--launch-plan",
            "/missing/private-plan.json",
            "--launch-plan-sha256",
            "0" * 64,
            "--role",
            union.SANDOQ_ROLE,
        ]
    )

    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "kimi_tb4_miniswe246_union_failed"
