from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import sft_run_identity as identity


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_private_union_artifact_rejects_exposed_mode(tmp_path: Path, mode: int) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    path = run / identity.PROVIDER_UNION_CERTIFICATE_FILENAME
    path.write_text("{}\n")
    path.chmod(mode)

    with pytest.raises(identity.SftRunIdentityError, match="^provider_union_artifact_not_private$"):
        identity._read_private_union_artifact(run, identity.PROVIDER_UNION_CERTIFICATE_FILENAME)


def test_private_union_artifact_rejects_exposed_root(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o755)
    run.chmod(0o755)
    path = run / identity.PROVIDER_UNION_CERTIFICATE_FILENAME
    path.write_text("{}\n")
    path.chmod(0o600)

    with pytest.raises(identity.SftRunIdentityError, match="^provider_union_artifact_not_private$"):
        identity._read_private_union_artifact(run, identity.PROVIDER_UNION_CERTIFICATE_FILENAME)


def test_private_union_artifact_rejects_hardlink(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    path = run / identity.PROVIDER_UNION_CERTIFICATE_FILENAME
    path.write_text("{}\n")
    path.chmod(0o600)
    os.link(path, tmp_path / "alias.json")

    with pytest.raises(identity.SftRunIdentityError, match="^provider_union_artifact_not_private$"):
        identity._read_private_union_artifact(run, identity.PROVIDER_UNION_CERTIFICATE_FILENAME)


def _write_run(tmp_path: Path) -> tuple[Path, dict[str, identity.IdentityArtifact], dict]:
    run = tmp_path / "run"
    inputs = run / "inputs"
    inputs.mkdir(parents=True)
    files = {
        "config.toml": b'[harness.runtime]\ntype = "sandoq"\n',
        "inputs/manifest.json": b"{}\n",
        "inputs/source_config.toml": b"source = true\n",
        "inputs/task_file.txt": b"opaque-task\n",
        "inputs/image_manifest.json": b"{}\n",
        "direct_workers.json": b"{}\n",
    }
    artifacts = {}
    for relative, body in files.items():
        path = run / relative
        path.write_bytes(body)
        artifacts[relative] = identity.IdentityArtifact(len(body), hashlib.sha256(body).hexdigest())
    source = {
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "a" * 64,
        "renderers_commit": "2" * 40,
        "renderers_tree_sha256": "b" * 64,
        "verifiers_commit": identity.SANDOQ_CLEANUP_VERIFIER_COMMIT,
        "verifiers_tree_sha256": "c" * 64,
        "sandbox_provider": "sandoq",
        "derived_image_manifest_sha256": artifacts["inputs/image_manifest.json"].sha256,
        "sandoq_client_version": "pinned-client",
        "sandoq_provider_commit": "3" * 40,
        "sandoq_provider_tree": "4" * 40,
        "sandoq_site_sha256": "d" * 64,
    }
    environment = {
        "environment": identity.SANDOQ_ENVIRONMENT,
        "task_network": "host",
        "pool_size": 64,
        "pool_min_size": 0,
        "tunnel_policy": "named-tunnel-loopback",
        "use_ecr": True,
        "ecr_registry": identity.SANDOQ_ECR_REGISTRY,
        "ecr_region": identity.SANDOQ_ECR_REGION,
        "ecr_pull_through_prefix": identity.SANDOQ_ECR_PULL_THROUGH_PREFIX,
        "allow_dockerhub_fallback": False,
        **identity.sandoq_expected_policy(64),
    }
    value = {
        "schema_version": 1,
        "role": "qwen-direct",
        "source": source,
        "config": {
            "source": {
                "path": str((run / "inputs/source_config.toml").resolve()),
                "sha256": artifacts["inputs/source_config.toml"].sha256,
            },
            "resolved": {
                "path": str((run / "config.toml").resolve()),
                "sha256": artifacts["config.toml"].sha256,
            },
        },
        "inputs": {
            "manifest": {
                "path": str((run / "inputs/manifest.json").resolve()),
                "sha256": artifacts["inputs/manifest.json"].sha256,
            },
            "task_file": {
                "path": str((run / "inputs/task_file.txt").resolve()),
                "sha256": artifacts["inputs/task_file.txt"].sha256,
                "count": 1,
            },
            "image_manifest": {
                "path": str((run / "inputs/image_manifest.json").resolve()),
                "sha256": artifacts["inputs/image_manifest.json"].sha256,
            },
        },
        "dataset": {
            "kind": "git_revision",
            "revision": "5" * 40,
            "content_sha256": None,
        },
        "deployment": {
            "kind": "direct_qwen",
            "worker_manifest": {
                "path": str((run / "direct_workers.json").resolve()),
                "sha256": artifacts["direct_workers.json"].sha256,
            },
            "spec_sha256": "e" * 64,
            "endpoint_bundle_sha256": "f" * 64,
            "base_url": "http://127.0.0.1:8000/v1",
            "router": {
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "provider_concurrency": 32,
            },
        },
        "contract": {
            "model": "Qwen3.8-2.4T-A95B",
            "reasoning_effort": "max",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "sampling_max_tokens": 32_768,
            "capture_model_io": True,
        },
        "execution": {
            "cleanup_must_succeed": True,
            "rollout_concurrency": 64,
            "multiplex": 64,
            "http_max_connections": 32,
            "http_max_keepalive_connections": 32,
            "runtime": {
                "type": "sandoq",
                "mode": "oci-runner",
                "network_access": False,
                "host_tunnel": "sandoq",
                "expected_environment": identity.SANDOQ_ENVIRONMENT,
                "guest_tunnel_url": "http://127.0.0.1:8485",
                "tunnel_pool_size": 8,
            },
            "sandoq_environment": environment,
        },
    }
    envelope = {
        "schema_version": 1,
        "eval_run_identity_sha256": hashlib.sha256(identity._canonical_json(value)).hexdigest(),
        "identity": value,
    }
    path = run / identity.EVAL_RUN_IDENTITY_FILENAME
    path.write_text(json.dumps(envelope, sort_keys=True) + "\n")
    return run, artifacts, envelope


def test_sandoq_identity_is_bound_and_reduced_without_session_payloads(tmp_path: Path) -> None:
    run, artifacts, envelope = _write_run(tmp_path)

    binding = identity.load_sft_run_identity(
        run,
        artifacts,
        (run / "config.toml").read_bytes(),
        identity_loader=lambda _path, *, verify_references: envelope,
    )

    assert binding is not None
    assert binding.provider == "sandoq"
    assert binding.bound_artifacts["direct_workers.json"].sha256 == artifacts["direct_workers.json"].sha256
    manifest = binding.manifest_value(selected_traces=1, excluded_error_traces=0)
    assert manifest["source"]["sandoq_site_sha256"] == "d" * 64
    assert manifest["environment"]["allow_dockerhub_fallback"] is False
    assert manifest["concurrency"]["rollout_concurrency"] == 64
    assert manifest["cleanup"]["cleanup_implied_successful_traces"] == 1
    encoded = json.dumps(manifest, sort_keys=True).lower()
    assert "sandbox_id" not in encoded
    assert "provider_session" not in encoded
    assert identity.validate_manifest_identity(manifest, counts={"selected_traces": 1, "excluded_error_traces": 0})


@pytest.mark.parametrize(
    ("section", "key", "value", "code"),
    [
        ("source", "sandoq_site_sha256", None, "sandoq_eval_run_identity_invalid"),
        ("source", "verifiers_commit", "0" * 40, "sandoq_cleanup_contract_unpinned"),
        ("environment", "allow_dockerhub_fallback", True, "sandoq_eval_run_identity_invalid"),
    ],
)
def test_sandoq_identity_rejects_unbound_contracts(
    tmp_path: Path,
    section: str,
    key: str,
    value: object,
    code: str,
) -> None:
    run, artifacts, envelope = _write_run(tmp_path)
    if section == "source":
        envelope["identity"]["source"][key] = value
    else:
        envelope["identity"]["execution"]["sandoq_environment"][key] = value
    (run / identity.EVAL_RUN_IDENTITY_FILENAME).write_text(json.dumps(envelope, sort_keys=True) + "\n")

    with pytest.raises(identity.SftRunIdentityError, match=f"^{code}$"):
        identity.load_sft_run_identity(
            run,
            artifacts,
            (run / "config.toml").read_bytes(),
            identity_loader=lambda _path, *, verify_references: envelope,
        )


def test_sandoq_manifest_cleanup_counts_fail_closed(tmp_path: Path) -> None:
    run, artifacts, envelope = _write_run(tmp_path)
    binding = identity.load_sft_run_identity(
        run,
        artifacts,
        (run / "config.toml").read_bytes(),
        identity_loader=lambda _path, *, verify_references: envelope,
    )
    assert binding is not None
    manifest = binding.manifest_value(selected_traces=1, excluded_error_traces=0)
    manifest["cleanup"]["cleanup_implied_successful_traces"] = 2

    with pytest.raises(identity.SftRunIdentityError, match="^sandoq_cleanup_provenance_invalid$"):
        identity.validate_manifest_identity(
            manifest,
            counts={"selected_traces": 1, "excluded_error_traces": 0},
        )


def test_identity_compatibility_rejects_mixed_and_different_providers() -> None:
    vmvm = {"sandbox_provider": "vmvm", "compatibility_sha256": "a" * 64}
    sandoq = {"sandbox_provider": "sandoq", "compatibility_sha256": "b" * 64}
    with pytest.raises(identity.SftRunIdentityError, match="^mixed_eval_run_identity$"):
        identity.compatible_manifest_identities(None, sandoq)
    with pytest.raises(identity.SftRunIdentityError, match="^incompatible_eval_run_identity$"):
        identity.compatible_manifest_identities(vmvm, sandoq)
