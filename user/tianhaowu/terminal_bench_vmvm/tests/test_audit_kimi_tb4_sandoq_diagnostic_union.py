import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import audit_kimi_tb4_sandoq_diagnostic_union as diagnostic
import kimi_tb4_provider_split as split
import pytest


def _plan(tmp_path: Path) -> diagnostic.PlanBinding:
    legacy = tuple(f"opaque-standard-{index:02d}" for index in range(31))
    memory_8g = tuple(f"opaque-fallback-8g-{index:02d}" for index in range(17))
    memory_16g = tuple(f"opaque-fallback-16g-{index:02d}" for index in range(4))
    compose = tuple(f"opaque-compose-{index:02d}" for index in range(11))
    gpu = tuple(f"opaque-gpu-{index:02d}" for index in range(3))
    all_members = legacy + memory_8g + memory_16g + compose + gpu
    return diagnostic.PlanBinding(
        standard_plan_sha256="a" * 64,
        fallback_plan_sha256="b" * 64,
        manifest_sha256="c" * 64,
        manifest_value={"source": {}},
        verifier_modes={member: "shared" for member in all_members},
        lanes=(
            diagnostic.LaneBinding(
                "standard_legacy",
                "kimi-direct-tb4-diagnostic",
                tmp_path / "standard",
                "d" * 64,
                "e" * 64,
                legacy,
                24,
                1.0,
                None,
                True,
            ),
            diagnostic.LaneBinding(
                "fallback_memory_8g",
                "kimi-direct-tb4-sandoq-fallback-diagnostic",
                tmp_path / "memory-8g",
                "f" * 64,
                "1" * 64,
                memory_8g,
                6,
                1.0,
                0.75,
                False,
            ),
            diagnostic.LaneBinding(
                "fallback_memory_16g",
                "kimi-direct-tb4-sandoq-fallback-diagnostic",
                tmp_path / "memory-16g",
                "2" * 64,
                "3" * 64,
                memory_16g,
                2,
                1.0,
                0.375,
                False,
            ),
        ),
        compose_excluded=compose,
        gpu_unsupported=gpu,
    )


def _lane_result(count: int, passes: int) -> dict:
    return {
        "state": "audited",
        "task_count": count,
        "passes": passes,
        "failures": count - passes,
        "resource_fidelity": False,
        "certification_eligible": False,
        "trace_rollout_eligible": False,
        "trace_audit": {
            "traces": count,
            "tasks": count,
            "model_io_turns": count,
            "sampled_tokens": count * 2,
            "trace_failures": 0,
        },
    }


def _lane_results() -> dict[str, dict]:
    return {
        "standard_legacy": _lane_result(31, 3),
        "fallback_memory_8g": _lane_result(17, 2),
        "fallback_memory_16g": _lane_result(4, 1),
    }


def _worker_manifest(*, router_port: int, metrics_port: int, worker_seed: str = "worker") -> dict:
    model_sha256 = hashlib.sha256(diagnostic.direct_workers.EXPECTED_MODEL.encode()).hexdigest()
    workers = sorted(
        (
            {
                "backend_sha256": hashlib.sha256(f"{worker_seed}-{index}".encode()).hexdigest(),
                "model_sha256": model_sha256,
            }
            for index in range(diagnostic.direct_workers.EXPECTED_ENDPOINTS)
        ),
        key=lambda worker: worker["backend_sha256"],
    )
    endpoint_bundle_sha256 = hashlib.sha256(
        "".join(f"{worker['backend_sha256']}\n" for worker in workers).encode()
    ).hexdigest()
    router_implementation = Path(diagnostic.direct_workers.__file__).with_name("direct_kimi_router.py")
    return {
        "schema_version": diagnostic.direct_workers.MANIFEST_SCHEMA_VERSION,
        "kind": "direct-kimi-worker-generation",
        "deployment_root": "/private/deployment",
        "model": diagnostic.direct_workers.EXPECTED_MODEL,
        "source_spec_sha256": diagnostic.direct_workers.EXPECTED_SPEC_SHA256,
        "source_proxy_config_sha256": diagnostic.direct_workers.EXPECTED_PROXY_CONFIG_SHA256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "workers": workers,
        "router": {
            "implementation": diagnostic.direct_workers.ROUTER_IMPLEMENTATION,
            "implementation_sha256": hashlib.sha256(router_implementation.read_bytes()).hexdigest(),
            "host": "127.0.0.1",
            "port": router_port,
            "metrics_host": "127.0.0.1",
            "metrics_port": metrics_port,
            "policy": diagnostic.direct_workers.ROUTER_POLICY,
            "request_id_headers": list(diagnostic.direct_workers.ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": diagnostic.direct_workers.ROUTER_REQUEST_TIMEOUT_SECONDS,
            "max_concurrent_requests": diagnostic.direct_workers.ROUTER_PROVIDER_CONCURRENCY,
            "queue_size": diagnostic.direct_workers.ROUTER_QUEUE_SIZE,
            "queue_timeout_seconds": diagnostic.direct_workers.ROUTER_QUEUE_TIMEOUT_SECONDS,
            "retries": diagnostic.direct_workers.ROUTER_RETRIES,
        },
    }


def test_summary_is_exact_full_denominator_and_never_certifying(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    value = diagnostic._summary(
        plan,
        _lane_results(),
        "4" * 64,
        standard_source_revision="a" * 40,
        fallback_source_revision="b" * 40,
    )

    assert value["coverage"] == {
        "executed": 52,
        "synthetic_unsupported_zero": 14,
        "compose_excluded_zero": 11,
        "gpu_unsupported_zero": 3,
        "total": 66,
        "disjoint": True,
        "exhaustive": True,
    }
    assert value["scores"] == {
        "passes": 6,
        "all_task_denominator": 66,
        "all_task_pass_rate": 6 / 66,
        "executed_denominator": 52,
        "executed_pass_rate": 6 / 52,
        "synthetic_passes": 0,
    }
    assert value["classification"] == {
        "diagnostic_only": True,
        "official_result": False,
        "resource_fidelity": False,
        "certification_eligible": False,
        "trace_rollout_eligible": False,
    }
    assert value["trace_audit"]["traces"] == 52
    assert value["trace_audit"]["synthetic_rows_audited"] == 0
    rendered = json.dumps(value, sort_keys=True)
    assert all(member not in rendered for lane in plan.lanes for member in lane.members)
    assert all(member not in rendered for member in (*plan.compose_excluded, *plan.gpu_unsupported))


def test_exact_partition_rejects_overlap_and_missing_members() -> None:
    groups = (
        tuple(f"legacy-{index}" for index in range(31)),
        tuple(f"memory8-{index}" for index in range(17)),
        tuple(f"memory16-{index}" for index in range(4)),
        tuple(f"compose-{index}" for index in range(11)),
        tuple(f"gpu-{index}" for index in range(3)),
    )
    all_tasks = set().union(*map(set, groups))
    diagnostic._assert_exact_partition(*groups, all_tasks)

    overlapping = (groups[0], (*groups[1][:-1], groups[0][0]), *groups[2:])
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_partition_overlap$"):
        diagnostic._assert_exact_partition(*overlapping, all_tasks)

    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_partition_not_exhaustive$"):
        diagnostic._assert_exact_partition(*groups, {*all_tasks, "unexpected-member"})


def test_stable_worker_generation_allows_ports_but_rejects_semantic_mismatch() -> None:
    first = diagnostic.direct_workers.worker_generation_contract(
        _worker_manifest(router_port=19001, metrics_port=19002),
        revalidate_live_source=False,
    )
    second = diagnostic.direct_workers.worker_generation_contract(
        _worker_manifest(router_port=29001, metrics_port=29002),
        revalidate_live_source=False,
    )
    different_workers = diagnostic.direct_workers.worker_generation_contract(
        _worker_manifest(router_port=39001, metrics_port=39002, worker_seed="other"),
        revalidate_live_source=False,
    )
    first_sha256 = split.sha256_bytes(split.canonical_json(first))
    second_sha256 = split.sha256_bytes(split.canonical_json(second))
    different_sha256 = split.sha256_bytes(split.canonical_json(different_workers))
    model_contract = {"model": "Kimi-K3"}

    assert first_sha256 == second_sha256
    diagnostic._validate_lane_compatibility(
        {
            name: {
                "model_contract": model_contract,
                "worker_generation_contract_sha256": first_sha256 if index == 0 else second_sha256,
            }
            for index, name in enumerate(diagnostic.EXPECTED_LANES)
        }
    )
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_lane_contract_mismatch$"):
        diagnostic._validate_lane_compatibility(
            {
                "standard_legacy": {
                    "model_contract": model_contract,
                    "worker_generation_contract_sha256": first_sha256,
                },
                "fallback_memory_8g": {
                    "model_contract": model_contract,
                    "worker_generation_contract_sha256": second_sha256,
                },
                "fallback_memory_16g": {
                    "model_contract": model_contract,
                    "worker_generation_contract_sha256": different_sha256,
                },
            }
        )


def test_source_revision_policy_allows_standard_difference_and_groups_fallback() -> None:
    standard_source = {"prime_rl_commit": "a" * 40, "tree": "1" * 64}
    fallback_source = {"prime_rl_commit": "b" * 40, "tree": "2" * 64}
    sources = {
        "standard_legacy": standard_source,
        "fallback_memory_8g": fallback_source,
        "fallback_memory_16g": dict(fallback_source),
    }
    diagnostic._validate_source_revision_policy(
        sources,
        expected_standard_revision="a" * 40,
        expected_fallback_revision="b" * 40,
    )

    sources["fallback_memory_16g"] = {**fallback_source, "tree": "3" * 64}
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^fallback_source_revision_mismatch$"):
        diagnostic._validate_source_revision_policy(
            sources,
            expected_standard_revision="a" * 40,
            expected_fallback_revision="b" * 40,
        )

    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^standard_source_revision_mismatch$"):
        diagnostic._validate_source_revision_policy(
            {**sources, "fallback_memory_16g": fallback_source},
            expected_standard_revision="c" * 40,
            expected_fallback_revision="b" * 40,
        )

    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^fallback_source_revision_mismatch$"):
        diagnostic._validate_source_revision_policy(
            {**sources, "fallback_memory_16g": fallback_source},
            expected_standard_revision="a" * 40,
            expected_fallback_revision="c" * 40,
        )


def test_source_revision_policy_rejects_equal_revision_and_equal_closure() -> None:
    standard_source = {"prime_rl_commit": "a" * 40, "tree": "1" * 64}
    fallback_source = {"prime_rl_commit": "b" * 40, "tree": "2" * 64}
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_source_revisions_not_distinct$"):
        diagnostic._validate_source_revision_policy(
            {
                "standard_legacy": standard_source,
                "fallback_memory_8g": fallback_source,
                "fallback_memory_16g": dict(fallback_source),
            },
            expected_standard_revision="a" * 40,
            expected_fallback_revision="a" * 40,
        )

    equal_source = {"prime_rl_commit": "a" * 40, "tree": "1" * 64}
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_source_closures_not_distinct$"):
        diagnostic._validate_source_revision_policy(
            {
                "standard_legacy": equal_source,
                "fallback_memory_8g": dict(equal_source),
                "fallback_memory_16g": dict(equal_source),
            },
            expected_standard_revision="a" * 40,
            expected_fallback_revision="b" * 40,
        )


def test_output_rejects_plan_bundle_and_run_directory_overlap(tmp_path: Path) -> None:
    plan_bundle = tmp_path / "plan-bundle"
    run_dir = tmp_path / "run"
    project_root = tmp_path / "source"
    dataset_root = tmp_path / "dataset"
    sandoq_site = tmp_path / "sandoq-site"
    plan_bundle.mkdir()
    run_dir.mkdir()
    project_root.mkdir()
    dataset_root.mkdir()
    sandoq_site.mkdir()

    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_output_evidence_overlap$"):
        diagnostic._validate_output_location(
            plan_bundle / "diagnostic.json",
            (plan_bundle, run_dir),
        )
    nested = run_dir / "reports"
    nested.mkdir()
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_output_evidence_overlap$"):
        diagnostic._validate_output_location(
            nested / "diagnostic.json",
            (plan_bundle, run_dir),
        )
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_output_evidence_overlap$"):
        diagnostic._validate_output_location(
            tmp_path / "diagnostic.json",
            (plan_bundle, run_dir),
        )
    for root in (project_root, dataset_root, sandoq_site):
        sibling = root / "private"
        sibling.mkdir()
        with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_output_evidence_overlap$"):
            diagnostic._validate_output_location(
                sibling / "diagnostic.json",
                (root,),
            )


def test_identity_tree_roots_are_retained_and_revalidated(tmp_path: Path) -> None:
    project_root = tmp_path / "source"
    dataset_root = tmp_path / "dataset"
    sandoq_site = tmp_path / "sandoq-site"
    for root in (project_root, dataset_root, sandoq_site):
        root.mkdir()
    identity = {
        "source": {
            "project_root": str(project_root),
            "sandoq_site": str(sandoq_site),
        },
        "dataset": {"path": str(dataset_root)},
    }

    with diagnostic.RetainedAuditEvidence() as retained:
        diagnostic._retain_identity_tree_roots(identity, retained)
        assert set(retained.evidence_roots()) >= {project_root, dataset_root, sandoq_site}
        retained.revalidate()

        moved = tmp_path / "source-moved"
        project_root.rename(moved)
        project_root.mkdir()
        with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_evidence_root_changed$"):
            retained.revalidate()


def test_build_publishes_private_marker_gated_aggregate_only_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path)
    results = _lane_results()
    for index, name in enumerate(diagnostic.EXPECTED_LANES, start=1):
        results[name]["source_closure_sha256"] = str(index) * 64
    compatibility = {
        "model_contract": {"model": "Kimi-K3"},
        "worker_generation_contract_sha256": "4" * 64,
    }
    standard_source = {"prime_rl_commit": "a" * 40, "source": "standard"}
    fallback_source = {"prime_rl_commit": "b" * 40, "source": "fallback"}
    monkeypatch.setattr(diagnostic, "authenticate_plans", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        diagnostic,
        "audit_lane",
        lambda lane, _plan_value, **_kwargs: (
            results[lane.name],
            compatibility,
            standard_source if lane.name == "standard_legacy" else fallback_source,
        ),
    )
    events: list[str] = []

    class FakeRetainedEvidence:
        artifacts = object()

        def __enter__(self) -> "FakeRetainedEvidence":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def revalidate(self) -> None:
            events.append("revalidate")

        def evidence_roots(self) -> tuple[Path, ...]:
            return ()

    original_publish = split._write_private_once

    def publish(path: Path, value: dict) -> None:
        events.append("publish")
        original_publish(path, value)

    monkeypatch.setattr(diagnostic, "RetainedAuditEvidence", FakeRetainedEvidence)
    monkeypatch.setattr(split, "_write_private_once", publish)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "diagnostic-union.json"

    value = diagnostic.build_diagnostic_union(
        standard_plan_path=tmp_path / "standard-plan.json",
        standard_plan_sha256=plan.standard_plan_sha256,
        fallback_plan_path=tmp_path / "fallback-plan.json",
        fallback_plan_sha256=plan.fallback_plan_sha256,
        standard_source_revision="a" * 40,
        fallback_source_revision="b" * 40,
        output=output,
    )

    marker = output.with_name(f".{output.name}{split.FILE_COMMIT_SUFFIX}")
    assert output.stat().st_mode & 0o777 == 0o600
    assert marker.stat().st_mode & 0o777 == 0o600
    assert output.read_bytes() == split.canonical_json(value)
    assert marker.read_bytes() == split._file_commit_payload(output.name, output.read_bytes())
    assert hashlib.sha256(output.read_bytes()).hexdigest() == split.sha256_bytes(output.read_bytes())
    assert value["plans"]["source_revision_policy"] == {
        "kind": "independently_authenticated_plan_bound_groups",
        "standard_prime_rl_revision": "a" * 40,
        "fallback_prime_rl_revision": "b" * 40,
        "fallback_lanes_same_source_closure": True,
        "standard_and_fallback_revisions_distinct": True,
        "standard_and_fallback_source_closures_distinct": True,
    }
    assert events == ["revalidate", "publish", "revalidate"]


def test_retained_evidence_detects_same_bytes_replacement_after_publication(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    evidence_path = private / "evidence.json"
    evidence_path.write_bytes(b"{}\n")
    evidence_path.chmod(0o600)
    output = private / "diagnostic-union.json"

    with diagnostic.RetainedAuditEvidence() as retained:
        split.read_regular(evidence_path, code="evidence_invalid", private=True, held=retained.artifacts)
        split._write_private_once(output, {"kind": diagnostic.KIND})
        evidence_path.rename(private / "original-evidence.json")
        evidence_path.write_bytes(b"{}\n")
        evidence_path.chmod(0o600)
        with pytest.raises(split.KimiProviderSplitError, match="provider_artifact_changed"):
            retained.revalidate()

    marker = output.with_name(f".{output.name}{split.FILE_COMMIT_SUFFIX}")
    assert output.is_file()
    assert marker.is_file()


def test_retained_run_references_require_exact_identity_paths_and_digests(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True, mode=0o700)
    run_dir.chmod(0o700)
    bodies = {
        run_dir / "config.toml": b"resolved\n",
        inputs_dir / "source_config.toml": b"source\n",
        inputs_dir / "manifest.json": b"manifest\n",
        inputs_dir / "task_file.txt": b"tasks\n",
        inputs_dir / "image_manifest.json": b"images\n",
    }
    for path, body in bodies.items():
        path.write_bytes(body)
        path.chmod(0o600)
    identity = {
        "config": {
            "resolved": {
                "path": str(run_dir / "config.toml"),
                "sha256": split.sha256_bytes(bodies[run_dir / "config.toml"]),
            },
            "source": {
                "path": str(inputs_dir / "source_config.toml"),
                "sha256": split.sha256_bytes(bodies[inputs_dir / "source_config.toml"]),
            },
        },
        "inputs": {
            "manifest": {
                "path": str(inputs_dir / "manifest.json"),
                "sha256": split.sha256_bytes(bodies[inputs_dir / "manifest.json"]),
            },
            "task_file": {
                "path": str(inputs_dir / "task_file.txt"),
                "sha256": split.sha256_bytes(bodies[inputs_dir / "task_file.txt"]),
            },
            "image_manifest": {
                "path": str(inputs_dir / "image_manifest.json"),
                "sha256": split.sha256_bytes(bodies[inputs_dir / "image_manifest.json"]),
            },
        },
    }

    held = split._HeldArtifactSet.create()
    try:
        diagnostic._retain_run_references(identity, run_dir, held)
        held.revalidate()
    finally:
        held.close()

    identity["inputs"]["manifest"]["sha256"] = "0" * 64
    rejected = split._HeldArtifactSet.create()
    try:
        with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_run_reference_invalid$"):
            diagnostic._retain_run_references(identity, run_dir, rejected)
    finally:
        rejected.close()


def test_summary_rejects_nonexact_real_trace_coverage(tmp_path: Path) -> None:
    results = _lane_results()
    results["fallback_memory_16g"]["trace_audit"]["traces"] = 3
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_trace_coverage_invalid$"):
        diagnostic._summary(
            _plan(tmp_path),
            results,
            "4" * 64,
            standard_source_revision="a" * 40,
            fallback_source_revision="b" * 40,
        )


def test_fallback_run_identity_requires_memory_only_multiplier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _plan(tmp_path).lanes[1]
    image_sha256 = "4" * 64
    dataset_sha256 = "5" * 64
    plan = replace(
        _plan(tmp_path),
        manifest_value={
            "source": {
                "image_manifest_sha256": image_sha256,
                "dataset_content_sha256": dataset_sha256,
            }
        },
    )
    source_root = tmp_path / "source"
    source_router = source_root / "user/tianhaowu/terminal_bench_vmvm/direct_kimi_router.py"
    source_router.parent.mkdir(parents=True)
    source_router.write_bytes(b"retained source router\n")
    source = {
        "project_root": str(source_root),
        "sandbox_provider": "sandoq",
        "derived_image_manifest_sha256": image_sha256,
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "1" * 64,
        "verifiers_commit": "2" * 40,
        "verifiers_tree_sha256": "2" * 64,
        "renderers_commit": "3" * 40,
        "renderers_tree_sha256": "3" * 64,
        "sandoq_provider_commit": "4" * 40,
        "sandoq_provider_tree": "4" * 40,
        "sandoq_client_version": "1.0",
        "sandoq_site_sha256": "5" * 64,
        "sandoq_host_harness_sha256": "6" * 64,
    }
    identity = {
        "role": lane.role,
        "source": source,
        "config": {
            "source": {"sha256": lane.config_sha256},
            "resolved": {"sha256": "9" * 64},
        },
        "inputs": {
            "task_file": {
                "path": str(tmp_path / "tasks.txt"),
                "sha256": lane.selector_sha256,
                "count": len(lane.members),
            },
            "image_manifest": {"sha256": image_sha256},
        },
        "dataset": {"content_sha256": dataset_sha256},
        "execution": {
            "cleanup_must_succeed": True,
            "runtime": {"type": "sandoq"},
            "rollout_concurrency": lane.concurrency,
            "multiplex": lane.concurrency,
            "http_max_connections": lane.concurrency,
            "http_max_keepalive_connections": lane.concurrency,
            "sandoq_environment": {
                "environment": "oci-runner",
                "task_network": "public",
                "pool_size": lane.concurrency,
                "pool_min_size": 0,
                "lease_profile": "kimi-tb4-long",
                "lease_duration": "12h",
                "pool_renew_interval": "5m",
            },
        },
        "deployment": {
            "kind": "direct_kimi",
            "worker_manifest": {
                "path": str(tmp_path / "workers.json"),
                "sha256": hashlib.sha256(b"worker").hexdigest(),
            },
            "spec_sha256": "7" * 64,
            "endpoint_bundle_sha256": "8" * 64,
            "router": {},
        },
    }
    config = {
        "num_tasks": len(lane.members),
        "max_concurrent": lane.concurrency,
        "multiplex": lane.concurrency,
        "client": {
            "max_connections": lane.concurrency,
            "max_keepalive_connections": lane.concurrency,
        },
        "taskset": {
            "task_file_sha256": lane.selector_sha256,
            "resource_multiplier": 1.0,
            "memory_resource_multiplier": 0.75,
            "enable_compose": False,
        },
    }

    retained = object()
    direct_retained = object()
    observed_source_router = False

    def read_regular(path: Path, **kwargs: object) -> bytes:
        nonlocal observed_source_router
        if path == source_router:
            assert kwargs["held"] is retained
            observed_source_router = True
            return source_router.read_bytes()
        return split._selector_payload(lane.members)

    monkeypatch.setattr(split, "read_regular", read_regular)
    monkeypatch.setattr(split, "_resolved_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(split, "_model_contract", lambda *_args, **_kwargs: {"model": "Kimi-K3"})
    monkeypatch.setattr(split, "_environment_identity", lambda *_args, **_kwargs: {})
    worker_manifest = {"router": {"implementation_sha256": hashlib.sha256(source_router.read_bytes()).hexdigest()}}

    def load_saved_manifest(*_args: object, **kwargs: object) -> tuple[bytes, dict]:
        assert kwargs == {"revalidate_live_source": True, "held": direct_retained}
        return b"worker", worker_manifest

    monkeypatch.setattr(diagnostic.direct_workers, "load_saved_manifest", load_saved_manifest)
    monkeypatch.setattr(diagnostic.direct_workers, "_validate_deployment_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        diagnostic.direct_workers,
        "worker_generation_contract",
        lambda *_args, **_kwargs: {"stable": True},
    )

    _model, _generation, _source, digests = diagnostic._validate_run_identity(
        identity,
        lane,
        plan,
        retained,
        direct_retained,
    )
    assert observed_source_router is True
    assert set(digests) == {"source_closure_sha256", "resolved_config_sha256", "worker_manifest"}

    config["taskset"]["resource_multiplier"] = 0.75
    with pytest.raises(diagnostic.KimiDiagnosticUnionError, match="^diagnostic_run_config_invalid$"):
        diagnostic._validate_run_identity(identity, lane, plan, retained, direct_retained)


def test_cli_redacts_unexpected_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        diagnostic,
        "build_diagnostic_union",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private-task-id raw-error-body")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_kimi_tb4_sandoq_diagnostic_union.py",
            "--standard-plan",
            str(tmp_path / "standard.json"),
            "--standard-plan-sha256",
            "a" * 64,
            "--fallback-plan",
            str(tmp_path / "fallback.json"),
            "--fallback-plan-sha256",
            "b" * 64,
            "--standard-source-revision",
            "c" * 40,
            "--fallback-source-revision",
            "d" * 40,
            "--output",
            str(tmp_path / "out.json"),
        ],
    )

    with pytest.raises(SystemExit):
        diagnostic.main()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "diagnostic_union_failed" in captured.err
    assert "private-task-id" not in captured.err
    assert "raw-error-body" not in captured.err


def test_module_does_not_mutate_certified_merge() -> None:
    source = Path(diagnostic.__file__).read_text()
    assert "merge_certified_runs(" not in source
    assert 'certification_eligible": True' not in source
    assert 'trace_rollout_eligible": True' not in source
    assert os.path.basename(diagnostic.__file__) == "audit_kimi_tb4_sandoq_diagnostic_union.py"
