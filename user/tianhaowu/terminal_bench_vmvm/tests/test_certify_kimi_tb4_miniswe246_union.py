from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import certify_kimi_tb4_miniswe246_union as certify
import kimi_sandoq_production as production
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import pytest


def _tool_row(index: int, return_code: int, *, content_encoding: bool = False) -> dict[str, object]:
    message: dict[str, object] = {"role": "tool", "content": "observation"}
    if content_encoding:
        message["content"] = json.dumps({"returncode": return_code})
    else:
        message["extra"] = {"returncode": return_code}
    return {"nodes": [{"message": message}], "id": f"trace-{index}", "rewards": {"solved": 0}}


def test_tool_execution_requires_numeric_evidence_but_allows_exploratory_failure() -> None:
    rows = {
        "opaque-a": _tool_row(1, 0),
        "opaque-b": _tool_row(2, 1, content_encoding=True),
    }

    assert certify._tool_execution(rows) == {
        "tool_observations": 2,
        "successful_tool_exits": 1,
        "nonzero_tool_exits": 1,
        "missing_tool_exits": 0,
        "traces_with_tool_exit_evidence": 2,
    }

    missing = {"opaque": {"nodes": [{"message": {"role": "tool", "content": "no code"}}]}}
    with pytest.raises(certify.UnionCertificationError, match="tool_exit_evidence_invalid"):
        certify._tool_execution(missing)

    ambiguous = {
        "opaque": {
            "nodes": [
                {
                    "message": {
                        "role": "tool",
                        "content": json.dumps({"returncode": 1}),
                        "extra": {"returncode": 0},
                    }
                }
            ]
        }
    }
    with pytest.raises(certify.UnionCertificationError, match="tool_exit_evidence_invalid"):
        certify._tool_execution(ambiguous)


def test_stable_deployment_contract_ignores_only_snapshot_root(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {
        "schema_version": 2,
        "kind": "direct-kimi-worker-generation",
        "deployment_root": "/private/lane-a",
        "model": "Kimi-K3",
        "source_spec_sha256": "1" * 64,
        "source_proxy_config_sha256": "2" * 64,
        "endpoint_bundle_sha256": "3" * 64,
        "workers": [{"backend_sha256": "4" * 64}],
        "router": {"policy": "consistent_hash"},
    }
    monkeypatch.setattr(
        certify.split,
        "_deployment_contract",
        lambda _identity, _held: {
            "worker_generation_sha256": "0" * 64,
            "spec_sha256": "1" * 64,
            "router": {"policy": "consistent_hash", "provider_concurrency": 64},
        },
    )
    monkeypatch.setattr(certify, "load_saved_manifest", lambda *_args, **_kwargs: (b"manifest", {}))
    monkeypatch.setattr(certify, "worker_generation_contract", lambda *_args, **_kwargs: dict(base))
    identity = {"deployment": {"worker_manifest": {"path": "/private/manifest.json"}}}

    first = certify._stable_deployment_contract(identity, object())
    base["deployment_root"] = "/private/lane-b"
    second = certify._stable_deployment_contract(identity, object())

    assert first == second
    base["router"] = {"policy": "round_robin"}
    third = certify._stable_deployment_contract(identity, object())
    assert third["worker_generation_sha256"] != first["worker_generation_sha256"]


def test_union_reproduction_gate_requires_seven_supported_passes() -> None:
    with pytest.raises(certify.UnionCertificationError, match="tb4_score_outside_expected_range"):
        certify._derived_union_fields(
            plan={"source": {"manifest": {"sha256": "a" * 64}}},
            sandoq={},
            vmvm={},
            passes=6,
            results_body=b"",
        )


def test_union_merge_rejects_relative_artifact_paths(tmp_path: Path) -> None:
    with pytest.raises(certify.UnionCertificationError, match="union_path_invalid"):
        certify.merge_certified_lanes(
            launch_plan=Path("relative-plan.json"),
            launch_plan_sha256="0" * 64,
            sandoq_certificate=tmp_path / "missing-sandoq.json",
            sandoq_certificate_sha256="1" * 64,
            vmvm_certificate=tmp_path / "missing-vmvm.json",
            vmvm_certificate_sha256="2" * 64,
            output=tmp_path / "output",
            expected_revision="3" * 40,
        )


def test_identity_contract_binds_run_local_snapshots_by_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    selector_body = b"opaque-a\n"
    config_body = b"""num_tasks = 1
max_concurrent = 4
multiplex = 4
output_dir = "/private/base"
[client]
base_url = "http://127.0.0.1:8000/v1"
max_connections = 4
max_keepalive_connections = 4
[taskset]
task_file = "/private/selector"
task_file_sha256 = "x"
resource_multiplier = 2.0
enable_compose = true
[harness]
runtime = { type = "vmvm" }
"""
    plan_selector = tmp_path / "plan-selector.txt"
    plan_config = tmp_path / "plan-config.toml"
    run_selector = tmp_path / "run-task-file.txt"
    run_config = tmp_path / "run-config.toml"
    for path, body in (
        (plan_selector, selector_body),
        (plan_config, config_body),
        (run_selector, selector_body),
        (run_config, b"resolved\n"),
    ):
        path.write_bytes(body)
        path.chmod(0o600)
    selector_sha256 = hashlib.sha256(selector_body).hexdigest()
    config_sha256 = hashlib.sha256(config_body).hexdigest()
    plan = {
        "plan_sha256": "f" * 64,
        "contracts": {
            "timeouts": {
                "request_seconds": union.REQUEST_TIMEOUT_SECONDS,
                "rollout_seconds": union.ROLLOUT_TIMEOUT_SECONDS,
                "session_seconds": union.SESSION_TIMEOUT_SECONDS,
            }
        },
        "lanes": {
            union.VMVM_ROLE: {
                "concurrency": 4,
                "resource_multiplier": 2.0,
                "selector": {
                    "path": str(plan_selector),
                    "bytes": len(selector_body),
                    "sha256": selector_sha256,
                },
                "config": {
                    "path": str(plan_config),
                    "bytes": len(config_body),
                    "sha256": config_sha256,
                },
            }
        },
    }
    expected_harness = {
        "id": "mini-swe-agent",
        "version": "2.4.6",
        "placement": "sandbox",
        "step_limit": 200,
        "request_timeout_seconds": union.REQUEST_TIMEOUT_SECONDS,
        "request_max_retries": 0,
    }
    source = {
        "sandbox_provider": "vmvm",
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "2" * 64,
        "verifiers_commit": union.VERIFIERS_COMMIT,
        "verifiers_tree_sha256": "3" * 64,
        "renderers_commit": "4" * 40,
        "renderers_tree_sha256": "5" * 64,
    }
    identity = {
        "role": "kimi-direct-tb4",
        "source": source,
        "deployment": {"router": {"policy": "consistent_hash"}},
        "execution": {
            "cleanup_must_succeed": True,
            "rollout_concurrency": 4,
            "multiplex": 4,
            "http_max_connections": 4,
            "http_max_keepalive_connections": 4,
            "runtime": {"type": "vmvm"},
            "vmvm_environment": {},
        },
        "inputs": {"task_file": {"path": str(run_selector), "sha256": selector_sha256, "count": 1}},
        "config": {
            "source": {"path": str(tmp_path / "inputs/source_config.toml"), "sha256": config_sha256},
            "resolved": {
                "path": str(run_config),
                "sha256": hashlib.sha256(run_config.read_bytes()).hexdigest(),
            },
        },
        "contract": {"model": "Kimi-K3", "harness": expected_harness},
    }
    monkeypatch.setattr(
        certify.split,
        "load_eval_run_identity_bytes",
        lambda *_args, **_kwargs: {"identity": identity, "eval_run_identity_sha256": "6" * 64},
    )
    monkeypatch.setattr(certify, "_stable_deployment_contract", lambda *_args: {"stable": True})
    monkeypatch.setattr(certify.split, "_model_contract", lambda _identity: {"model": "Kimi-K3"})
    monkeypatch.setattr(certify.split, "_run_invocation_binding", lambda *_args: ("7" * 64, "123"))
    evidence = SimpleNamespace(
        files={
            "eval_run_identity.json": SimpleNamespace(body=b"identity"),
            "eval_invocations.jsonl": SimpleNamespace(body=b"invocation"),
            "provenance.txt": SimpleNamespace(body=b"provenance"),
        }
    )
    held = split._HeldArtifactSet.create()
    try:
        observed, _contracts, *_rest = certify._identity_contract(
            run_dir=tmp_path,
            plan=plan,
            role=union.VMVM_ROLE,
            members=("opaque-a",),
            run_evidence=evidence,
            held=held,
            expected_revision="1" * 40,
        )
    finally:
        held.close()

    assert observed is identity


def _entries() -> tuple[split.ManifestEntry, ...]:
    values: list[split.ManifestEntry] = []
    for index in range(split.TOTAL_TASKS):
        if index < union.SANDOQ_TASKS:
            cpu, memory, disk, gpu = 2, 4, 10, 0
        elif index < split.LEGACY_SANDOQ_TASKS:
            cpu, memory, disk, gpu = 4, 4, 10, 0
        elif index < split.CPU_TASKS:
            cpu, memory, disk, gpu = 16, 8, 50, 0
        else:
            cpu, memory, disk, gpu = 2, 4, 10, 1
        request = split.ResourceRequest(cpu, memory * split.GIB, disk * split.GIB, gpu)
        values.append(
            split.ManifestEntry(
                task_id=f"opaque-{index:02d}",
                agent_resources=request,
                verifier_resources=request,
                verifier_mode="shared",
                requires_compose=split.LEGACY_SANDOQ_TASKS <= index < split.LEGACY_SANDOQ_TASKS + 11,
            )
        )
    return tuple(values)


def test_merge_emits_aggregate_schema2_certificate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    plan_path = tmp_path / union.LAUNCH_PLAN
    plan_body = b"opaque-plan\n"
    plan_path.write_bytes(plan_body)
    plan_path.chmod(0o600)
    partition_path = tmp_path / union.PARTITION_RECEIPT
    partition_path.write_bytes(b"opaque-partition\n")
    partition_path.chmod(0o600)
    sandoq_path = tmp_path / "sandoq-certificate.json"
    vmvm_path = tmp_path / "vmvm-certificate.json"
    for path, body in ((sandoq_path, b"sandoq\n"), (vmvm_path, b"vmvm\n")):
        path.write_bytes(body)
        path.chmod(0o600)
    entries = _entries()
    partition = union.derive_union_partition(entries)
    manifest_sha256 = "a" * 64
    plan = {
        "contracts": {
            "timeouts": {
                "request_seconds": union.REQUEST_TIMEOUT_SECONDS,
                "rollout_seconds": union.ROLLOUT_TIMEOUT_SECONDS,
                "session_seconds": union.SESSION_TIMEOUT_SECONDS,
            }
        },
        "source": {
            "manifest": {"path": "/private/manifest", "bytes": 1, "sha256": manifest_sha256},
            "partition_receipt": {
                "path": str(partition_path),
                "bytes": partition_path.stat().st_size,
                "sha256": hashlib.sha256(partition_path.read_bytes()).hexdigest(),
            },
        },
    }
    monkeypatch.setattr(certify, "_load_plan", lambda *_args: (plan, plan_body, entries))

    shared = {
        "deployment_contract": {
            "endpoint_bundle_sha256": "b" * 64,
            "spec_sha256": "c" * 64,
            "worker_generation_sha256": "d" * 64,
        }
    }
    lane_rows: dict[str, dict[str, dict[str, object]]] = {}
    for role, members in (
        (union.SANDOQ_ROLE, partition.sandoq_firecracker),
        (union.VMVM_ROLE, partition.vmvm_cpu),
    ):
        rows = {
            member: {
                "id": f"trace-{index}-{role}",
                "task": {"name": f"terminal-bench/{member}"},
                "rewards": {"solved": 1 if index < (3 if role == union.SANDOQ_ROLE else 4) else 0},
                "nodes": [],
            }
            for index, member in enumerate(members)
        }
        lane_rows[role] = rows

    def load_lane(*, path: Path, expected_role: str, **_kwargs: object):
        is_sandoq = expected_role == union.SANDOQ_ROLE
        value = {
            "shared_contract": shared,
            "worker_manifest_sha256": "9" * 64,
            "deployment_contract": {"exact": True},
            "routing_contract": {"profile": "w2"},
            "eval_run_identity_sha256": ("1" if is_sandoq else "2") * 64,
            "sandbox_provider": "sandoq" if is_sandoq else "vmvm",
            "trace_audit": {
                "passes": 3 if is_sandoq else 4,
                "model_io_turns": len(lane_rows[expected_role]),
                "sampled_tokens": len(lane_rows[expected_role]),
            },
            "tool_execution": {
                "tool_observations": len(lane_rows[expected_role]),
                "successful_tool_exits": len(lane_rows[expected_role]),
                "nonzero_tool_exits": 0,
            },
            "cleanup": {"state": "passed"},
            "capacity": None if is_sandoq else {"provider": "vmvm"},
            "artifacts": {
                name: {"sha256": digest}
                for name, digest in (
                    ("smoke_checkpoint", "a" * 64),
                    ("capacity_certificate", "b" * 64),
                    ("capacity_gate_receipt", "c" * 64),
                    ("endpoint_load_gate", "d" * 64),
                )
            },
        }
        return value, path.read_bytes(), lane_rows[expected_role]

    monkeypatch.setattr(certify, "_load_lane_certificate", load_lane)
    output = tmp_path / "union-output"
    summary = certify.merge_certified_lanes(
        launch_plan=plan_path,
        launch_plan_sha256=hashlib.sha256(plan_body).hexdigest(),
        sandoq_certificate=sandoq_path,
        sandoq_certificate_sha256=hashlib.sha256(sandoq_path.read_bytes()).hexdigest(),
        vmvm_certificate=vmvm_path,
        vmvm_certificate_sha256=hashlib.sha256(vmvm_path.read_bytes()).hexdigest(),
        output=output,
        expected_revision="a" * 40,
    )

    certificate = json.loads((output / certify.UNION_CERTIFICATE).read_bytes())
    assert summary["supported_passes"] == 7
    assert certificate["schema_version"] == 2
    assert certificate["counts"] == {
        "observed_traces": 66,
        "supported_tasks": 63,
        "cpu_unsupported_tasks": 3,
        "supported_passes": 7,
        "trace_failures": 0,
        "global_problems": 0,
    }
    assert b"opaque-" not in (output / certify.UNION_CERTIFICATE).read_bytes()
    assert len((output / certify.MERGED_RESULTS).read_bytes().splitlines()) == 66
    certificate_path = (output / certify.UNION_CERTIFICATE).resolve()
    validated, _artifact = production._validate_tb4_certificate(
        certificate_path,
        hashlib.sha256(certificate_path.read_bytes()).hexdigest(),
    )
    assert validated["adapter"] == union.CERTIFIER_ADAPTER

    tampered = dict(certificate)
    tampered["deployment"] = {**certificate["deployment"], "endpoint_bundle_sha256": "f" * 64}
    tampered.pop("tb4_certificate_sha256")
    tampered["tb4_certificate_sha256"] = hashlib.sha256(split.canonical_json(tampered)).hexdigest()
    tampered_path = tmp_path / "tampered-certificate.json"
    tampered_path.write_bytes(split.canonical_json(tampered))
    tampered_path.chmod(0o600)
    with pytest.raises(certify.UnionCertificationError, match="union_certificate_invalid"):
        certify.validate_union_certificate(
            tampered_path,
            hashlib.sha256(tampered_path.read_bytes()).hexdigest(),
        )


def test_cli_redacts_certification_failure(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        certify.main(
            [
                "certify-lane",
                "--role",
                union.SANDOQ_ROLE,
                "--run-dir",
                "/missing",
                "--launch-plan",
                "/missing/plan",
                "--launch-plan-sha256",
                "0" * 64,
                "--expected-revision",
                "1" * 40,
                "--output",
                "/missing/out",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "kimi_tb4_miniswe246_union_certification_failed"
