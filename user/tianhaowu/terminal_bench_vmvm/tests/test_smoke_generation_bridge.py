from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import audit_tb4_results
import create_smoke_generation_bridge as bridge
import eval_run_identity
import launch_tb4_shard_wave
import pytest
import smoke_qualification as qualification
from inference_route_generation import canonical_backend_identifier


def _generation(*backends: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": "101",
            "started_at": "2026-09-17T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": "102",
            "first_ready_at": "2026-09-17T00:01:00Z",
        },
        "routes": [
            {
                "slurm_job_id": str(200 + index),
                "started_at": f"2026-09-17T00:{10 + index:02d}:00Z",
                "backend_sha256": canonical_backend_identifier(backend),
            }
            for index, backend in enumerate(backends)
        ],
    }


def _readiness(generation: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe": {
            "routes": [
                {
                    "backend": route["backend_sha256"],
                    "representative_session_id": f"safe-session-{index}",
                }
                for index, route in enumerate(generation["routes"])
            ]
        }
    }


def _reasoning_message(**extra: Any) -> dict[str, Any]:
    return {"role": "assistant", "reasoning_content": "private reasoning", **extra}


class FakeTransport:
    def __init__(self, backends: Mapping[str, str], *, wrong_model: bool = False) -> None:
        self.backends = backends
        self.wrong_model = wrong_model
        self.requests: list[bytes] = []

    def request(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> bridge.HttpResponse:
        assert timeout > 0
        self.requests.append(body)
        request = json.loads(body)
        session_id = headers[bridge.SESSION_HEADERS[0]]
        backend = self.backends[session_id]
        model = "wrong-model" if self.wrong_model else request["model"]
        if request["tool_choice"] == "required":
            nonce = request["tools"][0]["function"]["parameters"]["properties"]["nonce"]["const"]
            message = _reasoning_message(
                content=None,
                tool_calls=[
                    {
                        "id": f"call-{session_id}",
                        "type": "function",
                        "function": {
                            "name": bridge.TOOL_NAME,
                            "arguments": json.dumps({"nonce": nonce}, separators=(",", ":")),
                        },
                    }
                ],
            )
        else:
            tool_result = json.loads(request["messages"][-1]["content"])
            message = _reasoning_message(content=tool_result["marker"])
        response = json.dumps(
            {
                "model": model,
                "choices": [
                    {
                        "message": message,
                        "finish_reason": ("tool_calls" if request["tool_choice"] == "required" else "stop"),
                    }
                ],
            },
            separators=(",", ":"),
        ).encode()
        return bridge.HttpResponse(
            status_code=200,
            headers={bridge.BACKEND_HEADER: backend, "x-litellm-attempted-retries": "0"},
            body=response,
        )


def test_generation_probe_round_trips_every_backend_without_raw_content() -> None:
    raw_backends = ("http://worker-a:8000/v1", "http://worker-b:8000/v1")
    generation = _generation(*raw_backends)
    sessions = {f"safe-session-{index}": backend for index, backend in enumerate(raw_backends)}
    transport = FakeTransport(sessions)
    runtime = bridge.ProbeRuntime(
        base_url="http://proxy.invalid/v1",
        api_key="unit-test-secret",
        endpoint_authority_sha256="a" * 64,
    )

    result = bridge.run_generation_probe(
        runtime,
        model="Kimi-K3",
        generation=generation,
        readiness_payload=_readiness(generation),
        timeout=10,
        transport=transport,
        nonce_factory=lambda: "b" * 32,
    )

    assert result["ok"] is True
    assert result["coverage"]["tested_routes"] == 2
    assert len(result["requests"]) == 4
    assert {item["phase"] for item in result["requests"]} == {"tool_call", "tool_result"}
    encoded = json.dumps(result, sort_keys=True)
    assert "unit-test-secret" not in encoded
    assert "private reasoning" not in encoded
    assert "GENERATION_BRIDGE_OK" not in encoded
    assert "b" * 32 not in encoded
    assert (
        result["probe_sha256"]
        == hashlib.sha256(
            qualification.canonical_json({key: value for key, value in result.items() if key != "probe_sha256"})
        ).hexdigest()
    )


def test_generation_probe_fails_closed_on_model_and_backend_changes() -> None:
    backend = "http://worker-a:8000/v1"
    generation = _generation(backend)
    runtime = bridge.ProbeRuntime(
        base_url="http://proxy.invalid/v1",
        api_key="secret",
        endpoint_authority_sha256="a" * 64,
    )
    with pytest.raises(bridge.GenerationBridgeError, match="response_model"):
        bridge.run_generation_probe(
            runtime,
            model="Kimi-K3",
            generation=generation,
            readiness_payload=_readiness(generation),
            transport=FakeTransport({"safe-session-0": backend}, wrong_model=True),
            nonce_factory=lambda: "c" * 32,
        )
    with pytest.raises(bridge.GenerationBridgeError, match="backend_changed"):
        bridge.run_generation_probe(
            runtime,
            model="Kimi-K3",
            generation=generation,
            readiness_payload=_readiness(generation),
            transport=FakeTransport({"safe-session-0": "http://other:8000/v1"}),
            nonce_factory=lambda: "c" * 32,
        )


def _artifact(path: Path, raw: bytes) -> qualification.Artifact:
    path.write_bytes(raw)
    return qualification.Artifact(
        path=path.resolve(),
        sha256=hashlib.sha256(raw).hexdigest(),
        raw=raw,
    )


def _endpoint(proxy: qualification.Artifact) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "deployment_local_proxy_info",
        "proxy_info": proxy.record,
        "authority_sha256": "d" * 64,
    }


def _probe(endpoint: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    backend = generation["routes"][0]["backend_sha256"]
    body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "endpoint_authority_sha256": endpoint["authority_sha256"],
        "serving_route_generation_sha256": qualification.sha256_bytes(qualification.canonical_json(generation)),
        "request_contract": {
            "provider_route": "/chat/completions",
            "model": "Kimi-K3",
            "reasoning_effort": "max",
            "chat_template_kwargs": {
                "enable_thinking": True,
                "preserve_thinking": True,
            },
            "tool_name": bridge.TOOL_NAME,
            "tool_choice": {"tool_call": "required", "tool_result": "none"},
            "temperature": 0,
            "max_tokens": bridge.PROBE_MAX_TOKENS,
        },
        "coverage": {
            "expected_routes": 1,
            "tested_routes": 1,
            "backends": [backend],
            "round_trips_per_backend": 1,
        },
        "requests": [
            {
                "phase": phase,
                "backend_sha256": backend,
                "request_sha256": character * 64,
                "response_sha256": character.upper().lower() * 64,
                "status_code": 200,
                "response_model": "Kimi-K3",
                "reasoning_nonempty": True,
                "tool_call_valid": phase == "tool_call",
            }
            for phase, character in (("tool_call", "a"), ("tool_result", "b"))
        ],
    }
    return {**body, "probe_sha256": qualification.sha256_bytes(qualification.canonical_json(body))}


def test_bridge_payload_is_separate_self_hashed_and_worker_only(tmp_path: Path) -> None:
    spec = _artifact(tmp_path / "spec.yaml", b"spec\n")
    proxy = _artifact(tmp_path / "proxy_info.json", b"opaque-secret-metadata\n")
    source_smoke = _artifact(tmp_path / "smoke_checkpoint.json", b"{}\n")
    source_readiness = _artifact(tmp_path / "source-readiness.json", b"{}\n")
    target_readiness = _artifact(tmp_path / "target-readiness.json", b"{}\n")
    endpoint = _endpoint(proxy)
    source_generation = _generation("http://worker-old:8000/v1")
    target_generation = _generation("http://worker-new:8000/v1")
    policy = {"schema_version": 1}
    evidence = {"source": {}, "evaluator_source": {"opaque": "bound"}}

    payload = qualification.build_bridge_payload(
        deployment_id="deployment-test",
        deployment_spec=spec,
        model="Kimi-K3",
        proxy_policy=policy,
        source_smoke=source_smoke,
        source_readiness=source_readiness,
        source_endpoint=endpoint,
        source_generation=source_generation,
        target_readiness=target_readiness,
        target_endpoint=endpoint,
        target_generation=target_generation,
        evaluator_evidence=evidence,
        probe=_probe(endpoint, target_generation),
    )

    assert payload["schema_version"] == 2
    assert payload["artifacts"]["source_smoke_checkpoint"] == source_smoke.record
    assert payload["source"]["serving_route_generation"] == source_generation
    assert payload["target"]["serving_route_generation"] == target_generation
    assert payload["smoke_qualification_sha256"] == qualification.sha256_bytes(
        qualification.canonical_json(
            {key: value for key, value in payload.items() if key != "smoke_qualification_sha256"}
        )
    )
    assert b"opaque-secret-metadata" not in qualification.canonical_json(payload)


def test_bridge_validator_recurses_and_rejects_proxy_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _artifact(tmp_path / "spec.yaml", b"spec\n")
    proxy = _artifact(tmp_path / "proxy_info.json", b"opaque-secret-metadata\n")
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    source_smoke = _artifact(
        source_run / "smoke_checkpoint.json",
        b'{"schema_version":1}\n',
    )
    source_smoke.path.chmod(0o444)
    source_readiness = _artifact(tmp_path / "source-readiness.json", b"{}\n")
    target_readiness = _artifact(tmp_path / "target-readiness.json", b"{}\n")
    endpoint = _endpoint(proxy)
    source_generation = _generation("http://worker-old:8000/v1")
    target_generation = _generation("http://worker-new:8000/v1")
    policy = {"schema_version": 1}
    evidence = {"source": {}, "evaluator_source": {"opaque": "bound"}}
    calls: list[str] = []
    monkeypatch.setattr(
        qualification,
        "validate_readiness",
        lambda artifact, **_kwargs: (
            source_generation if artifact.path == source_readiness.path else target_generation,
            policy,
        ),
    )
    monkeypatch.setattr(
        qualification,
        "load_deployment_endpoint",
        lambda *_args, **_kwargs: SimpleNamespace(binding=endpoint),
    )
    monkeypatch.setattr(
        qualification,
        "_evaluator_source_evidence",
        lambda _source: evidence["evaluator_source"],
    )

    def validate_source(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append("source")
        return {}, evidence

    monkeypatch.setattr(qualification, "validate_v1_smoke", validate_source)
    payload = qualification.build_bridge_payload(
        deployment_id="deployment-test",
        deployment_spec=spec,
        model="Kimi-K3",
        proxy_policy=policy,
        source_smoke=source_smoke,
        source_readiness=source_readiness,
        source_endpoint=endpoint,
        source_generation=source_generation,
        target_readiness=target_readiness,
        target_endpoint=endpoint,
        target_generation=target_generation,
        evaluator_evidence=evidence,
        probe=_probe(endpoint, target_generation),
    )
    raw = json.dumps(payload, sort_keys=True).encode() + b"\n"
    bridge_artifact = _artifact(tmp_path / "bridge.json", raw)
    bridge_artifact.path.chmod(0o444)

    observed = qualification._validate_bridge(
        bridge_artifact,
        payload,
        deployment_id="deployment-test",
        deployment_spec=spec,
        readiness=target_readiness,
        endpoint=endpoint,
        generation=target_generation,
        proxy_policy=policy,
        model="Kimi-K3",
        identity_loader=None,
    )

    assert calls == ["source"]
    assert observed.source_smoke == source_smoke
    assert observed.target_generation == target_generation

    rotated_proxy = _artifact(tmp_path / "rotated-proxy.json", b"rotated\n")
    tampered = json.loads(json.dumps(payload))
    tampered["artifacts"]["proxy_info"] = rotated_proxy.record
    body = {key: value for key, value in tampered.items() if key != "smoke_qualification_sha256"}
    tampered["smoke_qualification_sha256"] = qualification.sha256_bytes(qualification.canonical_json(body))
    with pytest.raises(qualification.SmokeQualificationError, match="target_mismatch"):
        qualification._validate_bridge(
            bridge_artifact,
            tampered,
            deployment_id="deployment-test",
            deployment_spec=spec,
            readiness=target_readiness,
            endpoint=endpoint,
            generation=target_generation,
            proxy_policy=policy,
            model="Kimi-K3",
            identity_loader=None,
        )


def test_probe_validator_rejects_duplicate_phase_and_tampered_hash() -> None:
    generation = _generation("http://worker-new:8000/v1")
    proxy = qualification.Artifact(Path("/tmp/proxy"), "a" * 64)
    endpoint = _endpoint(proxy)
    probe = _probe(endpoint, generation)
    qualification._validate_probe(
        probe,
        endpoint=endpoint,
        generation=generation,
        model="Kimi-K3",
    )
    duplicate = json.loads(json.dumps(probe))
    duplicate["requests"][1]["phase"] = "tool_call"
    duplicate_body = {key: value for key, value in duplicate.items() if key != "probe_sha256"}
    duplicate["probe_sha256"] = qualification.sha256_bytes(qualification.canonical_json(duplicate_body))
    with pytest.raises(qualification.SmokeQualificationError, match="probe_invalid"):
        qualification._validate_probe(
            duplicate,
            endpoint=endpoint,
            generation=generation,
            model="Kimi-K3",
        )
    boolean_count = json.loads(json.dumps(probe))
    boolean_count["coverage"]["expected_routes"] = True
    boolean_body = {key: value for key, value in boolean_count.items() if key != "probe_sha256"}
    boolean_count["probe_sha256"] = qualification.sha256_bytes(qualification.canonical_json(boolean_body))
    with pytest.raises(qualification.SmokeQualificationError, match="probe_invalid"):
        qualification._validate_probe(
            boolean_count,
            endpoint=endpoint,
            generation=generation,
            model="Kimi-K3",
        )
    probe["probe_sha256"] = "0" * 64
    with pytest.raises(qualification.SmokeQualificationError, match="probe_invalid"):
        qualification._validate_probe(
            probe,
            endpoint=endpoint,
            generation=generation,
            model="Kimi-K3",
        )


def test_strict_json_rejects_duplicates_and_write_once_never_overwrites(tmp_path: Path) -> None:
    assert not qualification._same_json({"typed": True}, {"typed": 1})
    duplicate = _artifact(tmp_path / "duplicate.json", b'{"a":1,"a":2}\n')
    with pytest.raises(qualification.SmokeQualificationError, match="duplicate_key"):
        qualification.load_json_artifact(duplicate, label="duplicate")

    output = tmp_path / "bridge.json"
    bridge._write_once(output, {"schema_version": 2})
    assert output.stat().st_mode & 0o777 == 0o444
    bridge._write_once(output, {"schema_version": 2})
    with pytest.raises(bridge.GenerationBridgeError, match="already_exists"):
        bridge._write_once(output, {"schema_version": 3})


def test_worker_only_rotation_rejects_proxy_or_coordinator_change() -> None:
    source = _generation("http://worker-old:8000/v1")
    target = _generation("http://worker-new:8000/v1")
    assert qualification._worker_only_rotation(source, target)
    changed = json.loads(json.dumps(target))
    changed["proxy"]["slurm_job_id"] = "999"
    assert not qualification._worker_only_rotation(source, changed)
    changed = json.loads(json.dumps(target))
    changed["coordinator"]["slurm_job_id"] = "999"
    assert not qualification._worker_only_rotation(source, changed)
    assert not qualification._worker_only_rotation(source, source)


def test_target_evaluator_requires_same_source_config_and_contract(tmp_path: Path) -> None:
    workflow = tmp_path / "user/tianhaowu/terminal_bench_vmvm"
    package = workflow / "terminal_bench_vmvm"
    vmvm = tmp_path / "environments/vmvm_tb_v2/vmvm_tb_v2"
    package.mkdir(parents=True)
    vmvm.mkdir(parents=True)
    (package / "taskset.py").write_text("VALUE = 1\n")
    (vmvm / "runtime.py").write_text("VALUE = 2\n")
    (workflow / "run_eval.sbatch").write_text("#!/bin/bash\n")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """model = "Kimi-K3"

[client]
type = "eval"
api_key_var = "OPENAI_API_KEY"
capture_model_io = true
outbound_body_denylist = ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
timeout = 7200
connect_timeout = 120

[sampling]
temperature = 1.0
top_p = 1.0
max_tokens = 32768
reasoning_effort = "max"
chat_template_kwargs = { enable_thinking = true, preserve_thinking = true }

[taskset]
id = "terminal-bench-vmvm"
image_prefix = "registry/terminal-bench"
image_tag = "pinned"
ignore_dockerfile = true
use_declared_images = true
enable_compose = true
verifier_runtime_retries = 2

[harness]
id = "mini-swe-agent"
version = "2.2.8"
config_file = "mini"
config_overrides = [
  "agent.step_limit=8",
  "environment.environment_class=local",
  "environment.timeout=600",
  "model.model_kwargs.drop_params=true",
  "model.model_kwargs.parallel_tool_calls=true",
]

[harness.env]
MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT = "10"

[harness.runtime]
type = "vmvm"
session_timeout = 32400
tenant_id = "tenant"
lease_ttl = "60s"

[retries.rollout]
max_retries = 2
include = ["ProviderError", "SandboxError", "TunnelError"]
"""
    )
    source = {
        "project_root": str(tmp_path.resolve()),
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "0" * 64,
        "verifiers_commit": "2" * 40,
        "verifiers_tree_sha256": "0" * 64,
        "renderers_commit": "3" * 40,
        "renderers_tree_sha256": "0" * 64,
        "vmvm_tb_v2_sha256": "4" * 64,
    }
    contract = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "capture_model_io": True,
    }
    config_record = {
        "path": str(config_path.resolve()),
        "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    parsed = tomllib.loads(config_path.read_text())
    evidence = {
        "source": source,
        "evaluator_source": qualification._evaluator_source_evidence(source),
        "source_config": {"path": str(config_path.resolve()), "sha256": "a" * 64},
        "resolved_config": config_record,
        "identity_contract": contract,
        "model_io_contract": qualification._expected_model_contract("Kimi-K3"),
        "tool_contract": qualification._tool_contract(parsed),
    }
    identity = {
        "role": "tb4",
        "source": source,
        "config": {"source": evidence["source_config"], "resolved": config_record},
        "contract": contract,
    }

    qualification.validate_target_evaluator_compatibility(identity, evidence)

    changed = json.loads(json.dumps(identity))
    changed["source"]["verifiers_commit"] = "9" * 40
    with pytest.raises(qualification.SmokeQualificationError, match="source_mismatch"):
        qualification.validate_target_evaluator_compatibility(changed, evidence)
    (vmvm / "runtime.py").write_text("VALUE = 3\n")
    with pytest.raises(qualification.SmokeQualificationError, match="contract_mismatch"):
        qualification.validate_target_evaluator_compatibility(identity, evidence)


def test_launcher_dispatches_schema_two_only_through_shared_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = tmp_path / "bridge.json"
    smoke_raw = b'{"schema_version":2}\n'
    smoke_path.write_bytes(smoke_raw)
    opaque = _artifact(tmp_path / "opaque", b"opaque")
    smoke = launch_tb4_shard_wave.PinnedArtifact(
        path=smoke_path.resolve(),
        sha256=hashlib.sha256(smoke_raw).hexdigest(),
        raw=smoke_raw,
    )
    pinned = launch_tb4_shard_wave.PinnedArtifact(
        path=opaque.path,
        sha256=opaque.sha256,
        raw=None,
    )
    generation = _generation("http://worker-new:8000/v1")
    calls: list[dict[str, Any]] = []

    def validate(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(target_generation=generation)

    monkeypatch.setattr(launch_tb4_shard_wave, "validate_smoke_qualification", validate)
    digest = launch_tb4_shard_wave._validate_generation_bindings(
        deployment_id="deployment-test",
        deployment_spec=pinned,
        readiness=pinned,
        proxy_info=pinned,
        smoke=smoke,
    )

    assert len(calls) == 1
    assert digest == qualification.sha256_bytes(qualification.canonical_json(generation))


def test_eval_identity_dispatches_schema_two_bridge_through_shared_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 7200\n      num_retries: 0\n")
    proxy_config = deployment_dir / "proxy_litellm_config.yaml"
    proxy_config.write_text("litellm_settings:\n  request_timeout: 7200\n  num_retries: 0\n")
    proxy = deployment_dir / "proxy_info.json"
    proxy.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8100,
                "url": "http://127.0.0.1:8100",
                "api_key": "secret",
                "model": "Kimi-K3",
                "proxy_jobid": "102",
                "extras": {"proxy_type": "litellm", "sticky": True, "redis_port": 6379},
            }
        )
        + "\n"
    )
    endpoint = eval_run_identity.load_deployment_endpoint(
        proxy,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=hashlib.sha256(proxy.read_bytes()).hexdigest(),
    ).binding
    generation = _generation("http://worker-new:8000/v1")
    policy = {
        "schema_version": 1,
        "request_timeout": 7200,
        "num_retries": 0,
        "proxy_litellm_config": {
            "path": str(proxy_config.resolve()),
            "sha256": hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
        },
    }
    readiness_body = {
        "schema_version": 1,
        "state": "passed",
        "deployment": deployment_id,
        "expected_routes": 1,
        "observed_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "endpoint": endpoint,
        "proxy_policy": policy,
        "serving_route_generation": generation,
        "last_status": {
            "schema_version": 4,
            "deployment_id": deployment_id,
            "phase": "serving",
            "desired": 1,
            "ready": 1,
            "running_not_ready": 0,
            "pending": 0,
            "coordinator_incarnation": generation["coordinator"],
            "coord_ticks_completed": 2,
            "serving_route_generation": generation,
        },
        "probe": {
            "ok": True,
            "endpoint_authority_sha256": endpoint["authority_sha256"],
            "coverage": {
                "ok": True,
                "expected_routes": 1,
                "discovered_routes": 1,
                "backends": [generation["routes"][0]["backend_sha256"]],
            },
        },
    }
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps(readiness_body) + "\n")
    smoke = tmp_path / "bridge.json"
    smoke.write_text('{"schema_version":2}\n')
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        eval_run_identity,
        "validate_smoke_qualification",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )
    args = SimpleNamespace(
        role="tb4",
        deployment_id=deployment_id,
        deployment_spec=spec,
        deployment_spec_sha256=hashlib.sha256(spec.read_bytes()).hexdigest(),
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=hashlib.sha256(readiness.read_bytes()).hexdigest(),
        smoke_checkpoint=smoke,
        smoke_checkpoint_sha256=hashlib.sha256(smoke.read_bytes()).hexdigest(),
        promotion_certificate=None,
        promotion_certificate_sha256=None,
        routing_deployment_id=None,
        expected_model="Kimi-K3",
    )

    deployment = eval_run_identity._checkpoint_identity(args, endpoint)

    assert len(calls) == 1
    assert deployment["smoke_checkpoint"]["path"] == str(smoke.resolve())


def test_tb4_audit_dispatches_schema_two_bridge_through_shared_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _artifact(tmp_path / "spec.yaml", b"spec")
    readiness = _artifact(tmp_path / "readiness.json", b"{}")
    smoke = _artifact(tmp_path / "bridge.json", b'{"schema_version":2}\n')
    proxy = _artifact(tmp_path / "proxy_info.json", b"opaque")
    generation = _generation("http://worker-new:8000/v1")
    endpoint = _endpoint(proxy)
    calls: list[dict[str, Any]] = []

    def validate(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(target_generation=generation)

    monkeypatch.setattr(audit_tb4_results, "validate_smoke_qualification", validate)
    identity = {
        "contract": {"model": "Kimi-K3"},
        "deployment": {
            "id": "deployment-test",
            "spec": spec.record,
            "readiness_checkpoint": readiness.record,
            "smoke_checkpoint": smoke.record,
            "serving_route_generation": generation,
        },
    }

    observed_readiness, observed_smoke = audit_tb4_results._validate_deployment_checkpoints(
        identity,
        endpoint,
    )

    assert len(calls) == 1
    assert observed_readiness == (readiness.path, readiness.sha256)
    assert observed_smoke == (smoke.path, smoke.sha256)
