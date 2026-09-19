from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import smoke_timeout_recovery as recovery


def _digest(value: dict) -> str:
    return hashlib.sha256(recovery.canonical_json(value)).hexdigest()


def _trace(trace_id: str, slug: str) -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "shell",
                    "description": "synthetic",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    message = {
        "role": "assistant",
        "content": "done",
        "reasoning_content": "reasoning",
    }
    response = {
        "id": "response",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    return {
        "id": trace_id,
        "task": {"slug": slug},
        "is_completed": True,
        "stop_condition": "max_turns",
        "errors": [],
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": "synthetic"},
            },
            {
                "parent": 0,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": message,
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
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
            },
        ],
    }


def _row(trace: dict) -> recovery.TraceRow:
    return recovery.TraceRow(raw=json.dumps(trace, sort_keys=True).encode() + b"\n", trace=trace)


def _artifact(path: Path, raw: bytes) -> recovery.FileArtifact:
    path.write_bytes(raw)
    return recovery.FileArtifact(path.resolve(), hashlib.sha256(raw).hexdigest(), raw)


def test_selector_derives_only_missing_line_and_keeps_identifiers_out_of_attestation(tmp_path: Path) -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    selection = recovery.derive_selection(manifest, [_row(_trace("private-trace", "private-task-beta"))])

    assert selection.retained_index == 1
    assert selection.recovery_index == 0
    assert selection.recovery_entry.raw == b"private-task-alpha\n"
    assert selection.missing_rows == 1
    assert selection.harness_timeout_rows == 0

    source = {
        "identity_sha256": "a" * 64,
        "identity": {
            "deployment": {
                "id": "deployment",
                "spec": {"path": "/spec", "sha256": "b" * 64},
                "readiness_checkpoint": {"path": "/ready", "sha256": "c" * 64},
                "endpoint": {"authority_sha256": "d" * 64},
                "serving_route_generation": {"schema_version": 2},
                "proxy_policy": {"request_timeout": 43_200},
            }
        },
        "results_artifact": recovery.FileArtifact(Path("/results"), "e" * 64),
        "identity_artifact": recovery.FileArtifact(Path("/identity"), "f" * 64),
        "invocations_artifact": recovery.FileArtifact(Path("/invocations"), "1" * 64),
        "receipt_artifact": recovery.FileArtifact(Path("/receipt"), "2" * 64),
    }
    body = recovery._selection_body(
        source=source,
        original_manifest=recovery.FileArtifact(Path("/manifest"), "3" * 64),
        recovery_task=recovery.FileArtifact(Path("/approval"), "4" * 64),
        recovery_run_dir=Path("/fresh/run"),
        selection=selection,
    )
    encoded = json.dumps(body, sort_keys=True)
    assert "private-task-alpha" not in encoded
    assert "private-task-beta" not in encoded
    assert "private-trace" not in encoded


def test_selector_accepts_only_exact_harness_timeout_for_second_row() -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    clean = _trace("trace-clean", "private-task-alpha")
    timed_out = _trace("trace-timeout", "private-task-beta")
    timed_out["stop_condition"] = "harness_timeout"

    selection = recovery.derive_selection(manifest, [_row(clean), _row(timed_out)])

    assert selection.retained_index == 0
    assert selection.recovery_index == 1
    assert selection.harness_timeout_rows == 1
    assert selection.missing_rows == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "two_clean",
        "other_infrastructure_stop",
        "duplicate_task",
        "trace_error",
        "normalized_provider_response",
    ],
)
def test_selector_fails_closed_on_ambiguous_or_ineligible_sources(mutation: str) -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    first = _trace("trace-a", "private-task-alpha")
    second = _trace("trace-b", "private-task-beta")
    if mutation == "other_infrastructure_stop":
        second["stop_condition"] = "cancelled"
    elif mutation == "duplicate_task":
        second["task"]["slug"] = "private-task-alpha"
        second["stop_condition"] = "harness_timeout"
    elif mutation == "trace_error":
        second["errors"] = [{"type": "private-error"}]
        second["stop_condition"] = "harness_timeout"
    elif mutation == "normalized_provider_response":
        second = None
        first["nodes"][1]["model_io"]["response"]["kind"] = "normalized_stream_response"
    rows = [_row(first)] if second is None else [_row(first), _row(second)]

    with pytest.raises(recovery.SmokeRecoveryError):
        recovery.derive_selection(manifest, rows)


def test_composite_is_exactly_disjoint_and_ordered_by_original_manifest(tmp_path: Path) -> None:
    manifest_raw = b"private-task-alpha\nprivate-task-beta\n"
    retained = _trace("trace-b", "private-task-beta")
    selection = recovery.derive_selection(manifest_raw, [_row(retained)])
    recovered = _trace("trace-a", "private-task-alpha")
    original_manifest = _artifact(tmp_path / "original.txt", manifest_raw)
    recovery_task = _artifact(tmp_path / "one.txt", b"private-task-alpha\n")
    recovery_results = _artifact(tmp_path / "recovery.jsonl", _row(recovered).raw)

    combined, summary, recovery_row = recovery._validate_combined_rows(
        original_manifest,
        selection,
        recovery_task,
        recovery_results,
    )

    assert [_trace_row.trace["task"]["slug"] for _trace_row in recovery._strict_jsonl(combined, label="test")] == [
        "private-task-alpha",
        "private-task-beta",
    ]
    assert summary["traces"] == summary["tasks"] == 2
    assert recovery_row.trace["id"] == "trace-a"


def test_composite_rejects_duplicate_trace_or_wrong_recovery_task(tmp_path: Path) -> None:
    manifest_raw = b"private-task-alpha\nprivate-task-beta\n"
    retained = _trace("same-trace", "private-task-alpha")
    selection = recovery.derive_selection(manifest_raw, [_row(retained)])
    original_manifest = _artifact(tmp_path / "original.txt", manifest_raw)
    expected_task = _artifact(tmp_path / "one.txt", b"private-task-beta\n")

    duplicate = _artifact(
        tmp_path / "duplicate.jsonl",
        _row(_trace("same-trace", "private-task-beta")).raw,
    )
    with pytest.raises(recovery.SmokeRecoveryError, match="^composite_disjointness_invalid$"):
        recovery._validate_combined_rows(original_manifest, selection, expected_task, duplicate)

    wrong_task = _artifact(tmp_path / "wrong.txt", b"private-task-alpha\n")
    recovered = _artifact(
        tmp_path / "recovered.jsonl",
        _row(_trace("other-trace", "private-task-beta")).raw,
    )
    with pytest.raises(recovery.SmokeRecoveryError, match="^recovery_cardinality_invalid$"):
        recovery._validate_combined_rows(original_manifest, selection, wrong_task, recovered)


def test_cli_error_output_never_echoes_untrusted_exception(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    secret = "https://private.invalid/private-task?key=secret"

    def fail(*_args, **_kwargs):
        raise recovery.SmokeRecoveryError(secret)

    monkeypatch.setattr(recovery, "create_selection", fail)
    result = recovery.main(
        [
            "select",
            "--source-run-dir",
            "/source",
            "--original-task-file",
            "/manifest",
            "--original-task-file-sha256",
            "a" * 64,
            "--namespace",
            "/namespace",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "smoke_recovery_error:recovery_failed\n"
    assert secret not in captured.err


def test_recovery_launch_requires_unset_resume_and_fresh_exact_run_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = tmp_path / "namespace"
    namespace.mkdir()
    task = namespace / "approved_task.txt"
    task.write_text("private-task-alpha\n")
    digest = hashlib.sha256(task.read_bytes()).hexdigest()
    spec = tmp_path / "spec.yaml"
    readiness = tmp_path / "readiness.json"
    proxy = tmp_path / "proxy.json"
    spec.write_text("spec\n")
    readiness.write_text("{}\n")
    proxy.write_text("{}\n")
    spec_record = {"path": str(spec.resolve()), "sha256": hashlib.sha256(spec.read_bytes()).hexdigest()}
    readiness_record = {
        "path": str(readiness.resolve()),
        "sha256": hashlib.sha256(readiness.read_bytes()).hexdigest(),
    }
    proxy_record = {"path": str(proxy.resolve()), "sha256": hashlib.sha256(proxy.read_bytes()).hexdigest()}
    payload = {
        "selection_sha256": "a" * 64,
        "recovery": {"run_dir": str(namespace / "run")},
        "artifacts": {"recovery_task_file": {"path": str(task.resolve()), "sha256": digest}},
        "deployment": {
            "id": "deployment",
            "spec": spec_record,
            "readiness_checkpoint": readiness_record,
            "endpoint": {"proxy_info": proxy_record},
        },
    }
    monkeypatch.setattr(recovery, "_load_selection", lambda *_args, **_kwargs: (payload, object(), object()))

    result = recovery.validate_recovery_launch(
        namespace / "selection.json",
        namespace / "run",
        task,
        digest,
        deployment_id="deployment",
        deployment_spec=spec,
        deployment_spec_sha256=spec_record["sha256"],
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=readiness_record["sha256"],
        proxy_info=proxy,
        proxy_info_sha256=proxy_record["sha256"],
        environ={},
    )
    assert result["counts"] == {"tasks": 1, "expected_traces": 1}

    with pytest.raises(recovery.SmokeRecoveryError, match="^resume_forbidden$"):
        recovery.validate_recovery_launch(
            namespace / "selection.json",
            namespace / "run",
            task,
            digest,
            deployment_id="deployment",
            deployment_spec=spec,
            deployment_spec_sha256=spec_record["sha256"],
            readiness_checkpoint=readiness,
            readiness_checkpoint_sha256=readiness_record["sha256"],
            proxy_info=proxy,
            proxy_info_sha256=proxy_record["sha256"],
            environ={"RESUME_DIR": ""},
        )
    (namespace / "run").mkdir()
    with pytest.raises(recovery.SmokeRecoveryError, match="^recovery_launch_binding_invalid$"):
        recovery.validate_recovery_launch(
            namespace / "selection.json",
            namespace / "run",
            task,
            digest,
            deployment_id="deployment",
            deployment_spec=spec,
            deployment_spec_sha256=spec_record["sha256"],
            readiness_checkpoint=readiness,
            readiness_checkpoint_sha256=readiness_record["sha256"],
            proxy_info=proxy,
            proxy_info_sha256=proxy_record["sha256"],
            environ={},
        )


def test_normalized_config_allows_only_reviewed_recovery_differences() -> None:
    original = {
        "model": "Kimi-K3",
        "num_tasks": 2,
        "max_concurrent": 2,
        "multiplex": 2,
        "max_turns": 8,
        "client": {"max_connections": 2, "max_keepalive_connections": 2, "timeout": 43_200},
        "taskset": {"task_file": "/two", "task_file_sha256": "a" * 64, "id": "terminal-bench-vmvm"},
        "harness": {"runtime": {"type": "vmvm", "session_timeout": 32_400}},
        "timeout": {"rollout": 28_800, "setup": 3_600},
    }
    one = copy.deepcopy(original)
    one.update({"num_tasks": 1, "max_concurrent": 1, "multiplex": 1})
    one["client"].update({"max_connections": 1, "max_keepalive_connections": 1})
    one["taskset"].update({"task_file": "/one", "task_file_sha256": "b" * 64})
    one["harness"]["runtime"]["session_timeout"] = 43_200
    one["timeout"]["rollout"] = 43_200

    assert recovery._normalized_recovery_config(original) == recovery._normalized_recovery_config(one)
    one["max_turns"] = 9
    assert recovery._normalized_recovery_config(original) != recovery._normalized_recovery_config(one)


def test_recovery_wrapper_is_48h_fresh_only_and_reuses_guarded_launcher() -> None:
    wrapper = (Path(recovery.__file__).parent / "run_kimi_smoke_recovery.sbatch").read_text()

    assert "#SBATCH --time=2-00:00:00" in wrapper
    assert "${RESUME_DIR+x}" in wrapper
    assert '[[ -e "$output_dir" ]]' in wrapper
    assert 'bash "$workflow_dir/run_eval.sbatch"' in wrapper
    assert "tb4_kimi_k3_recovery12h.toml" in wrapper
    assert "tb4_kimi_k3_fresh_smoke12h.toml" in wrapper
    assert "SMOKE_REQUIRE_EXACT_PROVIDER_JSON=1" in wrapper
    assert "sbatch " not in wrapper
    assert "scancel " not in wrapper


def test_schema3_validator_binds_exact_target_and_self_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _artifact(tmp_path / "results.jsonl", _row(_trace("trace-a", "private-task-alpha")).raw)
    selection = _artifact(tmp_path / "selection.json", b"{}\n")
    source_smoke = _artifact(tmp_path / "source-smoke.json", b"{}\n")
    endpoint = {"authority_sha256": "a" * 64}
    generation = {"schema_version": 2, "coordinator": {}, "proxy": {}, "routes": []}
    policy = {"request_timeout": 43_200}
    readiness = {"path": "/readiness", "sha256": "b" * 64}
    body = {
        "schema_version": 3,
        "kind": recovery.COMPOSITE_KIND,
        "state": "passed",
        "ok": True,
        "deployment_id": "deployment",
        "deployment_spec_sha256": "c" * 64,
        "artifacts": {
            "results": results.record,
            "selection_attestation": selection.record,
            "recovery_smoke_checkpoint": source_smoke.record,
        },
    }
    payload = {**body, "smoke_checkpoint_sha256": hashlib.sha256(recovery.canonical_json(body)).hexdigest()}
    checkpoint = tmp_path / "smoke_checkpoint.json"
    checkpoint.write_text(json.dumps(payload, sort_keys=True) + "\n")
    checkpoint.chmod(0o444)
    recovery_identity = {
        "deployment": {
            "id": "deployment",
            "spec": {"sha256": "c" * 64},
            "readiness_checkpoint": readiness,
            "endpoint": endpoint,
            "serving_route_generation": generation,
            "proxy_policy": policy,
        }
    }
    monkeypatch.setattr(
        recovery,
        "_prepare_composite",
        lambda *_args, **_kwargs: (body, source_smoke, recovery_identity, {"tool_contract": {}}),
    )
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    evidence, observed_source, observed_generation = recovery.validate_composite_qualification(
        checkpoint,
        checkpoint_sha,
        deployment_id="deployment",
        deployment_spec_sha256="c" * 64,
        readiness_record=readiness,
        endpoint=endpoint,
        generation=generation,
        proxy_policy=policy,
    )
    assert evidence == {"tool_contract": {}}
    assert observed_source == source_smoke
    assert observed_generation == generation

    with pytest.raises(recovery.SmokeRecoveryError, match="^composite_target_mismatch$"):
        recovery.validate_composite_qualification(
            checkpoint,
            checkpoint_sha,
            deployment_id="other-deployment",
            deployment_spec_sha256="c" * 64,
            readiness_record=readiness,
            endpoint=endpoint,
            generation=generation,
            proxy_policy=policy,
        )
