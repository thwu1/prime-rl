from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import direct_kimi_workers
import pytest
import yaml
from direct_kimi_workers import (
    DirectKimiWorkerError,
    certify_router,
    load_workers,
    materialize_source_snapshot,
    prepare_generation,
    validate_saved_manifest,
)


def test_source_snapshot_accepts_only_exact_group_writable_deployment_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _deployment(tmp_path, monkeypatch)
    (source / "proxy_litellm_config.yaml").chmod(0o664)
    with pytest.raises(DirectKimiWorkerError, match="source_unreadable"):
        load_workers(source)

    snapshot = tmp_path / "private" / "deployment-source"
    value = materialize_source_snapshot(source.resolve(), snapshot.resolve())

    assert value["path"] == str(snapshot.resolve())
    assert value["spec_sha256"] == direct_kimi_workers.EXPECTED_SPEC_SHA256
    assert value["proxy_config_sha256"] == direct_kimi_workers.EXPECTED_PROXY_CONFIG_SHA256
    assert len(load_workers(snapshot)[0]) == 24
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    assert {entry.name for entry in snapshot.iterdir()} == {
        "spec.yaml",
        "proxy_litellm_config.yaml",
        direct_kimi_workers.SOURCE_SNAPSHOT_MARKER_NAME,
    }
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in snapshot.iterdir())

    (source / "proxy_litellm_config.yaml").write_text("changed\n")
    assert len(load_workers(snapshot)[0]) == 24


def _deployment(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "shared-kimi-k3"
    root.mkdir(parents=True)
    spec = root / "spec.yaml"
    spec.write_text("spec: {}\n")
    config = root / "proxy_litellm_config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "litellm_settings": {"request_timeout": 600, "num_retries": 2},
                "model_list": [
                    {
                        "model_name": "Kimi-K3",
                        "model_info": {"mode": "chat"},
                        "litellm_params": {
                            "api_base": f"http://worker-{index}:8000/v1",
                            "api_key": "EMPTY",
                            "model": "backend-model",
                        },
                    }
                    for index in range(24)
                ],
                "router_settings": {},
                "general_settings": {},
            },
            sort_keys=True,
        )
    )
    monkeypatch.setattr(direct_kimi_workers, "EXPECTED_SPEC_SHA256", hashlib.sha256(spec.read_bytes()).hexdigest())
    monkeypatch.setattr(
        direct_kimi_workers,
        "EXPECTED_PROXY_CONFIG_SHA256",
        hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    return root


def _binding_files(
    run_dir: Path,
    *,
    role: str = "kimi-direct-tb4",
    manifest_path: Path | None = None,
) -> tuple[Path, Path, Path, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.chmod(0o700)
    if manifest_path is None:
        deployment = {
            "kind": "direct_kimi",
            "worker_manifest": {"path": str(run_dir / "manifest.json"), "sha256": "a" * 64},
            "spec_sha256": "b" * 64,
            "endpoint_bundle_sha256": "c" * 64,
            "base_url": "http://127.0.0.1:20000/v1",
            "router": {},
        }
    else:
        manifest = json.loads(manifest_path.read_text())
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        router = manifest["router"]
        deployment = {
            "kind": "direct_kimi",
            "worker_manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
            "spec_sha256": manifest["source_spec_sha256"],
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "base_url": f"http://127.0.0.1:{router['port']}/v1",
            "router": {
                "implementation": router["implementation"],
                "implementation_sha256": router["implementation_sha256"],
                "policy": router["policy"],
                "request_id_headers": router["request_id_headers"],
                "provider_concurrency": router["max_concurrent_requests"],
                "request_timeout_seconds": router["request_timeout_seconds"],
                "retries": router["retries"],
                "worker_count": len(manifest["workers"]),
            },
        }
        if "capacity_profile" in router:
            deployment["router"].update(
                {
                    "capacity_profile": router["capacity_profile"],
                    "endpoint_identifier": router["endpoint_identifier"],
                }
            )
        if "per_worker_capacity" in router:
            deployment["router"]["per_worker_capacity"] = router["per_worker_capacity"]
    identity_value = {
        "role": role,
        "source": {"sandbox_provider": "sandoq"},
        "deployment": deployment,
    }
    identity_sha256 = hashlib.sha256(
        json.dumps(
            identity_value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    identity = run_dir / "eval_run_identity.json"
    identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "identity": identity_value,
            }
        )
    )
    invocations = run_dir / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": role,
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "123",
            }
        )
        + "\n"
    )
    provenance = run_dir / "provenance.txt"
    provenance.write_text(
        f"eval_run_identity_sha256={identity_sha256}\neval_run_role={role}\nhost=test-host\nslurm_job_id=123\n"
    )
    for path in (identity, invocations, provenance):
        path.chmod(0o600)
    return identity, invocations, provenance, identity_sha256


def test_direct_kimi_manifest_is_secret_free_and_revalidates(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    urls_path = generation / direct_kimi_workers.GENERATION_URLS_NAME
    ports_path = generation / direct_kimi_workers.GENERATION_PORTS_NAME

    manifest = prepare_generation(root, generation, manifest_path, urls_path, ports_path)
    assert len(manifest["workers"]) == 24
    assert manifest["router"]["policy"] == "consistent_hash"
    assert manifest["router"]["implementation"] == "direct-kimi-transparent-v2"
    assert len(manifest["router"]["implementation_sha256"]) == 64
    assert manifest["router"]["request_id_headers"] == ["x-session-id"]
    assert manifest["router"]["request_timeout_seconds"] == 43_200
    assert manifest["router"]["retries"] == 0
    assert "worker-0" not in manifest_path.read_text()
    assert len(urls_path.read_text().splitlines()) == 24
    assert validate_saved_manifest(manifest_path) == manifest
    assert stat.S_IMODE(generation.stat().st_mode) == 0o700
    marker_path = generation / direct_kimi_workers.GENERATION_MARKER_NAME
    marker = json.loads(marker_path.read_bytes())
    assert set(marker["files"]) == {manifest_path.name, urls_path.name, ports_path.name}
    for path in (manifest_path, urls_path, ports_path, marker_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1

    held_marker = generation / "held-generation-marker"
    marker_path.rename(held_marker)
    with pytest.raises(DirectKimiWorkerError, match="manifest_invalid"):
        validate_saved_manifest(manifest_path)
    held_marker.rename(marker_path)

    urls_body = urls_path.read_bytes()
    urls_path.write_bytes(b"changed\n")
    urls_path.chmod(0o600)
    with pytest.raises(DirectKimiWorkerError, match="manifest_invalid"):
        validate_saved_manifest(manifest_path)
    urls_path.write_bytes(urls_body)
    urls_path.chmod(0o600)

    (root / "proxy_litellm_config.yaml").write_text("changed\n")
    with pytest.raises(DirectKimiWorkerError, match="source_generation_mismatch"):
        validate_saved_manifest(manifest_path)


def test_direct_kimi_extended_timeout_is_bound_and_revalidated(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME

    manifest = prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        request_timeout_seconds=144_000,
    )

    assert manifest["router"]["request_timeout_seconds"] == 144_000
    assert manifest["router"]["queue_timeout_seconds"] == 144_000
    assert validate_saved_manifest(manifest_path) == manifest


def test_direct_kimi_c64_manifest_requires_explicit_profile_and_endpoint(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    manifest = prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        capacity_profile="sandoq-c64-v1",
        endpoint_identifier="cpu-132-021_8103",
    )

    assert manifest["schema_version"] == 2
    assert manifest["router"]["capacity_profile"] == "sandoq-c64-v1"
    assert manifest["router"]["endpoint_identifier"] == "cpu-132-021_8103"
    assert manifest["router"]["max_concurrent_requests"] == 64
    assert manifest["router"]["queue_size"] == 64
    assert "per_worker_capacity" not in manifest["router"]
    assert manifest["router"]["retries"] == 0
    assert validate_saved_manifest(manifest_path) == manifest

    another = tmp_path / "another"
    with pytest.raises(ValueError, match="endpoint_identifier_invalid"):
        prepare_generation(
            root,
            another,
            another / direct_kimi_workers.GENERATION_MANIFEST_NAME,
            another / direct_kimi_workers.GENERATION_URLS_NAME,
            another / direct_kimi_workers.GENERATION_PORTS_NAME,
            capacity_profile="sandoq-c64-v1",
        )


def test_direct_kimi_w2_manifest_binds_profile_worker_capacity_and_v2(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    manifest = prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        capacity_profile="sandoq-c64-w2-v1",
        endpoint_identifier="cpu-132-021_8103",
    )

    assert manifest["schema_version"] == 3
    assert manifest["router"]["implementation"] == "direct-kimi-transparent-v2"
    assert manifest["router"]["capacity_profile"] == "sandoq-c64-w2-v1"
    assert manifest["router"]["per_worker_capacity"] == 2
    assert validate_saved_manifest(manifest_path) == manifest


def test_historical_legacy_manifest_accepts_only_pinned_v1_hash(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    manifest = prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
    )
    historical = json.loads(json.dumps(manifest))
    historical["router"].update(
        {
            "implementation": "direct-kimi-transparent-v1",
            "implementation_sha256": direct_kimi_workers.HISTORICAL_LEGACY_ROUTER_SHA256,
        }
    )

    assert direct_kimi_workers.validate_manifest_value(historical, revalidate_live_source=False) == historical
    historical["router"]["implementation_sha256"] = "0" * 64
    with pytest.raises(DirectKimiWorkerError, match="manifest_invalid"):
        direct_kimi_workers.validate_manifest_value(historical, revalidate_live_source=False)

    historical_v2 = json.loads(json.dumps(manifest))
    historical_v2["router"]["implementation_sha256"] = direct_kimi_workers.HISTORICAL_CURRENT_ROUTER_SHA256
    assert (
        direct_kimi_workers.validate_manifest_value(
            historical_v2,
            revalidate_live_source=False,
        )
        == historical_v2
    )
    historical_v2["router"]["request_timeout_seconds"] = 144_000
    historical_v2["router"]["queue_timeout_seconds"] = 144_000
    with pytest.raises(DirectKimiWorkerError, match="manifest_invalid"):
        direct_kimi_workers.validate_manifest_value(
            historical_v2,
            revalidate_live_source=False,
        )


def test_direct_kimi_atomic_publication_is_exclusive(tmp_path: Path) -> None:
    output = tmp_path / "private" / "receipt.json"
    direct_kimi_workers._atomic_write(output, b"first\n", exclusive=True)
    direct_kimi_workers._atomic_write(output, b"first\n", exclusive=True)
    with pytest.raises(DirectKimiWorkerError, match="output_incomplete_or_conflicting"):
        direct_kimi_workers._atomic_write(output, b"second\n", exclusive=True)

    assert output.read_bytes() == b"first\n"
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert {entry.name for entry in output.parent.iterdir()} == {
        output.name,
        f".{output.name}.complete",
    }
    assert direct_kimi_workers.read_published_file(output) == b"first\n"


def test_direct_kimi_atomic_publication_precommit_failure_is_not_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_write = os.write

    def failed_write(descriptor: int, body: bytes | memoryview) -> int:
        del descriptor, body
        raise OSError("synthetic precommit failure")

    monkeypatch.setattr(direct_kimi_workers.os, "write", failed_write)
    with pytest.raises(DirectKimiWorkerError, match="output_publish_failed"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)
    monkeypatch.setattr(direct_kimi_workers.os, "write", original_write)
    assert output.exists()
    assert not (output.parent / f".{output.name}.complete").exists()
    with pytest.raises(DirectKimiWorkerError, match="published_file_invalid"):
        direct_kimi_workers.read_published_file(output)
    with pytest.raises(DirectKimiWorkerError, match="output_incomplete_or_conflicting"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)

    fresh = tmp_path / "fresh-private" / output.name
    direct_kimi_workers._atomic_write(fresh, b"value\n", exclusive=True)
    assert direct_kimi_workers.read_published_file(fresh) == b"value\n"


def test_direct_kimi_atomic_publication_indeterminate_result_is_adoptable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_fsync = os.fsync
    calls = 0

    def fail_postcommit_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic postcommit failure")
        original_fsync(descriptor)

    monkeypatch.setattr(direct_kimi_workers.os, "fsync", fail_postcommit_fsync)
    with pytest.raises(DirectKimiWorkerError, match="output_publication_indeterminate"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)
    monkeypatch.setattr(direct_kimi_workers.os, "fsync", original_fsync)
    assert output.read_bytes() == b"value\n"

    direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)
    assert output.read_bytes() == b"value\n"


def test_direct_kimi_atomic_publication_detects_payload_name_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_write_final = direct_kimi_workers._write_final_at

    def substitute_after_write(parent: int, name: str, body: bytes) -> int:
        descriptor = original_write_final(parent, name, body)
        if name != output.name:
            return descriptor
        os.rename(name, ".owned-before-commit", src_dir_fd=parent, dst_dir_fd=parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        replacement = os.open(name, flags, 0o600, dir_fd=parent)
        try:
            os.write(replacement, b"replacement\n")
            os.fsync(replacement)
        finally:
            os.close(replacement)
        return descriptor

    monkeypatch.setattr(direct_kimi_workers, "_write_final_at", substitute_after_write)
    with pytest.raises(DirectKimiWorkerError, match="output_publication_indeterminate"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)

    assert output.read_bytes() == b"replacement\n"
    assert (output.parent / ".owned-before-commit").read_bytes() == b"value\n"
    with pytest.raises(DirectKimiWorkerError, match="published_file_invalid"):
        direct_kimi_workers.read_published_file(output)


def test_direct_kimi_atomic_publication_detects_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_write_final = direct_kimi_workers._write_final_at

    def replace_parent_after_marker(parent: int, name: str, body: bytes) -> int:
        descriptor = original_write_final(parent, name, body)
        if name == f".{output.name}.complete":
            output.parent.rename(tmp_path / "held-private")
            output.parent.mkdir(mode=0o700)
        return descriptor

    monkeypatch.setattr(direct_kimi_workers, "_write_final_at", replace_parent_after_marker)
    with pytest.raises(DirectKimiWorkerError, match="output_publication_indeterminate"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)

    assert not output.exists()
    assert (tmp_path / "held-private" / output.name).read_bytes() == b"value\n"


def test_direct_kimi_atomic_publication_rejects_symlink_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(private.name)

    with pytest.raises(DirectKimiWorkerError, match="output_parent_invalid"):
        direct_kimi_workers._atomic_write(alias / "receipt.json", b"value\n", exclusive=True)
    assert not (private / "receipt.json").exists()


def test_direct_kimi_router_receipt_is_exact(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
    )
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    output = generation / "router.json"
    stats = generation / "router-stats.json"
    stats.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "direct-kimi-transparent-router",
                "implementation": "direct-kimi-transparent-v2",
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 43_200,
                "retries": 0,
                "worker_count": 24,
                "active_workers": 24,
                "active_requests": 0,
                "max_active_requests": 1,
                "total_requests": 1,
                "chat_requests": 1,
                "missing_session_rejections": 0,
                "upstream_failures": 0,
                "worker_request_counts": [1, *([0] * 23)],
            }
        )
    )
    stats.chmod(0o600)
    identity, invocations, provenance, identity_sha256 = _binding_files(
        generation,
        manifest_path=manifest_path,
    )

    receipt = certify_router(
        manifest_path,
        digest,
        24,
        stats,
        output,
        eval_run_identity=identity,
        eval_invocations=invocations,
        provenance=provenance,
    )
    assert json.loads(output.read_text()) == receipt
    assert receipt["request_timeout_seconds"] == 43_200
    assert receipt["retries"] == 0
    assert receipt["implementation"] == "direct-kimi-transparent-v2"
    assert receipt["chat_requests"] == 1
    assert receipt["eval_run_identity_sha256"] == identity_sha256
    manifest = json.loads(manifest_path.read_text())
    mismatched_deployment = json.loads(json.dumps(json.loads(identity.read_text())["identity"]["deployment"]))
    mismatched_deployment["endpoint_bundle_sha256"] = "f" * 64
    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._validate_deployment_binding(
            mismatched_deployment,
            manifest_path,
            digest,
            manifest,
        )
    with pytest.raises(DirectKimiWorkerError, match="active_worker_count_mismatch"):
        certify_router(
            manifest_path,
            digest,
            23,
            stats,
            generation / "bad.json",
            eval_run_identity=identity,
            eval_invocations=invocations,
            provenance=provenance,
        )

    os.link(stats, generation / "router-stats-alias.json")
    with pytest.raises(DirectKimiWorkerError, match="router_stats_invalid"):
        certify_router(
            manifest_path,
            digest,
            24,
            stats,
            generation / "linked-stats.json",
            eval_run_identity=identity,
            eval_invocations=invocations,
            provenance=provenance,
        )


def test_direct_kimi_w2_router_receipt_requires_measured_clean_forwarding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        capacity_profile="sandoq-c64-w2-v1",
        endpoint_identifier="cpu-132-021_8103",
    )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    stats = generation / "router-stats.json"
    stats.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "direct-kimi-transparent-router",
                "implementation": "direct-kimi-transparent-v2",
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 43_200,
                "retries": 0,
                "worker_count": 24,
                "active_workers": 24,
                "capacity_profile": "sandoq-c64-w2-v1",
                "endpoint_identifier": "cpu-132-021_8103",
                "configured_capacity": 64,
                "configured_per_worker_capacity": 2,
                "active_requests": 0,
                "active_chat_requests": 0,
                "active_forwarded_requests": 0,
                "max_active_requests": 64,
                "max_active_chat_requests": 64,
                "max_active_forwarded_requests": 48,
                "total_requests": 128,
                "chat_requests": 128,
                "missing_session_rejections": 0,
                "capacity_rejections": 0,
                "queue_overflow_rejections": 0,
                "route_tracking_overflows": 0,
                "cross_route_anomalies": 0,
                "upstream_failures": 0,
                "worker_queue_timeouts": 0,
                "upstream_http_429": 0,
                "upstream_http_5xx": 0,
                "tracked_sessions": 64,
                "worker_request_counts": [6] * 8 + [5] * 16,
                "worker_active_request_counts": [0] * 24,
                "worker_max_active_request_counts": [2] * 24,
            }
        )
    )
    stats.chmod(0o600)
    identity, invocations, provenance, identity_sha256 = _binding_files(
        generation,
        role="kimi-direct-capacity-smoke",
        manifest_path=manifest_path,
    )

    receipt = certify_router(
        manifest_path,
        manifest_sha256,
        24,
        stats,
        generation / "router.json",
        eval_run_identity=identity,
        eval_invocations=invocations,
        provenance=provenance,
    )

    assert receipt["schema_version"] == 4
    assert receipt["eval_run_identity_sha256"] == identity_sha256
    assert receipt["capacity_profile"] == "sandoq-c64-w2-v1"
    assert receipt["configured_capacity"] == 64
    assert receipt["configured_per_worker_capacity"] == 2
    assert receipt["active_forwarded_requests"] == 0
    assert receipt["max_active_forwarded_requests"] == 48
    assert (
        receipt["worker_max_active_request_counts_sha256"]
        == hashlib.sha256((json.dumps([2] * 24, separators=(",", ":")) + "\n").encode()).hexdigest()
    )
    assert receipt["max_active_chat_requests"] == 64
    assert receipt["queue_overflow_rejections"] == 0

    valid_stats = json.loads(stats.read_text())
    for field, invalid_value in (
        ("active_forwarded_requests", 1),
        ("max_active_forwarded_requests", 47),
        ("worker_max_active_request_counts", [1, *([2] * 23)]),
        ("worker_queue_timeouts", 1),
        ("upstream_http_429", 1),
        ("upstream_http_5xx", 1),
    ):
        invalid_stats = json.loads(json.dumps(valid_stats))
        invalid_stats[field] = invalid_value
        stats.write_text(json.dumps(invalid_stats))
        stats.chmod(0o600)
        with pytest.raises(DirectKimiWorkerError, match="router_stats_invalid"):
            certify_router(
                manifest_path,
                manifest_sha256,
                24,
                stats,
                generation / f"invalid-{field}.json",
                eval_run_identity=identity,
                eval_invocations=invocations,
                provenance=provenance,
            )


def test_direct_kimi_w2_production_receipt_binds_observed_forwarding_peak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        capacity_profile="sandoq-c64-w2-v1",
        endpoint_identifier="cpu-132-021_8103",
    )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    run_dir = tmp_path / "production"
    identity, invocations, provenance, _identity_sha256 = _binding_files(
        run_dir,
        role="kimi-direct-mobius",
        manifest_path=manifest_path,
    )
    stats = run_dir / "router-stats.json"
    stats.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "direct-kimi-transparent-router",
                "implementation": "direct-kimi-transparent-v2",
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 43_200,
                "retries": 0,
                "worker_count": 24,
                "active_workers": 24,
                "capacity_profile": "sandoq-c64-w2-v1",
                "endpoint_identifier": "cpu-132-021_8103",
                "configured_capacity": 64,
                "configured_per_worker_capacity": 2,
                "active_requests": 0,
                "active_chat_requests": 0,
                "active_forwarded_requests": 0,
                "max_active_requests": 1,
                "max_active_chat_requests": 1,
                "max_active_forwarded_requests": 1,
                "total_requests": 1,
                "chat_requests": 1,
                "missing_session_rejections": 0,
                "capacity_rejections": 0,
                "queue_overflow_rejections": 0,
                "route_tracking_overflows": 0,
                "cross_route_anomalies": 0,
                "upstream_failures": 0,
                "worker_queue_timeouts": 0,
                "upstream_http_429": 0,
                "upstream_http_5xx": 0,
                "tracked_sessions": 1,
                "worker_request_counts": [1, *([0] * 23)],
                "worker_active_request_counts": [0] * 24,
                "worker_max_active_request_counts": [1, *([0] * 23)],
            }
        )
    )
    stats.chmod(0o600)

    receipt = certify_router(
        manifest_path,
        manifest_sha256,
        24,
        stats,
        run_dir / "router.json",
        eval_run_identity=identity,
        eval_invocations=invocations,
        provenance=provenance,
    )

    assert receipt["schema_version"] == 4
    assert receipt["max_active_forwarded_requests"] == 1
    assert (
        receipt["worker_max_active_request_counts_sha256"]
        == hashlib.sha256((json.dumps([1, *([0] * 23)], separators=(",", ":")) + "\n").encode()).hexdigest()
    )


def test_existing_c64_profile_cannot_authorize_capacity_role(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
        capacity_profile="sandoq-c64-v1",
        endpoint_identifier="cpu-132-021_8103",
    )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    identity, invocations, provenance, _identity_sha256 = _binding_files(
        generation,
        role="kimi-direct-capacity-smoke",
        manifest_path=manifest_path,
    )
    stats = generation / "router-stats.json"
    stats.write_text("{}\n")
    stats.chmod(0o600)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        certify_router(
            manifest_path,
            manifest_sha256,
            24,
            stats,
            generation / "router.json",
            eval_run_identity=identity,
            eval_invocations=invocations,
            provenance=provenance,
        )


@pytest.mark.parametrize(
    "evidence_name",
    (
        "eval_run_identity.json",
        "eval_invocations.jsonl",
        "provenance.txt",
        direct_kimi_workers.GENERATION_MARKER_NAME,
        direct_kimi_workers.GENERATION_MANIFEST_NAME,
        direct_kimi_workers.GENERATION_URLS_NAME,
        direct_kimi_workers.GENERATION_PORTS_NAME,
        "router-stats.json",
        "source-spec",
        "source-proxy",
        "router-implementation",
    ),
)
def test_direct_kimi_router_receipt_rejects_evidence_swap_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_name: str,
) -> None:
    router_implementation_body = Path(direct_kimi_workers.__file__).with_name("direct_kimi_router.py").read_bytes()
    module_source = tmp_path / "module-source"
    module_source.mkdir()
    router_implementation = module_source / "direct_kimi_router.py"
    router_implementation.write_bytes(router_implementation_body)
    router_implementation.chmod(0o444)
    monkeypatch.setattr(
        direct_kimi_workers,
        "__file__",
        str(module_source / "direct_kimi_workers.py"),
    )
    root = _deployment(tmp_path, monkeypatch)
    generation = tmp_path / "generation"
    manifest_path = generation / direct_kimi_workers.GENERATION_MANIFEST_NAME
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / direct_kimi_workers.GENERATION_URLS_NAME,
        generation / direct_kimi_workers.GENERATION_PORTS_NAME,
    )
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    stats = generation / "router-stats.json"
    stats.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "direct-kimi-transparent-router",
                "implementation": "direct-kimi-transparent-v2",
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "request_timeout_seconds": 43_200,
                "retries": 0,
                "worker_count": 24,
                "active_workers": 24,
                "active_requests": 0,
                "max_active_requests": 1,
                "total_requests": 1,
                "chat_requests": 1,
                "missing_session_rejections": 0,
                "upstream_failures": 0,
                "worker_request_counts": [1, *([0] * 23)],
            }
        )
    )
    stats.chmod(0o600)
    identity, invocations, provenance, _identity_sha256 = _binding_files(
        generation,
        manifest_path=manifest_path,
    )
    if evidence_name == "source-spec":
        target = root / "spec.yaml"
    elif evidence_name == "source-proxy":
        target = root / "proxy_litellm_config.yaml"
    elif evidence_name == "router-implementation":
        target = router_implementation
    else:
        target = generation / evidence_name
    target_body = target.read_bytes()
    target_mode = stat.S_IMODE(target.stat().st_mode)
    original_write = direct_kimi_workers._write_final_at
    swapped = False

    def write_then_swap(parent: int, name: str, body: bytes) -> int:
        nonlocal swapped
        descriptor = original_write(parent, name, body)
        if not swapped:
            swapped = True
            target.rename(generation / f"held-{evidence_name.lstrip('.')}")
            target.write_bytes(target_body)
            target.chmod(target_mode)
        return descriptor

    monkeypatch.setattr(direct_kimi_workers, "_write_final_at", write_then_swap)
    output = generation / "router.json"
    with pytest.raises(DirectKimiWorkerError, match="changed"):
        certify_router(
            manifest_path,
            manifest_sha256,
            24,
            stats,
            output,
            eval_run_identity=identity,
            eval_invocations=invocations,
            provenance=provenance,
        )
    assert output.exists()
    assert not (generation / f".{output.name}.complete").exists()
    with pytest.raises(DirectKimiWorkerError, match="published_file_invalid"):
        direct_kimi_workers.read_published_file(output)


def test_direct_kimi_run_binding_rejects_nonprivate_inputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    provenance.chmod(0o644)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


@pytest.mark.parametrize(
    "role",
    (
        "kimi-direct-tb4-diagnostic",
        "kimi-direct-tb4-sandoq-fallback-diagnostic",
        "kimi-direct-mobius",
    ),
)
def test_direct_kimi_router_binding_accepts_supported_role(tmp_path: Path, role: str) -> None:
    identity, invocations, provenance, identity_sha256 = _binding_files(
        tmp_path / "run",
        role=role,
    )

    observed_identity_sha256, invocation_sha256, observed_identity = direct_kimi_workers._run_binding(
        identity,
        invocations,
        provenance,
    )

    assert observed_identity_sha256 == identity_sha256
    assert len(invocation_sha256) == 64
    assert observed_identity["role"] == role


def test_direct_kimi_retained_bytes_binding_matches_path_binding(tmp_path: Path) -> None:
    identity, invocations, provenance, _identity_sha256 = _binding_files(
        tmp_path / "run",
        role="kimi-direct-tb4-sandoq-fallback-diagnostic",
    )

    expected = direct_kimi_workers._run_binding(identity, invocations, provenance)
    observed = direct_kimi_workers.validate_run_binding_bytes(
        identity.read_bytes(),
        invocations.read_bytes(),
        provenance.read_bytes(),
    )

    assert observed == expected


def test_direct_kimi_run_binding_rejects_hardlinks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    os.link(invocations, run_dir / "invocations-alias.jsonl")

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


def test_direct_kimi_run_binding_rejects_symlinks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    target = run_dir / "provenance-target.txt"
    provenance.rename(target)
    provenance.symlink_to(target.name)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


def test_direct_kimi_run_binding_rejects_symlinked_parent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    alias = tmp_path / "alias"
    alias.symlink_to(run_dir.name)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(
            alias / identity.name,
            alias / invocations.name,
            alias / provenance.name,
        )


def test_direct_kimi_run_binding_rejects_cross_directory_replay(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    replay_dir = tmp_path / "replay"
    replay_dir.mkdir(mode=0o700)
    replay = replay_dir / provenance.name
    replay.write_bytes(provenance.read_bytes())
    replay.chmod(0o600)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, replay)


def test_direct_kimi_run_binding_rejects_identity_digest_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    envelope = json.loads(identity.read_text())
    envelope["identity"]["role"] = "kimi-direct-smoke"
    identity.write_text(json.dumps(envelope))
    identity.chmod(0o600)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


def test_direct_kimi_run_binding_detects_path_replacement(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    original_read = os.read
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            held = run_dir / "held-identity.json"
            identity.rename(held)
            identity.write_bytes(held.read_bytes())
            identity.chmod(0o600)
        return original_read(descriptor, count)

    monkeypatch.setattr(direct_kimi_workers.os, "read", replacing_read)
    with pytest.raises(DirectKimiWorkerError, match="run_binding_changed"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


def test_direct_kimi_source_rejects_worker_credentials(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    config_path = root / "proxy_litellm_config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["model_list"][0]["litellm_params"]["api_key"] = "secret"
    config_path.write_text(yaml.safe_dump(config, sort_keys=True))
    monkeypatch.setattr(
        direct_kimi_workers,
        "EXPECTED_PROXY_CONFIG_SHA256",
        hashlib.sha256(config_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(DirectKimiWorkerError, match="worker_record_invalid"):
        load_workers(root)


def test_direct_kimi_source_rejects_symlink_and_hardlink_inputs(tmp_path: Path, monkeypatch) -> None:
    symlink_root = _deployment(tmp_path / "symlink-case", monkeypatch)
    proxy = symlink_root / "proxy_litellm_config.yaml"
    target = symlink_root / "proxy-target.yaml"
    proxy.rename(target)
    proxy.symlink_to(target.name)
    with pytest.raises(DirectKimiWorkerError, match="source_unreadable"):
        load_workers(symlink_root)

    hardlink_root = _deployment(tmp_path / "hardlink-case", monkeypatch)
    hardlink_proxy = hardlink_root / "proxy_litellm_config.yaml"
    os.link(hardlink_proxy, hardlink_root / "proxy-alias.yaml")
    with pytest.raises(DirectKimiWorkerError, match="source_unreadable"):
        load_workers(hardlink_root)


def test_direct_kimi_source_detects_path_replacement(tmp_path: Path, monkeypatch) -> None:
    root = _deployment(tmp_path, monkeypatch)
    spec = root / "spec.yaml"
    original_read = os.read
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            held = root / "held-spec.yaml"
            spec.rename(held)
            spec.write_bytes(held.read_bytes())
            spec.chmod(0o644)
        return original_read(descriptor, count)

    monkeypatch.setattr(direct_kimi_workers.os, "read", replacing_read)
    with pytest.raises(DirectKimiWorkerError, match="source_unreadable_changed"):
        load_workers(root)
