from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tomllib
from pathlib import Path
from types import SimpleNamespace

import eval_run_identity
import pytest
import tomli_w
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import (
    deployment_proxy_policy_snapshot,
    deployment_spec_policy_snapshot,
    load_deployment_proxy_policy,
)
from eval_run_identity import (
    EvalIdentityError,
    _bind_identity,
    _bind_provenance,
    _checkpoint_identity,
    _contract,
    _dataset_identity,
    _effective_vmvm_environment,
    _identity_envelope,
    _sandoq_site_sha256,
    _source_identity,
    _tree_digest,
    _validate_identity_shape,
    _verify_checkpoint_records,
    _verify_saved_provenance,
    _write_resolved_config,
    canonical_json,
    load_eval_run_identity,
    validate_kimi_retry_contract,
    validate_kimi_timeout_contract,
)
from guard_success_receipt import (
    build_guard_success_receipt,
    write_guard_success_receipt,
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
            "timeout": 7_200,
            "connect_timeout": 120,
        },
        "sampling": {
            "max_tokens": 32_768,
            "reasoning_effort": "max",
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
        "harness": {
            "config_overrides": [],
            "runtime": {"type": "vmvm", "session_timeout": 43_200},
        },
        "timeout": {
            "setup": 3_600,
            "rollout": 36_000,
            "finalize": 3_600,
            "scoring": 21_600,
        },
        "retries": {
            "rollout": {
                "max_retries": 2,
                "include": [
                    "ProviderError",
                    "SandboxError",
                    "TunnelError",
                    "InterceptionError",
                ],
            }
        },
    }


def _sandoq_kimi_config(*, smoke: bool) -> dict:
    config = _resolved_config()
    config["model"] = "Kimi-K3"
    config["client"]["timeout"] = 43_200
    config["harness"] = {
        "id": "terminal-bench-sandoq-host",
        "command_timeout_seconds": 240,
        "command_kill_grace_seconds": 10,
        "max_command_output_chars": 100_000,
        "request_timeout_seconds": 15_000,
        "runtime": {
            "type": "sandoq",
            "mode": "oci-runner",
            "network_access": True,
            "host_tunnel": "none",
            "expected_environment": "oci-runner",
            "ecr_token_file": "/private/ecr-token",
            "session_timeout": 32_400 if smoke else 43_200,
        },
    }
    config["taskset"] = {"verifier_runtime_retries": 0}
    config["retries"]["rollout"]["max_retries"] = 0
    config["timeout"]["rollout"] = 28_800 if smoke else 36_000
    return config


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
            "serving_route_generation": {
                "schema_version": 2,
                "coordinator": {
                    "slurm_job_id": "900",
                    "started_at": "2026-09-17T00:00:00Z",
                },
                "proxy": {
                    "slurm_job_id": "999",
                    "first_ready_at": "2026-09-17T00:30:00Z",
                },
                "routes": [
                    {
                        "slurm_job_id": "12345",
                        "started_at": "2026-09-17T01:00:00Z",
                        "backend_sha256": f"backend-sha256:{'c' * 64}",
                    }
                ],
            },
            "proxy_policy": {
                "schema_version": 1,
                "request_timeout": 7200,
                "num_retries": 0,
                "proxy_litellm_config": {
                    "path": "/deployment/proxy_litellm_config.yaml",
                    "sha256": "d" * 64,
                },
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


def _sandoq_identity() -> dict:
    identity = _identity()
    config = _resolved_config()
    config["retries"]["rollout"]["max_retries"] = 0
    config["taskset"] = {"verifier_runtime_retries": 0}
    config["harness"] = {
        "id": "terminal-bench-sandoq-host",
        "command_timeout_seconds": 240,
        "command_kill_grace_seconds": 10,
        "max_command_output_chars": 100_000,
        "request_timeout_seconds": 15_000,
        "runtime": {
            "type": "sandoq",
            "mode": "oci-runner",
            "network_access": True,
            "host_tunnel": "none",
            "expected_environment": "oci-runner",
            "ecr_token_file": "/run/secrets/ecr-token",
        },
    }
    contract, execution = _contract(config, "approved-model", sandbox_provider="sandoq")
    execution["sandoq_environment"] = {
        "environment": "oci-runner",
        "task_network": "public",
        "pool_size": 4,
        "pool_min_size": 0,
        "tunnel_policy": "host-interception-no-tunnel",
        "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        "owner": "test-user",
        "transport_proxy_policy": "official-client-auto",
        "pool_socket_scope": "job-node-local",
        "pool_wal": "/run/control/sandoq-pool.wal.jsonl",
        "pool_event_log": "/run/pool_events.jsonl",
        "use_ecr": True,
        "ecr_registry": "168653207203.dkr.ecr.us-east-2.amazonaws.com",
        "ecr_region": "us-east-2",
        "ecr_pull_through_prefix": "pt_dockerio",
        "ecr_token_file": "/run/secrets/ecr-token",
        "ecr_auth_policy": "private-token-file-mode-0600",
        "allow_dockerhub_fallback": True,
        "create_deadline": "30m",
        "pull_timeout": "3600s",
        "pull_poll_max_errors": "20",
        "gateway_retry_attempts": "15",
        "gateway_retry_interval": "2s",
        "podman_ignore_chown_errors": "1",
        "require_resource_limits": "1",
        "exec_timeout_ceiling": "270",
        "task_pids_limit": "512",
        "observability": "1",
        "pool_heartbeat_timeout": "45s",
        "pool_create_workers": "4",
        "pool_bootstrap_workers": "4",
        "pool_bootstrap_per_image": "4",
        "pool_drain_workers": "4",
        "pool_drain_timeout": "240",
        "pool_renew_workers": "4",
        "session_reuse": "1",
        "pool_max_reuse_count": "1",
        "pool_reuse_jitter": "0",
        "image_cache_max_entries": "0",
        "secret_cache_ttl": "5s",
        "lease_duration": "1h",
        "pool_renew_interval": "5m",
    }
    identity["contract"] = contract
    identity["execution"] = execution
    identity["source"] = {key: value for key, value in identity["source"].items() if key != "vmvm_tb_v2_sha256"} | {
        "sandbox_provider": "sandoq",
        "sandoq_provider_commit": "4" * 40,
        "sandoq_provider_tree": "5" * 40,
        "sandoq_client_version": "pinned-client",
        "sandoq_site": "/pinned/sandoq-site",
        "sandoq_site_sha256": "7" * 64,
        "sandoq_host_harness_sha256": "8" * 64,
        "derived_image_manifest_sha256": "6" * 64,
    }
    identity["inputs"]["image_manifest"] = {
        "path": "/run/inputs/image_manifest.json",
        "sha256": "6" * 64,
    }
    return identity


def test_sandoq_identity_shape_rejects_backend_and_manifest_mismatch() -> None:
    identity = _sandoq_identity()
    assert _validate_identity_shape(identity) == identity
    for path, value in (
        (("execution", "runtime", "type"), "vmvm"),
        (("source", "derived_image_manifest_sha256"), "7" * 64),
        (("execution", "sandoq_environment", "create_deadline"), "31m"),
        (("execution", "runtime", "ecr_token_file"), "/run/secrets/another-token"),
        (("execution", "runtime", "guest_tunnel_url"), "http://127.0.0.1:8485"),
        (("execution", "cleanup_must_succeed"), False),
        (("contract",), None),
    ):
        mismatched = json.loads(json.dumps(identity))
        target = mismatched
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(EvalIdentityError, match="schema_invalid"):
            _validate_identity_shape(mismatched)


def test_sandoq_provenance_round_trip(tmp_path: Path) -> None:
    identity = _sandoq_identity()
    args = SimpleNamespace(mode="fresh", invocation_host="host", slurm_job_id="123")
    _bind_provenance(tmp_path, identity, "8" * 64, args)
    _verify_saved_provenance(tmp_path, identity, "8" * 64)
    provenance = (tmp_path / "provenance.txt").read_text()
    assert "sandbox_provider=sandoq\n" in provenance
    assert "sandoq_allow_dockerhub_fallback=true\n" in provenance


def test_direct_qwen_sandoq_identity_binds_worker_generation() -> None:
    identity = _sandoq_identity()
    identity["role"] = "qwen-direct"
    identity["deployment"] = {
        "kind": "direct_qwen",
        "worker_manifest": {"path": "/run/direct_workers.json", "sha256": "8" * 64},
        "spec_sha256": "9" * 64,
        "endpoint_bundle_sha256": "a" * 64,
        "base_url": "http://127.0.0.1:12345/v1",
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "provider_concurrency": 4,
        },
    }

    assert _validate_identity_shape(identity) == identity
    identity["deployment"]["endpoint_bundle_sha256"] = "b" * 63
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _validate_identity_shape(identity)


def test_direct_qwen_vmvm_identity_binds_host_harness_contract() -> None:
    identity = _identity()
    identity["role"] = "qwen-direct"
    identity["contract"]["harness"] = {
        "id": "terminal-bench-sandoq-host",
        "placement": "host",
        "tool": "bash",
        "command_timeout_seconds": 240,
        "command_kill_grace_seconds": 10,
        "max_command_output_chars": 100_000,
        "request_timeout_seconds": 15_000,
        "request_max_retries": 0,
        "stream": False,
    }
    identity["execution"]["cleanup_must_succeed"] = True
    identity["execution"]["cleanup_receipt_contract"] = dict(
        eval_run_identity.VMVM_HOST_CLEANUP_CONTRACT
    )
    identity["deployment"] = {
        "kind": "direct_qwen",
        "worker_manifest": {"path": "/run/direct_workers.json", "sha256": "8" * 64},
        "spec_sha256": "9" * 64,
        "endpoint_bundle_sha256": "a" * 64,
        "base_url": "http://127.0.0.1:12345/v1",
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "provider_concurrency": 4,
        },
    }

    assert _validate_identity_shape(identity) == identity
    identity["contract"]["harness"]["request_timeout_seconds"] = 14_999
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _validate_identity_shape(identity)


def test_direct_qwen_sandoq_identity_envelope_round_trip(tmp_path: Path) -> None:
    identity = _sandoq_identity()
    identity["role"] = "qwen-direct"
    identity["deployment"] = {
        "kind": "direct_qwen",
        "worker_manifest": {"path": "/run/direct_workers.json", "sha256": "8" * 64},
        "spec_sha256": "9" * 64,
        "endpoint_bundle_sha256": "a" * 64,
        "base_url": "http://127.0.0.1:12345/v1",
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "provider_concurrency": 4,
        },
    }
    envelope = _identity_envelope(identity)
    path = tmp_path / "eval_run_identity.json"
    path.write_text(json.dumps(envelope))

    assert load_eval_run_identity(path, verify_references=False) == envelope


def test_direct_qwen_identity_reference_verification_does_not_require_routing(tmp_path: Path, monkeypatch) -> None:
    identity = _sandoq_identity()
    identity["role"] = "qwen-direct"
    identity["deployment"] = {
        "kind": "direct_qwen",
        "worker_manifest": {"path": "/run/direct_workers.json", "sha256": "8" * 64},
        "spec_sha256": "9" * 64,
        "endpoint_bundle_sha256": "a" * 64,
        "base_url": "http://127.0.0.1:12345/v1",
        "router": {
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "provider_concurrency": 4,
        },
    }
    envelope = _identity_envelope(identity)
    path = tmp_path / "eval_run_identity.json"
    path.write_text(json.dumps(envelope))
    monkeypatch.setattr(eval_run_identity, "_verify_source_record", lambda _source: None)
    monkeypatch.setattr(eval_run_identity, "_artifact", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(eval_run_identity, "_verify_config_and_inputs", lambda *_args: {})
    monkeypatch.setattr(eval_run_identity, "_verify_saved_provenance", lambda *_args: None)
    monkeypatch.setattr(
        eval_run_identity,
        "_git_output",
        lambda *_args, **_kwargs: identity["dataset"]["revision"] if "rev-parse" in _args else "",
    )

    assert load_eval_run_identity(path, verify_references=True) == envelope


def _direct_kimi_identity(*, smoke: bool) -> dict:
    identity = _sandoq_identity()
    concurrency = 1 if smoke else 24
    config = _sandoq_kimi_config(smoke=smoke)
    config["max_concurrent"] = concurrency
    config["multiplex"] = concurrency
    config["client"]["max_connections"] = concurrency
    config["client"]["max_keepalive_connections"] = concurrency
    if smoke:
        config["sampling"]["reasoning_effort"] = "max"
        config["timeout"].update(setup=600, rollout=900, finalize=300, scoring=600)
        config["harness"]["runtime"]["session_timeout"] = 2_400
    contract, execution = _contract(
        config,
        "Kimi-K3",
        role="kimi-direct-smoke" if smoke else "kimi-direct-tb4",
        sandbox_provider="sandoq",
    )
    environment = identity["execution"]["sandoq_environment"]
    environment["ecr_token_file"] = "/private/ecr-token"
    environment["pool_size"] = concurrency
    for key, cap in (
        ("pool_create_workers", 4),
        ("pool_bootstrap_workers", 64),
        ("pool_bootstrap_per_image", 8),
        ("pool_drain_workers", 32),
        ("pool_renew_workers", 16),
    ):
        environment[key] = str(min(concurrency, cap))
    execution["sandoq_environment"] = environment
    identity["role"] = "kimi-direct-smoke" if smoke else "kimi-direct-tb4"
    identity["contract"] = contract
    identity["execution"] = execution
    identity["deployment"] = {
        "kind": "direct_kimi",
        "worker_manifest": {"path": "/run/direct_kimi_workers.json", "sha256": "8" * 64},
        "spec_sha256": "9" * 64,
        "endpoint_bundle_sha256": "a" * 64,
        "base_url": "http://127.0.0.1:23456/v1",
        "router": {
            "implementation": "direct-kimi-transparent-v1",
            "implementation_sha256": "c" * 64,
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "provider_concurrency": 24,
            "request_timeout_seconds": 43_200,
            "retries": 0,
            "worker_count": 24,
        },
        "smoke_checkpoint": (
            None
            if smoke
            else {"path": "/run/smoke_checkpoint.json", "sha256": "b" * 64}
        ),
    }
    return identity


def test_direct_kimi_sandoq_identity_binds_router_and_smoke_lineage() -> None:
    smoke = _direct_kimi_identity(smoke=True)
    assert _validate_identity_shape(smoke) == smoke
    full = _direct_kimi_identity(smoke=False)
    assert _validate_identity_shape(full) == full
    assert smoke["contract"]["reasoning_effort"] == "max"
    assert full["contract"]["reasoning_effort"] == "max"

    for path, value in (
        (("deployment", "router", "policy"), "round_robin"),
        (("deployment", "router", "request_timeout_seconds"), 600),
        (("deployment", "router", "retries"), 2),
        (("deployment", "smoke_checkpoint"), None),
    ):
        mismatched = json.loads(json.dumps(full))
        target = mismatched
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(EvalIdentityError, match="schema_invalid"):
            _validate_identity_shape(mismatched)


def test_direct_kimi_identity_envelope_round_trip(tmp_path: Path) -> None:
    identity = _direct_kimi_identity(smoke=True)
    envelope = _identity_envelope(identity)
    path = tmp_path / "eval_run_identity.json"
    path.write_text(json.dumps(envelope))

    assert load_eval_run_identity(path, verify_references=False) == envelope


def test_sandoq_source_rejects_unobserved_client_version(tmp_path: Path, monkeypatch) -> None:
    clean = hashlib.sha256(b"").hexdigest()
    args = SimpleNamespace(
        project_root=tmp_path,
        prime_rl_commit="1" * 40,
        prime_rl_tree_sha256=clean,
        verifiers_commit="2" * 40,
        verifiers_tree_sha256=clean,
        renderers_commit="3" * 40,
        renderers_tree_sha256=clean,
        sandbox_provider="sandoq",
        sandoq_provider_commit="4" * 40,
        sandoq_provider_tree="5" * 40,
        sandoq_client_version="claimed",
        sandoq_site=tmp_path,
        sandoq_site_sha256="7" * 64,
        derived_image_manifest_sha256="6" * 64,
    )

    def git_output(_root, *git_args, label: str) -> str:
        if git_args[0] == "status":
            return ""
        if "HEAD^{tree}" in git_args:
            return "5" * 40
        if label.endswith("_commit"):
            return getattr(args, label)
        return {
            "sandoq_provider": args.sandoq_provider_commit,
        }[label]

    monkeypatch.setattr(eval_run_identity, "_git_output", git_output)
    monkeypatch.setattr(eval_run_identity, "_validate_vendored_sandoq_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eval_run_identity.importlib.metadata, "version", lambda _name: "observed")
    with pytest.raises(EvalIdentityError, match="client_version_mismatch"):
        _source_identity(args)


def test_vendored_sandoq_provider_matches_pinned_upstream_inventory() -> None:
    project_root = Path(__file__).resolve().parents[4]

    eval_run_identity._validate_vendored_sandoq_provider(
        project_root,
        expected_commit=eval_run_identity.SANDOQ_UPSTREAM_COMMIT,
        expected_tree=eval_run_identity.SANDOQ_UPSTREAM_TREE,
    )
    with pytest.raises(EvalIdentityError, match="sandoq_provider_mismatch"):
        eval_run_identity._validate_vendored_sandoq_provider(
            project_root,
            expected_commit="0" * 40,
            expected_tree=eval_run_identity.SANDOQ_UPSTREAM_TREE,
        )


def test_sandoq_site_digest_binds_non_cache_runtime_files(tmp_path: Path) -> None:
    (tmp_path / "package").mkdir()
    (tmp_path / "package/module.py").write_text("VALUE = 1\n")
    (tmp_path / "package/module.pyc").write_bytes(b"cache")
    (tmp_path / ".lock").write_bytes(b"mutable")
    before = _sandoq_site_sha256(tmp_path)
    (tmp_path / "package/module.pyc").write_bytes(b"changed-cache")
    (tmp_path / ".lock").write_bytes(b"changed-lock")
    assert _sandoq_site_sha256(tmp_path) == before
    (tmp_path / "package/module.py").write_text("VALUE = 2\n")
    assert _sandoq_site_sha256(tmp_path) != before


def test_eval_identity_is_canonical_write_once_and_resume_exact(tmp_path: Path) -> None:
    identity = _identity()
    expected = _identity_envelope(identity)

    digest = _bind_identity(tmp_path, identity, resume=False)

    assert digest == hashlib.sha256(canonical_json(identity)).hexdigest()
    assert (
        load_eval_run_identity(
            tmp_path / "eval_run_identity.json",
            verify_references=False,
        )
        == expected
    )
    assert _bind_identity(tmp_path, identity, resume=True) == digest
    with pytest.raises(EvalIdentityError, match="already_exists"):
        _bind_identity(tmp_path, identity, resume=False)


def test_eval_identity_rejects_legacy_and_mismatched_resume(tmp_path: Path) -> None:
    legacy = _identity()
    legacy["deployment"].pop("endpoint")
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _identity_envelope(legacy)

    legacy_generation = _identity()
    legacy_generation["deployment"].pop("serving_route_generation")
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _identity_envelope(legacy_generation)

    wrong_model_timeout = _identity()
    wrong_model_timeout["contract"]["model"] = "Kimi-K3"
    with pytest.raises(EvalIdentityError, match="schema_invalid"):
        _identity_envelope(wrong_model_timeout)

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

    records = dict(line.split("=", 1) for line in (tmp_path / "provenance.txt").read_text().splitlines())
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

    kimi = _resolved_config()
    kimi["model"] = "Kimi-K3"
    kimi["client"]["timeout"] = 43_200
    kimi["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
    _contract(kimi, "Kimi-K3")
    resolved_kimi = _resolved_config()
    resolved_kimi["model"] = "Kimi-K3"
    resolved_kimi["client"]["timeout"] = 43_200.0
    resolved_kimi["client"]["connect_timeout"] = 120.0
    resolved_kimi["timeout"]["rollout"] = 28_800.0
    resolved_kimi["harness"]["runtime"]["session_timeout"] = 32_400.0
    resolved_kimi["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
    _contract(resolved_kimi, "Kimi-K3")
    for invalid_timeout in (True, 43_200.5, float("nan"), float("inf")):
        invalid_kimi = _resolved_config()
        invalid_kimi["model"] = "Kimi-K3"
        invalid_kimi["client"]["timeout"] = invalid_timeout
        invalid_kimi["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
        with pytest.raises(EvalIdentityError, match="kimi_timeout_contract_invalid"):
            _contract(invalid_kimi, "Kimi-K3")
    for section, key, value in (
        ("client", "timeout", 7_200),
        ("timeout", "rollout", 43_200),
        ("harness.runtime", "session_timeout", 35_999),
    ):
        unsafe = _resolved_config()
        unsafe["model"] = "Kimi-K3"
        unsafe["client"]["timeout"] = 43_200
        unsafe["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
        target = unsafe["harness"]["runtime"] if section == "harness.runtime" else unsafe[section]
        target[key] = value
        with pytest.raises(EvalIdentityError, match="kimi_timeout_contract_invalid"):
            _contract(unsafe, "Kimi-K3")

    unsafe = _resolved_config()
    unsafe["model"] = "Kimi-K3"
    unsafe["client"]["timeout"] = 43_200
    unsafe["harness"]["config_overrides"] = ["model.model_kwargs.timeout=36000"]
    with pytest.raises(EvalIdentityError, match="kimi_timeout_contract_invalid"):
        _contract(unsafe, "Kimi-K3")

    for invalid_thinking in (
        {"enable_thinking": 1, "preserve_thinking": True},
        {"enable_thinking": True, "preserve_thinking": True, "extra": True},
    ):
        unsafe = _resolved_config()
        unsafe["sampling"]["chat_template_kwargs"] = invalid_thinking
        with pytest.raises(EvalIdentityError, match="reasoning_contract_required"):
            _contract(unsafe, "approved-model")


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("timeout", "setup", 3_599),
        ("timeout", "setup", True),
        ("timeout", "finalize", 3_599),
        ("timeout", "scoring", 21_599),
        ("client", "connect_timeout", 119),
    ],
)
def test_kimi_timeout_contract_rejects_weakened_fixed_stage(
    section: str,
    key: str,
    value: object,
) -> None:
    config = _resolved_config()
    config[section][key] = value

    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        validate_kimi_timeout_contract(config)


def test_kimi_timeout_contract_accepts_pydantic_resolved_exact_floats() -> None:
    config_path = Path(__file__).parents[1] / "configs/eval/tb4_kimi_k3_max_miniswe.toml"
    config = eval_run_identity.EvalConfig.model_validate(tomllib.loads(config_path.read_text())).model_dump(
        mode="json", exclude_none=True
    )

    assert isinstance(config["timeout"]["rollout"], float)
    validate_kimi_timeout_contract(config, required_profile="full")
    validate_kimi_retry_contract(config)


@pytest.mark.parametrize(
    ("rollout_timeout", "session_timeout"),
    [
        (28_799, 32_400),
        (28_800, 32_401),
        (35_999, 43_200),
        (36_000, 43_199),
        (28_800, 43_200),
        (36_000, 32_400),
    ],
)
def test_kimi_timeout_contract_rejects_unreviewed_or_swapped_pair(
    rollout_timeout: int,
    session_timeout: int,
) -> None:
    config = _resolved_config()
    config["timeout"]["rollout"] = rollout_timeout
    config["harness"]["runtime"]["session_timeout"] = session_timeout

    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        validate_kimi_timeout_contract(config)


def test_kimi_timeout_contract_distinguishes_smoke_and_full_profiles() -> None:
    full = _resolved_config()
    full["client"]["timeout"] = 43_200
    full["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
    validate_kimi_timeout_contract(full, required_profile="full")
    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        validate_kimi_timeout_contract(full, required_profile="smoke")

    smoke = _resolved_config()
    smoke["client"]["timeout"] = 43_200
    smoke["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
    smoke["timeout"]["rollout"] = 28_800
    smoke["harness"]["runtime"]["session_timeout"] = 32_400
    validate_kimi_timeout_contract(smoke, required_profile="smoke")
    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        validate_kimi_timeout_contract(smoke, required_profile="full")


def test_kimi_eval_role_selects_approved_smoke_or_full_timeout_profile() -> None:
    config = _resolved_config()
    config["model"] = "Kimi-K3"
    config["client"]["timeout"] = 43_200
    config["harness"]["config_overrides"] = ["model.model_kwargs.timeout=43200"]
    config["taskset"] = {}

    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        _contract(config, "Kimi-K3", role="smoke")
    _contract(config, "Kimi-K3", role="tb4")

    config["taskset"]["dataset_revision"] = "1" * 40
    _contract(config, "Kimi-K3", role="smoke")

    config["taskset"].pop("dataset_revision")
    config["timeout"]["rollout"] = 28_800
    config["harness"]["runtime"]["session_timeout"] = 32_400
    _contract(config, "Kimi-K3", role="smoke")
    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        _contract(config, "Kimi-K3", role="tb4")


@pytest.mark.parametrize(("role", "smoke"), [("smoke", True), ("tb4", False)])
def test_kimi_sandoq_host_contract_uses_approved_timeout_and_zero_retry(
    role: str,
    smoke: bool,
) -> None:
    config = _sandoq_kimi_config(smoke=smoke)

    timeout_contract = validate_kimi_timeout_contract(config, required_profile="smoke" if smoke else "full")
    retry_contract = validate_kimi_retry_contract(config)
    contract, execution = _contract(
        config,
        "Kimi-K3",
        role=role,
        sandbox_provider="sandoq",
    )

    assert timeout_contract["harness_request_timeout"] == 15_000
    assert retry_contract["max_retries"] == 0
    assert contract["harness"]["id"] == "terminal-bench-sandoq-host"
    assert execution["runtime"]["type"] == "sandoq"


@pytest.mark.parametrize(
    "rollout_retries",
    [
        {"max_retries": 1, "include": ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]},
        {"max_retries": True, "include": ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]},
        {"max_retries": 2, "include": []},
        {"max_retries": 2, "include": ["ProviderError", "SandboxError", "TunnelError"]},
        {
            "max_retries": 2,
            "include": [
                "ProviderError",
                "SandboxError",
                "TunnelError",
                "HarnessError",
            ],
        },
        {
            "max_retries": 2,
            "include": [
                "ProviderError",
                "SandboxError",
                "TunnelError",
                "InterceptionError",
                "UnknownError",
            ],
        },
        {
            "max_retries": 2,
            "include": [
                "ProviderError",
                "SandboxError",
                "TunnelError",
                "InterceptionError",
            ],
            "exclude": ["InterceptionError"],
        },
    ],
)
def test_kimi_retry_contract_rejects_broad_missing_or_swapped_policy(
    rollout_retries: dict[str, object],
) -> None:
    config = _resolved_config()
    config["retries"]["rollout"] = rollout_retries

    with pytest.raises(EvalIdentityError, match="^kimi_retry_contract_invalid$"):
        validate_kimi_retry_contract(config)


def test_kimi_retry_contract_rejects_missing_policy() -> None:
    config = _resolved_config()
    config.pop("retries")

    with pytest.raises(EvalIdentityError, match="^kimi_retry_contract_invalid$"):
        validate_kimi_retry_contract(config)


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
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n")
    generated_proxy_config = deployment_dir / "proxy_litellm_config.yaml"
    generated_proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n")
    proxy_info = deployment_dir / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8100,
                "url": "http://127.0.0.1:8100",
                "api_key": "unit-test-secret",
                "model": "Kimi-K3",
                "proxy_jobid": "12345",
                "extras": {"proxy_type": "litellm", "sticky": True, "redis_port": 6379},
            }
        )
        + "\n"
    )
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256(proxy_info),
    ).binding
    backend_sha256 = hashlib.sha256(b"http://worker-0:8000/v1").hexdigest()
    serving_route_generation = {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": "900",
            "started_at": "2026-09-17T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": "12345",
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
        "routes": [
            {
                "slurm_job_id": "12345",
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": f"backend-sha256:{backend_sha256}",
            }
        ],
    }
    proxy_policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=_sha256(spec),
        expected_request_timeout=43_200,
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "passed",
                "deployment": deployment_id,
                "observed_spec_sha256": _sha256(spec),
                "endpoint": endpoint,
                "proxy_policy": proxy_policy,
                "serving_route_generation": serving_route_generation,
                "expected_routes": 1,
                "last_status": {
                    "schema_version": 4,
                    "deployment_id": deployment_id,
                    "phase": "serving",
                    "desired": 1,
                    "ready": 1,
                    "running_not_ready": 0,
                    "pending": 0,
                    "coordinator_incarnation": serving_route_generation["coordinator"],
                    "coord_ticks_completed": 10,
                    "serving_route_generation": serving_route_generation,
                },
                "probe": {
                    "ok": True,
                    "endpoint_authority_sha256": endpoint["authority_sha256"],
                    "coverage": {
                        "ok": True,
                        "expected_routes": 1,
                        "discovered_routes": 1,
                        "backends": [f"backend-sha256:{backend_sha256}"],
                    },
                },
            }
        )
        + "\n"
    )
    smoke_identity = _identity()
    smoke_identity["contract"]["model"] = "Kimi-K3"
    smoke_identity["deployment"] = {
        "id": deployment_id,
        "endpoint": endpoint,
        "serving_route_generation": serving_route_generation,
        "proxy_policy": proxy_policy,
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
        path = tmp_path / ("results.jsonl" if name == "results" else name)
        path.write_bytes(f"opaque {name}".encode())
        artifacts[name] = {"path": str(path), "sha256": _sha256(path)}
    invocations = tmp_path / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
                "role": "smoke",
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "1",
            }
        )
        + "\n"
    )
    artifacts["eval_invocations"] = {
        "path": str(invocations),
        "sha256": _sha256(invocations),
    }
    guard_receipt_path = tmp_path / "route_guard_success.json"
    guard_receipt = build_guard_success_receipt(
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        eval_run_role="smoke",
        eval_run_identity=eval_identity,
        eval_invocations=invocations,
        results=Path(artifacts["results"]["path"]),
        deployment_id=deployment_id,
        deployment_spec_sha256=_sha256(spec),
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=_sha256(readiness),
        endpoint=endpoint,
        serving_route_generation=serving_route_generation,
        proxy_policy=proxy_policy,
    )
    write_guard_success_receipt(guard_receipt_path, guard_receipt)
    artifacts["route_guard_success"] = {
        "path": str(guard_receipt_path),
        "sha256": _sha256(guard_receipt_path),
    }
    smoke_body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
        "deployment": {"id": deployment_id, "spec_sha256": _sha256(spec)},
        "endpoint": endpoint,
        "serving_route_generation": serving_route_generation,
        "proxy_policy": proxy_policy,
        "audit_policy": {
            "expected_traces": 2,
            "rollouts_per_task": 1,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": eval_run_identity.EXPECTED_MODEL_IO_CONTRACT,
            "require_request_graph_match": True,
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
        expected_model="Kimi-K3",
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
    promotion.write_text(
        json.dumps(
            {
                "state": "passed",
                "deployment": {
                    "endpoint": endpoint,
                    "serving_route_generation": serving_route_generation,
                    "proxy_policy": proxy_policy,
                },
            }
        )
        + "\n"
    )
    args.role = "mobius"
    args.promotion_certificate = promotion
    args.promotion_certificate_sha256 = _sha256(promotion)
    deployment = _checkpoint_identity(args, endpoint)
    assert deployment["promotion_certificate"]["sha256"] == _sha256(promotion)
    args.role = "tb4"
    args.promotion_certificate = None
    args.promotion_certificate_sha256 = None
    smoke_payload["audit_policy"]["require_request_graph_match"] = False
    smoke_payload["smoke_checkpoint_sha256"] = hashlib.sha256(
        canonical_json({key: value for key, value in smoke_payload.items() if key != "smoke_checkpoint_sha256"})
    ).hexdigest()
    smoke.write_text(json.dumps(smoke_payload, sort_keys=True) + "\n")
    args.smoke_checkpoint_sha256 = _sha256(smoke)
    with pytest.raises(EvalIdentityError, match="smoke_checkpoint_not_passed"):
        _checkpoint_identity(args, endpoint)
    smoke_payload["audit_policy"]["require_request_graph_match"] = True
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

    historical_spec = tmp_path / "historical-spec-policy.json"
    historical_policy = tmp_path / "historical-policy.json"
    historical_spec.write_bytes(deployment_spec_policy_snapshot(_sha256(spec), proxy_policy))
    historical_policy.write_bytes(deployment_proxy_policy_snapshot(proxy_policy))
    spec.write_text(
        "spec:\n  num_endpoints: 24\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n"
    )
    generated_proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\nmodel_list: []\n")
    with pytest.raises(EvalIdentityError, match="deployment_spec_sha256_mismatch"):
        _verify_checkpoint_records(smoke_identity, endpoint)
    _verify_checkpoint_records(
        smoke_identity,
        endpoint,
        deployment_spec_snapshot=historical_spec,
        proxy_policy_snapshot=historical_policy,
    )


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
            "outbound_body_denylist": sorted(["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]),
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
