import base64
import copy
import fcntl
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import direct_kimi_workers as direct_workers
import kimi_tb4_provider_split as split
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _resource(
    *,
    cpu: int = 2,
    memory_gib: int = 4,
    disk_gib: int = 10,
    gpu: int = 0,
) -> dict[str, int]:
    return {
        "cpu_count": cpu,
        "memory_bytes": memory_gib * split.GIB,
        "disk_bytes": disk_gib * split.GIB,
        "gpu_count": gpu,
    }


def _manifest() -> dict:
    entries = []
    digest = "a" * 64
    for index in range(split.TOTAL_TASKS):
        if index < split.LEGACY_SANDOQ_TASKS:
            resources = _resource()
        elif index < split.LEGACY_SANDOQ_TASKS + 4:
            resources = _resource()
        elif index < split.CPU_TASKS:
            resources = _resource(memory_gib=8)
        else:
            resources = _resource(gpu=1)
        if index == split.LEGACY_SANDOQ_TASKS + 4:
            resources = _resource(cpu=16, memory_gib=8)
        elif index == split.LEGACY_SANDOQ_TASKS + 5:
            resources = _resource(memory_gib=16)
        elif index == split.LEGACY_SANDOQ_TASKS + 6:
            resources = _resource(memory_gib=8, disk_gib=50)
        requires_compose = split.LEGACY_SANDOQ_TASKS <= index < split.LEGACY_SANDOQ_TASKS + 11
        entries.append(
            {
                "task_id": f"opaque-case-{index:02d}",
                "images": {
                    "agent": f"registry.example/agent@sha256:{digest}",
                    "verifier": f"registry.example/verifier@sha256:{digest}",
                },
                "agent_resources": resources,
                "verifier_resources": dict(resources),
                "verifier_mode": "separate" if index % 2 else "shared",
                "runtime_requirements": {"compose": requires_compose},
            }
        )
    task_file = ("\n".join(entry["task_id"] for entry in entries) + "\n").encode()
    image_manifest = {
        "images": {entry["task_id"]: entry["images"] for entry in entries},
        "schema_version": 1,
        "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
    }
    return {
        "schema_version": split.MANIFEST_SCHEMA_VERSION,
        "kind": split.MANIFEST_KIND,
        "source": {
            "dataset_archive_sha256": split.CANONICAL_DATASET_ARCHIVE_SHA256,
            "dataset_content_sha256": split.CANONICAL_DATASET_CONTENT_SHA256,
            "image_manifest_sha256": hashlib.sha256(split.canonical_json(image_manifest)).hexdigest(),
            "task_file_sha256": hashlib.sha256(task_file).hexdigest(),
        },
        "entries": entries,
    }


@pytest.fixture(autouse=True)
def _synthetic_source_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _manifest()["source"]
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", source["image_manifest_sha256"])
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", source["task_file_sha256"])


def _manifest_file(tmp_path: Path) -> tuple[Path, str, tuple[split.ManifestEntry, ...]]:
    value = _manifest()
    body = split.canonical_json(value)
    path = tmp_path / "image-resource-manifest.json"
    _private_file(path, body)
    _value, entries = split.parse_manifest(body, hashlib.sha256(body).hexdigest())
    return path, hashlib.sha256(body).hexdigest(), entries


def _private_file(path: Path, body: bytes) -> None:
    path.write_bytes(body)
    path.chmod(0o600)


def _write_capacity_receipt(path: Path, body: bytes) -> None:
    _private_file(path, body)
    _private_file(
        path.with_name(f".{path.name}{split.FILE_COMMIT_SUFFIX}"),
        split.canonical_json(
            {
                "schema_version": 1,
                "kind": "private-file-complete",
                "state": "complete",
                "file": {
                    "name": path.name,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                },
            }
        ),
    )


def _identity(provider: str = "vmvm") -> dict:
    common_source = {
        "prime_rl_commit": "1" * 40,
        "verifiers_commit": "2" * 40,
        "renderers_commit": "3" * 40,
    }
    if provider == "vmvm":
        source = {**common_source, "vmvm_tb_v2_sha256": "4" * 64}
        environment = {
            "vacli_bin": "/bin/vacli",
            "lease_start_concurrency": 2,
            "lease_retries": 1,
            "max_pull_retries": 20,
            "image_pull_timeout_sec": 3600,
            "container_privileged": True,
        }
    else:
        source = {
            **common_source,
            "sandbox_provider": "sandoq",
            "sandoq_provider_commit": "4" * 40,
            "sandoq_provider_tree": "5" * 40,
            "sandoq_site_sha256": "6" * 64,
        }
        environment = {"environment": "oci-runner", "task_network": "public", "pool_size": 24}
    return {
        "source": source,
        "execution": {
            "runtime": {"type": provider},
            f"{provider}_environment": environment,
        },
    }


def _signed_capacity(
    tmp_path: Path,
    *,
    manifest_sha256: str,
    selector_sha256: str,
    identity: dict,
    identity_sha256: str,
    capacity: dict[str, int] | None = None,
    invocation_identity_sha256: str = "b" * 64,
    runtime_instance_nonce: str = "6" * 32,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[Path, str, Path, str]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_body = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path = tmp_path / "capacity-public.pem"
    public_path.write_bytes(public_body)
    public_sha256 = hashlib.sha256(public_body).hexdigest()
    issued_at = issued_at or datetime.now(timezone.utc)
    expires_at = expires_at or issued_at + split.CAPACITY_VALIDITY
    payload = {
        "schema_version": 2,
        "kind": split.CAPACITY_KIND,
        "state": "passed",
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "valid_for_seconds": split.CAPACITY_VALIDITY_SECONDS,
        "nonce": "7" * 32,
        "runtime_instance_nonce": runtime_instance_nonce,
        "provider": split._provider_name(identity),
        "environment_identity": split._environment_identity(identity),
        "eval_run_identity_sha256": identity_sha256,
        "invocation_identity_sha256": invocation_identity_sha256,
        "manifest_sha256": manifest_sha256,
        "selector_sha256": selector_sha256,
        "resource_multiplier": 2,
        "measurement_method": "in-runtime-cgroup-and-statvfs-v1",
        "measured_capacity": capacity
        or {
            "actual_cpu_count": 32,
            "outer_memory_bytes": 36 * split.GIB,
            "disk_available_bytes": 105 * split.GIB,
        },
    }
    signature = private_key.sign(split.canonical_json(payload))
    envelope = {
        "schema_version": 2,
        "kind": split.CAPACITY_KIND,
        "algorithm": "ed25519",
        "key_sha256": public_sha256,
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    receipt_body = split.canonical_json(envelope)
    receipt_path = tmp_path / "capacity-receipt.json"
    _write_capacity_receipt(receipt_path, receipt_body)
    return receipt_path, hashlib.sha256(receipt_body).hexdigest(), public_path, public_sha256


def _json_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _valid_trace(trace_id: str, task_id: str, *, mode: str = "shared", solved: int = 0) -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
            }
        ],
    }
    response = {
        "id": f"response-{trace_id}",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": None, "reasoning_content": "reasoning"},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    return {
        "id": trace_id,
        "task": {"slug": task_id},
        "nodes": [
            {
                "parent": None,
                "sampled": True,
                "token_ids": [1, 2],
                "mask": [True, True],
                "logprobs": [-0.1, -0.2],
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "reasoning",
                    "tool_calls": None,
                },
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _json_digest(request), "body": request},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _json_digest(response),
                        "body": response,
                    },
                },
            }
        ],
        "info": {"terminal_bench_verifier": {"mode": mode}},
        "is_completed": True,
        "stop_condition": "task_completed",
        "rewards": {"solved": solved},
        "metrics": {},
        "errors": [],
    }


def _direct_worker_manifest(tmp_path: Path, *, router_port: int, metrics_port: int) -> tuple[Path, dict]:
    workers = sorted(
        (
            {
                "backend_sha256": hashlib.sha256(f"worker-{index}".encode()).hexdigest(),
                "model_sha256": hashlib.sha256(direct_workers.EXPECTED_MODEL.encode()).hexdigest(),
            }
            for index in range(direct_workers.EXPECTED_ENDPOINTS)
        ),
        key=lambda item: item["backend_sha256"],
    )
    endpoint_bundle_sha256 = hashlib.sha256(
        "".join(f"{worker['backend_sha256']}\n" for worker in workers).encode()
    ).hexdigest()
    manifest = {
        "schema_version": direct_workers.MANIFEST_SCHEMA_VERSION,
        "kind": "direct-kimi-worker-generation",
        "deployment_root": "/private/reviewed-kimi-deployment",
        "model": direct_workers.EXPECTED_MODEL,
        "source_spec_sha256": direct_workers.EXPECTED_SPEC_SHA256,
        "source_proxy_config_sha256": direct_workers.EXPECTED_PROXY_CONFIG_SHA256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "workers": workers,
        "router": {
            "implementation": direct_workers.ROUTER_IMPLEMENTATION,
            "implementation_sha256": hashlib.sha256(
                Path(direct_workers.__file__).with_name("direct_kimi_router.py").read_bytes()
            ).hexdigest(),
            "host": "127.0.0.1",
            "port": router_port,
            "metrics_host": "127.0.0.1",
            "metrics_port": metrics_port,
            "policy": direct_workers.ROUTER_POLICY,
            "request_id_headers": list(direct_workers.ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": direct_workers.ROUTER_REQUEST_TIMEOUT_SECONDS,
            "max_concurrent_requests": direct_workers.ROUTER_PROVIDER_CONCURRENCY,
            "queue_size": direct_workers.ROUTER_QUEUE_SIZE,
            "queue_timeout_seconds": direct_workers.ROUTER_QUEUE_TIMEOUT_SECONDS,
            "retries": direct_workers.ROUTER_RETRIES,
        },
    }
    body = split.canonical_json(manifest)
    path = tmp_path / f"workers-{router_port}.json"
    _private_file(path, body)
    return path, manifest


def _direct_identity(tmp_path: Path, provider: str) -> tuple[dict, dict]:
    identity = _identity(provider)
    router_port = 20_001 if provider == "sandoq" else 20_002
    metrics_port = 40_001 if provider == "sandoq" else 40_002
    worker_path, worker_manifest = _direct_worker_manifest(
        tmp_path,
        router_port=router_port,
        metrics_port=metrics_port,
    )
    worker_body = worker_path.read_bytes()
    router = worker_manifest["router"]
    identity["source"].update(
        {
            "prime_rl_tree_sha256": "7" * 64,
            "verifiers_tree_sha256": "8" * 64,
            "renderers_tree_sha256": "9" * 64,
        }
    )
    identity["contract"] = {
        "model": "Kimi-K3",
        "pass_at_1": True,
        "num_rollouts": 1,
        "reasoning_effort": "max",
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "context_tokens": {
            "max_input_tokens": split.MAX_SEQUENCE_TOKENS,
            "max_output_tokens": split.MAX_SEQUENCE_TOKENS,
            "max_total_tokens": split.MAX_SEQUENCE_TOKENS,
        },
        "sampling_max_tokens": split.SAMPLING_MAX_TOKENS,
        "capture_model_io": True,
        "outbound_body_denylist": split.EXPECTED_DENYLIST,
        "retain_traces": False,
        "harness": {
            "id": "terminal-bench-sandoq-host",
            "placement": "host",
            "tool": "bash",
            "command_timeout_seconds": 240,
            "command_kill_grace_seconds": 10,
            "max_command_output_chars": 100_000,
            "request_timeout_seconds": 15_000,
            "request_max_retries": 0,
            "stream": False,
        },
    }
    identity["deployment"] = {
        "kind": "direct_kimi",
        "worker_manifest": {
            "path": str(worker_path),
            "sha256": hashlib.sha256(worker_body).hexdigest(),
        },
        "spec_sha256": worker_manifest["source_spec_sha256"],
        "endpoint_bundle_sha256": worker_manifest["endpoint_bundle_sha256"],
        "base_url": f"http://127.0.0.1:{router_port}/v1",
        "router": {
            "implementation": router["implementation"],
            "implementation_sha256": router["implementation_sha256"],
            "policy": router["policy"],
            "request_id_headers": router["request_id_headers"],
            "provider_concurrency": router["max_concurrent_requests"],
            "request_timeout_seconds": router["request_timeout_seconds"],
            "retries": router["retries"],
            "worker_count": len(worker_manifest["workers"]),
        },
        "smoke_checkpoint": {"path": "/private/smoke.json", "sha256": "e" * 64},
    }
    config = {
        "output_dir": f"/private/{provider}-run",
        "model": "Kimi-K3",
        "num_tasks": split.LEGACY_SANDOQ_TASKS if provider == "sandoq" else split.LARGE_PROVIDER_TASKS,
        "num_rollouts": 1,
        "max_concurrent": 24 if provider == "sandoq" else 4,
        "max_turns": 200,
        "max_input_tokens": split.MAX_SEQUENCE_TOKENS,
        "max_output_tokens": split.MAX_SEQUENCE_TOKENS,
        "max_total_tokens": split.MAX_SEQUENCE_TOKENS,
        "multiplex": 24 if provider == "sandoq" else 4,
        "rich": False,
        "retain_traces": False,
        "client": {
            "type": "eval",
            "base_url": "http://127.0.0.1:20000/v1",
            "api_key_var": "OPENAI_API_KEY",
            "timeout": 43_200,
            "connect_timeout": 120,
            "max_connections": 24 if provider == "sandoq" else 4,
            "max_keepalive_connections": 24 if provider == "sandoq" else 4,
            "capture_model_io": True,
            "outbound_body_denylist": split.EXPECTED_DENYLIST,
        },
        "sampling": {
            "temperature": 1.0,
            "top_p": 1.0,
            "max_tokens": split.SAMPLING_MAX_TOKENS,
            "reasoning_effort": "max",
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
        "taskset": {
            "id": "terminal-bench-vmvm",
            "dataset_dir": "/private/dataset",
            "task_file": f"/private/{provider}.tasks",
            "task_file_sha256": "f" * 64,
            "image_manifest": f"/private/{provider}.images",
            "image_manifest_sha256": split.CANONICAL_IMAGE_MANIFEST_SHA256,
            "resource_multiplier": 1.0 if provider == "sandoq" else 2.0,
            "ignore_dockerfile": True,
            "use_declared_images": True,
            "enable_compose": True,
            "verifier_runtime_retries": 0,
            "timeout_multiplier": 2.0,
        },
        "harness": {
            **identity["contract"]["harness"],
            "runtime": {"type": provider},
        },
        "timeout": {"setup": 3600, "rollout": 36000, "finalize": 3600, "scoring": 21600},
        "retries": {"rollout": {"max_retries": 0, "include": ["ProviderError", "SandboxError"]}},
    }
    return identity, config


def test_shared_contract_matches_only_exact_direct_model_generation_and_eval_budget(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    legacy_identity, legacy_config = _direct_identity(tmp_path, "sandoq")
    large_identity, large_config = _direct_identity(tmp_path, "vmvm")
    expected = split._shared_contract(legacy_identity, legacy_config)
    assert split._shared_contract(large_identity, large_config) == expected

    for target, key, value in (
        ("deployment", "endpoint_bundle_sha256", "0" * 64),
        ("router", "request_timeout_seconds", 43_201),
        ("config", "timeout", {"setup": 3600, "rollout": 1, "finalize": 3600, "scoring": 21600}),
    ):
        changed_identity = copy.deepcopy(large_identity)
        changed_config = copy.deepcopy(large_config)
        if target == "deployment":
            changed_identity["deployment"][key] = value
        elif target == "router":
            changed_identity["deployment"]["router"][key] = value
        else:
            changed_config[key] = value
        if target == "config":
            assert split._shared_contract(changed_identity, changed_config) != expected
        else:
            with pytest.raises(split.KimiProviderSplitError, match="^deployment_worker_manifest_invalid$"):
                split._shared_contract(changed_identity, changed_config)

    changed_identity = copy.deepcopy(large_identity)
    changed_manifest = json.loads(Path(changed_identity["deployment"]["worker_manifest"]["path"]).read_bytes())
    changed_manifest["workers"][0]["backend_sha256"] = "f" * 64
    changed_manifest["workers"].sort(key=lambda item: item["backend_sha256"])
    changed_manifest["endpoint_bundle_sha256"] = hashlib.sha256(
        "".join(f"{worker['backend_sha256']}\n" for worker in changed_manifest["workers"]).encode()
    ).hexdigest()
    changed_path = tmp_path / "workers-changed.json"
    changed_body = split.canonical_json(changed_manifest)
    _private_file(changed_path, changed_body)
    changed_identity["deployment"]["worker_manifest"] = {
        "path": str(changed_path),
        "sha256": hashlib.sha256(changed_body).hexdigest(),
    }
    changed_identity["deployment"]["endpoint_bundle_sha256"] = changed_manifest["endpoint_bundle_sha256"]
    assert split._shared_contract(changed_identity, large_config) != expected

    reordered_identity = copy.deepcopy(large_identity)
    reordered_manifest = json.loads(Path(reordered_identity["deployment"]["worker_manifest"]["path"]).read_bytes())
    reordered_manifest["workers"][0], reordered_manifest["workers"][1] = (
        reordered_manifest["workers"][1],
        reordered_manifest["workers"][0],
    )
    reordered_path = tmp_path / "workers-reordered.json"
    reordered_body = split.canonical_json(reordered_manifest)
    _private_file(reordered_path, reordered_body)
    reordered_identity["deployment"]["worker_manifest"] = {
        "path": str(reordered_path),
        "sha256": hashlib.sha256(reordered_body).hexdigest(),
    }
    with pytest.raises(split.KimiProviderSplitError, match="^deployment_worker_manifest_invalid$"):
        split._shared_contract(reordered_identity, large_config)


def test_manifest_partition_is_exact_disjoint_and_exhaustive(tmp_path: Path) -> None:
    _path, _digest, entries = _manifest_file(tmp_path)
    partition = split.derive_partition(entries)

    assert tuple(map(len, (partition.legacy_sandoq, partition.large_provider, partition.gpu_unsupported))) == (
        31,
        32,
        3,
    )
    assert len(partition.compose_required) == 11
    assert set(partition.compose_required).isdisjoint(partition.legacy_sandoq)
    assert set(partition.compose_required).issubset(partition.large_provider)
    assert len(set(partition.legacy_sandoq) | set(partition.large_provider) | set(partition.gpu_unsupported)) == 66


def test_manifest_rejects_duplicate_or_wrong_partition_cardinality(tmp_path: Path) -> None:
    value = _manifest()
    value["entries"][-1]["task_id"] = value["entries"][0]["task_id"]
    body = split.canonical_json(value)
    with pytest.raises(split.KimiProviderSplitError, match="^resource_manifest_duplicate_member$"):
        split.parse_manifest(body, hashlib.sha256(body).hexdigest())

    value = _manifest()
    value["entries"][0]["agent_resources"]["memory_bytes"] = 8 * split.GIB
    value["entries"][0]["verifier_resources"]["memory_bytes"] = 8 * split.GIB
    body = split.canonical_json(value)
    _parsed, entries = split.parse_manifest(body, hashlib.sha256(body).hexdigest())
    with pytest.raises(split.KimiProviderSplitError, match="^partition_cardinality_mismatch$"):
        split.derive_partition(entries)


def test_manifest_requires_exact_compose_capability_partition() -> None:
    value = _manifest()
    value["entries"][split.LEGACY_SANDOQ_TASKS]["runtime_requirements"]["compose"] = False
    body = split.canonical_json(value)
    _parsed, entries = split.parse_manifest(body, hashlib.sha256(body).hexdigest())
    with pytest.raises(split.KimiProviderSplitError, match="^compose_partition_invalid$"):
        split.derive_partition(entries)

    value = _manifest()
    del value["entries"][0]["runtime_requirements"]
    body = split.canonical_json(value)
    with pytest.raises(split.KimiProviderSplitError, match="^resource_manifest_invalid$"):
        split.parse_manifest(body, hashlib.sha256(body).hexdigest())


def test_sensitive_manifest_requires_private_single_link(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    value = _manifest()
    body = split.canonical_json(value)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    with pytest.raises(split.KimiProviderSplitError, match="^resource_manifest_invalid$"):
        split.materialize_partition(manifest, digest, tmp_path / "mode-output")

    manifest.chmod(0o600)
    alias = tmp_path / "manifest-hardlink.json"
    os.link(manifest, alias)
    with pytest.raises(split.KimiProviderSplitError, match="^resource_manifest_invalid$"):
        split.materialize_partition(manifest, digest, tmp_path / "link-output")


def test_held_run_evidence_rejects_same_bytes_path_replacement(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    bodies = {
        "eval_run_identity.json": b"{}\n",
        "eval_invocations.jsonl": b"{}\n",
        "provenance.txt": b"key=value\n",
    }
    for name, body in bodies.items():
        _private_file(run / name, body)
    evidence = split._open_held_run_evidence(run)
    try:
        original = run / "eval_run_identity.json"
        original.rename(run / "old-identity.json")
        _private_file(original, bodies["eval_run_identity.json"])
        with pytest.raises(split.KimiProviderSplitError, match="^run_evidence_changed$"):
            evidence.revalidate()
    finally:
        evidence.close()


def test_held_certificate_artifact_rejects_post_audit_path_replacement(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    result = tmp_path / "results.jsonl"
    _private_file(result, b"audited bytes\n")
    held = split._HeldArtifactSet.create()
    try:
        body, record = held.capture(
            result,
            code="provider_results_invalid",
            maximum_bytes=1024,
            private=True,
        )
        assert body == b"audited bytes\n"
        assert record["sha256"] == hashlib.sha256(body).hexdigest()

        result.rename(tmp_path / "results-original.jsonl")
        _private_file(result, body)
        with pytest.raises(split.KimiProviderSplitError, match="^provider_artifact_changed$"):
            held.revalidate()
    finally:
        held.close()


def test_checked_in_image_only_manifest_cannot_be_used_as_selector_source() -> None:
    path = Path(__file__).parents[1] / "configs/eval/servers/cpu-132-021_8103/tb4_images.sandoq.json"
    body = path.read_bytes()

    with pytest.raises(split.KimiProviderSplitError, match="^resource_manifest_invalid$"):
        split.parse_manifest(body, hashlib.sha256(body).hexdigest())


def test_materialized_bundle_is_private_and_stdout_is_aggregate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path.chmod(0o700)
    manifest, digest, _entries = _manifest_file(tmp_path)
    output = tmp_path / "partition"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kimi_tb4_provider_split.py",
            "materialize",
            "--manifest",
            str(manifest),
            "--manifest-sha256",
            digest,
            "--output",
            str(output),
        ],
    )

    split.main()

    stdout = capsys.readouterr().out
    assert "opaque-case" not in stdout
    assert json.loads(stdout)["partition"] == {
        "canonical_order": "manifest-entry-order",
        "disjoint": True,
        "exhaustive": True,
        "gpu_unsupported": 3,
        "large_provider": 32,
        "legacy_sandoq": 31,
        "compose_required_cpu": 11,
        "total": 66,
    }
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    split._read_partition_bundle(output, manifest, digest)


def test_private_bundle_marks_postcommit_mutation_indeterminate_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "bundle"
    original = split._verify_bundle_at
    calls = 0

    def mutate_after_first_verification(
        parent_descriptor: int,
        name: str,
        expected_identity: tuple[int, int, int, int],
        files: dict[str, bytes],
    ) -> None:
        nonlocal calls
        original(parent_descriptor, name, expected_identity, files)
        calls += 1
        if calls == 1:
            target = Path(f"/proc/self/fd/{parent_descriptor}") / name / "one"
            target.write_bytes(b"changed")
            target.chmod(0o600)

    monkeypatch.setattr(split, "_verify_bundle_at", mutate_after_first_verification)
    with pytest.raises(split.KimiProviderSplitError, match="^output_publication_indeterminate$"):
        split._publish_private_bundle(output, {"one": b"expected"})
    assert output.is_dir()
    assert (output / "one").read_bytes() == b"changed"
    with pytest.raises(split.KimiProviderSplitError, match="published_artifact_changed"):
        split._publish_private_bundle(output, {"one": b"expected"})


def test_private_bundle_rejects_symlink_parent_and_leaves_private_precommit_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(split.KimiProviderSplitError, match="^output_parent_invalid$"):
        split._publish_private_bundle(alias / "bundle", {"one": b"value"})
    assert not (real / "bundle").exists()

    original = split.os.fstat
    directory_calls = 0

    def fail_first_stage_stat(descriptor: int) -> os.stat_result:
        nonlocal directory_calls
        value = original(descriptor)
        if stat.S_ISDIR(value.st_mode):
            directory_calls += 1
            if directory_calls == 3:
                raise OSError("synthetic")
        return value

    monkeypatch.setattr(split.os, "fstat", fail_first_stage_stat)
    with pytest.raises(Exception, match="synthetic|rollback"):
        split._publish_private_bundle(real / "failed", {"one": b"value"})
    residues = [path for path in real.iterdir() if path.name.startswith(".failed.stage-")]
    assert len(residues) == 1
    assert stat.S_IMODE(residues[0].stat().st_mode) == 0o700


def test_private_certificate_write_is_no_overwrite(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "certificate.json"
    split._write_private_once(output, {"state": "first"})

    with pytest.raises(split.KimiProviderSplitError, match="^output_already_exists$"):
        split._write_private_once(output, {"state": "second"})

    assert json.loads(output.read_bytes()) == {"state": "first"}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    loaded, body = split._load_bound_certificate(
        output,
        hashlib.sha256(output.read_bytes()).hexdigest(),
    )
    assert loaded == {"state": "first"}
    assert body == output.read_bytes()


def test_private_publications_adopt_exact_postcommit_indeterminate_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    original_fsync = split.os.fsync
    calls = 0

    def fail_file_postcommit(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic postcommit failure")
        original_fsync(descriptor)

    certificate = tmp_path / "certificate.json"
    monkeypatch.setattr(split.os, "fsync", fail_file_postcommit)
    with pytest.raises(split.KimiProviderSplitError, match="^output_publication_indeterminate$"):
        split._write_private_once(certificate, {"state": "first"})
    monkeypatch.setattr(split.os, "fsync", original_fsync)
    split._write_private_once(certificate, {"state": "first"})

    calls = 0

    def fail_bundle_postcommit(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("synthetic postcommit failure")
        original_fsync(descriptor)

    bundle = tmp_path / "bundle"
    monkeypatch.setattr(split.os, "fsync", fail_bundle_postcommit)
    with pytest.raises(split.KimiProviderSplitError, match="^output_publication_indeterminate$"):
        split._publish_private_bundle(bundle, {"one": b"expected"})
    monkeypatch.setattr(split.os, "fsync", original_fsync)
    split._publish_private_bundle(bundle, {"one": b"expected"})
    assert (bundle / "one").read_bytes() == b"expected"


def test_private_bundle_destination_race_never_replaces_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "bundle"
    original = split._rename_noreplace

    def race(source: str, destination: str, parent_descriptor: int) -> None:
        os.mkdir(destination, 0o700, dir_fd=parent_descriptor)
        destination_descriptor = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY,
            dir_fd=parent_descriptor,
        )
        try:
            winner = os.open(
                "winner",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_descriptor,
            )
            os.close(winner)
        finally:
            os.close(destination_descriptor)
        original(source, destination, parent_descriptor)

    monkeypatch.setattr(split, "_rename_noreplace", race)
    with pytest.raises(split.KimiProviderSplitError, match="^output_already_exists$"):
        split._publish_private_bundle(output, {"one": b"expected"})
    assert {path.name for path in output.iterdir()} == {"winner"}


def test_private_bundle_portable_commit_marker_fallback_is_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "bundle"

    def unsupported(_source: str, _destination: str, _parent_descriptor: int) -> None:
        raise split.KimiProviderSplitError("rename_noreplace_unsupported")

    monkeypatch.setattr(split, "_rename_noreplace", unsupported)
    split._publish_private_bundle(output, {"one": b"expected"})
    marker = json.loads((output / split.BUNDLE_COMMIT).read_bytes())
    assert marker["state"] == "complete"
    assert marker["artifacts"] == {
        "one": {"bytes": len(b"expected"), "sha256": hashlib.sha256(b"expected").hexdigest()}
    }
    assert (output / "one").read_bytes() == b"expected"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    split._publish_private_bundle(output, {"one": b"expected"})


@pytest.mark.parametrize("concurrency", [23, 24])
def test_router_receipt_requires_exact_direct_publication_marker(
    tmp_path: Path,
    concurrency: int,
) -> None:
    tmp_path.chmod(0o700)
    identity, _config = _direct_identity(tmp_path, "sandoq")
    identity["execution"]["rollout_concurrency"] = concurrency
    identity_sha256 = "a" * 64
    invocation_sha256 = "b" * 64
    deployment = identity["deployment"]
    router = deployment["router"]
    if concurrency == 23:
        router.update(
            {
                "capacity_profile": "sandoq-c23-v1",
                "endpoint_identifier": "cpu-132-021_8103",
                "provider_concurrency": 23,
                "worker_count": 23,
            }
        )
    value = {
        "schema_version": 4 if concurrency == 23 else 2,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "eval_run_identity_sha256": identity_sha256,
        "invocation_identity_sha256": invocation_sha256,
        "worker_manifest_sha256": deployment["worker_manifest"]["sha256"],
        "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
        "active_workers": router["worker_count"],
        "implementation": router["implementation"],
        "implementation_sha256": router["implementation_sha256"],
        "policy": router["policy"],
        "request_id_headers": router["request_id_headers"],
        "request_timeout_seconds": router["request_timeout_seconds"],
        "retries": router["retries"],
        "source_generation_revalidated": True,
        "max_active_requests": 1,
        "total_requests": split.LEGACY_SANDOQ_TASKS,
        "chat_requests": split.LEGACY_SANDOQ_TASKS,
        "worker_request_counts_sha256": "c" * 64,
    }
    if concurrency == 23:
        value.update(
            {
                "capacity_profile": "sandoq-c23-v1",
                "endpoint_identifier": "cpu-132-021_8103",
                "configured_capacity": 23,
                "configured_per_worker_capacity": 1,
                "active_forwarded_requests": 0,
                "worker_active_request_counts_sha256": hashlib.sha256(
                    (json.dumps([0] * 23, separators=(",", ":")) + "\n").encode()
                ).hexdigest(),
                "worker_session_counts_sha256": "d" * 64,
                "active_worker_waiters": 0,
                "worker_waiting_request_counts_sha256": hashlib.sha256(
                    (json.dumps([0] * 23, separators=(",", ":")) + "\n").encode()
                ).hexdigest(),
                "max_active_chat_requests": 1,
                "capacity_rejections": 0,
                "queue_overflow_rejections": 0,
                "route_tracking_overflows": 0,
                "cross_route_anomalies": 0,
                "tracked_sessions": 1,
            }
        )
    receipt = tmp_path / "direct_kimi_router_final.json"
    body = split.canonical_json(value)
    _private_file(receipt, body)
    with pytest.raises(split.KimiProviderSplitError, match="^router_receipt_commit_invalid$"):
        split._validate_direct_router_receipt(
            receipt,
            identity,
            minimum_chat_requests=split.LEGACY_SANDOQ_TASKS,
            identity_sha256=identity_sha256,
            invocation_identity_sha256=invocation_sha256,
        )

    marker = {
        "schema_version": 1,
        "kind": "direct-kimi-file-publication",
        "files": {
            receipt.name: {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
        },
    }
    _private_file(receipt.with_name(f".{receipt.name}.complete"), split.canonical_json(marker))
    observed, _artifact, _marker_artifact = split._validate_direct_router_receipt(
        receipt,
        identity,
        minimum_chat_requests=split.LEGACY_SANDOQ_TASKS,
        identity_sha256=identity_sha256,
        invocation_identity_sha256=invocation_sha256,
    )
    assert observed == body


def test_capacity_receipt_requires_signature_binding_environment_and_minimums(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    identity = _identity()
    manifest_sha256 = "8" * 64
    selector_sha256 = "9" * 64
    identity_sha256 = "a" * 64
    receipt, receipt_sha, public_key, public_sha = _signed_capacity(
        tmp_path,
        manifest_sha256=manifest_sha256,
        selector_sha256=selector_sha256,
        identity=identity,
        identity_sha256=identity_sha256,
        invocation_identity_sha256="b" * 64,
        runtime_instance_nonce="6" * 32,
    )
    monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)

    payload, _artifacts = split._capacity_payload(
        receipt,
        receipt_sha,
        public_key,
        public_sha,
        manifest_sha256=manifest_sha256,
        selector_sha256=selector_sha256,
        identity=identity,
        identity_sha256=identity_sha256,
        invocation_identity_sha256="b" * 64,
        runtime_instance_nonces=frozenset({"6" * 32}),
    )
    assert payload["measured_capacity"]["actual_cpu_count"] == 32

    envelope = json.loads(receipt.read_bytes())
    envelope["signature"] = base64.b64encode(b"x" * 64).decode("ascii")
    _write_capacity_receipt(receipt, split.canonical_json(envelope))
    with pytest.raises(split.KimiProviderSplitError, match="^capacity_signature_invalid$"):
        split._capacity_payload(
            receipt,
            hashlib.sha256(receipt.read_bytes()).hexdigest(),
            public_key,
            public_sha,
            manifest_sha256=manifest_sha256,
            selector_sha256=selector_sha256,
            identity=identity,
            identity_sha256=identity_sha256,
            invocation_identity_sha256="b" * 64,
            runtime_instance_nonces=frozenset({"6" * 32}),
        )

    for field, value in (
        ("actual_cpu_count", 31),
        ("outer_memory_bytes", 36 * split.GIB - 1),
        ("disk_available_bytes", 105 * split.GIB - 1),
    ):
        receipt, receipt_sha, public_key, public_sha = _signed_capacity(
            tmp_path / field,
            manifest_sha256=manifest_sha256,
            selector_sha256=selector_sha256,
            identity=identity,
            identity_sha256=identity_sha256,
            capacity={
                "actual_cpu_count": 32,
                "outer_memory_bytes": 36 * split.GIB,
                "disk_available_bytes": 105 * split.GIB,
                field: value,
            },
        )
        monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)
        with pytest.raises(split.KimiProviderSplitError, match="^capacity_receipt_invalid$"):
            split._capacity_payload(
                receipt,
                receipt_sha,
                public_key,
                public_sha,
                manifest_sha256=manifest_sha256,
                selector_sha256=selector_sha256,
                identity=identity,
                identity_sha256=identity_sha256,
                invocation_identity_sha256="b" * 64,
                runtime_instance_nonces=frozenset({"6" * 32}),
            )


def test_capacity_receipt_rejects_environment_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    identity = _identity()
    receipt, receipt_sha, public_key, public_sha = _signed_capacity(
        tmp_path,
        manifest_sha256="8" * 64,
        selector_sha256="9" * 64,
        identity=identity,
        identity_sha256="a" * 64,
    )
    monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)
    changed = _identity()
    changed["execution"]["vmvm_environment"]["lease_start_concurrency"] = 3

    with pytest.raises(split.KimiProviderSplitError, match="^capacity_receipt_invalid$"):
        split._capacity_payload(
            receipt,
            receipt_sha,
            public_key,
            public_sha,
            manifest_sha256="8" * 64,
            selector_sha256="9" * 64,
            identity=changed,
            identity_sha256="a" * 64,
            invocation_identity_sha256="b" * 64,
            runtime_instance_nonces=frozenset({"6" * 32}),
        )


def test_capacity_receipt_rejects_stale_future_and_cross_runtime_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    now = datetime.now(timezone.utc)
    cases = (
        {"issued_at": now - timedelta(hours=7), "expires_at": now - timedelta(hours=1)},
        {
            "issued_at": now + timedelta(minutes=6),
            "expires_at": now + timedelta(minutes=6) + split.CAPACITY_VALIDITY,
        },
    )
    for index, times in enumerate(cases):
        receipt, receipt_sha, public, public_sha = _signed_capacity(
            tmp_path / f"time-{index}",
            manifest_sha256="8" * 64,
            selector_sha256="9" * 64,
            identity=identity,
            identity_sha256="a" * 64,
            **times,
        )
        monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)
        with pytest.raises(split.KimiProviderSplitError, match="^capacity_receipt_invalid$"):
            split._capacity_payload(
                receipt,
                receipt_sha,
                public,
                public_sha,
                manifest_sha256="8" * 64,
                selector_sha256="9" * 64,
                identity=identity,
                identity_sha256="a" * 64,
                invocation_identity_sha256="b" * 64,
                runtime_instance_nonces=frozenset({"6" * 32}),
            )

    delayed, delayed_sha, public, public_sha = _signed_capacity(
        tmp_path / "delayed",
        manifest_sha256="8" * 64,
        selector_sha256="9" * 64,
        identity=identity,
        identity_sha256="a" * 64,
        issued_at=now - timedelta(days=9),
        expires_at=now - timedelta(days=1),
    )
    monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)
    payload, _artifacts = split._capacity_payload(
        delayed,
        delayed_sha,
        public,
        public_sha,
        manifest_sha256="8" * 64,
        selector_sha256="9" * 64,
        identity=identity,
        identity_sha256="a" * 64,
        invocation_identity_sha256="b" * 64,
        runtime_instance_nonces=frozenset({"6" * 32}),
    )
    assert payload["expires_at"] < now.isoformat().replace("+00:00", "Z")

    receipt, receipt_sha, public, public_sha = _signed_capacity(
        tmp_path / "replay",
        manifest_sha256="8" * 64,
        selector_sha256="9" * 64,
        identity=identity,
        identity_sha256="a" * 64,
    )
    monkeypatch.setattr(split, "PINNED_CAPACITY_PUBLIC_KEY_SHA256", public_sha)
    with pytest.raises(split.KimiProviderSplitError, match="^capacity_receipt_invalid$"):
        split._capacity_payload(
            receipt,
            receipt_sha,
            public,
            public_sha,
            manifest_sha256="8" * 64,
            selector_sha256="9" * 64,
            identity=identity,
            identity_sha256="a" * 64,
            invocation_identity_sha256="e" * 64,
            runtime_instance_nonces=frozenset({"5" * 32}),
        )


def test_cpu_trace_audit_rejects_duplicate_missing_or_reasoning_loss(tmp_path: Path) -> None:
    members = ("opaque-a", "opaque-b")
    modes = {"opaque-a": "shared", "opaque-b": "separate"}
    results = tmp_path / "results.jsonl"
    rows = [
        _valid_trace("trace-a", "opaque-a", mode="shared", solved=1),
        _valid_trace("trace-b", "opaque-b", mode="separate", solved=0),
    ]
    _private_file(results, b"".join(split.canonical_json(row) for row in rows))
    summary, observed, artifact = split._audit_cpu_results(results, members, modes)
    assert summary["passes"] == 1
    assert set(observed) == set(members)
    assert artifact["sha256"] == hashlib.sha256(results.read_bytes()).hexdigest()

    rows[1]["id"] = "trace-a"
    _private_file(results, b"".join(split.canonical_json(row) for row in rows))
    with pytest.raises(split.KimiProviderSplitError, match="^provider_trace_audit_failed$"):
        split._audit_cpu_results(results, members, modes)

    rows[1] = _valid_trace("trace-b", "opaque-b", mode="separate")
    rows[1]["nodes"][0]["message"]["reasoning_content"] = None
    _private_file(results, b"".join(split.canonical_json(row) for row in rows))
    with pytest.raises(split.KimiProviderSplitError, match="^provider_trace_audit_failed$"):
        split._audit_cpu_results(results, members, modes)


def test_cpu_trace_audit_is_bound_to_one_held_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.chmod(0o700)
    results = tmp_path / "results.jsonl"
    original_body = split.canonical_json(_valid_trace("trace-a", "opaque-a", solved=1))
    _private_file(results, original_body)
    replacement = tmp_path / "replacement.jsonl"
    _private_file(replacement, b"not-json\n")
    original_read = split._read_regular_evidence

    def swap_after_read(path: Path, **kwargs):
        observed = original_read(path, **kwargs)
        if path == results:
            os.replace(replacement, results)
        return observed

    monkeypatch.setattr(split, "_read_regular_evidence", swap_after_read)
    summary, rows, artifact = split._audit_cpu_results(results, ("opaque-a",), {"opaque-a": "shared"})
    assert summary["passes"] == 1
    assert set(rows) == {"opaque-a"}
    assert artifact["sha256"] == hashlib.sha256(original_body).hexdigest()
    assert artifact["sha256"] != hashlib.sha256(results.read_bytes()).hexdigest()


def _vmvm_cleanup_row(nonce: str, identity_sha256: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "vmvm-runtime-cleanup",
        "runtime_instance_nonce": nonce,
        "cleanup_pass": 1,
        "state": "passed",
        "attempted": 1,
        "failures": 0,
        "host_tunnel_count": 0,
        "host_tunnels_closed": 0,
        "network_firewall_present": True,
        "network_firewall_cleanup_completed": True,
        "session_present": True,
        "session_stop_completed": True,
        "fifo_present": True,
        "fifo_cleanup_completed": True,
        "compose_present": False,
        "compose_teardown_completed": True,
        "compose_directory_cleanup_completed": True,
        "container_present": True,
        "container_teardown_completed": True,
        "internal_network_present": True,
        "internal_network_teardown_completed": True,
        "ssh_master_stop_completed": True,
        "lease_process_was_alive": True,
        "lease_sigterm_sent": True,
        "lease_wait_completed": True,
        "lease_exit_code": 0,
        "lease_sigkill_used": False,
        "release_on_exit_completed": True,
        "remote_deletion_verified": False,
        "eval_run_identity_sha256": identity_sha256,
    }


def _sandoq_cleanup(run_dir: Path, *, slurm_job_id: str = "123") -> tuple[Path, dict, dict]:
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    control = run_dir / "control"
    control.mkdir(mode=0o700)
    raw = split.canonical_json({"schema_version": 1, "state": "passed"})
    events = split.canonical_json(
        {
            "schema_version": 2,
            "record_type": "pool_event",
            "event": "pool_drained",
            "slurm_job_id": slurm_job_id,
        }
    )
    wal = split.canonical_json(
        {
            "schema_version": 2,
            "event": "outer_deleted",
            "slurm_job_id": slurm_job_id,
        }
    )
    _private_file(run_dir / "pool_cleanup_audit.json", raw)
    _private_file(run_dir / "pool_events.jsonl", events)
    _private_file(control / "sandoq-pool.wal.jsonl", wal)
    value = {
        "schema_version": 1,
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        "recorded_outer_sessions": split.LEGACY_SANDOQ_TASKS,
        "verified_http_404": split.LEGACY_SANDOQ_TASKS,
        "already_absent": 0,
        "deleted_and_verified": split.LEGACY_SANDOQ_TASKS,
        "assignments_acquired": split.LEGACY_SANDOQ_TASKS,
        "assignment_release_rows": split.LEGACY_SANDOQ_TASKS,
        "assignment_cancellation_rows": 0,
        "cleanup_gateway_retry_count": 0,
        "assignments_cleanup_verified": split.LEGACY_SANDOQ_TASKS,
        "assignment_event_order_high_water": 24,
        "assignment_measured_high_water": 24,
        "outer_sessions_created": split.LEGACY_SANDOQ_TASKS,
        "outer_sessions_deleted": split.LEGACY_SANDOQ_TASKS,
        "outer_session_high_water": 24,
        "pool_drain_deleted": 0,
        "gateway_close_warnings": 0,
        "recovered_poisoned_assignments": 0,
        "failures": 0,
        "raw_audit_sha256": hashlib.sha256(raw).hexdigest(),
        "pool_event_log_sha256": hashlib.sha256(events).hexdigest(),
        "pool_wal_sha256": hashlib.sha256(wal).hexdigest(),
        "pool_drain_sha256": "4" * 64,
    }
    path = run_dir / "sandoq_cleanup_audit.json"
    _private_file(path, split.canonical_json(value))
    identity = _identity("sandoq")
    identity["execution"]["sandoq_environment"].update(
        {
            "pool_event_log": str(run_dir / "pool_events.jsonl"),
            "pool_wal": str(control / "sandoq-pool.wal.jsonl"),
        }
    )
    return path, value, identity


def test_sandoq_cleanup_must_account_for_every_session_and_assignment(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    path, value, identity = _sandoq_cleanup(run_dir)
    summary, _artifacts = split._validate_sandoq_cleanup(
        path,
        run_dir,
        identity,
        "a" * 64,
        "b" * 64,
        "123",
        split.LEGACY_SANDOQ_TASKS,
        24,
    )
    assert summary["state"] == "passed"

    value["verified_http_404"] -= 1
    _private_file(path, split.canonical_json(value))
    with pytest.raises(split.KimiProviderSplitError, match="^sandoq_cleanup_invalid$"):
        split._validate_sandoq_cleanup(
            path,
            run_dir,
            identity,
            "a" * 64,
            "b" * 64,
            "123",
            split.LEGACY_SANDOQ_TASKS,
            24,
        )


def test_sandoq_cleanup_rejects_replay_from_another_invocation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    path, _value, identity = _sandoq_cleanup(run_dir, slurm_job_id="123")
    with pytest.raises(split.KimiProviderSplitError, match="^sandoq_cleanup_run_mismatch$"):
        split._validate_sandoq_cleanup(
            path,
            run_dir,
            identity,
            "a" * 64,
            "b" * 64,
            "124",
            split.LEGACY_SANDOQ_TASKS,
            24,
        )


def test_vmvm_cleanup_requires_every_created_runtime(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    control = run_dir / "control"
    control.mkdir(parents=True)
    control.chmod(0o700)
    identity_sha256 = "a" * 64
    nonces = ("1" * 32, "2" * 32)
    lifecycle = b"".join(
        split.canonical_json(
            {
                "schema_version": 1,
                "kind": "vmvm-runtime-created",
                "runtime_instance_nonce": nonce,
                "eval_run_identity_sha256": identity_sha256,
            }
        )
        for nonce in nonces
    )
    cleanup = b"".join(split.canonical_json(_vmvm_cleanup_row(nonce, identity_sha256)) for nonce in nonces)
    _private_file(control / "vmvm_runtime_lifecycle.jsonl", lifecycle)
    _private_file(control / "vmvm_cleanup_receipts.jsonl", cleanup)

    summary, _artifacts, observed_nonces = split._validate_vmvm_cleanup(
        run_dir,
        identity_sha256,
        "b" * 64,
        2,
    )
    assert summary["runtime_instances"] == 2
    assert observed_nonces == frozenset(nonces)

    _private_file(
        control / "vmvm_cleanup_receipts.jsonl",
        split.canonical_json(_vmvm_cleanup_row(nonces[0], identity_sha256)),
    )
    with pytest.raises(split.KimiProviderSplitError, match="^vmvm_cleanup_incomplete$"):
        split._validate_vmvm_cleanup(run_dir, identity_sha256, "b" * 64, 2)


def test_quiescence_lock_rejects_symlink_and_detects_active_owner(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    target = tmp_path / "target.lock"
    _private_file(target, b"")
    alias = tmp_path / "alias.lock"
    alias.symlink_to(target)
    with pytest.raises(split.KimiProviderSplitError, match="^writer_lock_missing$"):
        split._open_private_writer_lock(alias)

    first = split._open_private_writer_lock(target)
    second = split._open_private_writer_lock(target)
    try:
        fcntl.flock(first.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        first.close()
        second.close()


def test_merge_is_canonical_full_denominator_and_rejects_duplicate_trace_ids(tmp_path: Path) -> None:
    _path, digest, entries = _manifest_file(tmp_path)
    partition = split.derive_partition(entries)
    legacy = {
        member: {"id": f"legacy-{index}", "rewards": {"solved": index % 2}}
        for index, member in enumerate(partition.legacy_sandoq)
    }
    large = {
        member: {"id": f"large-{index}", "rewards": {"solved": index % 2}}
        for index, member in enumerate(partition.large_provider)
    }

    rows, passes = split._merge_rows(entries, partition, legacy, large, digest)

    assert len(rows) == 66
    assert passes == sum(row["rewards"].get("solved", 0) for row in rows)
    assert [split._task_slug(row) for row in rows[-3:]] == list(partition.gpu_unsupported)
    assert all(row["rewards"] == {} for row in rows[-3:])

    large[partition.large_provider[0]]["id"] = legacy[partition.legacy_sandoq[0]]["id"]
    with pytest.raises(split.KimiProviderSplitError, match="^merged_trace_id_invalid$"):
        split._merge_rows(entries, partition, legacy, large, digest)


def test_cli_redacts_unexpected_exceptions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kimi_tb4_provider_split.py",
            "materialize",
            "--manifest",
            "/private/member-name",
            "--manifest-sha256",
            "0" * 64,
            "--output",
            "/private/output",
        ],
    )

    with pytest.raises(SystemExit, match="kimi_tb4_provider_split_failed"):
        split.main()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "member-name" not in str(captured)
