from __future__ import annotations

import hashlib
import json
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
    root.mkdir()
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

    (root / "proxy_litellm_config.yaml").write_text("changed\n")
    with pytest.raises(DirectKimiWorkerError, match="source_generation_mismatch"):
        validate_saved_manifest(manifest_path)


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

    receipt = certify_router(manifest_path, digest, 24, stats, output)
    assert json.loads(output.read_text()) == receipt
    assert receipt["request_timeout_seconds"] == 43_200
    assert receipt["retries"] == 0
    assert receipt["implementation"] == "direct-kimi-transparent-v1"
    assert receipt["chat_requests"] == 1
    with pytest.raises(DirectKimiWorkerError, match="active_worker_count_mismatch"):
        certify_router(manifest_path, digest, 23, stats, generation / "bad.json")


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
