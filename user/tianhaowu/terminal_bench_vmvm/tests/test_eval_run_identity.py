from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import eval_run_identity
import pytest
import tomli_w
from deployment_endpoint import load_deployment_endpoint
from eval_run_identity import (
    EvalIdentityError,
    _bind_identity,
    _bind_provenance,
    _checkpoint_identity,
    _contract,
    _dataset_identity,
    _effective_vmvm_environment,
    _identity_envelope,
    _tree_digest,
    _write_resolved_config,
    canonical_json,
    load_eval_run_identity,
)


def _resolved_config() -> dict:
    return {
        "model": "approved-model",
        "num_rollouts": 1,
        "max_concurrent": 4,
        "multiplex": 4,
        "max_input_tokens": 262_144,
        "max_output_tokens": 262_144,
        "max_total_tokens": 262_144,
        "rich": False,
        "retain_traces": False,
        "client": {
            "type": "eval",
            "base_url": "https://endpoint.example/v1",
            "api_key_var": "OPENAI_API_KEY",
            "headers": {},
            "capture_model_io": True,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "top_logprobs",
                "return_token_ids",
            ],
            "max_connections": 4,
            "max_keepalive_connections": 4,
        },
        "sampling": {
            "max_tokens": 32_768,
            "reasoning_effort": "max",
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
        "harness": {"runtime": {"type": "vmvm", "session_timeout": 43_200}},
    }


def _identity() -> dict:
    artifact_sha256 = "a" * 64
    clean_sha256 = hashlib.sha256(b"").hexdigest()
    contract, execution = _contract(_resolved_config(), "approved-model")
    execution["vmvm_environment"] = {
        "vacli_bin": "/pinned/vacli",
        "lease_start_concurrency": 4,
        "lease_retries": 20,
        "max_pull_retries": 20,
        "image_pull_timeout_sec": 3600,
        "container_privileged": True,
    }
    return {
        "schema_version": 1,
        "role": "smoke",
        "source": {
            "project_root": "/pinned/project",
            "prime_rl_commit": "1" * 40,
            "prime_rl_tree_sha256": clean_sha256,
            "verifiers_commit": "2" * 40,
            "verifiers_tree_sha256": clean_sha256,
            "renderers_commit": "3" * 40,
            "renderers_tree_sha256": clean_sha256,
            "vmvm_tb_v2_sha256": "4" * 64,
        },
        "config": {
            "source": {"path": "/run/inputs/source_config.toml", "sha256": artifact_sha256},
            "resolved": {"path": "/run/config.toml", "sha256": artifact_sha256},
        },
        "inputs": {
            "manifest": {"path": "/run/inputs/manifest.json", "sha256": artifact_sha256},
            "task_file": {
                "path": "/run/inputs/task_file.txt",
                "sha256": artifact_sha256,
                "count": 2,
            },
            "image_manifest": None,
        },
        "dataset": {
            "kind": "git_revision",
            "path": "/pinned/dataset",
            "revision": "5" * 40,
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
        },
        "deployment": {
            "id": "deployment-metadata",
            "endpoint": {
                "schema_version": 1,
                "kind": "deployment_local_proxy_info",
                "proxy_info": {"path": "/deployment/proxy_info.json", "sha256": artifact_sha256},
                "authority_sha256": "b" * 64,
            },
            "routing": {"deployment_id": None, "headers": {}},
            "spec": {"path": "/deployment/spec.yaml", "sha256": artifact_sha256},
            "readiness_checkpoint": {
                "path": "/deployment/readiness.json",
                "sha256": artifact_sha256,
            },
            "smoke_checkpoint": None,
            "promotion_certificate": None,
        },
        "contract": contract,
        "execution": execution,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_eval_identity_is_canonical_write_once_and_resume_exact(tmp_path: Path) -> None:
    identity = _identity()
    expected = _identity_envelope(identity)

    digest = _bind_identity(tmp_path, identity, resume=False)

    assert digest == hashlib.sha256(canonical_json(identity)).hexdigest()
    assert load_eval_run_identity(
        tmp_path / "eval_run_identity.json",
        verify_references=False,
    ) == expected
    assert _bind_identity(tmp_path, identity, resume=True) == digest
    with pytest.raises(EvalIdentityError, match="already_exists"):
        _bind_identity(tmp_path, identity, resume=False)


def test_eval_identity_rejects_legacy_and_mismatched_resume(tmp_path: Path) -> None:
    legacy = _identity()
    legacy["deployment"].pop("endpoint")
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _identity_envelope(legacy)

    with pytest.raises(EvalIdentityError, match="legacy_resume"):
        _bind_identity(tmp_path, _identity(), resume=True)

    _bind_identity(tmp_path, _identity(), resume=False)
    changed = _identity()
    changed["contract"]["model"] = "other-approved-model"
    with pytest.raises(EvalIdentityError, match="identity_mismatch"):
        _bind_identity(tmp_path, changed, resume=True)


def test_eval_provenance_binds_endpoint_hashes_write_once(tmp_path: Path) -> None:
    identity = _identity()
    digest = hashlib.sha256(canonical_json(identity)).hexdigest()
    args = SimpleNamespace(
        mode="fresh",
        invocation_host="unit-test-host",
        slurm_job_id="12345",
    )

    _bind_provenance(tmp_path, identity, digest, args)

    records = dict(
        line.split("=", 1)
        for line in (tmp_path / "provenance.txt").read_text().splitlines()
    )
    endpoint = identity["deployment"]["endpoint"]
    assert records["deployment_endpoint_authority_sha256"] == endpoint["authority_sha256"]
    assert records["deployment_proxy_info_sha256"] == endpoint["proxy_info"]["sha256"]

    args.mode = "resume"
    _bind_provenance(tmp_path, identity, digest, args)


def test_eval_contract_binds_required_training_and_concurrency_settings() -> None:
    contract, execution = _contract(_resolved_config(), "approved-model")
    environment = _effective_vmvm_environment(
        SimpleNamespace(
            vacli_bin="/pinned/vacli",
            vacli_max_concurrent_leases="8",
            vacli_lease_retries="20",
            vacli_max_pull_retries="20",
            vacli_image_pull_timeout_seconds="3600",
            vacli_container_privileged="1",
        ),
        execution["rollout_concurrency"],
    )

    assert contract["pass_at_1"] is True
    assert contract["reasoning_effort"] == "max"
    assert set(contract["context_tokens"].values()) == {262_144}
    assert contract["capture_model_io"] is True
    assert contract["outbound_body_denylist"] == sorted(
        ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
    )
    assert execution["rollout_concurrency"] == 4
    assert execution["multiplex"] == 4
    assert environment["lease_start_concurrency"] == 4

    unsafe = _resolved_config()
    unsafe["client"]["base_url"] = "https://credential@example.invalid/v1"
    with pytest.raises(EvalIdentityError, match="endpoint_url_invalid"):
        _contract(unsafe, "approved-model")

    routed = _resolved_config()
    routed["client"]["headers"] = {"X-Deployment-Id": "deployment-metadata"}
    _contract(routed, "approved-model", "deployment-metadata")
    with pytest.raises(EvalIdentityError, match="routing_headers_mismatch"):
        _contract(routed, "approved-model")

    for invalid_thinking in (
        {"enable_thinking": 1, "preserve_thinking": True},
        {"enable_thinking": True, "preserve_thinking": True, "extra": True},
    ):
        unsafe = _resolved_config()
        unsafe["sampling"]["chat_template_kwargs"] = invalid_thinking
        with pytest.raises(EvalIdentityError, match="max_reasoning_contract_required"):
            _contract(unsafe, "approved-model")


def test_archive_dataset_requires_explicit_live_tree_digest(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    payload = dataset / "payload.bin"
    payload.write_bytes(b"opaque payload")
    archive = tmp_path / "dataset.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("tasks/payload.bin")
        data = payload.read_bytes()
        info.size = len(data)
        info.mode = payload.stat().st_mode & 0o7777
        handle.addfile(info, io.BytesIO(data))
    content_sha256 = _tree_digest(dataset)
    args = SimpleNamespace(
        dataset_revision=None,
        dataset_archive=archive,
        dataset_archive_sha256=_sha256(archive),
        dataset_content_sha256=content_sha256,
    )
    config = {"taskset": {"dataset_dir": str(dataset), "use_declared_images": True}}

    identity = _dataset_identity(config, args)

    assert identity["kind"] == "archive"
    assert identity["content_sha256"] == content_sha256
    args.dataset_content_sha256 = "0" * 64
    with pytest.raises(EvalIdentityError, match="dataset_archive_content_sha256_mismatch"):
        _dataset_identity(config, args)
    args.dataset_content_sha256 = content_sha256
    payload.write_bytes(b"changed payload")
    with pytest.raises(EvalIdentityError, match="dataset_content_sha256_mismatch"):
        _dataset_identity(config, args)


def test_checkpoint_chain_is_hashed_and_role_aware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deployment_id = "deployment-metadata"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text("version: pinned\n")
    proxy_info = deployment_dir / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8100,
                "url": "http://127.0.0.1:8100",
                "api_key": "unit-test-secret",
                "model": "approved-model",
                "proxy_jobid": "12345",
                "extras": {"proxy_type": "litellm", "sticky": True, "redis_port": 6379},
            }
        )
        + "\n"
    )
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="approved-model",
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256(proxy_info),
    ).binding
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "passed",
                "deployment": deployment_id,
                "observed_spec_sha256": _sha256(spec),
                "endpoint": endpoint,
                "probe": {"ok": True},
            }
        )
        + "\n"
    )
    smoke_identity = _identity()
    smoke_identity["deployment"] = {
        "id": deployment_id,
        "endpoint": endpoint,
        "routing": {"deployment_id": None, "headers": {}},
        "spec": {"path": str(spec), "sha256": _sha256(spec)},
        "readiness_checkpoint": {"path": str(readiness), "sha256": _sha256(readiness)},
        "smoke_checkpoint": None,
        "promotion_certificate": None,
    }
    envelope = _identity_envelope(smoke_identity)
    eval_identity = tmp_path / "eval_run_identity.json"
    eval_identity.write_text(json.dumps(envelope, sort_keys=True) + "\n")
    monkeypatch.setattr(
        eval_run_identity,
        "load_eval_run_identity",
        lambda _path, *, verify_references=True: envelope,
    )
    artifacts: dict[str, dict[str, str]] = {
        "eval_run_identity": {"path": str(eval_identity), "sha256": _sha256(eval_identity)},
        "readiness_checkpoint": {"path": str(readiness), "sha256": _sha256(readiness)},
        "proxy_info": endpoint["proxy_info"],
    }
    for name in ("results", "config", "inputs_manifest", "provenance"):
        path = tmp_path / name
        path.write_bytes(f"opaque {name}".encode())
        artifacts[name] = {"path": str(path), "sha256": _sha256(path)}
    smoke_body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
        "deployment": {"id": deployment_id, "spec_sha256": _sha256(spec)},
        "endpoint": endpoint,
        "audit_policy": {
            "expected_traces": 2,
            "rollouts_per_task": 1,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": eval_run_identity.EXPECTED_MODEL_IO_CONTRACT,
            "require_token_data": False,
            "require_logprobs": False,
            "max_sequence_tokens": 262_144,
        },
        "counts": {
            "traces": 2,
            "tasks": 2,
            "sampled_tokens": 10,
            "model_io_turns": 2,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "artifacts": artifacts,
    }
    smoke_payload = {
        **smoke_body,
        "smoke_checkpoint_sha256": hashlib.sha256(canonical_json(smoke_body)).hexdigest(),
    }
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps(smoke_payload, sort_keys=True) + "\n")
    args = SimpleNamespace(
        role="tb4",
        deployment_id=deployment_id,
        deployment_spec=spec,
        deployment_spec_sha256=_sha256(spec),
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=_sha256(readiness),
        smoke_checkpoint=smoke,
        smoke_checkpoint_sha256=_sha256(smoke),
        promotion_certificate=None,
        promotion_certificate_sha256=None,
        routing_deployment_id=None,
    )

    deployment = _checkpoint_identity(args, endpoint)

    assert deployment["id"] == deployment_id
    assert deployment["endpoint"] == endpoint
    assert deployment["smoke_checkpoint"]["sha256"] == _sha256(smoke)
    mismatched_endpoint = json.loads(json.dumps(endpoint))
    mismatched_endpoint["authority_sha256"] = "0" * 64
    with pytest.raises(EvalIdentityError, match="readiness_checkpoint_not_passed"):
        _checkpoint_identity(args, mismatched_endpoint)
    promotion = tmp_path / "promotion.json"
    promotion.write_text(json.dumps({"state": "passed", "deployment": {"endpoint": endpoint}}) + "\n")
    args.role = "mobius"
    args.promotion_certificate = promotion
    args.promotion_certificate_sha256 = _sha256(promotion)
    deployment = _checkpoint_identity(args, endpoint)
    assert deployment["promotion_certificate"]["sha256"] == _sha256(promotion)
    args.role = "tb4"
    args.promotion_certificate = None
    args.promotion_certificate_sha256 = None
    smoke_payload["counts"]["trace_failures"] = 1
    smoke_payload["smoke_checkpoint_sha256"] = hashlib.sha256(
        canonical_json({key: value for key, value in smoke_payload.items() if key != "smoke_checkpoint_sha256"})
    ).hexdigest()
    smoke.write_text(json.dumps(smoke_payload, sort_keys=True) + "\n")
    args.smoke_checkpoint_sha256 = _sha256(smoke)
    with pytest.raises(EvalIdentityError, match="smoke_checkpoint_not_passed"):
        _checkpoint_identity(args, endpoint)
    args.role = "smoke"
    with pytest.raises(EvalIdentityError, match="cannot_use_prior_smoke"):
        _checkpoint_identity(args, endpoint)


def test_fresh_resolver_writes_exact_config_before_eval(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    task_file = inputs / "task_file.txt"
    task_file.write_bytes(b"opaque-selection\n")
    task_sha256 = _sha256(task_file)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    source = {
        "model": "approved-model",
        "num_tasks": 1,
        "num_rollouts": 1,
        "max_concurrent": 1,
        "max_turns": 2,
        "max_input_tokens": 262_144,
        "max_output_tokens": 262_144,
        "max_total_tokens": 262_144,
        "multiplex": 1,
        "rich": False,
        "retain_traces": False,
        "client": {
            "type": "eval",
            "base_url": "http://127.0.0.1:1/v1",
            "api_key_var": "OPENAI_API_KEY",
            "capture_model_io": True,
            "outbound_body_denylist": sorted(
                ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
            ),
            "max_connections": 1,
            "max_keepalive_connections": 1,
        },
        "sampling": {
            "max_tokens": 32_768,
            "reasoning_effort": "max",
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
        "taskset": {
            "id": "terminal-bench-vmvm",
            "dataset_dir": str(dataset),
            "task_file": str(task_file),
            "task_file_sha256": task_sha256,
            "use_declared_images": True,
            "ignore_dockerfile": True,
        },
        "harness": {
            "id": "mini-swe-agent",
            "version": "2.2.8",
            "config_file": "mini",
            "runtime": {"type": "vmvm"},
        },
    }
    (inputs / "source_config.toml").write_text(tomli_w.dumps(source))
    output = tmp_path / "output"
    output.mkdir()

    resolved = _write_resolved_config(
        output,
        inputs,
        "https://endpoint.example/v1",
        None,
        task_sha256,
        "deployment-metadata",
    )

    assert resolved["taskset"]["task_file"] == str(task_file)
    assert resolved["taskset"]["task_file_sha256"] == task_sha256
    assert resolved["client"]["base_url"] == "https://endpoint.example/v1"
    assert resolved["client"]["headers"] == {"X-Deployment-Id": "deployment-metadata"}
    assert (output / "config.toml").is_file()
    assert (output / "results.jsonl").read_bytes() == b""
