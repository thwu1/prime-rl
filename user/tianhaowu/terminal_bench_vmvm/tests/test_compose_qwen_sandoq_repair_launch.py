from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path

import compose_qwen_sandoq_repair_launch as composer
import prepare_qwen_sandoq_catalog_plan as plan_generator
import pytest
from materialize_qwen_provider_union import DEPLOYMENT_NAMESPACE, _canonical_json
from terminal_bench_vmvm.offline_verifier_catalog import CatalogIdentity
from terminal_bench_vmvm.source_wheels import canonical_json


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _private(path: Path, body: bytes, mode: int = 0o600) -> Path:
    path.write_bytes(body)
    path.chmod(mode)
    return path


def _hashes(prefix: str, names: set[str]) -> dict[str, str]:
    return {name: _sha(f"{prefix}:{name}") for name in names}


def _config(
    *,
    dataset: Path,
    dataset_revision: str,
    task_file: Path,
    task_file_sha256: str,
    image_manifest: Path,
    image_manifest_sha256: str,
    environment: str,
    ecr_token_file: str,
) -> bytes:
    quote = json.dumps
    return (
        'model = "Qwen3.8-2.4T-A95B"\n'
        "num_tasks = 1233\n"
        "num_rollouts = 1\n"
        "max_concurrent = 64\n"
        "max_turns = 200\n"
        "max_input_tokens = 262144\n"
        "max_output_tokens = 262144\n"
        "max_total_tokens = 262144\n"
        "multiplex = 64\n"
        "rich = false\n"
        "retain_traces = false\n"
        "[client]\n"
        'type = "eval"\n'
        "capture_model_io = true\n"
        'outbound_body_denylist = ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]\n'
        'base_url = "http://127.0.0.1:8000/v1"\n'
        'api_key_var = "OPENAI_API_KEY"\n'
        "timeout = 7200\n"
        "connect_timeout = 30\n"
        "max_connections = 32\n"
        "max_keepalive_connections = 32\n"
        "[sampling]\n"
        'reasoning_effort = "max"\n'
        "temperature = 0.7\n"
        "top_p = 0.95\n"
        "top_k = 20\n"
        "max_tokens = 32768\n"
        "chat_template_kwargs = { enable_thinking = true, preserve_thinking = true }\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f"dataset_dir = {quote(str(dataset))}\n"
        f"dataset_revision = {quote(dataset_revision)}\n"
        f"task_file = {quote(str(task_file))}\n"
        f"task_file_sha256 = {quote(task_file_sha256)}\n"
        f"image_manifest = {quote(str(image_manifest))}\n"
        f"image_manifest_sha256 = {quote(image_manifest_sha256)}\n"
        "ignore_dockerfile = true\n"
        "verifier_runtime_retries = 0\n"
        "[harness]\n"
        'id = "terminal-bench-sandoq-host"\n'
        "command_timeout_seconds = 240\n"
        "command_kill_grace_seconds = 10\n"
        "max_command_output_chars = 100000\n"
        "request_timeout_seconds = 15000\n"
        "[harness.runtime]\n"
        'type = "sandoq"\n'
        'mode = "oci-runner"\n'
        "session_timeout = 43200\n"
        "network_access = true\n"
        'host_tunnel = "none"\n'
        f"expected_environment = {quote(environment)}\n"
        f"ecr_token_file = {quote(ecr_token_file)}\n"
        "[timeout]\n"
        "setup = 3600\n"
        "rollout = 36000\n"
        "finalize = 3600\n"
        "scoring = 21600\n"
        "[retries.rollout]\n"
        "max_retries = 0\n"
    ).encode()


def _policy_value(
    runtime: dict[str, object],
    binding: dict[str, object],
    worker_contract: dict[str, object],
    worker_sha256: str,
) -> dict[str, object]:
    artifacts = runtime["runtime_artifacts"]
    catalog = runtime["catalog_policy"]
    provision = runtime["provision_approval"]
    assert isinstance(artifacts, dict)
    assert isinstance(catalog, dict)
    assert isinstance(provision, dict)
    return {
        "schema_version": plan_generator.SCHEMA_VERSION,
        "kind": plan_generator.KIND,
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "expected_counts": {"repair": 1233, "sandoq": 1233, "vmvm": 0},
        "generator_sha256": artifacts["generator_sha256"],
        "provider_materialization_receipt_sha256": binding[
            "provider_materialization_receipt_sha256"
        ],
        "worker_contract_sha256": provision["worker_contract_sha256"],
        "worker": {
            "executable_sha256": worker_sha256,
            "runtime_sha256": worker_contract["worker_runtime_sha256"],
            "materializer_code_sha256": artifacts["catalog_materializer_sha256"],
            "cleanup_receipt_verifier_sha256": worker_contract[
                "cleanup_receipt_verifier_sha256"
            ],
            "environment_sha256": catalog["worker_environment_sha256"],
            "recovery_scope_sha256": catalog["worker_recovery_scope_sha256"],
            "ecr_rotator_sha256": catalog["ecr_rotator_sha256"],
            "environment_names": catalog["worker_environment_names"],
            "timeouts_seconds": catalog["timeouts_seconds"],
            "concurrency": catalog["concurrency"],
        },
        "catalog_policy": {
            "inventory_probe_code_sha256": worker_contract[
                "inventory_probe_code_sha256"
            ],
            "inventory_probe_environment_sha256": worker_contract[
                "inventory_probe_environment_sha256"
            ],
            "inventory_probe_approval_sha256": catalog[
                "inventory_probe_approval_sha256"
            ],
            "catalog_consumer_code_sha256": artifacts["catalog_consumer_sha256"],
            "requirements_extractor_sha256": artifacts[
                "requirements_extractor_sha256"
            ],
            "source_policy_sha256": catalog["source_policy_sha256"],
            "source_policy_approval_sha256": catalog[
                "source_policy_approval_sha256"
            ],
            "approved_binary_artifacts": catalog["approved_binary_artifacts"],
            "approved_source_attestations": catalog[
                "approved_source_attestations"
            ],
            "approved_toolchains": catalog["approved_toolchains"],
        },
    }


@pytest.fixture()
def synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    project = tmp_path / "project"
    dataset = tmp_path / "dataset"
    project.mkdir()
    dataset.mkdir()
    harness = project / "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_host_harness.py"
    harness.parent.mkdir(parents=True)
    harness.write_text("synthetic harness\n")
    profile_relative = (
        "user/tianhaowu/terminal_bench_vmvm/configs/provider_context/"
        "synthetic_cluster/qwen_sandoq.json"
    )
    profile = project / profile_relative
    profile.parent.mkdir(parents=True)
    profile.write_bytes(
        _canonical_json(
            {
                "schema_version": 1,
                "cluster_identifier": "synthetic_cluster",
                "transport_mode": "loopback",
                "effective_task_network": "public",
                "base_url": composer.SANDOQ_BASE_URL,
                "environment": "oci-runner",
                "provider_token_file": str(tmp_path / "credentials/provider-token"),
            }
        )
    )
    private_root = tmp_path / "synthetic_cluster" / DEPLOYMENT_NAMESPACE
    private_root.mkdir(parents=True, mode=0o700)
    private_root.chmod(0o700)
    code = {
        "project_revision": "1" * 40,
        "project_tree": "2" * 40,
        "verifiers_revision": "3" * 40,
        "renderers_revision": "4" * 40,
        "sandoq_provider_revision": "5" * 40,
    }
    monkeypatch.setattr(composer, "_code_identity", lambda _root: code)

    environment = "oci-runner"
    token_file = str(tmp_path / "credentials/provider-token")
    ecr_token_file = str(tmp_path / "credentials/ecr-token")
    ecr_metadata = str(tmp_path / "credentials/ecr-token.metadata.json")
    task_file = private_root / "repair-sandoq.tasks.txt"
    image_manifest = dataset / "images.json"
    task_sha256 = _sha("opaque task membership")
    image_sha256 = _sha("opaque images")
    dataset_revision = "6" * 40
    source_config_body = _config(
        dataset=dataset,
        dataset_revision=dataset_revision,
        task_file=task_file,
        task_file_sha256=task_sha256,
        image_manifest=image_manifest,
        image_manifest_sha256=image_sha256,
        environment=environment,
        ecr_token_file=ecr_token_file,
    )
    source_config = _private(private_root / "repair-sandoq.toml", source_config_body)
    binding = {
        "schema_version": 1,
        "kind": composer.BINDING_KIND,
        "state": "sealed",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "counts": {"repair": 1233, "sandoq": 1233, "vmvm": 0},
        "provider_materialization_receipt_sha256": _sha("provider receipt"),
        "repair_selection_manifest_sha256": _sha("selection"),
        "repair_union_indices_sha256": _sha("union"),
        "task_file_sha256": task_sha256,
        "task_file_path_sha256": _sha(str(task_file)),
        "source_config_sha256": _sha(source_config_body),
        "source_config_path_sha256": _sha(str(source_config)),
        "dataset_revision": dataset_revision,
        "dataset_path_sha256": _sha(str(dataset)),
        "image_manifest_sha256": image_sha256,
        "image_manifest_path_sha256": _sha(str(image_manifest)),
    }
    binding_body = _canonical_json(binding)
    binding_path = _private(private_root / "repair-binding.json", binding_body)

    environment_names = sorted(
        {
            "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK",
            "OCI_RUNNER_BASE_URL",
            "OCI_RUNNER_ECR_PULL_THROUGH_PREFIX",
            "OCI_RUNNER_ECR_REGION",
            "OCI_RUNNER_ECR_REGISTRY",
            "OCI_RUNNER_ECR_TOKEN_FILE",
            "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
            "OCI_RUNNER_ENVIRONMENT",
            "OCI_RUNNER_POOL_MIN_SIZE",
            "OCI_RUNNER_POOL_SOCKET",
            "OCI_RUNNER_POOL_WAL",
            "OCI_RUNNER_REQUIRE_RESOURCE_LIMITS",
            "OCI_RUNNER_SESSION_REUSE",
            "OCI_RUNNER_TASK_NETWORK",
            "OCI_RUNNER_TOKEN_FILE",
            "SANDOQ_CATALOG_BUILDER_IMAGE",
            "SANDOQ_CATALOG_EXCLUSIVE_POOL",
            "SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256",
            "SANDOQ_CATALOG_WORKER_MODULE",
            "SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256",
            "SANDOQ_CATALOG_WORKER_PYTHON",
            "SANDOQ_CATALOG_WORKER_SITE_MANIFEST",
            "SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256",
            "SANDOQ_CATALOG_WORKER_SITE_ROOT",
            "SANDOQ_OWNER",
            "SANDOQ_PROVIDER_ROOT",
            "VF_SANDBOX_PROVIDER",
        }
    )
    runtime_invariants = {
        "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK": "0",
        "OCI_RUNNER_ENVIRONMENT": environment,
        "OCI_RUNNER_POOL_MIN_SIZE": "0",
        "OCI_RUNNER_REQUIRE_RESOURCE_LIMITS": "1",
        "OCI_RUNNER_SESSION_REUSE": "1",
        "OCI_RUNNER_TASK_NETWORK": "none",
        "SANDOQ_CATALOG_EXCLUSIVE_POOL": "1",
        "VF_SANDBOX_PROVIDER": "sandoq",
    }
    worker_contract = {
        "schema_version": 1,
        "worker_protocol_version": 2,
        "provider_commit": code["sandoq_provider_revision"],
        "provider_tree": "7" * 40,
        "provider_source_sha256": _sha("provider source"),
        "sandoq_client_version": "synthetic-client",
        **_hashes(
            "worker-contract",
            {
                "worker_runtime_sha256",
                "python_runtime_manifest_sha256",
                "worker_provision_identity_sha256",
                "worker_site_manifest_sha256",
                "cleanup_receipt_verifier_sha256",
                "inventory_probe_code_sha256",
                "inventory_probe_environment_sha256",
            },
        ),
        "required_environment_names": environment_names,
        "runtime_invariants": runtime_invariants,
    }
    worker_contract_body = canonical_json(worker_contract)
    worker_contract_path = _private(
        private_root / "worker-contract.json", worker_contract_body
    )
    worker_body = b"#!/bin/sh\nexit 99\n"
    worker = _private(tmp_path / "sealed-worker-launcher", worker_body, 0o500)
    _, worker_path_identity = composer._path_identity(
        worker,
        executable=True,
        code="fixture_invalid",
        required_modes=frozenset({0o500}),
    )
    provision = {
        "schema_version": 1,
        "wheel_provenance": "approved_tls_origin_with_independent_refetch",
        "binary_wheels_only": True,
        "no_index_install": True,
        "require_hashes_install": True,
        **_hashes(
            "provision",
            composer.PROVISION_APPROVAL_KEYS
            - {
                "schema_version",
                "wheel_provenance",
                "binary_wheels_only",
                "no_index_install",
                "require_hashes_install",
                "provider_commit",
                "provider_tree",
                "sandoq_client_version",
            },
        ),
        "provider_commit": worker_contract["provider_commit"],
        "provider_tree": worker_contract["provider_tree"],
        "provider_source_sha256": worker_contract["provider_source_sha256"],
        "sandoq_client_version": worker_contract["sandoq_client_version"],
        "worker_contract_sha256": _sha(worker_contract_body),
        "worker_runtime_sha256": worker_contract["worker_runtime_sha256"],
        "python_runtime_manifest_sha256": worker_contract[
            "python_runtime_manifest_sha256"
        ],
        "provision_identity_sha256": worker_contract[
            "worker_provision_identity_sha256"
        ],
        "worker_site_manifest_sha256": worker_contract[
            "worker_site_manifest_sha256"
        ],
        "sealed_launcher_sha256": _sha(worker_body),
    }
    artifacts = _hashes("runtime-artifact", composer.RUNTIME_ARTIFACT_KEYS)
    artifacts.update(
        {
            "composer_sha256": composer._source_sha256(Path(composer.__file__)),
            "generator_sha256": composer._source_sha256(Path(plan_generator.__file__)),
            "catalog_materializer_sha256": composer.materializer_controller_code_sha256(),
            "catalog_consumer_sha256": composer.catalog_consumer_code_sha256(),
            "requirements_extractor_sha256": composer.offline_requirements_extractor_sha256(),
            "host_harness_sha256": composer._source_sha256(harness),
            "provider_profile_sha256": composer._source_sha256(profile),
            "sealed_launcher_path_identity_sha256": worker_path_identity,
        }
    )
    catalog_policy = {
        "worker_environment_names": environment_names,
        "worker_environment_sha256": _sha("worker environment"),
        "worker_runtime_invariants": runtime_invariants,
        "worker_recovery_scope_sha256": _sha("recovery scope"),
        "cleanup_receipt_verifier_sha256": worker_contract[
            "cleanup_receipt_verifier_sha256"
        ],
        "ecr_rotator_sha256": _sha("rotator"),
        "inventory_probe_approval_sha256": _sha("probe approval"),
        "source_policy_sha256": _sha("source policy"),
        "source_policy_approval_sha256": _sha("source policy approval"),
        "approved_binary_artifacts": [_sha("binary")],
        "approved_source_attestations": [_sha("source")],
        "approved_toolchains": [_sha("toolchain")],
        "timeouts_seconds": {"recover": 600, "probe": 600, "build": 3600, "validate": 600},
        "concurrency": {
            "probe": composer.MAX_SHARED_POOL_PROBE_CONCURRENCY,
            "build": composer.MAX_SHARED_POOL_BUILD_CONCURRENCY,
            "validate": composer.MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
        },
    }
    runtime = {
        "schema_version": 1,
        "kind": composer.RUNTIME_KIND,
        "state": "approved",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "model": composer.MODEL,
        "repair_binding_sha256": _sha(binding_body),
        "expected_catalog_policy_sha256": "0" * 64,
        "code": code,
        "provider": {
            "commit": worker_contract["provider_commit"],
            "tree": worker_contract["provider_tree"],
            "source_sha256": worker_contract["provider_source_sha256"],
            "client_version": worker_contract["sandoq_client_version"],
        },
        "runtime_artifacts": artifacts,
        "provision_approval_sha256": _sha(canonical_json(provision)),
        "provision_approval": provision,
        "catalog_policy": catalog_policy,
        "network_policy": {
            "state": "explicitly-authorized",
            "provider_commit": worker_contract["provider_commit"],
            "environment": environment,
            "declared_task_network": "no-network",
            "effective_task_network": "public",
            "network_isolation_verified": False,
            "network_access_explicitly_allowed": True,
            "authorization_sha256": _sha("network authorization"),
            "production_task_inputs_accessed": False,
        },
        "serving": {
            "deployment_id": DEPLOYMENT_NAMESPACE,
            "worker_count": 24,
            "healthy_workers": 24,
            "identity_matched_workers": 24,
            "spec_sha256": _sha("spec"),
            "endpoint_bundle_sha256": _sha("bundle"),
            "worker_manifest_sha256": _sha("manifest"),
            "routing_policy": "consistent_hash",
            "request_id_header": "x-session-id",
        },
        "execution": {
            "sandbox_provider": "sandoq",
            "cluster_identifier": "synthetic_cluster",
            "provider_profile_relative_path": profile_relative,
            "environment": environment,
            "transport_mode": "loopback",
            "base_url": composer.SANDOQ_BASE_URL,
            "token_file_path": token_file,
            "ecr_token_file_path": ecr_token_file,
            "ecr_token_metadata_path": ecr_metadata,
            "provider_context": {
                "transport_mode": "loopback",
                "effective_task_network": "public",
                "startup_timeout_seconds": 3600,
                "lease_duration": "1h",
                "session_reuse": 1,
                "pool_max_reuse_count": 1,
                "image_cache_max_entries": 0,
                "podman_fuse_overlayfs": 1,
                "fuse_overlayfs_path": "/usr/bin/fuse-overlayfs",
                "libfuse3_path": "/lib/x86_64-linux-gnu/libfuse3.so.3",
                "pull_timeout": "3600s",
                "pull_poll_max_errors": 20,
                "proxy_required": True,
                "proxy_bind_host": "127.0.0.1",
                "proxy_target_port": 443,
                "proxy_target_suffix": ".metafb.cloud",
                "proxy_environment_names": ["HTTPS_PROXY", "https_proxy"],
                "cleared_proxy_environment_names": list(
                    composer.PROXY_ENVIRONMENT_NAMES
                ),
                "vf_sandbox_provider_removed": True,
                "starts_before_provider": True,
                "lives_through_final_cleanup": True,
            },
            "task_network": "public",
            "host_tunnel": "none",
            "host_harness": True,
            "rollout_concurrency": 64,
            "provider_pool_capacity": 64,
            "lease_create_cap": 4,
            "http_max_connections": 32,
            "http_max_keepalive_connections": 32,
            "max_turns": 200,
            "client_timeout_seconds": 7200,
            "connect_timeout_seconds": 30,
            "runtime_session_timeout_seconds": 43200,
            "max_sequence_tokens": 262144,
            "sampling_max_tokens": 32768,
            "phase_timeouts_seconds": plan_generator.EXPECTED_PHASE_TIMEOUTS,
            "capture_model_io": True,
            "preserve_thinking": True,
            "reasoning_effort": "max",
            "cleanup_must_succeed": True,
            "fresh_output_required": True,
            "resume_allowed": False,
        },
        "ramps": [
            {
                "stage_count": count,
                "state": "passed",
                "measured": True,
                "certificate_sha256": _sha(f"ramp {count}"),
            }
            for count in (2, 8, 24, 64)
        ],
        "trust_boundary": {
            "x86_64_required": True,
            "exclusive_job_required": True,
            "exclusive_catalog_epoch_required": True,
            "credential_values_recorded": False,
            "production_task_inputs_accessed": False,
        },
    }
    expected_policy = _policy_value(runtime, binding, worker_contract, _sha(worker_body))
    runtime["expected_catalog_policy_sha256"] = _sha(_canonical_json(expected_policy))
    runtime_body = _canonical_json(runtime)
    runtime_path = _private(private_root / "runtime-approval.json", runtime_body)
    policy_path = private_root / "catalog-policy.json"
    common = {
        "project_root": project,
        "dataset_root": dataset,
        "private_output_root": private_root,
        "runtime_approval": runtime_path,
        "runtime_approval_sha256": _sha(runtime_body),
        "repair_binding": binding_path,
        "repair_binding_sha256": _sha(binding_body),
    }
    policy_args = {
        **common,
        "worker_contract": worker_contract_path,
        "worker_contract_sha256": _sha(worker_contract_body),
        "worker_executable": worker,
        "output": policy_path,
    }
    return {
        "common": common,
        "policy_args": policy_args,
        "private_root": private_root,
        "project": project,
        "dataset": dataset,
        "runtime": runtime,
        "runtime_path": runtime_path,
        "binding": binding,
        "binding_path": binding_path,
        "source_config": source_config,
        "policy_path": policy_path,
        "worker_contract": worker_contract,
    }


def _prepare_launch(synthetic: dict[str, object]) -> dict[str, object]:
    private_root = synthetic["private_root"]
    assert isinstance(private_root, Path)
    policy_args = synthetic["policy_args"]
    assert isinstance(policy_args, dict)
    assert composer.compose_policy(**policy_args) == {
        "repair": 1233,
        "sandoq": 1233,
        "vmvm": 0,
    }
    runtime = synthetic["runtime"]
    binding = synthetic["binding"]
    project = synthetic["project"]
    assert isinstance(runtime, dict)
    assert isinstance(binding, dict)
    assert isinstance(project, Path)
    policy_path = synthetic["policy_path"]
    assert isinstance(policy_path, Path)
    policy = json.loads(policy_path.read_bytes())
    plan_body = b"opaque synthetic plan\n"
    plan = _private(private_root / "catalog-plan.json", plan_body)
    identity = CatalogIdentity(
        dataset_revision=str(binding["dataset_revision"]),
        task_selection_sha256=str(binding["task_file_sha256"]),
        expected_task_count=1233,
        binding_plan_sha256=_sha("binding plan"),
        catalog_consumer_code_sha256=str(
            runtime["runtime_artifacts"]["catalog_consumer_sha256"]
        ),
        image_manifest_sha256=str(binding["image_manifest_sha256"]),
        requirements_extractor_sha256=str(
            runtime["runtime_artifacts"]["requirements_extractor_sha256"]
        ),
        inventory_probe_code_sha256=str(
            policy["catalog_policy"]["inventory_probe_code_sha256"]
        ),
        inventory_probe_environment_sha256=str(
            policy["catalog_policy"]["inventory_probe_environment_sha256"]
        ),
        inventory_probe_approval_sha256=str(
            policy["catalog_policy"]["inventory_probe_approval_sha256"]
        ),
        source_policy_sha256=str(policy["catalog_policy"]["source_policy_sha256"]),
        source_policy_approval_sha256=str(
            policy["catalog_policy"]["source_policy_approval_sha256"]
        ),
        approved_binary_artifacts_sha256=plan_generator._allowlist_sha256(
            "binary-artifacts", tuple(policy["catalog_policy"]["approved_binary_artifacts"])
        ),
        approved_source_attestations_sha256=plan_generator._allowlist_sha256(
            "source-attestations",
            tuple(policy["catalog_policy"]["approved_source_attestations"]),
        ),
        approved_toolchains_sha256=plan_generator._allowlist_sha256(
            "toolchains", tuple(policy["catalog_policy"]["approved_toolchains"])
        ),
    )
    identity_path = _private(
        private_root / "catalog-identity.json", canonical_json(identity.record())
    )
    plan_receipt_value = {
        "schema_version": plan_generator.SCHEMA_VERSION,
        "kind": plan_generator.KIND,
        "state": "sealed",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "counts": {
            "tasks": 1233,
            "sandoq": 1233,
            "vmvm": 0,
            "images": 1233,
            "probe_groups": 1233,
            "requirement_sets": 9,
            "shared_agent": 1200,
            "separate_verifier": 33,
        },
        "bindings": {
            "plan_sha256": _sha(plan_body),
            "identity_sha256": identity.sha256,
            "policy_sha256": runtime["expected_catalog_policy_sha256"],
            "generator_sha256": runtime["runtime_artifacts"]["generator_sha256"],
            "provider_materialization_receipt_sha256": binding[
                "provider_materialization_receipt_sha256"
            ],
            "sandoq_config_sha256": binding["source_config_sha256"],
            "worker_contract_sha256": runtime["provision_approval"][
                "worker_contract_sha256"
            ],
        },
        "private_set_commitments": {
            "assignments": {"unique_count": 1233, "set_sha256": _sha("assignments")},
            "probe_groups": {"unique_count": 1233, "set_sha256": _sha("probes")},
            "requirement_sets": {"unique_count": 9, "set_sha256": _sha("requirements")},
        },
        "runtime_contract": {
            "provider": "sandoq",
            "environment": runtime["execution"]["environment"],
            "task_network": "none",
            "host_harness": True,
            "rollout_retries": 0,
            "verifier_runtime_retries": 0,
            "catalog_epoch_exclusive": True,
            "probe_concurrency": composer.MAX_SHARED_POOL_PROBE_CONCURRENCY,
            "build_concurrency": composer.MAX_SHARED_POOL_BUILD_CONCURRENCY,
            "validate_concurrency": composer.MAX_SHARED_POOL_VALIDATE_CONCURRENCY,
        },
    }
    plan_receipt_body = _canonical_json(plan_receipt_value)
    plan_receipt = _private(private_root / "catalog-plan-receipt.json", plan_receipt_body)
    catalog_root = private_root / "catalog"
    catalog_root.mkdir(mode=0o700)
    catalog_body = canonical_json({"opaque": "catalog"})
    _private(catalog_root / "catalog.json", catalog_body, 0o400)
    launch_value = {
        "schema_version": 2,
        "catalog_file": "catalog.json",
        "catalog_sha256": _sha(catalog_body),
        "identity_sha256": identity.sha256,
        "expected_task_count": 1233,
        "provider_epoch": {"exclusive_socket_lock": True, "exclusive_wal_lock": True},
        "provider_recovery": {
            "durable_provider_wal": True,
            "recovery_attempted": True,
            "remaining_sessions": 0,
            "cleanup_receipts_verified": True,
            "recovery_scope_sha256": runtime["catalog_policy"][
                "worker_recovery_scope_sha256"
            ],
            "phase": "final",
            "wal_snapshot_sha256": _sha("zero wal"),
            "recovery_receipt_sha256": _sha("recovery receipt"),
            "receipt_verifier_sha256": runtime["catalog_policy"][
                "cleanup_receipt_verifier_sha256"
            ],
            "anchor_liveness": {
                "active_client_registered": True,
                "heartbeat_checks": 9,
                "stop_received": True,
            },
        },
    }
    catalog_launch_body = canonical_json(launch_value)
    _private(catalog_root / "launch.json", catalog_launch_body, 0o400)
    evaluation_output = private_root / "eval-output"
    eval_config_output = private_root / "eval.toml"
    launch_contract_output = private_root / "launch-contract.json"
    composition_receipt_output = private_root / "composition-receipt.json"
    source_config = synthetic["source_config"]
    assert isinstance(source_config, Path)
    source_body = source_config.read_bytes()
    runtime_object = composer.RuntimeApproval(
        body=(synthetic["runtime_path"]).read_bytes(),
        sha256=str(synthetic["common"]["runtime_approval_sha256"]),
        value=runtime,
    )
    binding_object = composer.RepairBinding(
        body=(synthetic["binding_path"]).read_bytes(),
        sha256=str(synthetic["common"]["repair_binding_sha256"]),
        value=binding,
    )
    # Use the path from the validated source, not a membership-bearing file read.
    _, validated = composer._validate_source_config(
        source_body, source_config, binding_object, runtime_object
    )
    assert validated.task_file is not None
    eval_body = composer._render_eval_config(
        source_body,
        catalog_path=catalog_root / "catalog.json",
        catalog_sha256=_sha(catalog_body),
        project_root=project,
        task_file=validated.task_file,
        task_file_sha256=str(binding["task_file_sha256"]),
        identity=identity,
    )
    output_binding = composer._fresh_output_binding(evaluation_output)
    launch_contract = composer._launch_contract_value(
        runtime=runtime_object,
        binding=binding_object,
        plan_sha256=_sha(plan_body),
        plan_receipt_sha256=_sha(plan_receipt_body),
        catalog_identity_sha256=_sha(canonical_json(identity.record())),
        catalog_launch_sha256=_sha(catalog_launch_body),
        catalog_sha256=_sha(catalog_body),
        project_root=project,
        eval_config=eval_config_output,
        eval_config_sha256=_sha(eval_body),
        catalog_path=catalog_root / "catalog.json",
        output_binding=output_binding,
    )
    authorization = {
        "schema_version": 1,
        "kind": composer.AUTHORIZATION_KIND,
        "state": "approved",
        "runtime_approval_sha256": runtime_object.sha256,
        "repair_binding_sha256": binding_object.sha256,
        "source_config_sha256": binding["source_config_sha256"],
        "plan_sha256": _sha(plan_body),
        "plan_receipt_sha256": _sha(plan_receipt_body),
        "catalog_identity_sha256": _sha(canonical_json(identity.record())),
        "catalog_launch_receipt_sha256": _sha(catalog_launch_body),
        "catalog_sha256": _sha(catalog_body),
        "expected_eval_config_sha256": _sha(eval_body),
        "expected_launch_contract_sha256": _sha(_canonical_json(launch_contract)),
    }
    authorization_body = _canonical_json(authorization)
    authorization_path = _private(
        private_root / "launch-authorization.json", authorization_body
    )
    launch_args = {
        **synthetic["common"],
        "source_config": source_config,
        "catalog_policy": policy_path,
        "plan": plan,
        "plan_sha256": _sha(plan_body),
        "plan_receipt": plan_receipt,
        "plan_receipt_sha256": _sha(plan_receipt_body),
        "catalog_identity": identity_path,
        "catalog_identity_sha256": _sha(canonical_json(identity.record())),
        "catalog_root": catalog_root,
        "catalog_launch_receipt_sha256": _sha(catalog_launch_body),
        "launch_authorization": authorization_path,
        "launch_authorization_sha256": _sha(authorization_body),
        "evaluation_output": evaluation_output,
        "eval_config_output": eval_config_output,
        "launch_contract_output": launch_contract_output,
        "composition_receipt_output": composition_receipt_output,
    }
    return {
        "args": launch_args,
        "runtime": runtime,
        "authorization": authorization,
        "catalog_root": catalog_root,
    }


def test_composes_task_free_policy_and_fresh_launch(synthetic: dict[str, object]) -> None:
    prepared = _prepare_launch(synthetic)
    arguments = prepared["args"]
    assert isinstance(arguments, dict)
    counts = composer.compose_launch(**arguments)
    assert counts == {"repair": 1233, "sandoq": 1233, "vmvm": 0}
    assert not arguments["evaluation_output"].exists()
    contract = json.loads(arguments["launch_contract_output"].read_bytes())
    assert contract["execution"]["rollout_concurrency"] == 64
    assert contract["execution"]["provider_pool_capacity"] >= 64
    assert contract["execution"]["max_sequence_tokens"] == 262144
    assert contract["serving"]["routing_policy"] == "consistent_hash"
    assert contract["serving"]["request_id_header"] == "x-session-id"
    assert contract["environment"]["OCI_RUNNER_ENVIRONMENT"] == "oci-runner"
    assert contract["environment"]["SANDOQ_EFFECTIVE_TASK_NETWORK"] == "public"
    assert "OCI_RUNNER_TASK_NETWORK" not in contract["environment"]
    assert contract["evaluation"]["mode"] == "fresh"
    assert contract["evaluation"]["resume_allowed"] is False
    assert contract["evaluation"]["execution_performed"] is False
    assert [item["stage_count"] for item in contract["ramps"]] == [2, 8, 24, 64]
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in (
            arguments["eval_config_output"],
            arguments["launch_contract_output"],
            arguments["composition_receipt_output"],
        )
    )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("execution", "rollout_concurrency", 63),
        ("execution", "provider_pool_capacity", 63),
        ("execution", "client_timeout_seconds", 7199),
        ("execution", "runtime_session_timeout_seconds", 43199),
        ("execution", "max_sequence_tokens", 131072),
        ("execution", "resume_allowed", True),
        ("serving", "routing_policy", "round_robin"),
        ("serving", "request_id_header", "x-other"),
        ("network_policy", "network_access_explicitly_allowed", False),
        ("network_policy", "provider_commit", "f" * 40),
    ],
)
def test_runtime_approval_rejects_execution_drift(
    synthetic: dict[str, object], section: str, key: str, value: object
) -> None:
    runtime = copy.deepcopy(synthetic["runtime"])
    runtime[section][key] = value
    body = _canonical_json(runtime)
    with pytest.raises(composer.LaunchCompositionError, match="runtime_approval_invalid"):
        composer._load_runtime_approval(
            body,
            _sha(body),
            project_root=synthetic["project"],
        )


def test_runtime_environment_is_parameterized_but_fail_closed(
    synthetic: dict[str, object],
) -> None:
    runtime = copy.deepcopy(synthetic["runtime"])
    runtime["execution"]["environment"] = "different-runtime"
    body = _canonical_json(runtime)
    with pytest.raises(composer.LaunchCompositionError, match="runtime_approval_invalid"):
        composer._load_runtime_approval(body, _sha(body), project_root=synthetic["project"])


def test_runtime_rejects_legacy_firecracker_key(
    synthetic: dict[str, object],
) -> None:
    runtime = copy.deepcopy(synthetic["runtime"])
    runtime["catalog_policy"]["worker_environment_names"].append("FIRECRACKER_KEY")
    runtime["catalog_policy"]["worker_environment_names"].sort()
    body = _canonical_json(runtime)
    with pytest.raises(composer.LaunchCompositionError, match="runtime_approval_invalid"):
        composer._load_runtime_approval(body, _sha(body), project_root=synthetic["project"])


def test_runtime_approval_supports_cluster_specific_auto_transport(
    synthetic: dict[str, object],
) -> None:
    runtime = copy.deepcopy(synthetic["runtime"])
    runtime["execution"]["transport_mode"] = "auto"
    context = runtime["execution"]["provider_context"]
    context.update(
        {
            "transport_mode": "auto",
            "proxy_required": False,
            "proxy_bind_host": "",
            "proxy_target_port": 0,
            "proxy_target_suffix": "",
            "proxy_environment_names": [],
        }
    )
    profile = synthetic["project"] / runtime["execution"]["provider_profile_relative_path"]
    profile.write_bytes(
        _canonical_json(
            {
                "schema_version": 1,
                "cluster_identifier": "synthetic_cluster",
                "transport_mode": "auto",
                "effective_task_network": "public",
                "base_url": composer.SANDOQ_BASE_URL,
                "environment": "oci-runner",
                "provider_token_file": runtime["execution"]["token_file_path"],
            }
        )
    )
    runtime["runtime_artifacts"]["provider_profile_sha256"] = _sha(profile.read_bytes())
    body = _canonical_json(runtime)

    loaded = composer._load_runtime_approval(
        body,
        _sha(body),
        project_root=synthetic["project"],
    )

    assert loaded.value["execution"]["transport_mode"] == "auto"


def test_launch_rejects_nonterminal_catalog_recovery(synthetic: dict[str, object]) -> None:
    prepared = _prepare_launch(synthetic)
    arguments = prepared["args"]
    launch_path = prepared["catalog_root"] / "launch.json"
    launch = json.loads(launch_path.read_bytes())
    launch["provider_recovery"]["remaining_sessions"] = 1
    launch_path.chmod(0o600)
    launch_path.write_bytes(canonical_json(launch))
    launch_path.chmod(0o400)
    arguments["catalog_launch_receipt_sha256"] = _sha(launch_path.read_bytes())
    with pytest.raises(composer.LaunchCompositionError, match="catalog_launch_receipt_invalid"):
        composer.compose_launch(**arguments)


def test_launch_rejects_existing_output_without_reading_task_file(
    synthetic: dict[str, object],
) -> None:
    prepared = _prepare_launch(synthetic)
    arguments = prepared["args"]
    arguments["evaluation_output"].mkdir(mode=0o700)
    with pytest.raises(composer.LaunchCompositionError, match="evaluation_output_not_fresh"):
        composer.compose_launch(**arguments)


def test_cli_failure_is_aggregate_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "do-not-emit-this-token"
    monkeypatch.setattr(
        composer,
        "compose_policy",
        lambda **_arguments: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    arguments = [
        "policy",
        "--project-root=/p",
        "--dataset-root=/d",
        "--private-output-root=/o",
        "--runtime-approval=/o/a",
        f"--runtime-approval-sha256={'a' * 64}",
        "--repair-binding=/o/b",
        f"--repair-binding-sha256={'b' * 64}",
        "--worker-contract=/o/c",
        f"--worker-contract-sha256={'c' * 64}",
        "--worker-executable=/w",
        "--output=/o/p",
    ]
    assert composer.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "composition_invalid",
        "state": "failed",
    }
    assert secret not in captured.err
