#!/usr/bin/env python3
"""Validate and reduce an eval identity into non-sensitive SFT provenance.

The eval identity remains the authority for the full launch contract.  SFT
artifacts retain only hashes and operational metadata; task, trace, model, tool,
and provider-session payloads are deliberately excluded.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

EVAL_RUN_IDENTITY_FILENAME = "eval_run_identity.json"
MAX_IDENTITY_BYTES = 4 * 1024 * 1024
SHA256_HEX = frozenset("0123456789abcdef")
SANDOQ_CLEANUP_VERIFIER_COMMIT = "25fa6d57400ef3f452d4c34d874f524ab43c18d5"
SANDOQ_ENVIRONMENT = "oci-runner-firecracker-tunnel-pull"
SANDOQ_ECR_REGISTRY = "168653207203.dkr.ecr.us-east-2.amazonaws.com"
SANDOQ_ECR_REGION = "us-east-2"
SANDOQ_ECR_PULL_THROUGH_PREFIX = "pt_dockerio"
SANDOQ_REQUIRED_POLICY = {
    "create_deadline": "30m",
    "gateway_retry_attempts": "15",
    "gateway_retry_interval": "2s",
    "podman_ignore_chown_errors": "1",
    "pool_drain_timeout": "240",
    "lease_duration": "1h",
    "pool_max_reuse_count": "6",
    "pool_renew_interval": "5m",
    "pull_poll_max_errors": "10",
    "pull_timeout": "1200",
    "require_resource_limits": "1",
    "session_reuse": "1",
}


def sandoq_expected_policy(pool_size: int) -> dict[str, str]:
    return {
        **SANDOQ_REQUIRED_POLICY,
        "pool_bootstrap_per_image": str(min(pool_size, 8)),
        "pool_bootstrap_workers": str(min(pool_size, 64)),
        "pool_create_workers": str(min(pool_size, 32)),
        "pool_drain_workers": str(min(pool_size, 32)),
        "pool_renew_workers": str(min(pool_size, 16)),
    }


class SftRunIdentityError(RuntimeError):
    """A fail-closed identity error represented by a non-sensitive code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class IdentityArtifact:
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {"bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class SftRunIdentity:
    artifact: IdentityArtifact
    eval_run_identity_sha256: str
    provider: str
    provenance: Mapping[str, Any]
    compatibility_sha256: str
    bound_artifacts: Mapping[str, IdentityArtifact] = field(default_factory=dict)

    def manifest_value(
        self,
        *,
        selected_traces: int,
        excluded_error_traces: int,
    ) -> dict[str, Any]:
        value = dict(self.provenance)
        if self.provider == "sandoq":
            value["cleanup"] = {
                "cleanup_implied_successful_traces": selected_traces,
                "excluded_error_traces": excluded_error_traces,
                "must_succeed": True,
                "selected_error_free_traces": selected_traces,
                "semantics": "runtime teardown failure is captured as trace.error",
            }
        return value


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SftRunIdentityError("eval_run_identity_provenance_invalid") from error


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and not (set(value) - SHA256_HEX)


def _read_regular(path: Path) -> tuple[bytes, IdentityArtifact]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SftRunIdentityError("eval_run_identity_unreadable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_IDENTITY_BYTES:
            raise SftRunIdentityError("eval_run_identity_invalid")
        body = bytearray()
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    file_identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
    if file_identity(before) != file_identity(after):
        raise SftRunIdentityError("eval_run_identity_changed")
    return bytes(body), IdentityArtifact(bytes=after.st_size, sha256=digest.hexdigest())


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and not (set(value) - SHA256_HEX)


def _valid_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _artifact_values(record: object) -> tuple[str, str]:
    if not isinstance(record, dict) or not {"path", "sha256"}.issubset(record):
        raise SftRunIdentityError("eval_run_identity_binding_invalid")
    path = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path, str) or not Path(path).is_absolute() or not _valid_sha256(digest):
        raise SftRunIdentityError("eval_run_identity_binding_invalid")
    return path, digest


def _bind_artifact(record: object, expected_path: Path, expected_sha256: str) -> None:
    path, digest = _artifact_values(record)
    try:
        recorded = Path(path).resolve(strict=True)
        expected = expected_path.resolve(strict=True)
    except OSError as error:
        raise SftRunIdentityError("eval_run_identity_binding_invalid") from error
    if recorded != expected or digest != expected_sha256:
        raise SftRunIdentityError("eval_run_identity_binding_mismatch")


def _source_artifact_sha256(source_artifacts: Mapping[str, Any], relative: str) -> str:
    source_artifact = source_artifacts.get(relative)
    expected_sha256 = getattr(source_artifact, "sha256", None)
    if expected_sha256 is None and isinstance(source_artifact, Mapping):
        expected_sha256 = source_artifact.get("sha256")
    if not _valid_sha256(expected_sha256):
        raise SftRunIdentityError("eval_run_identity_source_artifact_missing")
    return expected_sha256


def _runtime_provider(config_body: bytes) -> str | None:
    try:
        config = tomllib.loads(config_body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SftRunIdentityError("resolved_config_invalid") from error
    harness = config.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    provider = runtime.get("type") if isinstance(runtime, dict) else None
    if provider is not None and provider not in {"vmvm", "sandoq"}:
        raise SftRunIdentityError("sandbox_provider_invalid")
    return provider


def _sandoq_provenance(identity: Mapping[str, Any]) -> dict[str, Any]:
    source = identity["source"]
    execution = identity["execution"]
    environment = execution.get("sandoq_environment")
    runtime = execution.get("runtime")
    required_source = {
        "derived_image_manifest_sha256",
        "sandoq_client_version",
        "sandoq_provider_commit",
        "sandoq_provider_tree",
        "sandoq_site_sha256",
        "verifiers_commit",
    }
    if not isinstance(environment, dict) or not isinstance(runtime, dict):
        raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    if not required_source.issubset(source) or not _valid_sha256(source.get("sandoq_site_sha256")):
        raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    if source.get("verifiers_commit") != SANDOQ_CLEANUP_VERIFIER_COMMIT:
        raise SftRunIdentityError("sandoq_cleanup_contract_unpinned")
    pool_size = environment.get("pool_size")
    pool_min_size = environment.get("pool_min_size")
    if (
        not isinstance(pool_size, int)
        or isinstance(pool_size, bool)
        or not isinstance(pool_min_size, int)
        or isinstance(pool_min_size, bool)
    ):
        raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    expected_policy = sandoq_expected_policy(pool_size)
    if (
        environment.get("environment") != SANDOQ_ENVIRONMENT
        or environment.get("task_network") != "host"
        or environment.get("tunnel_policy") != "named-tunnel-loopback"
        or environment.get("use_ecr") is not True
        or environment.get("ecr_registry") != SANDOQ_ECR_REGISTRY
        or environment.get("ecr_region") != SANDOQ_ECR_REGION
        or environment.get("ecr_pull_through_prefix") != SANDOQ_ECR_PULL_THROUGH_PREFIX
        or environment.get("allow_dockerhub_fallback") is not False
        or any(environment.get(key) != value for key, value in expected_policy.items())
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not False
        or runtime.get("host_tunnel") != "sandoq"
        or runtime.get("expected_environment") != SANDOQ_ENVIRONMENT
        or runtime.get("guest_tunnel_url") != "http://127.0.0.1:8485"
        or execution.get("cleanup_must_succeed") is not True
    ):
        raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    for key in (
        "rollout_concurrency",
        "multiplex",
        "http_max_connections",
        "http_max_keepalive_connections",
    ):
        value = execution.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    if pool_size < execution["rollout_concurrency"] or pool_min_size != 0:
        raise SftRunIdentityError("sandoq_eval_run_identity_invalid")
    return {
        "cleanup_must_succeed": True,
        "environment": dict(environment),
        "runtime": dict(runtime),
    }


def _provenance(
    envelope: Mapping[str, Any],
    artifact: IdentityArtifact,
) -> tuple[str, dict[str, Any], str]:
    identity = envelope["identity"]
    source = identity["source"]
    execution = identity["execution"]
    provider = source.get("sandbox_provider", "vmvm")
    if provider not in {"vmvm", "sandoq"}:
        raise SftRunIdentityError("sandbox_provider_invalid")
    identity_sha256 = envelope.get("eval_run_identity_sha256")
    if not _valid_sha256(identity_sha256):
        raise SftRunIdentityError("eval_run_identity_digest_invalid")
    source_fields = {
        key: source[key]
        for key in (
            "prime_rl_commit",
            "prime_rl_tree_sha256",
            "renderers_commit",
            "renderers_tree_sha256",
            "verifiers_commit",
            "verifiers_tree_sha256",
        )
    }
    provider_execution: dict[str, Any]
    if provider == "sandoq":
        source_fields.update(
            {
                key: source[key]
                for key in (
                    "derived_image_manifest_sha256",
                    "sandoq_client_version",
                    "sandoq_provider_commit",
                    "sandoq_provider_tree",
                    "sandoq_site_sha256",
                )
            }
        )
        provider_execution = _sandoq_provenance(identity)
    else:
        source_fields["vmvm_tb_v2_sha256"] = source["vmvm_tb_v2_sha256"]
        provider_execution = {
            "environment": dict(execution["vmvm_environment"]),
            "runtime": dict(execution["runtime"]),
        }
    concurrency = {
        key: execution[key]
        for key in (
            "http_max_connections",
            "http_max_keepalive_connections",
            "multiplex",
            "rollout_concurrency",
        )
    }
    deployment = identity["deployment"]
    if identity["role"] == "qwen-direct":
        deployment_compatibility = {
            "base_url_sha256": hashlib.sha256(deployment["base_url"].encode("utf-8")).hexdigest(),
            "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
            "kind": "direct_qwen",
            "router": deployment["router"],
            "spec_sha256": deployment["spec_sha256"],
            "worker_manifest": {
                "sha256": deployment["worker_manifest"]["sha256"],
            },
        }
    else:
        deployment_compatibility = {
            "id": deployment["id"],
            "endpoint_authority_sha256": deployment["endpoint"]["authority_sha256"],
            "proxy_policy": deployment["proxy_policy"],
        }
    compatibility = {
        "contract": {
            "model": identity["contract"]["model"],
            "reasoning_effort": identity["contract"]["reasoning_effort"],
            "thinking": identity["contract"]["thinking"],
            "context_tokens": identity["contract"]["context_tokens"],
            "sampling_max_tokens": identity["contract"]["sampling_max_tokens"],
            "capture_model_io": identity["contract"]["capture_model_io"],
        },
        "dataset": {
            "kind": identity["dataset"]["kind"],
            "revision": identity["dataset"]["revision"],
            "content_sha256": identity["dataset"]["content_sha256"],
        },
        "deployment": deployment_compatibility,
        "execution": {"concurrency": concurrency, **provider_execution},
        "sandbox_provider": provider,
        "source": source_fields,
    }
    compatibility_sha256 = hashlib.sha256(_canonical_json(compatibility)).hexdigest()
    provenance = {
        "artifact": artifact.as_dict(),
        "compatibility": compatibility,
        "compatibility_sha256": compatibility_sha256,
        "concurrency": concurrency,
        "eval_run_identity_sha256": identity_sha256,
        "role": identity["role"],
        "sandbox_provider": provider,
        "schema_version": 1,
        "source": source_fields,
        **provider_execution,
    }
    return provider, provenance, compatibility_sha256


def load_sft_run_identity(
    run_dir: Path,
    source_artifacts: Mapping[str, Any],
    config_body: bytes,
    *,
    identity_loader: Callable[..., Mapping[str, Any]] | None = None,
) -> SftRunIdentity | None:
    """Load, fully validate, and bind an optional eval identity to one run."""
    path = run_dir / EVAL_RUN_IDENTITY_FILENAME
    runtime_provider = _runtime_provider(config_body)
    if not os.path.lexists(path):
        if runtime_provider == "sandoq":
            raise SftRunIdentityError("sandoq_eval_run_identity_missing")
        return None
    body, artifact = _read_regular(path)
    if identity_loader is None:
        try:
            from eval_run_identity import load_eval_run_identity

            identity_loader = load_eval_run_identity
        except Exception as error:
            raise SftRunIdentityError("eval_run_identity_validator_unavailable") from error
    try:
        envelope = identity_loader(path, verify_references=True)
    except Exception as error:
        raise SftRunIdentityError("eval_run_identity_validation_failed") from error
    if _read_regular(path)[1] != artifact:
        raise SftRunIdentityError("eval_run_identity_changed")
    try:
        if _canonical_json(json.loads(body)) != _canonical_json(envelope):
            raise SftRunIdentityError("eval_run_identity_loader_mismatch")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SftRunIdentityError("eval_run_identity_invalid") from error
    identity = envelope.get("identity")
    if not isinstance(identity, dict) or identity.get("role") not in {
        "mobius",
        "qwen-direct",
    }:
        raise SftRunIdentityError("eval_run_identity_role_invalid")
    provider, provenance, compatibility_sha256 = _provenance(envelope, artifact)
    if runtime_provider != provider:
        raise SftRunIdentityError("sandbox_provider_mismatch")
    if provider == "sandoq" and identity["role"] != "qwen-direct":
        raise SftRunIdentityError("sandoq_eval_run_identity_role_invalid")
    paths = {
        "config.toml": identity["config"]["resolved"],
        "inputs/manifest.json": identity["inputs"]["manifest"],
        "inputs/source_config.toml": identity["config"]["source"],
        "inputs/task_file.txt": identity["inputs"]["task_file"],
    }
    image_identity = identity["inputs"].get("image_manifest")
    if image_identity is not None:
        paths["inputs/image_manifest.json"] = image_identity
    for relative, record in paths.items():
        expected_sha256 = _source_artifact_sha256(source_artifacts, relative)
        _bind_artifact(record, run_dir / relative, expected_sha256)
    if provider == "sandoq":
        if image_identity is None or identity["source"]["derived_image_manifest_sha256"] != _source_artifact_sha256(
            source_artifacts, "inputs/image_manifest.json"
        ):
            raise SftRunIdentityError("sandoq_image_manifest_mismatch")
    bound_artifacts: dict[str, IdentityArtifact] = {}
    if identity["role"] == "qwen-direct":
        worker_path = run_dir / "direct_workers.json"
        _worker_body, worker_artifact = _read_regular(worker_path)
        _bind_artifact(
            identity["deployment"]["worker_manifest"],
            worker_path,
            worker_artifact.sha256,
        )
        bound_artifacts["direct_workers.json"] = worker_artifact
    return SftRunIdentity(
        artifact=artifact,
        eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
        provider=provider,
        provenance=provenance,
        compatibility_sha256=compatibility_sha256,
        bound_artifacts=bound_artifacts,
    )


def validate_manifest_identity(value: object, *, counts: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate exported identity provenance without reopening external references."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SftRunIdentityError("sft_run_identity_invalid")
    provider = value.get("sandbox_provider")
    common = {
        "artifact",
        "compatibility",
        "compatibility_sha256",
        "concurrency",
        "environment",
        "eval_run_identity_sha256",
        "role",
        "runtime",
        "sandbox_provider",
        "schema_version",
        "source",
    }
    expected = common | ({"cleanup", "cleanup_must_succeed"} if provider == "sandoq" else set())
    if (
        provider not in {"vmvm", "sandoq"}
        or set(value) != expected
        or value.get("schema_version") != 1
        or value.get("role") not in {"mobius", "qwen-direct"}
        or not _valid_sha256(value.get("eval_run_identity_sha256"))
        or not _valid_sha256(value.get("compatibility_sha256"))
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    compatibility = value.get("compatibility")
    source = value.get("source")
    concurrency = value.get("concurrency")
    environment = value.get("environment")
    runtime = value.get("runtime")
    common_source_keys = {
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
    }
    provider_source_keys = (
        {
            "derived_image_manifest_sha256",
            "sandoq_client_version",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
            "sandoq_site_sha256",
        }
        if provider == "sandoq"
        else {"vmvm_tb_v2_sha256"}
    )
    if (
        not isinstance(source, dict)
        or set(source) != common_source_keys | provider_source_keys
        or any(
            not _valid_git_sha(source.get(key)) for key in ("prime_rl_commit", "renderers_commit", "verifiers_commit")
        )
        or any(
            not _valid_sha256(source.get(key))
            for key in (
                "prime_rl_tree_sha256",
                "renderers_tree_sha256",
                "verifiers_tree_sha256",
            )
        )
        or not isinstance(concurrency, dict)
        or set(concurrency)
        != {
            "http_max_connections",
            "http_max_keepalive_connections",
            "multiplex",
            "rollout_concurrency",
        }
        or any(not _valid_positive_integer(item) for item in concurrency.values())
        or not isinstance(environment, dict)
        or not isinstance(runtime, dict)
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if provider == "sandoq" and (
        not _valid_sha256(source.get("derived_image_manifest_sha256"))
        or not _valid_sha256(source.get("sandoq_site_sha256"))
        or not _valid_git_sha(source.get("sandoq_provider_commit"))
        or not _valid_git_sha(source.get("sandoq_provider_tree"))
        or not isinstance(source.get("sandoq_client_version"), str)
        or not source["sandoq_client_version"]
        or any(character in source["sandoq_client_version"] for character in "\r\n=")
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if provider == "vmvm" and not _valid_sha256(source.get("vmvm_tb_v2_sha256")):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if (
        not isinstance(compatibility, dict)
        or set(compatibility)
        != {
            "contract",
            "dataset",
            "deployment",
            "execution",
            "sandbox_provider",
            "source",
        }
        or hashlib.sha256(_canonical_json(compatibility)).hexdigest() != value["compatibility_sha256"]
        or compatibility.get("sandbox_provider") != provider
        or compatibility.get("source") != value.get("source")
        or not isinstance(compatibility.get("execution"), dict)
        or compatibility["execution"].get("concurrency") != value.get("concurrency")
        or compatibility["execution"].get("environment") != value.get("environment")
        or compatibility["execution"].get("runtime") != value.get("runtime")
        or compatibility["execution"].get("cleanup_must_succeed") != value.get("cleanup_must_succeed")
        or not isinstance(compatibility.get("contract"), dict)
        or compatibility["contract"].get("capture_model_io") is not True
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    contract = compatibility["contract"]
    dataset = compatibility.get("dataset")
    deployment = compatibility.get("deployment")
    if (
        set(contract)
        != {
            "capture_model_io",
            "context_tokens",
            "model",
            "reasoning_effort",
            "sampling_max_tokens",
            "thinking",
        }
        or not isinstance(contract.get("model"), str)
        or not contract["model"]
        or contract.get("reasoning_effort") != "high"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or contract.get("context_tokens")
        != {
            "max_input_tokens": 262_144,
            "max_output_tokens": 262_144,
            "max_total_tokens": 262_144,
        }
        or not _valid_positive_integer(contract.get("sampling_max_tokens"))
        or contract["sampling_max_tokens"] > 262_144
        or not isinstance(dataset, dict)
        or set(dataset) != {"content_sha256", "kind", "revision"}
        or dataset.get("kind") not in {"archive", "git_revision"}
        or (
            dataset["kind"] == "git_revision"
            and (not _valid_git_sha(dataset.get("revision")) or dataset.get("content_sha256") is not None)
        )
        or (
            dataset["kind"] == "archive"
            and (dataset.get("revision") is not None or not _valid_sha256(dataset.get("content_sha256")))
        )
        or not isinstance(deployment, dict)
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if value.get("role") == "qwen-direct":
        router = deployment.get("router")
        worker = deployment.get("worker_manifest")
        if (
            set(deployment)
            != {
                "base_url_sha256",
                "endpoint_bundle_sha256",
                "kind",
                "router",
                "spec_sha256",
                "worker_manifest",
            }
            or deployment.get("kind") != "direct_qwen"
            or not _valid_sha256(deployment.get("base_url_sha256"))
            or not _valid_sha256(deployment.get("endpoint_bundle_sha256"))
            or not _valid_sha256(deployment.get("spec_sha256"))
            or not isinstance(worker, dict)
            or set(worker) != {"sha256"}
            or not _valid_sha256(worker.get("sha256"))
            or not isinstance(router, dict)
            or set(router) != {"policy", "provider_concurrency", "request_id_headers"}
            or router.get("policy") != "consistent_hash"
            or router.get("request_id_headers") != ["x-session-id"]
            or not _valid_positive_integer(router.get("provider_concurrency"))
        ):
            raise SftRunIdentityError("sft_run_identity_invalid")
    artifact = value.get("artifact")
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"bytes", "sha256"}
        or not isinstance(artifact.get("bytes"), int)
        or isinstance(artifact.get("bytes"), bool)
        or artifact["bytes"] < 1
        or not _valid_sha256(artifact.get("sha256"))
    ):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if provider == "sandoq":
        if value.get("role") != "qwen-direct":
            raise SftRunIdentityError("sft_run_identity_invalid")
        try:
            _sandoq_provenance(
                {
                    "source": value["source"],
                    "execution": {
                        **value["concurrency"],
                        "runtime": value["runtime"],
                        "sandoq_environment": value["environment"],
                        "cleanup_must_succeed": value["cleanup_must_succeed"],
                    },
                }
            )
        except (KeyError, TypeError, SftRunIdentityError) as error:
            raise SftRunIdentityError("sft_run_identity_invalid") from error
        cleanup = value.get("cleanup")
        selected = counts.get("selected_traces")
        excluded = counts.get("excluded_error_traces")
        if (
            not isinstance(cleanup, dict)
            or set(cleanup)
            != {
                "cleanup_implied_successful_traces",
                "excluded_error_traces",
                "must_succeed",
                "selected_error_free_traces",
                "semantics",
            }
            or cleanup.get("must_succeed") is not True
            or cleanup.get("semantics") != "runtime teardown failure is captured as trace.error"
            or not isinstance(selected, int)
            or isinstance(selected, bool)
            or selected < 0
            or cleanup.get("selected_error_free_traces") != selected
            or cleanup.get("cleanup_implied_successful_traces") != selected
            or cleanup.get("excluded_error_traces") != excluded
        ):
            raise SftRunIdentityError("sandoq_cleanup_provenance_invalid")
    return value


def validate_manifest_source_artifacts(
    value: Mapping[str, Any],
    source_artifacts: Mapping[str, Any],
) -> None:
    """Cross-bind reduced identity fields to the source artifact inventory."""
    identity_artifact = source_artifacts.get(EVAL_RUN_IDENTITY_FILENAME)
    if isinstance(identity_artifact, IdentityArtifact):
        identity_artifact_value = identity_artifact.as_dict()
    elif hasattr(identity_artifact, "as_dict"):
        identity_artifact_value = identity_artifact.as_dict()
    else:
        identity_artifact_value = identity_artifact
    if identity_artifact_value != value.get("artifact"):
        raise SftRunIdentityError("sft_run_identity_artifact_mismatch")
    source = value.get("source")
    if not isinstance(source, dict):
        raise SftRunIdentityError("sft_run_identity_invalid")
    if value.get("sandbox_provider") == "sandoq" and (
        _source_artifact_sha256(source_artifacts, "inputs/image_manifest.json")
        != source.get("derived_image_manifest_sha256")
    ):
        raise SftRunIdentityError("sft_run_identity_image_manifest_mismatch")
    if value.get("role") == "qwen-direct":
        compatibility = value.get("compatibility")
        deployment = compatibility.get("deployment") if isinstance(compatibility, dict) else None
        worker = deployment.get("worker_manifest") if isinstance(deployment, dict) else None
        if (
            not isinstance(worker, dict)
            or set(worker) != {"sha256"}
            or _source_artifact_sha256(source_artifacts, "direct_workers.json") != worker.get("sha256")
        ):
            raise SftRunIdentityError("sft_run_identity_worker_manifest_mismatch")


def compatible_manifest_identities(first: object, second: object) -> None:
    """Reject mixed legacy/provider exports and incompatible native identities."""
    if first is None and second is None:
        return
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise SftRunIdentityError("mixed_eval_run_identity")
    if first.get("sandbox_provider") != second.get("sandbox_provider") or first.get(
        "compatibility_sha256"
    ) != second.get("compatibility_sha256"):
        raise SftRunIdentityError("incompatible_eval_run_identity")
