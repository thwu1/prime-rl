from __future__ import annotations

import copy
import json
import subprocess
from types import SimpleNamespace

import finalize_kimi_tb4_sandoq_small_full as ordinary
import finalize_kimi_tb4_sandoq_small_v4_recovery as v4
import finalize_kimi_tb4_sandoq_small_v6_supersession as v6
import pytest


def _row(name: str) -> dict:
    return {
        "id": "trace-" + name,
        "task": {"name": "terminal-bench/" + name},
        "is_completed": True,
        "stop_condition": "error",
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "info": {},
        "errors": [
            {
                "type": "SandboxError",
                "message": "opaque failure",
                "traceback": "",
            }
        ],
    }


def _post_agent_verifier_sandbox_row(name: str = "separate-verifier") -> dict:
    row = _row(name)
    row["stop_condition"] = "agent_completed"
    row["nodes"] = [{"sampled": True}, {"sampled": True}]
    row["errors"] = [
        {
            "type": "SandboxError",
            "message": (
                f"terminal-bench/{name}: verifier VMVM failed after 3 attempts: "
                "attempt 1: Sandoq provisioning failed after 9 attempts; "
                "attempt 2: Sandoq provisioning failed after 9 attempts; "
                "attempt 3: Sandoq provisioning failed after 9 attempts"
            ),
            "traceback": (
                "Traceback (most recent call last):\n"
                '  File "taskset.py", line 1, in solved\n'
                '  File "taskset.py", line 2, in _score_separate\n'
                "    raise SandboxError\n"
            ),
        }
    ]
    row["info"] = {
        "terminal_bench_artifacts": {
            "bytes": 128,
            "captured": {"main": ["/results/output.txt"]},
            "collect": [],
            "missing": [{"service": "main", "source": "/logs/artifacts"}],
            "sha256": "a" * 64,
        }
    }
    return row


def _proxy_summary(**updates: int) -> dict:
    value = {
        "requests": 3,
        "upstream_attempts": 2,
        "coalesced_requests": 0,
        "replayed_requests": 1,
        "downstream_disconnects": 0,
        "conflicting_requests": 0,
        "inflight": 0,
        "streamed_requests": 3,
        "response_bytes": 123,
        "error_count": 0,
        "unknown_path_requests": 0,
        "statuses": {"200": 2},
        "protocols": {"chat_completions": 3},
        "path_counts": {
            "/muse-code/models": 1,
            "/v1/chat/completions": 3,
            "/v1/responses": 0,
        },
    }
    value.update(updates)
    return value


def _proxy_log(*summaries: dict) -> bytes:
    return b"".join(
        b"12:34:56    INFO "
        + v6.PROXY_SUMMARY_MARKER
        + json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
        for summary in summaries
    )


def test_v6_supersession_binds_exact_execution_and_ordinary_kind() -> None:
    assert v6.KIND == ordinary.KIND
    assert v6.EXECUTION_SOURCE_REVISION == "734fac07d92f75820892dd984b74f76707eb9b63"
    assert v6.EXECUTION_VERIFIERS_COMMIT == "f11bf7cec1ca16ecadf7c88046f6a4a660af2031"
    assert v6.EXECUTION_SLURM_JOB_ID == "1601096"
    assert v6.EXECUTION_PLAN_SHA256 == "f0b9c5df4c99b9d175f990f470a5d8872e846a68fec28c58159aabf0c4c4dab9"
    assert v6.TARGET_PASSES == 7


def test_v6_execution_semantics_manifest_uses_raw_file_sha256() -> None:
    manifest = v6._execution_semantics_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["hash_kind"] == "raw-file-sha256"
    assert manifest["source_revision"] == v6.EXECUTION_SOURCE_REVISION
    assert set(manifest["prime_rl_shared_files"]) == set(v6.PRIME_SHARED_EXECUTION_FILES)
    assert set(manifest["tb4_lane_files"]) == set(v6.TB4_LANE_EXECUTION_FILES)
    assert set(manifest["verifiers"]["files"]) == set(v6.VERIFIERS_EXECUTION_FILES)
    assert manifest["verifiers"]["commit"] == v6.EXECUTION_VERIFIERS_COMMIT
    assert manifest["sandoq_extension"]["path"] == v6.SANDOQ_EXTENSION_PREFIX
    for section in (
        manifest["prime_rl_shared_files"],
        manifest["tb4_lane_files"],
        manifest["sandoq_extension"]["files"],
        manifest["verifiers"]["files"],
    ):
        assert section
        assert all(len(value) == 64 for value in section.values())


def test_v6_supersession_rejects_any_other_plan_hash(tmp_path) -> None:
    held = v6.split._HeldArtifactSet.create()
    try:
        with pytest.raises(v6.V6SupersessionError, match="execution_plan_invalid"):
            v6._verified_plan(tmp_path / "missing.json", "0" * 64, held)
    finally:
        held.close()


def test_v6_supersession_source_rejects_untracked_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        v6.recovery,
        "_repository_binding",
        lambda revision: {"project_root": str(tmp_path), "revision": revision},
    )
    monkeypatch.setattr(
        v6.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="?? untracked.py\n"),
    )
    with pytest.raises(v6.V6SupersessionError, match="supersession_source_invalid"):
        v6._supersession_source_binding("a" * 40)


def test_v6_provider_context_is_exact_and_digest_bound(tmp_path) -> None:
    path = tmp_path / "context.json"
    value = {
        "schema_version": 1,
        "kind": "sandoq-provider-context-snapshot",
        "state": "validated",
        "provider_environment": "oci-runner-firecracker-small",
        "effective_task_network": "public",
        "task_network": "host",
        "network_access": True,
        "allow_dockerhub_fallback": False,
        "provider_profile_sha256": v6.plan_module.PROVIDER_PROFILE_SHA256,
        "provider_token_file_path_sha256": v6.PROVIDER_TOKEN_PATH_SHA256,
        "runtime_smoke_receipt_sha256": None,
        "provider_context_contract_sha256": "a" * 64,
    }
    path.write_bytes(v6.split.canonical_json(value))
    path.chmod(0o600)
    held = v6.split._HeldArtifactSet.create()
    try:
        assert v6._provider_context(path, held)["contract_sha256"] == "a" * 64
    finally:
        held.close()
    value["unexpected"] = True
    path.write_bytes(v6.split.canonical_json(value))
    held = v6.split._HeldArtifactSet.create()
    try:
        with pytest.raises(v6.V6SupersessionError, match="provider_context_invalid"):
            v6._provider_context(path, held)
    finally:
        held.close()


def test_v6_merge_preserves_derived_error_zero_and_adds_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v6.split, "TOTAL_TASKS", 3)
    derived = v4._derived_error_zero(_row("supported"), zero_model=True)
    body = v6._merge_rows(
        [
            SimpleNamespace(task_id="supported"),
            SimpleNamespace(task_id="compose"),
            SimpleNamespace(task_id="gpu"),
        ],
        {"supported": derived},
        ("compose",),
        ("gpu",),
        "a" * 64,
    )
    rows = [json.loads(line) for line in body.splitlines()]
    assert len(rows) == 3
    assert rows[0]["rewards"] == {"solved": 0}
    assert rows[0]["info"]["diagnostic_evaluation_disposition"] == {
        "kind": "execution-error-counted-as-zero",
        "source_row_sha256": v4._sha256(v6.split.canonical_json(_row("supported"))),
        "trainable": False,
        "zero_model": True,
    }
    assert [row["info"].get("provider_outcome") for row in rows[1:]] == ["compose", "gpu"]


def test_v6_audit_retains_score_but_excludes_trace_invalid_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "id": "trace-scored",
        "task": {"name": "terminal-bench/scored"},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "nodes": [{"sampled": True}],
        "rewards": {"solved": 0},
        "metrics": {},
        "info": {"terminal_bench_verifier": {"mode": "separate"}},
        "errors": [],
    }
    monkeypatch.setattr(
        v4.audit_traces,
        "_audit_trace",
        lambda *args, **kwargs: ["node_12_finish_reason_invalid"],
    )
    with pytest.raises(v4.V4RecoveryError, match="provider_trace_audit_failed"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("scored",),
            {"scored": "separate"},
        )
    summary, rows = v4._audit_supported_rows(
        v6.split.canonical_json(row),
        ("scored",),
        {"scored": "separate"},
        allow_nontrainable_scored_rows=True,
    )
    assert summary["passes"] == 0
    assert summary["scored_rows"] == 1
    assert summary["clean_scored_rows"] == 0
    assert summary["trace_invalid_scored_rows"] == 1
    assert summary["trace_invalid_passing_rows"] == 0
    assert summary["trace_invalid_problem_counts"] == {"node_*_finish_reason_invalid": 1}
    disposition = rows["scored"]["info"]["diagnostic_evaluation_disposition"]
    assert disposition["kind"] == "score-retained-trace-excluded"
    assert disposition["trainable"] is False
    assert disposition["source_row_sha256"] == v4._sha256(v6.split.canonical_json(row))
    assert disposition["audit_problem_set_sha256"] == v4._sha256(
        v6.split.canonical_json(["node_12_finish_reason_invalid"])
    )


def test_v7_error_row_audits_all_sampled_model_io_and_accepts_canonical_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("provider-error")
    row["nodes"] = [{"sampled": True}, {"sampled": True}]
    row["errors"] = [{"type": "ProviderError", "message": "opaque failure"}]
    calls: list[dict] = []

    def audit(*_args, **kwargs):
        calls.append(kwargs)
        return ["trace_has_errors"]

    monkeypatch.setattr(v4.audit_traces, "_audit_trace", audit)
    summary, _rows = v4._audit_supported_rows(
        v6.split.canonical_json(row),
        ("provider-error",),
        {"provider-error": "shared"},
        allow_nontrainable_scored_rows=True,
        audit_error_model_io=True,
    )

    assert summary["source_model_io_turns"] == 2
    assert summary["validated_error_model_io_turns"] == 2
    assert summary["error_model_io_audit_required"] is True
    assert "post_agent_verifier_sandbox_error_zeroes" not in summary
    assert len(calls) == 1
    assert calls[0]["require_reasoning"] is True
    assert calls[0]["require_model_io"] is True
    assert calls[0]["require_request_graph_match"] is True
    assert calls[0]["require_exact_provider_json"] is True
    assert calls[0]["require_clean_stop"] is False

    for traceback in (None, "trace"):
        row["errors"] = [
            {
                "type": "ProviderError",
                "message": "opaque failure",
                "traceback": traceback,
            }
        ]
        with pytest.raises(v4.V4RecoveryError, match="error_row_invalid"):
            v4._audit_supported_rows(
                v6.split.canonical_json(row),
                ("provider-error",),
                {"provider-error": "shared"},
                audit_error_model_io=True,
            )

    row["errors"] = [{"type": "SandboxError", "message": "opaque failure", "traceback": "trace"}]
    with pytest.raises(v4.V4RecoveryError, match="model_bearing_error_row_invalid"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("provider-error",),
            {"provider-error": "shared"},
            audit_error_model_io=True,
        )

    row["errors"] = [{"type": "HarnessError", "message": "opaque failure", "traceback": "trace"}]
    row["stop_condition"] = "agent_completed"
    with pytest.raises(v4.V4RecoveryError, match="error_row_invalid"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("provider-error",),
            {"provider-error": "shared"},
            audit_error_model_io=True,
        )

    row["errors"] = [
        {"type": "ProviderError", "message": "opaque failure"},
        {"type": "HarnessError", "message": "opaque failure", "traceback": "trace"},
    ]
    row["stop_condition"] = "error"
    with pytest.raises(v4.V4RecoveryError, match="error_row_invalid"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("provider-error",),
            {"provider-error": "shared"},
            audit_error_model_io=True,
        )


def test_v8_accepts_only_exact_post_agent_separate_verifier_sandbox_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _post_agent_verifier_sandbox_row()
    calls: list[dict] = []

    def audit(*_args, **kwargs):
        calls.append(kwargs)
        return ["trace_has_errors"]

    monkeypatch.setattr(v4.audit_traces, "_audit_trace", audit)
    summary, rows = v4._audit_supported_rows(
        v6.split.canonical_json(row),
        ("separate-verifier",),
        {"separate-verifier": "separate"},
        allow_nontrainable_scored_rows=True,
        audit_error_model_io=True,
        allow_post_agent_verifier_sandbox_errors=True,
        post_agent_verifier_attempts=3,
        sandoq_provisioning_attempts=9,
    )

    assert summary["execution_error_zeroes"] == 1
    assert summary["model_bearing_error_zeroes"] == 1
    assert summary["post_agent_verifier_sandbox_error_zeroes"] == 1
    assert summary["post_agent_verifier_sandbox_error_model_io_turns"] == 2
    assert len(summary["post_agent_verifier_sandbox_error_row_set_sha256"]) == 64
    assert summary["validated_error_model_io_turns"] == 2
    assert summary["provider_error_zeroes"] == 0
    assert len(calls) == 1
    assert calls[0]["require_clean_stop"] is False
    disposition = rows["separate-verifier"]["info"]["diagnostic_evaluation_disposition"]
    assert disposition == {
        "kind": "post-agent-verifier-error-counted-as-zero",
        "phase": "separate-verifier",
        "source_row_sha256": v4._sha256(v6.split.canonical_json(row)),
        "trainable": False,
        "zero_model": False,
    }
    assert rows["separate-verifier"]["rewards"] == {"solved": 0}


def test_v8_post_agent_verifier_sandbox_error_contract_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v4.audit_traces,
        "_audit_trace",
        lambda *_args, **_kwargs: ["trace_has_errors"],
    )
    base = _post_agent_verifier_sandbox_row()
    invalid: list[tuple[dict, str, int | None]] = []

    shared = copy.deepcopy(base)
    invalid.append((shared, "shared", 3))
    wrong_stop = copy.deepcopy(base)
    wrong_stop["stop_condition"] = "error"
    invalid.append((wrong_stop, "separate", 3))
    missing_artifacts = copy.deepcopy(base)
    missing_artifacts["info"] = {}
    invalid.append((missing_artifacts, "separate", 3))
    verifier_present = copy.deepcopy(base)
    verifier_present["info"]["terminal_bench_verifier"] = {"mode": "separate"}
    invalid.append((verifier_present, "separate", 3))
    rewarded = copy.deepcopy(base)
    rewarded["rewards"] = {"solved": 0}
    invalid.append((rewarded, "separate", 3))
    metered = copy.deepcopy(base)
    metered["metrics"] = {"loss": 0}
    invalid.append((metered, "separate", 3))
    zero_model = copy.deepcopy(base)
    zero_model["nodes"] = []
    invalid.append((zero_model, "separate", 3))
    duplicate_error = copy.deepcopy(base)
    duplicate_error["errors"].append(copy.deepcopy(duplicate_error["errors"][0]))
    invalid.append((duplicate_error, "separate", 3))
    wrong_message = copy.deepcopy(base)
    wrong_message["errors"][0]["message"] = "opaque sandbox error"
    invalid.append((wrong_message, "separate", 3))
    wrong_nested_attempts = copy.deepcopy(base)
    wrong_nested_attempts["errors"][0]["message"] = wrong_nested_attempts["errors"][0]["message"].replace(
        "9 attempts", "8 attempts"
    )
    invalid.append((wrong_nested_attempts, "separate", 3))
    missing_attempt = copy.deepcopy(base)
    missing_attempt["errors"][0]["message"] = (
        "terminal-bench/separate-verifier: verifier VMVM failed after 3 attempts: "
        "attempt 1: unavailable; attempt 3: unavailable"
    )
    invalid.append((missing_attempt, "separate", 3))
    blank_traceback = copy.deepcopy(base)
    blank_traceback["errors"][0]["traceback"] = ""
    invalid.append((blank_traceback, "separate", 3))
    wrong_frame = copy.deepcopy(base)
    wrong_frame["errors"][0]["traceback"] = "Traceback: raise SandboxError"
    invalid.append((wrong_frame, "separate", 3))
    malformed_artifact = copy.deepcopy(base)
    malformed_artifact["info"]["terminal_bench_artifacts"]["sha256"] = "a" * 40
    invalid.append((malformed_artifact, "separate", 3))
    wrong_attempts = copy.deepcopy(base)
    invalid.append((wrong_attempts, "separate", 2))

    for candidate, mode, attempts in invalid:
        with pytest.raises(v4.V4RecoveryError):
            v4._audit_supported_rows(
                v6.split.canonical_json(candidate),
                ("separate-verifier",),
                {"separate-verifier": mode},
                audit_error_model_io=True,
                allow_post_agent_verifier_sandbox_errors=True,
                post_agent_verifier_attempts=attempts,
                sandoq_provisioning_attempts=9,
            )

    with pytest.raises(v4.V4RecoveryError, match="post_agent_verifier_policy_invalid"):
        v4._audit_supported_rows(
            v6.split.canonical_json(base),
            ("separate-verifier",),
            {"separate-verifier": "separate"},
            audit_error_model_io=True,
            allow_post_agent_verifier_sandbox_errors=True,
            post_agent_verifier_attempts=None,
            sandoq_provisioning_attempts=9,
        )


def test_v8_pre_model_sandoq_provisioning_error_is_exact_and_nontrainable() -> None:
    row = _row("pre-model-provisioning")
    row["errors"] = [
        {
            "type": "SandboxError",
            "message": "Sandoq provisioning failed after 9 attempts",
            "traceback": (
                "Traceback (most recent call last):\n"
                '  File "verifiers/v1/runtimes/sandoq.py", line 1, in start\n'
                "    raise SandboxError(\n"
            ),
        }
    ]
    summary, rows = v4._audit_supported_rows(
        v6.split.canonical_json(row),
        ("pre-model-provisioning",),
        {"pre-model-provisioning": "shared"},
        audit_error_model_io=True,
        audit_pre_model_sandoq_provisioning_errors=True,
        sandoq_provisioning_attempts=9,
    )
    assert summary["pre_model_sandoq_provisioning_error_zeroes"] == 1
    assert len(summary["pre_model_sandoq_provisioning_error_row_set_sha256"]) == 64
    assert rows["pre-model-provisioning"]["info"]["diagnostic_evaluation_disposition"] == {
        "kind": "pre-model-sandoq-provisioning-error-counted-as-zero",
        "phase": "agent-runtime-provisioning",
        "source_row_sha256": v4._sha256(v6.split.canonical_json(row)),
        "trainable": False,
        "zero_model": True,
    }

    for mutation in (
        lambda value: value["errors"][0].update(message="Sandoq provisioning failed after 8 attempts"),
        lambda value: value["errors"][0].update(traceback="Traceback: raise SandboxError("),
        lambda value: value.update(info={"unexpected": True}),
        lambda value: value.update(nodes=[{"sampled": True}]),
    ):
        changed = copy.deepcopy(row)
        mutation(changed)
        with pytest.raises(v4.V4RecoveryError):
            v4._audit_supported_rows(
                v6.split.canonical_json(changed),
                ("pre-model-provisioning",),
                {"pre-model-provisioning": "shared"},
                audit_error_model_io=True,
                audit_pre_model_sandoq_provisioning_errors=True,
                sandoq_provisioning_attempts=9,
            )

    with pytest.raises(v4.V4RecoveryError, match="pre_model_sandoq_provisioning_policy_invalid"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("pre-model-provisioning",),
            {"pre-model-provisioning": "shared"},
            audit_error_model_io=True,
            audit_pre_model_sandoq_provisioning_errors=True,
            sandoq_provisioning_attempts=None,
        )


def test_v8_post_agent_verifier_sandbox_error_requires_exact_trace_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _post_agent_verifier_sandbox_row()
    monkeypatch.setattr(
        v4.audit_traces,
        "_audit_trace",
        lambda *_args, **_kwargs: ["trace_has_errors", "node_2_reasoning_mismatch"],
    )
    with pytest.raises(v4.V4RecoveryError, match="error_row_model_io_audit_failed"):
        v4._audit_supported_rows(
            v6.split.canonical_json(row),
            ("separate-verifier",),
            {"separate-verifier": "separate"},
            audit_error_model_io=True,
            allow_post_agent_verifier_sandbox_errors=True,
            post_agent_verifier_attempts=3,
            sandoq_provisioning_attempts=9,
        )


def test_v6_trace_invalid_pass_is_retained_but_blocks_diagnostic_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "id": "trace-passing",
        "task": {"name": "terminal-bench/passing"},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "nodes": [{"sampled": True}],
        "rewards": {"solved": 1},
        "metrics": {},
        "info": {"terminal_bench_verifier": {"mode": "shared"}},
        "errors": [],
    }
    problems = ["node_7_request_graph_mismatch"]
    monkeypatch.setattr(v4.audit_traces, "_audit_trace", lambda *args, **kwargs: problems)
    summary, rows = v4._audit_supported_rows(
        v6.split.canonical_json(row),
        ("passing",),
        {"passing": "shared"},
        allow_nontrainable_scored_rows=True,
    )
    assert summary["passes"] == 1
    assert summary["trace_invalid_passing_rows"] == 1
    assert v6._gate_met({"passes": v6.TARGET_PASSES, "trace_invalid_passing_rows": 1}) is False
    assert v6._gate_met({"passes": v6.TARGET_PASSES, "trace_invalid_passing_rows": 0}) is True
    disposition = rows["passing"]["info"]["diagnostic_evaluation_disposition"]
    assert disposition["source_row_sha256"] == v4._sha256(v6.split.canonical_json(row))
    assert disposition["audit_problem_set_sha256"] == v4._sha256(v6.split.canonical_json(problems))
    assert disposition["trainable"] is False


def test_v6_buffered_proxy_audit_accepts_and_reports_legacy_records() -> None:
    first = _proxy_summary()
    second = _proxy_summary(requests=2, streamed_requests=2, replayed_requests=0)
    audit = v6._buffered_proxy_audit(_proxy_log(first, second), expected_schema="legacy")
    assert audit["source_schema"] == "legacy"
    assert audit["summary_records"] == 2
    assert audit["exact_once_counters_required"] is False
    assert audit["integer_totals"]["requests"] == 5
    assert audit["integer_totals"]["coalesced_requests"] == 0
    assert audit["integer_totals"]["replayed_requests"] == 1
    assert audit["mapping_totals"]["statuses"] == {"200": 4}
    assert len(audit["record_set_sha256"]) == 64


def test_v7_buffered_proxy_audit_enforces_exact_once_and_reports_replay() -> None:
    summary = _proxy_summary(
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
    )
    audit = v6._buffered_proxy_audit(
        _proxy_log(summary),
        expected_schema="logical-exact-once-v1",
    )
    assert audit["source_schema"] == "logical-exact-once-v1"
    assert audit["exact_once_counters_required"] is True
    assert audit["integer_totals"]["logical_requests"] == 2
    assert audit["integer_totals"]["logical_upstream_attempts"] == 2
    assert audit["integer_totals"]["anonymous_upstream_attempts"] == 0
    assert audit["integer_totals"]["replayed_requests"] == 1
    assert audit["terminal_outcomes"] == {
        "failure_records": 0,
        "non_2xx_upstream_responses": 0,
        "exception_records": 0,
        "exception_observations": 0,
    }


def test_v7_buffered_proxy_audit_and_trace_binding_count_one_typed_terminal() -> None:
    summary = _proxy_summary(
        requests=2,
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
        replayed_requests=0,
        streamed_requests=2,
        statuses={"200": 1, "503": 1},
        protocols={"chat_completions": 2},
        path_counts={
            "/muse-code/models": 1,
            "/v1/chat/completions": 2,
            "/v1/responses": 0,
        },
    )
    audit = v6._buffered_proxy_audit(
        _proxy_log(summary),
        expected_schema="logical-exact-once-v1",
    )
    bound = v6._exact_proxy_trace_binding(
        audit,
        {
            "clean_model_io_turns": 1,
            "source_model_io_turns": 1,
            "validated_error_model_io_turns": 0,
            "error_model_io_audit_required": True,
            "execution_error_zeroes": 1,
        },
        expected_summary_records=1,
    )

    assert bound["terminal_outcomes"] == {
        "failure_records": 1,
        "non_2xx_upstream_responses": 1,
        "exception_records": 0,
        "exception_observations": 0,
    }
    assert bound["trace_binding"] == {
        "source_model_io_turns": 1,
        "validated_model_io_turns": 1,
        "logical_requests": 2,
        "terminal_attempt_gap": 1,
        "maximum_terminal_gap": 1,
        "gap_bound": "typed-error-rows-with-terminal-proxy-outcome",
    }
    with pytest.raises(v6.V6SupersessionError, match="buffered_proxy_trace_binding_invalid"):
        v6._exact_proxy_trace_binding(
            audit,
            {
                "clean_model_io_turns": 1,
                "source_model_io_turns": 1,
                "validated_error_model_io_turns": 0,
                "error_model_io_audit_required": True,
                "execution_error_zeroes": 1,
            },
            expected_summary_records=2,
        )

    router = {
        "chat_requests": 2,
        "upstream_failures": 0,
        "upstream_http_429": 0,
        "upstream_http_5xx": 1,
    }
    trace = {
        "provider_error_zeroes": 1,
    }
    router_binding = v6._exact_router_proxy_binding(
        v6.split.canonical_json(router),
        bound,
        trace,
    )
    assert router_binding["router_chat_requests"] == 2
    assert router_binding["proxy_non_2xx_upstream_responses"] == 1
    assert router_binding["provider_error_rows"] == 1

    router["chat_requests"] = 1
    with pytest.raises(v6.V6SupersessionError, match="router_transport_binding_invalid"):
        v6._exact_router_proxy_binding(
            v6.split.canonical_json(router),
            bound,
            trace,
        )


def test_v7_proxy_binding_counts_trace_invalid_scored_turn_as_persisted() -> None:
    summary = _proxy_summary(
        requests=2,
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
        replayed_requests=0,
        streamed_requests=2,
        protocols={"chat_completions": 2},
        path_counts={
            "/muse-code/models": 1,
            "/v1/chat/completions": 2,
            "/v1/responses": 0,
        },
    )
    audit = v6._buffered_proxy_audit(
        _proxy_log(summary),
        expected_schema="logical-exact-once-v1",
    )
    bound = v6._exact_proxy_trace_binding(
        audit,
        {
            "clean_model_io_turns": 1,
            "source_model_io_turns": 2,
            "validated_error_model_io_turns": 0,
            "error_model_io_audit_required": True,
            "execution_error_zeroes": 0,
        },
        expected_summary_records=1,
    )

    assert bound["trace_binding"]["source_model_io_turns"] == 2
    assert bound["trace_binding"]["validated_model_io_turns"] == 1
    assert bound["trace_binding"]["terminal_attempt_gap"] == 0


def test_v7_buffered_proxy_directory_is_canonical_private_and_complete(tmp_path) -> None:
    tmp_path.chmod(0o700)
    directory = tmp_path / "buffered-proxy-stats"
    directory.mkdir(mode=0o700)
    summary = _proxy_summary(
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
    )
    for index in range(2):
        path = directory / f"summary-{index:032x}.json"
        path.write_bytes(
            v6.split.canonical_json(
                {
                    "schema_version": 1,
                    "kind": "sandoq-buffered-model-proxy-summary",
                    "counters": summary,
                }
            )
        )
        path.chmod(0o600)
    held = v6.split._HeldArtifactSet.create()
    try:
        audit, artifacts = v6._buffered_proxy_directory_audit(
            directory,
            expected_records=2,
            expected_schema="logical-exact-once-v1",
            held=held,
        )
        assert audit["summary_records"] == 2
        assert len(artifacts) == 2
        held.revalidate()
        with pytest.raises(
            v6.V6SupersessionError,
            match="buffered_proxy_directory_invalid",
        ):
            v6._buffered_proxy_directory_audit(
                directory,
                expected_records=1,
                expected_schema="logical-exact-once-v1",
                held=held,
            )
    finally:
        held.close()


@pytest.mark.parametrize(
    ("updates",),
    [
        ({"logical_requests": 2, "logical_upstream_attempts": 1},),
        ({"anonymous_upstream_attempts": 1},),
        ({"conflicting_requests": 1},),
        ({"expired_logical_retries": 1},),
        ({"requests": 4},),
        ({"streamed_requests": 2},),
        ({"statuses": {"200": 1}},),
        ({"protocols": {"chat_completions": 2}},),
        (
            {
                "path_counts": {
                    "/muse-code/models": 1,
                    "/v1/chat/completions": 2,
                    "/v1/responses": 0,
                }
            },
        ),
        ({"unknown_path_requests": 1},),
    ],
)
def test_v7_buffered_proxy_audit_rejects_exact_once_counter_violation(updates: dict) -> None:
    summary = _proxy_summary(
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
    )
    summary.update(updates)
    with pytest.raises(v6.V6SupersessionError, match="buffered_proxy_exact_once_invalid"):
        v6._buffered_proxy_audit(
            _proxy_log(summary),
            expected_schema="logical-exact-once-v1",
        )


def test_buffered_proxy_audit_rejects_partial_or_wrong_schema() -> None:
    partial = _proxy_summary(logical_requests=2)
    with pytest.raises(v6.V6SupersessionError, match="buffered_proxy_audit_invalid"):
        v6._buffered_proxy_audit(
            _proxy_log(partial),
            expected_schema="logical-exact-once-v1",
        )
    exact = _proxy_summary(
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
    )
    with pytest.raises(v6.V6SupersessionError, match="buffered_proxy_audit_invalid"):
        v6._buffered_proxy_audit(_proxy_log(exact), expected_schema="legacy")


@pytest.mark.parametrize(
    "updates",
    [
        {"statuses": {"503": 2}},
        {"statuses": {"503": 1}, "error_count": 1},
        {"statuses": {"200": 1, "400": 1}},
    ],
)
def test_v7_buffered_proxy_audit_rejects_ambiguous_terminal_outcome(updates) -> None:
    summary = _proxy_summary(
        requests=2,
        logical_requests=2,
        logical_upstream_attempts=2,
        anonymous_upstream_attempts=0,
        expired_logical_retries=0,
        replayed_requests=0,
        streamed_requests=2,
        protocols={"chat_completions": 2},
        path_counts={
            "/muse-code/models": 1,
            "/v1/chat/completions": 2,
            "/v1/responses": 0,
        },
    )
    summary.update(updates)
    with pytest.raises(
        v6.V6SupersessionError,
        match="buffered_proxy_terminal_outcome_invalid",
    ):
        v6._buffered_proxy_audit(
            _proxy_log(summary),
            expected_schema="logical-exact-once-v1",
        )
