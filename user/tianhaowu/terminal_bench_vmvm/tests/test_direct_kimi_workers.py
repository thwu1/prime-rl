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
    prepare_generation,
    validate_saved_manifest,
)


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
    manifest_path = generation / "manifest.json"
    urls_path = generation / "urls.private.txt"
    ports_path = generation / "ports.private.txt"

    manifest = prepare_generation(root, generation, manifest_path, urls_path, ports_path)
    assert len(manifest["workers"]) == 24
    assert manifest["router"]["policy"] == "consistent_hash"
    assert manifest["router"]["implementation"] == "direct-kimi-transparent-v1"
    assert len(manifest["router"]["implementation_sha256"]) == 64
    assert manifest["router"]["request_id_headers"] == ["x-session-id"]
    assert manifest["router"]["request_timeout_seconds"] == 43_200
    assert manifest["router"]["retries"] == 0
    assert "worker-0" not in manifest_path.read_text()
    assert len(urls_path.read_text().splitlines()) == 24
    assert validate_saved_manifest(manifest_path) == manifest
    assert stat.S_IMODE(generation.stat().st_mode) == 0o700
    for path in (manifest_path, urls_path, ports_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1

    (root / "proxy_litellm_config.yaml").write_text("changed\n")
    with pytest.raises(DirectKimiWorkerError, match="source_generation_mismatch"):
        validate_saved_manifest(manifest_path)


def test_direct_kimi_atomic_publication_is_exclusive(tmp_path: Path) -> None:
    output = tmp_path / "private" / "receipt.json"
    direct_kimi_workers._atomic_write(output, b"first\n", exclusive=True)
    direct_kimi_workers._atomic_write(output, b"first\n", exclusive=True)
    with pytest.raises(DirectKimiWorkerError, match="output_already_exists"):
        direct_kimi_workers._atomic_write(output, b"second\n", exclusive=True)

    assert output.read_bytes() == b"first\n"
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert {entry.name for entry in output.parent.iterdir()} == {output.name}


def test_direct_kimi_atomic_publication_precommit_failure_leaves_only_quarantine_and_retry_succeeds(
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
    assert not output.exists()
    residues = list(output.parent.glob(".receipt.json.stage-*"))
    assert len(residues) == 1
    assert stat.S_IMODE(residues[0].stat().st_mode) == 0o600

    direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)
    assert output.read_bytes() == b"value\n"


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


def test_direct_kimi_atomic_publication_detects_stage_name_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_rename = direct_kimi_workers._rename_noreplace

    def substitute_after_rename(parent: int, source: str, destination: str) -> None:
        original_rename(parent, source, destination)
        os.rename(destination, ".owned-after-commit", src_dir_fd=parent, dst_dir_fd=parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        replacement = os.open(destination, flags, 0o600, dir_fd=parent)
        try:
            os.write(replacement, b"replacement\n")
            os.fsync(replacement)
        finally:
            os.close(replacement)

    monkeypatch.setattr(direct_kimi_workers, "_rename_noreplace", substitute_after_rename)
    with pytest.raises(DirectKimiWorkerError, match="output_publication_indeterminate"):
        direct_kimi_workers._atomic_write(output, b"value\n", exclusive=True)

    assert output.read_bytes() == b"replacement\n"
    assert (output.parent / ".owned-after-commit").read_bytes() == b"value\n"


def test_direct_kimi_atomic_publication_detects_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "receipt.json"
    original_rename = direct_kimi_workers._rename_noreplace

    def replace_parent_after_rename(parent: int, source: str, destination: str) -> None:
        original_rename(parent, source, destination)
        output.parent.rename(tmp_path / "held-private")
        output.parent.mkdir(mode=0o700)

    monkeypatch.setattr(direct_kimi_workers, "_rename_noreplace", replace_parent_after_rename)
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
    manifest_path = generation / "manifest.json"
    prepare_generation(
        root,
        generation,
        manifest_path,
        generation / "urls.private.txt",
        generation / "ports.private.txt",
    )
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    output = generation / "router.json"
    stats = generation / "router-stats.json"
    stats.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "direct-kimi-transparent-router",
                "implementation": "direct-kimi-transparent-v1",
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
    assert receipt["implementation"] == "direct-kimi-transparent-v1"
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


def test_direct_kimi_run_binding_rejects_nonprivate_inputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    identity, invocations, provenance, _digest = _binding_files(run_dir)
    provenance.chmod(0o644)

    with pytest.raises(DirectKimiWorkerError, match="run_binding_invalid"):
        direct_kimi_workers._run_binding(identity, invocations, provenance)


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
