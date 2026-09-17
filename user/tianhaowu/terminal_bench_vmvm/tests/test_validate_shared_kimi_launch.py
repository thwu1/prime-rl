from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping

import pytest

SERVER_DIR = Path(__file__).parents[1] / "configs" / "eval" / "servers" / "cpu-132-021_8103"
sys.path.insert(0, str(SERVER_DIR))

from validate_launch import (  # noqa: E402
    EXPECTED_CONFIG_FILE,
    EXPECTED_HTTP_CONCURRENCY,
    EXPECTED_ROLLOUT_CONCURRENCY,
    EXPECTED_ROUTES,
    EXPECTED_WAITING_REQUESTS,
    HttpResponse,
    ProxyMetadata,
    SharedKimiValidationError,
    validate_deployment,
    validate_eval_config,
    validate_runtime_metadata,
)


class FakeMetadataTransport:
    def __init__(self, *, healthy: int = EXPECTED_ROUTES, unhealthy: int = 0) -> None:
        self.healthy = healthy
        self.unhealthy = unhealthy
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, headers, timeout))
        if url.endswith("/v1/models"):
            payload = {"data": [{"id": "Kimi-K3"}]}
        else:
            payload = {
                "healthy_count": self.healthy,
                "unhealthy_count": self.unhealthy,
            }
        return HttpResponse(200, json.dumps(payload).encode())


def _deployment(tmp_path: Path) -> tuple[Path, Path, str, str]:
    root = tmp_path / "shared-kimi-k3"
    endpoints = root / "endpoints"
    endpoints.mkdir(parents=True)
    spec = b"fixture deployment spec\n"
    (root / "spec.yaml").write_bytes(spec)
    (root / "proxy_config.json").write_text(
        json.dumps(
            {
                "pixi_env": "proxy-litellm-x86/test",
                "sticky": True,
                "sticky_ttl": 14_400,
            }
        )
    )
    proxy_url = "http://proxy.example:8103"
    proxy_info = root / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "url": proxy_url,
                "api_key": "test-secret-key",
                "model": "Kimi-K3",
                "host": "proxy.example",
                "port": 8103,
                "proxy_jobid": "12345",
                "extras": {
                    "proxy_type": "litellm",
                    "prometheus_port": 8103,
                    "sticky": True,
                    "sticky_ttl": 14_400,
                    "redis_port": 39191,
                },
            }
        )
    )
    for index in range(EXPECTED_ROUTES):
        (endpoints / f"{10_000 + index}.json").write_text(
            json.dumps(
                {
                    "host": f"worker-{index}",
                    "port": 19_000 + index,
                    "started_at": "2026-09-16T20:21:47Z",
                }
            )
        )
    return root, proxy_info, hashlib.sha256(spec).hexdigest(), proxy_url


def test_shared_kimi_deployment_and_runtime_metadata_pass(tmp_path: Path) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)

    proxy = validate_deployment(
        root,
        proxy_info,
        expected_spec_sha256=spec_sha256,
        expected_proxy_url=proxy_url,
    )
    transport = FakeMetadataTransport()
    validate_runtime_metadata(proxy, transport=transport)

    assert proxy.url == proxy_url
    assert proxy.proxy_info_sha256 == hashlib.sha256(proxy_info.read_bytes()).hexdigest()
    assert len(transport.calls) == 2
    assert all(call[1]["Authorization"] == "Bearer test-secret-key" for call in transport.calls)
    assert EXPECTED_ROLLOUT_CONCURRENCY == 64
    assert EXPECTED_HTTP_CONCURRENCY == EXPECTED_ROUTES == 24
    assert EXPECTED_WAITING_REQUESTS == 40


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("spec", "deployment_spec_hash_mismatch"),
        ("sticky", "proxy_extras_contract_mismatch"),
        ("endpoint", "endpoint_count_mismatch"),
    ],
)
def test_shared_kimi_deployment_metadata_fails_closed(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)
    if mutation == "spec":
        (root / "spec.yaml").write_text("changed\n")
    elif mutation == "sticky":
        value = json.loads(proxy_info.read_text())
        value["extras"]["sticky"] = False
        proxy_info.write_text(json.dumps(value))
    else:
        next((root / "endpoints").iterdir()).unlink()

    with pytest.raises(SharedKimiValidationError, match=f"^{error}$"):
        validate_deployment(
            root,
            proxy_info,
            expected_spec_sha256=spec_sha256,
            expected_proxy_url=proxy_url,
        )


def test_shared_kimi_runtime_rejects_degraded_route_count() -> None:
    proxy = ProxyMetadata(
        url="http://proxy.example:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
    )

    with pytest.raises(SharedKimiValidationError, match="^route_health_mismatch$"):
        validate_runtime_metadata(proxy, transport=FakeMetadataTransport(healthy=23, unhealthy=1))


def test_shared_kimi_runtime_errors_do_not_expose_credentials() -> None:
    class FailedTransport:
        def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
            raise RuntimeError(headers["Authorization"])

    proxy = ProxyMetadata(
        url="http://proxy.example:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
    )

    with pytest.raises(SharedKimiValidationError, match="^models_endpoint_invalid$") as captured:
        validate_runtime_metadata(proxy, transport=FailedTransport())
    assert "test-secret-key" not in str(captured.value)


def test_production_eval_config_matches_shared24_contract() -> None:
    project = Path(__file__).parents[4]

    validate_eval_config(project, project / EXPECTED_CONFIG_FILE)
