from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import deployment_endpoint
import pytest
from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)


def _proxy_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 8100,
        "url": "http://127.0.0.1:8100",
        "api_key": "unit-test-secret",
        "model": "Kimi-K3",
        "proxy_jobid": "12345",
        "extras": {
            "proxy_type": "litellm",
            "prometheus_port": 8101,
            "sticky": True,
            "sticky_ttl": 900,
            "redis_port": 6379,
            "future_scalar": 1.5,
        },
    }
    payload.update(overrides)
    return payload


def _deployment_files(tmp_path: Path, *, raw: str | None = None) -> tuple[Path, Path]:
    deployment = tmp_path / "test-deployment"
    deployment.mkdir()
    spec = deployment / "spec.yaml"
    spec.write_text("immutable: true\n")
    proxy_info = deployment / "proxy_info.json"
    proxy_info.write_text(raw if raw is not None else json.dumps(_proxy_payload()))
    return proxy_info, spec


def _load(proxy_info: Path, spec: Path, **overrides: Any) -> deployment_endpoint.DeploymentEndpoint:
    values: dict[str, Any] = {
        "deployment_id": "test-deployment",
        "expected_model": "Kimi-K3",
        "deployment_spec": spec,
    }
    values.update(overrides)
    return load_deployment_endpoint(proxy_info, **values)


def test_loads_actual_schema_into_secret_free_deterministic_binding(tmp_path: Path) -> None:
    proxy_info, spec = _deployment_files(tmp_path)

    endpoint = _load(proxy_info, spec)
    repeated = _load(
        proxy_info,
        spec,
        expected_proxy_info_sha256=endpoint.proxy_info_sha256,
    )

    assert endpoint.binding == repeated.binding
    assert endpoint.proxy_base_url == "http://127.0.0.1:8100"
    assert endpoint.client_base_url == "http://127.0.0.1:8100/v1"
    assert endpoint.api_key == "unit-test-secret"
    assert endpoint.routing_metadata == {
        "proxy_type": "litellm",
        "redis_port": 6379,
        "sticky": True,
        "sticky_ttl": 900,
    }
    assert endpoint.binding == validate_endpoint_binding(endpoint.binding)
    serialized = json.dumps(endpoint.binding, sort_keys=True)
    assert "http://127.0.0.1:8100" not in serialized
    assert "unit-test-secret" not in serialized
    assert hashlib.sha256(b"unit-test-secret").hexdigest() not in serialized
    assert "unit-test-secret" not in repr(endpoint)
    assert "http://127.0.0.1:8100" not in repr(endpoint)


def test_authority_binds_endpoint_metadata_but_not_the_api_key(tmp_path: Path) -> None:
    proxy_info, spec = _deployment_files(tmp_path)
    baseline = _load(proxy_info, spec)

    rotated_key = _proxy_payload(api_key="different-unit-test-secret")
    proxy_info.write_text(json.dumps(rotated_key))
    rotated = _load(proxy_info, spec)
    assert rotated.authority_sha256 == baseline.authority_sha256
    assert rotated.proxy_info_sha256 != baseline.proxy_info_sha256

    changed_routing = _proxy_payload()
    changed_routing["extras"]["sticky_ttl"] = 901
    proxy_info.write_text(json.dumps(changed_routing))
    assert _load(proxy_info, spec).authority_sha256 != baseline.authority_sha256

    changed_url = _proxy_payload(host="127.0.0.2", url="http://127.0.0.2:8100")
    proxy_info.write_text(json.dumps(changed_url))
    assert _load(proxy_info, spec).authority_sha256 != baseline.authority_sha256

    changed_job = _proxy_payload(proxy_jobid="54321")
    proxy_info.write_text(json.dumps(changed_job))
    assert _load(proxy_info, spec).authority_sha256 != baseline.authority_sha256


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8100/?",
        "http://127.0.0.1:8100/#",
    ],
)
def test_rejects_empty_query_or_fragment_delimiters(tmp_path: Path, url: str) -> None:
    proxy_info, spec = _deployment_files(
        tmp_path,
        raw=json.dumps(_proxy_payload(url=url)),
    )

    with pytest.raises(EndpointBindingError, match="^proxy_info_malformed$"):
        _load(proxy_info, spec)


@pytest.mark.parametrize(
    "raw",
    [
        '{"host":"127.0.0.1","host":"localhost"}',
        (
            '{"host":"127.0.0.1","port":8100,"url":"http://127.0.0.1:8100",'
            '"api_key":"unit-test-secret","model":"Kimi-K3","proxy_jobid":"12345",'
            '"extras":{"sticky_ttl":NaN}}'
        ),
        (
            '{"host":"127.0.0.1","port":8100,"url":"http://127.0.0.1:8100",'
            '"api_key":"unit-test-secret","model":"Kimi-K3","proxy_jobid":"12345",'
            '"extras":{"future_scalar":1e9999}}'
        ),
    ],
)
def test_rejects_duplicate_keys_and_nonfinite_values(tmp_path: Path, raw: str) -> None:
    proxy_info, spec = _deployment_files(tmp_path, raw=raw)

    with pytest.raises(EndpointBindingError, match="^proxy_info_malformed$"):
        _load(proxy_info, spec)


def test_rejects_nonlocal_paths_and_wrong_expected_hash(tmp_path: Path) -> None:
    proxy_info, spec = _deployment_files(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    other_spec = other / "spec.yaml"
    other_spec.write_text("immutable: true\n")

    with pytest.raises(EndpointBindingError, match="^proxy_info_not_deployment_local$"):
        _load(proxy_info, other_spec)
    with pytest.raises(EndpointBindingError, match="^proxy_info_sha256_mismatch$"):
        _load(proxy_info, spec, expected_proxy_info_sha256="0" * 64)


def test_endpoint_binding_rejects_boolean_schema_version(tmp_path: Path) -> None:
    proxy_info, spec = _deployment_files(tmp_path)
    binding = _load(proxy_info, spec).binding
    binding["schema_version"] = True

    with pytest.raises(EndpointBindingError, match="^invalid_endpoint_binding$"):
        validate_endpoint_binding(binding)


def test_detects_file_metadata_change_during_single_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_info, spec = _deployment_files(tmp_path)
    real_fstat = os.fstat
    calls = 0

    def unstable_fstat(descriptor: int) -> Any:
        nonlocal calls
        observed = real_fstat(descriptor)
        calls += 1
        if calls != 2:
            return observed
        return SimpleNamespace(
            st_dev=observed.st_dev,
            st_ino=observed.st_ino,
            st_size=observed.st_size,
            st_mtime_ns=observed.st_mtime_ns + 1,
            st_mode=observed.st_mode,
        )

    monkeypatch.setattr(deployment_endpoint.os, "fstat", unstable_fstat)

    with pytest.raises(EndpointBindingError, match="^proxy_info_unstable$"):
        _load(proxy_info, spec)
