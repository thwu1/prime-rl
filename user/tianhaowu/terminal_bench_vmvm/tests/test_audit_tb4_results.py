from __future__ import annotations

import fcntl
import hashlib
import json
import sys
from pathlib import Path

import audit_tb4_results as tb4
import pytest
from audit_tb4_results import (
    EXPECTED_UNSUPPORTED_TASKS,
    TB4AuditError,
    _expected_slugs,
    audit_results,
    certify_tb4_results,
)
from deployment_endpoint import load_deployment_endpoint
from deployment_proxy_policy import load_deployment_proxy_policy
from guard_success_receipt import (
    build_guard_success_receipt,
    write_guard_success_receipt,
)


def _digest(body: dict) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _supported_trace(slug: str, *, solved: float = 0.0) -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": "repair the task"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    response = {
        "id": "response",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "reasoning_content": "reason",
                    "content": "answer",
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    return {
        "id": f"trace-{slug}",
        "task": {"slug": slug, "name": f"terminal-bench/{slug}", "resources": {}},
        "nodes": [
            {
                "parent": None,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "reason",
                },
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _digest(request), "body": request},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _digest(response),
                        "body": response,
                    },
                },
            }
        ],
        "rewards": {"solved": solved},
        "metrics": {},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "errors": [],
    }


def _unsupported_trace(slug: str) -> dict:
    message = (
        f"taskset setup: UnsupportedTaskError: terminal-bench/{slug}: "
        "requests GPU resources, but the current VMVM tenant is CPU-only"
    )
    return {
        "id": f"trace-{slug}",
        "task": {
            "slug": slug,
            "name": f"terminal-bench/{slug}",
            "resources": {"gpu": "1"},
        },
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "is_completed": True,
        "stop_condition": "error",
        "errors": [{"type": "TasksetError", "message": message, "traceback": message}],
    }


def _fixture(tmp_path: Path, *, passes: int = 8) -> tuple[Path, Path, list[dict]]:
    dataset = tmp_path / "tasks"
    dataset.mkdir()
    supported = [f"task-{index:02d}" for index in range(63)]
    slugs = [*supported, *sorted(EXPECTED_UNSUPPORTED_TASKS)]
    for slug in slugs:
        task_dir = dataset / slug
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("")
        (task_dir / "instruction.md").write_text("")
    rows = [_supported_trace(slug, solved=float(index < passes)) for index, slug in enumerate(supported)]
    rows.extend(_unsupported_trace(slug) for slug in sorted(EXPECTED_UNSUPPORTED_TASKS))
    results = tmp_path / "results.jsonl"
    results.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    return dataset, results, rows


def _certificate_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "tb4",
    expected_rollout_concurrency: int = 4,
) -> tuple[Path, Path, dict, dict[str, Path]]:
    dataset, results, _ = _fixture(tmp_path, passes=8)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    config = tmp_path / "config.toml"
    manifest = inputs / "manifest.json"
    task_file = inputs / "task_file.txt"
    provenance = tmp_path / "provenance.txt"
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    readiness = tmp_path / "readiness.json"
    smoke = tmp_path / "smoke.json"
    identity_path = tmp_path / "eval_run_identity.json"
    certificate = tmp_path / "checkpoint.json"
    (tmp_path / ".writer.lock").touch()
    config.write_text('model = "Kimi-K3"\n', encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    task_file.write_text("\n".join(sorted(path.name for path in dataset.iterdir())) + "\n")
    spec.write_text(
        "spec:\n"
        "  proxy:\n"
        "    config:\n"
        "      request_timeout: 7200\n"
        "      num_retries: 0\n",
        encoding="utf-8",
    )
    (deployment_dir / "proxy_litellm_config.yaml").write_text(
        "litellm_settings:\n"
        "  request_timeout: 7200\n"
        "  num_retries: 0\n",
        encoding="utf-8",
    )
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
        + "\n",
        encoding="utf-8",
    )
    endpoint = load_deployment_endpoint(
        proxy_info,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=_file_digest(proxy_info),
    ).binding
    expected_routes = tb4.EXPECTED_ROUTES_BY_ROLLOUT_CONCURRENCY[
        expected_rollout_concurrency
    ]
    backends = [
        f"backend-sha256:{hashlib.sha256(f'http://worker-{index}:8000/v1'.encode()).hexdigest()}"
        for index in range(expected_routes)
    ]
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
                "slurm_job_id": str(12345 + index),
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": backend,
            }
            for index, backend in enumerate(backends)
        ],
    }
    proxy_policy = load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=_file_digest(spec),
    )
    readiness_payload = {
        "schema_version": 1,
        "state": "passed",
        "deployment": deployment_id,
        "observed_spec_sha256": _file_digest(spec),
        "endpoint": endpoint,
        "proxy_policy": proxy_policy,
        "serving_route_generation": serving_route_generation,
        "expected_routes": expected_routes,
        "last_status": {
            "schema_version": 4,
            "deployment_id": deployment_id,
            "phase": "serving",
            "desired": expected_routes,
            "ready": expected_routes,
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
                "expected_routes": expected_routes,
                "discovered_routes": expected_routes,
                "backends": sorted(backends),
            },
        },
    }
    readiness.write_text(json.dumps(readiness_payload), encoding="utf-8")
    smoke_payload = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "deployment": {"id": deployment_id, "spec_sha256": _file_digest(spec)},
        "endpoint": endpoint,
        "serving_route_generation": serving_route_generation,
        "proxy_policy": proxy_policy,
        "audit_policy": {
            "expected_traces": 2,
            "rollouts_per_task": 1,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": tb4.EXPECTED_MODEL_IO_CONTRACT,
            "require_token_data": False,
            "require_logprobs": False,
            "max_sequence_tokens": 262144,
        },
        "counts": {
            "traces": 2,
            "tasks": 2,
            "sampled_tokens": 10,
            "model_io_turns": 2,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "artifacts": {
            "readiness_checkpoint": {
                "path": str(readiness),
                "sha256": _file_digest(readiness),
            },
            "proxy_info": endpoint["proxy_info"],
        },
    }
    if expected_rollout_concurrency == 24:
        smoke_payload["audit_policy"]["expected_traces"] = 24
        smoke_payload["counts"].update(
            {
                "traces": 24,
                "tasks": 24,
                "sampled_tokens": 24,
                "model_io_turns": 24,
            }
        )
        smoke_payload["qualified_execution"] = {
            "rollout_concurrency": 24,
            "multiplex": 24,
            "http_max_connections": 24,
            "http_max_keepalive_connections": 24,
            "lease_start_concurrency": 2,
        }
        smoke_payload["observed_concurrency"] = {
            "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
            "lease_start_signal": "vacli_lease_start_semaphore_holders",
            "peak_active_rollouts_lower_bound": 24,
            "peak_concurrent_lease_startups": 2,
            "required_peak_active_rollouts_lower_bound": 24,
            "required_peak_concurrent_lease_startups": 2,
        }
    smoke_payload["smoke_checkpoint_sha256"] = _digest(smoke_payload)
    smoke.write_text(json.dumps(smoke_payload), encoding="utf-8")

    source = {
        "project_root": str(tmp_path),
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "2" * 64,
        "verifiers_commit": "3" * 40,
        "verifiers_tree_sha256": "4" * 64,
        "renderers_commit": "5" * 40,
        "renderers_tree_sha256": "6" * 64,
        "vmvm_tb_v2_sha256": "7" * 64,
    }
    identity = {
        "schema_version": 1,
        "role": role,
        "source": source,
        "config": {
            "source": {"path": str(config), "sha256": _file_digest(config)},
            "resolved": {"path": str(config), "sha256": _file_digest(config)},
        },
        "inputs": {
            "manifest": {"path": str(manifest), "sha256": _file_digest(manifest)},
            "task_file": {
                "path": str(task_file),
                "sha256": _file_digest(task_file),
                "count": 66,
            },
            "image_manifest": None,
        },
        "dataset": {
            "kind": "archive",
            "path": str(dataset),
            "revision": None,
            "archive": {"path": str(spec), "sha256": _file_digest(spec)},
            "content_sha256": "8" * 64,
        },
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": serving_route_generation,
            "proxy_policy": proxy_policy,
            "spec": {"path": str(spec), "sha256": _file_digest(spec)},
            "readiness_checkpoint": {
                "path": str(readiness),
                "sha256": _file_digest(readiness),
            },
            "smoke_checkpoint": {"path": str(smoke), "sha256": _file_digest(smoke)},
        },
        "contract": {
            "model": "Kimi-K3",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "max",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262144,
                "max_output_tokens": 262144,
                "max_total_tokens": 262144,
            },
            "capture_model_io": True,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "return_token_ids",
                "top_logprobs",
            ],
            "retain_traces": False,
            "sampling_max_tokens": 32768,
        },
        "execution": {
            "rollout_concurrency": expected_rollout_concurrency,
            "multiplex": expected_rollout_concurrency,
            "http_max_connections": expected_rollout_concurrency,
            "http_max_keepalive_connections": expected_rollout_concurrency,
            "vmvm_environment": {"lease_start_concurrency": 2},
        },
    }
    identity_sha256 = _digest(identity)
    envelope = {
        "schema_version": 1,
        "eval_run_identity_sha256": identity_sha256,
        "identity": identity,
    }
    identity_path.write_text(json.dumps(envelope), encoding="utf-8")
    provenance_records = {
        "prime_rl": source["prime_rl_commit"],
        "prime_rl_tree": source["prime_rl_tree_sha256"],
        "verifiers": source["verifiers_commit"],
        "verifiers_tree": source["verifiers_tree_sha256"],
        "renderers": source["renderers_commit"],
        "renderers_tree": source["renderers_tree_sha256"],
        "vmvm_tb_v2": source["vmvm_tb_v2_sha256"],
        "deployment_id": deployment_id,
        "deployment_endpoint_authority_sha256": endpoint["authority_sha256"],
        "deployment_proxy_info_sha256": endpoint["proxy_info"]["sha256"],
        "eval_run_role": role,
        "eval_run_identity_sha256": identity_sha256,
        "host": "test-host",
        "slurm_job_id": "123",
        "approval_task_file_sha256": _file_digest(task_file),
        "approval_task_count": "66",
    }
    provenance.write_text("".join(f"{key}={value}\n" for key, value in provenance_records.items()))
    invocations = tmp_path / "eval_invocations.jsonl"
    invocations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": role,
                "resume": False,
                "host": "test-host",
                "slurm_job_id": "123",
            }
        )
        + "\n"
    )
    guard_receipt = build_guard_success_receipt(
        eval_run_identity_sha256=identity_sha256,
        eval_run_role=role,
        eval_run_identity=identity_path,
        eval_invocations=invocations,
        results=results,
        deployment_id=deployment_id,
        deployment_spec_sha256=_file_digest(spec),
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=_file_digest(readiness),
        endpoint=endpoint,
        serving_route_generation=serving_route_generation,
        proxy_policy=proxy_policy,
    )
    guard_receipt_path = tmp_path / "route_guard_success.json"
    write_guard_success_receipt(guard_receipt_path, guard_receipt)
    monkeypatch.setattr(tb4, "load_eval_run_identity", lambda _path: envelope)
    return results, certificate, envelope, {
        "config": config,
        "identity": identity_path,
        "manifest": manifest,
        "provenance": provenance,
        "readiness": readiness,
        "smoke": smoke,
        "proxy_info": proxy_info,
        "eval_invocations": invocations,
        "route_guard_success": guard_receipt_path,
    }


def test_accepts_exact_supported_and_gpu_unsupported_partition(tmp_path: Path) -> None:
    dataset, results, _ = _fixture(tmp_path, passes=8)

    summary, failed = audit_results(
        results,
        dataset_dir=dataset,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )

    assert failed is False
    assert summary["ok"] is True
    assert summary["observed_traces"] == 66
    assert summary["supported_tasks"] == 63
    assert summary["supported_passes"] == 8
    assert summary["supported_pass_rate"] == pytest.approx(8 / 63)
    assert summary["all_task_pass_rate"] == pytest.approx(8 / 66)
    assert summary["observed_unsupported_tasks"] == sorted(EXPECTED_UNSUPPORTED_TASKS)
    assert summary["trace_failures"] == 0
    assert summary["global_problems"] == []
    assert summary["failure_examples"] == []


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("stop_condition", "agent_completed", "unsupported_trace_stop_condition_invalid"),
        ("nodes", [{}], "unsupported_trace_nodes_not_empty"),
        ("rewards", {"solved": 0.0}, "unsupported_trace_rewards_not_empty"),
    ],
)
def test_rejects_malformed_expected_unsupported_rows(
    tmp_path: Path,
    field: str,
    value: object,
    problem: str,
) -> None:
    dataset, results, rows = _fixture(tmp_path)
    row = next(item for item in rows if item["task"]["slug"] == "fp8-rmsnorm-gemm")
    row[field] = value
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "fp8-rmsnorm-gemm")
    assert problem in failure["problems"]


def test_rejects_wrong_unsupported_error_message(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    row = next(item for item in rows if item["task"]["slug"] == "jax-speedrun-gpu")
    row["errors"][0]["message"] = "provider timeout"
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "jax-speedrun-gpu")
    assert "unsupported_trace_error_message_invalid" in failure["problems"]


def test_rejects_missing_duplicate_and_unexpected_tasks(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[-1] = _supported_trace("unexpected")
    rows[1]["task"]["slug"] = rows[0]["task"]["slug"]
    rows[1]["task"]["name"] = rows[0]["task"]["name"]
    rows[1]["id"] = rows[0]["id"]
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    assert "duplicate_trace_ids" in summary["global_problems"]
    assert any(problem.startswith("missing_tasks=") for problem in summary["global_problems"])
    assert any(problem.startswith("unexpected_tasks=") for problem in summary["global_problems"])
    assert any(problem.startswith("wrong_rollout_multiplicity=") for problem in summary["global_problems"])


def test_rejects_supported_errors_and_semantic_corruption(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["errors"] = [{"type": "ProviderError", "message": "500"}]
    rows[1]["nodes"][0]["message"]["reasoning_content"] = "@ " * 64
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    by_task = {item["task"]: item["problems"] for item in summary["failure_examples"]}
    assert "trace_has_errors" in by_task["task-00"]
    assert "node_0_repeated_at_in_reasoning" in by_task["task-01"]


def test_requires_model_io_on_every_supported_trace(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["nodes"][0].pop("model_io")
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "task-00")
    assert "node_0_model_io_missing" in failure["problems"]
    assert summary["supported_trace_failures"] == 1


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("is_completed", False, "supported_trace_not_completed"),
        ("stop_condition", None, "supported_trace_stop_condition_invalid"),
        ("stop_condition", "", "supported_trace_stop_condition_invalid"),
        ("stop_condition", "error", "supported_trace_stop_condition_invalid"),
    ],
)
def test_requires_supported_rows_to_be_completed_with_a_nonerror_stop(
    tmp_path: Path,
    field: str,
    value: object,
    problem: str,
) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0][field] = value
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    failure = next(item for item in summary["failure_examples"] if item["task"] == "task-00")
    assert problem in failure["problems"]


def test_score_bounds_are_explicit_and_fail_closed(tmp_path: Path) -> None:
    dataset, results, _ = _fixture(tmp_path, passes=2)

    summary, failed = audit_results(
        results,
        dataset_dir=dataset,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )

    assert failed is True
    assert summary["supported_passes"] == 2
    assert summary["supported_pass_rate"] == pytest.approx(2 / 63)
    assert summary["global_problems"] == [f"supported_pass_rate={2 / 63:.12g} below_min=0.04"]

    _, failed = audit_results(
        results,
        dataset_dir=dataset,
        max_supported_pass_rate=0.03,
    )
    assert failed is True


def test_task_file_must_name_exactly_the_dataset_tasks(tmp_path: Path) -> None:
    dataset, _, _ = _fixture(tmp_path)
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("\n".join(sorted(path.name for path in dataset.iterdir())) + "\n")

    assert _expected_slugs(dataset, task_file) == {path.name for path in dataset.iterdir()}

    task_file.write_text("task-00\ntask-00\n")
    with pytest.raises(TB4AuditError, match="duplicate task slugs"):
        _expected_slugs(dataset, task_file)


def test_score_must_be_a_single_binary_solved_reward(tmp_path: Path) -> None:
    dataset, results, rows = _fixture(tmp_path)
    rows[0]["rewards"] = {"solved": 0.5}
    rows[1]["rewards"] = {"solved": 0.0, "extra": 1.0}
    results.write_text("".join(f"{json.dumps(item)}\n" for item in rows))

    summary, failed = audit_results(results, dataset_dir=dataset)

    assert failed is True
    by_task = {item["task"]: item["problems"] for item in summary["failure_examples"]}
    assert "rewards_solved_not_binary" in by_task["task-00"]
    assert "rewards_solved_missing_or_extra" in by_task["task-01"]
    assert "scored_supported_tasks=61 expected=63" in summary["global_problems"]


def test_certificate_is_aggregate_only_self_hashed_and_write_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, envelope, paths = _certificate_fixture(tmp_path, monkeypatch)
    shared_smoke = json.loads(paths["smoke"].read_text())
    assert "qualified_execution" not in shared_smoke
    assert "observed_concurrency" not in shared_smoke

    certificate = certify_tb4_results(
        results,
        certificate_path=checkpoint,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )

    assert json.loads(checkpoint.read_text()) == certificate
    assert certificate["state"] == "passed"
    assert certificate["ok"] is True
    assert certificate["eval_run_identity_sha256"] == envelope["eval_run_identity_sha256"]
    assert certificate["endpoint"] == envelope["identity"]["deployment"]["endpoint"]
    assert certificate["artifacts"]["proxy_info"] == certificate["endpoint"]["proxy_info"]
    assert certificate["counts"] == {
        "observed_traces": 66,
        "supported_tasks": 63,
        "cpu_unsupported_tasks": 3,
        "supported_passes": 8,
        "trace_failures": 0,
        "supported_trace_failures": 0,
        "cpu_unsupported_trace_failures": 0,
        "global_problems": 0,
    }
    unsigned = {key: value for key, value in certificate.items() if key != "tb4_certificate_sha256"}
    assert certificate["tb4_certificate_sha256"] == _digest(unsigned)
    assert set(certificate["artifacts"]) == {
        "results",
        "eval_run_identity",
        "eval_invocations",
        "route_guard_success",
        "config",
        "inputs_manifest",
        "provenance",
        "readiness_checkpoint",
        "smoke_checkpoint",
        "proxy_info",
    }
    assert certificate["artifacts"]["config"]["sha256"] == _file_digest(paths["config"])
    serialized = json.dumps(certificate, sort_keys=True)
    for forbidden in (
        "failure_examples",
        "expected_unsupported_tasks",
        "observed_unsupported_tasks",
        '"task"',
        '"trace"',
    ):
        assert forbidden not in serialized

    assert (
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )
        == certificate
    )


def test_certificate_accepts_exact_server_smoke_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(
        tmp_path,
        monkeypatch,
        expected_rollout_concurrency=24,
    )

    certificate = certify_tb4_results(
        results,
        certificate_path=checkpoint,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
        expected_rollout_concurrency=24,
        expected_lease_start_concurrency=2,
    )

    assert certificate["audit_policy"]["rollout_concurrency"] == 24
    assert certificate["audit_policy"]["lease_start_concurrency"] == 2
    assert len(certificate["serving_route_generation"]["routes"]) == 24


@pytest.mark.parametrize(
    ("tamper", "error"),
    [
        ("missing_qualified", "smoke_checkpoint_qualified_execution_invalid"),
        ("mismatched_http", "smoke_checkpoint_qualified_execution_invalid"),
        ("missing_observed", "smoke_checkpoint_observed_concurrency_invalid"),
        ("lower_observed_rollouts", "smoke_checkpoint_observed_concurrency_invalid"),
        ("lower_observed_leases", "smoke_checkpoint_observed_concurrency_invalid"),
        ("mismatched_required", "smoke_checkpoint_observed_concurrency_invalid"),
        ("insufficient_traces", "smoke_checkpoint_observed_concurrency_invalid"),
        ("type_confused_execution", "smoke_checkpoint_qualified_execution_invalid"),
        ("type_confused_observation", "smoke_checkpoint_observed_concurrency_invalid"),
    ],
)
def test_server_certificate_rejects_unproven_smoke_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
    error: str,
) -> None:
    results, checkpoint, envelope, paths = _certificate_fixture(
        tmp_path,
        monkeypatch,
        expected_rollout_concurrency=24,
    )
    smoke = json.loads(paths["smoke"].read_text())
    if tamper == "missing_qualified":
        smoke.pop("qualified_execution")
    elif tamper == "mismatched_http":
        smoke["qualified_execution"]["http_max_connections"] = 4
    elif tamper == "missing_observed":
        smoke.pop("observed_concurrency")
    elif tamper == "lower_observed_rollouts":
        smoke["observed_concurrency"]["peak_active_rollouts_lower_bound"] = 23
    elif tamper == "lower_observed_leases":
        smoke["observed_concurrency"]["peak_concurrent_lease_startups"] = 1
    elif tamper == "mismatched_required":
        smoke["observed_concurrency"]["required_peak_active_rollouts_lower_bound"] = 4
    elif tamper == "insufficient_traces":
        smoke["audit_policy"]["expected_traces"] = 23
        smoke["counts"]["traces"] = 23
        smoke["counts"]["tasks"] = 23
    elif tamper == "type_confused_execution":
        smoke["qualified_execution"]["rollout_concurrency"] = 24.0
    else:
        smoke["observed_concurrency"]["peak_active_rollouts_lower_bound"] = 24.0
    body = {key: value for key, value in smoke.items() if key != "smoke_checkpoint_sha256"}
    smoke["smoke_checkpoint_sha256"] = _digest(body)
    paths["smoke"].write_text(json.dumps(smoke))
    envelope["identity"]["deployment"]["smoke_checkpoint"]["sha256"] = _file_digest(
        paths["smoke"]
    )

    with pytest.raises(TB4AuditError, match=f"^{error}$"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
            expected_rollout_concurrency=24,
            expected_lease_start_concurrency=2,
        )


def test_certificate_rejects_non_tb4_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(tmp_path, monkeypatch, role="smoke")

    with pytest.raises(TB4AuditError, match="tb4_eval_identity_required"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outbound_body_denylist", ["logprobs"]),
        (
            "outbound_body_denylist",
            ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs", "logprobs"],
        ),
        ("sampling_max_tokens", 0),
        ("sampling_max_tokens", 262145),
    ],
)
def test_certificate_rejects_weakened_model_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    results, checkpoint, envelope, _ = _certificate_fixture(tmp_path, monkeypatch)
    envelope["identity"]["contract"][field] = value

    with pytest.raises(TB4AuditError, match="eval_run_identity_contract_invalid"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


@pytest.mark.parametrize("tamper", ["self_hash", "policy", "counts"])
def test_certificate_rejects_smoke_integrity_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    results, checkpoint, envelope, paths = _certificate_fixture(tmp_path, monkeypatch)
    smoke = json.loads(paths["smoke"].read_text())
    if tamper == "self_hash":
        smoke["smoke_checkpoint_sha256"] = "0" * 64
    elif tamper == "policy":
        smoke["audit_policy"]["require_model_io"] = False
    else:
        smoke["counts"]["trace_failures"] = 1
    if tamper != "self_hash":
        body = {key: value for key, value in smoke.items() if key != "smoke_checkpoint_sha256"}
        smoke["smoke_checkpoint_sha256"] = _digest(body)
    paths["smoke"].write_text(json.dumps(smoke))
    envelope["identity"]["deployment"]["smoke_checkpoint"]["sha256"] = _file_digest(paths["smoke"])

    with pytest.raises(TB4AuditError, match="smoke_checkpoint"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_checkpoint_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, envelope, paths = _certificate_fixture(tmp_path, monkeypatch)
    paths["smoke"].write_text('{"schema_version":1,"state":"failed"}\n')
    envelope["identity"]["deployment"]["smoke_checkpoint"]["sha256"] = _file_digest(paths["smoke"])

    with pytest.raises(TB4AuditError, match="smoke_checkpoint_not_passed"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_legacy_or_mismatched_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, envelope, _ = _certificate_fixture(tmp_path, monkeypatch)
    envelope["identity"]["deployment"].pop("endpoint")
    with pytest.raises(TB4AuditError, match="eval_run_identity_endpoint_invalid"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )

    mismatch_dir = tmp_path / "mismatch"
    mismatch_dir.mkdir()
    results, checkpoint, envelope, paths = _certificate_fixture(
        mismatch_dir,
        monkeypatch,
    )
    smoke = json.loads(paths["smoke"].read_text())
    smoke["endpoint"]["authority_sha256"] = "0" * 64
    body = {key: value for key, value in smoke.items() if key != "smoke_checkpoint_sha256"}
    smoke["smoke_checkpoint_sha256"] = _digest(body)
    paths["smoke"].write_text(json.dumps(smoke))
    envelope["identity"]["deployment"]["smoke_checkpoint"]["sha256"] = _file_digest(
        paths["smoke"]
    )
    with pytest.raises(TB4AuditError, match="smoke_checkpoint_endpoint_mismatch"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_type_confused_smoke_model_io_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, envelope, paths = _certificate_fixture(tmp_path, monkeypatch)
    smoke = json.loads(paths["smoke"].read_text())
    smoke["audit_policy"]["model_io_contract"]["request_chat_template_kwargs"][
        "enable_thinking"
    ] = 1
    body = {key: value for key, value in smoke.items() if key != "smoke_checkpoint_sha256"}
    smoke["smoke_checkpoint_sha256"] = _digest(body)
    paths["smoke"].write_text(json.dumps(smoke))
    envelope["identity"]["deployment"]["smoke_checkpoint"]["sha256"] = _file_digest(
        paths["smoke"]
    )

    with pytest.raises(TB4AuditError, match="smoke_checkpoint_not_passed"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_bound_artifact_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, paths = _certificate_fixture(tmp_path, monkeypatch)
    paths["config"].write_text('model = "different"\n')

    with pytest.raises(TB4AuditError, match="config_sha256_mismatch"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_existing_different_certificate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(tmp_path, monkeypatch)
    checkpoint.write_text("{}\n")

    with pytest.raises(TB4AuditError, match="tb4_certificate_already_exists_different"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_missing_guard_success_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, paths = _certificate_fixture(tmp_path, monkeypatch)
    paths["route_guard_success"].unlink()

    with pytest.raises(TB4AuditError, match="guard_success_receipt_invalid"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_rejects_results_changed_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(tmp_path, monkeypatch)
    certify_tb4_results(
        results,
        certificate_path=checkpoint,
        min_supported_pass_rate=0.04,
        max_supported_pass_rate=0.22,
    )
    results.write_text(results.read_text() + "\n")

    with pytest.raises(TB4AuditError, match="guard_success_receipt_invalid"):
        certify_tb4_results(
            results,
            certificate_path=checkpoint,
            min_supported_pass_rate=0.04,
            max_supported_pass_rate=0.22,
        )


def test_certificate_holds_writer_lock_for_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(tmp_path, monkeypatch)
    with (tmp_path / ".writer.lock").open("rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TB4AuditError, match="writer_lock_busy"):
            certify_tb4_results(
                results,
                certificate_path=checkpoint,
                min_supported_pass_rate=0.04,
                max_supported_pass_rate=0.22,
            )


def test_certificate_cli_distinguishes_file_and_internal_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results, checkpoint, _, _ = _certificate_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_tb4_results.py",
            str(results),
            "--certificate",
            str(checkpoint),
            "--min-supported-pass-rate",
            "0.04",
            "--max-supported-pass-rate",
            "0.22",
        ],
    )

    tb4.main()

    output = json.loads(capsys.readouterr().out)
    checkpoint_payload = json.loads(checkpoint.read_text())
    assert output["checkpoint_file_sha256"] == _file_digest(checkpoint)
    assert output["tb4_certificate_sha256"] == checkpoint_payload["tb4_certificate_sha256"]
    assert output["checkpoint_file_sha256"] != output["tb4_certificate_sha256"]
